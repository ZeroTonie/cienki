import os

# ==============================================================================
#  CONFIG GEOMETRY v8.2 - PEŁNA DOKUMENTACJA
# ==============================================================================
# Ten plik służy jako "most" (bridge) przekazujący dane do generatora geometrii (engine_geometry.py).
# Zawiera wszystkie parametry sterujące wymiarami, jakością siatki oraz systemem pomiarowym.
# ==============================================================================

# --- 1. NAZEWNICTWO I ŚCIEŻKI ---
# Nazwa modelu będzie użyta w nazwach plików wyjściowych (.inp, .step, .msh).
MODEL_NAME = "Test_Box_Full_Integration"

# Katalog, w którym zostaną zapisane wszystkie wyniki.
# Jeśli folder nie istnieje, zostanie utworzony automatycznie.
OUTPUT_DIR = os.path.join("wyniki", "testy_geom")

# Całkowita długość belki/słupa w milimetrach [mm].
# Wpływa na czas generowania siatki (dłuższa belka = więcej elementów).
LENGTH = 1800.0


# --- 2. GEOMETRIA PROFILU (CEOWNIK) ---
# Parametry definiujące przekrój poprzeczny pojedynczego ceownika (np. UPE, UPN).
# Wartości powinny pochodzić z katalogu hutniczego.
PROFILE_DATA = {
    "Typ": "UPE",   # Nazwa typu (informacyjnie)
    "hc": 200.0,    # Wysokość całkowita ceownika [mm]
    "bc": 80.0,     # Szerokość półki (stopki) [mm]
    "twc": 6.0,     # Grubość środnika [mm]
    "tfc": 11.0,    # Grubość półki [mm]
    "rc": 13.0      # Promień zaokrąglenia wewnętrznego [mm].
                    # UWAGA: Ma duży wpływ na gęstość siatki. Generator zagęszcza siatkę na łukach.
}


# --- 3. GEOMETRIA PŁASKOWNIKA ---
# Parametry blachy łączącej ceowniki.
PLATE_DATA = {
    "tp": 10.0,     # Grubość płaskownika [mm]
    "bp": 300.0     # Szerokość płaskownika [mm].
                    # Ceowniki są zawsze zlicowane z krawędziami płaskownika.
                    # Jeśli bp jest szerokie, powstanie duża "pustka" wewnątrz skrzynki.
}


# --- 4. DANE GLOBALNE Z SOLVERA (PUNKTY REFERENCYJNE) ---
# Te punkty NIE wpływają na kształt bryły ani siatki.
# Służą wyłącznie do wygenerowania punktów w pliku CSV, aby w post-processingu
# wiedzieć, gdzie względem siatki znajduje się teoretyczny środek ciężkości/ścinania.
GLOBAL_DATA = {
    # Położenie w osi Y względem środka układu geometrycznego (0,0).
    # Układ: (0,0) to środek geometryczny płaskownika.
    # Wartości ujemne -> w stronę płaskownika. Wartości dodatnie -> w stronę otwarcia profilu.
    "Y_GC": -12.5,  # Współrzędna Y Środka Ciężkości (Gravity Center) całego układu
    "Y_SC": 25.0    # Współrzędna Y Środka Ścinania (Shear Center) całego układu
}


# --- 5. PARAMETRY SIATKI (MESH SIZE) ---
# Sterowanie wielkością elementów skończonych.
MESH_SIZE = {
    # Maksymalny rozmiar elementu na płaskich powierzchniach (tło).
    # Mniejsza wartość = dokładniejszy wynik, ale znacznie dłuższy czas obliczeń.
    "global": 5.0,  
    
    # Rozmiar elementu na łukach (zaokrągleniach ceownika).
    # Powinien być mniejszy niż promień 'rc' (np. rc/3 lub rc/4), aby łuk był gładki.
    "fillet": 3.0,
    
    # Rząd elementów skończonych (Order).
    # 1 = Elementy liniowe (4 węzły na czworościan). Szybkie, ale sztywne.
    # 2 = Elementy kwadratowe (10 węzłów na czworościan). Dokładne, zalecane do analiz nieliniowych.
    # UWAGA: Generator najpierw tworzy siatkę rzędu 1, a potem konwertuje na 2 dla stabilności.
    "order": 2
}


# --- 6. JAKOŚĆ SIATKI (MESH QUALITY & ALGORITHMS) ---
# Zaawansowane ustawienia silnika Gmsh.
MESH_QUALITY = {
    # Wybór algorytmu siatkowania 3D:
    # 1 = Delaunay (Domyślny, najbardziej stabilny, szybki).
    # 4 = Frontal (Tworzy ładniejsze elementy, ale wolniejszy i czasem zawodzi przy skomplikowanej geometrii).
    # 10 = HXT (Równoległy Delaunay, bardzo szybki dla ogromnych siatek).
    "algorithm_3d": 1,
    
    # Liczba kroków wygładzania siatki (Smoothing).
    # Przesuwa węzły, aby poprawić jakość elementów (zwiększyć min. kąt).
    # Zalecane: 2-5. Zbyt duża wartość może spowolnić generowanie.
    "smoothing": 2,
    
    # Optymalizator Netgen.
    # UWAGA KRYTYCZNA: Musi być False, jeśli używamy punktów wymuszonych (Embed/Slicing).
    # Włączenie tego przy 'active: True' w Slicing spowoduje błąd "Access Violation" (crash).
    "optimize_netgen": False 
}


# --- 7. SYSTEM METROLOGII I ZAGĘSZCZANIA (SLICING & SENSORS) ---
# To najważniejsza sekcja dla analizy wyników. Definiuje "Wirtualne Czujniki".
SLICING = {
    # Czy generować punkty pomiarowe? True = Tak.
    "active": True,
    
    # Odległość między kolejnymi przekrojami pomiarowymi wzdłuż belki [mm].
    # Np. 50.0 oznacza, że będziemy mieli czujniki w Z=0, 50, 100... itd.
    "step": 50.0,
    
    # "Jitter" (Luz) [mm].
    # Losowe przesunięcie całego przekroju w osi Z o małą wartość (np. +/- 1.5mm).
    # CEL: Zapobiega sytuacji, w której przekrój wypada idealnie na krawędzi elementów siatki tła,
    # co mogłoby prowadzić do powstania zdegenerowanych (płaskich) elementów.
    # Zalecane: 1.0 - 2.0 mm.
    "jitter": 1.5,
    
    # Czy zapisać plik CSV z mapą wszystkich wygenerowanych punktów (ID węzła -> Współrzędne)?
    # Niezbędne do późniejszego odczytu wyników w CalculiX.
    "export_map": True,
    
    # Lokalne zagęszczanie siatki wokół czujników (Refinement Fields).
    "refinement": {
        "active": True,      # Czy włączyć zagęszczanie?
        "radius": 20.0,      # Promień strefy zagęszczenia wokół punktu [mm].
        "size_min": 3.0,     # Rozmiar elementu w samym centrum czujnika [mm].
        "size_max": 15.0,    # Rozmiar elementu poza strefą promienia (płynne przejście).
        
        # Filtrowanie celów zagęszczenia.
        # Wpisz fragmenty nazw punktów, które mają być zagęszczone.
        # Dostępne nazwy w kodzie to m.in.: "Center", "Weld", "Web", "Corner", "Flange".
        # Tutaj zagęszczamy tylko spoiny (P2, P3), bo tam są największe gradienty naprężeń.
        "targets": ["P2_Weld", "P3_Weld"]
    }
}


# --- 8. ZASOBY SYSTEMOWE ---
# Liczba wątków procesora używanych przez Gmsh.
# Więcej wątków przyspiesza algorytm HXT (algo 10), ale dla Delaunay (algo 1) wpływ jest mniejszy.
SYSTEM_RESOURCES = {"num_threads": 20}