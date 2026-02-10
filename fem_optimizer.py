import os
import json
import shutil
import multiprocessing
import engine_geometry
import engine_fem

class FemOptimizer:
    def __init__(self, router_instance):
        self.router = router_instance
        ccx = "ccx"
        if hasattr(self.router, 'get_ccx_path'):
            ccx = self.router.get_ccx_path()
        self.fem_engine = engine_fem.FemEngine(ccx_path=ccx)
        self.stop_requested = False

    def run_single_candidate(self, candidate_data, fem_settings, signal_callback=None):
        """
        Uruchamia proces optymalizacji (Mesh -> Solve -> Check -> MeshRefine) dla jednego profilu.
        """
        def log(msg): 
            if signal_callback: signal_callback(msg)
            else: print(msg)

        # Identyfikacja profilu
        prof = candidate_data.get("Nazwa_Profilu", "Unknown")
        tp = float(candidate_data.get("Input_Geo_tp", 10))
        cid = f"{prof}_tp{int(tp)}"
        
        # Pobranie ustawień z GUI
        max_iter = int(fem_settings.get("max_iterations", 3))
        tol = float(fem_settings.get("tolerance", 0.02))
        mesh_fact = float(fem_settings.get("refinement_factor", 0.7))
        curr_mesh = float(fem_settings.get("mesh_start_size", 15.0))
        
        # Nowe parametry v3.0 (Strefy i Sondy)
        ref_zones = fem_settings.get("refinement_zones", [])
        cust_probes = fem_settings.get("custom_probes", {})
        
        # Zasoby
        c_mesh = int(fem_settings.get("cores_mesh", 4))
        c_solv = int(fem_settings.get("cores_solver", 4))

        converged = False
        last_vm = 0.0
        final_path = ""
        final_res = {}

        for i in range(1, max_iter + 1):
            if self.stop_requested: break
            
            iter_name = f"Iter_{i}_Mesh{curr_mesh:.1f}"
            work_dir = self.router.get_path("MES_WORK", iter_name, subdir=cid)
            
            log(f"> Iteracja {i} (Siatka {curr_mesh:.1f}mm)...")
            
            # --- 1. GEOMETRIA ---
            # Budujemy parametry dla engine_geometry
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
                    # Safety fuse: fillet nie mniejszy niż 1.0, ale skaluje się z global
                    "fillet": max(1.0, curr_mesh * 0.4), 
                    "order": int(fem_settings.get("mesh_order", 1))
                },
                "mesh_quality": {"algorithm_3d": 1},
                "system_resources": {"num_threads": c_mesh},
                "refinement_zones": ref_zones # Przekazanie stref!
            }
            
            gen = engine_geometry.GeometryGenerator(logger_callback=log)
            meta = gen.generate_model(g_params)
            
            if not meta:
                log("  ! Błąd generowania geometrii/siatki.")
                break
            
            # --- 2. FEM SOLVER ---
            run_p = {
                "E": 210000,
                "Fx": candidate_data.get("Input_Load_Fx", 1000),
                "Length": g_params["length"],
                "SC_Y": float(candidate_data.get("Res_Geo_Ys", 0)), # Środek ścinania
                "profile_data": g_params["profile_data"],
                "plate_data": g_params["plate_data"],
                "custom_probes": cust_probes, # Przekazanie sond!
                "step": 50.0
            }
            
            inp_file = meta['paths']['inp']
            run_inp = self.fem_engine.prepare_calculix_deck(inp_file, run_p)
            
            if not run_inp:
                log("  ! Błąd przygotowania decku CCX.")
                break
            
            log("  > Obliczenia Solverem...")
            if not self.fem_engine.run_solver(run_inp, work_dir, num_threads=c_solv):
                log("  ! Błąd wykonania solvera.")
                break
            
            # --- 3. WYNIKI I ZBIEŻNOŚĆ ---
            dat_file = run_inp.replace(".inp", ".dat")
            res = self.fem_engine.parse_dat_results(dat_file)
            
            vm = res.get("MODEL_MAX_VM", 0.0)
            log(f"  Max VM: {vm:.2f} MPa")
            
            # Sprawdzenie zbieżności
            if i > 1:
                if last_vm > 1e-6:
                    delta = abs(vm - last_vm) / last_vm
                else:
                    delta = 1.0
                    
                log(f"  Delta: {delta*100:.2f}% (Tol: {tol*100}%)")
                
                if delta < tol:
                    converged = True
                    final_path = work_dir
                    
                    # Zapisujemy json z wynikami
                    try:
                        with open(os.path.join(work_dir, "results.json"), 'w') as f:
                            json.dump(res, f, indent=4)
                    except: pass
                    
                    # Dodajemy ścieżkę do msh do podglądu w GUI
                    final_res = res
                    final_res['mesh_path'] = os.path.join(work_dir, f"Model_I{i}.msh")
                    log("  >>> ZBIEŻNOŚĆ OSIĄGNIĘTA.")
                    break
            
            last_vm = vm
            final_res = res
            final_res['mesh_path'] = os.path.join(work_dir, f"Model_I{i}.msh")
            final_path = work_dir
            
            # Przygotowanie kolejnej iteracji
            curr_mesh *= mesh_fact
            if curr_mesh < 1.0: curr_mesh = 1.0

        # Kopiowanie wyników finalnych do folderu FINAL
        final_dest = self.router.get_path("FINAL", "", subdir=cid)
        if os.path.exists(final_dest): shutil.rmtree(final_dest)
        if final_path:
            try: shutil.copytree(final_path, final_dest)
            except: pass
        
        final_res["id"] = cid
        final_res["converged"] = converged
        final_res["iterations"] = i
        final_res["final_stress"] = last_vm
        
        return final_res