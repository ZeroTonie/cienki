import os
import sys
import datetime
import shutil

# ==============================================================================
#  ROUTING MANAGER v1.0
# ==============================================================================
# Centralny zarządca ścieżek i plików.
# Odpowiada za:
# 1. Tworzenie struktury folderów dla Projektu.
# 2. Wskazywanie ścieżek do zapisu (Analityka, Geometria, MES).
# 3. Lokalizowanie zewnętrznych narzędzi (CCX).
# ==============================================================================

class ProjectRouting:
    def __init__(self, base_output_dir="WYNIKI"):
        # --- ZMIANA DLA EXE ---
        if getattr(sys, 'frozen', False):
            # Jeśli program jest uruchomiony jako .exe, ścieżką główną jest folder z plikiem .exe
            self.root_dir = os.path.dirname(sys.executable)
        else:
            # Jeśli uruchamiamy z kodu w VS Code
            self.root_dir = os.path.dirname(os.path.abspath(__file__))
        # ----------------------

        self.base_output_dir = os.path.join(self.root_dir, base_output_dir)
        self.current_project_name = "Default_Project"
        self.project_path = ""
        
        # Definicje podfolderów
        self.folders = {
            "ANALYTICAL": "00_Analityka",
            "GEOMETRY": "01_Geometria",
            "MES_WORK": "02_MES_Roboczy",
            "FINAL": "03_Final",
            "TEMP": "99_Temp"
        }
        
        # Ścieżka do CalculiX
        self.ccx_path = os.path.join(self.root_dir, "solver_bin", "ccx.exe")

    def set_project(self, project_name=None):
        """Ustawia aktywny projekt i tworzy jego strukturę folderów."""
        if not project_name:
            # Generuj nazwę z datą, jeśli puste
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            project_name = f"Projekt_{ts}"
            
        self.current_project_name = project_name
        self.project_path = os.path.join(self.base_output_dir, project_name)
        
        # Tworzenie struktury
        if not os.path.exists(self.project_path):
            os.makedirs(self.project_path)
            
        for key, folder_name in self.folders.items():
            full_path = os.path.join(self.project_path, folder_name)
            if not os.path.exists(full_path):
                os.makedirs(full_path)
                
        print(f"[ROUTING] Aktywny projekt: {self.current_project_name}")
        print(f"[ROUTING] Ścieżka: {self.project_path}")
        return self.project_path

    def get_path(self, category, filename, subdir=None):
        """
        Zwraca pełną ścieżkę zapisu dla danego pliku.
        category: KLUCZ z self.folders (np. 'ANALYTICAL', 'MES_WORK')
        filename: nazwa pliku (np. 'wynik.csv')
        subdir: (opcjonalnie) podfolder wewnątrz kategorii (np. nazwa profilu)
        """
        if not self.project_path:
            self.set_project() # Fallback na domyślny
            
        if category not in self.folders:
            raise ValueError(f"[ROUTING] Nieznana kategoria: {category}")
            
        base_folder = os.path.join(self.project_path, self.folders[category])
        
        # Obsługa podfolderu (np. 02_MES_Roboczy/UPE200_iter1)
        if subdir:
            final_folder = os.path.join(base_folder, subdir)
            if not os.path.exists(final_folder):
                os.makedirs(final_folder)
            return os.path.join(final_folder, filename)
        
        return os.path.join(base_folder, filename)

    def get_ccx_path(self):
        """Zwraca ścieżkę do pliku wykonywalnego CalculiX."""
        if not os.path.exists(self.ccx_path):
            # Fallback - może jest w PATH systemowym?
            return "ccx"
        return self.ccx_path

    def get_solver_modules(self):
        """Skanuje folder ./solvers_opt/ i zwraca listę dostępnych skryptów optymalizacyjnych."""
        solvers_dir = os.path.join(self.root_dir, "solvers_opt")
        if not os.path.exists(solvers_dir):
            os.makedirs(solvers_dir)
            return []
            
        files = [f for f in os.listdir(solvers_dir) if f.endswith(".py") and f != "__init__.py"]
        return files

    def archive_final_result(self, source_file, new_name=None):
        """Kopiuje plik do folderu 03_Final."""
        if not os.path.exists(source_file):
            print(f"[ROUTING] Błąd archiwizacji: Nie znaleziono {source_file}")
            return
            
        filename = os.path.basename(source_file)
        if new_name:
            filename = new_name
            
        dest_path = self.get_path("FINAL", filename)
        shutil.copy2(source_file, dest_path)
        print(f"[ROUTING] Zarchiwizowano: {filename}")

# Singleton - jedna instancja dla całej aplikacji
router = ProjectRouting()