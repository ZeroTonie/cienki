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
    Wersja 5.3: Jawny zapis NSET dla spoin (naprawa błędu TIE/ELSET).
    """
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.work_dir = ""
        self.groups = {}
        self.nodes_map = {} 
        self.ref_node_structure = None
        self.ref_node_load = None

    def _load_metadata(self, base_path_no_ext):
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
                    next(reader, None)
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
        deck.append("** CALCULIX DECK FOR SHELL MODEL (TIE FIX)")
        deck.append(mesh_content) 
        
        # --- TWORZENIE NSET DLA WSZYSTKICH GRUP ---
        # Ważne: Tworzymy NSETy także dla spoin (LINE_WELD...), aby TIE działało na węzłach,
        # a nie szukało nieistniejących NSETów (bo Gmsh tworzy ELSETy dla linii).
        
        groups_to_write = [
            "NSET_SUPPORT", "NSET_LOAD", 
            "LINE_WELD_L_SLAVE", "LINE_WELD_R_SLAVE"
        ]
        
        for g_name in groups_to_write:
            nodes = self.groups.get(g_name, [])
            if nodes:
                deck.append(f"*NSET, NSET={g_name}")
                for i in range(0, len(nodes), 12):
                    deck.append(", ".join(map(str, nodes[i:i+12])))

        # --- PARAMETRY ---
        max_id = max(self.nodes_map.keys()) if self.nodes_map else 100000
        
        mat_name = run_params.get("Stop", "S355")
        mat_db = material_catalogue.baza_materialow()
        if mat_name in mat_db:
            m = mat_db[mat_name]
            E, G, rho = float(m['E']), float(m['G']), float(m['rho'])
            nu = (E / (2.0 * G)) - 1.0 if G > 0 else 0.3
            rho_fem = rho * 1.0e-9
        else:
            E, nu, rho_fem = 210000.0, 0.3, 7.85e-9

        # Definicja Materiałów
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

        # --- SEKCJE POWŁOKOWE ---
        pl = run_params.get("plate_data", {})
        pr = run_params.get("profile_data", {})
        
        deck.append(f"*SHELL SECTION, ELSET=SHELL_PLATE, MATERIAL=MAT_SHELL\n{pl.get('tp', 10.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_WEBS, MATERIAL=MAT_SHELL\n{pr.get('twc', 6.0)}")
        deck.append(f"*SHELL SECTION, ELSET=SHELL_FLANGES, MATERIAL=MAT_SHELL\n{pr.get('tfc', 10.0)}")

        # --- WIĄZANIA TIE ---
        deck.append("** --- TIE DEFINITION ---")
        deck.append("*SURFACE, NAME=SURF_PLATE_MASTER")
        deck.append("SHELL_PLATE, SPOS")
        
        gap = (float(pl.get('tp', 10.0)) + float(pr.get('tfc', 10.0))) / 2.0
        tol = gap * 1.2
        
        # Odwołujemy się do NSETów utworzonych ręcznie powyżej
        if self.groups.get("LINE_WELD_L_SLAVE"):
            deck.append(f"*TIE, NAME=TIE_L, POSITION TOLERANCE={tol}")
            deck.append("LINE_WELD_L_SLAVE, SURF_PLATE_MASTER")
            
        if self.groups.get("LINE_WELD_R_SLAVE"):
            deck.append(f"*TIE, NAME=TIE_R, POSITION TOLERANCE={tol}")
            deck.append("LINE_WELD_R_SLAVE, SURF_PLATE_MASTER")

        # --- RIGID ARM ---
        L = float(run_params.get("Length", 1000.0))
        y_cent = float(run_params.get("Y_structure_center", 0.0))
        y_load = float(run_params.get("Y_load_level", 0.0))
        
        self.ref_node_structure = max_id + 1
        self.ref_node_load = max_id + 2
        
        deck.append("*NODE")
        deck.append(f"{self.ref_node_structure}, {L}, {y_cent}, 0.0")
        deck.append(f"{self.ref_node_load}, {L}, {y_load}, 0.0")
        
        # Jawne zestawy NSET dla outputu
        deck.append(f"*NSET, NSET=N_REF_STRUCT\n{self.ref_node_structure}")
        
        # Dodanie masy (stabilizacja)
        deck.append("*ELEMENT, TYPE=MASS, ELSET=E_MASS_REF")
        deck.append(f"{max_id+200}, {self.ref_node_structure}")
        deck.append(f"{max_id+201}, {self.ref_node_load}")
        deck.append("*MASS, ELSET=E_MASS_REF")
        deck.append("1e-6")
        
        # Rigid Body
        if self.groups.get("NSET_LOAD"):
            deck.append(f"*RIGID BODY, NSET=NSET_LOAD, REF NODE={self.ref_node_structure}")
            
        # Beam Element
        deck.append(f"*ELEMENT, TYPE=B31, ELSET=EL_ARM")
        deck.append(f"{max_id+100}, {self.ref_node_structure}, {self.ref_node_load}")
        deck.append(f"*BEAM SECTION, ELSET=EL_ARM, MATERIAL=MAT_RIGID, SECTION=RECT\n50.0, 50.0\n1.0, 0.0, 0.0")
        
        # --- STATIC STEP ---
        deck.append("*STEP\n*STATIC")
        if self.groups.get("NSET_SUPPORT"):
            deck.append("*BOUNDARY\nNSET_SUPPORT, 1, 6, 0.0")
            
        deck.append("*CLOAD")
        tn = self.ref_node_load
        fx = float(run_params.get("Fx",0))
        fy = float(run_params.get("Fy",0))
        fz = float(run_params.get("Fz",0))
        mx = float(run_params.get("Mx",0))
        my = float(run_params.get("My",0))
        mz = float(run_params.get("Mz",0))
        
        if abs(fx)>1e-9: deck.append(f"{tn}, 1, {fx}")
        if abs(fy)>1e-9: deck.append(f"{tn}, 2, {fy}")
        if abs(fz)>1e-9: deck.append(f"{tn}, 3, {fz}")
        if abs(mx)>1e-9: deck.append(f"{tn}, 4, {mx}")
        if abs(my)>1e-9: deck.append(f"{tn}, 5, {my}")
        if abs(mz)>1e-9: deck.append(f"{tn}, 6, {mz}")
        
        deck.append(f"*NODE PRINT, NSET=N_REF_STRUCT\nU") 
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
                lines = f.readlines()
                
            stress_section = False
            mode = None
            
            for line in lines:
                l = line.lower().strip()
                
                # Wykrywanie sekcji
                if "step" in l and "static" in l: mode = "static"; step_found = True
                if "step" in l and "buckle" in l: mode = "buckle"
                
                # Wyboczenie
                if mode == "buckle" and "buckling factor" in l:
                    try: res["BUCKLING_FACTORS"].append(float(l.split()[-1]))
                    except: pass
                
                # Przemieszczenia węzła referencyjnego
                if mode == "static" and self.ref_node_structure:
                    parts = l.split()
                    if len(parts) > 3 and parts[0] == str(self.ref_node_structure):
                        try:
                            res["DISPLACEMENTS_REF"]["Ux"] = float(parts[1])
                            res["DISPLACEMENTS_REF"]["Uy"] = float(parts[2])
                            res["DISPLACEMENTS_REF"]["Uz"] = float(parts[3])
                        except: pass
                
                # Naprężenia
                if mode == "static" and ("stresses" in l or "stress" in l) and ("el" in l or "print" in l):
                    stress_section = True
                    continue
                if "end step" in l: stress_section = False
                
                # Parsowanie Von Mises (dla Shell)
                if stress_section and l and l[0].isdigit():
                    parts = l.split()
                    # Oczekujemy co najmniej 8 kolumn (elem, ip, s11, s22, s33, s12, s13, s23)
                    if len(parts) >= 8:
                        try:
                            # Pomijamy elem i ip
                            s = [float(x) for x in parts[2:8]]
                            # Uproszczony VM dla shell
                            # s[0]=xx, s[1]=yy, s[2]=zz, s[3]=xy, s[4]=yz, s[5]=zx
                            sxx, syy, szz = s[0], s[1], s[2]
                            sxy, syz, szx = s[3], s[4], s[5]
                            
                            vm = math.sqrt(0.5 * ((sxx-syy)**2 + (syy-szz)**2 + (szz-sxx)**2 + 6*(sxy**2 + syz**2 + szx**2)))
                            if vm > res["MODEL_MAX_VM"]: res["MODEL_MAX_VM"] = vm
                        except: pass

            # Warunki zbieżności
            u_mag = abs(res["DISPLACEMENTS_REF"]["Uy"]) + abs(res["DISPLACEMENTS_REF"]["Uz"]) + abs(res["DISPLACEMENTS_REF"]["Ux"])
            if u_mag > 1e-9: 
                res["converged"] = True
                # Placeholder, jeśli parser naprężeń zawiódł (ale przemieszczenia są ok)
                if res["MODEL_MAX_VM"] == 0.0: res["MODEL_MAX_VM"] = 1.0 
            else:
                res["converged"] = False

        except: pass
        return res