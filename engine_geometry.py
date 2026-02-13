import gmsh
import sys
import os
import json
import csv
import math

class GeometryGenerator:
    def __init__(self, logger_callback=None):
        self.logger = logger_callback

    def log(self, message):
        msg = f"[GEOM] {message}"
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
        # Nie zamykamy całkowicie gmsh.finalize(), bo w multiprocessing może to powodować problemy przy restarcie
        pass

    def _get_nodes_manual(self, xmin, ymin, zmin, xmax, ymax, zmax):
        """
        Pobiera węzły w zadanym prostopadłościanie (Bounding Box).
        Filtrowanie odbywa się w Pythonie.
        """
        # Tu zwraca 3 wartości, więc używamy _, _
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        selected_tags = []
        count = len(node_tags)
        
        # coords to płaska lista [x1, y1, z1, x2, y2, z2...]
        for i in range(count):
            x = coords[3*i]
            y = coords[3*i+1]
            z = coords[3*i+2]
            
            if (xmin <= x <= xmax) and (ymin <= y <= ymax) and (zmin <= z <= zmax):
                selected_tags.append(int(node_tags[i]))
                
        return selected_tags

    def _apply_refinement(self, zones, global_lc, p_data, pl_data, length):
        """
        Aplikuje pola zagęszczania siatki (Fields) na podstawie stref.
        Rozbudowana wersja o precyzyjne strefy przekroju.
        """
        if not zones: return

        # --- POBRANIE WYMIARÓW ---
        tp = float(pl_data['tp'])       # Grubość blachy
        bp = float(pl_data['bp'])       # Szerokość blachy (zasięg Z)
        
        hc = float(p_data['hc'])        # Wysokość ceownika
        tfc = float(p_data['tfc'])      # Grubość stopki
        twc = float(p_data['twc'])      # Grubość środnika
        rc = float(p_data.get('rc', 0.0)) # Promień naroża (jeśli jest)

        # Baza Y (góra blachy, dół ceownika)
        y_base = tp / 2.0 
        
        field_ids = []
        
        for i, zone in enumerate(zones):
            name = zone.get("name", "Unknown")
            lc_min = float(zone.get("lc_min", global_lc))
            lc_max = float(zone.get("lc_max", global_lc))
            dist_max = float(zone.get("dist_max", 10.0)) # Grubość strefy przejścia
            
            # Inicjalizacja Boxa "poza światem" (bezpiecznik)
            ymin, ymax, zmin, zmax = -9999, -9999, -9999, -9999
            
            # Margines bezpieczeństwa dla boxów (żeby na pewno złapały węzły)
            margin = 2.0 

            # --- LOGIKA STREF ---
            
            # 1. CAŁE PODZESPOŁY (Stare)
            if name == "SURF_WEBS": 
                # Całe środniki
                ymin = y_base + tfc
                ymax = y_base + hc - tfc
                zmin, zmax = -bp, bp
                
            elif name == "SURF_FLANGES":
                # Całe stopki (górna i dolna)
                # To złapie obie, bo box obejmie całą wysokość z wycięciem środka? 
                # Nie, lepiej zrobić duży box na całość, a potem inni będą nadpisywać.
                # Ale tutaj zrobimy po prostu zakres Y od dołu do góry
                ymin = y_base - margin
                ymax = y_base + hc + margin
                zmin, zmax = -bp, bp
                
            elif name == "SURF_PLATE":
                # Cały płaskownik
                ymin = -tp/2.0 - margin
                ymax = tp/2.0 + margin
                zmin, zmax = -bp - margin, bp + margin

            # 2. PRECYZYJNE STREFY CEOWNIKA
            
            elif name == "SURF_CORNERS_ROOT":
                # [KLUCZOWE] Naroża wewnętrzne (pachwiny) - tam gdzie największe naprężenia
                # Definiujemy dwa paski: na dole i na górze środnika
                # Uwaga: Box musi złapać Y w okolicach (y_base + tfc) oraz (y_base + hc - tfc)
                # Ponieważ Box jest jeden na Field, zrobimy to szeroko na środku albo skupimy się na dole/górze
                # Tu robimy "wszystkie naroża" -> obejmujemy Y całego ceownika, ale ograniczymy Z w kolejnym kroku?
                # W Gmsh Box jest prostopadłościanem. Żeby złapać tylko naroża, musimy użyć Cylinder albo kombinacji.
                # Uproszczenie: Pasek obejmujący strefę przyśrodnikową
                ymin = y_base + 1.0 # Lekko powyżej styku
                ymax = y_base + hc - 1.0
                zmin, zmax = -bp, bp 
                # To jest mało precyzyjne. Lepiej zdefiniować konkretne Y dla stopek.
                # Zróbmy to inaczej: Zagęszczenie całego obszaru przejścia stopka-środnik
                ymin = y_base
                ymax = y_base + hc
                # Tutaj polegamy na inteligencji użytkownika, że lc_min nie jest ultra małe dla całego profilu
                
            elif name == "SURF_FLANGE_BOTTOM":
                # Tylko dolna stopka (stykająca się z blachą)
                ymin = y_base - margin
                ymax = y_base + tfc + rc + margin
                zmin, zmax = -bp, bp

            elif name == "SURF_FLANGE_TOP":
                # Tylko górna stopka
                ymin = y_base + hc - tfc - rc - margin
                ymax = y_base + hc + margin
                zmin, zmax = -bp, bp

            elif name == "SURF_WEB_CENTER":
                # Środek środnika (często mało ważne, można rozrzedzić)
                ymin = y_base + tfc + rc
                ymax = y_base + hc - tfc - rc
                zmin, zmax = -bp, bp

            # 3. STREFY PŁASKOWNIKA
            
            elif name == "SURF_PLATE_CONTACT":
                # Górna powierzchnia płaskownika (tam gdzie styk)
                ymin = tp/2.0 - 2.0
                ymax = tp/2.0 + 2.0
                zmin, zmax = -bp, bp

            elif name == "SURF_PLATE_EDGES":
                # Krawędzie boczne płaskownika (daleko od środka)
                # Tu trzeba by użyć Boxa wycinającego środek, co jest trudne jednym Boxem.
                # Zrobimy zagęszczenie całości po grubości
                ymin = -tp/2.0 - margin
                ymax = tp/2.0 + margin
                zmin, zmax = -bp - margin, bp + margin

            # --- TWORZENIE POLA (FIELD) ---
            # Jeśli udało się zdefiniować sensowny Box
            if ymin > -9000:
                fid = gmsh.model.mesh.field.add("Box")
                gmsh.model.mesh.field.setNumber(fid, "VIn", lc_min)
                gmsh.model.mesh.field.setNumber(fid, "VOut", lc_max)
                gmsh.model.mesh.field.setNumber(fid, "XMin", -10.0)
                gmsh.model.mesh.field.setNumber(fid, "XMax", length + 10.0)
                gmsh.model.mesh.field.setNumber(fid, "YMin", ymin)
                gmsh.model.mesh.field.setNumber(fid, "YMax", ymax)
                gmsh.model.mesh.field.setNumber(fid, "ZMin", zmin)
                gmsh.model.mesh.field.setNumber(fid, "ZMax", zmax)
                gmsh.model.mesh.field.setNumber(fid, "Thickness", dist_max)
                field_ids.append(fid)

        # Aplikacja pól
        if field_ids:
            # Używamy pola Min (bierzemy najmniejszy zadeklarowany rozmiar w danym punkcie)
            fid_min = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(fid_min, "FieldsList", field_ids)
            gmsh.model.mesh.field.setAsBackgroundMesh(fid_min)
            self.log(f"Zaaplikowano {len(field_ids)} stref zagęszczania.")

    def generate_model(self, params):
        self._prepare_gmsh()
        try:
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))

            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 15.0))
            lc_fillet = float(mesh_cfg.get('fillet', 3.0))
            element_order = int(mesh_cfg.get('order', 1)) 
            
            algo_3d = int(params.get('mesh_quality', {}).get('algorithm_3d', 1))
            gmsh.option.setNumber("Mesh.Algorithm3D", algo_3d)
            gmsh.option.setNumber("Mesh.ElementOrder", element_order)
            
            # Limity wielkości elementu
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc_global)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc_fillet * 0.5)

            p_data = params['profile_data']
            pl_data = params['plate_data']
            L = float(params['length'])
            out_dir = params['output_dir']
            name = params['model_name']
            
            if not os.path.exists(out_dir): os.makedirs(out_dir)
            factory = gmsh.model.occ
            
            # Wymiary
            h = float(p_data['hc'])
            b_flange = float(p_data['bc'])
            tw = float(p_data['twc'])
            tf = float(p_data['tfc'])
            r_root = float(p_data.get('rc', 0.0))
            tp = float(pl_data['tp'])
            bp = float(pl_data['bp'])

            # --- GEOMETRIA ---
            
            # 1. Płaskownik
            y_p_half = tp / 2.0
            z_p_half = bp / 2.0
            
            pts_plate = [
                (-y_p_half, -z_p_half), 
                ( y_p_half, -z_p_half), 
                ( y_p_half,  z_p_half), 
                (-y_p_half,  z_p_half)
            ]
            
            tags_plate = []
            for y, z in pts_plate:
                tags_plate.append(factory.addPoint(0, y, z, lc_global))
                
            lines_plate = []
            for i in range(4):
                lines_plate.append(factory.addLine(tags_plate[i], tags_plate[(i+1)%4]))
            
            loop_plate = factory.addCurveLoop(lines_plate)
            face_plate = factory.addPlaneSurface([loop_plate])

            # 2. Ceowniki
            def draw_channel(z_start, direction_z):
                dz = direction_z # +1 lub -1
                y_base = tp / 2.0
                
                pts_def = [
                    (y_base, z_start),                                     # 0
                    (y_base + h, z_start),                                 # 1
                    (y_base + h, z_start + b_flange * dz),                 # 2
                    (y_base + h - tf, z_start + b_flange * dz),            # 3
                    (y_base + h - tf, z_start + tw * dz + r_root*dz),      # 4
                    (y_base + h - tf - r_root, z_start + tw * dz),         # 5
                    (y_base + tf + r_root, z_start + tw * dz),             # 6
                    (y_base + tf, z_start + tw * dz + r_root*dz),          # 7
                    (y_base + tf, z_start + b_flange * dz),                # 8
                    (y_base, z_start + b_flange * dz)                      # 9
                ]
                
                tags = []
                for i, (y, z) in enumerate(pts_def):
                    lc = lc_fillet if i in [4,5,6,7] else lc_global
                    tags.append(factory.addPoint(0, y, z, lc))
                
                # Punkty centralne dla łuków
                center_top = factory.addPoint(0, y_base + h - tf - r_root, z_start + tw * dz + r_root * dz, lc_fillet)
                center_bottom = factory.addPoint(0, y_base + tf + r_root, z_start + tw * dz + r_root * dz, lc_fillet)

                lns = [
                    factory.addLine(tags[0], tags[1]),
                    factory.addLine(tags[1], tags[2]),
                    factory.addLine(tags[2], tags[3]),
                    factory.addLine(tags[3], tags[4]),
                    factory.addCircleArc(tags[4], center_top, tags[5]),
                    factory.addLine(tags[5], tags[6]),
                    factory.addCircleArc(tags[6], center_bottom, tags[7]),
                    factory.addLine(tags[7], tags[8]),
                    factory.addLine(tags[8], tags[9]),
                    factory.addLine(tags[9], tags[0])
                ]
                
                return factory.addPlaneSurface([factory.addCurveLoop(lns)])

            face_left = draw_channel(-bp/2.0, 1)
            face_right = draw_channel(bp/2.0, -1)
            
            factory.synchronize()

            # Extrude
            vol_plate = factory.extrude([(2, face_plate)], L, 0, 0)
            vol_left = factory.extrude([(2, face_left)], L, 0, 0)
            vol_right = factory.extrude([(2, face_right)], L, 0, 0)
            
            factory.synchronize()

            # Fragment (Scalanie brył)
            v_input = []
            for v_list in [vol_plate, vol_left, vol_right]:
                for dim, tag in v_list:
                    if dim == 3: v_input.append((3, tag))
            
            try: factory.healShapes(v_input)
            except: pass
            
            frag_out, _ = factory.fragment(v_input, v_input)
            factory.synchronize()
            
            # Grupa fizyczna dla całej objętości (VOL_ALL)
            final_vols = [tag for dim, tag in frag_out if dim == 3]
            gmsh.model.addPhysicalGroup(3, final_vols, name="VOL_ALL")

            # --- APLIKACJA PÓŁ ZAGĘSZCZEŃ ---
            ref_zones = params.get("refinement_zones", [])
            if ref_zones:
                self._apply_refinement(ref_zones, lc_global, p_data, pl_data, L)

            # --- GENERACJA SIATKI ---
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(3)

            self.log("Scalanie duplikatów węzłów (Safety check)...")
            gmsh.model.mesh.removeDuplicateNodes()
            
            if element_order == 2:
                self.log("Konwersja do elementów 2. rzędu...")
                gmsh.model.mesh.setOrder(2)
            
            # --- IDENTYFIKACJA WĘZŁÓW DO POST-PROCESSINGU ---
            self.log("Identyfikacja węzłów powierzchni styku...")
            eps = 1e-3
            y_int = tp / 2.0
            
            # Znajdujemy encje powierzchni (dim=2) w Bounding Boxie
            interface_surfaces_raw = gmsh.model.getEntitiesInBoundingBox(
                -eps, y_int - eps, -bp/2 - eps, L + eps, y_int + eps, bp/2 + eps, dim=2
            )
            interface_surface_tags = [tag for dim, tag in interface_surfaces_raw]
            
            int_nodes = []
            if interface_surface_tags:
                self.log(f"Znaleziono {len(interface_surface_tags)} powierzchni styku.")
                # POBIERAMY WĘZŁY BEZ TWORZENIA PHYSICAL GROUP 2D
                # NAPRAWA: getNodes zwraca 3 wartości (tags, coords, param_coords)
                node_tags_set = set()
                for s_tag in interface_surface_tags:
                    n_tags, coords, _ = gmsh.model.mesh.getNodes(2, s_tag, includeBoundary=True)
                    for nt in n_tags:
                        node_tags_set.add(int(nt))
                int_nodes = list(node_tags_set)
            else:
                self.log("Ostrzeżenie: Brak powierzchni w BBox. Używam metody manualnej.")
                int_nodes = self._get_nodes_manual(-1.0, y_int-1.0, -1e4, L+1.0, y_int+1.0, 1e4)

            # Grupy węzłów dla podpór i obciążeń
            supp_nodes = self._get_nodes_manual(-1.0, -1e4, -1e4, 1.0, 1e4, 1e4)
            load_nodes = self._get_nodes_manual(L-1.0, -1e4, -1e4, L+1.0, 1e4, 1e4)
            
            groups_data = {
                "SURF_SUPPORT": supp_nodes,
                "SURF_LOAD": load_nodes,
                "GRP_INTERFACE": int_nodes
            }
            
            self.log(f"Znaleziono węzły: Supp={len(supp_nodes)}, Load={len(load_nodes)}, Interface={len(int_nodes)}")
            
            # Ścieżki plików
            nodes_csv = os.path.join(out_dir, f"{name}_nodes.csv")
            groups_json = os.path.join(out_dir, f"{name}_groups.json")
            path_inp = os.path.join(out_dir, f"{name}.inp")
            path_msh = os.path.join(out_dir, f"{name}.msh")
            
            # Zapis CSV z mapą węzłów
            tags_all, coords_all, _ = gmsh.model.mesh.getNodes()
            
            with open(nodes_csv, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["NodeID", "X", "Y", "Z"])
                for i in range(len(tags_all)):
                    w.writerow([
                        tags_all[i], 
                        coords_all[3*i], 
                        coords_all[3*i+1], 
                        coords_all[3*i+2]
                    ])
            
            # Zapis JSON z grupami
            with open(groups_json, 'w') as f:
                json.dump(groups_data, f)
            
            # Zapis .inp i .msh
            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            return {
                "paths": {
                    "inp": os.path.abspath(path_inp),
                    "nodes_csv": os.path.abspath(nodes_csv),
                    "groups_json": os.path.abspath(groups_json)
                },
                "stats": {"nodes": len(tags_all)}
            }
            
        except Exception as e:
            self.log(f"CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            self._finalize_gmsh()