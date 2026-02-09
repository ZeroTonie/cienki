import os
import json
import csv
import traceback
import math
from routing import router
from engine_geometry import GeometryGenerator
from engine_fem import CalculixDeckBuilder, CalculixRunner, ResultsParser

class FemSimulationManager:
    def __init__(self):
        self.geo = GeometryGenerator()
        self.builder = CalculixDeckBuilder()
        self.runner = CalculixRunner()
        self.parser = ResultsParser()
        self.stop_requested = False # Flaga do zatrzymywania z GUI
        
    def map_probes(self, nodes_csv, probe_defs, logger=print):
        nodes = []
        try:
            with open(nodes_csv, 'r') as f:
                r = csv.DictReader(f)
                for row in r:
                    nodes.append({
                        "id": int(row["NodeID"]),
                        "x": float(row["X"]), "y": float(row["Y"]), "z": float(row["Z"])
                    })
        except Exception as e: 
            logger(f"[PROBE ERROR] Nie można odczytać węzłów: {e}")
            return {}
        
        mapped = {}
        for p in probe_defs:
            L = float(p.get('L', 0))
            step = float(p.get('step', 50.0))
            if step <= 0.1: step = 50.0
            
            curr_x = 0.0
            p_y, p_z = float(p.get('y', 0)), float(p.get('z', 0))
            
            while curr_x <= L + 1.0: 
                candidates = [n for n in nodes if abs(n['x'] - curr_x) < 20.0]
                best, min_d2 = None, 1e9
                for n in candidates:
                    d2 = (n['x']-curr_x)**2 + (n['y']-p_y)**2 + (n['z']-p_z)**2
                    if d2 < min_d2: min_d2 = d2; best = n
                
                if best:
                    pname = f"{p['name_base']}_X{int(curr_x)}"
                    mapped[pname] = {
                        "id": best['id'],
                        "dx": best['x'] - curr_x, 
                        "dy": best['y'] - p_y, 
                        "dz": best['z'] - p_z,
                        "theory_x": curr_x
                    }
                curr_x += step
        return mapped

    def _estimate_resources(self, nodes_path, logger_callback):
        """Szacuje czas i RAM na podstawie liczby węzłów."""
        try:
            num_nodes = 0
            with open(nodes_path, 'r') as f:
                # Odejmujemy nagłówek, liczymy linie
                num_nodes = sum(1 for line in f) - 1
            
            if num_nodes <= 0: return
            
            # Heurystyki dla CalculiX (Spooles)
            # Równania (DOF)
            dof = num_nodes * 3
            
            # RAM: Zgrubnie 1.5 GB na 100k węzłów (dla elementów 2. rzędu może być więcej)
            # Używamy bezpieczniejszego mnożnika
            est_ram_gb = (num_nodes * 2.0) / 100000.0
            if est_ram_gb < 0.2: est_ram_gb = 0.2
            
            # Czas: Zależność nieliniowa. Przyjmijmy (Nodes/1000)^1.2 * k
            # k zależy od CPU, tu arbitralne 0.05s
            est_time_s = 0.02 * math.pow(num_nodes, 1.1)
            est_time_m = est_time_s / 60.0
            
            logger_callback(f"   [ESTYM] Węzłów: {num_nodes} | Równań: {dof}")
            logger_callback(f"   [ESTYM] Szacowany RAM: {est_ram_gb:.2f} GB")
            logger_callback(f"   [ESTYM] Szacowany Czas: {est_time_m:.1f} min")
            
        except Exception as e:
            logger_callback(f"   [ESTYM] Nie udało się oszacować zasobów: {e}")

    def run_simulation(self, config, logger_callback=print):
        self.stop_requested = False
        project_name = config.get("project_name", "FemProject")
        router.set_project(project_name)
        
        # Rozpakowanie konfiguracji
        m_params = config['mesh_params']
        max_iter = int(m_params.get('max_iterations', 3))
        tol = float(m_params.get('convergence_tol', 0.02))
        ref_factor = float(m_params.get('refinement_factor', 0.7))
        use_nlgeom = config.get('use_nlgeom', False)
        cores = int(config.get('cores_solver', 4))
        solver_type = config.get('solver_type', 'spooles')
        
        prev_vm = None
        converged = False
        final_res = {}
        probe_map = {} # Musi być w tym zakresie, żeby było dostępne dla analizy wyboczeniowej
        
        # --- PĘTLA ZBIEŻNOŚCI ---
        for i in range(1, max_iter + 1):
            if self.stop_requested:
                logger_callback("!!! PRZERWANO NA ŻĄDANIE UŻYTKOWNIKA !!!")
                return {"status": "stopped"}
                
            iter_name = f"Iteracja_{i}"
            logger_callback(f"\n--- START {iter_name} (NLGEOM={use_nlgeom}) ---")
            
            # W kolejnych iteracjach zagęszczamy siatkę
            if i > 1:
                m_params['mesh_size_global'] *= ref_factor
                logger_callback(f"   Nowy rozmiar siatki globalnej: {m_params['mesh_size_global']:.2f} mm")
                
            try:
                # --- 1. GEOMETRIA I SIATKA ---
                logger_callback("   Generowanie siatki...")
                self.geo.logger = logger_callback
                
                # Odbiór słownika ze ścieżkami
                paths_data = self.geo.generate_mesh(config, iter_name)
                mesh_path_inp = paths_data['inp']
                mesh_path_viz = paths_data['viz'] # Ścieżka do pliku VTK dla wizualizacji
                nodes_path = paths_data['nodes']
                group_nodes_map = paths_data['groups']
                
                # --- 2. SZACOWANIE ZASOBÓW ---
                self._estimate_resources(nodes_path, logger_callback)
                
                # --- 3. MAPOWANIE SOND ---
                probes_def = config.get('probes', [])
                for p in probes_def: p['L'] = config['geometry']['L']
                probe_map = self.map_probes(nodes_path, probes_def, logger_callback)
                
                # --- 4. TWORZENIE PLIKU WEJŚCIOWEGO (.inp) ---
                inp_path = self.builder.build_deck(
                    mesh_path_inp, config, probe_map, group_nodes_map, # Przekazujemy mapę grup
                    is_buckling=False, use_nlgeom=use_nlgeom
                )
                
                # --- 5. URUCHOMIENIE SOLVERA ---
                logger_callback(f"   Uruchamianie Solvera CCX ({cores} rdzeni)...")
                self.runner.run(inp_path, num_cores=cores, solver_type=solver_type) # Przekazanie typu solvera
                
                # --- 6. PARSOWANIE WYNIKÓW ---
                wdir = os.path.dirname(inp_path)
                job = os.path.splitext(os.path.basename(inp_path))[0]
                res = self.parser.parse(wdir, job, probe_map)
                
                # --- 7. LOGOWANIE I ZAPIS WYNIKÓW POŚREDNICH ---
                res['iteration'] = i
                res['converged_in_iter'] = False
                res['mesh_path'] = mesh_path_viz # Zapisujemy ścieżkę do VTK dla GUI
                res['mesh_size'] = m_params['mesh_size_global']
                res['group_nodes_map'] = group_nodes_map
                
                with open(router.get_path("FEM_WORK", "results.json", iter_name), 'w') as f:
                    json.dump(res, f, indent=4)
                    
                shear_msg = f", Shear_R={res.get('interface_shear_R',0):.2f}, Shear_L={res.get('interface_shear_L',0):.2f}"
                logger_callback(f"   Wynik Iteracji {i}: Max VM = {res['max_vm']:.2f}{shear_msg} MPa")
                
                final_res = res # Zawsze przechowuj ostatni poprawny wynik
                
                # --- 8. SPRAWDZENIE ZBIEŻNOŚCI ---
                if prev_vm is not None and prev_vm > 1e-6:
                    delta = abs(res['max_vm'] - prev_vm) / prev_vm
                    logger_callback(f"   Delta VM: {delta*100:.2f}% (Limit: {tol*100}%)")
                    
                    if delta < tol:
                        logger_callback(">>> ZBIEŻNOŚĆ OSIĄGNIĘTA <<<")
                        converged = True
                        final_res['converged_in_iter'] = True
                        break # Wyjdź z pętli zbieżności
                
                prev_vm = res['max_vm']
                
            except Exception as e:
                logger_callback(f"[STOP] Krytyczny błąd w iteracji {i}: {e}")
                logger_callback(traceback.format_exc())
                return {"status": "error", "message": str(e)}
        
        # --- ANALIZA WYBOCZENIOWA (jeśli osiągnięto zbieżność) ---
        if not converged:
            logger_callback("Ostrzeżenie: Nie osiągnięto pełnej zbieżności w zadanej liczbie iteracji.")
        elif final_res:
            try:
                logger_callback("\n--- Uruchamianie analizy wyboczeniowej (Buckling)... ---")
                buckling_group_nodes = final_res.get('group_nodes_map', {})
                inp_buck = self.builder.build_deck(final_res['mesh_path'], config, probe_map, buckling_group_nodes, is_buckling=True)
                self.runner.run(inp_buck, num_cores=cores, solver_type=solver_type) # Przekazanie typu solvera
                
                wdir = os.path.dirname(inp_buck)
                job = os.path.splitext(os.path.basename(inp_buck))[0]
                res_buck = self.parser.parse(wdir, job, probe_map)
                
                final_res['buckling_factors'] = res_buck.get('buckling_factors', [])
                logger_callback(f"   Mnożniki wyboczenia: {final_res['buckling_factors']}")
            except Exception as e:
                logger_callback(f"[BŁĄD] Analiza wyboczeniowa nie powiodła się: {e}")
                final_res['buckling_factors'] = []

        # --- FINALIZACJA ---
        if not final_res:
            logger_callback("[STOP] Brak jakichkolwiek wyników do zapisania.")
            return {"status": "error", "message": "No results generated."}

        final_res['status'] = "converged" if converged else "not_converged"
        
        final_dir = router.get_path("FINAL", "", subdir="")
        with open(os.path.join(final_dir, "results.json"), 'w') as f:
             json.dump(final_res, f, indent=4)
        
        if 'analytical_snapshot' in config:
            with open(os.path.join(final_dir, "analytical.json"), 'w') as f:
                json.dump(config['analytical_snapshot'], f, indent=4)
        
        logger_callback(f"\n>>> Zapisano końcowe wyniki w folderze: {final_dir}")
        return final_res