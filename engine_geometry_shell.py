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
        # Nie zamykamy całkowicie, aby nie psuć sesji w GUI, 
        # ale w trybie wsadowym można tu dodać gmsh.finalize()
        pass

    def generate_model(self, params):
        """
        Generuje model powłokowy (Shell) na podstawie płaszczyzn środkowych (Mid-Surfaces).
        Układ współrzędnych:
          X: Długość (0 = Utwierdzenie, L = Obciążenie)
          Y: Wysokość (0 = Środek grubości płaskownika)
          Z: Szerokość
        """
        self._prepare_gmsh()
        try:
            # --- 1. ODCZYT PARAMETRÓW I KONFIGURACJA GMSH ---
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))

            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 15.0))
            order = int(mesh_cfg.get('order', 1))
            
            # Algorytm 6 = Frontal-Delaunay for 2D (bardzo dobry dla powłok)
            gmsh.option.setNumber("Mesh.Algorithm", 6) 
            gmsh.option.setNumber("Mesh.ElementOrder", order)

            p_data = params['profile_data']
            pl_data = params['plate_data']
            L = float(params['length'])
            out_dir = params['output_dir']
            name = params['model_name']
            
            if not os.path.exists(out_dir): os.makedirs(out_dir)
            factory = gmsh.model.occ

            # Wymiary Geometryczne Profilu (Ceownika)
            hc = float(p_data['hc'])
            bc = float(p_data['bc'])
            twc = float(p_data['twc'])
            tfc = float(p_data['tfc'])
            rc = float(p_data.get('rc', 0.0)) # Promień (opcjonalny w modelu shell uproszczonym)
            
            # Wymiary Płaskownika
            tp = float(pl_data['tp'])
            bp = float(pl_data['bp'])

            # --- 2. OBLICZANIE WSPÓŁRZĘDNYCH PŁASZCZYZN ŚRODKOWYCH (MID-SURFACES) ---
            # Kluczowe założenie: Y=0 znajduje się w geometrycznym środku płaskownika.
            
            # PŁASKOWNIK (PLATE)
            # Fizycznie: od Y = -tp/2 do Y = +tp/2.
            # Środek (Mid-surface): Y = 0.0
            y_plate_mid = 0.0
            
            # Płaszczyzna styku fizycznego (Góra płaskownika / Dół ceownika)
            y_interface = tp / 2.0
            
            # CEOWNIK (CHANNEL)
            # Fizycznie stopka dolna zaczyna się na y_interface.
            # Środek stopki dolnej: y_interface + połowa grubości stopki
            y_flange_bot_mid = y_interface + (tfc / 2.0)
            
            # Środek stopki górnej: y_interface + wysokość całkowita - połowa grubości stopki
            y_flange_top_mid = y_interface + hc - (tfc / 2.0)
            
            # Pozycja Z środników (Webs)
            # Fizycznie zewnętrzna krawędź konstrukcji to +/- bp/2.
            # Środek ścianki środnika jest cofnięty o twc/2 do wewnątrz.
            z_web_left = -(bp / 2.0) + (twc / 2.0)
            z_web_right = (bp / 2.0) - (twc / 2.0)

            # --- 3. GENEROWANIE GEOMETRII (POWIERZCHNIE) ---
            
            # Funkcja pomocnicza: Tworzy prostokąt w płaszczyźnie poziomej (XZ)
            def create_rect_xz(y_level, z_min, z_max, length, tag_prefix):
                p1 = factory.addPoint(0, y_level, z_min)
                p2 = factory.addPoint(length, y_level, z_min)
                p3 = factory.addPoint(length, y_level, z_max)
                p4 = factory.addPoint(0, y_level, z_max)
                
                l1 = factory.addLine(p1, p2)
                l2 = factory.addLine(p2, p3)
                l3 = factory.addLine(p3, p4)
                l4 = factory.addLine(p4, p1)
                
                loop = factory.addCurveLoop([l1, l2, l3, l4])
                surf = factory.addPlaneSurface([loop])
                return surf

            # A. PŁASKOWNIK
            # Rozciąga się na całej szerokości bp
            s_plate = create_rect_xz(y_plate_mid, -bp/2.0, bp/2.0, L, "PLATE")
            
            # B. CEOWNIKI (Złożone z 3 płaszczyzn: Stopka dół, Środnik, Stopka góra)
            def create_channel(z_web_pos, direction_z):
                # direction_z: +1 (w prawo/do środka od lewej), -1 (w lewo/do środka od prawej)
                # Długość stopki w osiach: bc - twc/2
                flange_len = bc - (twc / 2.0)
                z_tip = z_web_pos + (flange_len * direction_z)
                
                z_min = min(z_web_pos, z_tip)
                z_max = max(z_web_pos, z_tip)
                
                # Stopka Dolna i Górna
                s_flange_bot = create_rect_xz(y_flange_bot_mid, z_min, z_max, L, "FBOT")
                s_flange_top = create_rect_xz(y_flange_top_mid, z_min, z_max, L, "FTOP")
                
                # Środnik (Płaszczyzna XY - pionowa)
                p1 = factory.addPoint(0, y_flange_bot_mid, z_web_pos)
                p2 = factory.addPoint(L, y_flange_bot_mid, z_web_pos)
                p3 = factory.addPoint(L, y_flange_top_mid, z_web_pos)
                p4 = factory.addPoint(0, y_flange_top_mid, z_web_pos)
                
                lw1 = factory.addLine(p1, p2) # Dolna krawędź środnika
                lw2 = factory.addLine(p2, p3)
                lw3 = factory.addLine(p3, p4)
                lw4 = factory.addLine(p4, p1)
                
                loop_w = factory.addCurveLoop([lw1, lw2, lw3, lw4])
                s_web = factory.addPlaneSurface([loop_w])
                
                # Zwracamy listę powierzchni
                return [s_flange_bot, s_web, s_flange_top]

            # Lewy Ceownik
            parts_left = create_channel(z_web_left, 1.0)
            
            # Prawy Ceownik
            parts_right = create_channel(z_web_right, -1.0)
            
            factory.synchronize()
            
            # --- 4. ZSZYWANIE WEWNĘTRZNE CEOWNIKÓW (FRAGMENT) ---
            # Zszywamy stopki ze środnikiem w ramach jednego ceownika, aby węzły w narożach były wspólne.
            # UWAGA: Płaskownik pozostaje oddzielną geometrią (nie zszywamy go z ceownikiem, bo jest luka Y).
            
            f_left, _ = factory.fragment([(2, s) for s in parts_left], [])
            f_right, _ = factory.fragment([(2, s) for s in parts_right], [])
            
            factory.synchronize()
            
            # Odzyskujemy tagi powierzchni po fragmencie (mogły ulec zmianie)
            final_surfs_left = [tag for dim, tag in f_left if dim == 2]
            final_surfs_right = [tag for dim, tag in f_right if dim == 2]
            final_surf_plate = s_plate

            # --- 5. DEFINICJA GRUP FIZYCZNYCH 2D (SEKCJE / MATERIAŁY) ---
            
            gmsh.model.addPhysicalGroup(2, [final_surf_plate], name="SHELL_PLATE")
            
            # Rozdzielamy Środniki i Stopki (dla przypisania różnych grubości w Solverze)
            # Używamy Bounding Box do klasyfikacji: 
            # Środnik jest wysoki w Y (dy > dz), Stopka jest szeroka w Z (dz > dy).
            
            def classify_channel_surfs(tags):
                webs = []
                flanges = []
                for t in tags:
                    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, t)
                    dy = abs(ymax - ymin)
                    dz = abs(zmax - zmin)
                    if dy > dz: webs.append(t) # Pionowy -> Środnik
                    else: flanges.append(t)    # Poziomy -> Stopka
                return webs, flanges

            l_webs, l_flanges = classify_channel_surfs(final_surfs_left)
            r_webs, r_flanges = classify_channel_surfs(final_surfs_right)
            
            gmsh.model.addPhysicalGroup(2, l_webs + r_webs, name="SHELL_WEBS")
            gmsh.model.addPhysicalGroup(2, l_flanges + r_flanges, name="SHELL_FLANGES")

            # --- 6. PRZYGOTOWANIE DO *TIE (WELD LINES - EMBED) ---
            # Aby wiązanie *TIE działało idealnie, siatka płaskownika musi mieć węzły 
            # dokładnie pod środnikami ceowników.
            # Używamy funkcji `embed` (wtopienie), rzutując linię środnika na płaskownik.
            
            # Tworzymy linie rzutu na poziomie płaskownika (Y = y_plate_mid)
            pt_w1 = factory.addPoint(0, y_plate_mid, z_web_left)
            pt_w2 = factory.addPoint(L, y_plate_mid, z_web_left)
            l_weld_left_proj = factory.addLine(pt_w1, pt_w2)
            
            pt_w3 = factory.addPoint(0, y_plate_mid, z_web_right)
            pt_w4 = factory.addPoint(L, y_plate_mid, z_web_right)
            l_weld_right_proj = factory.addLine(pt_w3, pt_w4)
            
            # Wtapiamy te linie w powierzchnię płaskownika
            factory.synchronize()
            gmsh.model.mesh.embed(1, [l_weld_left_proj, l_weld_right_proj], 2, final_surf_plate)
            
            # Definiujemy grupy fizyczne dla linii wiążących (1D)
            # MASTER: Linie na płaskowniku
            gmsh.model.addPhysicalGroup(1, [l_weld_left_proj], name="LINE_WELD_L_MASTER")
            gmsh.model.addPhysicalGroup(1, [l_weld_right_proj], name="LINE_WELD_R_MASTER")
            
            # SLAVE: Dolne krawędzie ceowników (Środników)
            # Musimy znaleźć ich ID w przestrzeni. Są na Y = y_flange_bot_mid i Z = z_web_left/right.
            def find_line_in_box(xmin, ymin, zmin, xmax, ymax, zmax, tolerance=0.1):
                return gmsh.model.getEntitiesInBoundingBox(
                    xmin-tolerance, ymin-tolerance, zmin-tolerance,
                    xmax+tolerance, ymax+tolerance, zmax+tolerance, dim=1
                )

            slaves_L = find_line_in_box(0, y_flange_bot_mid, z_web_left, L, y_flange_bot_mid, z_web_left)
            slaves_L_tags = [t for d, t in slaves_L]
            
            slaves_R = find_line_in_box(0, y_flange_bot_mid, z_web_right, L, y_flange_bot_mid, z_web_right)
            slaves_R_tags = [t for d, t in slaves_R]
            
            if slaves_L_tags: gmsh.model.addPhysicalGroup(1, slaves_L_tags, name="LINE_WELD_L_SLAVE")
            if slaves_R_tags: gmsh.model.addPhysicalGroup(1, slaves_R_tags, name="LINE_WELD_R_SLAVE")

            # --- 7. GENEROWANIE SIATKI ---
            self.log("Generowanie siatki 2D...")
            gmsh.model.mesh.generate(2)
            
            if order == 2:
                self.log("Konwersja do elementów 2. rzędu...")
                gmsh.model.mesh.setOrder(2)

            # --- 8. EKSPORT DANYCH (PLIKI I GRUPY WĘZŁÓW) ---
            path_inp = os.path.join(out_dir, f"{name}_shell.inp")
            path_msh = os.path.join(out_dir, f"{name}_shell.msh")
            groups_json = os.path.join(out_dir, f"{name}_shell_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_shell_nodes.csv")

            # Zapisz geometrię (.inp dla CalculiX, .msh dla PyVista)
            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            # --- TWORZENIE GRUP WĘZŁÓW (NSET) DLA SOLVERA ---
            
            # A. Support (Utwierdzenie) - Wszystkie węzły na X=0
            supp_nodes = self._get_nodes_in_x_plane(0.0)
            
            # B. Load (Obciążenie) - Wszystkie węzły na X=L
            # To jest KLUCZOWE dla metody Rigid Body: Te węzły będą "Slave'ami" dla Punktu Referencyjnego.
            load_nodes = self._get_nodes_in_x_plane(L)
            
            # C. Grupy węzłów dla spoin (opcjonalne, jeśli solver używa surface-to-surface, ale przydatne)
            weld_groups = {}
            for gname in ["LINE_WELD_L_MASTER", "LINE_WELD_R_MASTER", "LINE_WELD_L_SLAVE", "LINE_WELD_R_SLAVE"]:
                nodes = self._get_nodes_from_physical_group(1, gname)
                weld_groups[gname] = nodes

            groups_data = {
                "NSET_SUPPORT": supp_nodes,
                "NSET_LOAD": load_nodes, # <-- RIGID BODY SLAVES
                **weld_groups
            }
            
            with open(groups_json, 'w') as f:
                json.dump(groups_data, f)

            # Eksport mapy węzłów (dla post-processingu w Pythonie)
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

    def _get_nodes_in_x_plane(self, x_loc, tol=0.01):
        """Pobiera ID węzłów leżących na płaszczyźnie X = x_loc"""
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        selected = []
        # coords to płaska lista [x1, y1, z1, x2, y2, z2...]
        for i in range(len(node_tags)):
            if abs(coords[3*i] - x_loc) < tol:
                selected.append(int(node_tags[i]))
        return selected

    def _get_nodes_from_physical_group(self, dim, name):
        """Pobiera węzły należące do danej grupy fizycznej (np. linii spoiny)."""
        try:
            group_tags = gmsh.model.getPhysicalGroups(dim)
            target_tag = -1
            for d, t in group_tags:
                if gmsh.model.getPhysicalName(d, t) == name:
                    target_tag = t
                    break
            
            if target_tag == -1: return []

            # Pobierz encje w grupie
            entities = gmsh.model.getEntitiesForPhysicalGroup(dim, target_tag)
            
            all_nodes = set()
            for e in entities:
                # includeBoundary=True łapie węzły końcowe linii
                tags, _, _ = gmsh.model.mesh.getNodes(dim, e, includeBoundary=True) 
                for t in tags: all_nodes.add(int(t))
            
            return list(all_nodes)
        except:
            return []

    def _export_node_map(self, path):
        tags, coords, _ = gmsh.model.mesh.getNodes()
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["NodeID", "X", "Y", "Z"])
            for i in range(len(tags)):
                w.writerow([int(tags[i]), coords[3*i], coords[3*i+1], coords[3*i+2]])