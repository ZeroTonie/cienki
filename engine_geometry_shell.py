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
            gmsh.option.setNumber("General.Terminal", 1) 
            gmsh.option.setNumber("Geometry.Tolerance", 1e-4) 
            gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        except: pass

    def _finalize_gmsh(self):
        pass

    def generate_model(self, params):
        self._prepare_gmsh()
        try:
            sys_res = params.get('system_resources', {})
            gmsh.option.setNumber("General.NumThreads", int(sys_res.get('num_threads', 4)))
            
            mesh_cfg = params.get('mesh_size', {})
            lc_global = float(mesh_cfg.get('global', 20.0))
            order = int(mesh_cfg.get('order', 2))
            
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
            y_plate = 0.0
            y_web_bot = tp/2.0 + tfc/2.0
            y_web_top = tp/2.0 + hc - tfc/2.0
            z_plate_L, z_plate_R = -bp/2.0, bp/2.0
            z_web_L, z_web_R = -bp/2.0 + twc/2.0, bp/2.0 - twc/2.0
            flange_len = bc - twc/2.0

            # 1. PŁASKOWNIK
            p1 = factory.addPoint(0, y_plate, z_plate_L)
            p2 = factory.addPoint(0, y_plate, z_plate_R)
            l_plate = factory.addLine(p1, p2)
            
            # 2. CEOWNIKI
            def make_upe(z_pos, direction):
                p_root = factory.addPoint(0, y_web_bot, z_pos)
                p_tip_bot = factory.addPoint(0, y_web_bot, z_pos + flange_len * direction)
                l_bot = factory.addLine(p_tip_bot, p_root)
                p_top = factory.addPoint(0, y_web_top, z_pos)
                l_web = factory.addLine(p_root, p_top)
                p_tip_top = factory.addPoint(0, y_web_top, z_pos + flange_len * direction)
                l_top = factory.addLine(p_top, p_tip_top)
                return l_bot, l_web, l_top

            lL_bot, lL_web, lL_top = make_upe(z_web_L, 1)
            lR_bot, lR_web, lR_top = make_upe(z_web_R, -1)

            factory.synchronize()

            # --- EKSTRUZJA ---
            def safe_extrude(line_tag):
                if line_tag < 0: return -1
                res = factory.extrude([(1, line_tag)], L, 0, 0)
                for dim, tag in res:
                    if dim == 2: return tag
                return -1

            s_plate = safe_extrude(l_plate)
            
            s_L_bot = safe_extrude(lL_bot)
            s_L_web = safe_extrude(lL_web)
            s_L_top = safe_extrude(lL_top)
            
            s_R_bot = safe_extrude(lR_bot)
            s_R_web = safe_extrude(lR_web)
            s_R_top = safe_extrude(lR_top)

            factory.synchronize()
            factory.removeAllDuplicates()
            factory.synchronize()

            # --- GRUPY FIZYCZNE ---
            if s_plate != -1:
                gmsh.model.addPhysicalGroup(2, [s_plate], name="SHELL_PLATE")
            
            web_surfs = [s for s in [s_L_web, s_R_web] if s != -1]
            if web_surfs: gmsh.model.addPhysicalGroup(2, web_surfs, name="SHELL_WEBS")
            
            flange_surfs = [s for s in [s_L_bot, s_L_top, s_R_bot, s_R_top] if s != -1]
            if flange_surfs: gmsh.model.addPhysicalGroup(2, flange_surfs, name="SHELL_FLANGES")

            # --- KRAWĘDZIE DLA TIE (SLAVE) ---
            def get_bottom_line(surf_tag, y_target, z_target):
                if surf_tag == -1: return -1
                bounds = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
                candidates = []
                for dim, tag in bounds:
                    if dim == 1:
                        cm = gmsh.model.occ.getCenterOfMass(1, tag)
                        if abs(cm[1]-y_target) < 0.1 and abs(cm[2]-z_target) < 0.1:
                            candidates.append(tag)
                best_tag = -1; max_len = -1
                for tag in candidates:
                    bbox = gmsh.model.getBoundingBox(1, tag)
                    lx = abs(bbox[3] - bbox[0])
                    if lx > max_len: max_len = lx; best_tag = tag
                return best_tag

            slave_L = get_bottom_line(s_L_web, y_web_bot, z_web_L)
            slave_R = get_bottom_line(s_R_web, y_web_bot, z_web_R)
            
            if slave_L != -1: gmsh.model.addPhysicalGroup(1, [slave_L], name="LINE_WELD_L_SLAVE")
            if slave_R != -1: gmsh.model.addPhysicalGroup(1, [slave_R], name="LINE_WELD_R_SLAVE")

            # --- SIATKOWANIE ---
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), lc_global)
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(2)
            if order == 2: gmsh.model.mesh.setOrder(2)

            # --- EKSPORT ---
            path_inp = os.path.join(out_dir, f"{name}.inp")
            path_msh = os.path.join(out_dir, f"{name}.msh")
            groups_json = os.path.join(out_dir, f"{name}_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_nodes.csv")

            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
            supp_nodes = self._get_nodes_in_x_plane(0.0, tol=1.0)
            load_nodes = self._get_nodes_in_x_plane(L, tol=1.0)
            
            slave_l_ids = self._get_nodes_from_physical_group(1, "LINE_WELD_L_SLAVE")
            slave_r_ids = self._get_nodes_from_physical_group(1, "LINE_WELD_R_SLAVE")

            groups_data = {
                "NSET_SUPPORT": supp_nodes,
                "NSET_LOAD": load_nodes,
                "LINE_WELD_L_SLAVE": slave_l_ids,
                "LINE_WELD_R_SLAVE": slave_r_ids
            }
            
            with open(groups_json, 'w') as f: json.dump(groups_data, f)
            self._export_node_map(nodes_csv)

            return {
                "paths": {"inp": os.path.abspath(path_inp), "nodes_csv": os.path.abspath(nodes_csv), "groups_json": os.path.abspath(groups_json)},
                "stats": {"nodes": gmsh.model.mesh.getNodes()[0].size}
            }
            
        except Exception as e:
            self.log(f"CRITICAL ERROR: {e}")
            traceback.print_exc()
            return None
        finally:
            self._finalize_gmsh()

    def _get_nodes_in_x_plane(self, x_loc, tol=1.0):
        try:
            node_tags, coords, _ = gmsh.model.mesh.getNodes()
            selected = []
            for i in range(len(node_tags)):
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
                    target_tag = t; break
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