import os
import subprocess
import math
import csv
import sys
import shutil
import json
import time
import material_catalogue

# Próba importu numpy dla szybszych obliczeń (opcjonalnie)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class FemEngineShell:
    """
    Silnik FEM dedykowany dla modeli powłokowych (Shell).
    Generuje inputy dla CalculiX (CCX), uruchamia solver i parsuje wyniki.
    Obsługuje:
    - Statykę (Step 1)
    - Wyboczenie (Step 2)
    - Fizyczne ramię siły (Rigid Arm)
    """
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.work_dir = ""
        
        # Przechowalnia danych o grupach i węzłach z geometrii
        self.groups = {}
        self.nodes_map = {} 
        
        # ID kluczowych węzłów (ustalane dynamicznie)
        self.ref_node_structure = None  # Węzeł "A": Środek ciężkości przekroju (Rigid Body Master)
        self.ref_node_load = None       # Węzeł "B": Punkt przyłożenia siły (Load Point)

    def _load_metadata(self, base_path_no_ext):
        """
        Wczytuje metadane (grupy węzłów, mapę ID) wygenerowane przez engine_geometry_shell.
        Pliki: *_groups.json, *_nodes.csv
        """
        groups_path = f"{base_path_no_ext}_groups.json"
        nodes_path = f"{base_path_no_ext}_nodes.csv"
        
        # 1. Wczytanie grup (NSET)
        if os.path.exists(groups_path):
            try:
                with open(groups_path, 'r') as f:
                    self.groups = json.load(f)
            except Exception as e:
                print(f"[FEM-SHELL] Error loading groups: {e}")
        
        # 2. Wczytanie mapy węzłów (potrzebne do znalezienia max_id)
        self.nodes_map = {}
        if os.path.exists(nodes_path):
            try:
                with open(nodes_path, 'r') as f:
                    reader = csv.reader(f)
                    next(reader, None) # Skip header
                    for row in reader:
                        if row:
                            nid = int(row[0])
                            # [x, y, z]
                            self.nodes_map[nid] = [float(row[1]), float(row[2]), float(row[3])]
            except Exception as e:
                print(f"[FEM-SHELL] Error loading nodes: {e}")

    def prepare_calculix_deck(self, inp_path, run_params):
        """
        Główna metoda tworząca plik .inp.
        Łączy siatkę (Mesh), Materiały, Sekcje, Wiązania (TIE/Rigid) i Kroki (Steps).
        """
        if not os.path.exists(inp_path):
            return None
        
        self.work_dir = os.path.dirname(inp_path)
        base_name = os.path.splitext(os.path.basename(inp_path))[0]
        # Usuwamy sufiksy czasowe, by znaleźć plik geometrii bazowej
        base_geo_name = base_name.split("_run_")[0]
        base_full_path = os.path.join(self.work_dir, base_geo_name)
        
        # Ładujemy dane o grupach z geometrii
        self._load_metadata(base_full_path)
        
        # Czytamy siatkę wygenerowaną przez Gmsh
        with open(inp_path, 'r') as f:
            mesh_content = f.read()

        deck = []
        deck.append("** ==================================================================")
        deck.append("** CALCULIX DECK FOR SHELL MODEL (Rigid Arm Version)")
        deck.append(f"** Timestamp: {time.ctime()}")
        deck.append("** ==================================================================")
        deck.append(mesh_content)
        
        # --- 1. DEFINICJA NODE SETÓW Z GEOMETRII ---
        deck.append("** --- GRUPY WEZLOW (IMPORTOWANE) ---")
        for g_name, nodes in self.groups.items():
            if nodes:
                deck.append(f"*NSET, NSET={g_name}")
                # CalculiX lubi max 16 liczb w linii, dajemy bezpiecznie 10
                for i in range(0, len(nodes), 10):
                    deck.append(", ".join(map(str, nodes[i:i+10])))

        # Grupa wszystkich węzłów (do wizualizacji/outputu)
        max_id = max(self.nodes_map.keys()) if self.nodes_map else 100000
        deck.append(f"*NSET, NSET=NALL, GENERATE\n1, {max_id}, 1")

        # --- 2. MATERIAŁY (Z BAZY DANYCH) ---
        deck.append("** --- MATERIALY ---")
        
        mat_name = run_params.get("Stop", "S355")
        mat_db = material_catalogue.baza_materialow()
        
        if mat_name in mat_db:
            m = mat_db[mat_name]
            E_val = float(m['E'])
            G_val = float(m['G'])
            rho_val = float(m['rho'])
            Re_val = float(m.get('Re', 0.0))
            
            # Obliczenie współczynnika Poissona nu = E/(2G) - 1
            if G_val > 0:
                nu_val = (E_val / (2.0 * G_val)) - 1.0
                if not (0.0 < nu_val < 0.5): nu_val = 0.3
            else:
                nu_val = 0.3
            
            # Konwersja gęstości: kg/m3 -> t/mm3 (jednostka spójna dla N/mm2)
            # 1 kg/m3 = 1e-9 t/mm3 (np. stal 7850 -> 7.85e-9)
            rho_fem = rho_val * 1.0e-9
            
            comment = f"** Material DB: {mat_name} (Re={Re_val}, E={E_val})"
        else:
            # Fallback
            E_val, nu_val, rho_fem = 210000.0, 0.3, 7.85e-9
            comment = "** Material: GENERIC FALLBACK (Steel)"

        # A) Materiał Konstrukcyjny (SHELL)
        deck.append(f"*MATERIAL, NAME=MAT_SHELL")
        deck.append(comment)
        deck.append("*ELASTIC")
        deck.append(f"{E_val}, {nu_val}")
        deck.append("*DENSITY")
        deck.append(f"{rho_fem}")

        # B) Materiał Sztywny (RIGID ARM BEAM)
        # Używamy bardzo dużego modułu Younga i znikomej gęstości
        deck.append(f"*MATERIAL, NAME=MAT_RIGID")
        deck.append("** Super-stiff material for load arm")
        deck.append("*ELASTIC")
        deck.append(f"{E_val * 1000.0}, {nu_val}") # 1000x sztywniejszy
        deck.append("*DENSITY")
        deck.append("1.0e-12") # Prawie bezmasowy

        # --- 3. SEKCJE POWŁOKOWE (*SHELL SECTION) ---
        deck.append("** --- SEKCJE POWLOKOWE ---")
        pl = run_params.get("plate_data", {})
        pr = run_params.get("profile_data", {})
        
        # Przypisanie grubości do grup elementów (ELSET generowane przez Gmsh)
        deck.append(f"*SHELL SECTION, ELSET=SHELL_PLATE, MATERIAL=MAT_SHELL\n{pl.get('tp', 10.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_WEBS, MATERIAL=MAT_SHELL\n{pr.get('twc', 6.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_FLANGES, MATERIAL=MAT_SHELL\n{pr.get('tfc', 10.0)}")

        # --- 4. WIĄZANIA (TIE - SPOINY) ---
        deck.append("** --- WIAZANIA (SPOINY) ---")
        # Obliczamy tolerancję (luka między mid-surfaces)
        gap = (float(pl.get('tp', 10.0)) + float(pr.get('tfc', 10.0))) / 2.0
        tie_tol = gap + 15.0 # Margines bezpieczeństwa
        
        # Dodajemy TIE tylko jeśli grupy istnieją
        if "LINE_WELD_L_SLAVE" in self.groups and "LINE_WELD_L_MASTER" in self.groups:
            deck.append(f"*TIE, NAME=WELD_L, POSITION TOLERANCE={tie_tol}")
            deck.append("NSET_LINE_WELD_L_SLAVE, NSET_LINE_WELD_L_MASTER")
        
        if "LINE_WELD_R_SLAVE" in self.groups and "LINE_WELD_R_MASTER" in self.groups:
            deck.append(f"*TIE, NAME=WELD_R, POSITION TOLERANCE={tie_tol}")
            deck.append("NSET_LINE_WELD_R_SLAVE, NSET_LINE_WELD_R_MASTER")

        # --- 5. UKŁAD WPROWADZANIA OBCIĄŻENIA (RIGID ARM) ---
        deck.append("** --- MECHANIZM OBCIAZENIA (RIGID ARM) ---")
        
        L = float(run_params.get("Length", 1000.0))
        y_centroid = float(run_params.get("Y_structure_center", 0.0))
        y_load = float(run_params.get("Y_load_level", 0.0))
        
        # Nowe ID węzłów
        self.ref_node_structure = max_id + 1
        self.ref_node_load = max_id + 2
        
        deck.append("*NODE")
        # Węzeł A: Środek Ciężkości Struktury (tutaj mierzymy ugięcie)
        deck.append(f"{self.ref_node_structure}, {L}, {y_centroid}, 0.0")
        # Węzeł B: Punkt Przyłożenia Siły (ramię siły)
        deck.append(f"{self.ref_node_load}, {L}, {y_load}, 0.0")
        
        # A) Rigid Body: Wiąże koniec powłok (NSET_LOAD) z węzłem A
        if "NSET_LOAD" in self.groups and len(self.groups["NSET_LOAD"]) > 0:
            deck.append(f"*RIGID BODY, NSET=NSET_LOAD, REF NODE={self.ref_node_structure}")
        else:
            deck.append("** ERROR: NSET_LOAD is empty! Rigid Body will fail.")
        
        # B) Element Belkowy (B31): Łączy węzeł A z węzłem B
        elem_id_beam = 1000000 # Bezpieczne wysokie ID
        deck.append(f"*ELEMENT, TYPE=B31, ELSET=EL_RIGID_ARM")
        deck.append(f"{elem_id_beam}, {self.ref_node_structure}, {self.ref_node_load}")
        
        deck.append(f"*BEAM SECTION, ELSET=EL_RIGID_ARM, MATERIAL=MAT_RIGID, SECTION=RECT")
        deck.append("50.0, 50.0")
        deck.append("1.0, 0.0, 0.0")

        # Grupy dla outputu
        deck.append(f"*NSET, NSET=REF_NODE_STRUCT\n{self.ref_node_structure}")

        # --- 6. STEP 1: STATYKA ---
        deck.append("** --- KROK 1: STATYKA ---")
        deck.append("*STEP")
        deck.append("*STATIC")
        
        # Warunki brzegowe (Utwierdzenie na początku X=0)
        if "NSET_SUPPORT" in self.groups:
            deck.append("*BOUNDARY")
            deck.append("NSET_NSET_SUPPORT, 1, 6, 0.0")
        
        # Siły skupione (CLOAD) przykładane do WĘZŁA B (Load Point)
        deck.append("*CLOAD")
        fx = float(run_params.get("Fx", 0.0))
        fy = float(run_params.get("Fy", 0.0))
        fz = float(run_params.get("Fz", 0.0))
        mx = float(run_params.get("Mx", 0.0))
        my = float(run_params.get("My", 0.0))
        mz = float(run_params.get("Mz", 0.0))
        
        target = self.ref_node_load # <-- Siła działa na ramię
        
        if abs(fx) > 1e-9: deck.append(f"{target}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{target}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{target}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{target}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{target}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{target}, 6, {mz}")

        # Output Requests
        deck.append("*NODE PRINT, NSET=REF_NODE_STRUCT")
        deck.append("U")
        if "NSET_SUPPORT" in self.groups:
            deck.append("*NODE PRINT, NSET=NSET_NSET_SUPPORT, TOTAL=YES")
            deck.append("RF")
        deck.append("*EL PRINT, ELSET=NALL")
        deck.append("S")
        deck.append("*NODE PRINT, NSET=NALL")
        deck.append("U")
        
        deck.append("*END STEP")

        # --- 7. STEP 2: WYBOCZENIE ---
        deck.append("** --- KROK 2: WYBOCZENIE ---")
        deck.append("*STEP")
        deck.append("*BUCKLE")
        deck.append("5") # Liczymy 5 pierwszych modów
        
        deck.append("*CLOAD")
        if abs(fx) > 1e-9: deck.append(f"{target}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{target}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{target}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{target}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{target}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{target}, 6, {mz}")
        
        deck.append("*NODE FILE")
        deck.append("U")
        deck.append("*END STEP")
        
        timestamp = int(time.time())
        run_inp_path = inp_path.replace(".inp", f"_run_{timestamp}.inp")
        
        try:
            with open(run_inp_path, 'w') as f:
                f.write("\n".join(deck))
            return run_inp_path
        except Exception as e:
            print(f"[FEM-SHELL] Error writing .inp file: {e}")
            return None

    def run_solver(self, inp_path, work_dir, num_threads=4, callback=None):
        """Uruchamia CalculiX (ccx)."""
        ccx_cmd = self.ccx_path
        if not os.path.isabs(ccx_cmd) and not shutil.which(ccx_cmd):
             local = os.path.join(os.getcwd(), ccx_cmd + ".exe")
             if os.path.exists(local): ccx_cmd = local
        job_name = os.path.splitext(os.path.basename(inp_path))[0]
        env = os.environ.copy(); env["OMP_NUM_THREADS"] = str(num_threads)
        
        try:
            cmd = [ccx_cmd, job_name]
            process = subprocess.Popen(
                cmd, cwd=work_dir, shell=(os.name=='nt'), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None: break
                if line:
                    l = line.strip()
                    if not l: continue
                    msg = f"CCX: {l}"
                    if callback: callback(msg)
            return (process.poll() == 0)
        except Exception as e:
            if callback: callback(f"ERROR: {e}")
            return False

    def parse_dat_results(self, dat_path):
        """
        Parsuje plik .dat przy użyciu Maszyny Stanów (State Machine).
        """
        if not os.path.exists(dat_path): return {}

        results = {
            "MODEL_MAX_VM": 0.0,
            "BUCKLING_FACTORS": [],
            "DISPLACEMENTS_REF": {"Ux":0.0, "Uy":0.0, "Uz":0.0},
            "REACTIONS_TOTAL": {"Fx":0.0, "Fy":0.0, "Fz":0.0},
            "converged": False
        }
        
        current_step = 0
        current_type = None 
        max_vm = 0.0
        
        try:
            with open(dat_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    l_low = line.lower()

                    # Wykrywanie kroku
                    if "step" in l_low and "1" in l_low and "static" in l_low: 
                        current_step = 1
                    elif "step" in l_low and "buckle" in l_low: 
                        current_step = 2

                    # --- STEP 2: WYBOCZENIE ---
                    if current_step == 2 and "buckling factor" in l_low:
                        parts = line.split()
                        try:
                            val = float(parts[-1])
                            results["BUCKLING_FACTORS"].append(val)
                        except: pass
                        continue
                    
                    # --- STEP 1: STATYKA ---
                    if current_step == 1:
                        if "displacements" in l_low: current_type = 'disp'; continue
                        if "stresses" in l_low: current_type = 'stress'; continue
                        if "total" in l_low and "force" in l_low and "support" in l_low:
                            current_type = 'rf_total'; continue
                        if "forces" in l_low and "total" not in l_low:
                            current_type = None; continue

                        parts = line.split()
                        if not parts: continue

                        if current_type == 'rf_total':
                            nums = []
                            for p in parts:
                                clean_p = p.replace('e','').replace('E','').replace('.','').replace('-','')
                                if clean_p.isdigit():
                                    try: nums.append(float(p))
                                    except: pass
                            if len(nums) >= 3:
                                results["REACTIONS_TOTAL"]["Fx"] = nums[-3]
                                results["REACTIONS_TOTAL"]["Fy"] = nums[-2]
                                results["REACTIONS_TOTAL"]["Fz"] = nums[-1]
                                current_type = None 
                            continue

                        if not parts[0].isdigit(): continue
                        nid = int(parts[0])
                        try: vals = [float(x) for x in parts[1:]]
                        except: continue

                        if current_type == 'disp':
                            if self.ref_node_structure and nid == self.ref_node_structure:
                                if len(vals) >= 3:
                                    results["DISPLACEMENTS_REF"] = {"Ux":vals[0], "Uy":vals[1], "Uz":vals[2]}
                        
                        elif current_type == 'stress':
                            if len(vals) >= 6: 
                                if len(vals) >= 8:
                                    s11, s22, s33 = vals[2], vals[3], vals[4]
                                    s12, s13, s23 = vals[5], vals[6], vals[7]
                                    vm = math.sqrt(0.5*((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s23**2 + s13**2)))
                                    if vm > max_vm: max_vm = vm

        except Exception as e:
            print(f"[FEM-SHELL] Parser Error: {e}")

        results["MODEL_MAX_VM"] = max_vm
        results["converged"] = (max_vm > 0.0) 
        
        return results