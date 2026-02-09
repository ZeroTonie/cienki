import os
import subprocess
import math
import csv
import json
import re
import sys
from routing import router


class CalculixDeckBuilder:
    def __init__(self):
        self.rp_node_id = 9999999 
    
    def build_deck(self, mesh_inp_path, config, probe_map, group_nodes_map, is_buckling=False, use_nlgeom=False):
        # Wymuszenie wypisania logu natychmiast (flush=True)
        print(f"   [DEBUG] >>> URUCHAMIAM DECK BUILDER v3 (AGRESYWNY) <<< Plik: {os.path.basename(mesh_inp_path)}", flush=True)
        
        work_dir = os.path.dirname(mesh_inp_path)
        run_inp_path = os.path.join(work_dir, "run.inp")
        
        loads = config['loads']
        Fx, Fy, Fz = float(loads['Fx']), float(loads['Fy']), float(loads['Fz'])
        r = float(loads.get('eccentricity_r', 0.0))
        sc = float(loads.get('sc_y', 0.0))
        ss = float(loads.get('ss_y', 0.0))
        
        Mg_z = Fx * r
        Ms_x = Fz * (r + sc + ss)
        
        L = float(config['geometry']['L'])
        rp_y = sc 
        rp_z = 0.0

        # 1. Czytamy i CZYŚCIMY siatkę z Gmsha
        clean_mesh_lines = []
        try:
            # errors='ignore' pozwala ominąć problemy z kodowaniem
            with open(mesh_inp_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"   [ERROR] Nie udało się otworzyć pliku siatki: {e}", flush=True)
            raise e

        skip_next = False
        removed_count = 0
        
        for line in lines:
            # Normalizacja linii: usuwamy białe znaki z boków i zamieniamy na wielkie litery
            # Usuwamy też ewentualne znaki null (\x00), które czasem psują odczyt
            line_normalized = line.strip().upper().replace('\x00', '')
            
            # A. Usuwanie *HEADING
            if line_normalized.startswith("*HEADING"):
                skip_next = True 
                continue
            
            # B. BARDZO AGRESYWNE Usuwanie *SOLID SECTION
            # Jeśli linia zawiera ciąg "SOLID SECTION", usuwamy ją.
            # Dzięki temu pozbędziemy się linii z Gmsha.
            # Naszą własną linię dodajemy później w kodzie, więc jej nie usuniemy (bo jeszcze jej tu nie ma).
            if "SOLID SECTION" in line_normalized:
                print(f"   [DeckBuilder] USUNIĘTO: {line.strip()}", flush=True)
                removed_count += 1
                continue

            if skip_next:
                skip_next = False
                continue
            
            clean_mesh_lines.append(line)
        
        if removed_count == 0:
            print("   [DeckBuilder] OSTRZEŻENIE: Nie znaleziono linii SOLID SECTION do usunięcia!", flush=True)

        mesh_content = "".join(clean_mesh_lines)

        # 2. Wyszukiwanie nazwy zbioru 3D
        solid_elset_name = None
        for line in lines:
            if "ELEMENT" in line.upper() and "C3D" in line.upper():
                match = re.search(r'ELSET=["\']?([\w\d_\s]+)["\']?', line, re.IGNORECASE)
                if match:
                    solid_elset_name = match.group(1)
                    break
        
        if not solid_elset_name:
            solid_elset_name = "SOLID_BODY"
            print(f"   [DeckBuilder] Nie wykryto ELSET, używam: {solid_elset_name}", flush=True)

        with open(run_inp_path, 'w', newline='\n') as f:
            f.write("*HEADING\nAnaliza Automatyczna\n")
            
            # Wklejamy siatkę BEZ sekcji Gmsha
            f.write(mesh_content + "\n")
            
            # Definicje węzłów i grup
            f.write(f"*NODE\n{self.rp_node_id}, {L}, {rp_y}, {rp_z}\n")
            f.write(f"*NSET, NSET=N_RP\n{self.rp_node_id}\n")
            
            for group_name, node_ids in group_nodes_map.items():
                if not node_ids: continue 
                f.write(f"*NSET, NSET=N_{group_name}\n")
                for i in range(0, len(node_ids), 10):
                    f.write(", ".join(map(str, node_ids[i:i + 10])) + "\n")

            # Materiał
            mat = config['material']
            f.write(f"*MATERIAL, NAME=STEEL\n*ELASTIC\n{mat['E']}, {mat['nu']}\n")
            
            # --- TU DEFINIUJEMY WŁAŚCIWĄ SEKCJE ---
            # To jest jedyne miejsce, gdzie *SOLID SECTION powinno wystąpić w pliku wynikowym
            f.write(f"*SOLID SECTION, ELSET={solid_elset_name}, MATERIAL=STEEL\n")
            
            # Reszta definicji (Rigid Body, Boundary, Step...)
            if 'GRP_LOAD' in group_nodes_map and group_nodes_map['GRP_LOAD']:
                f.write(f"*RIGID BODY, NSET=N_GRP_LOAD, REF NODE={self.rp_node_id}\n")
            
            f.write("*BOUNDARY\n")
            if 'GRP_FIX' in group_nodes_map and group_nodes_map['GRP_FIX']:
                f.write("N_GRP_FIX, 1, 6, 0.0\n")
            
            step_params = ", NLGEOM" if (use_nlgeom and not is_buckling) else ""
            f.write(f"*STEP{step_params}\n")
            
            if is_buckling:
                f.write("*BUCKLE\n3\n")
            else:
                if use_nlgeom: f.write("*STATIC\n0.05, 1.0\n")
                else: f.write("*STATIC\n")

            f.write("*CLOAD\n")
            if abs(Fx) > 1e-9: f.write(f"{self.rp_node_id}, 1, {-abs(Fx)}\n")
            if abs(Fy) > 1e-9: f.write(f"{self.rp_node_id}, 2, {Fy}\n")
            if abs(Fz) > 1e-9: f.write(f"{self.rp_node_id}, 3, {Fz}\n")
            if abs(Ms_x) > 1e-9: f.write(f"{self.rp_node_id}, 4, {Ms_x}\n")
            if abs(Mg_z) > 1e-9: f.write(f"{self.rp_node_id}, 6, {Mg_z}\n")
            
            f.write("*NODE PRINT, NSET=N_RP, TOTALS=ONLY\nU, RF\n")
            if "GRP_INTERFACE" in group_nodes_map and group_nodes_map["GRP_INTERFACE"]:
                f.write("*NODE PRINT, NSET=N_GRP_INTERFACE\nS\n")
            
            f.write(f"*EL PRINT, ELSET={solid_elset_name}\nS\n")
            f.write("*NODE PRINT, FREQUENCY=1\nU\n") 
            if is_buckling: f.write("*NODE FILE\nU\n")
            
            f.write("*END STEP\n")
        
        return run_inp_path


class CalculixRunner:
    def run(self, inp_path, num_cores=4, solver_type="spooles"):
        ccx = router.get_ccx_path()
        wdir = os.path.dirname(inp_path)
        job = os.path.splitext(os.path.basename(inp_path))[0]
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(num_cores)
        
        cmd = [ccx, "-i", job]
        if solver_type and solver_type.lower() != "spooles":
            cmd.append(f"SOLVER={solver_type}")
        log_path = os.path.join(wdir, "solver.log")
        
        try:
            p = subprocess.run(cmd, cwd=wdir, capture_output=True, text=True, env=env, check=False)
            
            with open(log_path, "w", encoding='utf-8') as f:
                f.write(f"--- STDOUT ---\n{p.stdout}\n")
                if p.stderr: f.write(f"\n--- STDERR ---\n{p.stderr}\n")

            output_log = p.stdout + p.stderr
            if p.returncode != 0 or "error" in output_log.lower() or "job aborted" in output_log.lower():
                error_message = f"Błąd wykonania CalculiX (job: {job}). Kod wyjścia: {p.returncode}.\n"
                error_message += f"Sprawdź plik logu: {log_path}\n\n"
                error_lines = [line for line in output_log.splitlines() if "error" in line.lower() or "warning" in line.lower()]
                if error_lines:
                    error_message += "Wykryte linie z błędami/ostrzeżeniami:\n" + "\n".join(error_lines)
                else:
                    error_message += "Nie znaleziono konkretnych linii z błędami, sprawdź cały log."
                raise RuntimeError(error_message)

            if not os.path.exists(os.path.join(wdir, f"{job}.dat")):
                raise FileNotFoundError(f"Solver zakończył pracę bez błędów, ale nie utworzył pliku .dat. Sprawdź log: {log_path}")
            
            return True
        except FileNotFoundError:
            raise FileNotFoundError(f"Nie można uruchomić CalculiX. Sprawdź, czy ścieżka '{ccx}' jest poprawna i znajduje się w PATH.")
        except Exception as e:
            if isinstance(e, RuntimeError): raise e
            raise RuntimeError(f"Nieoczekiwany błąd podczas uruchamiania CCX: {e}\nSprawdź log: {log_path}") from e

class ResultsParser:
    def __init__(self):
        self.rp_node_id = 9999999 

    def parse(self, work_dir, job_name, probe_map):
        dat = os.path.join(work_dir, f"{job_name}.dat")
        if not os.path.exists(dat) or os.path.getsize(dat) < 1024: 
            log_path = os.path.join(work_dir, "solver.log")
            try:
                with open(log_path, 'r') as f: 
                    log_content = f.read()
            except:
                log_content = "Brak dostępu do logu."
            raise RuntimeError(f"Błąd Solvera! Plik .dat jest pusty lub nie istnieje.\nLog solvera:\n{log_content}")
        
        res = {
            "max_vm": 0.0, 
            "max_u": 0.0, 
            "interface_shear_R": 0.0,
            "interface_shear_L": 0.0,
            "reactions": {},
            "rp_results": {},
            "buckling_factors": [], 
            "probes": {}
        }
        
        current_set = None  
        current_type = None 
        
        try:
            with open(dat, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    if "BUCKLING FACTOR" in line:
                        try: res["buckling_factors"].append(float(line.split()[-1]))
                        except: pass
                        continue
                    
                    l_low = line.lower()
                    
                    if "for set" in l_low and any(k in l_low for k in ["stresses", "displacements", "reaction forces"]):
                        if "grp_interface_r" in l_low: 
                            current_set = "INTERFACE_R"
                        elif "grp_interface_l" in l_low: 
                            current_set = "INTERFACE_L"
                        elif "grp_fix" in l_low: 
                            current_set = "FIX"
                        elif "n_rp" in l_low: 
                            current_set = "RP"
                        else:
                            current_set = "GLOBAL"
                        
                        if "stresses" in l_low: current_type = "S"
                        elif "displacements" in l_low: current_type = "U"
                        elif "reaction forces" in l_low: current_type = "RF"
                        continue

                    if not line or not line[0].isdigit(): continue
                    
                    parts = line.split()
                    try:
                        nid = int(parts[0])
                        vals = []
                        for p in parts[1:]:
                            try: vals.append(float(p))
                            except: pass
                        
                        if current_type == 'S' and len(vals) >= 6:
                            s11,s22,s33,s12,s13,s23 = vals[:6]
                            vm = math.sqrt(0.5*((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2+s23**2+s13**2)))
                            
                            if current_set == "GLOBAL":
                                if vm > res["max_vm"]: res["max_vm"] = vm
                            
                            shear_mag = math.sqrt(s12**2 + s13**2 + s23**2)
                            if current_set == "INTERFACE_R":
                                if shear_mag > res["interface_shear_R"]: res["interface_shear_R"] = shear_mag
                            elif current_set == "INTERFACE_L":
                                if shear_mag > res["interface_shear_L"]: res["interface_shear_L"] = shear_mag

                        elif current_type == 'U' and len(vals) >= 3:
                            u_mag = math.sqrt(vals[0]**2 + vals[1]**2 + vals[2]**2)
                            
                            if current_set == "GLOBAL":
                                if u_mag > res["max_u"]: res["max_u"] = u_mag
                            
                            for pname, pdata in probe_map.items():
                                if pdata['id'] == nid:
                                    res["probes"][pname] = {
                                        "ux": vals[0], "uy": vals[1], "uz": vals[2],
                                        "mag": u_mag,
                                        "err_dx": pdata.get('dx', 0)
                                    }

                            if current_set == "RP" and nid == self.rp_node_id:
                                res["rp_results"]["U"] = {"ux": vals[0], "uy": vals[1], "uz": vals[2], "mag": u_mag}

                        elif current_type == 'RF' and len(vals) >= 3:
                            if current_set == "FIX":
                                res["reactions"] = {"RFx": vals[0], "RFy": vals[1], "RFz": vals[2]}
                            elif current_set == "RP" and nid == self.rp_node_id:
                                res["rp_results"]["RF"] = {"RFx": vals[0], "RFy": vals[1], "RFz": vals[2]}
                                if len(vals) >= 6:
                                    res["rp_results"]["RF"].update({"RMx": vals[3], "RMy": vals[4], "RMz": vals[5]})

                    except: continue
                    
        except Exception as e:
            print(f"[FEM PARSER] Ostrzeżenie: {e}", flush=True)
            
        return res