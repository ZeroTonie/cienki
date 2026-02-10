import os
from datetime import datetime

class ProjectRouter:
    def __init__(self):
        # Folder główny na wszystkie wyniki
        self.root_output_dir = "WYNIKI_PROJEKTU"
        # Domyślna nazwa projektu
        self.current_project = f"Projekt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def set_project(self, project_name):
        """Ustawia aktywny folder projektu (tworzony przy pierwszym zapisie)."""
        if project_name:
            # Usuwamy niedozwolone znaki z nazwy pliku
            safe_name = "".join([c for c in project_name if c.isalpha() or c.isdigit() or c in (' ', '_', '-')]).strip()
            self.current_project = safe_name

    def get_path(self, category, filename=None, create=True):
        """
        Zwraca pełną ścieżkę do pliku lub folderu w strukturze projektu.
        category: np. 'ANALYTICAL', 'FEM', 'LOGS'
        """
        # Struktura: WYNIKI_PROJEKTU / Nazwa_Projektu / Kategoria
        dir_path = os.path.join(self.root_output_dir, self.current_project, category)
        
        if create and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                print(f"Błąd tworzenia katalogu {dir_path}: {e}")

        if filename:
            return os.path.join(dir_path, filename)
        return dir_path

# Instancja singleton (używana przez inne moduły jako 'routing.router')
router = ProjectRouter()