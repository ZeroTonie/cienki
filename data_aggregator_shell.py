import os
import json
import math

class DataAggregatorShell:
    """
    Agregator dla modelu Shell (uproszczony).
    Zadanie:
    1. Sparować wyniki (folder).
    2. Narysować krzywą analityczną (wykres ciągły).
    3. Nanieść punkt FEM (tylko koniec belki - RefNode).
    """
    def __init__(self, router_instance):
        self.router = router_instance

    def get_available_comparisons(self):
        # Zakładamy, że wyniki lądują w folderze "FINAL" (lub dedykowanym "SHELL" w configu)
        base_dir = self.router.get_path("FINAL", "") 
        if not os.path.exists(base_dir): return []

        pairs = []
        for folder_name in os.listdir(base_dir):
            sub_path = os.path.join(base_dir, folder_name)
            if not os.path.isdir(sub_path): continue
            
            # Szukamy pliku wyników (solver zazwyczaj zapisuje results.json)
            # Musimy rozróżnić, czy to wynik Shell czy Solid.
            # Najlepiej sprawdzać zawartość lub specyficzny plik flagowy.
            path_res = os.path.join(sub_path, "results.json")
            path_ana = os.path.join(sub_path, "analytical.json")
            
            if os.path.exists(path_res) and os.path.exists(path_ana):
                try:
                    with open(path_res, 'r') as f: res_data = json.load(f)
                    
                    # Prosta heurystyka: Shell ma "DISPLACEMENTS_REF", a Solid miał mapy sensorów
                    if "DISPLACEMENTS_REF" in res_data:
                        max_vm = res_data.get("MODEL_MAX_VM", 0.0)
                        # Pobieramy pierwszy mod wyboczenia (jeśli jest)
                        buckling = res_data.get("BUCKLING_FACTORS", [])
                        buckle_str = f"Buckling: {buckling[0]:.2f}" if buckling else "No Buckle"
                        
                        label = f"[SHELL] {folder_name} | VM: {max_vm:.1f} MPa | {buckle_str}"
                        
                        pairs.append({
                            "id": folder_name,
                            "label": label,
                            "path_res": path_res,
                            "path_ana": path_ana
                        })
                except: pass
        return pairs

    def load_data(self, comparison_id):
        base_dir = self.router.get_path("FINAL", comparison_id)
        path_res = os.path.join(base_dir, "results.json")
        path_ana = os.path.join(base_dir, "analytical.json")
        
        if not os.path.exists(path_res): return None
        
        try:
            with open(path_res, 'r') as f: res_fem = json.load(f)
            res_ana = {}
            if os.path.exists(path_ana):
                with open(path_ana, 'r') as f: res_ana = json.load(f)
            return {"fem": res_fem, "ana": res_ana}
        except: return None

    def prepare_plots_data(self, data_package):
        """Generuje dane do wykresów GUI."""
        if not data_package: return {}
        
        res_fem = data_package["fem"]
        res_ana = data_package["ana"]
        plots = {}
        
        # --- PARAMETRY GEOMETRYCZNE Z ANALITYKI ---
        # Są potrzebne do narysowania krzywej teoretycznej
        L = float(res_ana.get("Input_Length", 1000.0))
        
        # --- WYKRES 1: UGIĘCIE (Uy) ---
        # Analityka: Krzywa ugięcia belki wspornikowej
        # v(x) = v_max * (x^2 * (3L - x)) / (2L^3)
        
        uy_max_ana = float(res_ana.get("Res_Disp_U_y_max", 0.0))
        
        # Generujemy punkty analityczne (np. 50 punktów dla gładkości)
        x_ana = []
        y_ana = []
        steps = 50
        for i in range(steps + 1):
            x = (i / steps) * L
            val = 0.0
            if L > 0 and uy_max_ana != 0:
                val = uy_max_ana * (x**2 * (3*L - x)) / (2 * L**3)
            x_ana.append(x)
            y_ana.append(val)
            
        # Dane FEM: Tylko punkt końcowy (Ref Node)
        fem_disp = res_fem.get("DISPLACEMENTS_REF", {})
        fem_uy = abs(float(fem_disp.get("Uy", 0.0)))
        
        plots["Deflection_Shell"] = {
            "title": "Porównanie Ugięcia: Teoria (Linia) vs FEM (Punkt)",
            "xlabel": "Długość belki [mm]",
            "ylabel": "Ugięcie [mm]",
            "series": [
                {
                    "name": "Analityka (Krzywa)", 
                    "x": x_ana, 
                    "y": y_ana, 
                    "color": "blue", 
                    "style": "--"
                },
                {
                    "name": "FEM Shell (Koniec belki)", 
                    "x": [L],       # Tylko jeden punkt X=L
                    "y": [fem_uy],  # Ugięcie FEM w tym punkcie
                    "color": "red", 
                    "style": "o",   # Marker punktowy
                    "size": 8       # Większy punkt dla widoczności
                }
            ]
        }

        # --- WYKRES 2: NAPRĘŻENIA ZREDUKOWANE ---
        # Ponieważ nie mamy mapy FEM, pokażemy to jako słupki (Bar Chart) 
        # lub po prostu linie stałe na wykresie.
        
        vm_fem = float(res_fem.get("MODEL_MAX_VM", 0.0))
        vm_ana = float(res_ana.get("Res_Max_VonMises", 0.0))
        
        plots["Stress_Comparison"] = {
            "title": "Maksymalne Naprężenia Zredukowane",
            "xlabel": "Porównanie",
            "ylabel": "Naprężenie [MPa]",
            "type": "bar",  # Sugestia dla GUI, że to wykres słupkowy
            "categories": ["Analityka", "FEM Shell"],
            "series": [
                {
                    "name": "Max Von Mises",
                    "x": ["Analityka", "FEM Shell"],
                    "y": [vm_ana, vm_fem],
                    "color": ["blue", "orange"]
                }
            ]
        }
        
        # --- INFO O WYBOCZENIU (Jako metadane do wyświetlenia) ---
        # Aggregator może zwrócić dodatkowe pole "info", jeśli GUI to obsługuje,
        # lub możemy dodać to jako tytuł wykresu.
        
        buckling_factors = res_fem.get("BUCKLING_FACTORS", [])
        if buckling_factors:
            # Tworzymy sztuczny wykres dla współczynników wyboczenia
            modes = [f"Mod {i+1}" for i in range(len(buckling_factors))]
            plots["Buckling_Modes"] = {
                "title": "Współczynniki Wyboczenia (Buckling Factors)",
                "xlabel": "Postać Wyboczenia",
                "ylabel": "Współczynnik [-]",
                "type": "bar",
                "categories": modes,
                "series": [
                    {
                        "name": "Critical Factor",
                        "x": modes,
                        "y": buckling_factors,
                        "color": "green"
                    }
                ]
            }

        return plots