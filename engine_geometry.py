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
        # Nie zamykamy całkowicie gmsh.finalize(), bo w multiprocessing może to powodować problemy przy restarcie,
        # ale gmsh.clear() w _prepare robi robotę.
        pass

    def _get_nodes_manual(self, xmin, ymin, zmin, xmax, ymax, zmax):
        """
        Pobiera węzły w zadanym prostopadłościanie (Bounding Box).
        Filtrowanie odbywa się w Pythonie, co jest bardziej niezawodne niż Physical Groups dla węzłów w API.
        """
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        selected_tags = []
        count = len(node_tags)
        
        # coords to płaska lista [x1, y1, z1, x2, y2, z2...]
        # Iterujemy i sprawdzamy warunki
        for i in range(count):
            x = coords[3*i]
            y = coords[3*i+1]
            z = coords[3*i+2]
            
            if (xmin <= x <= xmax) and (ymin <= y <= ymax) and (zmin <= z <= zmax):
                selected_tags.append(int(node_tags[i]))
                
        return selected_tags

    def _apply_refinement(self, zones, global_lc, p_data, pl_data, length):
        """Aplikuje pola zagęszczania siatki (Fields) na podstawie stref z GUI."""
        if not zones: return

        # Wymiary do interpretacji nazw stref
        tp = float(pl_data['tp'])
        bp = float(pl_data['bp'])
        hc = float(p_data['hc'])
        
        field_ids = []
        
        for i, zone in enumerate(zones):
            name = zone.get("name", "Unknown")
            lc_min = float(zone.get("lc_min", global_lc))
            lc_max = float(zone.get("lc_max", global_lc))
            # Distances w Box Field działają jako Thickness (strefa przejścia)
            dist_max = float(zone.get("dist_max", 10.0))
            
            # Domyślny Box (ogromny, nic nie łapie)
            ymin, ymax, zmin, zmax = -9999, -9999, -9999, -9999
            
            if name == "SURF_WEBS":
                # Obszar środników ceowników (Y > tp/2)
                # Obejmujemy od poziomu płaskownika w górę
                ymin = tp/2.0 - 5.0
                ymax = tp/2.0 + hc + 5.0
                # Z - pełna szerokość
                zmin, zmax = -bp*2, bp*2 
                
            elif name == "SURF_FLANGES":
                # Strefa stopek - upraszczamy do boxa obejmującego górę i dół ceownika
                # Bardziej precyzyjnie byłoby 2 boxy, ale jeden duży też zadziała
                ymin = tp/2.0 - 2.0
                ymax = tp/2.0 + hc + 2.0
                zmin, zmax = -bp*2, bp*2
                
            elif name == "SURF_PLATE":
                # Płaskownik
                ymin = -tp/2.0 - 5.0
                ymax = tp/2.0 + 5.0
                zmin, zmax = -bp*2, bp*2
            
            # Tworzenie pola Box
            fid_box = gmsh.model.mesh.field.add("Box")
            gmsh.model.mesh.field.setNumber(fid_box, "VIn", lc_min)
            gmsh.model.mesh.field.setNumber(fid_box, "VOut", lc_max)
            gmsh.model.mesh.field.setNumber(fid_box, "XMin", -10.0)
            gmsh.model.mesh.field.setNumber(fid_box, "XMax", length + 10.0)
            gmsh.model.mesh.field.setNumber(fid_box, "YMin", ymin)
            gmsh.model.mesh.field.setNumber(fid_box, "YMax", ymax)
            gmsh.model.mesh.field.setNumber(fid_box, "ZMin", zmin)
            gmsh.model.mesh.field.setNumber(fid_box, "ZMax", zmax)
            # Grubosc przejscia (gradientu siatki)
            gmsh.model.mesh.field.setNumber(fid_box, "Thickness", dist_max) 
            
            field_ids.append(fid_box)

        if field_ids:
            # Używamy pola Min, aby wziąć najmniejszą wartość z wielu pól (intersekcja wymagań)
            fid_min = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(fid_min, "FieldsList", field_ids)
            gmsh.model.mesh.field.setAsBackgroundMesh(fid_min)
            self.log(f"Zaaplikowano {len(field_ids)} pól zagęszczania.")

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
            
            # Limity
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
            
            # 1. Płaskownik (Y: -tp/2 do tp/2, Z: -bp/2 do bp/2)
            y_p_half = tp / 2.0
            z_p_half = bp / 2.0
            
            # Punkty płaskownika
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

            # 2. Ceowniki (Y startuje od tp/2)
            # Funkcja rysująca kształt C
            def draw_channel(z_start, direction_z):
                dz = direction_z # +1 lub -1
                y_base = tp / 2.0
                
                # Definicja punktów obrysu (uproszczona dla stabilności meshera, bez fizycznych łuków CAD, 
                # ale z zagęszczeniem punktów w narożach)
                
                # Lista krotek (y, z, czy_fillet)
                pts_def = [
                    (y_base, z_start, False),                                     # 0. Narożnik zewn dolny
                    (y_base + h, z_start, False),                                 # 1. Narożnik zewn górny
                    (y_base + h, z_start + b_flange * dz, False),                 # 2. Koniec półki górnej zewn
                    (y_base + h - tf, z_start + b_flange * dz, False),            # 3. Koniec półki górnej wewn
                    (y_base + h - tf, z_start + tw * dz + r_root*dz, True),       # 4. Wewn góra (przed łukiem)
                    (y_base + tf + r_root, z_start + tw * dz, True),              # 5. Wewn dół (przed łukiem - wariant uproszczony skosu)
                    (y_base + tf, z_start + b_flange * dz, False),                # 6. Koniec półki dolnej wewn
                    (y_base, z_start + b_flange * dz, False)                      # 7. Koniec półki dolnej zewn
                ]
                
                tags = []
                for y, z, is_fillet in pts_def:
                    lc = lc_fillet if is_fillet else lc_global
                    tags.append(factory.addPoint(0, y, z, lc))
                
                lns = []
                for i in range(len(tags)-1):
                    lns.append(factory.addLine(tags[i], tags[i+1]))
                lns.append(factory.addLine(tags[-1], tags[0])) # Zamknięcie
                
                return factory.addPlaneSurface([factory.addCurveLoop(lns)])

            # Lewy (Z < 0, stopki w prawo czyli +Z) -> direction_z = 1
            # Prawy (Z > 0, stopki w lewo czyli -Z) -> direction_z = -1
            # Zaczepienie na krawędziach płaskownika: -bp/2 i bp/2
            face_left = draw_channel(-bp/2.0, 1)
            face_right = draw_channel(bp/2.0, -1)
            
            factory.synchronize()

            # Extrude (Wyciągnięcie w X)
            vol_plate = factory.extrude([(2, face_plate)], L, 0, 0)
            vol_left = factory.extrude([(2, face_left)], L, 0, 0)
            vol_right = factory.extrude([(2, face_right)], L, 0, 0)
            
            factory.synchronize()

            # Fragment (Scalanie brył w jedną topologię)
            # Zbieramy tagi objętości (dim=3)
            v_input = []
            for v_list in [vol_plate, vol_left, vol_right]:
                for dim, tag in v_list:
                    if dim == 3: v_input.append((3, tag))
            
            # Opcjonalne naprawianie
            try: factory.healShapes(v_input)
            except: pass
            
            frag_out, _ = factory.fragment(v_input, v_input)
            factory.synchronize()
            
            # Grupa fizyczna dla całej objętości
            final_vols = [tag for dim, tag in frag_out if dim == 3]
            gmsh.model.addPhysicalGroup(3, final_vols, name="VOL_ALL")
            
            # NIE tworzymy Physical Surface, aby nie eksportować elementów 2D do .inp (CalculiX tego nie lubi w 3D)

            # --- APLIKACJA PÓŁ ZAGĘSZCZEŃ ---
            ref_zones = params.get("refinement_zones", [])
            if ref_zones:
                self._apply_refinement(ref_zones, lc_global, p_data, pl_data, L)

            # --- SIATKA ---
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(3)
            
            if element_order == 2:
                self.log("Konwersja do elementów 2. rzędu...")
                gmsh.model.mesh.setOrder(2)
            
            # --- EKSPORT WĘZŁÓW I GRUP ---
            self.log("Identyfikacja grup węzłów...")
            eps = 1.0 # Tolerancja 1mm
            y_int = tp / 2.0
            
            # Manualne wybieranie węzłów
            supp_nodes = self._get_nodes_manual(-eps, -1e4, -1e4, eps, 1e4, 1e4)
            load_nodes = self._get_nodes_manual(L-eps, -1e4, -1e4, L+eps, 1e4, 1e4)
            # Interface: Y bliskie tp/2
            int_nodes = self._get_nodes_manual(-eps, y_int-eps, -1e4, L+eps, y_int+eps, 1e4)
            
            groups_data = {
                "SURF_SUPPORT": supp_nodes,
                "SURF_LOAD": load_nodes,
                "GRP_INTERFACE": int_nodes
            }
            
            self.log(f"Znaleziono węzły: Supp={len(supp_nodes)}, Load={len(load_nodes)}")
            
            # Ścieżki plików
            nodes_csv = os.path.join(out_dir, f"{name}_nodes.csv")
            groups_json = os.path.join(out_dir, f"{name}_groups.json")
            path_inp = os.path.join(out_dir, f"{name}.inp")
            path_msh = os.path.join(out_dir, f"{name}.msh")
            
            # Zapis CSV z mapą węzłów (dla Engine FEM)
            tags_all, coords_all, _ = gmsh.model.mesh.getNodes()
            # Uwaga: getNodes może zwrócić bardzo dużo danych.
            
            with open(nodes_csv, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["NodeID", "X", "Y", "Z"])
                for i in range(len(tags_all)):
                    # coords_all jest płaskie: x,y,z,x,y,z...
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