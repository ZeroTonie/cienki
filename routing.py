import os
import json
import datetime
import shutil
import sys

class ProjectRouting:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ProjectRouting, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, base_output_dir="WYNIKI_FEM"):
        if hasattr(self, 'initialized'): return
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_output_dir = os.path.join(self.root_dir, base_output_dir)
        self.current_project_name = None
        self.project_path = None
        self.manifest_path = None
        
        self.folders = {
            "ANALYTICAL": "01_Analityka",
            "GEOMETRY": "02_Geometria",
            "FEM_WORK": "03_Obliczenia_Robocze",
            "FINAL": "04_Wyniki_Koncowe",
            "LOGS": "99_Logi"
        }
        self.initialized = True

    def set_project(self, project_name=None):
        if not project_name:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = f"Projekt_{ts}"
        self.current_project_name = project_name
        self.project_path = os.path.join(self.base_output_dir, project_name)
        
        if not os.path.exists(self.project_path):
            os.makedirs(self.project_path)
            
        for key, folder_name in self.folders.items():
            path = os.path.join(self.project_path, folder_name)
            if not os.path.exists(path): os.makedirs(path)
            
        # Init manifest
        self.manifest_path = os.path.join(self.project_path, "project_manifest.json")
        if not os.path.exists(self.manifest_path):
            self._update_manifest("INIT", {"created": str(datetime.datetime.now())})
            
        return self.project_path

    def get_path(self, category, filename, subdir=None):
        if not self.project_path: self.set_project()
        base = os.path.join(self.project_path, self.folders[category])
        if subdir:
            base = os.path.join(base, subdir)
            if not os.path.exists(base): os.makedirs(base)
        return os.path.join(base, filename)

    def register_file(self, category, filename, subdir=None, metadata=None):
        """Rejestruje plik w manifeście projektu."""
        path = self.get_path(category, filename, subdir)
        entry = {
            "path": path,
            "category": category,
            "subdir": subdir,
            "timestamp": str(datetime.datetime.now()),
            "meta": metadata or {}
        }
        self._update_manifest(filename, entry)
        return path

    def _update_manifest(self, key, data):
        """Zapisuje dane do pliku JSON."""
        current = {}
        if self.manifest_path and os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, 'r') as f: current = json.load(f)
            except: pass
        
        current[key] = data
        if self.manifest_path:
            try:
                with open(self.manifest_path, 'w') as f: json.dump(current, f, indent=4)
            except: pass

    def get_ccx_path(self):
        # 1. Szukaj w folderze bin projektu
        local_bin = os.path.join(self.root_dir, "bin", "ccx.exe")
        if os.path.exists(local_bin): return local_bin
        
        # 2. Szukaj w zmiennych systemowych
        sys_ccx = shutil.which("ccx")
        if sys_ccx: return sys_ccx
        
        # 3. Szukaj typowych nazw linuxowych
        sys_ccx_linux = shutil.which("ccx_2.17") 
        if sys_ccx_linux: return sys_ccx_linux

        raise FileNotFoundError("Nie znaleziono pliku wykonywalnego CalculiX (ccx).")

router = ProjectRouting()