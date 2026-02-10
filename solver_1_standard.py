import sys
import os
import json
import csv
import importlib

# --- POPRAWKA: Importujemy routing bezpośrednio, bo jest w tym samym folderze
import routing
import engine_solver
import config_solver
import material_catalogue

# ==============================================================================
# NARZĘDZIA POMOCNICZE (Eksport)
# ==============================================================================

def sortuj_klucze_wg_priorytetu(wszystkie_klucze):
    """
    Ustawia kolejność kolumn zgodnie z życzeniem użytkownika.
    """
    priorytety = [
        "Stop",             # <--- Materiał
        "Nazwa_Profilu",
        "Input_Geo_tp",
        "Input_Geo_bp",
        "Input_Geo_b_otw",
        "Res_Masa_kg_m",
        "Calc_Fy",
        "Calc_Fz",
        "Input_Load_Fx",
        "Res_UR",
        "Status_Wymogow",
        "Res_Max_VonMises",
        "Res_Stab_M_cr",
        "Calc_Nb_Rd", 
        # Momenty
        "Res_Force_Mz_Ed",
        "Res_Force_My_Ed",
        "Res_Force_Ms_Ed",
        "Res_Force_B_Ed", 
        # Charakterystyki geometryczne
        "Res_Geo_Iy", 
        "Res_Geo_Iz", 
        "Res_Geo_It", 
        "Res_Geo_Iw", 
        "Res_Geo_Ys", 
        "Res_Geo_Delta_Ys",
        # Etap na końcu
        "Raport_Etap"       # <--- Raport Etap
    ]
    
    posortowane = []
    for k in priorytety:
        if k in wszystkie_klucze:
            posortowane.append(k)
            
    for k in wszystkie_klucze:
        if k not in posortowane:
            posortowane.append(k)
            
    return posortowane

def formatuj_wartosc_config(v):
    if isinstance(v, dict):
        s = "<ul style='margin:0; padding-left:15px;'>"
        for sk, sv in v.items():
            s += f"<li><b>{sk}:</b> {sv}</li>"
        s += "</ul>"
        return s
    return str(v)

def zapisz_wszystkie_formaty(lista_wynikow, sciezka_baza):
    """
    Eksportuje zebrane dane do trzech formatów: CSV, JSON, HTML.
    sciezka_baza: pełna ścieżka do pliku bez rozszerzenia (z routingu).
    """
    if not lista_wynikow:
        print("(!) Brak danych do zapisu.")
        return

    wszystkie_klucze = list(lista_wynikow[0].keys())
    klucze_posortowane = sortuj_klucze_wg_priorytetu(wszystkie_klucze)

    # --- 1. ZAPIS CSV ---
    sciezka_csv = f"{sciezka_baza}.csv"
    try:
        with open(sciezka_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=klucze_posortowane)
            writer.writeheader()
            writer.writerows(lista_wynikow)
        print(f"[OK] Zapisano CSV: {sciezka_csv}")
    except Exception as e:
        print(f"[BŁĄD] Zapis CSV: {e}")

    # --- 2. ZAPIS JSON ---
    sciezka_json = f"{sciezka_baza}.json"
    try:
        def numpy_helper(obj):
            return obj.item() if hasattr(obj, 'item') else obj
            
        with open(sciezka_json, 'w', encoding='utf-8') as f:
            json.dump(lista_wynikow, f, default=numpy_helper, indent=4, ensure_ascii=False)
        print(f"[OK] Zapisano JSON: {sciezka_json}")
    except Exception as e:
        print(f"[BŁĄD] Zapis JSON: {e}")

    # --- 3. ZAPIS HTML ---
    sciezka_html = f"{sciezka_baza}.html"
    try:
        html = """
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 13px; margin: 20px; }
                h2, h3 { color: #333; margin-bottom: 5px; }
                .config-box { background: #f9f9f9; border: 1px solid #ddd; padding: 15px; margin-bottom: 25px; border-radius: 5px; }
                .config-table { width: auto; border: none; margin-bottom: 0; }
                .config-table td { border: none; padding: 3px 15px 3px 0; vertical-align: top; }
                .label { font-weight: bold; color: #555; }
                .results-table { border-collapse: collapse; width: 100%; box-shadow: 0 0 20px rgba(0,0,0,0.1); font-size: 12px; }
                .results-table th, .results-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                .results-table th { background-color: #009879; color: white; position: sticky; top: 0; z-index: 10; }
                .results-table tr:nth-child(even) { background-color: #f3f3f3; }
                .results-table tr:hover { background-color: #ddd; }
                .status-ok { color: green; font-weight: bold; }
                .status-fail { color: red; font-weight: bold; }
            </style>
        </head>
        <body>
            <h2>Raport Optymalizacji Słupa</h2>
            <div style="font-size:11px; color:#777; margin-bottom:15px;">Wygenerowano automatycznie</div>
            
            <div class="config-box">
                <h3>Parametry Konfiguracji (config_solver.py)</h3>
                <table class="config-table">
        """
        
        for attr_name in dir(config_solver):
            if attr_name.isupper():
                val = getattr(config_solver, attr_name)
                html += f"<tr><td class='label'>{attr_name}:</td><td>{formatuj_wartosc_config(val)}</td></tr>"
                
        html += """
                </table>
            </div>
            
            <h3>Wyniki Symulacji</h3>
            <table class="results-table">
                <thead><tr>
        """
        
        for k in klucze_posortowane:
            opis = k
            if hasattr(engine_solver, 'OPISY_PARAMETROW') and k in engine_solver.OPISY_PARAMETROW:
                nazwa, jedn = engine_solver.OPISY_PARAMETROW[k]
                opis = f"{nazwa}<br><span style='font-size:0.85em; opacity:0.8'>{jedn}</span>"
            html += f"<th>{opis}</th>"
        html += "</tr></thead><tbody>"
        
        for row in lista_wynikow:
            html += "<tr>"
            for k in klucze_posortowane:
                val = row.get(k, "")
                if isinstance(val, float):
                    val_str = f"{val:.4f}"
                else:
                    val_str = str(val)
                
                if k == "Status_Wymogow":
                    klasa_css = "status-ok" if val == "SPEŁNIA" else "status-fail"
                    html += f"<td class='{klasa_css}'>{val_str}</td>"
                else:
                    html += f"<td>{val_str}</td>"
            html += "</tr>"
            
        html += "</tbody></table></body></html>"
        
        with open(sciezka_html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"[OK] Zapisano HTML: {sciezka_html}")
    except Exception as e:
        print(f"[BŁĄD] Zapis HTML: {e}")


# ==============================================================================
# GŁÓWNA PĘTLA OPTYMALIZACYJNA
# ==============================================================================

def glowna_petla_optymalizacyjna(router_instance=None):
    print("=== START OPTYMALIZATORA KONSTRUKCJI SŁUPA ===")
    
    # --- POPRAWKA: Bezpieczniejsza obsługa routera
    # Jeśli wywołujemy skrypt ręcznie (nie przez GUI), używamy domyślnego routera.
    if router_instance is None:
        router_instance = routing.router

    # Wymuszenie przeładowania konfiguracji (dla GUI)
    importlib.reload(config_solver)

    zbieracz = engine_solver.ZbieraczWynikow()
    
    # 1. PĘTLA PO MATERIAŁACH
    for material_nazwa in config_solver.LISTA_MATERIALOW:
        print(f"\n>>> ANALIZA DLA MATERIAŁU: {material_nazwa}")
        
        mat_db = material_catalogue.baza_materialow()
        if material_nazwa not in mat_db:
            print(f"BŁĄD: Brak materiału {material_nazwa} w bazie!")
            continue
        mat_data = mat_db[material_nazwa]
        
        load_full = config_solver.LOAD_PARAMS.copy()
        load_full.update(mat_data)
        
        baza_prof = material_catalogue.baza_upe()
        typ_mat = mat_data.get("Typ", "Stal")
        
        dostepne_profile = []
        for k, v in baza_prof.items():
            if typ_mat == "Aluminium" and v["Typ"] == "ALU":
                dostepne_profile.append(k)
            elif typ_mat != "Aluminium" and v["Typ"] in ["UPE", "UPN"]:
                dostepne_profile.append(k)
        
        # Sortowanie rosnąco po wysokości hc
        dostepne_profile.sort(key=lambda k: baza_prof[k]['hc'])
        
        if not dostepne_profile:
            print(f"Brak profili typu {typ_mat} w bazie!")
            continue

        dostepne_plaskowniki = material_catalogue.dostepne_plaskowniki(typ_mat)
        lista_tp = sorted(dostepne_plaskowniki['tp']) # Posortowana ROSNĄCO
        
        # Zmienne do globalnego stopu
        masa_referencyjna_poprzedniego = None
        licznik_wzrostu_masy = 0
        indeks_optimum_poprzedni = None
        
        # --- PĘTLA PO CEOWNIKACH (ROSNĄCO) ---
        for i, prof_nazwa in enumerate(dostepne_profile):
            upe_data = baza_prof[prof_nazwa]
            hc = upe_data['hc']
            
            # --- KROK 1: INTELIGENTNE USTALENIE STARTU ---
            global_max_gp = config_solver.MAX_GRUBOSC_PLASKOWNIKA
            
            if indeks_optimum_poprzedni is not None:
                start_index = indeks_optimum_poprzedni + config_solver.START_SEARCH_OFFSET
                if start_index >= len(lista_tp): 
                    start_index = len(lista_tp) - 1
                start_tp_value = lista_tp[start_index]
                current_start_limit = min(start_tp_value, global_max_gp)
            else:
                current_start_limit = global_max_gp

            lista_tp_filtrowana = sorted([t for t in lista_tp if t <= current_start_limit], reverse=True)
            
            if not lista_tp_filtrowana:
                continue

            # --- KROK 2: SZUKANIE "DNA" ---
            tp_min = None
            for tp_test in lista_tp_filtrowana:
                b_otw = config_solver.MIN_SZEROKOSC_OTWARCIA
                bp = b_otw + 2 * hc
                geo_data = {"bp": bp, "tp": tp_test}
                
                res = engine_solver.analizuj_przekroj_pelna_dokladnosc(upe_data, geo_data, load_full, config_solver.SAFETY_PARAMS)
                
                if res['Wskazniki']['UR'] <= 1.0 and res['Wskazniki']['Klasa_Przekroju'] <= 3:
                    tp_min = tp_test
                else:
                    break
            
            if tp_min is None:
                indeks_optimum_poprzedni = None
                continue 
            
            try:
                indeks_tp_min_w_pelnej_liscie = lista_tp.index(tp_min)
                indeks_optimum_poprzedni = indeks_tp_min_w_pelnej_liscie
            except ValueError:
                indeks_optimum_poprzedni = None

            print(f"[ZNALEZIONO BAZĘ] {prof_nazwa}: Min grubość = {tp_min}mm")

            # --- KROK 3: GENEROWANIE WYNIKÓW ---
            start_idx = indeks_tp_min_w_pelnej_liscie
            end_idx = start_idx + config_solver.ILE_KROKOW_W_GORE + 1
            kandydaci_w_gore = lista_tp[start_idx : end_idx]
            grubosci_do_analizy = [t for t in kandydaci_w_gore if t <= config_solver.MAX_GRUBOSC_PLASKOWNIKA]

            waga_referencyjna = 0.0

            for i_grubosc, tp_current in enumerate(grubosci_do_analizy):
                # === A) WYNIK DLA MINIMALNEGO OTWARCIA ===
                b_otw_min = config_solver.MIN_SZEROKOSC_OTWARCIA
                bp_min = b_otw_min + 2 * hc
                geo_min = {"bp": bp_min, "tp": tp_current}
                
                res_min = engine_solver.analizuj_przekroj_pelna_dokladnosc(upe_data, geo_min, load_full, config_solver.SAFETY_PARAMS)
                waga_min = engine_solver.oblicz_mase_metra(upe_data, geo_min, load_full)
                
                if i_grubosc == 0:
                    waga_referencyjna = waga_min

                dane_min = engine_solver.splaszcz_wyniki_do_wiersza(upe_data, geo_min, load_full, config_solver.SAFETY_PARAMS, res_min)
                dane_min["Stop"] = material_nazwa
                dane_min["Nazwa_Profilu"] = prof_nazwa
                dane_min["Input_Geo_b_otw"] = b_otw_min
                dane_min["Res_Masa_kg_m"] = waga_min
                dane_min["Raport_Etap"] = f"1_MIN_GEO_{prof_nazwa}_tp{tp_current}"
                
                dane_min["Calc_Fy"] = load_full['Fx'] * load_full['w_Ty']
                dane_min["Calc_Fz"] = load_full['Fx'] * load_full['w_Tz']
                nb_rd = (dane_min.get("Res_Stab_Chi_N", 0) * dane_min.get("Res_Geo_Acal", 0) * load_full['Re']) / config_solver.SAFETY_PARAMS['gamma_M1']
                dane_min["Calc_Nb_Rd"] = nb_rd
                dane_min["Status_Wymogow"] = "SPEŁNIA"
                
                zbieracz.lista_wierszy.append(dane_min)
                
                # === B) SZUKANIE MAKSYMALNEGO OTWARCIA ===
                limit_otw = config_solver.LIMIT_POSZERZANIA * config_solver.MIN_SZEROKOSC_OTWARCIA
                current_b_otw = config_solver.MIN_SZEROKOSC_OTWARCIA + config_solver.KROK_POSZERZANIA
                
                max_b_otw_found = config_solver.MIN_SZEROKOSC_OTWARCIA
                ostatni_poprawny_wynik = res_min 
                
                while current_b_otw <= limit_otw:
                    bp_test = current_b_otw + 2 * hc
                    geo_test = {"bp": bp_test, "tp": tp_current}
                    
                    res_test = engine_solver.analizuj_przekroj_pelna_dokladnosc(upe_data, geo_test, load_full, config_solver.SAFETY_PARAMS)
                    
                    if res_test['Wskazniki']['UR'] <= 1.0 and res_test['Wskazniki']['Klasa_Przekroju'] <= 3:
                        max_b_otw_found = current_b_otw
                        ostatni_poprawny_wynik = res_test
                        current_b_otw += config_solver.KROK_POSZERZANIA
                    else:
                        break
                
                if max_b_otw_found > config_solver.MIN_SZEROKOSC_OTWARCIA:
                    waga_max = engine_solver.oblicz_mase_metra(upe_data, {"bp": max_b_otw_found + 2*hc, "tp": tp_current}, load_full)
                    dane_max = engine_solver.splaszcz_wyniki_do_wiersza(upe_data, {"bp": max_b_otw_found + 2*hc, "tp": tp_current}, load_full, config_solver.SAFETY_PARAMS, ostatni_poprawny_wynik)
                    
                    dane_max["Stop"] = material_nazwa
                    dane_max["Nazwa_Profilu"] = prof_nazwa
                    dane_max["Input_Geo_b_otw"] = max_b_otw_found
                    dane_max["Res_Masa_kg_m"] = waga_max
                    dane_max["Raport_Etap"] = f"2_MAX_GEO_{prof_nazwa}_tp{tp_current}"
                    
                    dane_max["Calc_Fy"] = load_full['Fx'] * load_full['w_Ty']
                    dane_max["Calc_Fz"] = load_full['Fx'] * load_full['w_Tz']
                    nb_rd = (dane_max.get("Res_Stab_Chi_N", 0) * dane_max.get("Res_Geo_Acal", 0) * load_full['Re']) / config_solver.SAFETY_PARAMS['gamma_M1']
                    dane_max["Calc_Nb_Rd"] = nb_rd
                    dane_max["Status_Wymogow"] = "SPEŁNIA"
                    
                    zbieracz.lista_wierszy.append(dane_max)
                    
                    if config_solver.POKAZUJ_KROKI_POSREDNIE:
                        print(f"   -> tp={tp_current}: Max Otwarcie {max_b_otw_found}mm")

            # --- SPRAWDZENIE GLOBALNEGO STOPU ---
            if masa_referencyjna_poprzedniego is not None:
                if waga_referencyjna > masa_referencyjna_poprzedniego:
                    licznik_wzrostu_masy += 1
                else:
                    licznik_wzrostu_masy = 0
            
            masa_referencyjna_poprzedniego = waga_referencyjna
            
            if licznik_wzrostu_masy >= config_solver.MAX_N_WZROSTOW_WAGI:
                print(f"[INFO] Przerwano symulację: Masa minimalna rośnie przez {config_solver.MAX_N_WZROSTOW_WAGI} kolejne profile.")
                break

    # --- KONIEC I EKSPORT ---
    
    if config_solver.NAZWA_BADANIA:
        nazwa_symulacji = config_solver.NAZWA_BADANIA
    else:
        param_str = f"Fx{int(config_solver.LOAD_PARAMS['Fx'])}_L{int(config_solver.LOAD_PARAMS['L'])}"
        nazwa_symulacji = f"Symulacja_{param_str}"
    
    # Wykorzystujemy nowy router do ścieżki (bezpośrednio nazwę, bez rozszerzenia)
    sciezka_baza = router_instance.get_path("ANALYTICAL", nazwa_symulacji)
    
    print(f"\n=== KONIEC OBLICZEŃ. Zapisywanie do: {sciezka_baza}.* ===")
    
    zapisz_wszystkie_formaty(zbieracz.lista_wierszy, sciezka_baza)
    
    # Zwracamy pełną ścieżkę do CSV
    return f"{sciezka_baza}.csv"

if __name__ == "__main__":
    glowna_petla_optymalizacyjna()