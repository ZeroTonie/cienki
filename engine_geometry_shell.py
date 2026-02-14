import gmsh
import sys
import os
import json
import csv
import math

class GeometryGeneratorShell:
    def __init__(self, logger_callback=None):
        self.logger = logger_callback

    def log(self, message):
        msg = f"[GEOM-SHELL] {message}"
        if self.logger: self.logger(msg)
        else: print(msg)

    def _prepare_gmsh(self):
        try:
            if not gmsh.isInitialized(): gmsh.initialize()
            gmsh.clear()
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Geometry.Tolerance", 1e-4) 
            gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        except: pass

    def _finalize_gmsh(self):
        pass

    def generate_model(self, params):
        self._prepare_gmsh()
        try:
            # --- 1. KONFIGURACJA ---
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))
            
            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 20.0))
            order = int(mesh_cfg.get('order', 2))
            
            # Algorytm 6 (Frontal-Delaunay for 2D) jest najlepszy dla powłok
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", order)

            p_data = params['profile_data']
            pl_data = params['plate_data']
            L = float(params['length'])
            out_dir = params['output_dir']
            name = params['model_name']
            
            if not os.path.exists(out_dir): os.makedirs(out_dir)
            factory = gmsh.model.occ

            # Wymiary
            hc = float(p_data['hc'])
            bc = float(p_data['bc'])
            twc = float(p_data['twc'])
            tfc = float(p_data['tfc'])
            tp = float(pl_data['tp'])
            bp = float(pl_data['bp'])

            # --- 2. BUDOWA PROFILI (LINIE 1D NA PŁASZCZYŹNIE X=0) ---
            
            # Współrzędne Y (płaszczyzny środkowe - mid-surfaces)
            y_plate = 0.0
            # Dół stopki fizycznie styka się z górą płaskownika (tp/2).
            # Środek stopki dolnej = tp/2 + tfc/2
            y_web_bot = tp/2.0 + tfc/2.0
            y_web_top = tp/2.0 + hc - tfc/2.0
            
            # Współrzędne Z
            z_plate_L = -bp/2.0
            z_plate_R = bp/2.0
            z_web_L = -bp/2.0 + twc/2.0
            z_web_R = bp/2.0 - twc/2.0
            
            # Długość stopki (od osi środnika)
            flange_len = bc - twc/2.0

            # A. PŁASKOWNIK (Linia pozioma)
            pt_pl_1 = factory.addPoint(0, y_plate, z_plate_L)
            pt_pl_2 = factory.addPoint(0, y_plate, z_plate_R)
            l_plate = factory.addLine(pt_pl_1, pt_pl_2)
            
            # B. CEOWNIK LEWY (Kształt C)
            # Stopka dolna (do wewnątrz)
            p_LB_root = factory.addPoint(0, y_web_bot, z_web_L)
            p_LB_tip = factory.addPoint(0, y_web_bot, z_web_L + flange_len) 
            l_LB_flange = factory.addLine(p_LB_tip, p_LB_root)
            
            # Środnik (Pionowo)
            p_LT_root = factory.addPoint(0, y_web_top, z_web_L)
            l_L_web = factory.addLine(p_LB_root, p_LT_root)
            
            # Stopka górna (do wewnątrz)
            p_LT_tip = factory.addPoint(0, y_web_top, z_web_L + flange_len)
            l_LT_flange = factory.addLine(p_LT_root, p_LT_tip)
            
            # C. CEOWNIK PRAWY (Kształt C odwrócony)
            # Stopka dolna
            p_RB_root = factory.addPoint(0, y_web_bot, z_web_R)
            p_RB_tip = factory.addPoint(0, y_web_bot, z_web_R - flange_len) 
            l_RB_flange = factory.addLine(p_RB_tip, p_RB_root)
            
            # Środnik
            p_RT_root = factory.addPoint(0, y_web_top, z_web_R)
            l_R_web = factory.addLine(p_RB_root, p_RT_root)
            
            # Stopka górna
            p_RT_tip = factory.addPoint(0, y_web_top, z_web_R - flange_len)
            l_RT_flange = factory.addLine(p_RT_root, p_RT_tip)

            factory.synchronize()

            # --- 3. EKSTRUZJA (WYCIĄGNIĘCIE WZDŁUŻ X) ---
            # Tworzymy listę linii do wyciągnięcia
            # Kolejność jest WAŻNA dla późniejszego mapowania powierzchni
            profiles_to_extrude = [
                (1, l_plate),      # Index 0 -> Powierzchnia Płaskownika
                (1, l_LB_flange),  # Index 1 -> Lewy Dół
                (1, l_L_web),      # Index 2 -> Lewy Środnik
                (1, l_LT_flange),  # Index 3 -> Lewa Góra
                (1, l_RB_flange),  # Index 4 -> Prawy Dół
                (1, l_R_web),      # Index 5 -> Prawy Środnik
                (1, l_RT_flange)   # Index 6 -> Prawa Góra
            ]
            
            # Wyciągamy wszystko naraz o długość L w osi X
            ext_results = factory.extrude(profiles_to_extrude, L, 0, 0)
            factory.synchronize()

            # Odzyskiwanie tagów powierzchni (dim=2) z wyników ekstruzji
            surfs = [tag for dim, tag in ext_results if dim == 2]
            
            # Przypisanie do zmiennych
            s_plate = surfs[0]
            s_L_fbot, s_L_web, s_L_ftop = surfs[1], surfs[2], surfs[3]
            s_R_fbot, s_R_web, s_R_ftop = surfs[4], surfs[5], surfs[6]

            # --- 4. GRUPY FIZYCZNE (MATERIAL ASSIGNMENT) ---
            gmsh.model.addPhysicalGroup(2, [s_plate], name="SHELL_PLATE")
            gmsh.model.addPhysicalGroup(2, [s_L_web, s_R_web], name="SHELL_WEBS")
            gmsh.model.addPhysicalGroup(2, [s_L_fbot, s_L_ftop, s_R_fbot, s_R_ftop], name="SHELL_FLANGES")

            # --- 5. PRZYGOTOWANIE SPAWÓW (EMBED) ---
            # Rzutujemy linie środników na płaskownik, by stworzyć węzły dla wiązania TIE
            
            # Linie na płaskowniku (Y=0) pod środnikami
            pt_wL_1 = factory.addPoint(0, y_plate, z_web_L)
            pt_wL_2 = factory.addPoint(L, y_plate, z_web_L)
            l_weld_L = factory.addLine(pt_wL_1, pt_wL_2)
            
            pt_wR_1 = factory.addPoint(0, y_plate, z_web_R)
            pt_wR_2 = factory.addPoint(L, y_plate, z_web_R)
            l_weld_R = factory.addLine(pt_wR_1, pt_wR_2)
            
            factory.synchronize()
            
            # Wtapiamy (Embed) te linie w powierzchnię płaskownika
            gmsh.model.mesh.embed(1, [l_weld_L, l_weld_R], 2, s_plate)
            
            # Definicja grup Master (linie na płaskowniku)
            gmsh.model.addPhysicalGroup(1, [l_weld_L], name="LINE_WELD_L_MASTER")
            gmsh.model.addPhysicalGroup(1, [l_weld_R], name="LINE_WELD_R_MASTER")

            # Definicja grup Slave (dolne krawędzie środników)
            # Funkcja pomocnicza do znalezienia linii na krawędzi powierzchni
            def get_boundary_lines_at_y(surf_tag, y_target, tol=0.1):
                found_lines = []
                bounds = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
                for dim, tag in bounds:
                    # Sprawdzamy współrzędną Y środka linii
                    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(1, tag)
                    y_mid = (ymin + ymax) / 2.0
                    if abs(y_mid - y_target) < tol:
                        found_lines.append(tag)
                return found_lines

            # Szukamy dolnych krawędzi środników (na poziomie y_web_bot)
            # Uwaga: Środnik zaczyna się od y_web_bot.
            slave_L_lines = get_boundary_lines_at_y(s_L_web, y_web_bot)
            slave_R_lines = get_boundary_lines_at_y(s_R_web, y_web_bot)
            
            if slave_L_lines: gmsh.model.addPhysicalGroup(1, slave_L_lines, name="LINE_WELD_L_SLAVE")
            if slave_R_lines: gmsh.model.addPhysicalGroup(1, slave_R_lines, name="LINE_WELD_R_SLAVE")

            # --- 6. SIATKOWANIE ---
            # Ustawiamy rozmiar siatki globalnie na punkty
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), lc_global)
            
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(2)
            
            if order == 2:
                self.log("Konwersja do elementow 2. rzedu...")
                gmsh.model.mesh.setOrder(2)

            # --- 7. EKSPORT ---
            path_inp = os.path.join(out_dir, f"{name}_shell.inp")
            path_msh = os.path.join(out_dir, f"{name}_shell.msh")
            groups_json = os.path.join(out_dir, f"{name}_shell_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_shell_nodes.csv")

            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            # --- 8. GRUPY WĘZŁÓW DLA SOLVERA ---
            # Tolerancja 1.0mm jest bezpieczna przy tej metodzie
            supp_nodes = self._get_nodes_in_x_plane(0.0, tol=1.0)
            load_nodes = self._get_nodes_in_x_plane(L, tol=1.0)
            
            self.log(f"Wezly Support: {len(supp_nodes)}, Load: {len(load_nodes)}")

            weld_groups = {}
            for gname in ["LINE_WELD_L_MASTER", "LINE_WELD_R_MASTER", "LINE_WELD_L_SLAVE", "LINE_WELD_R_SLAVE"]:
                nodes = self._get_nodes_from_physical_group(1, gname)
                weld_groups[gname] = nodes

            groups_data = {
                "NSET_SUPPORT": supp_nodes,
                "NSET_LOAD": load_nodes,
                **weld_groups
            }
            
            with open(groups_json, 'w') as f:
                json.dump(groups_data, f)
            
            self._export_node_map(nodes_csv)

            return {
                "paths": {
                    "inp": os.path.abspath(path_inp),
                    "nodes_csv": os.path.abspath(nodes_csv),
                    "groups_json": os.path.abspath(groups_json)
                },
                "stats": {"nodes": gmsh.model.mesh.getNodes()[0].size}
            }
            
        except Exception as e:
            self.log(f"CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            self._finalize_gmsh()

    def _get_nodes_in_x_plane(self, x_loc, tol=1.0):
        """Pobiera ID węzłów leżących na płaszczyźnie X = x_loc (z dużą tolerancją)."""
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        selected = []
        for i in range(len(node_tags)):
            if abs(coords[3*i] - x_loc) < tol:
                selected.append(int(node_tags[i]))
        return selected

    def _get_nodes_from_physical_group(self, dim, name):
        try:
            group_tags = gmsh.model.getPhysicalGroups(dim)
            target_tag = -1
            for d, t in group_tags:
                if gmsh.model.getPhysicalName(d, t) == name:
                    target_tag = t
                    break
            if target_tag == -1: return []
            
            entities = gmsh.model.getEntitiesForPhysicalGroup(dim, target_tag)
            all_nodes = set()
            for e in entities:
                tags, _, _ = gmsh.model.mesh.getNodes(dim, e, includeBoundary=True)
                for t in tags: all_nodes.add(int(t))
            return list(all_nodes)
        except: return []

    def _export_node_map(self, path):
        tags, coords, _ = gmsh.model.mesh.getNodes()
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["NodeID", "X", "Y", "Z"])
            for i in range(len(tags)):
                w.writerow([int(tags[i]), coords[3*i], coords[3*i+1], coords[3*i+2]])