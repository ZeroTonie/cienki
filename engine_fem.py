import os
import subprocess
import math
import csv
import sys
import shutil
import json
import time

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class NodeMapper:
    def __init__(self, nodes_csv_path):
        self.nodes = None
        self.ids = None
        self.loaded = False
        self.node_map_dict = {} 
        self.max_id = 0 
        self.load_nodes(nodes_csv_path)

    def load_nodes(self, path):
        if not os.path.exists(path): return
        try:
            data_arr = []
            ids_arr = []
            max_id = 0
            with open(path, 'r') as f:
                reader = csv.reader(f)
                next(reader) 
                for row in reader:
                    if not row: continue
                    nid = int(row[0])
                    coords = [float(row[1]), float(row[2]), float(row[3])]
                    ids_arr.append(nid)
                    data_arr.append(coords)
                    self.node_map_dict[nid] = coords
                    if nid > max_id: max_id = nid
            
            self.max_id = max_id
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
        if not self.loaded: return None
        if HAS_NUMPY:
            t = np.array([target_x, target_y, target_z])
            deltas = self.nodes - t
            dist_sq = np.einsum('ij,ij->i', deltas, deltas)
            min_idx = np.argmin(dist_sq)
            return int(self.ids[min_idx])
        else:
            best_dist = 1e12
            best_id = None
            for i, (nx, ny, nz) in enumerate(self.nodes):
                d = (nx-target_x)**2 + (ny-target_y)**2 + (nz-target_z)**2
                if d < best_dist:
                    best_dist = d
                    best_id = self.ids[i]
            return best_id

    def generate_sensor_map(self, length, profile_data, plate_data, custom_probes=None, step=50.0):
        map_result = {}
        if not self.loaded: return map_result

        hc = float(profile_data['hc'])
        bc = float(profile_data['bc'])
        twc = float(profile_data.get('twc', 5.0))
        tp = float(plate_data['tp'])
        bp = float(plate_data['bp'])
        y_int = tp/2.0
        
        ctx = {"hc":hc, "bc":bc, "twc":twc, "tp":tp, "bp":bp, "math":math}

        probes_def = {
            "P1_Center": (0.0, 0.0),
            "P2_Weld_L": (y_int, -bp/2.0),
            "P3_Weld_R": (y_int,  bp/2.0),
            "P4_Web_Mid": (y_int + hc/2.0, -bp/2.0 + twc/2.0),
            "P5_Flange_Top": (y_int + hc, -bp/2.0 + bc/2.0)
        }
        
        if custom_probes:
            for name, (expr_y, expr_z) in custom_probes.items():
                try:
                    py = eval(str(expr_y), {"__builtins__": None}, ctx)
                    pz = eval(str(expr_z), {"__builtins__": None}, ctx)
                    probes_def[name] = (float(py), float(pz))
                except: pass

        curr_x = 0.0
        if step < 1.0: step = 10.0
        while curr_x <= length + 0.1:
            x_label = int(curr_x)
            for p_name, (py, pz) in probes_def.items():
                nid = self.find_nearest_node(curr_x, py, pz)
                if nid:
                    key = f"X{x_label}_{p_name}"
                    map_result[key] = {
                        "id": nid, "orig_x": curr_x, "orig_y": py, "orig_z": pz, "probe_name": p_name
                    }
            curr_x += step
        return map_result

class FemEngine:
    def __init__(self, ccx_path="ccx"):
        self.ccx_path = ccx_path
        self.mapper = None
        self.sensor_info = {}
        self.interface_nodes = []
        self.support_nodes = [] 
        self.load_nodes = []    
        self.support_ref_node = None
        self.load_ref_node = None
        self.node_to_elements = {}

    def prepare_calculix_deck(self, inp_path, run_params):
        if not os.path.exists(inp_path): return None
        
        # Reset mapy dla każdego nowego uruchomienia
        self.node_to_elements = {}

        work_dir = os.path.dirname(inp_path)
        base = os.path.splitext(os.path.basename(inp_path))[0]
        
        self.mapper = NodeMapper(os.path.join(work_dir, f"{base}_nodes.csv"))
        if not self.mapper.loaded: return None
        
        max_mesh_id = self.mapper.max_id
        self.support_ref_node = max_mesh_id + 1
        self.load_ref_node = max_mesh_id + 2

        self.sensor_info = self.mapper.generate_sensor_map(
            float(run_params.get("Length", 1000)),
            run_params.get("profile_data", {}),
            run_params.get("plate_data", {}),
            run_params.get("custom_probes", {}),
            step=float(run_params.get("step", 50.0))
        )
        
        with open(inp_path, 'r') as f: mesh_content = f.read()

        # --- Budowanie mapy Węzeł -> Elementy ---
        lines = mesh_content.splitlines()
        element_block_lines = []
        in_element_block = False
        element_type_line = ""
        
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line: continue

            if stripped_line.upper().startswith('*ELEMENT'):
                in_element_block = True
                element_type_line = stripped_line.upper()
                continue

            if in_element_block:
                if stripped_line.startswith('*'):
                    in_element_block = False
                else:
                    element_block_lines.append(stripped_line)
        
        if element_block_lines and element_type_line:
            all_numbers_str = ' '.join(element_block_lines).replace(',', ' ').split()
            all_numbers = [int(n) for n in all_numbers_str if n.strip().isdigit()]

            nodes_per_element = 0
            if 'C3D20' in element_type_line: nodes_per_element = 20
            elif 'C3D10' in element_type_line: nodes_per_element = 10
            elif 'C3D8' in element_type_line: nodes_per_element = 8
            elif 'C3D4' in element_type_line: nodes_per_element = 4
            
            if nodes_per_element > 0 and all_numbers:
                numbers_per_entry = nodes_per_element + 1 # ID + nodes
                for i in range(0, len(all_numbers), numbers_per_entry):
                    chunk = all_numbers[i : i + numbers_per_entry]
                    if len(chunk) == numbers_per_entry:
                        element_id = chunk[0]
                        node_ids = chunk[1:]
                        for node_id in node_ids:
                            if node_id not in self.node_to_elements:
                                self.node_to_elements[node_id] = []
                            self.node_to_elements[node_id].append(element_id)

        deck = [mesh_content]
        
        groups = {}
        try:
            with open(os.path.join(work_dir, f"{base}_groups.json"), 'r') as f: 
                groups = json.load(f)
            if "GRP_INTERFACE" in groups: self.interface_nodes = groups["GRP_INTERFACE"]
            if "SURF_SUPPORT" in groups: self.support_nodes = groups["SURF_SUPPORT"]
            if "SURF_LOAD" in groups: self.load_nodes = groups["SURF_LOAD"]
        except: pass
        
        for g_name, nodes in groups.items():
            if nodes:
                deck.append(f"*NSET, NSET=NSET_{g_name}")
                for i in range(0, len(nodes), 12):
                    deck.append(", ".join(map(str, nodes[i:i+12])))
        
        deck.append("*NSET, NSET=NALL")
        all_ids = list(self.mapper.ids) if hasattr(self.mapper, 'ids') else []
        for i in range(0, len(all_ids), 12):
            deck.append(", ".join(map(str, all_ids[i:i+12])))

        # --- SEKCJA LOAD REF NODE ---
        L = float(run_params.get("Length", 1000.0))
        y_load_point = float(run_params.get("Y_ref_node", 0.0))
        
        deck.append("*NODE")
        deck.append(f"{self.load_ref_node}, {L}, {y_load_point}, 0.0")
        deck.append(f"*NSET, NSET=REF_NODES\n{self.load_ref_node}")
        
        deck.append(f"** INFO: Load Ref Node ID={self.load_ref_node}, Y={y_load_point}")
        
        if self.load_nodes:
            deck.append(f"*RIGID BODY, NSET=NSET_SURF_LOAD, REF NODE={self.load_ref_node}")
            
        E = float(run_params.get("E", 210000))
        nu = float(run_params.get("nu", 0.3))
        deck.append(f"*MATERIAL, NAME=STEEL\n*ELASTIC\n{E}, {nu}")
        deck.append("*SOLID SECTION, ELSET=VOL_ALL, MATERIAL=STEEL")
        
        # --- KROK 1: STATYKA ---
        deck.append("*STEP")
        
        solver_type = run_params.get("solver_type", "DIRECT")
        if solver_type == "ITERATIVE":
            deck.append("*STATIC, SOLVER=ITERATIVE SCALING, CHI=1e-8")
        else:
            deck.append("*STATIC")
        
        if self.support_nodes:
            deck.append("*BOUNDARY")
            deck.append("NSET_SURF_SUPPORT, 1, 3, 0.0")
        
        deck.append("*CLOAD")
        fx = float(run_params.get("Fx", 0.0))
        fy = float(run_params.get("Fy", 0.0))
        fz = float(run_params.get("Fz", 0.0))
        mx = float(run_params.get("Mx", 0.0))
        my = float(run_params.get("My", 0.0))
        mz = float(run_params.get("Mz", 0.0))
        
        if abs(fx) > 1e-9: deck.append(f"{self.load_ref_node}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{self.load_ref_node}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{self.load_ref_node}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{self.load_ref_node}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{self.load_ref_node}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{self.load_ref_node}, 6, {mz}")
        
        # Żądanie outputu reakcji dla NSET_SURF_SUPPORT
        # To spowoduje, że CCX wypisze "total force ... for set NSET_SURF_SUPPORT" w .dat
        if self.support_nodes:
            deck.append("*NODE PRINT, NSET=NSET_SURF_SUPPORT")
            deck.append("RF")
        if self.load_nodes:
            deck.append("*NODE PRINT, NSET=NSET_SURF_LOAD")
            deck.append("U")
        
        deck.append("*NODE PRINT, NSET=NALL")
        deck.append("U")
        deck.append("*EL PRINT, ELSET=VOL_ALL")
        deck.append("S")
        if self.interface_nodes:
            deck.append("*NODE PRINT, NSET=NSET_GRP_INTERFACE")
            deck.append("U")
        
        deck.append("*END STEP")
        
        # --- KROK 2: WYBOCZENIE ---
        deck.append("*STEP")
        deck.append("*BUCKLE")
        deck.append("3")
        deck.append("*CLOAD")
        if abs(fx) > 1e-9: deck.append(f"{self.load_ref_node}, 1, {fx}")
        if abs(fy) > 1e-9: deck.append(f"{self.load_ref_node}, 2, {fy}")
        if abs(fz) > 1e-9: deck.append(f"{self.load_ref_node}, 3, {fz}")
        if abs(mx) > 1e-9: deck.append(f"{self.load_ref_node}, 4, {mx}")
        if abs(my) > 1e-9: deck.append(f"{self.load_ref_node}, 5, {my}")
        if abs(mz) > 1e-9: deck.append(f"{self.load_ref_node}, 6, {mz}")

        deck.append("*NODE FILE")
        deck.append("U")
        deck.append("*END STEP")
        
        timestamp = int(time.time())
        run_inp_path = inp_path.replace(".inp", f"_run_{timestamp}.inp")
        
        with open(run_inp_path, 'w') as f: f.write("\n".join(deck))
        return run_inp_path

    def run_solver(self, inp_path, work_dir, num_threads=4, callback=None):
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
        if not os.path.exists(dat_path): return {}
        
        data_disp = {}
        raw_elem_stress = {} 
        data_force = {}  
        buckling_factors = []

        # Nowe zmienne do parsowania sumarycznych reakcji
        capturing_reactions = False
        current_step = 0

        current_type = None
        disp_parsed_header = False
        stress_parsed_header = False
        
        with open(dat_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                l_low = line.lower()

                # Wykrywanie kroku (interesuje nas Step 1 dla statyki)
                if "step" in l_low and "1" in l_low and not "end" in l_low:
                    current_step = 1
                elif "step" in l_low and "2" in l_low:
                    current_step = 2

                # Parsowanie Buckling Factor (Krok 2)
                if current_step == 2 and "buckling factor" in l_low:
                    parts = line.split()
                    try: buckling_factors.append(float(parts[-1]))
                    except: pass
                    continue
                
                # --- [POPRAWKA] Bardziej niezawodne parsowanie reakcji podporowych ---
                if "forces (rf) applied to nodes of set nset_surf_support" in l_low:
                    capturing_reactions = True
                    current_type = None # Wyłączamy inne parsery, aby uniknąć konfliktów
                    continue

                if capturing_reactions:
                    if "internal node number" in l_low:
                        continue # Pomiń linię nagłówka
                    
                    parts = line.split()
                    if not parts or not parts[0].isdigit():
                        capturing_reactions = False # Koniec bloku reakcji
                    else:
                        try:
                            nid = int(parts[0])
                            vals = [float(x) for x in parts[1:]]
                            data_force[nid] = vals
                        except ValueError:
                            capturing_reactions = False
                        continue # Linia została przetworzona, przejdź do następnej

                if "displacements" in l_low:
                    if not disp_parsed_header:
                        current_type = 'disp'
                        disp_parsed_header = True
                    else:
                        current_type = None 
                    continue
                if "stresses" in l_low:
                    if not stress_parsed_header:
                        current_type = 'stress'
                        stress_parsed_header = True
                    else:
                        current_type = None 
                    continue

                parts = line.split()
                if not parts or not parts[0].isdigit():
                    if current_type in ['disp', 'stress']:
                        current_type = None
                    continue
                
                nid = int(parts[0])
                try: vals = [float(x) for x in parts[1:]]
                except: continue
                
                if current_type == 'disp': data_disp[nid] = vals
                elif current_type == 'stress':
                    if len(vals) >= 6: 
                        s_comps = vals[:6]
                        s11, s22, s33 = s_comps[0], s_comps[1], s_comps[2]
                        s12, s23, s13 = s_comps[3], s_comps[4], s_comps[5]
                        vm = math.sqrt(0.5 * ((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s23**2 + s13**2)))
                        s_comps.append(vm)
                        raw_elem_stress[nid] = s_comps

        # --- UŚREDNIANIE WĘZŁOWE (NODAL AVERAGING) ---
        data_stress = {}
        if self.node_to_elements and self.mapper and self.mapper.loaded:
            all_node_ids = self.mapper.ids if HAS_NUMPY else list(self.mapper.node_map_dict.keys())
            for node_id in all_node_ids:
                connected_elements = self.node_to_elements.get(node_id, [])
                
                if not connected_elements:
                    data_stress[node_id] = [0.0] * 7 # S11..S13, VM
                    continue
                
                stress_tensors = [raw_elem_stress[elem_id][:6] for elem_id in connected_elements if elem_id in raw_elem_stress]

                if not stress_tensors:
                    data_stress[node_id] = [0.0] * 7
                    continue
                
                # Uśrednianie tensorów
                if HAS_NUMPY:
                    avg_tensor = np.mean(np.array(stress_tensors), axis=0).tolist()
                else:
                    num_tensors = len(stress_tensors)
                    avg_tensor = [sum(col) / num_tensors for col in zip(*stress_tensors)]
                
                # Przeliczenie Von Mises z uśrednionego tensora
                s11, s22, s33, s12, s23, s13 = avg_tensor
                avg_vm = math.sqrt(0.5 * ((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s23**2 + s13**2)))
                
                data_stress[node_id] = avg_tensor + [avg_vm]

        # --- OBLICZENIA WYNIKOWE ---
        
        # --- [POPRAWKA] Obliczanie sumarycznych reakcji i momentów podporowych ---
        total_rf = [0.0, 0.0, 0.0]  # Fx, Fy, Fz
        total_rm = [0.0, 0.0, 0.0]  # Mx, My, Mz (wokół początku układu 0,0,0)

        if self.mapper and self.mapper.loaded:
            support_ids = set(self.support_nodes)
            for nid, rf_vals in data_force.items():
                if nid in support_ids and len(rf_vals) >= 3:
                    # 1. Sumowanie sił
                    fx, fy, fz = rf_vals[0], rf_vals[1], rf_vals[2]
                    total_rf[0] += fx
                    total_rf[1] += fy
                    total_rf[2] += fz

                    # 2. Obliczanie momentów (Moment = r x F)
                    if nid in self.mapper.node_map_dict:
                        x, y, z = self.mapper.node_map_dict[nid]
                        total_rm[0] += (y * fz - z * fy)  # Moment skręcający Mx
                        total_rm[1] += (z * fx - x * fz)  # Moment gnący My
                        total_rm[2] += (x * fy - y * fx)  # Moment gnący Mz
                
        phi_deg = 0.0
        if self.load_nodes and data_disp:
            min_z, max_z = 1e9, -1e9
            n_min, n_max = None, None
            
            for nid in self.load_nodes:
                if nid in self.mapper.node_map_dict:
                    z = self.mapper.node_map_dict[nid][2]
                    if z < min_z: min_z = z; n_min = nid
                    if z > max_z: max_z = z; n_max = nid
            
            if n_min and n_max and (max_z - min_z) > 1.0:
                uy_1 = data_disp.get(n_min, [0,0,0])[1]
                uy_2 = data_disp.get(n_max, [0,0,0])[1]
                dz = max_z - min_z
                phi_rad = math.atan((uy_2 - uy_1) / dz)
                phi_deg = math.degrees(phi_rad)

        max_vm = 0.0
        for s in data_stress.values():
            if s[-1] > max_vm: max_vm = s[-1]
            
        max_u = 0.0
        full_res = {}
        if self.mapper.loaded:
            for nid, coords in self.mapper.node_map_dict.items():
                d = data_disp.get(nid, [0.0]*3)
                s = data_stress.get(nid, [0.0]*7)
                u_mag = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
                if u_mag > max_u: max_u = u_mag
                
                full_res[nid] = [coords[0], coords[1], coords[2], s[-1] if len(s)>6 else 0.0, u_mag, d[1], d[2]]

        int_data = []
        max_tau = 0.0
        for nid in self.interface_nodes:
            if nid in data_stress and nid in self.mapper.node_map_dict:
                s = data_stress[nid]
                if len(s) >= 6:
                    tau = math.sqrt(s[3]**2 + s[4]**2)
                    if tau > max_tau: max_tau = tau
                    coords = self.mapper.node_map_dict[nid]
                    int_data.append({"x": coords[0], "z": coords[2], "tau": tau})
        int_data.sort(key=lambda k: k['x'])

        sensor_res = {}
        for key, meta in self.sensor_info.items():
            nid = meta['id']
            d = data_disp.get(nid, [0,0,0])
            s = data_stress.get(nid, [0]*7)
            sensor_res[key] = {
                "X": meta['orig_x'], "U_X":d[0], "U_Y":d[1], "U_Z":d[2], "S_VM": s[-1] if len(s)>6 else 0.0
            }

        return {
            "MODEL_MAX_VM": max_vm,
            "MODEL_MAX_U": max_u,
            "BUCKLING_FACTORS": buckling_factors,
            "REACTIONS": {
                "Fx": total_rf[0], 
                "Fy": total_rf[1], 
                "Fz": total_rf[2],
                "Mx": total_rm[0],
                "My": total_rm[1],
                "Mz": total_rm[2]
            },
            "ROTATIONS": {"Rx": math.radians(phi_deg)},
            "INTERFACE_DATA": int_data,
            "INTERFACE_MAX_SHEAR": max_tau,
            "FULL_NODAL_RESULTS": full_res,
            "converged": (max_vm > 0.0)
        }