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

        # Czytamy czystą siatkę z Gmsha
        with open(mesh_inp_path, 'r') as f:
            mesh_content = f.read()

        # --- DYNAMICZNE WYSZUKIWANIE NAZWY ZBIORU 3D ---
        # To jest kluczowa poprawka. Zamiast zakładać, że zbiór elementów 3D
        # nazywa się 'SOLID_BODY' lub 'Eall', dynamicznie odczytujemy jego nazwę
        # z linii '*ELEMENT, TYPE=C3D...'. To uniezależnia nas od zmian
        # w sposobie eksportu przez Gmsh.
        solid_elset_name = None
        for line in mesh_content.splitlines():
            if line.upper().startswith("*ELEMENT") and "C3D" in line.upper():
                match = re.search(r'ELSET=([\w\d_]+)', line, re.IGNORECASE)
                if match:
                    solid_elset_name = match.group(1)
                    break
        
        if not solid_elset_name:
            raise RuntimeError("Nie można odnaleźć zbioru elementów 3D (ELSET) w pliku siatki .inp")

        with open(run_inp_path, 'w', newline='\n') as f: # Wymuszamy jednolite końcówki linii (LF)
            # Plik mesh.inp z Gmsh już zawiera sekcję *HEADING.
            # Ręczne dodawanie drugiej powoduje błąd "more than 1", więc wklejamy tylko zawartość siatki.
            f.write(mesh_content + "\n")
            
            # RP Node - musi być zdefiniowany PRZED materiałami i sekcjami, aby zachować poprawną strukturę pliku .inp
            f.write(f"*NODE, NSET=N_RP\n{self.rp_node_id}, {L}, {rp_y}, {rp_z}\n")
            
            # RĘCZNE WSTAWIENIE GRUP (NSET) - To naprawia WARNINGI
            for group_name, node_ids in group_nodes_map.items():
                f.write(f"*NSET, NSET=N_{group_name}\n")
                for i in range(0, len(node_ids), 10):
                    f.write(", ".join(map(str, node_ids[i:i + 10])) + "\n")

            # Materiał
            mat = config['material']
            f.write(f"*MATERIAL, NAME=STEEL\n*ELASTIC\n{mat['E']}, {mat['nu']}\n")
            
            # Sekcja - Używamy dynamicznie znalezionej nazwy ELSET
            f.write(f"*SOLID SECTION, ELSET={solid_elset_name}, MATERIAL=STEEL\n")
            
            # Rigid Body
            if 'GRP_LOAD' in group_nodes_map:
                f.write(f"*RIGID BODY, NSET=N_GRP_LOAD, REF NODE={self.rp_node_id}\n")
            
            # Boundary
            f.write("*BOUNDARY\n")
            if 'GRP_FIX' in group_nodes_map:
                f.write("N_GRP_FIX, 1, 6, 0.0\n")
            
            # Step
            step = "*STEP" + (", NLGEOM" if use_nlgeom and not is_buckling else "")
            f.write(f"{step}\n")
            
            if is_buckling:
                f.write("*BUCKLE\n3\n")
            else:
                # Dla analizy nieliniowej (NLGEOM) używamy parametrów automatycznej inkrementacji.
                # Dla standardowej analizy liniowej wystarczy prosta karta *STATIC, co jest bardziej stabilne.
                if use_nlgeom:
                    f.write("*STATIC\n0.05, 1.0\n")
                else:
                    f.write("*STATIC\n")

            # Loads
            f.write("*CLOAD\n")
            if abs(Fx) > 1e-9: f.write(f"{self.rp_node_id}, 1, {-abs(Fx)}\n")
            if abs(Fy) > 1e-9: f.write(f"{self.rp_node_id}, 2, {Fy}\n")
            if abs(Fz) > 1e-9: f.write(f"{self.rp_node_id}, 3, {Fz}\n")
            if abs(Ms_x) > 1e-9: f.write(f"{self.rp_node_id}, 4, {Ms_x}\n")
            if abs(Mg_z) > 1e-9: f.write(f"{self.rp_node_id}, 6, {Mg_z}\n")
            
            # Outputy - Używamy naszych NSETów (prefiks N_)
            f.write("*NODE PRINT, NSET=N_RP, TOTALS=ONLY\nU, RF\n")
            if "GRP_INTERFACE" in group_nodes_map:
                f.write("*NODE PRINT, NSET=N_GRP_INTERFACE\nS\n")
            
            # Globalne
            # Używamy dynamicznie znalezionej nazwy ELSET dla naprężeń elementowych (S)
            f.write(f"*EL PRINT, ELSET={solid_elset_name}\nS\n")
            # Używamy NSET N_SOLID_BODY (z naszej mapy) dla przemieszczeń węzłowych (U)
            if 'SOLID_BODY' in group_nodes_map:
                f.write("*NODE PRINT, NSET=N_SOLID_BODY, FREQUENCY=1\nU\n")
            
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
        if not os.path.exists(dat) or os.path.getsize(dat) < 1024: # Plik nie istnieje lub jest podejrzanie mały
            log_path = os.path.join(work_dir, "solver.log")
            if os.path.exists(log_path):
                with open(log_path, 'r') as f: raise RuntimeError(f"Błąd Solvera! Sprawdź log: {log_path}\n{f.read()}")
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
                    
                    # 2. Wykrywanie nagłówków sekcji (bardziej odporne)
                    l_low = line.lower()
                    
                    # Reset kontekstu przy nowym nagłówku
                    # Szukamy słów kluczowych, a nie dokładnego formatu
                    if "for set" in l_low and any(k in l_low for k in ["stresses", "displacements", "reaction forces"]):
                        if "grp_interface_r" in l_low: current_set = "INTERFACE_R"
                        elif "grp_interface_l" in l_low: current_set = "INTERFACE_L"
                        elif "vol_all" in l_low: current_set = "GLOBAL"
                        elif "grp_fix" in l_low: current_set = "FIX"
                        elif "n_rp" in l_low: current_set = "RP"
                        else: current_set = "OTHER"
                        
                        if "stresses" in l_low: current_type = "S"
                        elif "displacements" in l_low: current_type = "U"
                        elif "reaction forces" in l_low: current_type = "RF"
                        continue

                    # Ignoruj linie niebędące danymi (nie zaczynają się od cyfry)
                    if not line[0].isdigit(): continue
                    
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
                            s11,s22,s33,s12,s13,s23 = vals[:6]
                            
                            # 1. Von Mises (Globalnie)
                            vm = math.sqrt(0.5*((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2+s23**2+s13**2)))
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
            
        # Ostateczna weryfikacja - jeśli VM jest nadal 0, to znaczy, że coś poszło nie tak z parsowaniem
        if res["max_vm"] < 1e-9 and not res["buckling_factors"]:
             raise ValueError("Parsowanie pliku .dat nie powiodło się. Nie znaleziono żadnych wartości naprężeń.")

        return res