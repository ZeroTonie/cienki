import gmsh
import sys
import os
import math

def calculate_cog(dim, tags):
    """
    Oblicza rzeczywisty środek ciężkości (Center of Gravity) dla grupy obiektów.
    """
    total_area = 0.0
    moment_x = 0.0
    moment_y = 0.0
    moment_z = 0.0
    
    for tag in tags:
        try:
            mass = gmsh.model.occ.getMass(dim, tag)
            com = gmsh.model.occ.getCenterOfMass(dim, tag)
            
            total_area += mass
            moment_x += com[0] * mass
            moment_y += com[1] * mass
            moment_z += com[2] * mass
        except Exception as e:
            # Fallback: BoundingBox
            bb = gmsh.model.getBoundingBox(dim, tag)
            cx, cy, cz = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2, (bb[2]+bb[5])/2
            total_area += 1.0
            moment_x += cx
            moment_y += cy
            moment_z += cz

    if total_area <= 1e-9:
        return (0.0, 0.0, 0.0)
        
    return (moment_x / total_area, moment_y / total_area, moment_z / total_area)

def create_rect_yz(occ, y_start, z_start, height, width):
    """
    Pomocnicza funkcja tworząca prostokąt na płaszczyźnie YZ przy użyciu linii.
    Unika błędu 'float interpreted as integer' w addRectangle.
    Zwraca tag powierzchni.
    """
    # Punkty (X zawsze 0)
    p1 = occ.addPoint(0, y_start, z_start)
    p2 = occ.addPoint(0, y_start + height, z_start)
    p3 = occ.addPoint(0, y_start + height, z_start + width)
    p4 = occ.addPoint(0, y_start, z_start + width)
    
    # Linie
    l1 = occ.addLine(p1, p2)
    l2 = occ.addLine(p2, p3)
    l3 = occ.addLine(p3, p4)
    l4 = occ.addLine(p4, p1)
    
    # Pętla i Powierzchnia
    loop = occ.addCurveLoop([l1, l2, l3, l4])
    surf = occ.addPlaneSurface([loop])
    
    return surf

def create_and_mesh_model(geometry_params, mesh_params, job_name, output_dir):
    """
    Generuje geometrię i siatkę w GMSH.
    UWAGA: Zakłada, że gmsh.initialize() zostało wywołane w wątku głównym GUI.
    Tutaj robimy tylko gmsh.clear().
    """
    
    # Czyścimy poprzedni model zamiast inicjalizować nowy proces
    gmsh.clear()
    
    gmsh.model.add(job_name)
    occ = gmsh.model.occ
    
    # 1. Rozpakowanie danych geometrii
    L = float(geometry_params['L'])
    tp = float(geometry_params['tp'])
    bp = float(geometry_params['bp'])
    hc = float(geometry_params['hc'])
    bc = float(geometry_params['bc'])
    twc = float(geometry_params['twc'])
    tfc = float(geometry_params['tfc'])
    yc_global = float(geometry_params['yc_global'])

    # 2. Parametry siatki (Nowe parametry)
    # base_mesh_size: wielkość podstawowa elementu (wpisana przez usera)
    # min_wall_factor: mnożnik dla najcieńszej ścianki (np. 0.2)
    user_base_size = float(mesh_params.get('base_mesh_size', 10.0))
    min_wall_factor = float(mesh_params.get('min_wall_factor', 0.5))
    
    # Znajdujemy najcieńszą ściankę
    min_thickness = min(tp, twc, tfc)
    
    # Rozmiar minimalny to ułamek grubości ścianki (dla detali)
    calculated_min_size = min_thickness * min_wall_factor
    
    # Rozmiar maksymalny to zadeklarowana wielkość bazowa
    calculated_max_size = user_base_size

    # --------------------------------------------------------------------------
    # 3. TWORZENIE PRZEKROJU 2D (Płaszczyzna YZ, X=0) METODĄ PUNKTOWĄ
    # --------------------------------------------------------------------------
    # A. Płaskownik
    # Y: 0 do tp, Z: -bp/2 do bp/2
    # create_rect_yz(occ, y_start, z_start, dy, dz)
    tag_flat = create_rect_yz(occ, 0, -bp/2, tp, bp)
    
    # B. Ceowniki
    z_web_inner = bp/2 - twc
    y_top = 0
    y_bot = -hc
    
    # Ceownik 1 (Prawy) - budujemy z 3 prostokątów i łączymy (Fuse)
    # Środnik
    web1 = create_rect_yz(occ, y_bot, z_web_inner, hc, twc)
    # Stopka górna
    flange_top1 = create_rect_yz(occ, y_top - tfc, z_web_inner - (bc-twc), tfc, bc-twc)
    # Stopka dolna
    flange_bot1 = create_rect_yz(occ, y_bot, z_web_inner - (bc-twc), tfc, bc-twc)
    
    # Scalanie C1
    c1_fused, _ = occ.fuse([(2, web1)], [(2, flange_top1), (2, flange_bot1)])
    tag_c1 = c1_fused[0][1]
    
    # C. Ceownik 2 (Lewy - Lustro)
    c2_copy = occ.copy([(2, tag_c1)])
    occ.mirror(c2_copy, 0, 0, 0, 0, 0, 1) 
    tag_c2 = c2_copy[0][1]

    # --------------------------------------------------------------------------
    # 4. POZYCJONOWANIE (Centrowanie Płaskownika w Y=0)
    # --------------------------------------------------------------------------
    dy_shift = -tp / 2.0
    occ.translate([(2, tag_flat), (2, tag_c1), (2, tag_c2)], 0, dy_shift, 0)
    
    # Poziom styku (potrzebny do detekcji powierzchni)
    y_contact_level = dy_shift

    # --------------------------------------------------------------------------
    # 5. WYCIĄGANIE (EXTRUDE)
    # --------------------------------------------------------------------------
    vol_flat = occ.extrude([(2, tag_flat)], L, 0, 0)
    vol_c1 = occ.extrude([(2, tag_c1)], L, 0, 0)
    vol_c2 = occ.extrude([(2, tag_c2)], L, 0, 0)
    
    v_flat_tag = vol_flat[1][1]
    v_c1_tag = vol_c1[1][1]
    v_c2_tag = vol_c2[1][1]
    
    occ.synchronize()

    # --------------------------------------------------------------------------
    # 6. FRAGMENTACJA (Spójna Siatka)
    # --------------------------------------------------------------------------
    input_volumes = [(3, v_flat_tag), (3, v_c1_tag), (3, v_c2_tag)]
    occ.fragment(input_volumes, input_volumes)
    occ.synchronize()
    
    # --------------------------------------------------------------------------
    # 7. GRUPY FIZYCZNE I DETEKCJA POWIERZCHNI
    # --------------------------------------------------------------------------
    all_surfs = gmsh.model.getEntities(2)
    surfaces_map = {
        "SUPPORT_FACE": [],
        "LOAD_FACE": [],
        "CONTACT_C1_Z_POS": [],
        "CONTACT_C2_Z_NEG": [],
        "FLATBAR_TOP": [],
        "WEB_SURFACES": [],
        "FLANGES_FREE": []
    }
    
    eps = 1e-3
    
    for s in all_surfs:
        tag = s[1]
        bb = gmsh.model.getBoundingBox(2, tag)
        cx, cy, cz = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2, (bb[2]+bb[5])/2
        
        # 1. Utwierdzenie (X=0)
        if abs(cx - 0.0) < eps:
            surfaces_map["SUPPORT_FACE"].append(tag)
        # 2. Obciążenie (X=L)
        elif abs(cx - L) < eps:
            surfaces_map["LOAD_FACE"].append(tag)
        # 3. Styki (Y = y_contact_level)
        elif abs(cy - y_contact_level) < eps:
            if abs(cz) < (bp/2 + eps):
                if cz > eps: surfaces_map["CONTACT_C1_Z_POS"].append(tag)
                elif cz < -eps: surfaces_map["CONTACT_C2_Z_NEG"].append(tag)
        # 4. Góra Płaskownika (Y = y_contact + tp)
        elif abs(cy - (y_contact_level + tp)) < eps:
            surfaces_map["FLATBAR_TOP"].append(tag)
        # 5. Środniki (Zew. pionowe, Z = +/- bp/2)
        elif abs(abs(cz) - bp/2) < eps:
            surfaces_map["WEB_SURFACES"].append(tag)

    for name, tags in surfaces_map.items():
        if tags: gmsh.model.addPhysicalGroup(2, tags, name=name)
        
    all_vols = gmsh.model.getEntities(3)
    v_tags = [v[1] for v in all_vols]
    gmsh.model.addPhysicalGroup(3, v_tags, name="PART_SOLID")

    # --------------------------------------------------------------------------
    # 8. OBLICZANIE PUNKTÓW REFERENCYJNYCH (COG)
    # --------------------------------------------------------------------------
    rp_support = calculate_cog(2, surfaces_map["SUPPORT_FACE"])
    rp_load = calculate_cog(2, surfaces_map["LOAD_FACE"])
    
    # --------------------------------------------------------------------------
    # 9. SIATKOWANIE I PARAMETRY
    # --------------------------------------------------------------------------
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", calculated_min_size)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", calculated_max_size)
    
    mesh_order = mesh_params.get('mesh_order', 2)
    gmsh.option.setNumber("Mesh.ElementOrder", mesh_order)
    
    cores_mesh = mesh_params.get('mesh_cores', 4)
    gmsh.option.setNumber("General.NumThreads", cores_mesh)
    
    # Algorytm: 1=Delaunay, 4=Frontal, 10=HXT (Dobre dla parallel)
    # HXT (10) jest świetny do wielowątkowości w 3D
    gmsh.option.setNumber("Mesh.Algorithm3D", 10) 
    
    gmsh.model.mesh.generate(3)
    
    # Optymalizacja HighOrder (jeśli rząd > 1)
    if mesh_order > 1:
        gmsh.model.mesh.optimize("HighOrder")
    else:
        gmsh.model.mesh.optimize("Netgen")
    
    msh_path = os.path.join(output_dir, f"{job_name}.msh")
    gmsh.write(msh_path)
    
    stl_path = os.path.join(output_dir, f"{job_name}_vis.stl")
    gmsh.write(stl_path)
    
    return {
        "msh_file": msh_path,
        "stl_file": stl_path,
        "ref_point_support": rp_support,
        "ref_point_load": rp_load
    }