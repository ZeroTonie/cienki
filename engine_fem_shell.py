import os
import subprocess
import math
import csv
import sys
import shutil
import json
import time
import material_catalogue  # Import Twojej bazy materiałowej

# Próba importu numpy (zalecane do szybszych obliczeń)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class FemEngineShell:
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.work_dir = ""
        
        # Przechowalnia kluczowych danych z geometrii
        self.groups = {}
        self.nodes_map = {} # id -> [x, y, z]
        
        # [NOWOŚĆ] Zapamiętujemy ID węzła referencyjnego (końca belki)
        # Służy do wyciągnięcia ugięcia bez mapowania całej siatki
        self.ref_node_id = None 

    def _load_metadata(self, base_path_no_ext):
        """Wczytuje mapę węzłów i grupy z plików JSON/CSV wygenerowanych przez geometrię."""
        groups_path = f"{base_path_no_ext}_groups.json"
        nodes_path = f"{base_path_no_ext}_nodes.csv"
        
        # 1. Wczytanie grup węzłów (Support, Load, Weld Lines)
        if os.path.exists(groups_path):
            with open(groups_path, 'r') as f:
                self.groups = json.load(f)
        
        # 2. Wczytanie węzłów (potrzebujemy tylko max_id)
        self.nodes_map = {}
        if os.path.exists(nodes_path):
            with open(nodes_path, 'r') as f:
                reader = csv.reader(f)
                next(reader) # Skip header
                for row in reader:
                    if row:
                        self.nodes_map[int(row[0])] = [float(row[1]), float(row[2]), float(row[3])]

    def prepare_calculix_deck(self, inp_path, run_params):
        """
        Tworzy plik startowy .inp dla CalculiX na podstawie siatki i parametrów.
        Integruje dane z material_catalogue.
        """
        if not os.path.exists(inp_path):
            return None
        
        self.work_dir = os.path.dirname(inp_path)
        base_name = os.path.splitext(os.path.basename(inp_path))[0]
        # Usuwamy ewentualny sufiks "_run_..." żeby znaleźć pliki geometrii
        base_geo_name = base_name.split("_run_")[0]
        base_full_path = os.path.join(self.work_dir, base_geo_name)
        
        self._load_metadata(base_full_path)
        
        # Czytamy oryginalny plik .inp z siatką (węzły i elementy)
        with open(inp_path, 'r') as f:
            mesh_content = f.read()

        deck = []
        deck.append("** CALCULIX DECK FOR SHELL MODEL (Merged Version) **")
        deck.append(mesh_content)
        
        # --- 1. DEFINICJA NODE SETÓW (GRUP) ---
        # Przepisujemy grupy z JSON do formatu *NSET w pliku .inp
        for g_name, nodes in self.groups.items():
            if nodes:
                deck.append(f"*NSET, NSET={g_name}")
                # Zapisujemy w blokach po 10 ID dla czytelności i limitów długości linii
                for i in range(0, len(nodes), 10):
                    chunk = nodes[i:i+10]
                    deck.append(", ".join(map(str, chunk)))

        # Grupa wszystkich węzłów (dla outputu)
        max_id = max(self.nodes_map.keys()) if self.nodes_map else 100000
        deck.append("*NSET, NSET=NALL, GENERATE")
        deck.append(f"1, {max_id}, 1")

        # --- 2. MATERIAŁ (Z BAZY DANYCH) ---
        # Pobieramy nazwę materiału przekazaną z GUI/Optymalizatora
        mat_name = run_params.get("Stop", "S355")
        
        # Pobieramy bazę
        mat_db = material_catalogue.baza_materialow()
        
        if mat_name in mat_db:
            mat_data = mat_db[mat_name]
            E_val = float(mat_data['E'])
            G_val = float(mat_data['G'])
            rho_kg_m3 = float(mat_data['rho'])
            
            # Obliczenie współczynnika Poissona (nu = E/2G - 1)
            if G_val > 0:
                nu_val = (E_val / (2.0 * G_val)) - 1.0
                if not (0.0 < nu_val < 0.5): nu_val = 0.3
            else:
                nu_val = 0.3
            
            # Konwersja gęstości: kg/m3 -> t/mm3 (jednostka spójna dla N/mm2)
            rho_fem = rho_kg_m3 * 1.0e-9
            
            comment = f"** Material from DB: {mat_name} (Re={mat_data.get('Re',0)})"
        else:
            # Fallback
            E_val = float(run_params.get("E", 210000.0))
            nu_val = float(run_params.get("nu", 0.3))
            rho_fem = 7.85e-9
            comment = "** Material: GENERIC FALLBACK"

        # Nazwa wewnętrzna używana w definicji sekcji
        INTERNAL_MAT_NAME = "MAT_SHELL_DB"

        deck.append(f"*MATERIAL, NAME={INTERNAL_MAT_NAME}")
        deck.append(comment)
        deck.append("*ELASTIC")
        deck.append(f"{E_val}, {nu_val}")
        deck.append("*DENSITY")
        deck.append(f"{rho_fem}")

        # --- 3. SEKCJE POWŁOKOWE (*SHELL SECTION) ---
        plate_data = run_params.get("plate_data", {})
        profile_data = run_params.get("profile_data", {})
        
        # Pobieramy grubości
        tp = float(plate_data.get("tp", 10.0))
        twc = float(profile_data.get("twc", 6.0))
        tfc = float(profile_data.get("tfc", 10.0))
        
        # Przypisanie sekcji
        deck.append(f"*SHELL SECTION, ELSET=SHELL_PLATE, MATERIAL={INTERNAL_MAT_NAME}")
        deck.append(f"{tp}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_WEBS, MATERIAL={INTERNAL_MAT_NAME}")
        deck.append(f"{twc}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_FLANGES, MATERIAL={INTERNAL_MAT_NAME}")
        deck.append(f"{tfc}")

        # --- 4. WIĄZANIA SPOIN (*TIE) ---
        # Tolerancja uwzględniająca mid-surfaces
        gap = (tp + tfc) / 2.0
        tie_tol = gap + 2.0 
        
        deck.append(f"*TIE, NAME=WELD_L, POSITION TOLERANCE={tie_tol}")
        deck.append("NSET_LINE_WELD_L_SLAVE, NSET_LINE_WELD_L_MASTER")
        deck.append(f"*TIE, NAME=WELD_R, POSITION TOLERANCE={tie_tol}")
        deck.append("NSET_LINE_WELD_R_SLAVE, NSET_LINE_WELD_R_MASTER")

        # --- 5. OBCIĄŻENIE (*RIGID BODY & REF NODE) ---
        # Tworzymy nowy węzeł (Ref Node) w przestrzeni
        # [ZMIANA] Przypisujemy do self.ref_node_id, aby parser mógł go użyć
        self.ref_node_id = max_id + 1
        
        L = float(run_params.get("Length", 1000.0))
        y_ref = float(run_params.get("Y_ref_node", 0.0))
        
        deck.append("*NODE")
        deck.append(f"{self.ref_node_id}, {L}, {y_ref}, 0.0")
        
        # Definiujemy Rigid Body (Sztywne połączenie)
        deck.append(f"*RIGID BODY, NSET=NSET_LOAD, REF NODE={self.ref_node_id}")
        
        # Tworzymy NSET dla Ref Node, żeby łatwo poprosić o output
        deck.append(f"*NSET, NSET=REF_NODE_SET")
        deck.append(f"{self.ref_node_id}")

        # --- 6. KROK 1: STATYKA ---
        deck.append("*STEP")
        deck.append("*STATIC")
        
        # Warunki brzegowe
        deck.append("*BOUNDARY")
        deck.append("NSET_SUPPORT, 1, 6, 0.0")
        
        # Siły skupione (CLOAD)
        deck.append("*CLOAD")
        
        fx = float(run_params.get("Fx", 0.0))
        fy = float(run_params.get("Fy", 0.0))
        fz = float(run_params.get("Fz", 0.0))
        mx = float(run_params.get("Mx", 0.0))
        my = float(run_params.get("My", 0.0))
        mz = float(run_params.get("Mz", 0.0))
        
        if abs(fx) > 1e-9: deck.append(f"{self.ref_node_id}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{self.ref_node_id}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{self.ref_node_id}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{self.ref_node_id}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{self.ref_node_id}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{self.ref_node_id}, 6, {mz}")

        # Output Requests
        deck.append("*NODE PRINT, NSET=NSET_SUPPORT, TOTAL=YES")
        deck.append("RF")
        
        # [KLUCZOWE] Prośba o wyniki dla węzła referencyjnego
        deck.append("*NODE PRINT, NSET=REF_NODE_SET")
        deck.append("U")
        
        # Naprężenia w elementach (dla Max VM)
        deck.append("*EL PRINT")
        deck.append("S")
        
        deck.append("*END STEP")

        # --- 7. KROK 2: WYBOCZENIE (*BUCKLE) ---
        deck.append("*STEP")
        deck.append("*BUCKLE")
        deck.append("10")
        
        deck.append("*CLOAD")
        if abs(fx) > 1e-9: deck.append(f"{self.ref_node_id}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{self.ref_node_id}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{self.ref_node_id}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{self.ref_node_id}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{self.ref_node_id}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{self.ref_node_id}, 6, {mz}")
        
        deck.append("*NODE FILE")
        deck.append("U")
        deck.append("*END STEP")

        # Zapis gotowego pliku .inp
        timestamp = int(time.time())
        run_inp_path = inp_path.replace(".inp", f"_run_{timestamp}.inp")
        
        with open(run_inp_path, 'w') as f:
            f.write("\n".join(deck))
            
        return run_inp_path

    def run_solver(self, inp_path, work_dir, num_threads=4, callback=None):
        """Uruchamia CalculiX (ccx)."""
        ccx_cmd = self.ccx_path
        if not os.path.isabs(ccx_cmd) and not shutil.which(ccx_cmd):
             local = os.path.join(os.getcwd(), ccx_cmd + ".exe")
             if os.path.exists(local): ccx_cmd = local
             
        job_name = os.path.splitext(os.path.basename(inp_path))[0]
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(num_threads)
        
        try:
            cmd = [ccx_cmd, job_name]
            process = subprocess.Popen(
                cmd, cwd=work_dir, shell=(os.name=='nt'), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    l = line.strip()
                    if l and callback:
                        callback(f"CCX: {l}")
            return (process.poll() == 0)
        except Exception as e:
            if callback: callback(f"ERROR executing solver: {e}")
            return False

    def parse_dat_results(self, dat_path):
        """Parsuje plik tekstowy .dat z wynikami."""
        if not os.path.exists(dat_path):
            return {}

        results = {
            "MODEL_MAX_VM": 0.0,
            "BUCKLING_FACTORS": [],
            "REACTIONS": {"Fx":0, "Fy":0, "Fz":0, "Mx":0, "My":0, "Mz":0},
            "DISPLACEMENTS_REF": {"Ux":0.0, "Uy":0.0, "Uz":0.0},
            "converged": False
        }
        
        current_step = 0
        reading_reactions = False
        reading_stresses = False
        current_type = None # disp, stress, force
        
        max_vm = 0.0
        
        with open(dat_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                l_lower = line.lower()

                # Wykrywanie kroku
                if "step" in l_lower and "1" in l_lower and "static" in l_lower:
                    current_step = 1
                elif "step" in l_lower and "buckle" in l_lower:
                    current_step = 2

                # --- STEP 1: STATYKA ---
                if current_step == 1:
                    
                    # 1. Wykrywanie typu danych (Displacements, Stresses, Forces)
                    if "displacements" in l_lower:
                        current_type = 'disp'
                        continue
                    if "stresses" in l_lower:
                        current_type = 'stress'
                        continue
                    if "forces" in l_lower:
                        current_type = 'force'
                        continue

                    # Parsowanie linii z danymi
                    parts = line.split()
                    if not parts or not parts[0].isdigit():
                        continue
                        
                    nid = int(parts[0])
                    
                    # A. Przemieszczenia (szukamy Ref Node)
                    if current_type == 'disp':
                        if self.ref_node_id and nid == self.ref_node_id:
                            # Format: Node, Ux, Uy, Uz
                            try:
                                results["DISPLACEMENTS_REF"]["Ux"] = float(parts[1])
                                results["DISPLACEMENTS_REF"]["Uy"] = float(parts[2])
                                results["DISPLACEMENTS_REF"]["Uz"] = float(parts[3])
                            except: pass

                    # B. Naprężenia (Max VM globalnie)
                    elif current_type == 'stress':
                        try:
                            # Format Shell: Elem_ID, Int_Pt, S11, S22, S33, S12, S13, S23
                            if len(parts) >= 8:
                                s11 = float(parts[2])
                                s22 = float(parts[3])
                                s33 = float(parts[4])
                                s12 = float(parts[5])
                                s13 = float(parts[6])
                                s23 = float(parts[7])
                                
                                vm = math.sqrt(0.5 * ((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s23**2 + s13**2)))
                                if vm > max_vm: max_vm = vm
                        except: pass
                        
                    # C. Reakcje
                    # (Można dodać parsowanie sumaryczne, jeśli CalculiX wyrzuca linię TOTAL)

                # --- STEP 2: WYBOCZENIE ---
                if current_step == 2:
                    if "buckling factor" in l_lower:
                        parts = line.split()
                        try:
                            val = float(parts[-1])
                            results["BUCKLING_FACTORS"].append(val)
                        except: pass

        results["MODEL_MAX_VM"] = max_vm
        results["converged"] = (max_vm > 0.0)
        
        return results