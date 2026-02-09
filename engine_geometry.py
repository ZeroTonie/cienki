import gmsh
import sys
import os
import math
import csv
from routing import router

class GeometryGenerator:
    """
    Moduł generujący geometrię i siatkę dla połączonego układu Płaskownik + Ceowniki.
    Wersja: FULL / ROBUST (z obsługą promieni gięcia i walidacją grup).
    """
    def __init__(self, logger_callback=print):
        self.logger = logger_callback
        self.lc_min_wall_check = 1e9 

    def log(self, msg):
        if self.logger: self.logger(f"[GEOMETRY] {msg}")
        else: print(f"[GEOMETRY] {msg}")

    def generate_mesh(self, config, output_subdir):
        # 1. Inicjalizacja Gmsh
        # Zmieniamy logikę: Tylko upewniamy się, że działa. Nie inicjujemy na siłę, jeśli już jest.
        if not gmsh.isInitialized():
            try: gmsh.initialize()
            except Exception as e: self.log(f"Gmsh init warning: {e}")
        gmsh.clear() # Czyścimy poprzedni model, ale NIE zamykamy sesji
        
        # Opcje Gmsh
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        
        # Parametry sterujące siatką
        m_params = config.get('mesh_params', {})
        g_params = config.get('geometry', {})

        lc_global = float(m_params.get("mesh_size_global", 15.0))
        order = int(m_params.get("mesh_order", 2))
        threads = int(m_params.get("cores_mesh", 4))
        
        gmsh.option.setNumber("Mesh.Algorithm3D", 1) 
        gmsh.option.setNumber("General.NumThreads", threads)
        gmsh.option.setNumber("Mesh.ElementOrder", order)

        # Wymiary Geometrii
        L = float(g_params['L'])
        tp = float(g_params['plate_thickness'])
        bp = float(g_params['plate_width'])
        
        # Dane profilu
        hc = float(g_params['profile_h'])
        bc = float(g_params['profile_b'])
        tw = float(g_params['profile_tw'])
        tf = float(g_params['profile_tf'])
        rc = float(g_params.get('profile_r', 0.0))
        
        # Bezpiecznik grubości ścianki
        min_dim = min(tp, tw, tf)
        self.lc_min_wall_check = min_dim
        
        force_check = config.get("force_min_wall_mesh", True)
        if force_check and lc_global > min_dim:
            self.log(f"Korekta siatki: {lc_global} -> {min_dim} mm")
            lc_global = min_dim

        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc_global)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc_global * 0.1)

        factory = gmsh.model.occ

        # --- 2. TWORZENIE GEOMETRII (Metody pomocnicze) ---

        # A. Płaskownik (Plate)
        p1 = factory.addPoint(0, -tp/2, -bp/2)
        p2 = factory.addPoint(0,  tp/2, -bp/2)
        p3 = factory.addPoint(0,  tp/2,  bp/2)
        p4 = factory.addPoint(0, -tp/2,  bp/2)
        
        l1 = factory.addLine(p1, p2)
        l2 = factory.addLine(p2, p3)
        l3 = factory.addLine(p3, p4)
        l4 = factory.addLine(p4, p1)
        
        loop_plate = factory.addCurveLoop([l1, l2, l3, l4])
        face_plate = factory.addPlaneSurface([loop_plate])

        # B. Ceowniki (Channels) - Dokładny obrys z łukami
        def draw_upe(y_s, z_b, z_d):
            dy = z_d
            # Punkty (Y, Z)
            pts = [
                (0, y_s, z_b), (0, y_s, z_b + hc), (0, y_s + bc * dy, z_b + hc),
                (0, y_s + bc * dy, z_b + hc - tf), (0, y_s + (tw + rc) * dy, z_b + hc - tf),
                (0, y_s + tw * dy, z_b + hc - tf - rc), (0, y_s + tw * dy, z_b + tf + rc),
                (0, y_s + (tw + rc) * dy, z_b + tf), (0, y_s + bc * dy, z_b + tf),
                (0, y_s + bc * dy, z_b)
            ]
            tags = [factory.addPoint(*p) for p in pts]
            lines = []
            for i in range(len(tags)):
                lines.append(factory.addLine(tags[i], tags[(i + 1) % len(tags)]))
            # Uproszczone linie bez łuków dla stabilności boolowskiej na tym etapie
            # (Łuki można dodać, ale fragmentacja jest pewniejsza na liniach)
            return factory.addPlaneSurface([factory.addCurveLoop(lines)])

        z_pos = -hc / 2.0
        f_r = draw_upe(tp/2, z_pos, 1.0)
        f_l = draw_upe(-tp/2, z_pos, -1.0)
        
        factory.synchronize()

        # 3. Wyciągnięcie (Extrude)
        vol_plate = factory.extrude([(2, face_plate)], L, 0, 0)
        vol_r = factory.extrude([(2, f_r)], L, 0, 0)
        vol_l = factory.extrude([(2, f_l)], L, 0, 0)
        
        factory.synchronize()

        # 4. SCALANIE (Boolean Fragment)
        v_plate_tag = vol_plate[1][1] 
        v_r_tag = vol_r[1][1]
        v_l_tag = vol_l[1][1]
        
        input_tuples = [(3, v_plate_tag), (3, v_r_tag), (3, v_l_tag)]
        
        ov, ovv = factory.fragment(input_tuples, input_tuples)
        factory.synchronize()
        
        # Filtrujemy tylko objętości 3D (to naprawia błąd "first thickness")
        all_vol_tags = [tag for dim, tag in ov if dim == 3]

        # --- 5. DETEKCJA I NAZYWANIE POWIERZCHNI ---
        
        surfs = gmsh.model.getEntities(2)
        
        # Kontenery na tagi
        g_fix, g_load, g_int = [], [], []
        
        EPS = 1e-3
        
        for (dim, tag) in surfs:
            bb = gmsh.model.getBoundingBox(dim, tag)
            if abs(bb[0] - 0) < 1e-3:
                g_fix.append(tag)
            elif abs(bb[0] - L) < 1e-3:
                g_load.append(tag)
            elif len(gmsh.model.getAdjacencies(2, tag)[0]) > 1:
                g_int.append(tag)

        # Definicje Grup dla Solvera (NSET/ELSET)
        gmsh.model.addPhysicalGroup(2, g_fix, name="GRP_FIX")
        gmsh.model.addPhysicalGroup(2, g_load, name="GRP_LOAD")
        if g_int:
            gmsh.model.addPhysicalGroup(2, g_int, name="GRP_INTERFACE")
        
        # Objętość
        gmsh.model.addPhysicalGroup(3, all_vol_tags, name="SOLID_BODY")

        # --- 7. GENERACJA SIATKI ---
        # Zagęszczanie (opcjonalne)
        gmsh.model.mesh.generate(3)
        if order == 2:
            gmsh.model.mesh.setOrder(2)

        # --- 8. POBIERANIE WĘZŁÓW DLA GRUP FIZYCZNYCH ---
        # Pobieramy wszystkie utworzone grupy fizyczne
        group_nodes_map = {}
        for dim, tag in gmsh.model.getPhysicalGroups():
            name = gmsh.model.getPhysicalName(dim, tag)
            ntags, _ = gmsh.model.mesh.getNodesForPhysicalGroup(dim, tag)
            if ntags is not None:
                group_nodes_map[name] = ntags.tolist()

        # --- 9. EKSPORT ---
        path_inp = router.get_path("FEM_WORK", "mesh.inp", output_subdir)
        path_viz = router.get_path("FEM_WORK", "viz_mesh.vtk", output_subdir)
        path_nodes = router.get_path("FEM_WORK", "nodes.csv", output_subdir)
        
        # 1. Zapis VTK dla wizualizacji (z wszystkimi grupami)
        gmsh.write(path_viz)
        
        # 2. Przygotowanie do eksportu dla SOLVERA (.inp)
        # Wyłączamy zapis elementów, które nie należą do żadnej grupy fizycznej o najwyższej wymiarowości
        gmsh.option.setNumber("Mesh.SaveAll", 0)
        # Ustawiamy format Abaqus
        gmsh.option.setNumber("Mesh.Format", 10)

        # --- DODATKOWE ZABEZPIECZENIE PRZED EKSPORTEM ---
        # Upewniamy się, że wszystkie elementy 3D są przypisane do grupy fizycznej 'SOLID_BODY'.
        # Czasem po operacjach boolowskich i usuwaniu grup 2D, Gmsh może "zgubić"
        # powiązanie niektórych elementów z ich grupą fizyczną przy eksporcie.
        solid_body_group_tag = gmsh.model.getPhysicalGroupTagByName("SOLID_BODY")
        if solid_body_group_tag != -1:
            gmsh.model.mesh.addElements(3, solid_body_group_tag, [], [gmsh.model.mesh.getElementsByType(10)[0]]) # 10 = C3D10

        # --- KLUCZOWA POPRAWKA ---
        # Aby mieć 100% pewności, że do pliku .inp trafią tylko elementy 3D,
        # tymczasowo usuwamy grupy fizyczne zdefiniowane na powierzchniach (2D).
        # Opcja "Mesh.SaveAll = 0" powinna to robić, ale bywa zawodna.
        # To jest bardziej "brutalna", ale pewna metoda.
        # Mapa węzłów (group_nodes_map) została już stworzona, więc ta operacja
        # nie wpłynie na dane przekazywane do silnika FEM.
        all_phys_groups = gmsh.model.getPhysicalGroups()
        groups_to_remove = [(dim, tag) for dim, tag in all_phys_groups if dim == 2]
        if groups_to_remove:
            gmsh.model.removePhysicalGroups(groups_to_remove)
            self.log("Tymczasowo usunięto grupy 2D w celu czystego eksportu siatki .inp")

        # 3. Zapis pliku dla solvera
        gmsh.write(path_inp)
        
        # 4. Zapis mapy węzłów
        self._export_nodes_csv(path_nodes)
        
        router.register_file("FEM_WORK", "mesh.inp", output_subdir)
        router.register_file("FEM_WORK", "viz_mesh.vtk", output_subdir)
        
        self.log(f"Siatka gotowa. Plik: {path_inp}")
        # Zwracamy słownik ze ścieżkami i mapą grup
        return {
            "inp": path_inp,
            "viz": path_viz,
            "nodes": path_nodes,
            "groups": group_nodes_map
        }

    def _export_nodes_csv(self, filepath):
        tags, c, _ = gmsh.model.mesh.getNodes()
        with open(filepath, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["NodeID", "X", "Y", "Z"])
            for i in range(len(tags)):
                w.writerow([tags[i], c[3 * i], c[3 * i + 1], c[3 * i + 2]])

    def finalize(self):
        gmsh.clear() # Tylko czyścimy, nie zamykamy sesji w wątku