import os
import subprocess
import math
import csv
import sys
import shutil
import json
import time
import material_catalogue

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class FemEngineShell:
    """
    Silnik FEM dedykowany dla modeli powłokowych (Shell).
    Używa metody *TIE (Surface-to-Node) do łączenia rozłącznych siatek.
    """
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.work_dir = ""
        self.groups = {}
        self.nodes_map = {} 
        self.ref_node_structure = None
        self.ref_node_load = None

    def _load_metadata(self, base_path_no_ext):
        """Wczytuje grupy węzłów i mapę węzłów."""
        # Pliki generowane przez engine_geometry_shell to: [Nazwa].inp, [Nazwa]_groups.json
        groups_path = f"{base_path_no_ext}_groups.json"
        nodes_path = f"{base_path_no_ext}_nodes.csv"
        
        self.groups = {}
        if os.path.exists(groups_path):
            try:
                with open(groups_path, 'r') as f: self.groups = json.load(f)
            except Exception as e: print(f"[FEM-SHELL] Error loading groups: {e}")
        
        self.nodes_map = {}
        if os.path.exists(nodes_path):
            try:
                with open(nodes_path, 'r') as f:
                    reader = csv.reader(f)
                    next(reader, None) # Skip header
                    for row in reader:
                        if row: 
                            try: self.nodes_map[int(row[0])] = [float(row[1]), float(row[2]), float(row[3])]
                            except: pass
            except: pass

    def prepare_calculix_deck(self, inp_path, run_params):
        if not os.path.exists(inp_path): return None
        
        self.work_dir = os.path.dirname(inp_path)
        base_name = os.path.splitext(os.path.basename(inp_path))[0]
        base_full_path = os.path.join(self.work_dir, base_name)
        
        self._load_metadata(base_full_path)
        
        with open(inp_path, 'r') as f: mesh_content = f.read()

        deck = []
        deck.append("** CALCULIX DECK FOR SHELL MODEL (TIE METHOD)")
        deck.append(mesh_content) # Zawiera węzły, elementy i NSETy wygenerowane przez Gmsh
        
        # --- DEFINICJE GRUP LOGICZNYCH ---
        # Tylko te grupy, których Gmsh nie generuje automatycznie lub są specyficzne dla BC
        # NSET_SUPPORT i NSET_LOAD są w JSON, ale nie zawsze w INP od Gmsh (chyba że jako Physical Point)
        # Dla bezpieczeństwa definiujemy je jawnie, sprawdzając czy nie dublujemy nazw
        
        for g_name in ["NSET_SUPPORT", "NSET_LOAD"]:
            nodes = self.groups.get(g_name, [])
            if nodes:
                deck.append(f"*NSET, NSET={g_name}")
                for i in range(0, len(nodes), 12):
                    deck.append(", ".join(map(str, nodes[i:i+12])))
            else:
                print(f"[FEM-SHELL] WARNING: Empty group {g_name}")

        # --- MAX ID WĘZŁA ---
        max_id = max(self.nodes_map.keys()) if self.nodes_map else 100000
        
        # --- MATERIAŁY ---
        mat_name = run_params.get("Stop", "S355")
        mat_db = material_catalogue.baza_materialow()
        if mat_name in mat_db:
            m = mat_db[mat_name]
            E, G, rho = float(m['E']), float(m['G']), float(m['rho'])
            nu = (E / (2.0 * G)) - 1.0 if G > 0 else 0.3
            rho_fem = rho * 1.0e-9
        else:
            E, nu, rho_fem = 210000.0, 0.3, 7.85e-9

        deck.append("*MATERIAL, NAME=MAT_SHELL")
        deck.append("*ELASTIC")
        deck.append(f"{E}, {nu}")
        deck.append("*DENSITY")
        deck.append(f"{rho_fem}")
        
        deck.append("*MATERIAL, NAME=MAT_RIGID")
        deck.append("*ELASTIC")
        deck.append(f"{E*1000}, {nu}")
        deck.append("*DENSITY")
        deck.append("1e-12")

        # --- SEKCJE ---
        pl = run_params.get("plate_data", {})
        pr = run_params.get("profile_data", {})
        
        # ELSETy SHELL_PLATE, SHELL_WEBS itp. są już w mesh_content (z Gmsh)
        deck.append(f"*SHELL SECTION, ELSET=SHELL_PLATE, MATERIAL=MAT_SHELL\n{pl.get('tp', 10.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_WEBS, MATERIAL=MAT_SHELL\n{pr.get('twc', 6.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_FLANGES, MATERIAL=MAT_SHELL\n{pr.get('tfc', 10.0)}")

        # --- POŁĄCZENIA *TIE ---
        # Wymóg CCX: Master musi być powierzchnią (*SURFACE zdefiniowane na ELSET)
        # Slave może być zbiorem węzłów (NSET)
        
        deck.append("** --- DEFINICJA POWIERZCHNI MASTER (PŁASKOWNIK) ---")
        # SPOS - dodatnia strona powłoki (zależy od numeracji węzłów, zazwyczaj OK)
        deck.append("*SURFACE, NAME=SURF_PLATE_MASTER")
        deck.append("SHELL_PLATE, SPOS")
        
        deck.append("** --- WIĄZANIA TIE ---")
        # Obliczamy tolerancję: połowa grubości blachy + połowa grubości stopki + margines
        # Bo środnik zaczyna się w pewnej odległości od środka blachy
        gap = (float(pl.get('tp', 10.0)) + float(pr.get('tfc', 10.0))) / 2.0
        tol = gap * 1.2 # Margines 20%
        if tol < 1.0: tol = 1.0 # Minimum
        
        # Nazwy grup węzłów Slave pochodzą z Gmsh (Physical Groups) -> NSETs w pliku inp
        # Sprawdzamy czy istnieją w JSON (czy zostały znalezione)
        if self.groups.get("LINE_WELD_L_SLAVE"):
            deck.append(f"*TIE, NAME=TIE_L, POSITION TOLERANCE={tol}")
            deck.append("NSET_LINE_WELD_L_SLAVE, SURF_PLATE_MASTER") # Gmsh dodaje prefix NSET_ do nazw grup
            
        if self.groups.get("LINE_WELD_R_SLAVE"):
            deck.append(f"*TIE, NAME=TIE_R, POSITION TOLERANCE={tol}")
            deck.append("NSET_LINE_WELD_R_SLAVE, SURF_PLATE_MASTER")

        # --- RIGID ARM (Wprowadzanie obciążenia) ---
        L = float(run_params.get("Length", 1000.0))
        y_cent = float(run_params.get("Y_structure_center", 0.0))
        y_load = float(run_params.get("Y_load_level", 0.0))
        
        self.ref_node_structure = max_id + 1
        self.ref_node_load = max_id + 2
        
        deck.append("*NODE")
        deck.append(f"{self.ref_node_structure}, {L}, {y_cent}, 0.0")
        deck.append(f"{self.ref_node_load}, {L}, {y_load}, 0.0")
        
        # Łączymy strukturę z węzłem A (Rigid Body)
        # NSET_LOAD zawiera węzły na końcu belki
        if self.groups.get("NSET_LOAD"):
            deck.append(f"*RIGID BODY, NSET=NSET_LOAD, REF NODE={self.ref_node_structure}")
            
        # Element belkowy łączący A i B (ramię)
        deck.append(f"*ELEMENT, TYPE=B31, ELSET=EL_ARM")
        deck.append(f"{max_id+100}, {self.ref_node_structure}, {self.ref_node_load}")
        deck.append(f"*BEAM SECTION, ELSET=EL_ARM, MATERIAL=MAT_RIGID, SECTION=RECT\n50.0, 50.0\n1.0, 0.0, 0.0")
        
        # --- STATIC STEP ---
        deck.append("*STEP\n*STATIC")
        if self.groups.get("NSET_SUPPORT"):
            deck.append("*BOUNDARY\nNSET_SUPPORT, 1, 6, 0.0")
            
        # Zablokowanie obrotu belki ramienia, żeby nie była mechanizmem
        # deck.append(f"*BOUNDARY\n{self.ref_node_structure}, 4, 5, 0.0") # Opcjonalne
            
        deck.append("*CLOAD")
        tn = self.ref_node_load
        fx, fy, fz = float(run_params.get("Fx",0)), float(run_params.get("Fy",0)), float(run_params.get("Fz",0))
        mx, my, mz = float(run_params.get("Mx",0)), float(run_params.get("My",0)), float(run_params.get("Mz",0))
        
        if abs(fx)>1e-9: deck.append(f"{tn}, 1, {fx}")
        if abs(fy)>1e-9: deck.append(f"{tn}, 2, {fy}")
        if abs(fz)>1e-9: deck.append(f"{tn}, 3, {fz}")
        if abs(mx)>1e-9: deck.append(f"{tn}, 4, {mx}")
        if abs(my)>1e-9: deck.append(f"{tn}, 5, {my}")
        if abs(mz)>1e-9: deck.append(f"{tn}, 6, {mz}")
        
        deck.append(f"*NODE PRINT, NSET=NSET_LOAD\nU") # Monitoruj grupę LOAD
        deck.append(f"*NODE PRINT, NSET=NSET_{self.ref_node_structure}\nU") # Monitoruj ref node
        deck.append("*EL PRINT, ELSET=SHELL_PLATE\nS")
        deck.append("*END STEP")
        
        # --- BUCKLE STEP ---
        deck.append("*STEP\n*BUCKLE\n5")
        deck.append("*CLOAD")
        if abs(fx)>1e-9: deck.append(f"{tn}, 1, {fx}")
        deck.append("*NODE FILE\nU\n*END STEP")
        
        run_inp_path = inp_path.replace(".inp", "_run.inp")
        try:
            with open(run_inp_path, 'w') as f: f.write("\n".join(deck))
            return run_inp_path
        except: return None

    def run_solver(self, inp_path, work_dir, num_threads=4, callback=None):
        ccx = self.ccx_path
        if not shutil.which(ccx) and not os.path.exists(ccx):
            local = os.path.join(os.getcwd(), "ccx.exe")
            if os.path.exists(local): ccx = local
            
        job = os.path.splitext(os.path.basename(inp_path))[0]
        env = os.environ.copy(); env["OMP_NUM_THREADS"] = str(num_threads)
        
        try:
            p = subprocess.Popen([ccx, job], cwd=work_dir, env=env, shell=(os.name=='nt'),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                if callback: callback(f"CCX: {line.strip()}")
            return (p.wait() == 0)
        except Exception as e:
            if callback: callback(f"Solver Error: {e}")
            return False

    def parse_dat_results(self, dat_path):
        if not os.path.exists(dat_path): 
            return {"converged": False, "MODEL_MAX_VM": 0.0}
            
        res = {
            "MODEL_MAX_VM": 0.0, 
            "BUCKLING_FACTORS": [], 
            "DISPLACEMENTS_REF": {"Ux":0.0, "Uy":0.0, "Uz":0.0},
            "converged": False
        }
        
        step_found = False
        try:
            with open(dat_path, 'r') as f:
                mode = None
                for line in f:
                    l = line.lower().strip()
                    if "step" in l and "static" in l: mode = "static"; step_found = True
                    if "step" in l and "buckle" in l: mode = "buckle"
                    
                    if mode == "buckle" and "buckling factor" in l:
                        try: res["BUCKLING_FACTORS"].append(float(l.split()[-1]))
                        except: pass
                        
                    # Szukamy przemieszczeń węzła referencyjnego (sprawdzamy ID)
                    if mode == "static" and self.ref_node_structure:
                        parts = l.split()
                        if len(parts) > 3 and parts[0] == str(self.ref_node_structure):
                            try:
                                res["DISPLACEMENTS_REF"]["Ux"] = float(parts[1])
                                res["DISPLACEMENTS_REF"]["Uy"] = float(parts[2])
                                res["DISPLACEMENTS_REF"]["Uz"] = float(parts[3])
                            except: pass
            
            # Weryfikacja zbieżności
            # Jeśli znaleziono krok, ale przemieszczenia są 0.0 (przy niezerowej sile), to błąd
            if step_found:
                u_mag = abs(res["DISPLACEMENTS_REF"]["Uy"]) + abs(res["DISPLACEMENTS_REF"]["Uz"])
                if u_mag > 1e-9: 
                    res["converged"] = True
                    # Tutaj można by dodać czytanie Max VM z pliku frd lub dat (wymaga więcej parsowania)
                    # Dla uproszczenia wstawiamy wartość "placeholder" lub parsujemy dokładniej
                    res["MODEL_MAX_VM"] = 100.0 # Placeholder, wymaga parsowania S Mises
                else:
                    res["converged"] = False # Solver padł lub zerowe obciążenie
                    
        except: pass
        return res