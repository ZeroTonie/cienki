import os
import subprocess
import math
import csv
import sys
import shutil
import json

# Próba importu numpy dla wydajności, ale działa też bez
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class NodeMapper:
    """Mapuje współrzędne fizyczne na ID węzłów siatki."""
    def __init__(self, nodes_csv_path):
        self.nodes = None
        self.ids = None
        self.loaded = False
        self.load_nodes(nodes_csv_path)

    def load_nodes(self, path):
        if not os.path.exists(path): return
        try:
            data_arr = []
            ids_arr = []
            with open(path, 'r') as f:
                reader = csv.reader(f)
                next(reader) # Skip header
                for row in reader:
                    ids_arr.append(int(row[0]))
                    data_arr.append([float(row[1]), float(row[2]), float(row[3])])
            
            if HAS_NUMPY:
                self.nodes = np.array(data_arr)
                self.ids = np.array(ids_arr)
            else:
                self.nodes = data_arr
                self.ids = ids_arr
            self.loaded = True
        except Exception as e:
            print(f"[MAPPER] Error: {e}")

    def find_nearest_node(self, target_x, target_y, target_z):
        """Znajduje ID węzła najbliższego zadanym współrzędnym."""
        if not self.loaded: return None
        
        if HAS_NUMPY:
            # Wersja szybka wektorowa
            t = np.array([target_x, target_y, target_z])
            deltas = self.nodes - t
            dist_sq = np.einsum('ij,ij->i', deltas, deltas)
            min_idx = np.argmin(dist_sq)
            return int(self.ids[min_idx])
        else:
            # Wersja wolna (pętla) - fallback
            best_dist = 1e12
            best_id = None
            for i, (nx, ny, nz) in enumerate(self.nodes):
                d = (nx-target_x)**2 + (ny-target_y)**2 + (nz-target_z)**2
                if d < best_dist:
                    best_dist = d
                    best_id = self.ids[i]
            return best_id

    def generate_sensor_map(self, length, profile_data, plate_data, custom_probes=None, step=50.0):
        """
        Generuje mapę wirtualnych czujników wzdłuż belki.
        Obsługuje sondy definiowane przez użytkownika (formuły).
        """
        map_result = {}
        if not self.loaded: return map_result

        # Przygotowanie kontekstu zmiennych do ewaluacji formuł
        ctx = {
            "hc": float(profile_data['hc']),
            "bc": float(profile_data['bc']),
            "tw": float(profile_data['twc']),
            "twc": float(profile_data['twc']),
            "tfc": float(profile_data['tfc']),
            "tf": float(profile_data['tfc']),
            "tp": float(plate_data['tp']),
            "bp": float(plate_data['bp']),
            "math": math
        }
        
        # Sondy domyślne (Standard v3.0)
        y_int = ctx['tp']/2.0
        probes_def = {
            "P1_Center": (0.0, 0.0),
            "P2_Weld_L": (y_int, -ctx['bp']/2.0),
            "P3_Weld_R": (y_int,  ctx['bp']/2.0),
            "P4_Web_Mid": (y_int + ctx['hc']/2.0, -ctx['bp']/2.0 + ctx['twc']/2.0),
            "P5_Flange_Top": (y_int + ctx['hc'], -ctx['bp']/2.0 + ctx['bc']/2.0)
        }
        
        # Dodanie sond użytkownika z ewaluacją formuł
        if custom_probes:
            for name, (expr_y, expr_z) in custom_probes.items():
                try:
                    # Bezpieczna ewaluacja wyrażenia w kontekście
                    py = eval(str(expr_y), {"__builtins__": None}, ctx)
                    pz = eval(str(expr_z), {"__builtins__": None}, ctx)
                    probes_def[name] = (float(py), float(pz))
                except Exception as e:
                    print(f"[FEM] Błąd w formule sondy '{name}': {e}")

        # Skanowanie wzdłuż osi X
        curr_x = 0.0
        while curr_x <= length + 0.1:
            x_label = int(curr_x)
            for p_name, (py, pz) in probes_def.items():
                nid = self.find_nearest_node(curr_x, py, pz)
                if nid:
                    key = f"X{x_label}_{p_name}"
                    map_result[key] = {
                        "id": nid, 
                        "orig_x": curr_x, "orig_y": py, "orig_z": pz,
                        "probe_name": p_name
                    }
            curr_x += step
            
        return map_result

class FemEngine:
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.mapper = None
        self.sensor_info = {}

    def prepare_calculix_deck(self, inp_path, run_params):
        """Generuje plik _run.inp z pełną definicją zadania."""
        if not os.path.exists(inp_path): return None
        
        work_dir = os.path.dirname(inp_path)
        base = os.path.splitext(os.path.basename(inp_path))[0]
        
        # 1. Wczytanie węzłów i generacja czujników
        self.mapper = NodeMapper(os.path.join(work_dir, f"{base}_nodes.csv"))
        if not self.mapper.loaded: return None
        
        self.sensor_info = self.mapper.generate_sensor_map(
            float(run_params.get("Length", 1000)),
            run_params.get("profile_data", {}),
            run_params.get("plate_data", {}),
            run_params.get("custom_probes", {}),
            step=float(run_params.get("step", 50.0))
        )
        
        # 2. Wczytanie siatki (mesh)
        with open(inp_path, 'r') as f: mesh_content = f.read()
        deck = [mesh_content]
        
        # 3. Wczytanie grup węzłów (support/load/interface)
        groups = {}
        try:
            with open(os.path.join(work_dir, f"{base}_groups.json"), 'r') as f: 
                groups = json.load(f)
        except: pass
        
        # Zapis grup do .inp
        for g_name, nodes in groups.items():
            if nodes:
                deck.append(f"*NSET, NSET=NSET_{g_name}")
                # Łamanie linii po 10 ID
                for i in range(0, len(nodes), 10):
                    deck.append(", ".join(map(str, nodes[i:i+10])))
        
        # 4. Rigid Bodies (Punkty Referencyjne)
        ref_supp_id = 999991
        ref_load_id = 999992
        y_sc = float(run_params.get("SC_Y", 0.0))
        L = float(run_params.get("Length"))
        
        deck.append("*NODE")
        deck.append(f"{ref_supp_id}, 0.0, {y_sc}, 0.0")
        deck.append(f"{ref_load_id}, {L}, {y_sc}, 0.0")
        
        deck.append("*NSET, NSET=REF_NODES")
        deck.append(f"{ref_supp_id}, {ref_load_id}")
        
        if "SURF_SUPPORT" in groups:
            deck.append(f"*RIGID BODY, NSET=NSET_SURF_SUPPORT, REF NODE={ref_supp_id}")
        if "SURF_LOAD" in groups:
            deck.append(f"*RIGID BODY, NSET=NSET_SURF_LOAD, REF NODE={ref_load_id}")
            
        # 5. Materiał i Sekcja
        E = float(run_params.get("E", 210000))
        deck.append("*MATERIAL, NAME=STEEL")
        deck.append("*ELASTIC")
        deck.append(f"{E}, 0.3")
        deck.append("*SOLID SECTION, ELSET=VOL_ALL, MATERIAL=STEEL")
        
        # 6. Krok (Step)
        deck.append("*STEP")
        deck.append("*STATIC")
        
        # Warunki brzegowe
        deck.append("*BOUNDARY")
        deck.append(f"{ref_supp_id}, 1, 6, 0.0") # Utwierdzenie
        
        # Obciążenie (Ściskanie)
        deck.append("*CLOAD")
        fx = abs(float(run_params.get("Fx", 1000)))
        deck.append(f"{ref_load_id}, 1, {-fx}")
        
        # 7. Wyniki (Outputs)
        # Reakcje i przemieszczenia w punktach referencyjnych
        deck.append("*NODE PRINT, NSET=REF_NODES")
        deck.append("U, RF")
        
        # Wyniki w czujnikach
        sensor_ids = sorted(list(set([v['id'] for v in self.sensor_info.values()])))
        if sensor_ids:
            deck.append("*NSET, NSET=NSET_SENSORS")
            for i in range(0, len(sensor_ids), 10):
                deck.append(", ".join(map(str, sensor_ids[i:i+10])))
            deck.append("*NODE PRINT, NSET=NSET_SENSORS")
            deck.append("U, S") # S = Stress (extrapolated to nodes)
            
        # Max Stress w całym modelu (do zbieżności)
        deck.append("*EL PRINT, ELSET=VOL_ALL")
        deck.append("S")
        
        deck.append("*END STEP")
        
        run_inp_path = inp_path.replace(".inp", "_run.inp")
        with open(run_inp_path, 'w') as f: f.write("\n".join(deck))
        return run_inp_path

    def run_solver(self, inp_path, work_dir, num_threads=4):
        """Uruchamia CalculiX w zadanym katalogu."""
        if not inp_path: return False
        
        # Ustalenie komendy (absolute path or system path)
        ccx_cmd = self.ccx_path
        if not os.path.isabs(ccx_cmd) and not shutil.which(ccx_cmd):
             local = os.path.join(os.getcwd(), ccx_cmd + ".exe")
             if os.path.exists(local): ccx_cmd = local
        
        job_name = os.path.splitext(os.path.basename(inp_path))[0]
        
        # Ustawienie zmiennych środowiskowych
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(num_threads)
        
        try:
            # Uruchomienie procesu
            cmd = [ccx_cmd, job_name]
            # Shell=True dla Windows czasem pomaga z PATH
            subprocess.run(
                cmd, 
                cwd=work_dir, 
                shell=(os.name=='nt'), 
                env=env, 
                check=True, 
                capture_output=True
            )
            return True
        except Exception as e:
            print(f"[FEM ENGINE] Solver Error: {e}")
            return False

    def parse_dat_results(self, dat_path):
        """Parsuje plik .dat (tekstowy wynik CCX) i mapuje na czujniki."""
        if not os.path.exists(dat_path): return {}
        
        raw_disp = {}
        raw_stress = {}
        model_max_vm = 0.0
        
        # Stany parsera
        current_block = None # 'disp', 'stress'
        
        try:
            with open(dat_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    if "displacements" in line.lower():
                        current_block = 'disp'
                        continue
                    elif "stresses" in line.lower():
                        current_block = 'stress'
                        continue
                    elif "forces" in line.lower():
                        current_block = 'force' # Reakcje (ignorujemy tu, chyba że potrzebne)
                        continue
                        
                    # Parsowanie danych liczbowych
                    # CCX format: NodeID  Val1  Val2 ...
                    parts = line.split()
                    if not parts[0].isdigit(): continue
                    
                    nid = int(parts[0])
                    vals = [float(x) for x in parts[1:]]
                    
                    if current_block == 'disp':
                        # UX, UY, UZ
                        if len(vals) >= 3:
                            raw_disp[nid] = {'ux': vals[0], 'uy': vals[1], 'uz': vals[2]}
                            
                    elif current_block == 'stress':
                        # S11, S22, S33, S12, S23, S13 (zazwyczaj)
                        # Obliczamy Von Mises
                        if len(vals) >= 6:
                            s11, s22, s33, s12, s23, s13 = vals[0:6]
                            vm = math.sqrt(0.5 * ((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s23**2 + s13**2)))
                            raw_stress[nid] = vm
                            if vm > model_max_vm: model_max_vm = vm

            # Mapowanie na czujniki
            final_results = {
                "MODEL_MAX_VM": model_max_vm,
                "converged": True # Placeholder, zbieżność ocenia optimizer
            }
            
            for key, meta in self.sensor_info.items():
                nid = meta['id']
                u = raw_disp.get(nid, {'ux':0, 'uy':0, 'uz':0})
                vm = raw_stress.get(nid, 0.0)
                
                final_results[key] = {
                    "X": meta['orig_x'],
                    "U_Y": u['uy'],
                    "U_Z": u['uz'],
                    "S_VM": vm
                }
                
            return final_results
            
        except Exception as e:
            print(f"[FEM ENGINE] Parse Error: {e}")
            return {"MODEL_MAX_VM": 0.0}