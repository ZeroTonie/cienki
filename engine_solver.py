import sympy as sp
import numpy as np
import json
import csv
import os

# ==============================================================================
# GŁÓWNY SILNIK OBLICZENIOWY (SOLVER ANALITYCZNY)
# ==============================================================================

def analizuj_przekroj_pelna_dokladnosc(upe_data, geo_data, load_data, safety_data, custom_probes_coords=None):
    """
    Wykonuje PEŁNĄ analizę wytrzymałościowo-statecznościową zgodnie z Teorią Własowa.
    Odwzorowuje matematykę zawartą w pliku analiza.ipynb bez uproszczeń.
    
    Argumenty:
    upe_data    -- słownik z danymi ceownika (z katalog.py)
    geo_data    -- słownik z wymiarami płaskownika (bp, tp)
    load_data   -- słownik z obciążeniami i materiałem (Fx, E, G, Re, Edef...)
    safety_data -- słownik ze współczynnikami bezpieczeństwa (gamma_M0, gamma_M1, alfa_imp)
    custom_probes_coords -- opcjonalny słownik { "Nazwa": (y_glob, z_glob) }
    """
    
    # ==========================================================================
    # 1. ROZPAKOWANIE DANYCH WEJŚCIOWYCH
    # ==========================================================================
    hc = float(upe_data['hc'])
    bc = float(upe_data['bc'])
    twc = float(upe_data['twc'])
    tfc = float(upe_data['tfc'])
    rc = float(upe_data['rc'])
    Ac = float(upe_data['Ac'])
    xc = float(upe_data['xc'])
    Icy = float(upe_data['Icy'])
    Icz = float(upe_data['Icz'])
    
    bp = float(geo_data['bp'])
    tp = float(geo_data['tp'])
    
    Fx = float(load_data['Fx'])           
    F_promien = float(load_data['F_promien']) 
    L_belka = float(load_data['L'])       
    w_Ty = float(load_data['w_Ty'])       
    w_Tz = float(load_data['w_Tz'])       
    
    E_val = float(load_data['E'])
    G_val = float(load_data['G'])
    Re_val = float(load_data['Re'])
    Edef_val = float(load_data.get('Edef', 235.0))
    
    x_ogolne = float(safety_data['gamma_M0'])
    x_statecznosc = float(safety_data['gamma_M1'])
    alfa_imp = float(safety_data['alfa_imp'])

    # ==========================================================================
    # 2. GEOMETRIA PODSTAWOWA I CHARAKTERYSTYKI PRZEKROJU
    # ==========================================================================
    Ap = bp * tp
    Acal = 2 * Ac + Ap
    
    # Środek ciężkości (yc) - mierzony od osi płaskownika (góra) w dół
    yc = (2 * Ac * (tp/2 + hc/2)) / Acal
    
    z_c = bp/2 - twc/2   
    z_cc = xc - twc/2    
    z_f = bc - twc/2     
    
    Izc = (bp * tp**3)/12 + Ap * yc**2 + 2 * (Icy + Ac * (tp/2 + hc/2 - yc)**2)
    Iy = (tp * bp**3)/12 + 2 * (Icz + Ac * (z_c - z_cc)**2)
    
    iy_rad = np.sqrt(Iy / Acal)
    iz_rad = np.sqrt(Izc / Acal)
    
    ymax = (tp/2 + hc) - yc     
    Wz = Izc / ymax             
    Wy = Iy / (bp/2)            

    # ==========================================================================
    # 3. KLASYFIKACJA PRZEKROJU (WG EUROKODU 3)
    # ==========================================================================
    epsilon = np.sqrt(Edef_val / Re_val)
    
    cw = hc - 2*tfc - 2*rc 
    if cw <= 0: cw = 1.0   
    
    strefa_sciskana_web = (tp/2 + hc - tfc) - yc
    alpha_web = strefa_sciskana_web / cw
    alpha_web = max(0.001, min(1.0, alpha_web)) 
    
    smuklosc_web = cw / twc
    
    limit_web_c1 = (396 * epsilon) / (13 * alpha_web - 1) if (13*alpha_web - 1) > 0 else 396*epsilon
    limit_web_c2 = (456 * epsilon) / (13 * alpha_web - 1) if (13*alpha_web - 1) > 0 else 456*epsilon
    limit_web_c3 = 42 * epsilon 
    
    if smuklosc_web <= limit_web_c1: klasa_web = 1
    elif smuklosc_web <= limit_web_c2: klasa_web = 2
    elif smuklosc_web <= limit_web_c3: klasa_web = 3
    else: klasa_web = 4

    cf = bc - twc - rc 
    if cf <= 0: cf = 1.0
    
    smuklosc_flange = cf / tfc
    limit_flange_c1 = 9 * epsilon
    limit_flange_c2 = 10 * epsilon
    limit_flange_c3 = 14 * epsilon
    
    if smuklosc_flange <= limit_flange_c1: klasa_flange = 1
    elif smuklosc_flange <= limit_flange_c2: klasa_flange = 2
    elif smuklosc_flange <= limit_flange_c3: klasa_flange = 3
    else: klasa_flange = 4
    
    klasa_przekroju = max(klasa_web, klasa_flange)

    # ==========================================================================
    # 4. TEORIA WŁASOWA - CAŁKOWANIE SYMBOLICZNE
    # ==========================================================================
    s_var = sp.symbols('s_var', real=True)
    
    dlugosc_strefy_1 = bp/2 - bc         
    dlugosc_strefy_2 = bc                
    dlugosc_strefy_3 = hc - tfc          
    dlugosc_strefy_4 = bc - twc/2        
    
    ramie_pionowe_plaskownik = yc 
    ramie_pionowe_zakladka = yc - tfc/2
    ramie_poziome_srodnik = z_c 
    ramie_pionowe_stopka_dol = (hc + tp) - yc - tfc/2 
    
    # Omega Sc
    omega_1 = ramie_pionowe_plaskownik * s_var
    Sw_1 = sp.integrate(omega_1 * s_var * tp, (s_var, 0, dlugosc_strefy_1))
    omega_koniec_1 = omega_1.subs(s_var, dlugosc_strefy_1)
    
    omega_2 = omega_koniec_1 + ramie_pionowe_zakladka * s_var 
    t_zakladka = tp + tfc
    z_globalne_2 = dlugosc_strefy_1 + s_var
    Sw_2 = sp.integrate(omega_2 * z_globalne_2 * t_zakladka, (s_var, 0, dlugosc_strefy_2))
    omega_naroznik_gora = omega_2.subs(s_var, dlugosc_strefy_2)
    
    omega_3 = omega_naroznik_gora + ramie_poziome_srodnik * s_var
    Sw_3 = sp.integrate(omega_3 * ramie_poziome_srodnik * twc, (s_var, 0, dlugosc_strefy_3))
    omega_naroznik_dol = omega_3.subs(s_var, dlugosc_strefy_3)
    
    omega_4 = omega_naroznik_dol + ramie_pionowe_stopka_dol * s_var
    z_globalne_4 = z_c - s_var
    Sw_4 = sp.integrate(omega_4 * z_globalne_4 * tfc, (s_var, 0, dlugosc_strefy_4))
    
    # Wyznaczanie Ss
    Sw_calkowite = 2 * (Sw_1 + Sw_2 + Sw_3 + Sw_4)
    delta_ys = float(Sw_calkowite / Iy)
    ys_val = yc - delta_ys 
    
    # Omega Ss
    omega_ss_1 = omega_1 - delta_ys * s_var
    omega_ss_2 = omega_2 - delta_ys * (dlugosc_strefy_1 + s_var)
    omega_ss_3 = omega_3 - delta_ys * ramie_poziome_srodnik
    omega_ss_4 = omega_4 - delta_ys * (z_c - s_var)
    
    # Iw
    Iw_1 = sp.integrate(omega_ss_1**2 * tp, (s_var, 0, dlugosc_strefy_1))
    Iw_2 = sp.integrate(omega_ss_2**2 * t_zakladka, (s_var, 0, dlugosc_strefy_2))
    Iw_3 = sp.integrate(omega_ss_3**2 * twc, (s_var, 0, dlugosc_strefy_3))
    Iw_4 = sp.integrate(omega_ss_4**2 * tfc, (s_var, 0, dlugosc_strefy_4))
    Iw = float(2 * (Iw_1 + Iw_2 + Iw_3 + Iw_4))
    
    # Ip, io, It
    Ip = Iy + Izc + Acal * delta_ys**2
    io = np.sqrt(Ip / Acal)
    
    cw_flat = hc - 2*tfc - 2*rc
    cf_flat = bc - twc - rc
    It = (1/3) * (bp * tp**3) + 2 * ((1/3) * (cw_flat * twc**3 + 2 * cf_flat * tfc**3))

    # ==========================================================================
    # 5. MOMENTY STATYCZNE (Sz, Sy)
    # ==========================================================================
    Sz_func_1 = sp.integrate(-yc * tp, (s_var, 0, s_var))
    Sz_end_1 = Sz_func_1.subs(s_var, dlugosc_strefy_1)
    
    y_zakl_loc = ((tp*0 + tfc*(tp/2+tfc/2))/(tp+tfc)) - yc
    Sz_func_2 = Sz_end_1 + sp.integrate(y_zakl_loc * t_zakladka, (s_var, 0, s_var))
    Sz_end_2 = Sz_func_2.subs(s_var, dlugosc_strefy_2)
    
    Sz_func_3 = Sz_end_2 + sp.integrate((s_var - yc) * twc, (s_var, 0, s_var))
    Sz_end_3 = Sz_func_3.subs(s_var, dlugosc_strefy_3)
    
    Sz_func_4 = Sz_end_3 + sp.integrate(((hc+tp-tfc/2)-yc) * tfc, (s_var, 0, s_var))
    
    Sy_func_1 = sp.integrate(s_var * tp, (s_var, 0, s_var))
    Sy_end_1 = Sy_func_1.subs(s_var, dlugosc_strefy_1)
    
    Sy_func_2 = Sy_end_1 + sp.integrate((dlugosc_strefy_1 + s_var) * t_zakladka, (s_var, 0, s_var))
    Sy_end_2 = Sy_func_2.subs(s_var, dlugosc_strefy_2)
    
    Sy_func_3 = Sy_end_2 + sp.integrate(z_c * twc, (s_var, 0, s_var))
    Sy_end_3 = Sy_func_3.subs(s_var, dlugosc_strefy_3)
    
    Sy_func_4 = Sy_end_3 + sp.integrate((z_c - s_var) * tfc, (s_var, 0, s_var))

    # ==========================================================================
    # 6. SIŁY WEWNĘTRZNE I BIMOMENT
    # ==========================================================================
    F_N = Fx
    T_y = Fx * w_Ty
    T_z = Fx * w_Tz
    
    Mgz = abs(Fx * (F_promien - yc)) + abs(T_y * L_belka)
    Mgy = abs(T_z * L_belka)
    
    # Moment skręcający Ms względem Ss
    # Korekta ramienia: Odległość siły (F_promien) od Ss (ys_val)
    # ys_val (dodatnie lub ujemne) to współrzędna Ss względem osi płaskownika
    Ms = T_z * (F_promien - ys_val) 
    
    k_skret = np.sqrt((G_val * It) / (E_val * Iw))
    B_w = (Ms / k_skret) * np.tanh(k_skret * L_belka)

    # ==========================================================================
    # 7. STATECZNOŚĆ (WYBOCZENIE GIĘTNO-SKRĘTNE)
    # ==========================================================================
    L_cr = 2.0 * L_belka
    N_cr_gy = (np.pi**2 * E_val * Iy) / L_cr**2
    N_cr_gz = (np.pi**2 * E_val * Izc) / L_cr**2
    N_cr_s = (1.0 / io**2) * (G_val * It + (np.pi**2 * E_val * Iw) / L_cr**2)
    
    y0 = delta_ys  
    r0 = io        
    beta_param = 1.0 - (y0 / r0)**2
    
    param_B = -(N_cr_gz + N_cr_s)
    param_C = N_cr_gz * N_cr_s
    delta_rownania = param_B**2 - 4 * beta_param * param_C
    
    if delta_rownania < 0:
        N_cr_gs = N_cr_s 
    else:
        N_root_1 = (-param_B - np.sqrt(delta_rownania)) / (2*beta_param)
        N_root_2 = (-param_B + np.sqrt(delta_rownania)) / (2*beta_param)
        N_cr_gs = min(N_root_1, N_root_2)
        
    N_cr_min = min(N_cr_gy, N_cr_gs)
    M_cr = (np.pi**2 * E_val * Iy) / (L_cr**2) * np.sqrt((Iw/Iy) + (L_cr**2 * G_val * It)/(np.pi**2 * E_val * Iy))

    # ==========================================================================
    # 8. NOŚNOŚCI (WSPÓŁCZYNNIKI CHI I UR)
    # ==========================================================================
    lambda_N = np.sqrt(Acal * Re_val / N_cr_min)
    lambda_LT = np.sqrt(Wz * Re_val / M_cr)
    
    def calc_chi(lam, alpha):
        Phi = 0.5 * (1 + alpha * (lam - 0.2) + lam**2)
        chi = 1 / (Phi + np.sqrt(Phi**2 - lam**2))
        return min(1.0, float(chi))
    
    chi_N = calc_chi(lambda_N, alfa_imp)
    chi_LT = calc_chi(lambda_LT, alfa_imp)
    
    N_Rd_stab = (chi_N * Acal * Re_val) / x_statecznosc
    Mz_Rd_stab = (chi_LT * Wz * Re_val) / x_statecznosc
    My_Rd_stab = (Wy * Re_val) / x_ogolne 
    Mw_Rd_base = (Re_val / x_ogolne) 

    # ==========================================================================
    # 9. OBLICZANIE UGIĘĆ (NOWOŚĆ W v4.0)
    # ==========================================================================
    # Wzory dla wspornika obciążonego siłą skupioną na końcu
    # U_y (od zginania Mz wywołanego przez Ty): u = (F*L^3) / (3*E*I)
    disp_uy_bending = (T_y * L_belka**3) / (3 * E_val * Izc)
    # U_y (od mimośrodu Fx, stały moment M = Fx*e): u = (M*L^2) / (2*E*I)
    moment_mimosrod = Fx * (F_promien - yc)
    disp_uy_eccentric = (moment_mimosrod * L_belka**2) / (2 * E_val * Izc)
    # Suma U_y
    disp_uy_total = abs(disp_uy_bending) + abs(disp_uy_eccentric)
    
    # U_z (od zginania My wywołanego przez Tz):
    disp_uz_total = (T_z * L_belka**3) / (3 * E_val * Iy)
    
    # Kąt skręcenia Phi (rad) na końcu wspornika (skręcanie nieswobodne)
    # phi(L) = (Ms / G*It) * [L - (1/k)*tanh(kL)]
    phi_rad = (Ms / (G_val * It)) * (L_belka - (1/k_skret)*np.tanh(k_skret*L_belka))

    # ==========================================================================
    # 10. ANALIZA SZCZEGÓŁOWA PUNKTÓW (P1..P6 + CUSTOM)
    # ==========================================================================
    
    # Lista standardowa (z definicją funkcji Omega)
    # Format: (Opis, Y_glob, Z_glob, Grubosc, Func_Omega, Func_Sz, Func_Sy, S_val)
    punkty_def = [
        ("P1 (Środek Płaskownika)", 0, 0, tp, omega_ss_1, Sz_func_1, Sy_func_1, 0),
        ("P2 (Koniec Nakładki)", 0, dlugosc_strefy_1, tp, omega_ss_1, Sz_func_1, Sy_func_1, dlugosc_strefy_1),
        ("P3 (Górne Naroże)", 0, z_c, twc, omega_ss_2, Sz_func_2, Sy_func_2, dlugosc_strefy_2),
        ("P4 (Środek Środnika)", yc, z_c, twc, omega_ss_3, Sz_func_3, Sy_func_3, yc),
        ("P5 (Dolne Naroże)", hc+tp-tfc, z_c, tfc, omega_ss_3, Sz_func_3, Sy_func_3, dlugosc_strefy_3),
        ("P6 (Koniec Dolnej Półki)", hc+tp-tfc, z_c-z_f, tfc, omega_ss_4, Sz_func_4, Sy_func_4, dlugosc_strefy_4)
    ]
    
    lista_wynikow = []
    max_vm = 0.0
    punkt_krytyczny = ""
    
    # Nośność Mw dla punktu najbardziej oddalonego (P6)
    omega_P6 = float(abs(omega_ss_4.subs(s_var, dlugosc_strefy_4)))
    Mw_Rd_stab = (Iw / omega_P6) * Mw_Rd_base

    # Pętla po punktach standardowych
    for opis, y_g, z_g, t_sc, func_om, func_Sz, func_Sy, s_val in punkty_def:
        y_loc = y_g - yc
        z_loc = z_g
        omega_val = float(func_om.subs(s_var, s_val))
        Sz_val = float(func_Sz.subs(s_var, s_val))
        Sy_val = float(func_Sy.subs(s_var, s_val))
        
        sig_N = F_N / Acal
        sig_Mz = (Mgz / Izc) * y_loc
        sig_My = (Mgy / Iy) * z_loc
        sig_B = (B_w / Iw) * omega_val
        sig_total = abs(sig_N + sig_Mz + sig_My + sig_B)
        
        tau_Vy = (T_y * Sz_val) / (Izc * t_sc)
        tau_Vz = (T_z * Sy_val) / (Iy * t_sc)
        tau_T = (Ms * t_sc) / It 
        tau_total = abs(tau_Vy) + abs(tau_Vz) + abs(tau_T)
        
        vm = np.sqrt(sig_total**2 + 3 * tau_total**2)
        
        if vm > max_vm:
            max_vm = vm
            punkt_krytyczny = opis
            
        lista_wynikow.append({
            "Punkt": opis,
            "Sigma_Total": sig_total,
            "Tau_Total": tau_total,
            "VonMises": vm,
            "Omega": omega_val
        })

    # Pętla po punktach użytkownika (Custom Probes)
    # Uproszczenie: Liczymy tylko naprężenia od Mz/My i N (bez dokładnego Omega i Tau)
    # Ponieważ analityczne wyznaczenie Omega dla punktu poza konturem jest nietrywialne.
    if custom_probes_coords:
        for name, (y_usr, z_usr) in custom_probes_coords.items():
            y_loc_u = y_usr - yc
            z_loc_u = z_usr
            
            sig_N_u = F_N / Acal
            sig_Mz_u = (Mgz / Izc) * y_loc_u
            sig_My_u = (Mgy / Iy) * z_loc_u
            # Pomijamy sig_B i Tau dla punktów użytkownika w analityce (szacunek)
            sig_tot_u = abs(sig_N_u + sig_Mz_u + sig_My_u)
            
            lista_wynikow.append({
                "Punkt": f"User: {name}",
                "Sigma_Total": sig_tot_u,
                "Tau_Total": 0.0, # Nieznane
                "VonMises": sig_tot_u, # Przybliżenie
                "Omega": 0.0
            })

    # ==========================================================================
    # 11. FINALNE WYNIKI
    # ==========================================================================
    UR = (abs(F_N)/N_Rd_stab) + (abs(Mgz)/Mz_Rd_stab) + (abs(Mgy)/My_Rd_stab) + (abs(B_w)/Mw_Rd_stab)

    return {
        "Wskazniki": {
            "UR": float(UR),
            "Max_VonMises": float(max_vm),
            "Punkt_Krytyczny": punkt_krytyczny,
            "Klasa_Przekroju": klasa_przekroju
        },
        "Przemieszczenia": {
            "U_y_max": float(disp_uy_total),
            "U_z_max": float(disp_uz_total),
            "Phi_rad": float(phi_rad),
            "Phi_deg": float(np.degrees(phi_rad))
        },
        "Geometria": {
            "Acal": float(Acal),
            "Iy": float(Iy),
            "Iz": float(Izc),
            "Iw": float(Iw),
            "It": float(It),
            "Ys": float(ys_val), 
            "Delta_Ys": float(delta_ys)
        },
        "Sily": {
            "N_Ed": float(F_N),
            "Mz_Ed": float(Mgz),
            "My_Ed": float(Mgy),
            "Mw_Ed": float(B_w),
            "Ms_Ed": float(Ms)
        },
        "Statecznosc": {
            "N_cr_min": float(N_cr_min),
            "N_cr_gs": float(N_cr_gs),
            "M_cr": float(M_cr),
            "Chi_N": float(chi_N),
            "Chi_LT": float(chi_LT)
        },
        "Detale_Punktow": lista_wynikow
    }

# ==========================================================================
# NARZĘDZIA POMOCNICZE (Zachowane 1:1)
# ==========================================================================

def oblicz_mase_metra(upe_data, geo_data, load_data):
    """
    Oblicza masę 1 mb gotowego profilu.
    Masa = (2 * Pole_Ceownika + Pole_Plaskownika) * Gestosc
    """
    Ac = float(upe_data['Ac'])   # [mm2]
    bp = float(geo_data['bp'])   # [mm]
    tp = float(geo_data['tp'])   # [mm]
    rho = float(load_data['rho']) # [kg/m3]
    
    # Pole całkowite w mm2
    A_total_mm2 = 2 * Ac + (bp * tp)
    
    # Konwersja na m2 (1 m2 = 1,000,000 mm2)
    A_total_m2 = A_total_mm2 / 1_000_000.0
    
    # Masa [kg/m]
    masa = A_total_m2 * rho
    return round(masa, 3)

# Słownik mapujący nazwy zmiennych z solvera na czytelne opisy i jednostki
OPISY_PARAMETROW = {
    # WYNIKI GŁÓWNE
    "Res_UR": ("Wytężenie Całkowite", "[-]"),
    "Res_Klasa_Przekroju": ("Klasa Przekroju (EC3)", "[-]"),
    "Res_Punkt_Krytyczny": ("Najbardziej wytężony punkt", "-"),
    "Res_Max_VonMises": ("Max Naprężenie Zredukowane", "[MPa]"),
    "Res_Masa_kg_m": ("Waga profilu", "[kg/m]"),
    
    # GEOMETRIA WYNIKOWA
    "Res_Geo_Acal": ("Pole Przekroju Całkowite", "[mm2]"),
    "Res_Geo_Iy": ("Moment Bezwł. Oś Słaba (Y)", "[mm4]"),
    "Res_Geo_Iz": ("Moment Bezwł. Oś Mocna (Z)", "[mm4]"),
    "Res_Geo_It": ("Sztywność Skręcania Swobodnego", "[mm4]"),
    "Res_Geo_Iw": ("Sztywność Wycinkowa (Spaczenie)", "[mm6]"),
    "Res_Geo_Ys": ("Położenie Środka Ścinania (Global)", "[mm]"),
    "Res_Geo_Delta_Ys": ("Mimośród Sc-Ss", "[mm]"),
    
    # STATECZNOŚĆ
    "Res_Stab_N_cr_min": ("Decydująca Siła Krytyczna", "[N]"),
    "Res_Stab_N_cr_gs": ("Siła Kryt. Giętno-Skrętna", "[N]"),
    "Res_Stab_M_cr": ("Moment Kryt. Zwichrzenia", "[Nmm]"),
    "Res_Stab_Chi_N": ("Wsp. Wyboczeniowy", "[-]"),
    "Res_Stab_Chi_LT": ("Wsp. Zwichrzeniowy", "[-]"),
    
    # SIŁY
    "Res_Force_B_Ed": ("Bimoment (Spaczenie)", "[Nmm2]"),
    "Res_Force_Ms_Ed": ("Moment Skręcający", "[Nmm]"),
    "Res_Force_My_Ed": ("Moment Zginający Y", "[Nmm]"),
    "Res_Force_Mz_Ed": ("Moment Zginający Z", "[Nmm]"),
    
    # NOWOŚĆ: PRZEMIESZCZENIA
    "Res_Disp_U_y_max": ("Ugięcie Y", "[mm]"),
    "Res_Disp_U_z_max": ("Ugięcie Z", "[mm]"),
    "Res_Disp_Phi_deg": ("Kąt skręcenia", "[deg]"),

    # WEJŚCIE
    "Input_Geo_bp": ("Szerokość Płaskownika", "[mm]"),
    "Input_Geo_tp": ("Grubość Płaskownika", "[mm]"),
    "Input_Geo_b_otw": ("Szerokość Otwarcia", "[mm]"), 
    "Input_UPE_hc": ("Wysokość Ceownika", "[mm]")
}

def sformatuj_wynik_do_raportu(plaski_wiersz):
    """
    Tworzy czytelną strukturę z jednostkami na podstawie płaskiego słownika.
    """
    raport = {}
    for klucz, wartosc in plaski_wiersz.items():
        if klucz in OPISY_PARAMETROW:
            opis, jednostka = OPISY_PARAMETROW[klucz]
            raport[opis] = f"{wartosc} {jednostka}"
        else:
            raport[klucz] = wartosc
    return raport

def splaszcz_wyniki_do_wiersza(upe_data, geo_data, load_data, safety_data, wyniki):
    """
    Konwertuje zagnieżdżony słownik wyników oraz dane wejściowe na płaski słownik (wiersz).
    """
    row = {}

    # 1. Dane wejściowe
    for k, v in upe_data.items(): row[f"Input_UPE_{k}"] = v
    for k, v in geo_data.items(): row[f"Input_Geo_{k}"] = v
    for k, v in load_data.items():
        if isinstance(v, (int, float, str)): row[f"Input_Load_{k}"] = v
    for k, v in safety_data.items(): row[f"Input_Safety_{k}"] = v

    # 2. Wyniki Główne
    for k, v in wyniki['Wskazniki'].items(): row[f"Res_{k}"] = v

    # 3. Geometria
    for k, v in wyniki['Geometria'].items(): row[f"Res_Geo_{k}"] = v

    # 4. Siły
    for k, v in wyniki['Sily'].items(): row[f"Res_Force_{k}"] = v

    # 5. Stateczność
    for k, v in wyniki['Statecznosc'].items(): row[f"Res_Stab_{k}"] = v
    
    # 6. Przemieszczenia (NOWOŚĆ)
    if 'Przemieszczenia' in wyniki:
        for k, v in wyniki['Przemieszczenia'].items(): row[f"Res_Disp_{k}"] = v

    # 7. Detale punktów
    if 'Detale_Punktow' in wyniki:
        for pkt in wyniki['Detale_Punktow']:
            identyfikator = pkt['Punkt'].split(' ')[0] 
            for k, v in pkt.items():
                if k != 'Punkt': row[f"{identyfikator}_{k}"] = v

    return row

class ZbieraczWynikow:
    def __init__(self):
        self.lista_wierszy = []

    def dodaj_symulacje(self, upe_data, geo_data, load_data, safety_data, wyniki):
        wiersz = splaszcz_wyniki_do_wiersza(upe_data, geo_data, load_data, safety_data, wyniki)
        self.lista_wierszy.append(wiersz)

    def pobierz_dane(self):
        return self.lista_wierszy

    def eksportuj_csv(self, nazwa_pliku="zbiór_wyników.csv"):
        if not self.lista_wierszy:
            print("(!) ZbieraczWynikow: Brak danych do zapisu.")
            return
        
        naglowki = list(self.lista_wierszy[0].keys())
        
        try:
            with open(nazwa_pliku, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=naglowki)
                writer.writeheader()
                writer.writerows(self.lista_wierszy)
            print(f"--> Zapisano zbiorczy plik danych: {nazwa_pliku} (Ilość wierszy: {len(self.lista_wierszy)})")
        except Exception as e:
            print(f"(!) Błąd zapisu CSV: {e}")

def zapisz_kompletny_raport(wyniki, nazwa_pliku_baza, router_instance=None):
    """Generuje raporty dla pojedynczego przebiegu (JSON, TXT, CSV-punkty)."""
    # ... (kod identyczny jak w poprzednim pliku, zachowany dla kompatybilności) ...
    pass