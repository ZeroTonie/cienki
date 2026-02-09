import os
import json
import math
import re
import numpy as np # <--- WYMAGANE DLA LINII TRENDU

class DataAggregator:
    """
    Moduł odpowiedzialny za:
    1. Skanowanie folderu FINAL w poszukiwaniu wyników.
    2. Parowanie wyników Analitycznych z FEM.
    3. Przetwarzanie surowych danych z sond (Probes) na wykresy X-Y.
    4. Generowanie linii trendu (aproksymacja wielomianowa).
    """
    def __init__(self, router_instance):
        self.router = router_instance

    def get_available_comparisons(self):
        """
        Skanuje folder FINAL. Zwraca listę dostępnych symulacji,
        które mają zarówno results.json (FEM) jak i analytical.json (Input).
        """
        final_dir = self.router.get_path("FINAL", "") 
        if not os.path.exists(final_dir): return []

        pairs = []
        items = os.listdir(final_dir)
        for item in items:
            sub_path = os.path.join(final_dir, item)
            
            # Wariant A: Podfolder dla symulacji
            if os.path.isdir(sub_path):
                path_fem = os.path.join(sub_path, "results.json")
                path_ana = os.path.join(sub_path, "analytical.json")
                
                if os.path.exists(path_fem):
                    if os.path.exists(path_ana):
                        pairs.append(self._make_entry(item, path_fem, path_ana))
                    else:
                        # Fallback: Sama analityka
                        pairs.append(self._make_entry(item, path_fem, None))

        return pairs

    def _make_entry(self, sim_id, path_fem, path_ana):
        return {
            "id": sim_id,
            "path_fem": path_fem,
            "path_ana": path_ana,
            "folder": os.path.dirname(path_fem)
        }

    def load_comparison_data(self, sim_id):
        """Ładuje pełne dane (JSONy) dla wybranego ID."""
        pairs = self.get_available_comparisons()
        target = next((p for p in pairs if p['id'] == sim_id), None)
        
        if not target: return None
        
        data = {"fem": {}, "ana": {}, "dir": target['folder']}
        
        try:
            with open(target['path_fem'], 'r') as f: 
                data["fem"] = json.load(f)
        except: pass
        
        if target['path_ana']:
            try:
                with open(target['path_ana'], 'r') as f: 
                    data["ana"] = json.load(f)
            except: pass
            
        return data

    def prepare_plots_data(self, data_package):
        """
        Konwertuje słownik sond (probes) na serie danych do wykresów.
        Generuje również linie trendu.
        """
        res_fem = data_package["fem"]
        res_ana = data_package["ana"]
        
        plots = {}
        probes = res_fem.get("probes", {})
        if not probes: return plots
        
        # 1. Parsowanie sond
        series_data = {}
        
        for key, vals in probes.items():
            # Oczekiwany format klucza: "Nazwa_X{liczba}"
            match = re.search(r"(.*)_X(\d+)$", key)
            if match:
                base_name = match.group(1)
                x_val = int(match.group(2))
                
                if base_name not in series_data: series_data[base_name] = []
                
                uy = vals.get("uy", 0.0)
                uz = vals.get("uz", 0.0)
                
                series_data[base_name].append({
                    "x": x_val, "uy": uy, "uz": uz
                })
        
        # Sortowanie po X
        for name in series_data:
            series_data[name].sort(key=lambda k: k['x'])

        # 2. Generowanie wykresów
        L = float(res_ana.get("Input_Load_L", res_ana.get("L", 1000)))
        
        # Wybór głównej sondy
        primary_probe = "User_Center" if "User_Center" in series_data else list(series_data.keys())[0] if series_data else None
        
        # --- FUNKCJA POMOCNICZA DO TRENDU (BRAKOWAŁO TEGO) ---
        def add_trendline(x_data, y_data, plot_dict, label_suffix="Trend"):
            if len(x_data) > 3:
                try:
                    # Dopasowanie wielomianu 3. stopnia (odpowiednie dla belki wspornikowej)
                    z = np.polyfit(x_data, y_data, 3)
                    p = np.poly1d(z)
                    
                    x_smooth = np.linspace(min(x_data), max(x_data), 100)
                    y_smooth = p(x_smooth)
                    
                    plot_dict["series"].append({
                        "name": f"Trend {label_suffix} (Poly3)", 
                        "x": x_smooth, "y": y_smooth, 
                        "color": "yellow", "style": "--", "linewidth": 1
                    })
                except Exception as e:
                    print(f"Błąd trendu: {e}")

        # A) UGIĘCIE Y (Słaba oś / Mimośród)
        if primary_probe:
            data_pts = series_data[primary_probe]
            X = [p['x'] for p in data_pts]
            Y_fem = [abs(p['uy']) for p in data_pts] # Ugięcie Y
            
            plots["Deflection_Uy"] = {
                "title": f"Ugięcie Uy (Oś słaba) - Sonda: {primary_probe}",
                "xlabel": "Długość belki [mm]",
                "ylabel": "Przemieszczenie [mm]",
                "series": [
                    {"name": "FEM Punkty", "x": X, "y": Y_fem, "color": "cyan", "style": "o"}
                ]
            }
            
            # --- DODANIE LINII TRENDU (NOWE) ---
            add_trendline(X, Y_fem, plots["Deflection_Uy"], "FEM")
            
            # Teoria (Analityka)
            uy_max_ana = float(res_ana.get("Res_Disp_U_y_max", 0.0))
            if uy_max_ana > 0:
                Y_ana = []
                for x in X:
                    val = uy_max_ana * (x**2 * (3*L - x)) / (2 * L**3)
                    Y_ana.append(val)
                
                plots["Deflection_Uy"]["series"].append(
                    {"name": "Teoria", "x": X, "y": Y_ana, "color": "orange", "style": "--"}
                )

        # B) UGIĘCIE Z (Mocna oś / Siła poprzeczna)
        if primary_probe:
            data_pts = series_data[primary_probe]
            X = [p['x'] for p in data_pts]
            Z_fem = [abs(p['uz']) for p in data_pts]
            
            plots["Deflection_Uz"] = {
                "title": f"Ugięcie Uz (Oś mocna) - Sonda: {primary_probe}",
                "xlabel": "Długość belki [mm]",
                "ylabel": "Przemieszczenie [mm]",
                "series": [
                    {"name": "FEM Punkty", "x": X, "y": Z_fem, "color": "magenta", "style": "o"}
                ]
            }
            
            # --- DODANIE LINII TRENDU (NOWE) ---
            add_trendline(X, Z_fem, plots["Deflection_Uz"], "FEM")
            
            # Teoria
            uz_max_ana = float(res_ana.get("Res_Disp_U_z_max", 0.0))
            if uz_max_ana > 0:
                Z_ana = [uz_max_ana * (x**2 * (3*L - x)) / (2 * L**3) for x in X]
                plots["Deflection_Uz"]["series"].append(
                    {"name": "Teoria", "x": X, "y": Z_ana, "color": "green", "style": "--"}
                )

        return plots

    def get_mesh_data_path(self, data_package):
        """Zwraca ścieżkę do pliku .msh w celu wizualizacji 3D."""
        if not data_package: return None, None
        
        fem_dir = data_package["dir"]
        # Sprawdzamy klucz w JSON
        mesh_path_json = data_package["fem"].get("mesh_path")
        
        # Jeśli ścieżka w JSON jest bezwzględna i istnieje, użyj jej
        if mesh_path_json and os.path.exists(mesh_path_json):
            return mesh_path_json, None
            
        # Jeśli nie, szukamy w folderze
        for f in os.listdir(fem_dir):
            if f.endswith(".inp") and "mesh" in f:
                return os.path.join(fem_dir, f), None
                
        return None, None