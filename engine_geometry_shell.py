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
            # --- 1. ODCZYT PARAMETRÓW ---
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))

            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 15.0))
            order = int(mesh_cfg.get('order', 1))
            
            gmsh.option.setNumber("Mesh.Algorithm", 6) # 6 = Frontal-Delaunay for 2D
            gmsh.option.setNumber("Mesh.ElementOrder", order)

            p_data = params['profile_data']
            pl_data = params['plate_data']
            L = float(params['length'])
            out_dir = params['output_dir']
            name = params['model_name']
            
            if not os.path.exists(out_dir): os.makedirs(out_dir)
            factory = gmsh.model.occ

            # Wymiary Geometryczne
            hc = float(p_data['hc'])
            bc = float(p_data['bc'])
            twc = float(p_data['twc'])
            tfc = float(p_data['tfc'])
            rc = float(p_data.get('rc', 0.0))
            
            tp = float(pl_data['tp'])
            bp = float(pl_data['bp'])

            # --- 2. OBLICZANIE PŁASZCZYZN ŚRODKOWYCH (MID-SURFACES) ---
            # Układ współrzędnych: Y=0 to góra płaskownika (powierzchnia styku fizycznego)
            # Dzięki temu łatwo liczyć offsety.
            
            # PŁASKOWNIK (PLATE)
            # Fizycznie: od Y = -tp do Y = 0.
            # Środek: Y = -tp / 2
            y_plate_mid = -tp / 2.0
            
            # CEOWNIK (CHANNEL)
            # Fizycznie stopka dolna: od Y = 0 do Y = tfc.
            # Środek stopki dolnej: Y = tfc / 2
            y_flange_bot_mid = tfc / 2.0
            
            # Środek stopki górnej: Y = hc - tfc/2
            y_flange_top_mid = hc - (tfc / 2.0)
            
            # Środnik (Web): Rozciąga się pionowo pomiędzy środkami stopek?
            # W modelowaniu powłokowym zazwyczaj dociągamy środnik do osi stopek.
            # Pozycja Z środnika: 
            # Fizycznie zewnętrzna krawędź to +/- bp/2.
            # Środek ścianki środnika jest cofnięty o twc/2 do wewnątrz.
            z_web_left = -(bp / 2.0) + (twc / 2.0)
            z_web_right = (bp / 2.0) - (twc / 2.0)

            # --- 3. GENEROWANIE GEOMETRII ---
            
            surfaces = []
            
            # A. PŁASKOWNIK (Prostokąt na Y = y_plate_mid)
            tag_plate = factory.addRectangle(-10.0, y_plate_mid, -bp/2.0, L + 20.0, bp) 
            # Robimy ciut dłuższy (-10 do L+20) lub idealnie L? 
            # Zróbmy idealnie L, żeby pasowało do modelu.
            # Uwaga: Gmsh addRectangle(x, y, z, dx, dy). Tutaj Z jest szerokością.
            # Prostokąt w płaszczyźnie X-Z
            # Musimy uważać na orientację addRectangle. Domyślnie tworzy w XY.
            # Użyjmy 4 punktów i linii dla pewności orientacji.
            
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
                return surf, [l1, l2, l3, l4]

            # 1. PLATE SURFACE
            s_plate, l_plate = create_rect_xz(y_plate_mid, -bp/2.0, bp/2.0, L, "PLATE")
            
            # B. CEOWNIKI (Złożone z 3 płaszczyzn: Stopka dół, Środnik, Stopka góra)
            
            def create_channel(z_web_pos, direction_z):
                # direction_z: +1 dla lewego (stopki idą w +Z), -1 dla prawego (stopki idą w -Z)
                # Szerokość stopki w modelu osiowym:
                # Fizyczna szerokość bc. Od osi środnika (z_web_pos) do końca stopki jest:
                # bc - (twc/2). 
                flange_len = bc - (twc / 2.0)
                
                z_tip = z_web_pos + (flange_len * direction_z)
                
                # Stopka Dolna
                # Od z_web_pos do z_tip
                z_min = min(z_web_pos, z_tip)
                z_max = max(z_web_pos, z_tip)
                s_flange_bot, l_fbot = create_rect_xz(y_flange_bot_mid, z_min, z_max, L, "FBOT")
                
                # Stopka Górna
                s_flange_top, l_ftop = create_rect_xz(y_flange_top_mid, z_min, z_max, L, "FTOP")
                
                # Środnik (Płaszczyzna XY)
                # Rozciąga się od y_flange_bot_mid do y_flange_top_mid
                # Stałe Z = z_web_pos
                p1 = factory.addPoint(0, y_flange_bot_mid, z_web_pos)
                p2 = factory.addPoint(L, y_flange_bot_mid, z_web_pos)
                p3 = factory.addPoint(L, y_flange_top_mid, z_web_pos)
                p4 = factory.addPoint(0, y_flange_top_mid, z_web_pos)
                
                lw1 = factory.addLine(p1, p2) # To jest linia styku ze stopką dolną
                lw2 = factory.addLine(p2, p3)
                lw3 = factory.addLine(p3, p4) # To jest linia styku ze stopką górną
                lw4 = factory.addLine(p4, p1)
                
                loop_w = factory.addCurveLoop([lw1, lw2, lw3, lw4])
                s_web = factory.addPlaneSurface([loop_w])
                
                return [s_flange_bot, s_web, s_flange_top]

            # Lewy Ceownik (stoi na -Z, stopki w kierunku +Z do środka)
            # Uwaga: UPE ma stopki równoległe.
            # Jeśli ceowniki są "[]" (plecami do zewnątrz), to Lewy ma środnik na minusie, stopki w plus.
            # Zakładam układ "Skrzynka otwarta" (Box), czyli "[" i "]"
            # Lewy: Środnik na -bp/2 + twc/2. Stopki w prawo (+Z).
            parts_left = create_channel(z_web_left, 1.0)
            
            # Prawy Ceownik: Środnik na +bp/2 - twc/2. Stopki w lewo (-Z).
            parts_right = create_channel(z_web_right, -1.0)
            
            all_surfs = [s_plate] + parts_left + parts_right
            
            factory.synchronize()
            
            # --- 4. ZSZYWANIE WEWNĘTRZNE CEOWNIKÓW (FRAGMENT) ---
            # Musimy zszyć stopki ze środnikiem w ramach JEDNEGO ceownika, 
            # żeby tworzyły ciągłość (węzły wspólne w narożach).
            # NIE zszywamy ceownika z płaskownikiem (bo jest gap).
            
            # Fragmentujemy Lewy Ceownik
            f_left, _ = factory.fragment([(2, s) for s in parts_left], [])
            
            # Fragmentujemy Prawy Ceownik
            f_right, _ = factory.fragment([(2, s) for s in parts_right], [])
            
            factory.synchronize()
            
            # Pobieramy nowe tagi po fragmentacji (mogły się zmienić)
            # Gmsh zwraca listę (dim, tag). Filtrujemy surface (dim=2).
            final_surfs_left = [tag for dim, tag in f_left if dim == 2]
            final_surfs_right = [tag for dim, tag in f_right if dim == 2]
            
            # Płaskownik pozostaje bez zmian (nie brał udziału we fragmencie)
            final_surf_plate = s_plate

            # --- 5. DEFINICJA GRUP FIZYCZNYCH (DLA CLOAD, BOUNDARY I TIE) ---
            
            # A. Materiały / Sekcje (Element Sets)
            gmsh.model.addPhysicalGroup(2, [final_surf_plate], name="SHELL_PLATE")
            
            # Rozdzielamy środniki i stopki dla przypisania różnych grubości w Solverze
            # Prosta heurystyka: Środnik jest pionowy (rozciąga się w Y), stopki poziome (w Z).
            # Bounding Box check.
            
            def classify_channel_surfs(tags):
                webs = []
                flanges = []
                for t in tags:
                    # Get Bounding Box
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

            # B. Linie do *TIE (Weld Lines)
            # Szukamy linii, które są "nad sobą".
            # Linia na płaskowniku pod lewą stopką i pod prawą stopką.
            # Ponieważ nie robiliśmy fragmentacji płaskownika, musimy znaleźć linię geometrycznie
            # lub zdefiniować "linię wirtualną" na płaskowniku używając 'Embed' (wtopienie punktów/linii w powierzchnię).
            
            # TO JEST KLUCZOWE: Żeby węzły na płaskowniku istniały dokładnie pod środnikiem ceownika,
            # musimy wtopić (Embed) rzut linii środnika na płaskownik.
            
            # Rzut linii środnika lewego na płaskownik (Y = y_plate_mid, Z = z_web_left)
            pt_w1 = factory.addPoint(0, y_plate_mid, z_web_left)
            pt_w2 = factory.addPoint(L, y_plate_mid, z_web_left)
            l_weld_left_proj = factory.addLine(pt_w1, pt_w2)
            
            # Rzut linii środnika prawego (Y = y_plate_mid, Z = z_web_right)
            pt_w3 = factory.addPoint(0, y_plate_mid, z_web_right)
            pt_w4 = factory.addPoint(L, y_plate_mid, z_web_right)
            l_weld_right_proj = factory.addLine(pt_w3, pt_w4)
            
            # Wtapiamy te linie w powierzchnię płaskownika
            factory.synchronize()
            gmsh.model.mesh.embed(1, [l_weld_left_proj, l_weld_right_proj], 2, final_surf_plate)
            
            # Teraz mamy pewność, że na płaskowniku powstaną węzły wzdłuż tych linii.
            # Tworzymy grupy fizyczne linii (1D) dla *TIE
            
            # Grupa MASTER (na płaskowniku)
            gmsh.model.addPhysicalGroup(1, [l_weld_left_proj], name="LINE_WELD_L_MASTER")
            gmsh.model.addPhysicalGroup(1, [l_weld_right_proj], name="LINE_WELD_R_MASTER")
            
            # Grupa SLAVE (na dolnych stopkach ceowników)
            # Musimy znaleźć ID linii, które są dolnymi krawędziami środników/stopek.
            # Są to linie na Y = y_flange_bot_mid i Z = z_web_left/right.
            # Użyjemy Bounding Box do znalezienia ich ID wśród linii ceowników.
            
            def find_line_in_box(xmin, ymin, zmin, xmax, ymax, zmax, tolerance=0.1):
                return gmsh.model.getEntitiesInBoundingBox(
                    xmin-tolerance, ymin-tolerance, zmin-tolerance,
                    xmax+tolerance, ymax+tolerance, zmax+tolerance, dim=1
                )

            # Szukamy dolnej krawędzi lewego środnika
            # Linia wzdłuż X (0 do L), Y=y_flange_bot_mid, Z=z_web_left
            slaves_L = find_line_in_box(0, y_flange_bot_mid, z_web_left, L, y_flange_bot_mid, z_web_left)
            slaves_L_tags = [t for d, t in slaves_L]
            
            slaves_R = find_line_in_box(0, y_flange_bot_mid, z_web_right, L, y_flange_bot_mid, z_web_right)
            slaves_R_tags = [t for d, t in slaves_R]
            
            if slaves_L_tags: gmsh.model.addPhysicalGroup(1, slaves_L_tags, name="LINE_WELD_L_SLAVE")
            if slaves_R_tags: gmsh.model.addPhysicalGroup(1, slaves_R_tags, name="LINE_WELD_R_SLAVE")

            # C. Grupy Węzłów dla Warunków Brzegowych (Support / Load)
            # Support: X=0
            # Load: X=L
            
            # Użyjemy funkcji manualnej po wygenerowaniu siatki, bo łatwiej złapać węzły.
            
            # --- 6. GENEROWANIE SIATKI ---
            self.log("Generowanie siatki 2D...")
            gmsh.model.mesh.generate(2)
            
            if order == 2:
                self.log("Konwersja do elementów 2. rzędu...")
                gmsh.model.mesh.setOrder(2)

            # --- 7. EKSPORT DO .INP I GRUPY W JSON ---
            path_inp = os.path.join(out_dir, f"{name}_shell.inp")
            path_msh = os.path.join(out_dir, f"{name}_shell.msh")
            groups_json = os.path.join(out_dir, f"{name}_shell_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_shell_nodes.csv")

            # Zapisz Inp i Msh
            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            # Pobranie węzłów do grup Support i Load (ręcznie po BBox)
            # Support: Wszystkie węzły na X=0
            supp_nodes = self._get_nodes_in_x_plane(0.0)
            # Load: Wszystkie węzły na X=L
            load_nodes = self._get_nodes_in_x_plane(L)
            
            # Zapisz grupy specjalne (Weld lines są już w INP jako Elsets 1D, 
            # ale potrzebujemy ich Node Sets do TIE w CalculiX, jeśli używamy NSET based TIE.
            # CalculiX *TIE działa na SURFACE (czyli face'y) lub NSETs.
            # Dla Shell-to-Shell edge connection najlepiej użyć *EQUATION lub *TIE z NSET.
            # Zapiszmy NSETY z Physical Groups linii.
            
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

            # Eksport mapy węzłów (dla post-processingu)
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
        for i in range(len(node_tags)):
            if abs(coords[3*i] - x_loc) < tol:
                selected.append(int(node_tags[i]))
        return selected

    def _get_nodes_from_physical_group(self, dim, name):
        """Pobiera węzły należące do danej grupy fizycznej."""
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