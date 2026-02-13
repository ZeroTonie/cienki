import os
import json
import shutil
import multiprocessing
import traceback
import math
import engine_geometry
import engine_fem

class FemOptimizer:
    def __init__(self, router_instance):
        self.router = router_instance
        ccx = self.router.get_ccx_path()
        self.fem_engine = engine_fem.FemEngine(ccx_path=ccx)
        self.stop_requested = False

    def _parse_gui_float(self, value_str):
        """Bezpiecznie konwertuje string z GUI na float, obsługując puste wartości."""
        if not value_str or not isinstance(value_str, str) or not value_str.strip():
            return 0.0
        try:
            return float(value_str)
        except (ValueError, TypeError):
            return 0.0

    def run_single_candidate(self, candidate_data, fem_settings, signal_callback=None):
        """Uruchamia proces optymalizacji (Mesh -> Solve -> Check -> MeshRefine) dla jednego profilu."""
        # Wrapper do logowania - wysyła sygnał do GUI lub drukuje w konsoli
        def log(msg): 
            if signal_callback: signal_callback(msg)
            else: print(msg)

        # Identyfikacja profilu (Nazwa + Grubość płaskownika)
        prof = candidate_data.get("Nazwa_Profilu", "Unknown")
        tp = float(candidate_data.get("Input_Geo_tp", 10))
        bp = float(candidate_data.get("Input_Geo_bp", 0))
        cid = f"{prof}_tp{int(tp)}_bp{int(bp)}"
        
        # Pobranie ustawień z GUI (z domyślnymi wartościami)
        max_iter = int(fem_settings.get("max_iterations", 3))
        tol = float(fem_settings.get("tolerance", 0.02))
        mesh_fact = float(fem_settings.get("refinement_factor", 0.7))
        curr_mesh = float(fem_settings.get("mesh_start_size", 15.0))
        
        # Pobranie limitu równań z ustawień (domyślnie 2 miliony)
        eq_limit = int(fem_settings.get("eq_limit", 2000000))

        # Parametry v3.0 (Strefy i Sondy)
        fem_loads_settings = fem_settings.get("fem_loads", {})
        ref_zones = fem_settings.get("refinement_zones", [])
        cust_probes = fem_settings.get("custom_probes", {})

        # [NOWOŚĆ] Dynamiczne wyznaczanie Y_ref dla tego kandydata
        yc_ref_mode = fem_loads_settings.get("yc_ref_mode", 1)
        yc_ref_manual_val_str = fem_loads_settings.get("yc_ref_manual_value", "0.0")
        if yc_ref_mode == 0: # Manual
            y_ref = self._parse_gui_float(yc_ref_manual_val_str)
        elif yc_ref_mode == 1: # Ramię (z analityki)
            y_ref = float(candidate_data.get("Input_Load_F_promien", 0.0))
        elif yc_ref_mode == 2: # Środek ciężkości (z analityki)
            y_ref = float(candidate_data.get("Res_Geo_Yc", 0.0))
        else: # Fallback
            y_ref = float(candidate_data.get("Input_Load_F_promien", 0.0))

        # Zasoby (Rdzenie)
        c_mesh = int(fem_settings.get("cores_mesh", 4))
        c_solv = int(fem_settings.get("cores_solver", 4))

        # --- LOGIKA STATUSU ZBIEŻNOŚCI ---
        is_batch = (max_iter == 1)
        # Jeśli to batch, a nie było wcześniej optymalizacji siatki, ustawiamy "NOT_DEFINED"
        converged = "NOT_DEFINED" if is_batch else False
        
        last_vm = 0.0
        final_path = ""
        final_res = {}

        # --- GŁÓWNA PĘTLA OPTYMALIZACJI SIATKI ---
        for i in range(1, max_iter + 1):
            if self.stop_requested: 
                log("  ! Przerwano na żądanie użytkownika. ||| [Status: Przerwano]")
                break
            
            iter_name = f"Iter_{i}_Mesh{curr_mesh:.1f}"
            work_dir = self.router.get_path("MES_WORK", iter_name, subdir=cid)
            
            # --- [FIX] Upewnij się, że folder istnieje PRZED zapisem JSON ---
            if not os.path.exists(work_dir):
                try: os.makedirs(work_dir, exist_ok=True)
                except: pass

            # === [NOWOŚĆ] Zapis danych analitycznych do folderu roboczego ===
            try:
                with open(os.path.join(work_dir, "analytical.json"), 'w') as f:
                    json.dump(candidate_data, f, indent=4)
            except Exception as e:
                log(f"  ! Ostrzeżenie: Nie udało się zapisać analytical.json: {e}")
            # ================================================================

            # [STATUS LIVE] Natychmiastowa informacja o starcie iteracji
            log(f"> Iteracja {i} (Siatka {curr_mesh:.1f}mm)... ||| [Status: Start Iteracji {i} (Siatka {curr_mesh:.1f}mm)]")
            
            # --- 1. GEOMETRIA ---
            log(f"Generowanie geometrii... ||| [Status: Generowanie Siatki (Gmsh)...]")
            
            g_params = {
                "output_dir": work_dir,
                "model_name": f"Model_I{i}",
                "length": float(candidate_data.get("Input_Load_L", 1500)),
                "profile_data": {
                    "hc": float(candidate_data.get("Input_UPE_hc", 200)),
                    "bc": float(candidate_data.get("Input_UPE_bc", 80)),
                    "twc": float(candidate_data.get("Input_UPE_twc", 6)),
                    "tfc": float(candidate_data.get("Input_UPE_tfc", 11)),
                    "rc": float(candidate_data.get("Input_UPE_rc", 10))
                },
                "plate_data": {
                    "tp": tp, 
                    "bp": float(candidate_data.get("Input_Geo_bp", 300))
                },
                "mesh_size": {
                    "global": curr_mesh, 
                    "fillet": max(1.0, curr_mesh * 0.4), 
                    "order": int(fem_settings.get("mesh_order", 1))
                },
                "mesh_quality": {"algorithm_3d": 1},
                "system_resources": {"num_threads": c_mesh},
                "refinement_zones": ref_zones
            }
            
            # Generowanie modelu
            try:
                gen = engine_geometry.GeometryGenerator(logger_callback=log)
                meta = gen.generate_model(g_params)
            except Exception as e:
                log(f"  ! Wyjątek w generatorze geometrii: {e}")
                meta = None
            
            if not meta:
                log("  ! Błąd generowania geometrii/siatki. Przerywam profil.")
                break

            # >>> ZMIANA: Sprawdzanie limitu równań i ostrzeżenie <<<
            node_count = meta.get('stats', {}).get('nodes', 0)
            est_equations = node_count * 3 # 3 stopnie swobody na węzeł
            
            log(f"||| [Węzły Siatki: {node_count:,}]".replace(',', ' '))
            log(f"||| [Układ Równań: ~{est_equations / 1e6:.2f} M]")

            if est_equations > eq_limit:
                log(f"  ! UWAGA: Przekroczono limit {eq_limit/1e6:.1f}M równań. Model ma ~{est_equations/1e6:.1f}M równań.")
                log(f"  ! ZAGĘŚĆ SIATKĘ: Ryzyko błędu krytycznego z powodu braku pamięci RAM.")

            # Wybór solvera do tego przebiegu
            current_solver_type = fem_settings.get("solver_type", "DIRECT")
            
            # --- 2. FEM SOLVER (FIZYKA & MATERIAŁ) ---
            
            # --- [NOWOŚĆ] Przetwarzanie obciążeń z GUI ---
            loads_ctx = {
                "L": float(candidate_data.get("Input_Load_L", 1500)),
                "Yc": float(candidate_data.get("Res_Geo_Yc", 0.0)),
                "Ys": float(candidate_data.get("Res_Geo_Ys", 0.0)),
                "math": math,
                "Y_ref": y_ref # Używamy dynamicznie wyliczonej wartości
            }

            # --- [POPRAWKA] Logika pobierania sił z uwzględnieniem checkboxów "Z analityki" ---
            fx_settings = fem_loads_settings.get("fx", {})
            if fx_settings.get("use_ana", True):
                fx_val = -float(candidate_data.get("Input_Load_Fx", 0.0))
            else:
                fx_val = self._parse_gui_float(fx_settings.get("value", "0.0"))
            loads_ctx["Fx"] = fx_val

            fy_settings = fem_loads_settings.get("fy", {})
            if fy_settings.get("use_ana", True):
                fy_val = float(candidate_data.get("Res_Force_Fy_Ed", 0.0))
            else:
                fy_val = self._parse_gui_float(fy_settings.get("value", "0.0"))
            loads_ctx["Fy"] = fy_val

            fz_settings = fem_loads_settings.get("fz", {})
            if fz_settings.get("use_ana", True):
                fz_val = float(candidate_data.get("Res_Force_Fz_Ed", 0.0))
            else:
                fz_val = self._parse_gui_float(fz_settings.get("value", "0.0"))
            loads_ctx["Fz"] = fz_val

            # Momenty (eval)
            def eval_expr(expr, context):
                """Bezpiecznie ewaluuje wyrażenie matematyczne."""
                if not expr or not str(expr).strip():
                    return 0.0
                try:
                    return float(eval(str(expr), {"__builtins__": None}, context))
                except Exception as e:
                    log(f"  ! Błąd ewaluacji wyrażenia '{expr}': {e}")
                    return 0.0

            mx_val = eval_expr(fem_loads_settings.get("mx_expr"), loads_ctx)
            my_val = eval_expr(fem_loads_settings.get("my_expr"), loads_ctx)
            mz_val = eval_expr(fem_loads_settings.get("mz_expr"), loads_ctx)

            log(f"   [FIZYKA] Obciążenia FEM: Y_ref={y_ref:.2f}, Fx={fx_val:.1f}, Fy={fy_val:.1f}, Fz={fz_val:.1f}")
            log(f"   [FIZYKA] Momenty FEM: Mx={mx_val:.1f}, My={my_val:.1f}, Mz={mz_val:.1f}")

            try:
                e_mod = float(candidate_data["Input_Load_E"])
                g_mod = float(candidate_data["Input_Load_G"])
            except KeyError as e:
                raise ValueError(f"Brak kluczowych danych materiałowych w kandydacie: {e}")

            if g_mod > 1.0 and e_mod > 1.0:
                nu_val = (e_mod / (2.0 * g_mod)) - 1.0
                if not (0.0 < nu_val < 0.5):
                    raise ValueError(f"Wyliczony wsp. Poissona ({nu_val:.3f}) jest nieprawidłowy.")
            else:
                raise ValueError(f"Wartości E ({e_mod}) lub G ({g_mod}) są nieprawidłowe.")

            run_p = {
                "E": e_mod,
                "nu": nu_val,
                "Fx": fx_val,
                "Fy": fy_val,
                "Fz": fz_val,
                "Mx": mx_val,
                "My": my_val,
                "Mz": mz_val,
                "Length": g_params["length"],
                "Y_ref_node": y_ref,
                "profile_data": g_params["profile_data"],
                "plate_data": g_params["plate_data"],
                "custom_probes": cust_probes,
                "step": float(fem_settings.get("step", 50.0)),
                "solver_type": current_solver_type
            }
            
            inp_file = meta['paths']['inp']
            run_inp = self.fem_engine.prepare_calculix_deck(inp_file, run_p)
            
            if not run_inp:
                log("  ! Błąd przygotowania decku CCX.")
                break
            
            log(f"  > Uruchamianie Solvera ({current_solver_type})... ||| [Status: Start Solvera ({current_solver_type})...]")
            
            # Uruchomienie Solvera
            solver_success = self.fem_engine.run_solver(
                run_inp, 
                work_dir, 
                num_threads=c_solv, 
                callback=log
            )
            
            if not solver_success:
                log("  ! Błąd wykonania solvera. ||| [Status: Błąd Solvera]")
                break
            
            log("  > Przetwarzanie wyników... ||| [Status: Analiza wyników (.dat)]")
            
            # --- 3. WYNIKI I ZBIEŻNOŚĆ ---
            dat_file = run_inp.replace(".inp", ".dat")
            res = self.fem_engine.parse_dat_results(dat_file)
            
            vm = res.get("MODEL_MAX_VM", 0.0)
            buckling = res.get("BUCKLING_FACTORS", [])
            
            log(f"  Max VM: {vm:.2f} MPa")
            if buckling:
                log(f"  Buckling Factors: {buckling}")
            
            if "INTERFACE_MAX_SHEAR" in res:
                tau_max = res["INTERFACE_MAX_SHEAR"]
                log(f"  Max Shear Interface: {tau_max:.2f} MPa")

            # --- ZAPIS WYNIKÓW ---
            res["id"] = cid
            res["mesh_path"] = os.path.join(work_dir, f"Model_I{i}.msh")
            res['converged'] = converged 
            
            try:
                with open(os.path.join(work_dir, "results.json"), 'w') as f:
                    json.dump(res, f, indent=4)
            except Exception as e:
                log(f"  ! Błąd zapisu JSON wyników roboczych: {e}")

            # Sprawdzenie zbieżności (Tylko jeśli NIE jesteśmy w trybie Batch)
            if not is_batch and i > 1:
                if last_vm > 1e-6:
                    delta = abs(vm - last_vm) / last_vm
                else:
                    delta = 1.0
                    
                log(f"  Delta: {delta*100:.2f}% (Tol: {tol*100}%)")
                
                if delta < tol:
                    converged = True
                    res['converged'] = True
                    try:
                        with open(os.path.join(work_dir, "results.json"), 'w') as f:
                            json.dump(res, f, indent=4)
                    except: pass
                    final_res = res
                    log("  >>> ZBIEŻNOŚĆ OSIĄGNIĘTA.")
                    final_path = work_dir 
                    break
            
            last_vm = vm
            final_res = res
            final_path = work_dir 
            
            curr_mesh *= mesh_fact
            if curr_mesh < 1.0: curr_mesh = 1.0

        # --- FINALIZACJA KANDYDATA ---
        final_dest = self.router.get_path("FINAL", "", subdir=cid)
        
        if os.path.exists(final_dest): 
            try: shutil.rmtree(final_dest)
            except: pass
        
        if final_path and os.path.exists(final_path):
            try: 
                shutil.copytree(final_path, final_dest)
                log(f"  > Wyniki zarchiwizowane w: {final_dest}")
            except Exception as e: 
                log(f"  ! Błąd kopiowania do FINAL: {e}")
        
        final_res["id"] = cid
        final_res["converged"] = converged
        final_res["iterations"] = i 
        final_res["final_stress"] = last_vm
        final_res["final_mesh_size"] = curr_mesh
        
        return final_res