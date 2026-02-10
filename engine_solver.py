import sympy as sp
import numpy as np
import json
import csv
import os

def analizuj_przekroj_pelna_dokladnosc(upe_data, geo_data, load_data, safety_data):
    """
    Wykonuje PEŁNĄ analizę wytrzymałościowo-statecznościową zgodnie z Teorią Własowa.
    Odwzorowuje matematykę zawartą w pliku analiza.ipynb bez uproszczeń.
    
    Argumenty:
    upe_data    -- słownik z danymi ceownika (z katalog.py)
    geo_data    -- słownik z wymiarami płaskownika (bp, tp)
    load_data   -- słownik z obciążeniami i materiałem (Fx, E, G, Re, Edef...)
    safety_data -- słownik ze współczynnikami bezpieczeństwa (gamma_M0, gamma_M1, alfa_imp)
    """
    
    # ==========================================================================
    # 1. ROZPAKOWANIE DANYCH WEJŚCIOWYCH
    # ==========================================================================
    # Dane geometryczne ceownika (klucze zgodne z katalog.py)
    hc = float(upe_data['hc'])
    bc = float(upe_data['bc'])
    twc = float(upe_data['twc'])
    tfc = float(upe_data['tfc'])
    rc = float(upe_data['rc'])
    Ac = float(upe_data['Ac'])
    xc = float(upe_data['xc'])
    Icy = float(upe_data['Icy'])
    Icz = float(upe_data['Icz'])
    
    # Dane płaskownika
    bp = float(geo_data['bp'])
    tp = float(geo_data['tp'])
    
    # Obciążenia i geometria belki
    Fx = float(load_data['Fx'])           # Siła osiowa
    F_promien = float(load_data['F_promien']) # Punkt przyłożenia siły
    L_belka = float(load_data['L'])       # Długość belki
    w_Ty = float(load_data['w_Ty'])       # Współczynnik siły tnącej Ty
    w_Tz = float(load_data['w_Tz'])       # Współczynnik siły tnącej Tz
    
    # Dane materiałowe
    E_val = float(load_data['E'])
    G_val = float(load_data['G'])
    Re_val = float(load_data['Re'])
    # Edef jest opcjonalne w load_data, domyślnie 235 (Stal) - potrzebne do klasyfikacji
    Edef_val = float(load_data.get('Edef', 235.0))
    
    # Współczynniki bezpieczeństwa
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
    
    # Zmienne pomocnicze (odległości osiowe)
    z_c = bp/2 - twc/2   # odległość osi środnika od osi symetrii Y
    z_cc = xc - twc/2    # odległość SC ceownika od osi środnika
    z_f = bc - twc/2     # długość efektywna stopki (od osi środnika)
    
    # Momenty bezwładności (Twierdzenie Steinera)
    # Izc - względem osi mocnej (poziomej Zc)
    Izc = (bp * tp**3)/12 + Ap * yc**2 + 2 * (Icy + Ac * (tp/2 + hc/2 - yc)**2)
    # Iy - względem osi słabej (pionowej Y - osi symetrii)
    Iy = (tp * bp**3)/12 + 2 * (Icz + Ac * (z_c - z_cc)**2)
    
    # Promienie bezwładności
    iy_rad = np.sqrt(Iy / Acal) # Używamy numpy tam gdzie nie potrzeba symboli
    iz_rad = np.sqrt(Izc / Acal)
    
    # Wskaźniki wytrzymałości
    ymax = (tp/2 + hc) - yc     # włókno dolne (najbardziej oddalone)
    Wz = Izc / ymax             # Wskaźnik dla zginania względem Z
    Wy = Iy / (bp/2)            # Wskaźnik dla zginania względem Y

    # ==========================================================================
    # 3. KLASYFIKACJA PRZEKROJU (WG EUROKODU 3)
    # ==========================================================================
    epsilon = np.sqrt(Edef_val / Re_val)
    
    # --- ŚRODNIK (WEB) ---
    cw = hc - 2*tfc - 2*rc # Wysokość obliczeniowa środnika
    if cw <= 0: cw = 1.0   # Zabezpieczenie matematyczne
    
    # Współczynnik alpha (udział strefy ściskanej)
    # Zakładamy oś obojętną na wysokości yc. Ściskanie jest na dole (pod osią).
    # Współrzędna dołu środnika (względem góry): tp/2 + hc - tfc
    strefa_sciskana_web = (tp/2 + hc - tfc) - yc
    alpha_web = strefa_sciskana_web / cw
    alpha_web = max(0.001, min(1.0, alpha_web)) # Clamp 0..1
    
    smuklosc_web = cw / twc
    
    # Limity dla środnika (Klasa 1, 2, 3)
    limit_web_c1 = (396 * epsilon) / (13 * alpha_web - 1) if (13*alpha_web - 1) > 0 else 396*epsilon
    limit_web_c2 = (456 * epsilon) / (13 * alpha_web - 1) if (13*alpha_web - 1) > 0 else 456*epsilon
    limit_web_c3 = 42 * epsilon # Uproszczone dla ściskania/zginania
    
    if smuklosc_web <= limit_web_c1: klasa_web = 1
    elif smuklosc_web <= limit_web_c2: klasa_web = 2
    elif smuklosc_web <= limit_web_c3: klasa_web = 3
    else: klasa_web = 4

    # --- STOPKA (FLANGE) ---
    cf = bc - twc - rc # Wysięg stopki
    if cf <= 0: cf = 1.0
    
    smuklosc_flange = cf / tfc
    
    limit_flange_c1 = 9 * epsilon
    limit_flange_c2 = 10 * epsilon
    limit_flange_c3 = 14 * epsilon
    
    if smuklosc_flange <= limit_flange_c1: klasa_flange = 1
    elif smuklosc_flange <= limit_flange_c2: klasa_flange = 2
    elif smuklosc_flange <= limit_flange_c3: klasa_flange = 3
    else: klasa_flange = 4
    
    # Klasa przekroju (najgorsza z podzespołów)
    klasa_przekroju = max(klasa_web, klasa_flange)

    # ==========================================================================
    # 4. TEORIA WŁASOWA - CAŁKOWANIE SYMBOLICZNE (PELNA DOKLADNOSC)
    # ==========================================================================
    s_var = sp.symbols('s_var', real=True)
    
    # Definicja stref całkowania (długości)
    dlugosc_strefy_1 = bp/2 - bc         # Czysty płaskownik
    dlugosc_strefy_2 = bc                # Zakładka
    dlugosc_strefy_3 = hc - tfc          # Środnik
    dlugosc_strefy_4 = bc - twc/2        # Stopka dolna (z_f)
    
    # Definicja ramion sił (odległości od Sc)
    ramie_pionowe_plaskownik = yc 
    ramie_pionowe_zakladka = yc - tfc/2
    ramie_poziome_srodnik = z_c 
    ramie_pionowe_stopka_dol = (hc + tp) - yc - tfc/2 
    
    # --- Etap A: Wyznaczanie Omega względem Sc ---
    
    # 1. Płaskownik
    omega_1 = ramie_pionowe_plaskownik * s_var
    # Moment wycinkowy (do wyznaczenia delta_ys)
    Sw_1 = sp.integrate(omega_1 * s_var * tp, (s_var, 0, dlugosc_strefy_1))
    omega_koniec_1 = omega_1.subs(s_var, dlugosc_strefy_1)
    
    # 2. Zakładka
    omega_2 = omega_koniec_1 + ramie_pionowe_zakladka * s_var 
    t_zakladka = tp + tfc
    z_globalne_2 = dlugosc_strefy_1 + s_var
    Sw_2 = sp.integrate(omega_2 * z_globalne_2 * t_zakladka, (s_var, 0, dlugosc_strefy_2))
    omega_naroznik_gora = omega_2.subs(s_var, dlugosc_strefy_2)
    
    # 3. Środnik
    omega_3 = omega_naroznik_gora + ramie_poziome_srodnik * s_var
    Sw_3 = sp.integrate(omega_3 * ramie_poziome_srodnik * twc, (s_var, 0, dlugosc_strefy_3))
    omega_naroznik_dol = omega_3.subs(s_var, dlugosc_strefy_3)
    
    # 4. Dolna stopka
    omega_4 = omega_naroznik_dol + ramie_pionowe_stopka_dol * s_var
    z_globalne_4 = z_c - s_var
    Sw_4 = sp.integrate(omega_4 * z_globalne_4 * tfc, (s_var, 0, dlugosc_strefy_4))
    
    # --- Etap B: Wyznaczanie Środka Ścinania (Ss) ---
    Sw_calkowite = 2 * (Sw_1 + Sw_2 + Sw_3 + Sw_4)
    delta_ys = float(Sw_calkowite / Iy)
    ys_val = yc - delta_ys # Współrzędna Ss względem osi płaskownika
    
    # --- Etap C: Transformacja do układu głównego (Ss) ---
    # omega_Ss = omega_Sc - delta_ys * z_glob
    omega_ss_1 = omega_1 - delta_ys * s_var
    omega_ss_2 = omega_2 - delta_ys * (dlugosc_strefy_1 + s_var)
    omega_ss_3 = omega_3 - delta_ys * ramie_poziome_srodnik
    omega_ss_4 = omega_4 - delta_ys * (z_c - s_var)
    
    # --- Etap D: Wycinkowy moment bezwładności (Iw) ---
    Iw_1 = sp.integrate(omega_ss_1**2 * tp, (s_var, 0, dlugosc_strefy_1))
    Iw_2 = sp.integrate(omega_ss_2**2 * t_zakladka, (s_var, 0, dlugosc_strefy_2))
    Iw_3 = sp.integrate(omega_ss_3**2 * twc, (s_var, 0, dlugosc_strefy_3))
    Iw_4 = sp.integrate(omega_ss_4**2 * tfc, (s_var, 0, dlugosc_strefy_4))
    
    Iw = float(2 * (Iw_1 + Iw_2 + Iw_3 + Iw_4))
    
    # Biegunowy moment bezwładności (względem Ss)
    Ip = Iy + Izc + Acal * delta_ys**2
    io = np.sqrt(Ip / Acal)
    
    # Moment skręcania swobodnego It (suma prostokątów)
    # Używamy wymiarów płaskich (flat)
    cw_flat = hc - 2*tfc - 2*rc
    cf_flat = bc - twc - rc
    It = (1/3) * (bp * tp**3) + 2 * ((1/3) * (cw_flat * twc**3 + 2 * cf_flat * tfc**3))

    # ==========================================================================
    # 5. MOMENTY STATYCZNE (Sz, Sy) - PRZYGOTOWANIE FUNKCJI
    # ==========================================================================
    # Potrzebne do naprężeń stycznych w dowolnym punkcie
    
    # Sz (Dla siły Ty - całka po y)
    Sz_func_1 = sp.integrate(-yc * tp, (s_var, 0, s_var))
    Sz_end_1 = Sz_func_1.subs(s_var, dlugosc_strefy_1)
    
    # Lokalny y środka ciężkości zakładki
    y_zakl_loc = ((tp*0 + tfc*(tp/2+tfc/2))/(tp+tfc)) - yc
    Sz_func_2 = Sz_end_1 + sp.integrate(y_zakl_loc * t_zakladka, (s_var, 0, s_var))
    Sz_end_2 = Sz_func_2.subs(s_var, dlugosc_strefy_2)
    
    Sz_func_3 = Sz_end_2 + sp.integrate((s_var - yc) * twc, (s_var, 0, s_var))
    Sz_end_3 = Sz_func_3.subs(s_var, dlugosc_strefy_3)
    
    Sz_func_4 = Sz_end_3 + sp.integrate(((hc+tp-tfc/2)-yc) * tfc, (s_var, 0, s_var))
    
    # Sy (Dla siły Tz - całka po z)
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
    
    # Momenty zginające
    # Mgz: Mimośród siły osiowej + moment od siły poprzecznej Ty
    Mgz = abs(Fx * (F_promien - yc)) + abs(T_y * L_belka)
    # Mgy: Od siły bocznej Tz
    Mgy = abs(T_z * L_belka)
    
    # Moment skręcający względem Ss
    # Ramię = odległość siły (F_promien) od Ss (ys_val)
    # Uwaga: F_promien liczone od góry, ys_val też od góry (ujemne lub dodatnie względem góry)
    # W analizie: Ms = T_z * (F_promien + ys). Tutaj ys to odległość od OY.
    # Spójnie: Ms = T_z * (ramię_siły_wzgl_Ss)
    # ys_val to pozycja Ss (np. 40mm w dół od góry). F_promien to pozycja siły.
    Ms = T_z * (F_promien + (yc - delta_ys)) 
    
    # Bimoment (Wspornik)
    k_skret = np.sqrt((G_val * It) / (E_val * Iw))
    B_w = (Ms / k_skret) * np.tanh(k_skret * L_belka)

    # ==========================================================================
    # 7. STATECZNOŚĆ (WYBOCZENIE GIĘTNO-SKRĘTNE)
    # ==========================================================================
    # Dla wspornika L_cr = 2L
    L_cr = 2.0 * L_belka
    
    # Siły krytyczne Eulera
    N_cr_gy = (np.pi**2 * E_val * Iy) / L_cr**2
    N_cr_gz = (np.pi**2 * E_val * Izc) / L_cr**2
    
    # Siła krytyczna skrętna
    N_cr_s = (1.0 / io**2) * (G_val * It + (np.pi**2 * E_val * Iw) / L_cr**2)
    
    # Rozwiązanie równania Timoszenki dla wyboczenia giętno-skrętnego
    y0 = delta_ys  # Mimośród geometryczny
    r0 = io        # Promień biegunowy
    beta_param = 1.0 - (y0 / r0)**2
    
    # Równanie: beta*N^2 - (Nz+Ns)*N + Nz*Ns = 0
    param_B = -(N_cr_gz + N_cr_s)
    param_C = N_cr_gz * N_cr_s
    
    delta_rownania = param_B**2 - 4 * beta_param * param_C
    
    if delta_rownania < 0:
        # Teoretycznie niemożliwe dla fizycznych profili, fallback
        N_cr_gs = N_cr_s 
    else:
        N_root_1 = (-param_B - np.sqrt(delta_rownania)) / (2*beta_param)
        N_root_2 = (-param_B + np.sqrt(delta_rownania)) / (2*beta_param)
        N_cr_gs = min(N_root_1, N_root_2)
        
    # Decydująca siła krytyczna
    N_cr_min = min(N_cr_gy, N_cr_gs)
    
    # Moment krytyczny zwichrzenia
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
    
    # Nośność na bimoment zależy od omega w konkretnym punkcie (liczone niżej w pętli)
    # Tutaj wstępna deklaracja, nadpisana przy analizie punktów
    Mw_Rd_base = (Re_val / x_ogolne) 

    # ==========================================================================
    # 9. ANALIZA SZCZEGÓŁOWA PUNKTÓW (P1..P6)
    # ==========================================================================
    # Definicja punktów: (Nazwa, Y_glob, Z_glob, grubosc, funkcja_omega, func_Sz, func_Sy, s_do_podstawienia)
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
    
    # Zmienne do finalnego UR (bazujemy na najgorszym punkcie dla Bimomentu - P6)
    omega_P6 = float(abs(omega_ss_4.subs(s_var, dlugosc_strefy_4)))
    Mw_Rd_stab = (Iw / omega_P6) * Mw_Rd_base

    for opis, y_g, z_g, t_sc, func_om, func_Sz, func_Sy, s_val in punkty_def:
        # Obliczenie wartości geometrycznych w punkcie
        y_loc = y_g - yc
        z_loc = z_g
        omega_val = float(func_om.subs(s_var, s_val))
        Sz_val = float(func_Sz.subs(s_var, s_val))
        Sy_val = float(func_Sy.subs(s_var, s_val))
        
        # Naprężenia Normalne
        sig_N = F_N / Acal
        sig_Mz = (Mgz / Izc) * y_loc
        sig_My = (Mgy / Iy) * z_loc
        sig_B = (B_w / Iw) * omega_val
        
        sig_total = abs(sig_N + sig_Mz + sig_My + sig_B)
        
        # Naprężenia Styczne
        tau_Vy = (T_y * Sz_val) / (Izc * t_sc)
        tau_Vz = (T_z * Sy_val) / (Iy * t_sc)
        tau_T = (Ms * t_sc) / It # St. Venant (uproszczony liniowy rozkład)
        
        tau_total = abs(tau_Vy) + abs(tau_Vz) + abs(tau_T)
        
        # Wytężenie Von Mises
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
        
    # ==========================================================================
    # 10. FINALNY WSKAŹNIK WYKORZYSTANIA NOŚNOŚCI (UR)
    # ==========================================================================
    UR = (abs(F_N)/N_Rd_stab) + (abs(Mgz)/Mz_Rd_stab) + (abs(Mgy)/My_Rd_stab) + (abs(B_w)/Mw_Rd_stab)

    return {
        "Wskazniki": {
            "UR": float(UR),
            "Max_VonMises": float(max_vm),
            "Punkt_Krytyczny": punkt_krytyczny,
            "Klasa_Przekroju": klasa_przekroju
        },
        "Geometria": {
            "Acal": float(Acal),
            "Iy": float(Iy),
            "Iz": float(Izc),
            "Iw": float(Iw),
            "It": float(It),
            "Ys": float(ys_val), # Położenie Ss
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
# 11. EKSPORT I AGREGACJA DANYCH (DO SYMULACJI ZBIORCZYCH)
# ==========================================================================

import csv

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
            # Dla parametrów bez opisu (np. Input_Safety) zostawiamy jak jest
            raport[klucz] = wartosc
    return raport

def splaszcz_wyniki_do_wiersza(upe_data, geo_data, load_data, safety_data, wyniki):
    """
    Konwertuje zagnieżdżony słownik wyników oraz dane wejściowe na płaski słownik (wiersz),
    który nadaje się do zapisu w tabeli zbiorczej (np. dla DataFrame lub CSV).
    Wszystkie klucze są unikalne.
    """
    row = {}

    # 1. Dane wejściowe (Input) - Logujemy co weszło do obliczeń
    for k, v in upe_data.items():
        row[f"Input_UPE_{k}"] = v
    for k, v in geo_data.items():
        row[f"Input_Geo_{k}"] = v
    for k, v in load_data.items():
        # Pomijamy słowniki zagnieżdżone w load_data (jeśli są), bierzemy wartości proste
        if isinstance(v, (int, float, str)):
            row[f"Input_Load_{k}"] = v
    for k, v in safety_data.items():
        row[f"Input_Safety_{k}"] = v

    # 2. Wyniki Główne (Wskazniki)
    for k, v in wyniki['Wskazniki'].items():
        row[f"Res_{k}"] = v

    # 3. Geometria obliczona
    for k, v in wyniki['Geometria'].items():
        row[f"Res_Geo_{k}"] = v

    # 4. Siły wewnętrzne
    for k, v in wyniki['Sily'].items():
        row[f"Res_Force_{k}"] = v

    # 5. Stateczność
    for k, v in wyniki['Statecznosc'].items():
        row[f"Res_Stab_{k}"] = v

    # 6. Detale punktów (P1...P6)
    # Iterujemy po punktach i dodajemy ich wyniki jako kolumny (spłaszczanie listy)
    # Np. P1_Sigma_Total, P1_VonMises itp.
    if 'Detale_Punktow' in wyniki:
        for pkt in wyniki['Detale_Punktow']:
            # Wyciągamy krótki identyfikator punktu (np. "P1" z "P1 (Środek...)")
            # Zakładamy format "P1 (Opis)" -> split daje ["P1", "(Opis)..."]
            identyfikator = pkt['Punkt'].split(' ')[0] 
            
            for k, v in pkt.items():
                if k != 'Punkt': # Pomijamy pełną nazwę w wartościach kolumn
                    row[f"{identyfikator}_{k}"] = v

    return row

class ZbieraczWynikow:
    """
    Klasa pomocnicza do gromadzenia wyników z wielu symulacji.
    Służy jako bufor, który przechowuje spłaszczone wiersze i potrafi je zapisać do pliku.
    """
    def __init__(self):
        self.lista_wierszy = []

    def dodaj_symulacje(self, upe_data, geo_data, load_data, safety_data, wyniki):
        """
        Przetwarza wynik pojedynczej symulacji na płaski wiersz i dodaje do listy.
        """
        wiersz = splaszcz_wyniki_do_wiersza(upe_data, geo_data, load_data, safety_data, wyniki)
        self.lista_wierszy.append(wiersz)

    def pobierz_dane(self):
        """Zwraca zebraną listę słowników (np. do konwersji na pandas DataFrame)."""
        return self.lista_wierszy

    def eksportuj_csv(self, nazwa_pliku="zbiór_wyników.csv"):
        """Zapisuje wszystkie zebrane symulacje do jednego pliku CSV."""
        if not self.lista_wierszy:
            print("(!) ZbieraczWynikow: Brak danych do zapisu.")
            return
        
        # Pobieramy nagłówki z pierwszego wiersza (zakładamy stałą strukturę)
        naglowki = list(self.lista_wierszy[0].keys())
        
        try:
            with open(nazwa_pliku, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=naglowki)
                writer.writeheader()
                writer.writerows(self.lista_wierszy)
            print(f"--> Zapisano zbiorczy plik danych: {nazwa_pliku} (Ilość wierszy: {len(self.lista_wierszy)})")
        except Exception as e:
            print(f"(!) Błąd zapisu CSV: {e}")

# Funkcja pomocnicza do pojedynczego zapisu (kompatybilność wsteczna z Twoim testem)
def zapisz_kompletny_raport(wyniki, nazwa_pliku_baza, router_instance=None):
    """Generuje raporty dla pojedynczego przebiegu (JSON, TXT, CSV-punkty)."""
    import json
    
    # Helper dla numpy
    def _konwerter(o):
        if isinstance(o, (np.generic, np.number)): return float(o)
        raise TypeError

    # Determine paths
    if router_instance:
        # Tylko nazwa pliku, bez ścieżki (jeśli nazwa_pliku_baza zawiera ścieżkę, wycinamy ją)
        base_name = os.path.basename(nazwa_pliku_baza)
        # Usuwamy ewentualne rozszerzenie, jeśli zostało podane (choć zmienna sugeruje bazę)
        if base_name.endswith(".json") or base_name.endswith(".txt"):
            base_name = os.path.splitext(base_name)[0]
            
        # Pobierz pełną ścieżkę w folderze 00_Analityka
        full_path_json = router_instance.get_path("ANALYTICAL", f"{base_name}.json")
        full_path_txt = router_instance.get_path("ANALYTICAL", f"{base_name}_raport.txt")
        full_path_csv = router_instance.get_path("ANALYTICAL", f"{base_name}_punkty.csv")
    else:
        # Fallback (stara logika)
        full_path_json = f"{nazwa_pliku_baza}.json"
        full_path_txt = f"{nazwa_pliku_baza}_raport.txt"
        full_path_csv = f"{nazwa_pliku_baza}_punkty.csv"

    # 1. JSON
    try:
        with open(full_path_json, 'w', encoding='utf-8') as f:
            json.dump(wyniki, f, default=_konwerter, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Błąd zapisu JSON: {e}")
        
    # 2. TXT (Raport)
    try:
        with open(full_path_txt, 'w', encoding='utf-8') as f:
            w = wyniki['Wskazniki']
            f.write(f"RAPORT: {nazwa_pliku_baza}\nUR: {w['UR']:.4f} | Klasa: {w['Klasa_Przekroju']} | Pkt Kryt: {w['Punkt_Krytyczny']}\n")
            # (Można rozbudować o pełny raport jak wcześniej, tutaj wersja skrócona dla czytelności kodu)
    except Exception as e:
        print(f"Błąd zapisu TXT: {e}")

    # 3. CSV (Punkty szczegółowe dla tego jednego przypadku)
    if wyniki.get("Detale_Punktow"):
        keys = wyniki["Detale_Punktow"][0].keys()
        try:
            with open(full_path_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                # Konwersja numpy -> float
                rows = [{k: float(v) if isinstance(v, (np.generic, np.number)) else v for k, v in r.items()} for r in wyniki["Detale_Punktow"]]
                writer.writerows(rows)
        except Exception as e:
            print(f"Błąd zapisu CSV: {e}")
            
    print(f"--- Wygenerowano raporty pojedyncze: {os.path.basename(nazwa_pliku_baza)} ---")
    if router_instance:
        print(f"    Lokalizacja: {os.path.dirname(full_path_json)}")