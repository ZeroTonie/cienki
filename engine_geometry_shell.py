import gmsh
import sys
import os
import json
import csv
import math
import traceback

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
            # Ustawienia dla stabilności
            gmsh.option.setNumber("General.Terminal", 1) # Logi kernela
            gmsh.option.setNumber("Geometry.Tolerance", 1e-4) 
            gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        except: pass

    def _finalize_gmsh(self):
        # Nie zamykamy całkowicie, aby procesy nadrzędne mogły używać
        pass

    def generate_model(self, params):
        self._prepare_gmsh()
        try:
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))
            
            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 20.0))
            order = int(mesh_cfg.get('order', 2))
            
            # Algorytm 6: Frontal 2D (dobry dla Shell) lub 1: Delaunay
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

            # --- GEOMETRIA ---
            # Układ: Blacha w Y=0 (środek), Ceowniki dosunięte (z przerwą na grubości)
            
            # Współrzędne Y
            y_plate = 0.0
            # Środek stopki dolnej ceownika (odległość = połowa grubości blachy + połowa grubości stopki)
            y_web_bot = tp/2.0 + tfc/2.0
            y_web_top = tp/2.0 + hc - tfc/2.0
            
            # Współrzędne Z
            z_plate_L = -bp/2.0
            z_plate_R = bp/2.0
            
            # Środniki (odsunięte o połowę grubości środnika od krawędzi)
            z_web_L = -bp/2.0 + twc/2.0
            z_web_R = bp/2.0 - twc/2.0
            
            # Długość stopki (modelowa)
            flange_len = bc - twc/2.0

            # A. PŁASKOWNIK (Linia -> Ekstruzja)
            pt_pl_1 = factory.addPoint(0, y_plate, z_plate_L)
            pt_pl_2 = factory.addPoint(0, y_plate, z_plate_R)
            l_plate = factory.addLine(pt_pl_1, pt_pl_2)
            
            # B. CEOWNIKI (Punkty startowe przekroju)
            # Lewy
            p_LB_root = factory.addPoint(0, y_web_bot, z_web_L) # Punkt styku (wirtualnego)
            p_LB_tip = factory.addPoint(0, y_web_bot, z_web_L + flange_len) 
            l_LB_flange = factory.addLine(p_LB_tip, p_LB_root)
            
            p_LT_root = factory.addPoint(0, y_web_top, z_web_L)
            l_L_web = factory.addLine(p_LB_root, p_LT_root)
            
            p_LT_tip = factory.addPoint(0, y_web_top, z_web_L + flange_len)
            l_LT_flange = factory.addLine(p_LT_root, p_LT_tip)
            
            # Prawy
            p_RB_root = factory.addPoint(0, y_web_bot, z_web_R)
            p_RB_tip = factory.addPoint(0, y_web_bot, z_web_R - flange_len) 
            l_RB_flange = factory.addLine(p_RB_tip, p_RB_root)
            
            p_RT_root = factory.addPoint(0, y_web_top, z_web_R)
            l_R_web = factory.addLine(p_RB_root, p_RT_root)
            
            p_RT_tip = factory.addPoint(0, y_web_top, z_web_R - flange_len)
            l_RT_flange = factory.addLine(p_RT_root, p_RT_tip)

            # --- EKSTRUZJA Z JEDNOCZESNYM POBRANIEM TAGÓW ---
            # Funkcja pomocnicza zwracająca (powierzchnia, linia_góra, linia_bok, linia_dół)
            # Ale tutaj extrude(Point) -> Line, extrude(Line) -> Surface.
            
            def safe_extrude(tag_dim_1):
                # Extrude zwraca listę [(dim, tag), (dim, tag)...]
                # Dla linii (dim=1) -> [(2, surface_tag), (1, top), (1, sides)...]
                res = factory.extrude([(1, tag_dim_1)], L, 0, 0)
                surf_tag = -1
                for dim, tag in res:
                    if dim == 2: surf_tag = tag
                return surf_tag

            def safe_extrude_point(tag_dim_0):
                # Extrude Punktu -> Linia
                res = factory.extrude([(0, tag_dim_0)], L, 0, 0)
                line_tag = -1
                for dim, tag in res:
                    if dim == 1: line_tag = tag
                return line_tag

            # Ekstruzja powierzchni
            s_plate = safe_extrude(l_plate)
            
            s_L_fbot = safe_extrude(l_LB_flange)
            s_L_web  = safe_extrude(l_L_web)
            s_L_ftop = safe_extrude(l_LT_flange)
            
            s_R_fbot = safe_extrude(l_RB_flange)
            s_R_web  = safe_extrude(l_R_web)
            s_R_ftop = safe_extrude(l_RT_flange)

            # [FIX] Ekstruzja linii "styku" (dla grupy Slave)
            # Ekstrudujemy punkty startowe środników wzdłuż L, aby uzyskać krawędź
            l_weld_L_slave = safe_extrude_point(p_LB_root)
            l_weld_R_slave = safe_extrude_point(p_RB_root)

            factory.synchronize()

            # --- DEFINICJA GRUP FIZYCZNYCH ---
            # 1. Płaskownik (Master Surface)
            gmsh.model.addPhysicalGroup(2, [s_plate], name="SHELL_PLATE")
            
            # 2. Reszta profilu
            gmsh.model.addPhysicalGroup(2, [s_L_web, s_R_web], name="SHELL_WEBS")
            gmsh.model.addPhysicalGroup(2, [s_L_fbot, s_L_ftop, s_R_fbot, s_R_ftop], name="SHELL_FLANGES")

            # 3. Linie Styku (Slave Lines dla TIE)
            # Ważne: To muszą być te same linie, które są krawędziami s_L_web/s_R_web.
            # safe_extrude_point zwraca nową linię, ale ponieważ p_LB_root jest końcem l_L_web, 
            # OCC *powinien* zachować topologię lub zduplikować.
            # W OCC extrude tworzy nową geometrię. Sprawdźmy spójność.
            # Ponieważ p_LB_root był użyty do l_L_web, extrude l_L_web stworzyło s_L_web I 3 linie brzegowe.
            # Jedna z tych linii to "szyna" wzdłuż X. 
            # Użycie safe_extrude_point tworzy DUPLIKAT linii w tym samym miejscu.
            # Aby uniknąć duplikatów, lepiej pobrać brzeg powierzchni s_L_web.
            
            # [METODA BEZPIECZNA]: RemoveDuplicate, a potem pobranie linii z powierzchni.
            factory.removeAllDuplicates()
            factory.synchronize()
            
            # Funkcja znajdująca linię w powierzchni s_web na dole (y = y_web_bot)
            def get_bottom_line(surf_tag, y_target):
                boundary = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
                for dim, tag in boundary:
                    if dim == 1:
                        # Sprawdź czy linia leży na y_target
                        com = gmsh.model.occ.getCenterOfMass(1, tag)
                        if abs(com[1] - y_target) < 0.1:
                            # Sprawdź czy jest długa (wzdłuż X)
                            bbox = gmsh.model.getBoundingBox(1, tag)
                            length_x = abs(bbox[3] - bbox[0])
                            if length_x > L * 0.9:
                                return tag
                return None

            real_slave_L = get_bottom_line(s_L_web, y_web_bot)
            real_slave_R = get_bottom_line(s_R_web, y_web_bot)
            
            if real_slave_L: gmsh.model.addPhysicalGroup(1, [real_slave_L], name="LINE_WELD_L_SLAVE")
            if real_slave_R: gmsh.model.addPhysicalGroup(1, [real_slave_R], name="LINE_WELD_R_SLAVE")

            # --- SIATKOWANIE ---
            # Ustawienie rozmiaru
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), lc_global)
            
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(2)
            
            # Weryfikacja
            if gmsh.model.mesh.getNodes()[0].size == 0:
                raise Exception("Mesh generation failed (0 nodes).")

            if order == 2:
                self.log("Konwersja do elementów 2. rzędu...")
                gmsh.model.mesh.setOrder(2)

            # --- EKSPORT ---
            # Nazewnictwo: Używamy czystej nazwy, suffixy tylko w rozszerzeniu
            path_inp = os.path.join(out_dir, f"{name}.inp")
            path_msh = os.path.join(out_dir, f"{name}.msh")
            groups_json = os.path.join(out_dir, f"{name}_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_nodes.csv")

            # Zapisz siatkę CalculiX (to automatycznie zapisuje NSET i ELSET dla grup fizycznych)
            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            # --- DODATKOWE GRUPY LOGICZNE (Support / Load) ---
            # Te grupy nie są fizycznymi elementami, tylko zbiorami węzłów na końcach
            supp_nodes = self._get_nodes_in_x_plane(0.0, tol=1.0)
            load_nodes = self._get_nodes_in_x_plane(L, tol=1.0)
            
            self.log(f"Węzły Support: {len(supp_nodes)}, Load: {len(load_nodes)}")

            # Pobieramy też ID węzłów Slave, aby mieć pewność (opcjonalne, bo NSET jest w INP)
            # Ale zapisujemy je do JSON dla spójności
            slave_L_nodes = self._get_nodes_from_physical_group(1, "LINE_WELD_L_SLAVE")
            slave_R_nodes = self._get_nodes_from_physical_group(1, "LINE_WELD_R_SLAVE")

            groups_data = {
                "NSET_SUPPORT": supp_nodes,
                "NSET_LOAD": load_nodes,
                "LINE_WELD_L_SLAVE": slave_L_nodes,
                "LINE_WELD_R_SLAVE": slave_R_nodes
            }
            
            with open(groups_json, 'w') as f: json.dump(groups_data, f)
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
            self.log(f"CRITICAL ERROR in Geometry Generation: {e}")
            traceback.print_exc()
            return None
        finally:
            self._finalize_gmsh()

    def _get_nodes_in_x_plane(self, x_loc, tol=1.0):
        try:
            node_tags, coords, _ = gmsh.model.mesh.getNodes()
            selected = []
            for i in range(len(node_tags)):
                # coords jest płaskie [x,y,z, x,y,z...]
                if abs(coords[3*i] - x_loc) < tol:
                    selected.append(int(node_tags[i]))
            return selected
        except: return []

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
        try:
            tags, coords, _ = gmsh.model.mesh.getNodes()
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["NodeID", "X", "Y", "Z"])
                for i in range(len(tags)):
                    w.writerow([int(tags[i]), coords[3*i], coords[3*i+1], coords[3*i+2]])
        except: pass