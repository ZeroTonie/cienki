import gmsh
import os

def generate_inp_file(job_name, output_path, geo_results, mat_params, load_params, settings):
    """
    Tworzy plik wsadowy .inp dla CalculiX.
    
    Separuje elementy 3D (Solid) od 2D (Dummy).
    Tworzy Rigid Body i Outputy dla wszystkich powierzchni.
    """
    
    with open(output_path, 'w') as f:
        f.write(f"** CALCULIX INPUT DECK FOR {job_name}\n")
        
        # 1. WĘZŁY
        f.write("*NODE, NSET=NALL\n")
        # Pobieramy węzły z bieżącego modelu Gmsh (zakładamy, że jest załadowany)
        nodeTags, nodeCoords, _ = gmsh.model.mesh.getNodes()
        for i in range(len(nodeTags)):
            f.write(f"{nodeTags[i]}, {nodeCoords[3*i]:.6f}, {nodeCoords[3*i+1]:.6f}, {nodeCoords[3*i+2]:.6f}\n")
            
        # Punkty Referencyjne (RP)
        max_id = max(nodeTags) if len(nodeTags) > 0 else 0
        rp_supp = max_id + 1
        rp_load = max_id + 2
        sx, sy, sz = geo_results['ref_point_support']
        lx, ly, lz = geo_results['ref_point_load']
        
        f.write(f"{rp_supp}, {sx:.6f}, {sy:.6f}, {sz:.6f}\n")
        f.write(f"{rp_load}, {lx:.6f}, {ly:.6f}, {lz:.6f}\n")
        f.write(f"*NSET, NSET=N_RP_SUPPORT\n{rp_supp}\n")
        f.write(f"*NSET, NSET=N_RP_LOAD\n{rp_load}\n")

        # 2. ELEMENTY (Separacja 3D / 2D)
        phys_groups = gmsh.model.getPhysicalGroups()
        for dim, tag in phys_groups:
            name = gmsh.model.getPhysicalName(dim, tag)
            entities = gmsh.model.getEntitiesForPhysicalGroup(dim, tag)
            
            for entity in entities:
                elemTypes, elemTags, elemNodeTags = gmsh.model.mesh.getElements(dim, entity)
                for j, eType in enumerate(elemTypes):
                    # Mapowanie
                    ccx_type = ""
                    is_solid = False
                    if eType == 4: ccx_type="C3D4"; is_solid=True
                    elif eType == 11: ccx_type="C3D10"; is_solid=True
                    elif eType == 2: ccx_type="S3"
                    elif eType == 9: ccx_type="S6"
                    
                    if not ccx_type: continue
                    
                    elset_name = "E_VOL" if is_solid else f"E_SURF_{name}"
                    f.write(f"*ELEMENT, TYPE={ccx_type}, ELSET={elset_name}\n")
                    
                    # Zapis węzłów
                    npe = 10 if ccx_type=="C3D10" else (4 if ccx_type=="C3D4" else (6 if ccx_type=="S6" else 3))
                    tags = elemTags[j]
                    nodes = elemNodeTags[j]
                    
                    for k in range(len(tags)):
                        nds = nodes[k*npe : (k+1)*npe]
                        f.write(f"{tags[k]}, " + ", ".join(map(str, nds)) + "\n")

        # 3. ZBIORY WĘZŁÓW DLA POWIERZCHNI (Do Rigid Body i Outputu)
        known_surfs = ["SUPPORT_FACE", "LOAD_FACE", "CONTACT_C1_Z_POS", "CONTACT_C2_Z_NEG", 
                       "FLATBAR_TOP", "WEB_SURFACES", "FLANGES_FREE"]
        
        for s in known_surfs:
            f.write(f"*NSET, NSET=N_{s}, ELSET=E_SURF_{s}\n")

        # 4. MATERIAŁ I SEKCJE
        mat = mat_params.get('name', 'STEEL')
        E = mat_params.get('E', 210000)
        nu = mat_params.get('nu', 0.3)
        
        # Solid Material
        f.write(f"*MATERIAL, NAME={mat}\n*ELASTIC\n{E}, {nu}\n")
        f.write(f"*SOLID SECTION, ELSET=E_VOL, MATERIAL={mat}\n")
        
        # Dummy Material (2D)
        f.write("*MATERIAL, NAME=DUMMY\n*ELASTIC\n1.0, 0.3\n")
        for s in known_surfs:
            f.write(f"*SHELL SECTION, ELSET=E_SURF_{s}, MATERIAL=DUMMY\n0.001\n")

        # 5. WARUNKI BRZEGOWE (Rigid Body)
        f.write(f"*RIGID BODY, NSET=N_SUPPORT_FACE, REF NODE={rp_supp}\n")
        f.write(f"*RIGID BODY, NSET=N_LOAD_FACE, REF NODE={rp_load}\n")
        
        f.write("*STEP\n*STATIC\n")
        f.write("*BOUNDARY\n")
        f.write(f"{rp_supp}, 1, 6\n") # Utwierdzenie

        # 6. OBCIĄŻENIA (Na RP Load)
        f.write("*CLOAD\n")
        # Fx (Oś X), Fy (Oś Y), Fz (Oś Z)
        if abs(load_params['Fx']) > 1e-5: f.write(f"{rp_load}, 1, {load_params['Fx']}\n")
        if abs(load_params['Fy']) > 1e-5: f.write(f"{rp_load}, 2, {load_params['Fy']}\n")
        if abs(load_params['Fz']) > 1e-5: f.write(f"{rp_load}, 3, {load_params['Fz']}\n")
        
        # Momenty: Mx (rot X), My (rot Y), Mz (rot Z)
        if abs(load_params['Mx']) > 1e-5: f.write(f"{rp_load}, 4, {load_params['Mx']}\n")
        if abs(load_params['My']) > 1e-5: f.write(f"{rp_load}, 5, {load_params['My']}\n")
        if abs(load_params['Mz']) > 1e-5: f.write(f"{rp_load}, 6, {load_params['Mz']}\n")

        # 7. OUTPUT
        f.write("*NODE FILE\nU, RF\n") # Do .frd
        f.write("*EL FILE\nS, E\n")
        
        # Output tabelaryczny (.dat) dla wszystkich powierzchni
        for s in known_surfs:
            f.write(f"*NODE PRINT, NSET=N_{s}, TOTALS=YES\nU, RF\n")
            
        f.write("*END STEP\n")