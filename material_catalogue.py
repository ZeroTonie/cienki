import math

# ==============================================================================
# 1. BAZA MATERIAŁOWA
# ==============================================================================
# Klucze:
# Re  - Granica plastyczności [MPa] (Dla Alu f0.2)
# E   - Moduł Younga [MPa]
# G   - Moduł Kirchhoffa [MPa]
# rho - Gęstość [kg/m3]
# Edef - Parametr odniesienia do obliczania epsilon (Epsilon = sqrt(Edef / Re))
#        Dla stali czarnej Edef = 235
#        Dla aluminium (wg EC9) Edef = 250
#        Dla nierdzewki (wg EC3-1-4) Edef = 235 * (E/210000)

def baza_materialow():
    """Zwraca słownik właściwości materiałowych."""
    db = {
        # --- STAL CZARNA (CARBON STEEL) ---
        "S235": {
            "Re": 235.0, "E": 210000.0, "G": 81000.0, "rho": 7850.0, "Edef": 235.0, "Typ": "Stal"
        },
        "S275": {
            "Re": 275.0, "E": 210000.0, "G": 81000.0, "rho": 7850.0, "Edef": 235.0, "Typ": "Stal"
        },
        "S355": {
            "Re": 355.0, "E": 210000.0, "G": 81000.0, "rho": 7850.0, "Edef": 235.0, "Typ": "Stal"
        },
        "S420": {
            "Re": 420.0, "E": 210000.0, "G": 81000.0, "rho": 7850.0, "Edef": 235.0, "Typ": "Stal"
        },
        "S460": {
            "Re": 460.0, "E": 210000.0, "G": 81000.0, "rho": 7850.0, "Edef": 235.0, "Typ": "Stal"
        },

        # --- STAL NIERDZEWNA (STAINLESS STEEL) ---
        # E moduł ok. 200 GPa.
        # Epsilon wg PN-EN 1993-1-4: eps = sqrt( (235/fy) * (E/210000) )
        "1.4301 (304)": {
            "Re": 210.0, "E": 200000.0, "G": 77000.0, "rho": 7900.0, "Edef": 235.0, "Typ": "Nierdzewna"
        },
        "1.4401 (316)": {
            "Re": 220.0, "E": 200000.0, "G": 77000.0, "rho": 7980.0, "Edef": 235.0, "Typ": "Nierdzewna"
        },
        "1.4016 (430)": {
            "Re": 240.0, "E": 200000.0, "G": 77000.0, "rho": 7700.0, "Edef": 235.0, "Typ": "Nierdzewna"
        },
        "1.4571 (316Ti)": {
            "Re": 220.0, "E": 200000.0, "G": 77000.0, "rho": 7980.0, "Edef": 235.0, "Typ": "Nierdzewna"
        },
        "1.4462 (Duplex)": {
            "Re": 460.0, "E": 200000.0, "G": 77000.0, "rho": 7800.0, "Edef": 235.0, "Typ": "Nierdzewna"
        },

        # --- ALUMINIUM ---
        # E moduł ok. 70 GPa. G ok. 26-27 GPa. Re to f0.2.
        # Epsilon wg PN-EN 1999-1-1 (Eurokod 9): eps = sqrt(250 / fo)
        "AW-6060 T6": {
            "Re": 160.0, "E": 70000.0,  "G": 26000.0, "rho": 2700.0, "Edef": 250.0, "Typ": "Aluminium"
        },
        "AW-6063 T6": {
            "Re": 170.0, "E": 70000.0,  "G": 26000.0, "rho": 2700.0, "Edef": 250.0, "Typ": "Aluminium"
        },
        "AW-6082 T6": {
            "Re": 260.0, "E": 70000.0,  "G": 26000.0, "rho": 2700.0, "Edef": 250.0, "Typ": "Aluminium"
        },
        "AW-5754 H111": {
            "Re": 80.0,  "E": 70000.0,  "G": 26000.0, "rho": 2680.0, "Edef": 250.0, "Typ": "Aluminium"
        },
        "AW-7075 T6": {
            "Re": 480.0, "E": 71000.0,  "G": 26500.0, "rho": 2800.0, "Edef": 250.0, "Typ": "Aluminium"
        }
    }
    return db

# ==============================================================================
# 2. DOSTĘPNE PŁASKOWNIKI (Wg Materiału)
# ==============================================================================
# Zwraca słownik: { 'grubosci': [...], 'szerokosci': [...] }

def dostepne_plaskowniki(typ_materialu):
    """
    Zwraca dostępne grubości (tp) i zakresy szerokości (bp) w zależności od materiału.
    typ_materialu: "Stal", "Nierdzewna", "Aluminium"
    """
    
    # Wspólne grubości bazowe
    grubosci_base = [5, 6, 8, 10, 12, 15, 16, 18, 20, 22, 25, 30, 35, 40, 50]
    
    # Szerokości - generujemy listę co 10mm lub co 5mm w zależności od precyzji
    # Tutaj definiujemy logiczny zakres, algorytm dobierający 'bp' będzie szukał w tym zakresie.
    
    if typ_materialu == "Stal":
        # Stal czarna - bardzo duży wybór, walcowane i palone z blach
        return {
            "tp": grubosci_base + [60, 70, 80],
            "bp_min": 20.0,
            "bp_max": 400.0,
            "bp_step": 5.0 # Dostępne co 5mm (lub palone na wymiar)
        }
    
    elif typ_materialu == "Nierdzewna":
        # Nierdzewka - pręty płaskie ciągnione (mniejsze) lub cięte z blach (większe)
        return {
            "tp": [3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50],
            "bp_min": 20.0,
            "bp_max": 400.0, # Powyżej 150mm zazwyczaj cięte z blachy
            "bp_step": 5.0
        }
        
    elif typ_materialu == "Aluminium":
        # Aluminium - płaskowniki wyciskane lub cięte z płyt (blach walcowanych)
        # Dla małych grubości standardowe wymiary, dla dużych cięcie z płyty
        return {
            "tp": [3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60],
            "bp_min": 20.0,
            "bp_max": 400.0, # Cięte z płyty, więc dowolny wymiar
            "bp_step": 5.0
        }
    
    else:
        # Fallback
        return {
            "tp": grubosci_base,
            "bp_min": 30.0,
            "bp_max": 300.0,
            "bp_step": 10.0
        }


# ==============================================================================
# 3. BAZA PROFILI (CEOWNIKI)
# ==============================================================================
# Zawiera:
# 1. Standardowe UPE (Stal czarna) - od UPE80
# 2. Małe ceowniki gorącowalcowane UPN (DIN 1026-1) - dla stali/nierdzewki - od 30mm
#    UWAGA: Dla UPN wartość 'tfc' została SKORYGOWANA. W tabelach podawana jest średnia
#    grubość stopki. My wpisujemy tutaj przybliżoną grubość NA KOŃCU stopki (tip),
#    aby bezpiecznie liczyć geometrię styku z płaskownikiem.
#    Przybliżenie: t_tip = t_mean - 0.08 * (b/2)
# 3. Ceowniki aluminiowe (U-profil) - wymiary standardowe wyciskane - od 30mm

def baza_upe():
    """
    Zwraca bazę wszystkich dostępnych ceowników (Stal UPE/UPN, Nierdzewka UPN, Aluminium U).
    UWAGA: Zachowano nazewnictwo kluczy (hc, bc, twc...), ale dla profili aluminiowych (o stałej grubości)
    twc == tfc.
    """
    db = {}

    # --- 1. STAL CZARNA - SERIA UPE (Norma DIN 1026-2) ---
    # Standardowe profile UPE, ekonomiczne, cienkościenne, stopki równoległe
    upe_data = {
        "UPE80": {
            "hc": 80.0, "bc": 50.0, "twc": 4.0, "tfc": 7.0, "rc": 10.0, "Ac": 7.90e2, 
            "Gc": 6.20, "Icy": 78.7e4, "Icz": 11.6e4, "Wcy": 19.7e3, "Wcz": 3.23e3, 
            "xc": 13.9, "xsc": 18.2, "Typ": "UPE"
        },
        "UPE100": {
            "hc": 100.0, "bc": 55.0, "twc": 4.5, "tfc": 7.5, "rc": 10.0, "Ac": 9.85e2, 
            "Gc": 7.73, "Icy": 158e4, "Icz": 18.9e4, "Wcy": 31.6e3, "Wcz": 4.75e3, 
            "xc": 15.6, "xsc": 20.9, "Typ": "UPE"
        },
        "UPE120": {
            "hc": 120.0, "bc": 60.0, "twc": 5.0, "tfc": 8.0, "rc": 12.0, "Ac": 12.1e2, 
            "Gc": 9.50, "Icy": 275e4, "Icz": 28.7e4, "Wcy": 45.8e3, "Wcz": 6.46e3, 
            "xc": 17.2, "xsc": 23.3, "Typ": "UPE"
        },
        "UPE140": {
            "hc": 140.0, "bc": 65.0, "twc": 5.0, "tfc": 9.0, "rc": 12.0, "Ac": 14.5e2, 
            "Gc": 11.4, "Icy": 436e4, "Icz": 41.1e4, "Wcy": 62.3e3, "Wcz": 8.44e3, 
            "xc": 18.9, "xsc": 25.9, "Typ": "UPE"
        },
        "UPE160": {
            "hc": 160.0, "bc": 70.0, "twc": 5.5, "tfc": 9.5, "rc": 12.0, "Ac": 17.0e2, 
            "Gc": 13.3, "Icy": 649e4, "Icz": 56.2e4, "Wcy": 81.1e3, "Wcz": 10.7e3, 
            "xc": 20.5, "xsc": 28.1, "Typ": "UPE"
        },
        "UPE180": {
            "hc": 180.0, "bc": 75.0, "twc": 5.5, "tfc": 10.5,"rc": 12.0, "Ac": 19.7e2, 
            "Gc": 15.5, "Icy": 919e4, "Icz": 73.9e4, "Wcy": 102e3, "Wcz": 13.2e3, 
            "xc": 22.0, "xsc": 30.1, "Typ": "UPE"
        },
        "UPE200": {
            "hc": 200.0, "bc": 80.0, "twc": 6.0, "tfc": 11.0,"rc": 13.0, "Ac": 22.8e2, 
            "Gc": 17.9, "Icy": 1260e4, "Icz": 94.9e4, "Wcy": 126e3, "Wcz": 16.0e3, 
            "xc": 23.8, "xsc": 32.4, "Typ": "UPE"
        },
        "UPE220": {
            "hc": 220.0, "bc": 85.0, "twc": 6.5, "tfc": 12.0,"rc": 13.0, "Ac": 26.6e2, 
            "Gc": 20.9, "Icy": 1690e4, "Icz": 121e4, "Wcy": 154e3, "Wcz": 19.4e3, 
            "xc": 25.7, "xsc": 34.2, "Typ": "UPE"
        },
        "UPE240": {
            "hc": 240.0, "bc": 90.0, "twc": 7.0, "tfc": 12.5,"rc": 15.0, "Ac": 30.6e2, 
            "Gc": 24.0, "Icy": 2230e4, "Icz": 152e4, "Wcy": 186e3, "Wcz": 22.9e3, 
            "xc": 27.2, "xsc": 36.8, "Typ": "UPE"
        },
        "UPE270": {
            "hc": 270.0, "bc": 95.0, "twc": 7.5, "tfc": 13.5,"rc": 15.0, "Ac": 35.4e2, 
            "Gc": 27.8, "Icy": 3230e4, "Icz": 191e4, "Wcy": 239e3, "Wcz": 27.1e3, 
            "xc": 28.7, "xsc": 39.4, "Typ": "UPE"
        },
        "UPE300": {
            "hc": 300.0, "bc": 100.0,"twc": 9.5, "tfc": 15.0,"rc": 15.0, "Ac": 41.5e2, 
            "Gc": 32.6, "Icy": 4490e4, "Icz": 236e4, "Wcy": 299e3, "Wcz": 31.6e3, 
            "xc": 30.1, "xsc": 42.3, "Typ": "UPE"
        },
        "UPE330": {
            "hc": 330.0, "bc": 105.0,"twc": 11.0,"tfc": 16.0,"rc": 18.0, "Ac": 48.7e2, 
            "Gc": 38.2, "Icy": 6110e4, "Icz": 291e4, "Wcy": 370e3, "Wcz": 37.1e3, 
            "xc": 31.8, "xsc": 45.3, "Typ": "UPE"
        },
        "UPE360": {
            "hc": 360.0, "bc": 110.0,"twc": 12.0,"tfc": 17.0,"rc": 18.0, "Ac": 55.4e2, 
            "Gc": 43.5, "Icy": 8030e4, "Icz": 353e4, "Wcy": 446e3, "Wcz": 42.6e3, 
            "xc": 33.3, "xsc": 48.2, "Typ": "UPE"
        },
        "UPE400": {
            "hc": 400.0, "bc": 115.0,"twc": 13.5,"tfc": 18.0,"rc": 18.0, "Ac": 64.2e2, 
            "Gc": 50.4, "Icy": 11100e4,"Icz": 427e4, "Wcy": 557e3, "Wcz": 49.0e3, 
            "xc": 34.6, "xsc": 52.1, "Typ": "UPE"
        }
    }
    db.update(upe_data)

    # --- 2. CEOWNIKI UPN (DIN 1026-1) ---
    # KOREKTA t_fc (Grubość stopki):
    # W tabelach UPN podaje się średnią grubość stopki (t_mean).
    # Ze względu na zbieżność (8%), grubość na końcu (tip) jest mniejsza.
    # W obliczeniach geometrycznych zakładamy t_fc = t_tip, aby bezpiecznie 
    # określić wymiary węzła z płaskownikiem.
    # Wartości Ac, Icy, Icz, Wcy pozostają normowe (średnie), co daje lekkie przewymiarowanie (bezpieczne).
    # t_tip ~= t_mean - 0.5 * b * 0.08
    
    upn_data = {
        "UPN30": {
            "hc": 30.0, "bc": 33.0, "twc": 5.0, "tfc": 5.5, "rc": 7.0, "Ac": 4.26e2, # t_mean 7.0 -> 5.5
            "Gc": 4.27, "Icy": 6.39e4, "Icz": 5.33e4, "Wcy": 4.26e3, "Wcz": 2.68e3, 
            "xc": 12.3, "xsc": 15.0, "Typ": "UPN" 
        },
        "UPN40": {
            "hc": 40.0, "bc": 35.0, "twc": 5.0, "tfc": 5.5, "rc": 7.0, "Ac": 5.21e2, # t_mean 7.0 -> 5.5
            "Gc": 4.87, "Icy": 14.1e4, "Icz": 6.68e4, "Wcy": 7.05e3, "Wcz": 3.08e3, 
            "xc": 13.3, "xsc": 17.5, "Typ": "UPN"
        },
        "UPN50": {
            "hc": 50.0, "bc": 38.0, "twc": 5.0, "tfc": 5.5, "rc": 7.0, "Ac": 7.12e2, # t_mean 7.0 -> 5.5
            "Gc": 5.59, "Icy": 26.4e4, "Icz": 9.12e4, "Wcy": 10.6e3, "Wcz": 3.75e3, 
            "xc": 13.7, "xsc": 18.5, "Typ": "UPN"
        },
        "UPN65": {
            "hc": 65.0, "bc": 42.0, "twc": 5.5, "tfc": 6.0, "rc": 7.5, "Ac": 9.03e2, # t_mean 7.5 -> 6.0
            "Gc": 7.09, "Icy": 57.5e4, "Icz": 14.1e4, "Wcy": 17.7e3, "Wcz": 5.07e3, 
            "xc": 14.2, "xsc": 20.1, "Typ": "UPN"
        }
    }
    db.update(upn_data)

    # --- 3. CEOWNIKI ALUMINIOWE (ALU U-PROFIL) ---
    # Wymiary wg standardów wyciskanych (PN-EN 755-9). 
    # Uwaga: Stała grubość ścianek (często) lub lekko pogrubione pasy.
    # Przyjęto profile o stałej grubości (box U) lub zbliżone.
    # xsc dla ceownika o stałej grubości: e = (3*b^2) / (h + 6*b) * (w przybliżeniu)
    # Wartości momentów przeliczone dla aluminium (geometrycznie mm4 są te same, masa inna)
    
    # Format nazwy: ALU_U[Wysokość]x[Szerokość]x[Grubość]
    
    alu_data = {
        "ALU_U30x30x3": {
            "hc": 30.0, "bc": 30.0, "twc": 3.0, "tfc": 3.0, "rc": 3.0, "Ac": 2.61e2,
            "Gc": 0.70, "Icy": 3.5e4, "Icz": 2.1e4, "Wcy": 2.3e3, "Wcz": 1.4e3,
            "xc": 9.0, "xsc": 12.0, "Typ": "ALU" # Masa dla rho=2700
        },
        "ALU_U40x40x4": {
            "hc": 40.0, "bc": 40.0, "twc": 4.0, "tfc": 4.0, "rc": 4.0, "Ac": 4.48e2,
            "Gc": 1.21, "Icy": 10.6e4, "Icz": 6.8e4, "Wcy": 5.3e3, "Wcz": 2.8e3,
            "xc": 11.5, "xsc": 16.0, "Typ": "ALU"
        },
        "ALU_U50x50x5": {
            "hc": 50.0, "bc": 50.0, "twc": 5.0, "tfc": 5.0, "rc": 5.0, "Ac": 7.0e2,
            "Gc": 1.89, "Icy": 26.0e4, "Icz": 17.0e4, "Wcy": 10.4e3, "Wcz": 5.2e3,
            "xc": 14.0, "xsc": 20.5, "Typ": "ALU"
        },
        "ALU_U60x40x4": { # Węższy
            "hc": 60.0, "bc": 40.0, "twc": 4.0, "tfc": 4.0, "rc": 4.0, "Ac": 5.4e2,
            "Gc": 1.45, "Icy": 30.0e4, "Icz": 8.5e4, "Wcy": 10.0e3, "Wcz": 3.0e3,
            "xc": 10.5, "xsc": 14.0, "Typ": "ALU"
        },
        "ALU_U80x40x4": {
            "hc": 80.0, "bc": 40.0, "twc": 4.0, "tfc": 4.0, "rc": 4.0, "Ac": 6.2e2,
            "Gc": 1.68, "Icy": 61.0e4, "Icz": 9.5e4, "Wcy": 15.2e3, "Wcz": 3.1e3,
            "xc": 9.0, "xsc": 11.5, "Typ": "ALU"
        },
        "ALU_U100x50x5": {
            "hc": 100.0, "bc": 50.0, "twc": 5.0, "tfc": 5.0, "rc": 5.0, "Ac": 9.5e2,
            "Gc": 2.56, "Icy": 145e4, "Icz": 22.0e4, "Wcy": 29.0e3, "Wcz": 6.2e3,
            "xc": 11.5, "xsc": 15.0, "Typ": "ALU"
        },
        "ALU_U120x60x6": {
            "hc": 120.0, "bc": 60.0, "twc": 6.0, "tfc": 6.0, "rc": 6.0, "Ac": 13.7e2,
            "Gc": 3.70, "Icy": 310e4, "Icz": 45.0e4, "Wcy": 51.6e3, "Wcz": 10.5e3,
            "xc": 14.0, "xsc": 19.0, "Typ": "ALU"
        },
        "ALU_U160x60x7": { # Typowy profil burtowy
            "hc": 160.0, "bc": 60.0, "twc": 7.0, "tfc": 7.0, "rc": 7.0, "Ac": 18.6e2,
            "Gc": 5.02, "Icy": 680e4, "Icz": 55.0e4, "Wcy": 85.0e3, "Wcz": 12.0e3,
            "xc": 13.0, "xsc": 17.5, "Typ": "ALU"
        }
    }
    db.update(alu_data)
    
    return db

def pobierz_ceownik(nazwa):
    """Pobiera dane ceownika o konkretnej nazwie"""
    nazwa = nazwa.upper()
    db = baza_upe()
    if nazwa in db:
        return db[nazwa]
    else:
        # print(f"BŁĄD: Nie znaleziono profilu '{nazwa}' w bazie")
        return None