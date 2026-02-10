import gmsh
import sys
import os
import math

def calculate_cog(dim, tags):
    """
    Oblicza środek ciężkości (Center of Gravity) dla grupy obiektów.
    Wykorzystuje silnik OCC do ważenia powierzchni masą (polem).
    """
    total_area = 0.0
    moment_x = 0.0
    moment_y = 0.0
    moment_z = 0.0
    
    for tag in tags:
        try:
            # getMass dla powierzchni (dim=2) zwraca jej pole
            mass = gmsh.model.occ.getMass(dim, tag)
            # getCenterOfMass zwraca krotkę (x, y, z)
            com = gmsh.model.occ.getCenterOfMass(dim, tag)
            
            total_area += mass
            moment_x += com[0] * mass
            moment_y += com[1] * mass
            moment_z += com[2] * mass
        except Exception as e:
            # Fallback: W rzadkim przypadku błędu OCC używamy środka BoundingBox
            # (mniej dokładne dla niesymetrycznych kształtów, ale bezpieczne)
            print(f"[Warning] COG calculation fallback for tag {tag}: {e}")
            bb = gmsh.model.getBoundingBox(dim, tag)
            cx, cy, cz = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2, (bb[2]+bb[5])/2
            # Aproksymacja: dodajemy jako wagę 1.0 (średnia arytmetyczna)
            total_area += 1.0
            moment_x += cx
            moment_y += cy
            moment_z += cz

    if total_area <= 1e-9:
        return (0.0, 0.0, 0.0)
        
    return (moment_x / total_area, moment_y / total_area, moment_z / total_area)

def create_and_mesh_model(geometry_params, mesh_params, job_name, output_dir):
    """
    Generuje geometrię i siatkę w GMSH dla słupa złożonego.
    Punkty referencyjne liczone dynamicznie ze środków ciężkości powierzchni.
    """
    
    gmsh.initialize()
    gmsh.model.add(job_name)
    occ = gmsh.model.occ
    
    # 1. Rozpakowanie danych
    L = geometry_params['L']
    tp = geometry_params['tp']
    bp = geometry_params['bp']
    hc = geometry_params['hc']
    bc = geometry_params['bc']
    twc = geometry_params['twc']
    tfc = geometry_params['tfc']
    # yc_global - odległość COG od góry płaskownika
    yc_global = geometry_params['yc_global'] 

    # Parametry siatki
    base_mesh_size = min(tp, twc, tfc) * mesh_params.get('mesh_size_factor', 1.0)

    # --------------------------------------------------------------------------
    # 2. TWORZENIE PRZEKROJU 2D (Płaszczyzna YZ, X=0)
    # --------------------------------------------------------------------------
    # A. Płaskownik
    tag_flat = occ.addRectangle(0, 0, -bp/2, 0, tp, bp)
    
    # B. Ceowniki
    # Rozstaw zew. środników = bp
    z_web_inner = bp/2 - twc
    y_top = 0
    y_bot = -hc
    
    # Budowa Ceownika 1 (Prawy)
    web1 = occ.addRectangle(0, y_bot, z_web_inner, 0, hc, twc)
    flange_top1 = occ.addRectangle(0, y_top - tfc, z_web_inner - (bc-twc), 0, tfc, bc-twc)
    flange_bot1 = occ.addRectangle(0, y_bot, z_web_inner - (bc-twc), 0, tfc, bc-twc)
    
    c1_fused, _ = occ.fuse([(2, web1)], [(2, flange_top1), (2, flange_bot1)])
    tag_c1 = c1_fused[0][1]
    
    # C. Ceownik 2 (Lewy - Lustro)
    c2_copy = occ.copy([(2, tag_c1)])
    occ.mirror(c2_copy, 0, 0, 0, 0, 0, 1)
    tag_c2 = c2_copy[0][1]

    # --------------------------------------------------------------------------
    # 3. POZYCJONOWANIE (Centrowanie Płaskownika w Y=0)
    # --------------------------------------------------------------------------
    # Zgodnie z życzeniem, punkt (0,0,0) ma być w geometrycznym środku płaskownika na utwierdzeniu.
    # Płaskownik ma Y od 0 do tp. Jego środek to tp/2.
    # Przesuwamy wszystko w dół o tp/2.
    
    dy_shift = -tp / 2.0
    occ.translate([(2, tag_flat), (2, tag_c1), (2, tag_c2)], 0, dy_shift, 0)
    
    # Poziom styku (potrzebny do detekcji powierzchni)
    y_contact_level = dy_shift

    # --------------------------------------------------------------------------
    # 4. WYCIĄGANIE (EXTRUDE)
    # --------------------------------------------------------------------------
    vol_flat = occ.extrude([(2, tag_flat)], L, 0, 0)
    vol_c1 = occ.extrude([(2, tag_c1)], L, 0, 0)
    vol_c2 = occ.extrude([(2, tag_c2)], L, 0, 0)
    
    v_flat_tag = vol_flat[1][1]
    v_c1_tag = vol_c1[1][1]
    v_c2_tag = vol_c2[1][1]
    
    occ.synchronize()

    # --------------------------------------------------------------------------
    # 5. FRAGMENTACJA
    # --------------------------------------------------------------------------
    input_volumes = [(3, v_flat_tag), (3, v_c1_tag), (3, v_c2_tag)]
    occ.fragment(input_volumes, input_volumes)
    occ.synchronize()
    
    # --------------------------------------------------------------------------
    # 6. GRUPY FIZYCZNE I DETEKCJA POWIERZCHNI
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
                
        # 4. Góra Płaskownika
        elif abs(cy - (y_contact_level + tp)) < eps:
            surfaces_map["FLATBAR_TOP"].append(tag)
            
        # 5. Środniki
        elif abs(abs(cz) - bp/2) < eps:
            surfaces_map["WEB_SURFACES"].append(tag)

    for name, tags in surfaces_map.items():
        if tags: gmsh.model.addPhysicalGroup(2, tags, name=name)
        
    all_vols = gmsh.model.getEntities(3)
    v_tags = [v[1] for v in all_vols]
    gmsh.model.addPhysicalGroup(3, v_tags, name="PART_SOLID")

    # --------------------------------------------------------------------------
    # 7. OBLICZANIE PUNKTÓW REFERENCYJNYCH (COG)
    # --------------------------------------------------------------------------
    # Tutaj dzieje się magia: zamiast zgadywać (0,0,0), pytamy geometrię,
    # gdzie dokładnie leży środek ciężkości wyciętych powierzchni.
    
    rp_support = calculate_cog(2, surfaces_map["SUPPORT_FACE"])
    rp_load = calculate_cog(2, surfaces_map["LOAD_FACE"])
    
    # --------------------------------------------------------------------------
    # 8. SIATKOWANIE I ZAPIS
    # --------------------------------------------------------------------------
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", base_mesh_size * 0.5)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", base_mesh_size)
    gmsh.option.setNumber("Mesh.ElementOrder", mesh_params.get('mesh_order', 2))
    gmsh.option.setNumber("General.NumThreads", mesh_params.get('mesh_cores', 4))
    
    gmsh.model.mesh.generate(3)
    gmsh.model.mesh.optimize("Netgen")
    
    msh_path = os.path.join(output_dir, f"{job_name}.msh")
    gmsh.write(msh_path)
    
    stl_path = os.path.join(output_dir, f"{job_name}_vis.stl")
    gmsh.write(stl_path)
    
    return {
        "msh_file": msh_path,
        "stl_file": stl_path,
        # Zwracamy obliczone COG jako punkty referencyjne
        "ref_point_support": rp_support,
        "ref_point_load": rp_load
    }