import os
import json
import math
import numpy as np
import pandas as pd

class DataAggregator:
    """
    Moduł odpowiedzialny za:
    1. Parowanie wyników Analitycznych (00_Analityka) z FEM (03_Final).
    2. Przygotowywanie serii danych do wykresów.
    3. Obsługę ścieżek do wizualizacji 3D.
    """
    def __init__(self, router_instance):
        self.router = router_instance

    def get_available_comparisons(self):
        """Skanuje foldery FEM w poszukiwaniu kompletnych par wyników."""
        fem_dir = self.router.get_path("FINAL", "") 
        if not os.path.exists(fem_dir): return []

        pairs = []
        for folder_name in os.listdir(fem_dir):
            sub_path = os.path.join(fem_dir, folder_name)
            if not os.path.isdir(sub_path): continue
            
            path_fem = os.path.join(sub_path, "results.json")
            path_ana = os.path.join(sub_path, "analytical.json")
            
            if os.path.exists(path_fem) and os.path.exists(path_ana):
                try:
                    with open(path_ana, 'r') as f: ana_data = json.load(f)
                    
                    # Etykieta do listy w GUI
                    label = f"{folder_name} | MaxVM: {ana_data.get('Res_Max_VonMises',0):.1f} MPa"
                    pairs.append({
                        "id": folder_name,
                        "label": label,
                        "path_fem": path_fem,
                        "path_ana": path_ana,
                        "folder": sub_path
                    })
                except: pass
                
        return pairs

    def load_comparison_data(self, comparison_id):
        """Ładuje pełne dane dla wybranego ID (nazwy folderu)."""
        fem_dir = self.router.get_path("FINAL", comparison_id)
        path_fem = os.path.join(fem_dir, "results.json")
        path_ana = os.path.join(fem_dir, "analytical.json")
        
        if not os.path.exists(path_fem) or not os.path.exists(path_ana):
            return None
            
        try:
            with open(path_fem, 'r') as f: res_fem = json.load(f)
            with open(path_ana, 'r') as f: res_ana = json.load(f)
            return {"fem": res_fem, "ana": res_ana, "dir": fem_dir}
        except Exception as e:
            print(f"[AGGREGATOR] Błąd ładowania danych: {e}")
            return None

    def _get_val(self, data, key, alt_keys=[]):
        """Pomocnicza funkcja do bezpiecznego pobierania wartości."""
        if key in data: return float(data[key])
        for k in alt_keys:
            if k in data: return float(data[k])
        return 0.0

    def prepare_plots_data(self, data_package):
        """
        Przygotowuje słownik z seriami danych do wykresów (X, Y) dla GUI.
        """
        res_fem = data_package["fem"]
        res_ana = data_package["ana"]
        
        plots = {}
        
        # --- 1. FILTROWANIE DANYCH FEM (SONDY) ---
        sensors = []
        # Szukamy kluczy w formacie "X{liczba}_{Nazwa}"
        for k, v in res_fem.items():
            if k.startswith("X") and isinstance(v, dict) and "X" in v:
                sensors.append(v)
        
        if not sensors: return plots
        
        # Sortujemy po współrzędnej X (długość belki)
        sensors.sort(key=lambda s: s['X'])
        
        # Oś X [0...L]
        L_fem = sensors[-1]['X']
        x_axis = [s['X'] for s in sensors]
        
        # --- 2. DOKŁADNE FUNKCJE TEORETYCZNE (Przywrócone z Twojego kodu) ---
        
        def beam_shape_cantilever(x, u_max, length):
            """Funkcja kształtu dla wspornika obciążonego na końcu (dokładna)."""
            if length == 0: return 0
            # Wzór: v(x) = P*x^2/(6EI) * (3L - x)
            # Przy x=L, v_max = P*L^3/(3EI)
            # Stosunek v(x)/v_max = (x^2 * (3L - x)) / (2L^3)
            return u_max * (x**2 * (3*length - x)) / (2 * length**3)

        # --- 3. GENEROWANIE SERII DANYCH ---
        
        # A) Ugięcie U_Y (Słaba oś - P1_Center)
        # Filtrujemy tylko sondy środkowe
        s_p1 = [s for s in sensors if s.get("probe_name") == "P1_Center"]
        
        if s_p1:
            x_p1 = [s['X'] for s in s_p1]
            
            # Pobieramy wartość początkową (offset), aby wykres startował od 0
            u0_y = s_p1[0]['U_Y']
            y_fem_uy = [abs(s['U_Y'] - u0_y) for s in s_p1]
            
            plots["Deflection_Uy"] = {
                "title": "Ugięcie osi słabej (Uy)",
                "xlabel": "Długość belki [mm]",
                "ylabel": "Ugięcie [mm]",
                "series": [
                    {"name": "FEM (P1 Center)", "x": x_p1, "y": y_fem_uy, "color": "red", "style": "-o"}
                ]
            }
            
            # Teoria
            uy_max_ana = self._get_val(res_ana, "Res_Disp_U_y_max", ["Przemieszczenia", "U_y_max"])
            if uy_max_ana > 0:
                y_ana = [beam_shape_cantilever(x, uy_max_ana, L_fem) for x in x_p1]
                plots["Deflection_Uy"]["series"].append(
                    {"name": "Analityka (Teoria)", "x": x_p1, "y": y_ana, "color": "blue", "style": "--"}
                )

        # B) Naprężenia w Spoinie (Interface)
        if "INTERFACE_DATA" in res_fem and res_fem["INTERFACE_DATA"]:
            int_data = res_fem["INTERFACE_DATA"]
            # Sprawdzamy, czy mamy dane do mapy (x, z, tau)
            if int_data and 'z' in int_data[0] and 'tau' in int_data[0]:
                x_coords = [p['x'] for p in int_data]
                z_coords = [p['z'] for p in int_data]
                tau_vals = [p['tau'] for p in int_data]
                
                plots["Interface_Shear_Map"] = {
                    "title": "Mapa naprężeń tnących w spoinie",
                    "xlabel": "Długość belki [mm]",
                    "ylabel": "Pozycja w szerokości [mm]",
                    "type": "scatter", # Nowy typ wykresu
                    "series": [
                        {
                            "name": "FEM (Interface)", 
                            "x": x_coords, 
                            "y": z_coords, 
                            "c": tau_vals, # Dane do koloru
                            "cmap": "jet"
                        }
                    ]
                }
            else: # Fallback do starego wykresu liniowego
                x_int = [p['x'] for p in int_data]
                y_int = [p['tau'] for p in int_data]
                tau_ana = self._get_val(res_ana, "Res_Weld_Tau", ["Spoina", "Tau_max"])
                plots["Interface_Shear_Line"] = {
                    "title": "Naprężenia tnące w spoinie (Tau vs X)",
                    "xlabel": "Długość belki [mm]",
                    "ylabel": "Naprężenie [MPa]",
                    "series": [
                        {"name": "FEM (Interface)", "x": x_int, "y": y_int, "color": "magenta", "style": "."},
                        {"name": "Analityka (Max)", "x": [0, L_fem], "y": [tau_ana, tau_ana], "color": "green", "style": "--"}
                    ]
                }

        # C) Naprężenia VonMises wzdłuż belki (P1_Center)
        # Dodatkowy wykres, który mógł być przydatny
        if s_p1:
            x_vm = [s['X'] for s in s_p1]
            y_vm = [s['S_VM'] for s in s_p1]
            
            vm_ana = self._get_val(res_ana, "Res_Max_VonMises", ["Wytezenie", "Sigma_red"])
            
            plots["Stress_VM"] = {
                "title": "Naprężenia zredukowane (P1 Center)",
                "xlabel": "Długość belki [mm]",
                "ylabel": "Naprężenie [MPa]",
                "series": [
                    {"name": "FEM (P1 VM)", "x": x_vm, "y": y_vm, "color": "orange", "style": "-o"},
                    {"name": "Analityka (Max)", "x": [0, L_fem], "y": [vm_ana, vm_ana], "color": "black", "style": "--"}
                ]
            }

        return plots

    def get_mesh_data_path(self, data_package):
        """Zwraca ścieżki do plików .msh (siatka) i .json (wyniki węzłowe) dla wizualizacji 3D."""
        if not data_package: return None, None
        
        fem_dir = data_package["dir"]
        # Nazwa pliku .msh zazwyczaj taka sama jak folderu
        msh_files = [f for f in os.listdir(fem_dir) if f.endswith(".msh")]
        if not msh_files: return None, None
        
        path_msh = os.path.join(fem_dir, msh_files[0])
        path_res = os.path.join(fem_dir, "results.json")
        
        return path_msh, path_res