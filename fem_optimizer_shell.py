import os
import json
import time
import copy
import math

# Importy silników Shell
from engine_geometry_shell import GeometryGeneratorShell
from engine_fem_shell import FemEngineShell

class FemOptimizerShell:
    """
    Optymalizator Shell.
    Zarządza badaniem zbieżności i uruchamianiem serii obliczeń.
    """
    def __init__(self, work_dir, logger_callback=None):
        self.work_dir = work_dir
        self.logger = logger_callback
        self.geo_engine = GeometryGeneratorShell(logger_callback)
        self.fem_engine = FemEngineShell(ccx_path="ccx") 

    def log(self, msg):
        if self.logger: self.logger(f"[OPT-SHELL] {msg}")
        else: print(f"[OPT-SHELL] {msg}")

    def find_optimal_mesh_settings(self, candidate, load_conditions, constraints):
        """
        Przeprowadza badanie zbieżności (Convergence Study).
        Parametry sterujące pobierane są z 'constraints' (ustawienia użytkownika).
        """
        self.log(f"--- START KALIBRACJI SIATKI: {candidate.get('Name', 'Unknown')} ---")
        
        # 1. Pobranie parametrów użytkownika (z wartościami domyślnymi)
        start_lc = float(constraints.get("mesh_start", 20.0))       # Startowy rozmiar elementu [mm]
        mesh_factor = float(constraints.get("mesh_factor", 0.7))    # Współczynnik zagęszczania (0.1 - 0.9)
        max_iter = int(constraints.get("max_iter", 5))              # Max liczba iteracji
        target_tol = float(constraints.get("conv_tol", 0.01))       # Tolerancja zbieżności (0.01 = 1%)
        min_lc_limit = 1.0                                          # Sztywne zabezpieczenie przed zbyt gęstą siatką

        current_lc = start_lc
        prev_vm = None
        optimal_lc = current_lc
        is_converged = False
        
        self.log(f"Parametry: Start={start_lc}mm, Factor={mesh_factor}, MaxIter={max_iter}, Tol={target_tol*100}%")

        for step in range(1, max_iter + 1):
            # Przygotowanie parametrów symulacji testowej
            run_params = self._prepare_run_params(candidate, load_conditions, current_lc)
            # Folder tymczasowy dla iteracji
            run_params["output_dir"] = os.path.join(self.work_dir, "_convergence_temp")
            
            # Uruchomienie symulacji
            res = self._run_single_sim(run_params)
            
            # Obsługa błędu solvera/geometrii
            if not res or not res.get("converged"):
                self.log(f"  Krok {step}: Błąd obliczeń dla siatki {current_lc:.2f}mm. Próba zagęszczenia.")
                current_lc *= mesh_factor
                continue
            
            curr_vm = res.get("MODEL_MAX_VM", 0.0)
            self.log(f"  Krok {step}: Mesh={current_lc:.2f}mm -> Max VM={curr_vm:.2f} MPa")
            
            # Sprawdzenie kryterium zbieżności
            if prev_vm is not None:
                # Obliczenie różnicy procentowej
                diff = abs(curr_vm - prev_vm) / max(prev_vm, 1e-6)
                self.log(f"     -> Delta: {diff*100:.2f}% (Cel: <{target_tol*100:.2f}%)")
                
                if diff < target_tol:
                    self.log("     -> ZBIEŻNOŚĆ OSIĄGNIĘTA.")
                    optimal_lc = current_lc
                    is_converged = True
                    break
            
            # Przygotowanie do kolejnego kroku
            prev_vm = curr_vm
            optimal_lc = current_lc # Zapamiętujemy bieżącą jako najlepszą dostępną
            
            current_lc *= mesh_factor
            
            # Zabezpieczenie przed zbyt małym elementem
            if current_lc < min_lc_limit:
                self.log("     -> Osiągnięto limit minimalnej wielkości elementu.")
                break
        
        if not is_converged:
            self.log(f"(!) Nie osiągnięto pełnej zbieżności w {max_iter} krokach. Użyto ostatniej siatki.")

        return {
            "global": optimal_lc, 
            "order": 2, 
            "converged_status": is_converged
        }

    def run_batch(self, candidates, load_conditions, mesh_settings=None):
        """
        Uruchamia serię obliczeń.
        Decyduje czy użyć "fixed" settings, czy przeprowadzić kalibrację.
        """
        final_results = {}
        
        # Domyślne flagi
        convergence_reached = False
        
        # 1. Konfiguracja siatki (Automatyczna vs Ręczna)
        if not mesh_settings or not mesh_settings.get("fixed", False):
            # Tryb AUTO: Kalibracja na pierwszym kandydacie
            if candidates:
                # Przekazujemy mesh_settings jako constraints dla funkcji kalibrującej
                opt_params = self.find_optimal_mesh_settings(candidates[0], load_conditions, mesh_settings or {})
                
                mesh_config = {
                    "global": opt_params["global"], 
                    "order": opt_params["order"]
                }
                convergence_reached = opt_params["converged_status"]
                
                self.log(f"Wybrano siatkę z kalibracji: {mesh_config['global']:.2f} mm")
            else:
                mesh_config = {"global": 10.0, "order": 2}
        else:
            # Tryb FIXED: Użytkownik wymusił konkretny rozmiar
            mesh_config = {
                "global": float(mesh_settings.get("global", 10.0)),
                "order": int(mesh_settings.get("order", 2))
            }
            convergence_reached = True # Zakładamy, że user wie co robi

        # 2. Pętla Batch (Dla wszystkich kandydatów)
        for i, cand in enumerate(candidates):
            name = cand.get("Name", f"Shell_{i}")
            self.log(f"Przetwarzanie [{i+1}/{len(candidates)}]: {name}")
            
            params = self._prepare_run_params(cand, load_conditions, mesh_config["global"])
            params["output_dir"] = os.path.join(self.work_dir, name)
            params["model_name"] = name
            
            res = self._run_single_sim(params)
            
            if res:
                # Dodajemy informację o statusie zbieżności do wyniku
                res["convergence_status"] = "YES" if (res["converged"] and convergence_reached) else "NO"
                res["mesh_used"] = mesh_config["global"]
                
                self._save_results(params["output_dir"], res, cand)
                final_results[name] = res
            else:
                self.log(f"Błąd obliczeń dla {name}")
                
        return final_results

    def _prepare_run_params(self, cand, loads, lc):
        # 1. Pobieramy wymiary geometryczne
        # 2. Pozycjonowanie
        y_centroid_global = float(cand.get("Res_Geo_Yc", 0.0))
        y_load_level = float(loads.get("Y_load_level", cand.get("Input_Load_F_promien", 0.0)))
        
        return {
            "model_name": cand.get("Name", "unknown"),
            "length": float(cand.get("Input_Length", 1000.0)),
            "profile_data": {
                "hc": float(cand.get("Geom_h_c", 100)),
                "bc": float(cand.get("Geom_b_c", 50)),
                "twc": float(cand.get("Geom_t_w", 5)),
                "tfc": float(cand.get("Geom_t_f", 8)),
                "rc": float(cand.get("Geom_r_c", 0))
            },
            "plate_data": {
                "tp": float(cand.get("Geom_t_p", 10)),
                "bp": float(cand.get("Geom_b_p", 200))
            },
            "mesh_size": {"global": lc, "order": 2},
            "Stop": cand.get("Mat_Name", "S355"),
            
            # Pozycje węzłów
            "Y_structure_center": y_centroid_global,
            "Y_load_level": y_load_level,
            
            # Obciążenia
            "Fx": float(loads.get("Fx", 0)),
            "Fy": float(loads.get("Fy", 0)),
            "Fz": float(loads.get("Fz", 0)),
            "Mx": float(loads.get("Mx", 0)),
            "My": float(loads.get("My", 0)),
            "Mz": float(loads.get("Mz", 0)),
            
            "system_resources": {"num_threads": 4}
        }

    def _run_single_sim(self, params):
        geo_res = self.geo_engine.generate_model(params)
        if not geo_res: return None
        
        inp_path = geo_res["paths"]["inp"]
        run_inp = self.fem_engine.prepare_calculix_deck(inp_path, params)
        if not run_inp: return None
        
        wd = os.path.dirname(run_inp)
        ok = self.fem_engine.run_solver(run_inp, wd)
        if not ok: return None
        
        dat_path = run_inp.replace(".inp", ".dat")
        return self.fem_engine.parse_dat_results(dat_path)

    def _save_results(self, folder, fem_res, cand_data):
        if not os.path.exists(folder): os.makedirs(folder)
        
        # Oznaczamy typ analizy
        fem_res["analysis_type"] = "shell"
        
        with open(os.path.join(folder, "results.json"), 'w') as f:
            json.dump(fem_res, f, indent=4)
        with open(os.path.join(folder, "analytical.json"), 'w') as f:
            json.dump(cand_data, f, indent=4)