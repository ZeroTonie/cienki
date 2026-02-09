import os
import subprocess
import math
import csv
import json
import re # Import modułu wyrażeń regularnych
from routing import router


class CalculixDeckBuilder:
    def __init__(self):
        self.rp_node_id = 9999999 # Hardcoded ID dla punktu referencyjnego
    
    def build_deck(self, mesh_inp_path, config, probe_map, group_nodes_map, is_buckling=False, use_nlgeom=False):
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

        # 1. Czytamy i CZYŚCIMY siatkę z Gmsha (usuwamy *HEADING z Gmsha, by nie dublować)
        clean_mesh_lines = []
        with open(mesh_inp_path, 'r') as f:
            lines = f.readlines()
            skip_next = False
            for line in lines:
                line_upper = line.strip().upper()
                
                # A. Usuwanie *HEADING (tytuł z Gmsha)
                if line_upper.startswith("*HEADING"):
                    skip_next = True # Pomiń tę linię i następną (tytuł)
                    continue
                
                # B. Usuwanie *SOLID SECTION (to naprawia błąd "nonexistent material")
                # Usuwamy sekcję zdefiniowaną przez Gmsh, bo my definiujemy własną poprawną niżej
                if line_upper.startswith("*SOLID SECTION"):
                    continue

                if skip_next:
                    skip_next = False
                    continue
                clean_mesh_lines.append(line)
        
        mesh_content = "".join(clean_mesh_lines)

        # 2. DYNAMICZNE WYSZUKIWANIE NAZWY ZBIORU 3D (Ulepszony Regex)
        # Próbujemy odczytać nazwę ELSET z linii '*ELEMENT...'.
        # Jeśli się nie uda, zakładamy, że nazywa się 'SOLID_BODY', co jest
        # teraz gwarantowane przez logikę w engine_geometry.py.
        solid_elset_name = None
        # Szukamy w oryginalnych liniach, żeby nie zgubić kontekstu
        for line in lines:
            if line.upper().startswith("*ELEMENT") and "C3D" in line.upper():
                # Obsługa: ELSET=Name, ELSET="Name", ELSET='Name'
                match = re.search(r'ELSET=["\']?([\w\d_\s]+)["\']?', line, re.IGNORECASE)
                if match:
                    solid_elset_name = match.group(1)
                    break
        
        # Fallback - jeśli z jakiegoś powodu regex nie zadziała
        if not solid_elset_name:
            solid_elset_name = "SOLID_BODY"
            print(f"[DeckBuilder] OSTRZEŻENIE: Nie znaleziono ELSET w pliku siatki. Używam domyślnego: {solid_elset_name}")

        with open(run_inp_path, 'w', newline='\n') as f: # Wymuszamy jednolite końcówki linii (LF)
            # A. Własny nagłówek (zawsze bezpieczny)
            f.write("*HEADING\nAnaliza Automatyczna\n")
            
            # B. Wklejenie wyczyszczonej siatki
            f.write(mesh_content + "\n")
            
            # C. RP Node
            f.write(f"*NODE, NSET=N_RP\n{self.rp_node_id}, {L}, {rp_y}, {rp_z}\n")
            
            # D. GRUPY (NSET) - Zabezpieczenie przed pustymi grupami
            for group_name, node_ids in group_nodes_map.items():
                if not node_ids:
                    continue # Pomijamy puste grupy, aby uniknąć błędu parsowania
                
                f.write(f"*NSET, NSET=N_{group_name}\n")
                # Zapis w blokach po 10, by nie przekroczyć limitu linii
                for i in range(0, len(node_ids), 10):
                    chunk = node_ids[i:i + 10]
                    line_str = ", ".join(map(str, chunk))
                    f.write(line_str + "\n")

            # E. Materiał
            mat = config['material']
            f.write(f"*MATERIAL, NAME=STEEL\n*ELASTIC\n{mat['E']}, {mat['nu']}\n")
            
            # F. Sekcja
            f.write(f"*SOLID SECTION, ELSET={solid_elset_name}, MATERIAL=STEEL\n")
            
            # G. Rigid Body (Tylko jeśli grupa istnieje)
            if 'GRP_LOAD' in group_nodes_map and group_nodes_map['GRP_LOAD']:
                f.write(f"*RIGID BODY, NSET=N_GRP_LOAD, REF NODE={self.rp_node_id}\n")
            
            # H. Boundary
            f.write("*BOUNDARY\n")
            if 'GRP_FIX' in group_nodes_map and group_nodes_map['GRP_FIX']:
                f.write("N_GRP_FIX, 1, 6, 0.0\n")
            
            # I. Step
            step_params = ""
            if use_nlgeom and not is_buckling:
                step_params = ", NLGEOM"
            
            f.write(f"*STEP{step_params}\n")
            
            if is_buckling:
                f.write("*BUCKLE\n3\n")
            else:
                if use_nlgeom:
                    f.write("*STATIC\n0.05, 1.0\n")
                else:
                    f.write("*STATIC\n")

            # J. Loads
            f.write("*CLOAD\n")
            if abs(Fx) > 1e-9: f.write(f"{self.rp_node_id}, 1, {-abs(Fx)}\n")
            if abs(Fy) > 1e-9: f.write(f"{self.rp_node_id}, 2, {Fy}\n")
            if abs(Fz) > 1e-9: f.write(f"{self.rp_node_id}, 3, {Fz}\n")
            if abs(Ms_x) > 1e-9: f.write(f"{self.rp_node_id}, 4, {Ms_x}\n")
            if abs(Mg_z) > 1e-9: f.write(f"{self.rp_node_id}, 6, {Mg_z}\n")
            
            # K. Outputy
            f.write("*NODE PRINT, NSET=N_RP, TOTALS=ONLY\nU, RF\n")
            
            if "GRP_INTERFACE" in group_nodes_map and group_nodes_map["GRP_INTERFACE"]:
                f.write("*NODE PRINT, NSET=N_GRP_INTERFACE\nS\n")
            
            f.write(f"*EL PRINT, ELSET={solid_elset_name}\nS\n")
            
            # Używamy mapy, by sprawdzić czy SOLID_BODY istnieje jako klucz (chociaż dla U lepiej użyć wszystkich)
            f.write("*NODE PRINT, FREQUENCY=1\nU\n") # Domyślnie wszystkie węzły
            
            if is_buckling: 
                f.write("*NODE FILE\nU\n")
            
            f.write("*END STEP\n")
        return run_inp_path


class CalculixRunner:
    def run(self, inp_path, num_cores=4, solver_type="spooles"):
        ccx = router.get_ccx_path()
        wdir = os.path.dirname(inp_path)
        job = os.path.splitext(os.path.basename(inp_path))[0]
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(num_cores)
        
        # Budowanie komendy z opcjonalnym solverem
        cmd = [ccx, "-i", job]
        if solver_type and solver_type.lower() != "spooles":
            cmd.append(f"SOLVER={solver_type}")
        log_path = os.path.join(wdir, "solver.log")
        
        try:
            p = subprocess.run(cmd, cwd=wdir, capture_output=True, text=True, env=env, check=False)
            
            # Zawsze zapisuj logi
            with open(log_path, "w", encoding='utf-8') as f:
                f.write(f"--- STDOUT ---\n{p.stdout}\n")
                if p.stderr: f.write(f"\n--- STDERR ---\n{p.stderr}\n")

            # Sprawdzanie błędów
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
        self.rp_node_id = 9999999 # Musi być zgodne z DeckBuilder

    def parse(self, work_dir, job_name, probe_map):
        dat = os.path.join(work_dir, f"{job_name}.dat")
        if not os.path.exists(dat) or os.path.getsize(dat) < 1024: 
            log_path = os.path.join(work_dir, "solver.log")
            if os.path.exists(log_path):
                # Próba odczytu logu, by rzucić lepszym błędem
                try:
                    with open(log_path, 'r') as f: 
                        log_content = f.read()
                except:
                    log_content = "Brak dostępu do logu."
                raise RuntimeError(f"Błąd Solvera! Plik .dat jest pusty lub nie istnieje.\nLog solvera:\n{log_content}")
            raise FileNotFoundError(f"Brak pliku wyników: {dat}")
        
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
        
        # Flagi stanu parsera
        current_set = None  # Jaka grupa węzłów/elementów jest czytana
        current_type = None # 'S' (stress), 'U' (disp), 'RF' (reaction force)
        
        try:
            with open(dat, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    # 1. Wykrywanie Bucklingu
                    if "BUCKLING FACTOR" in line:
                        try: res["buckling_factors"].append(float(line.split()[-1]))
                        except: pass
                        continue
                    
                    # 2. Wykrywanie nagłówków sekcji
                    # Szukamy słów kluczowych. Przykład nagłówka CalculiX:
                    # " stresses (2D integration point) for set VOLUME_1 and time  1.0000000E+00"
                    l_low = line.lower()
                    
                    if "for set" in l_low and any(k in l_low for k in ["stresses", "displacements", "reaction forces"]):
                        
                        # --- LOGIKA ROZPOZNAWANIA ZBIORU (POPRAWIONA) ---
                        if "grp_interface_r" in l_low: 
                            current_set = "INTERFACE_R"
                        elif "grp_interface_l" in l_low: 
                            current_set = "INTERFACE_L"
                        elif "grp_fix" in l_low: 
                            current_set = "FIX"
                        elif "n_rp" in l_low: 
                            current_set = "RP"
                        else:
                            # JEŚLI to nie jest żadna ze specyficznych grup powyżej,
                            # a są to wyniki (stresses/displacements), to traktujemy to jako GŁÓWNĄ BRYŁĘ (VOL).
                            # Dzięki temu nie musimy znać nazwy "Volume_1", "Solid_1" czy "vol_all".
                            current_set = "GLOBAL"
                        
                        # Rozpoznanie typu danych
                        if "stresses" in l_low: current_type = "S"
                        elif "displacements" in l_low: current_type = "U"
                        elif "reaction forces" in l_low: current_type = "RF"
                        continue

                    # Ignoruj linie niebędące danymi (nie zaczynają się od cyfry)
                    if not line or not line[0].isdigit(): continue
                    
                    parts = line.split()
                    try:
                        nid = int(parts[0])
                        vals = []
                        for p in parts[1:]:
                            try: vals.append(float(p))
                            except: pass
                        
                        # --- LOGIKA PARSOWANIA WYNIKÓW ---
                        
                        # A) NAPRĘŻENIA (S)
                        if current_type == 'S' and len(vals) >= 6:
                            # CalculiX output: node/elem, Sxx, Syy, Szz, Sxy, Sxz, Syz
                            s11,s22,s33,s12,s13,s23 = vals[:6]
                            
                            # 1. Von Mises (Dla zestawu GLOBAL liczymy Max VM dla całej bryły)
                            vm = math.sqrt(0.5*((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2+s23**2+s13**2)))
                            
                            if current_set == "GLOBAL":
                                if vm > res["max_vm"]: res["max_vm"] = vm
                            
                            # 2. Ścinanie w spoinach (rozdzielone)
                            shear_mag = math.sqrt(s12**2 + s13**2 + s23**2)
                            if current_set == "INTERFACE_R":
                                if shear_mag > res["interface_shear_R"]: res["interface_shear_R"] = shear_mag
                            elif current_set == "INTERFACE_L":
                                if shear_mag > res["interface_shear_L"]: res["interface_shear_L"] = shear_mag

                        # B) PRZEMIESZCZENIA (U)
                        elif current_type == 'U' and len(vals) >= 3:
                            u_mag = math.sqrt(vals[0]**2 + vals[1]**2 + vals[2]**2)
                            
                            if current_set == "GLOBAL":
                                if u_mag > res["max_u"]: res["max_u"] = u_mag
                            
                            # Mapowanie sond (tylko z globalnego zbioru lub jeśli trafimy na ID)
                            for pname, pdata in probe_map.items():
                                if pdata['id'] == nid:
                                    res["probes"][pname] = {
                                        "ux": vals[0], "uy": vals[1], "uz": vals[2],
                                        "mag": u_mag,
                                        "err_dx": pdata.get('dx', 0)
                                    }

                            # Wyniki dla punktu referencyjnego
                            if current_set == "RP" and nid == self.rp_node_id:
                                res["rp_results"]["U"] = {"ux": vals[0], "uy": vals[1], "uz": vals[2], "mag": u_mag}

                        # C) SIŁY REAKCJI (RF)
                        elif current_type == 'RF' and len(vals) >= 3:
                            if current_set == "FIX":
                                res["reactions"] = {"RFx": vals[0], "RFy": vals[1], "RFz": vals[2]}
                            elif current_set == "RP" and nid == self.rp_node_id:
                                res["rp_results"]["RF"] = {"RFx": vals[0], "RFy": vals[1], "RFz": vals[2]}
                                if len(vals) >= 6:
                                    res["rp_results"]["RF"].update({"RMx": vals[3], "RMy": vals[4], "RMz": vals[5]})

                    except: continue
                    
        except Exception as e:
            print(f"[FEM PARSER] Ostrzeżenie: {e}")
            
        # Ostateczna weryfikacja
        if res["max_vm"] < 1e-9 and not res["buckling_factors"]:
             # Jeśli max_vm jest 0, to znaczy że parser nie "złapał" zestawu GLOBAL
             pass 
             # Można tu dodać print warningu, ale nie raise, bo czasem model jest po prostu nienaprężony

        return res