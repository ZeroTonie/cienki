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
            # Logi na terminal = 1 aby widziec bledy kernela
            gmsh.option.setNumber("General.Terminal", 1)
            gmsh.option.setNumber("General.Verbosity", 5) 
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

            hc = float(p_data['hc'])
            bc = float(p_data['bc'])
            twc = float(p_data['twc'])
            tfc = float(p_data['tfc'])
            tp = float(pl_data['tp'])
            bp = float(pl_data['bp'])

            # Wymiary Y
            y_plate = 0.0
            y_web_bot = tp/2.0 + tfc/2.0
            y_web_top = tp/2.0 + hc - tfc/2.0
            
            # Wymiary Z
            z_plate_L = -bp/2.0
            z_plate_R = bp/2.0
            z_web_L = -bp/2.0 + twc/2.0
            z_web_R = bp/2.0 - twc/2.0
            flange_len = bc - twc/2.0

            # A. PŁASKOWNIK
            pt_pl_1 = factory.addPoint(0, y_plate, z_plate_L)
            pt_pl_2 = factory.addPoint(0, y_plate, z_plate_R)
            l_plate = factory.addLine(pt_pl_1, pt_pl_2)
            
            # B. CEOWNIKI
            # Lewy
            p_LB_root = factory.addPoint(0, y_web_bot, z_web_L)
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

            # --- BEZPIECZNA EKSTRUZJA ---
            def extrude_line(line_tag):
                res = factory.extrude([(1, line_tag)], L, 0, 0)
                for dim, tag in res:
                    if dim == 2: return tag
                return None

            s_plate = extrude_line(l_plate)
            
            s_L_fbot = extrude_line(l_LB_flange)
            s_L_web  = extrude_line(l_L_web)
            s_L_ftop = extrude_line(l_LT_flange)
            
            s_R_fbot = extrude_line(l_RB_flange)
            s_R_web  = extrude_line(l_R_web)
            s_R_ftop = extrude_line(l_RT_flange)

            factory.synchronize()

            # --- FRAGMENTACJA (zamiast Embed) ---
            pt_wL_1 = factory.addPoint(0, y_plate, z_web_L)
            pt_wL_2 = factory.addPoint(L, y_plate, z_web_L)
            l_weld_L = factory.addLine(pt_wL_1, pt_wL_2)
            
            pt_wR_1 = factory.addPoint(0, y_plate, z_web_R)
            pt_wR_2 = factory.addPoint(L, y_plate, z_web_R)
            l_weld_R = factory.addLine(pt_wR_1, pt_wR_2)
            
            frag_res, frag_map = factory.fragment([(2, s_plate)], [(1, l_weld_L), (1, l_weld_R)])
            factory.synchronize()
            
            final_plate_surfs = []
            if len(frag_map) > 0:
                for dim, tag in frag_map[0]:
                    if dim == 2: final_plate_surfs.append(tag)
            else:
                final_plate_surfs = [s_plate]

            # --- GRUPY FIZYCZNE ---
            gmsh.model.addPhysicalGroup(2, final_plate_surfs, name="SHELL_PLATE")
            gmsh.model.addPhysicalGroup(2, [s_L_web, s_R_web], name="SHELL_WEBS")
            gmsh.model.addPhysicalGroup(2, [s_L_fbot, s_L_ftop, s_R_fbot, s_R_ftop], name="SHELL_FLANGES")

            # --- GRUPY MASTER/SLAVE ---
            def get_lines_at_z(surfaces, z_target, tol=0.1):
                found = []
                for s_tag in surfaces:
                    bounds = gmsh.model.getBoundary([(2, s_tag)], oriented=False)
                    for dim, tag in bounds:
                        if dim == 1:
                            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(1, tag)
                            if abs(zmin - z_target) < tol and abs(zmax - z_target) < tol:
                                if abs(xmax - xmin) > 1.0: 
                                    found.append(tag)
                return list(set(found))

            master_L = get_lines_at_z(final_plate_surfs, z_web_L)
            master_R = get_lines_at_z(final_plate_surfs, z_web_R)
            
            if master_L: gmsh.model.addPhysicalGroup(1, master_L, name="LINE_WELD_L_MASTER")
            if master_R: gmsh.model.addPhysicalGroup(1, master_R, name="LINE_WELD_R_MASTER")

            def get_lines_at_y(surf_tag, y_target, tol=0.1):
                found = []
                bounds = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
                for dim, tag in bounds:
                    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(1, tag)
                    if abs(ymin - y_target) < tol and abs(ymax - y_target) < tol:
                         if abs(xmax - xmin) > 1.0:
                            found.append(tag)
                return found

            slave_L = get_lines_at_y(s_L_web, y_web_bot)
            slave_R = get_lines_at_y(s_R_web, y_web_bot)
            
            if slave_L: gmsh.model.addPhysicalGroup(1, slave_L, name="LINE_WELD_L_SLAVE")
            if slave_R: gmsh.model.addPhysicalGroup(1, slave_R, name="LINE_WELD_R_SLAVE")

            # --- SIATKOWANIE ---
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), lc_global)
            self.log("Generowanie siatki...")
            gmsh.model.mesh.generate(2)
            
            if gmsh.model.mesh.getNodes()[0].size == 0:
                raise Exception("Mesh generation failed (0 nodes).")

            if order == 2:
                self.log("Konwersja do elementow 2. rzedu...")
                gmsh.model.mesh.setOrder(2)

            # --- EKSPORT ---
            path_inp = os.path.join(out_dir, f"{name}_shell.inp")
            path_msh = os.path.join(out_dir, f"{name}_shell.msh")
            groups_json = os.path.join(out_dir, f"{name}_shell_groups.json")
            nodes_csv = os.path.join(out_dir, f"{name}_shell_nodes.csv")

            gmsh.write(path_inp)
            gmsh.write(path_msh)
            
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