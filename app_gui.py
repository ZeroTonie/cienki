# -*- coding: utf-8 -*-
##### SEKCJA 1: IMPORTY I KONFIGURACJA GLOBALNA #####
import sys
import os
import glob
import pandas as pd
import numpy as np
import importlib
import traceback
import subprocess
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTabWidget, QLabel, QPushButton, 
                             QFileDialog, QTableView, QHeaderView, QLineEdit, 
                             QFormLayout, QGroupBox, QCheckBox, QSplitter, 
                             QProgressBar, QTextBrowser, QListWidget, QListWidgetItem,
                             QScrollArea, QMessageBox, QFrame, QComboBox, QColorDialog,
                             QSizePolicy, QRadioButton, QButtonGroup, QStackedWidget,
                             QMenu, QDoubleSpinBox, QSpinBox, 
                             # --- DODANE NOWE ELEMENTY ---
                             QTableWidget, QTableWidgetItem, QAbstractItemView)
from PyQt6.QtCore import Qt, QAbstractTableModel, QUrl, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QDesktopServices, QAction, QFont, QBrush, QIcon
try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
    HAS_PYVISTA = True
except ImportError:
    HAS_PYVISTA = False
    print("Brak biblioteki pyvista/pyvistaqt. Zainstaluj: pip install pyvista pyvistaqt meshio")

# --- MODUŁY WŁASNE ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import routing
from routing import router
import material_catalogue
import engine_solver
import config_solver
import fem_optimizer

# --- GLOBALNE STAŁE GUI ---
HEADER_MAP = {
    "Res_Masa_kg_m": ("Waga", "kg/m"),
    "Input_Geo_tp": ("Grubość Płask.", "mm"),
    "Input_Geo_bp": ("Szer. Płask.", "mm"),
    "Input_Geo_b_otw": ("Otwarcie", "mm"),
    "Res_UR": ("Wytężenie UR", "-"),
    "Res_Stab_M_cr": ("Mcr", "Nmm"),
    "Res_Max_VonMises": ("Sigma Red.", "MPa"),
    "Input_Load_Fx": ("Siła Fx", "N"),
    "Calc_Nb_Rd": ("Nośność Nb", "N"),
    "Nazwa_Profilu": ("Profil", "-"),
    "Stop": ("Materiał", "-"),
    "Raport_Etap": ("Etap", "-"),
    "PRZEKAZ": ("Przekaż", "FEM"),
    "WYKLUCZ": ("Wyklucz", "Ukryj")
}

OPTIMIZER_REGISTRY = {
    "Standard V3.0 (Waga -> Pareto)": {
        "module_name": "solver_1_standard",
        "params": {
            "START_SEARCH_OFFSET": {"label": "Offset startu:", "default": "2", "type": "int"},
            "MAX_N_WZROSTOW_WAGI": {"label": "Max wzrostów (Stop):", "default": "2", "type": "int"},
            "ILE_KROKOW_W_GORE":   {"label": "Raport (kroki w górę):", "default": "2", "type": "int"},
            "KROK_POSZERZANIA":    {"label": "Krok poszerzania:", "default": "10.0", "type": "float"},
            "LIMIT_POSZERZANIA":   {"label": "Limit poszerzania:", "default": "2.0", "type": "float"}
        }
    },
}

# ==============================================================================
# SEKCJA 2: WIDGETY POMOCNICZE
# ==============================================================================

class CustomHeaderView(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsMovable(True)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
        
    def mousePressEvent(self, event):
        idx = self.logicalIndexAt(event.pos())
        if idx == -1: super().mousePressEvent(event); return
        header_pos = self.sectionViewportPosition(idx)
        width = self.sectionSize(idx)
        click_x = event.pos().x()
        
        if (header_pos + width - 25) < click_x < (header_pos + width):
            order = Qt.SortOrder.DescendingOrder if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
            self.setSortIndicator(idx, order)
            self.model().sort(idx, order)
        else:
            super().mousePressEvent(event)
            if self.model(): self.model().set_highlight_col_only(idx)
                
    def mouseDoubleClickEvent(self, event):
        idx = self.logicalIndexAt(event.pos())
        if idx >= 0 and self.model():
            col_name = self.model().headerData(idx, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
            if col_name in ["PRZEKAZ", "WYKLUCZ"]: self.model().toggle_column_all(col_name)
        super().mouseDoubleClickEvent(event)

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        btn_rect = rect.adjusted(rect.width() - 22, 4, -2, -4)
        painter.setBrush(QColor(60, 60, 60))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(btn_rect, 3, 3)
        painter.setPen(QColor(220, 220, 220))
        font = painter.font(); font.setPixelSize(10); painter.setFont(font)
        painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "⇅")
        painter.restore()

class FilterWidget(QWidget):
    def __init__(self, parent=None, columns=[]):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        
        self.combo_col = QComboBox()
        self.combo_col.addItems(columns)
        self.combo_col.setMinimumWidth(120)
        
        self.inp_min = QLineEdit()
        self.inp_min.setPlaceholderText("Min")
        self.inp_min.setFixedWidth(60)
        
        self.inp_max = QLineEdit()
        self.inp_max.setPlaceholderText("Max")
        self.inp_max.setFixedWidth(60)
        
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(25)
        self.btn_remove.setStyleSheet("background-color: #802020; color: white; font-weight: bold;")
        self.btn_remove.clicked.connect(self.deleteLater)
        
        layout.addWidget(self.combo_col)
        layout.addWidget(self.inp_min)
        layout.addWidget(self.inp_max)
        layout.addWidget(self.btn_remove)

class AdvancedPandasModel(QAbstractTableModel):
    def __init__(self, df=pd.DataFrame()):
        super().__init__()
        self._df_original = df.copy()
        self._df = df.copy()
        self.use_scientific = False
        self.show_excluded = True
        self.highlight_row = -1
        self.highlight_col = -1
        self.colors = {
            "bg_1": QColor(35, 35, 35), 
            "bg_2": None, 
            "bg_excluded": QColor(60, 20, 20),
            "bg_passed": QColor(20, 60, 20), 
            "bg_highlight": QColor(70, 70, 120), 
            "text_normal": QColor(230, 230, 230)
        }
        self._ensure_control_columns()

    def _ensure_control_columns(self):
        for df in [self._df, self._df_original]:
            if not df.empty:
                if "PRZEKAZ" not in df.columns: df.insert(0, "PRZEKAZ", False)
                if "WYKLUCZ" not in df.columns: df.insert(1, "WYKLUCZ", False)

    def rowCount(self, parent=None): return self._df.shape[0]
    def columnCount(self, parent=None): return self._df.shape[1]
    def headerData(self, section, orientation, role):
        # Obsługa wyświetlania tekstu w nagłówkach
        if role == Qt.ItemDataRole.DisplayRole:
            
            # Nagłówki Poziome (Kolumny)
            if orientation == Qt.Orientation.Horizontal:
                if section < len(self._df.columns):
                    col_name = self._df.columns[section]
                    
                    # Używamy mapowania na ładne nazwy (zdefiniowane w HEADER_MAP na górze pliku)
                    if col_name in HEADER_MAP:
                        nazwa, jednostka = HEADER_MAP[col_name]
                        return f"{nazwa}\n[{jednostka}]"
                    
                    return str(col_name)
            
            # Nagłówki Pionowe (Numery wierszy)
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        
        # Obsługa dymków z podpowiedzią (ToolTip) - pokazuje surową nazwę kolumny
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            if section < len(self._df.columns):
                return str(self._df.columns[section])
                
        return None
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        row = index.row()
        col = index.column()
        col_name = self._df.columns[col]
        value = self._df.iloc[row, col]

        if col_name in ["PRZEKAZ", "WYKLUCZ"]:
            if role == Qt.ItemDataRole.CheckStateRole: 
                return Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, (int, float)):
                if self.use_scientific: return f"{value:.2e}"
                else: return f"{int(value)}" if float(value).is_integer() else f"{value:.4f}"
            return str(value)

        if role == Qt.ItemDataRole.BackgroundRole:
            if row == self.highlight_row or col == self.highlight_col: return self.colors["bg_highlight"]
            if self._df.iloc[row]["WYKLUCZ"]: return self.colors["bg_excluded"]
            if self._df.iloc[row]["PRZEKAZ"]: return self.colors["bg_passed"]
            if self.colors["bg_2"] is not None and row % 2 == 1: return self.colors["bg_2"]
            return self.colors["bg_1"]

        if role == Qt.ItemDataRole.ForegroundRole: return self.colors["text_normal"]
        if role == Qt.ItemDataRole.ToolTipRole: return f"{col_name}"
        return None

    def setData(self, index, value, role):
        if not index.isValid(): return False
        if role == Qt.ItemDataRole.CheckStateRole:
            col_name = self._df.columns[index.column()]
            if col_name in ["PRZEKAZ", "WYKLUCZ"]:
                new_val = (value == Qt.CheckState.Checked.value)
                self._df.iloc[index.row(), index.column()] = new_val
                real_idx = self._df.index[index.row()]
                if real_idx in self._df_original.index:
                    col_idx_orig = self._df_original.columns.get_loc(col_name)
                    self._df_original.iloc[real_idx, col_idx_orig] = new_val
                self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.BackgroundRole])
                return True
        return False

    def flags(self, index):
        col_name = self._df.columns[index.column()]
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if col_name in ["PRZEKAZ", "WYKLUCZ"]: return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def sort(self, column, order):
        colname = self._df.columns[column]
        self.layoutAboutToBeChanged.emit()
        self._df.sort_values(by=colname, ascending=(order == Qt.SortOrder.AscendingOrder), inplace=True)
        self.layoutChanged.emit()

    def set_scientific_notation(self, enable): 
        self.use_scientific = enable; self.layoutChanged.emit()
    
    def set_highlight(self, row, col): 
        self.highlight_row = row; self.highlight_col = col; self.layoutChanged.emit()
    
    def set_highlight_col_only(self, col): 
        self.highlight_row = -1; self.highlight_col = col; self.layoutChanged.emit()
    
    def set_column_state(self, col_name, state):
        if col_name not in self._df.columns: return
        self.layoutAboutToBeChanged.emit()
        self._df[col_name] = state
        self._df_original.loc[self._df.index, col_name] = state
        self.layoutChanged.emit()
    
    def toggle_column_all(self, col_name):
        if col_name not in self._df.columns: return
        self.layoutAboutToBeChanged.emit()
        current_val = self._df[col_name].iloc[0] if len(self._df) > 0 else False
        new_val = not current_val
        self._df[col_name] = new_val
        self._df_original.loc[self._df.index, col_name] = new_val
        self.layoutChanged.emit()

    def apply_advanced_filter(self, filters_list, show_excluded):
        self.layoutAboutToBeChanged.emit()
        df_temp = self._df_original.copy()
        
        # Logika: Jeśli NIE pokazujemy wykluczonych, to bierzemy tylko te,
        # gdzie WYKLUCZ jest Fałszem (lub Puste/0).
        if not show_excluded:
            # Bezpieczniejsze filtrowanie (obsługuje bool i int 0/1)
            df_temp = df_temp[ (df_temp["WYKLUCZ"] == False) | (df_temp["WYKLUCZ"] == 0) ]
        
        for col, vmin, vmax in filters_list:
            if col in df_temp.columns:
                try:
                    df_temp[col] = pd.to_numeric(df_temp[col], errors='coerce')
                    if vmin is not None: df_temp = df_temp[df_temp[col] >= vmin]
                    if vmax is not None: df_temp = df_temp[df_temp[col] <= vmax]
                except: pass
        self._df = df_temp
        self.layoutChanged.emit()

class MaterialSelectorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_add = QPushButton(" + Dodaj Materiał do Analizy")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: #2da342; color: white; font-weight: bold; 
                padding: 8px; border-radius: 4px; text-align: left;
            }
            QPushButton::menu-indicator { subcontrol-position: right center; right: 10px; }
        """)
        
        self.menu = QMenu(self)
        self.btn_add.setMenu(self.menu)
        layout.addWidget(self.btn_add)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setStyleSheet("QListWidget { background: #333; border: 1px solid #555; }")
        self.list_widget.setFixedHeight(120)
        layout.addWidget(self.list_widget)
        
        self.refresh_menu()
        self.add_material_tile("S355")

    def refresh_menu(self):
        self.menu.clear()
        try:
            db = material_catalogue.baza_materialow()
            grouped = {}
            for k, v in db.items():
                typ = v.get("Typ", "Inne")
                if typ not in grouped: grouped[typ] = []
                grouped[typ].append(k)
            
            order = ["Stal", "Nierdzewna", "Aluminium"]
            remaining = sorted([k for k in grouped.keys() if k not in order])
            
            for group in order + remaining:
                if group in grouped:
                    sub = self.menu.addMenu(group)
                    for mat in sorted(grouped[group]):
                        action = sub.addAction(mat)
                        action.triggered.connect(lambda checked, m=mat: self.add_material_tile(m))
        except Exception as e:
            print(f"Błąd ładowania materiałów: {e}")

    def add_material_tile(self, name):
        existing = self.get_selected_materials()
        if name in existing: return

        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(0, 34)) 
        item.setData(Qt.ItemDataRole.UserRole, name)
        
        widget = QWidget()
        w_layout = QHBoxLayout(widget)
        w_layout.setContentsMargins(5, 2, 5, 2)
        
        lbl = QLabel(name)
        lbl.setStyleSheet("font-weight: bold; color: white;")
        
        btn_del = QPushButton("✕")
        btn_del.setFixedSize(24, 24)
        btn_del.setStyleSheet("background-color: #c0392b; color: white; border-radius: 12px; font-weight: bold;")
        btn_del.clicked.connect(lambda: self.remove_item(item))
        
        w_layout.addWidget(lbl)
        w_layout.addStretch()
        w_layout.addWidget(btn_del)
        
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

    def remove_item(self, item):
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)

    def get_selected_materials(self):
        materials = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            val = item.data(Qt.ItemDataRole.UserRole)
            if val: materials.append(val)
        return materials

class SingleProfileWidget(QGroupBox):
    def __init__(self, index, parent=None):
        super().__init__(f"Profil #{index}")
        self.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; border: 1px solid #555; margin-top: 25px; 
                padding-top: 15px; background-color: #2b2b2b; 
            }
            QGroupBox::title { 
                subcontrol-origin: margin; subcontrol-position: top left; 
                padding: 0 5px; color: #aaa; left: 10px; 
            }
        """)
        layout = QFormLayout()
        layout.setContentsMargins(10, 20, 10, 10)
        
        self.combo_mat = QComboBox()
        self.populate_materials()
        
        self.inp_prof = QLineEdit("UPE200")
        self.inp_tp = QLineEdit("10")
        self.inp_bp = QLineEdit("300")
        self.inp_otw = QLineEdit("100")
        
        layout.addRow("Materiał:", self.combo_mat)
        layout.addRow("Typ (np. UPE200):", self.inp_prof)
        layout.addRow("Grubość blachy [mm]:", self.inp_tp)
        layout.addRow("Szerokość blachy [mm]:", self.inp_bp)
        layout.addRow("Otwarcie [mm]:", self.inp_otw)
        self.setLayout(layout)

    def populate_materials(self):
        self.combo_mat.clear()
        try:
            db = material_catalogue.baza_materialow()
            grouped = {}
            for k, v in db.items():
                typ = v.get("Typ", "Inne")
                if typ not in grouped: grouped[typ] = []
                grouped[typ].append(k)
            
            order = ["Stal", "Nierdzewna", "Aluminium"]
            remaining = sorted([k for k in grouped.keys() if k not in order])
            
            for group in order + remaining:
                if group in grouped:
                    for mat in sorted(grouped[group]):
                        self.combo_mat.addItem(f"[{group}] {mat}", mat)
        except Exception as e:
            print(f"Błąd ładowania materiałów w widgecie: {e}")

# ==============================================================================
# SEKCJA 3: WORKERS I ZAKŁADKI (MODULARNE)
# ==============================================================================

class OptimizationWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    found_file_signal = pyqtSignal(str)

    def __init__(self, router_instance=None):
        super().__init__()
        self.router = router_instance

    def run(self):
        original_stdout = sys.__stdout__
        class StreamToSignal:
            def __init__(self, s): self.s = s
            def write(self, t): 
                try: self.s.emit(str(t)); original_stdout.write(str(t))
                except: pass
            def flush(self): original_stdout.flush()
        
        sys.stdout = StreamToSignal(self.log_signal)
        try:
            self.log_signal.emit(">>> Inicjalizacja wątku...\n")
            import config_solver
            importlib.reload(config_solver)
            
            # --- SMART IMPORT SOLVERA ---
            root_dir = os.path.dirname(os.path.abspath(__file__))
            module_name = "solver_1_standard"
            possible_folders = ["solvers_opt", "solvers_opty"]
            solvers_subdir = None
            
            for folder in possible_folders:
                check_path = os.path.join(root_dir, folder)
                if os.path.exists(os.path.join(check_path, f"{module_name}.py")):
                    solvers_subdir = check_path
                    self.log_signal.emit(f">>> Wykryto solver w folderze: {folder}\n")
                    break
            
            if not solvers_subdir and os.path.exists(os.path.join(root_dir, f"{module_name}.py")):
                solvers_subdir = root_dir
                self.log_signal.emit(f">>> Wykryto solver w katalogu głównym.\n")
                
            if not solvers_subdir:
                raise FileNotFoundError(f"Nie znaleziono pliku {module_name}.py")

            if solvers_subdir not in sys.path:
                sys.path.append(solvers_subdir)

            self.log_signal.emit(f">>> Ładowanie modułu: {module_name}\n")
            
            solver_module = importlib.import_module(module_name)
            importlib.reload(solver_module)
            
            self.log_signal.emit(">>> Start symulacji...\n")
            
            sciezka_wynikowa = solver_module.glowna_petla_optymalizacyjna(router_instance=self.router)
            
            if sciezka_wynikowa: self.found_file_signal.emit(str(sciezka_wynikowa))
            self.finished_signal.emit(True, str(sciezka_wynikowa))
            
        except Exception as e:
            import traceback
            sys.stdout = original_stdout
            msg = traceback.format_exc()
            self.log_signal.emit("\n!!! BŁĄD KRYTYCZNY !!!\n" + msg)
            self.finished_signal.emit(False, "")
        finally:
            sys.stdout = original_stdout

class FemWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    data_signal = pyqtSignal(dict)
    
    def __init__(self, candidates, settings):
        super().__init__()
        self.candidates = candidates
        self.settings = settings
        self.optimizer = fem_optimizer.FemOptimizer(router)
        self.summary_data = [] 
        
    def run(self):
        self.log_signal.emit(">>> START PROCEDURY FEM BATCH...")
        success_count = 0
        
        for i, cand in enumerate(self.candidates):
            prof_name = cand.get('Nazwa_Profilu', 'Unknown')
            self.log_signal.emit(f"\n--- Przetwarzanie: {prof_name} ({i+1}/{len(self.candidates)}) ---")
            
            try:
                # --- [NOWOŚĆ] INTELIGENTNA KOREKTA SIATKI (Auto-Mesh Check) ---
                # Pobieramy wymiary krytyczne, aby uniknąć błędu generacji siatki
                # (Element skończony nie może być większy niż grubość ścianki)
                thicknesses = []
                if 'Input_UPE_twc' in cand: thicknesses.append(float(cand['Input_UPE_twc'])) # Środnik
                if 'Input_UPE_tfc' in cand: thicknesses.append(float(cand['Input_UPE_tfc'])) # Półka
                if 'Input_Geo_tp' in cand: thicknesses.append(float(cand['Input_Geo_tp']))   # Płaskownik
                
                # Tworzymy lokalną kopię ustawień dla tego jednego profilu
                local_settings = self.settings.copy()
                
                if thicknesses:
                    min_t = min(thicknesses)
                    user_mesh = float(local_settings.get('mesh_start_size', 15.0))
                    
                    # Warunek: Jeżeli siatka użytkownika jest większa niż najcieńsza ścianka -> Error
                    # Akcja: Zmniejszamy siatkę startową do wartości grubości ścianki
                    if user_mesh > min_t:
                        self.log_signal.emit(f"   [AUTO-CHECK] Wykryto cienką ściankę: {min_t} mm (vs Siatka {user_mesh} mm)")
                        self.log_signal.emit(f"   [AUTO-CHECK] -> Automatyczna korekta siatki startowej na: {min_t} mm")
                        local_settings['mesh_start_size'] = min_t

                # Uruchomienie obliczeń z (ewentualnie) skorygowanymi ustawieniami
                res = self.optimizer.run_single_candidate(
                    cand, 
                    local_settings, 
                    signal_callback=self.log_signal.emit
                )
                
                # Przekazanie danych do GUI
                res['profile_name'] = prof_name
                res['final_stress'] = res.get('final_vm', res.get('final_stress', 0.0))
                self.data_signal.emit(res)

                status_text = "ZBIEŻNY" if res['converged'] else "NIEZBIEŻNY"
                self.log_signal.emit(f"   [KONIEC PROFILU] Status: {status_text}, Final Stress: {res['final_stress']:.2f} MPa")
                
                if res['converged']: success_count += 1
                
                # Zbieranie danych do raportu
                final_json_path = router.get_path("FINAL", f"{res['id']}_RESULTS.json")
                if os.path.exists(final_json_path):
                    import json
                    try:
                        with open(final_json_path, 'r') as f: full = json.load(f)
                        self.summary_data.append({
                            "Profil": prof_name,
                            "Material": cand.get("Stop"),
                            "Iteracje": res.get('iterations', 0),
                            "Zbieznosc": "TAK" if res['converged'] else "NIE",
                            "Max_VM": full.get("MODEL_MAX_VM", 0)
                        })
                    except: pass

            except Exception as e:
                # --- [NOWOŚĆ] PEŁNE RAPORTOWANIE BŁĘDÓW DO KONSOLI GUI ---
                self.log_signal.emit(f"CRITICAL ERROR: {str(e)}")
                import traceback
                # Przekierowanie pełnego zrzutu błędu do okna logów w aplikacji
                self.log_signal.emit(traceback.format_exc())
        
        # Zapis pliku zbiorczego
        if self.summary_data and len(self.candidates) > 1:
            try:
                ts = datetime.now().strftime("%H%M%S")
                path = router.get_path("FINAL", f"BATCH_REPORT_{ts}.csv")
                import csv
                keys = self.summary_data[0].keys()
                with open(path, 'w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=keys, delimiter=';')
                    w.writeheader()
                    w.writerows(self.summary_data)
                self.log_signal.emit(f"\n>>> ZAPISANO RAPORT: {path}")
            except Exception as e:
                self.log_signal.emit(f"Błąd zapisu raportu: {e}")

        self.log_signal.emit(f"\n>>> ZAKOŃCZONO. Sukces: {success_count}/{len(self.candidates)}")
        self.finished_signal.emit(True)

class Tab1_Dashboard(QWidget):
    switch_tab_signal = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_widgets = [] 
        self.init_ui()
        self.dynamic_inputs = {}
        # FIX: Odwołanie do combo_algo, które jest już zdefiniowane w init_ui
        self.update_algo_params(self.combo_algo.currentText())

    def init_ui(self):
        main_split = QHBoxLayout(self)
        
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setSpacing(10)
        
        # A: Globalne
        g_loads = QGroupBox("1. Obciążenia Globalne")
        g_loads.setFixedHeight(180)
        l_loads = QHBoxLayout()
        f1 = QFormLayout()
        self.inp_Fx = QLineEdit("24000.0"); self.inp_L = QLineEdit("1800.0"); self.inp_Promien = QLineEdit("450.0")
        f1.addRow("Fx [N]:", self.inp_Fx); f1.addRow("L [mm]:", self.inp_L); f1.addRow("Ramię [mm]:", self.inp_Promien)
        
        f2 = QFormLayout()
        self.inp_Ty = QLineEdit("0.2"); self.inp_Tz = QLineEdit("0.2")
        self.inp_GM0 = QLineEdit("2.0"); self.inp_GM1 = QLineEdit("2.0"); self.inp_Alfa = QLineEdit("0.49")
        f2.addRow("w_Ty:", self.inp_Ty); f2.addRow("w_Tz:", self.inp_Tz)
        f2.addRow("Gamma M0:", self.inp_GM0); f2.addRow("Gamma M1:", self.inp_GM1); f2.addRow("Alfa Imp:", self.inp_Alfa)
        
        l_loads.addLayout(f1); l_loads.addLayout(f2); g_loads.setLayout(l_loads)
        left_layout.addWidget(g_loads)
        
        # B: Tryb
        g_mode = QGroupBox()
        g_mode.setStyleSheet("QGroupBox{border:none;background:#333;border-radius:5px;}")
        l_mode = QHBoxLayout(g_mode)
        self.rb_auto = QRadioButton("🤖 AUTO"); self.rb_manual = QRadioButton("📐 MANUAL")
        self.rb_auto.setChecked(True)
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.rb_auto, 0); self.mode_group.addButton(self.rb_manual, 1)
        self.mode_group.idToggled.connect(self.on_mode_changed)
        l_mode.addWidget(self.rb_auto); l_mode.addStretch(); l_mode.addWidget(self.rb_manual)
        left_layout.addWidget(g_mode)
        
        # C: Stack
        self.stack = QStackedWidget()
        
        # AUTO
        page_auto = QWidget(); la = QVBoxLayout(page_auto)
        g_mat = QGroupBox("2. Materiały"); lm = QVBoxLayout()
        self.material_selector = MaterialSelectorWidget()
        lm.addWidget(self.material_selector); g_mat.setLayout(lm); la.addWidget(g_mat)
        
        g_algo = QGroupBox("3. Algorytm"); l_algo = QHBoxLayout()
        f_geo = QFormLayout()
        self.inp_MinOtw = QLineEdit("70.0"); self.inp_MaxTp = QLineEdit("25.0")
        f_geo.addRow("Min Otw:", self.inp_MinOtw); f_geo.addRow("Max Grub:", self.inp_MaxTp)
        
        l_dyn = QVBoxLayout()
        self.combo_algo = QComboBox(); self.combo_algo.addItems(OPTIMIZER_REGISTRY.keys())
        self.combo_algo.currentTextChanged.connect(self.update_logic_panel)
        self.logic_params_container = QWidget(); self.logic_params_layout = QFormLayout(self.logic_params_container)
        l_dyn.addWidget(self.combo_algo); l_dyn.addWidget(self.logic_params_container)
        
        l_algo.addLayout(f_geo, 1); l_algo.addLayout(l_dyn, 2); g_algo.setLayout(l_algo); la.addWidget(g_algo)
        
        g_files = QGroupBox("4. Pliki"); lf = QHBoxLayout()
        self.inp_NazwaBadania = QLineEdit(""); self.inp_NazwaBadania.setPlaceholderText("Nazwa folderu (opcjonalna)")
        self.chk_WspolnyKat = QCheckBox("Wspólny Katalog"); self.chk_PokazKroki = QCheckBox("Logowanie kroków")
        lf.addWidget(QLabel("Nazwa:")); lf.addWidget(self.inp_NazwaBadania); lf.addWidget(self.chk_WspolnyKat); lf.addWidget(self.chk_PokazKroki)
        g_files.setLayout(lf); la.addWidget(g_files); la.addStretch(); self.stack.addWidget(page_auto)
        
        # MANUAL
        page_manual = QWidget(); lm2 = QVBoxLayout(page_manual)
        self.scroll_prof = QScrollArea(); self.scroll_prof.setWidgetResizable(True)
        self.prof_cont = QWidget(); self.prof_lay = QVBoxLayout(self.prof_cont); self.prof_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_prof.setWidget(self.prof_cont); lm2.addWidget(self.scroll_prof)
        btn_addp = QPushButton("+ Profil"); btn_addp.clicked.connect(self.add_manual_profile)
        lm2.addWidget(btn_addp)
        self.stack.addWidget(page_manual)
        self.add_manual_profile()
        
        left_layout.addWidget(self.stack); main_split.addWidget(left_container, 6)
        
        # PRAWY PANEL
        right_container = QWidget(); rl = QVBoxLayout(right_container)
        g_run = QGroupBox("Sterowanie"); lr = QVBoxLayout()
        
        self.btn_run_opty = QPushButton("URUCHOM PROCES")
        self.btn_run_opty.setFixedHeight(60)
        self.btn_run_opty.setStyleSheet("background-color: #2a82da; font-weight: bold; font-size: 16px;")
        self.btn_run_opty.clicked.connect(self.run_process_based_on_mode)
        
        self.console = QTextBrowser()
        self.console.setStyleSheet("background:#111; color:#0f0; font-family:Consolas;")
        self.console.setOpenExternalLinks(False)
        self.console.anchorClicked.connect(self.on_console_link_click)
        
        self.progress = QProgressBar()
        
        lr.addWidget(self.btn_run_opty); lr.addWidget(QLabel("Logi:")); lr.addWidget(self.console); lr.addWidget(self.progress)
        g_run.setLayout(lr); rl.addWidget(g_run); 
        # FIX: Używamy main_split a nie layout
        main_split.addWidget(right_container, 4)

    def on_mode_changed(self, btn_id, checked):
        if checked:
            self.stack.setCurrentIndex(btn_id)
            if btn_id == 0:
                self.btn_run_opty.setText("URUCHOM OPTYMALIZACJĘ 🤖")
                self.btn_run_opty.setStyleSheet("background-color: #2a82da; font-size: 16px; font-weight: bold;")
            else:
                self.btn_run_opty.setText("PRZELICZ PROFILE RĘCZNIE 📐")
                self.btn_run_opty.setStyleSheet("background-color: #d68a00; color: black; font-size: 16px; font-weight: bold;")

    def update_logic_panel(self, algo_name):
        while self.logic_params_layout.count():
            child = self.logic_params_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.dynamic_inputs = {}
        if algo_name in OPTIMIZER_REGISTRY:
            params = OPTIMIZER_REGISTRY[algo_name].get("params", {})
            for key, info in params.items():
                inp = QLineEdit(str(info["default"]))
                self.dynamic_inputs[key] = inp
                self.logic_params_layout.addRow(info["label"], inp)
    
    def update_algo_params(self, name): self.update_logic_panel(name)

    def add_manual_profile(self):
        idx = len(self.profile_widgets) + 1
        w = SingleProfileWidget(idx)
        self.prof_lay.addWidget(w)
        self.profile_widgets.append(w)
        # FIX: Poprawna nazwa scrolla
        self.scroll_prof.verticalScrollBar().setValue(self.scroll_prof.verticalScrollBar().maximum())

    def save_config(self):
        mats = self.material_selector.get_selected_materials()
        if not mats and self.mode_group.checkedId() == 0: raise ValueError("Wybierz materiał!")
        
        dyn_str = ""
        for k, i in self.dynamic_inputs.items():
            typ = OPTIMIZER_REGISTRY[self.combo_algo.currentText()]["params"][k]["type"]
            val = f'"{i.text()}"' if typ=="str" else i.text()
            dyn_str += f"{k} = {val}\n"

        content = f"""# AUTO-GENERATED CONFIG
LOAD_PARAMS = {{ "Fx": {self.inp_Fx.text()}, "F_promien": {self.inp_Promien.text()}, "L": {self.inp_L.text()}, "w_Ty": {self.inp_Ty.text()}, "w_Tz": {self.inp_Tz.text()} }}
LISTA_MATERIALOW = {mats if self.mode_group.checkedId()==0 else []}
MIN_SZEROKOSC_OTWARCIA = {self.inp_MinOtw.text()}
MAX_GRUBOSC_PLASKOWNIKA = {self.inp_MaxTp.text()}
SAFETY_PARAMS = {{ "gamma_M0": {self.inp_GM0.text()}, "gamma_M1": {self.inp_GM1.text()}, "alfa_imp": {self.inp_Alfa.text()} }}
NAZWA_BADANIA = "{self.inp_NazwaBadania.text()}"
WSPOLNY_KATALOG = {self.chk_WspolnyKat.isChecked()}
POKAZUJ_KROKI_POSREDNIE = {self.chk_PokazKroki.isChecked()}
# DYNAMICZNE
{dyn_str}
"""
        with open("config_solver.py", "w", encoding="utf-8") as f:
            f.write(content)

    def run_process_based_on_mode(self):
        mode = self.mode_group.checkedId()
        self.console.clear()
        try:
            if mode == 0: # AUTO
                name = self.inp_NazwaBadania.text() or f"Auto_{datetime.now().strftime('%H%M%S')}"
                router.set_project(name)
                self.console.append(f">>> Projekt: {name}")
                self.save_config()
                
                self.worker = OptimizationWorker(router)
                self.worker.log_signal.connect(self.console.append)
                self.worker.finished_signal.connect(self.on_finished)
                self.worker.found_file_signal.connect(lambda p: setattr(self, 'last_res', p))
                self.btn_run_opty.setEnabled(False); self.progress.setValue(5)
                self.worker.start()
            else: # MANUAL
                self.run_manual_logic()
        except Exception as e:
            self.console.append(f"<b style='color:red'>BŁĄD: {e}</b>")

    def run_manual_logic(self):
        self.console.append(">>> Tryb Manualny...")
        if not self.profile_widgets: return
        
        try:
            self.save_config()
            import config_solver; importlib.reload(config_solver)
            import engine_solver; importlib.reload(engine_solver)
            import material_catalogue
            
            root = os.path.dirname(os.path.abspath(__file__))
            solvers = ["solvers_opt", "solvers_opty"]
            found = False
            for f in solvers:
                if os.path.exists(os.path.join(root, f, "solver_1_standard.py")):
                    if os.path.join(root, f) not in sys.path: sys.path.append(os.path.join(root, f))
                    found = True; break
            
            if not found and os.path.exists(os.path.join(root, "solver_1_standard.py")): found=True
            if not found: raise FileNotFoundError("Brak solver_1_standard.py")
            
            opty = importlib.import_module("solver_1_standard"); importlib.reload(opty)
            
            w = self.profile_widgets[0]
            mat = w.combo_mat.currentText().split("] ")[-1] if "]" in w.combo_mat.currentText() else w.combo_mat.currentText()
            prof = w.inp_prof.text().upper()
            try: tp = float(w.inp_tp.text()); bp = float(w.inp_bp.text()); otw = float(w.inp_otw.text())
            except: self.console.append("Błąd liczb!"); return
            
            mdb = material_catalogue.baza_materialow()
            if mat not in mdb:
                for k in mdb.keys():
                    if k in mat: mat = k; break
            if mat not in mdb: self.console.append("Nieznany materiał"); return
            
            pdb = material_catalogue.pobierz_ceownik(prof)
            if not pdb: self.console.append("Nieznany profil"); return
            
            load = config_solver.LOAD_PARAMS.copy(); load.update(mdb[mat])
            geo = {"bp": bp, "tp": tp}
            
            res = engine_solver.analizuj_przekroj_pelna_dokladnosc(pdb, geo, load, config_solver.SAFETY_PARAMS)
            masa = engine_solver.oblicz_mase_metra(pdb, geo, load)
            dane = engine_solver.splaszcz_wyniki_do_wiersza(pdb, geo, load, config_solver.SAFETY_PARAMS, res)
            
            dane.update({"Stop": mat, "Nazwa_Profilu": prof, "Input_Geo_b_otw": otw, 
                         "Input_Geo_tp": tp, "Input_Geo_bp": bp, "Res_Masa_kg_m": masa, 
                         "Raport_Etap": "MANUAL"})
            
            dane["Calc_Fy"] = load['Fx']*load['w_Ty']; dane["Calc_Fz"] = load['Fx']*load['w_Tz']
            dane["Calc_Nb_Rd"] = (dane.get("Res_Stab_Chi_N",0)*dane.get("Res_Geo_Acal",0)*load['Re'])/config_solver.SAFETY_PARAMS['gamma_M1']
            dane["Status_Wymogow"] = "SPEŁNIA" if res['Wskazniki']['UR']<=1.0 and res['Wskazniki']['Klasa_Przekroju']<=3 else "NIE SPEŁNIA"
            
            keys = opty.sortuj_klucze_wg_priorytetu(list(dane.keys()))
            html = "<table border=1 cellspacing=0 cellpadding=3 style='font-size:11px'>"
            for k in keys:
                v = dane[k]; sv = f"{v:.4f}" if isinstance(v, float) else str(v)
                color = "#ccc"
                if k == "Status_Wymogow": color = "#0f0" if v=="SPEŁNIA" else "#f00"
                elif "Res_UR" in k: color = "#0f0" if v<=1.0 else "#f44"
                html += f"<tr><td>{k}</td><td style='color:{color}'><b>{sv}</b></td></tr>"
            html += "</table>"
            self.console.append(html)
            self.progress.setValue(100)
            
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = router.get_path("TEMP", f"Manual_{prof}_{mat}_{ts}")
            opty.zapisz_wszystkie_formaty([dane], os.path.splitext(path)[0])
            self.console.append(f"<br>Zapisano: {path}.csv")
            
        except Exception as e:
            self.console.append(f"ERROR: {e}\n{traceback.format_exc()}")

    def on_finished(self, success, path):
        self.btn_run_opty.setEnabled(True)
        if success:
            self.progress.setValue(100); self.console.append(f"<b style='color:#0f0'>GOTOWE: {path}</b>")
            self.console.append('<a href="goto_results" style="color:#2a82da;">>>> ZOBACZ WYNIKI <<<</a>')
        else: self.progress.setValue(0)

    def on_console_link_click(self, url):
        # Sprawdzamy czy kliknięto link "zobacz wyniki"
        if url.toString() == "goto_results": 
            try:
                # Pobieramy główne okno aplikacji (rodzica wszystkich zakładek)
                main_window = self.window()
                
                # Przełączamy na zakładkę nr 3 (index 2, bo liczymy od 0: 0=Dash, 1=Baza, 2=Selektor)
                main_window.tabs.setCurrentIndex(2)
                
                # Jeśli mamy zapisaną ścieżkę ostatniego pliku, ładujemy go w Tab3
                if hasattr(self, 'last_res') and self.last_res:
                    # Odwołujemy się do obiektu tab3 w głównym oknie
                    if hasattr(main_window, 'tab3'):
                        main_window.tab3.load_csv(self.last_res)
                        print(f"Automatycznie załadowano: {self.last_res}")
            except Exception as e:
                self.console.append(f"Błąd nawigacji: {e}")

class Tab2_Knowledge(QWidget):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda i: QDesktopServices.openUrl(QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole))))
        l.addWidget(QLabel("Dostępne dokumenty:")); l.addWidget(self.list)
        b = QPushButton("Odśwież"); b.clicked.connect(self.refresh); l.addWidget(b); self.refresh()
    def refresh(self):
        self.list.clear()
        for f in glob.glob("*.pdf")+glob.glob("Baza wiedzy/*"):
            i = QListWidgetItem(os.path.basename(f)); i.setData(Qt.ItemDataRole.UserRole, os.path.abspath(f)); self.list.addItem(i)

class Tab3_Selector(QWidget):
    request_transfer = pyqtSignal(list)
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        l = QVBoxLayout(self)
        tb = QHBoxLayout()
        b_load = QPushButton("📂 Wczytaj CSV"); b_load.clicked.connect(lambda: self.load_csv())
        self.chk_sci = QCheckBox("E-notacja"); self.chk_sci.stateChanged.connect(self.tog_sci)
        b_col = QPushButton("🎨 Kolor"); b_col.clicked.connect(self.col)
        self.b_send = QPushButton("PRZEKAŻ DO FEM ➡️"); self.b_send.setEnabled(False); self.b_send.clicked.connect(self.send); self.b_send.setStyleSheet("background-color:#2da342;font-weight:bold;")
        tb.addWidget(b_load); tb.addWidget(self.chk_sci); tb.addWidget(b_col); tb.addStretch(); tb.addWidget(self.b_send); l.addLayout(tb)
        
        spl = QSplitter(); l.addWidget(spl)
        
        ff = QFrame(); fl = QVBoxLayout(ff)
        sc = QScrollArea(); sc.setWidgetResizable(True); self.w_fil = QWidget(); self.l_fil = QVBoxLayout(self.w_fil); self.l_fil.setAlignment(Qt.AlignmentFlag.AlignTop); sc.setWidget(self.w_fil); fl.addWidget(sc)
        b_af = QPushButton("+ Filtr"); b_af.clicked.connect(self.add_fil); fl.addWidget(b_af)
        b_ap = QPushButton("Zastosuj"); b_ap.clicked.connect(self.apply); fl.addWidget(b_ap)
        
        # --- POPRAWKA TUTAJ ---
        self.chk_ex = QCheckBox("Pokaż Ukryte")
        self.chk_ex.setChecked(True)
        # To sprawia, że kliknięcie od razu filtruje tabelę
        self.chk_ex.clicked.connect(self.apply) 
        fl.addWidget(self.chk_ex)
        # ----------------------
        
        fl.addWidget(QLabel("Masowe:")); h=QHBoxLayout(); b1=QPushButton("All P"); b1.clicked.connect(lambda: self.bulk("PRZEKAZ", True)); b2=QPushButton("No P"); b2.clicked.connect(lambda: self.bulk("PRZEKAZ", False)); h.addWidget(b1); h.addWidget(b2); fl.addLayout(h)
        h2=QHBoxLayout(); b3=QPushButton("All W"); b3.clicked.connect(lambda: self.bulk("WYKLUCZ", True)); b4=QPushButton("No W"); b4.clicked.connect(lambda: self.bulk("WYKLUCZ", False)); h2.addWidget(b3); h2.addWidget(b4); fl.addLayout(h2)
        spl.addWidget(ff)
        
        self.tab = QTableView(); self.head = CustomHeaderView(self.tab); self.tab.setHorizontalHeader(self.head); spl.addWidget(self.tab)
        self.det = QTextBrowser(); self.det.setStyleSheet("font-family:Consolas;"); spl.addWidget(self.det)
        spl.setSizes([200, 900, 300])

    def load_csv(self, path=None):
        if not path: path, _ = QFileDialog.getOpenFileName(self, "CSV", "", "*.csv")
        if path:
            try:
                df = pd.read_csv(path)
                cols = list(df.columns); m = ['Input_Load_Fx', 'Calc_Fy', 'Calc_Fz']
                for c in m: 
                    if c in cols: cols.remove(c); cols.append(c)
                self.model = AdvancedPandasModel(df[cols])
                self.tab.setModel(self.model); self.avail = list(df.columns)
                self.tab.selectionModel().currentChanged.connect(self.click)
                self.b_send.setEnabled(True)
            except Exception as e: QMessageBox.critical(self, "Err", str(e))

    def click(self, c, p):
        self.model.set_highlight(c.row(), c.column())
        r = self.model._df.iloc[c.row()]
        LMAP = {"Nazwa_Profilu":"Profil","Stop":"Materiał","Res_Masa_kg_m":"Masa","Res_UR":"UR","Status_Wymogow":"Status"}
        ORDER = ["Status_Wymogow","Nazwa_Profilu","Stop","Res_Masa_kg_m","Res_UR","Input_Geo_tp","Input_Geo_bp"]
        html = "<h3>Detale</h3><table border=0>"
        for k in ORDER:
            if k in r:
                val = r[k]; sv = f"{val:.4f}" if isinstance(val, float) else str(val)
                col = "#fff"
                if k=="Status_Wymogow": col="#0f0" if val=="SPEŁNIA" else "red"
                html += f"<tr><td style='color:#ccc'>{LMAP.get(k,k)}:</td><td style='color:{col}'><b>{sv}</b></td></tr>"
        for k, v in r.items():
            if k not in ORDER and (str(k).startswith("Input") or str(k).startswith("Calc")):
                html += f"<tr><td style='color:#888'>{k}:</td><td>{v}</td></tr>"
        html += "</table>"
        self.det.setHtml(html)

    def send(self):
        if not hasattr(self, 'model'): return
        sel = self.model._df[self.model._df["PRZEKAZ"]==True].to_dict('records')
        if not sel: QMessageBox.warning(self,"Info","Zaznacz profile (PRZEKAZ)."); return
        self.request_transfer.emit(sel)
        QMessageBox.information(self, "OK", f"Przekazano {len(sel)} profili.")

    def tog_sci(self, s): 
        if hasattr(self, 'model'): self.model.set_scientific_notation(s==2)
    def col(self): 
        c = QColorDialog.getColor()
        if c.isValid(): self.model.colors["bg_highlight"]=c; self.model.layoutChanged.emit()
    def add_fil(self): 
        if hasattr(self, 'avail'): self.l_fil.addWidget(FilterWidget(columns=self.avail))
    def bulk(self, col, v): 
        if hasattr(self, 'model'): self.model.toggle_column_all(col)
    def apply(self):
        # Ta funkcja teraz jest wywoływana po kliknięciu checkboxa
        if not hasattr(self, 'model'): return
        fs = []
        for i in range(self.l_fil.count()):
            w = self.l_fil.itemAt(i).widget()
            if isinstance(w, FilterWidget):
                try: fs.append((w.combo_col.currentText(), float(w.inp_min.text()) if w.inp_min.text() else None, float(w.inp_max.text()) if w.inp_max.text() else None))
                except: pass
        self.model.apply_advanced_filter(fs, self.chk_ex.isChecked())

class Tab4_Fem(QWidget):
    def __init__(self):
        super().__init__()
        self.cands = []
        self.last_pilot_data = None
        self.plotter = None # Uchwyt do okna 3D
        self.init_ui()

    def init_ui(self):
        l = QHBoxLayout(self)
        
        # --- KOLUMNA 1: USTAWIENIA (BEZ ZMIAN) ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(500) 
        
        w_inp = QWidget()
        l_inp = QVBoxLayout(w_inp)
        l_inp.setSpacing(10)
        
        # 1. PARAMETRY SIATKI
        g_par = QGroupBox("1. Parametry Siatki i Solver")
        f_par = QFormLayout(g_par)
        
        self.sp_mesh = QDoubleSpinBox(); self.sp_mesh.setValue(15.0); self.sp_mesh.setRange(1.0, 100.0); self.sp_mesh.setSuffix(" mm")
        self.lbl_mesh_hint = QLabel("Min. ścianka: (brak danych)")
        self.lbl_mesh_hint.setStyleSheet("color: #d35400; font-size: 10px; font-style: italic;")
        
        self.sp_fact = QDoubleSpinBox(); self.sp_fact.setValue(0.7); self.sp_fact.setSingleStep(0.1); self.sp_fact.setRange(0.1, 0.99)
        self.sp_tol = QDoubleSpinBox(); self.sp_tol.setValue(2.0); self.sp_tol.setSuffix(" %")
        self.sp_iter = QSpinBox(); self.sp_iter.setValue(3); self.sp_iter.setRange(1, 10)
        
        h_mesh = QHBoxLayout()
        h_mesh.addWidget(self.sp_mesh); h_mesh.addWidget(self.lbl_mesh_hint)
        
        f_par.addRow("Startowy rozmiar siatki:", h_mesh)
        f_par.addRow("Współczynnik zagęszczania:", self.sp_fact)
        f_par.addRow("Tolerancja zbieżności:", self.sp_tol)
        f_par.addRow("Max iteracji:", self.sp_iter)
        l_inp.addWidget(g_par)
        
        # 2. STREFY ZAGĘSZCZANIA
        g_zones = QGroupBox("2. Strefy Zagęszczania")
        l_zones = QVBoxLayout(g_zones)
        self.tbl_zones = QTableWidget(0, 5)
        self.tbl_zones.setHorizontalHeaderLabels(["Strefa", "Lc Min", "Lc Max", "D Min", "D Max"])
        self.tbl_zones.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_zones.setFixedHeight(100)
        self.tbl_zones.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        l_zones.addWidget(self.tbl_zones)
        
        hz = QHBoxLayout()
        b_zadd = QPushButton("+"); b_zadd.setFixedSize(30, 25); b_zadd.clicked.connect(self.add_zone_row)
        b_zdel = QPushButton("-"); b_zdel.setFixedSize(30, 25); b_zdel.clicked.connect(self.del_zone_row)
        hz.addWidget(QLabel("Edycja:")); hz.addWidget(b_zadd); hz.addWidget(b_zdel); hz.addStretch()
        l_zones.addLayout(hz)
        self.add_zone_row("SURF_WEBS", 5.0, 15.0)
        self.add_zone_row("SURF_FLANGES", 3.0, 10.0)
        l_inp.addWidget(g_zones)
        
        # 3. SONDY
        g_prob = QGroupBox("3. Punkty Pomiarowe")
        l_prob = QVBoxLayout(g_prob)
        self.tbl_prob = QTableWidget(0, 3)
        self.tbl_prob.setHorizontalHeaderLabels(["Nazwa", "Formuła Y", "Formuła Z"])
        self.tbl_prob.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_prob.setFixedHeight(100)
        l_prob.addWidget(self.tbl_prob)
        hp = QHBoxLayout()
        b_padd = QPushButton("+"); b_padd.setFixedSize(30, 25); b_padd.clicked.connect(self.add_probe_row)
        b_pdel = QPushButton("-"); b_pdel.setFixedSize(30, 25); b_pdel.clicked.connect(self.del_probe_row)
        hp.addWidget(QLabel("Edycja:")); hp.addWidget(b_padd); hp.addWidget(b_pdel); hp.addStretch()
        l_prob.addLayout(hp)
        self.add_probe_row("User_Center", "0", "0")
        self.add_probe_row("User_Flange", "tp/2 + hc", "bc/2")
        l_inp.addWidget(g_prob)
        
        # 4. ZASOBY
        g_sys = QGroupBox("4. Zasoby")
        f_sys = QFormLayout(g_sys)
        self.combo_ord = QComboBox(); self.combo_ord.addItems(["Order 1", "Order 2"]); self.combo_ord.setCurrentIndex(1)
        self.sp_cores_mesh = QSpinBox(); self.sp_cores_mesh.setRange(1, 128); self.sp_cores_mesh.setValue(4)
        self.sp_cores_ccx = QSpinBox(); self.sp_cores_ccx.setRange(1, 128); self.sp_cores_ccx.setValue(4)
        f_sys.addRow("Rząd:", self.combo_ord)
        f_sys.addRow("Rdzenie (M):", self.sp_cores_mesh)
        f_sys.addRow("Rdzenie (S):", self.sp_cores_ccx)
        l_inp.addWidget(g_sys)
        l_inp.addStretch()
        scroll.setWidget(w_inp)
        l.addWidget(scroll)

        # --- KOLUMNA 2: STEROWANIE I WIZUALIZACJA (ZMIANY TUTAJ) ---
        w_res = QWidget()
        l_res = QVBoxLayout(w_res)
        
        # A. Sterowanie
        f_ctrl = QFrame(); f_ctrl.setStyleSheet("background:#2a2a2a; border-radius:5px;")
        l_ctrl = QVBoxLayout(f_ctrl)
        h_pilot = QHBoxLayout()
        self.btn_pilot = QPushButton("1. URUCHOM PILOTA")
        self.btn_pilot.setStyleSheet("background-color:#d35400; font-weight:bold; padding:8px;")
        self.btn_pilot.clicked.connect(self.run_pilot)
        self.btn_pilot.setEnabled(False)
        
        self.btn_show_mesh = QPushButton("👁️ POKAŻ SIATKĘ (3D)")
        self.btn_show_mesh.setEnabled(False)
        self.btn_show_mesh.clicked.connect(self.show_mesh)
        
        h_pilot.addWidget(self.btn_pilot); h_pilot.addWidget(self.btn_show_mesh)
        l_ctrl.addLayout(h_pilot)
        
        self.btn_batch = QPushButton("2. URUCHOM PEŁNY BATCH")
        self.btn_batch.setStyleSheet("background-color:#27ae60; font-weight:bold; padding:8px;")
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self.run_batch)
        l_ctrl.addWidget(self.btn_batch)
        l_res.addWidget(f_ctrl)
        
        # B. Okno 3D (PyVista)
        if HAS_PYVISTA:
            self.frame_3d = QFrame()
            self.frame_3d.setStyleSheet("border: 1px solid #444;")
            l_3d = QVBoxLayout(self.frame_3d)
            l_3d.setContentsMargins(0,0,0,0)
            
            # Tworzymy widget PyVista
            self.plotter = QtInteractor(self.frame_3d)
            self.plotter.set_background("#303030") # Ciemne tło
            l_3d.addWidget(self.plotter.interactor)
            l_res.addWidget(self.frame_3d, stretch=2) # Stretch=2, żeby zajmował więcej miejsca
        else:
            lbl_no_pv = QLabel("Brak biblioteki PyVista. Zainstaluj 'pip install pyvistaqt'.")
            lbl_no_pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_no_pv.setStyleSheet("border: 1px dashed #666; color: #888; padding: 20px;")
            l_res.addWidget(lbl_no_pv, stretch=1)

        # C. Tabela Wyników
        self.tbl_res = QTableWidget(0, 4)
        self.tbl_res.setHorizontalHeaderLabels(["Profil", "Iter", "Conv", "Max VM"])
        self.tbl_res.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_res.setFixedHeight(100) # Mniejsza tabela
        l_res.addWidget(self.tbl_res)
        
        # D. Konsola
        self.con = QTextBrowser()
        self.con.setStyleSheet("font-family:Consolas; font-size:10px; background:#111; color:#0f0;")
        self.con.setFixedHeight(100) # Mniejsza konsola
        l_res.addWidget(self.con)
        
        l.addWidget(w_res)

    # --- METODY LOGIKI (BEZ ZMIAN W WIĘKSZOŚCI) ---
    def add_zone_row(self, name="SURF_WEBS", mn=2.0, mx=10.0):
        if isinstance(name, bool): name = "SURF_WEBS"
        r = self.tbl_zones.rowCount(); self.tbl_zones.insertRow(r)
        cb = QComboBox(); cb.addItems(["SURF_WEBS", "SURF_FLANGES", "SURF_PLATE"]); cb.setEditable(True)
        idx = cb.findText(name); 
        if idx >= 0: cb.setCurrentIndex(idx) 
        else: cb.setCurrentText(name)
        self.tbl_zones.setCellWidget(r, 0, cb)
        self.tbl_zones.setItem(r, 1, QTableWidgetItem(str(mn)))
        self.tbl_zones.setItem(r, 2, QTableWidgetItem(str(mx)))
        self.tbl_zones.setItem(r, 3, QTableWidgetItem("2.0"))
        self.tbl_zones.setItem(r, 4, QTableWidgetItem("10.0"))

    def del_zone_row(self):
        r = self.tbl_zones.currentRow()
        if r >= 0: self.tbl_zones.removeRow(r)

    def add_probe_row(self, name="P_User", fy="0", fz="0"):
        if isinstance(name, bool): name = f"P_User_{self.tbl_prob.rowCount()}"
        r = self.tbl_prob.rowCount(); self.tbl_prob.insertRow(r)
        self.tbl_prob.setItem(r, 0, QTableWidgetItem(name))
        self.tbl_prob.setItem(r, 1, QTableWidgetItem(fy))
        self.tbl_prob.setItem(r, 2, QTableWidgetItem(fz))

    def del_probe_row(self):
        r = self.tbl_prob.currentRow()
        if r >= 0: self.tbl_prob.removeRow(r)

    def receive_data(self, d):
        self.cands = d
        self.con.append(f"Załadowano {len(d)} kandydatów.")
        if d:
            c = d[0]; ts = []
            if 'Input_UPE_twc' in c: ts.append(float(c['Input_UPE_twc']))
            if 'Input_UPE_tfc' in c: ts.append(float(c['Input_UPE_tfc']))
            if 'Input_Geo_tp' in c: ts.append(float(c['Input_Geo_tp']))
            if ts: self.lbl_mesh_hint.setText(f"Min. ścianka: {min(ts)} mm")
        self.btn_pilot.setEnabled(True)
        self.btn_batch.setEnabled(False)

    def get_settings(self):
        zones = []
        for r in range(self.tbl_zones.rowCount()):
            try:
                w_combo = self.tbl_zones.cellWidget(r, 0)
                nm = w_combo.currentText() if w_combo else "Unknown"
                mn = float(self.tbl_zones.item(r, 1).text())
                mx = float(self.tbl_zones.item(r, 2).text())
                dmn = float(self.tbl_zones.item(r, 3).text())
                dmx = float(self.tbl_zones.item(r, 4).text())
                zones.append({"name": nm, "lc_min": mn, "lc_max": mx, "dist_min": dmn, "dist_max": dmx})
            except: pass
        probes = {}
        for r in range(self.tbl_prob.rowCount()):
            try:
                nm = self.tbl_prob.item(r, 0).text()
                fy = self.tbl_prob.item(r, 1).text()
                fz = self.tbl_prob.item(r, 2).text()
                if nm: probes[nm] = (fy, fz)
            except: pass

        return {
            "mesh_start_size": self.sp_mesh.value(),
            "refinement_factor": self.sp_fact.value(),
            "tolerance": self.sp_tol.value()/100.0,
            "max_iterations": self.sp_iter.value(),
            "mesh_order": 2 if self.combo_ord.currentIndex() == 1 else 1,
            "refinement_zones": zones,
            "custom_probes": probes,
            "cores_mesh": self.sp_cores_mesh.value(),
            "cores_solver": self.sp_cores_ccx.value()
        }

    def run_pilot(self):
        if not self.cands: return
        self.con.clear(); self.con.append("=== START PILOTA ===")
        sets = self.get_settings()
        self.w = FemWorker([self.cands[0]], sets)
        self.w.log_signal.connect(self.con.append)
        self.w.data_signal.connect(self.on_worker_data)
        self.w.finished_signal.connect(self.on_pilot_done)
        self.btn_pilot.setEnabled(False)
        self.w.start()

    def on_worker_data(self, data):
        self.last_pilot_data = data
        if 'mesh_path' in data and data['mesh_path']:
            self.btn_show_mesh.setEnabled(True)
            # Automatyczne wyświetlenie siatki po zakończeniu pilota
            self.show_mesh()
        
        r = self.tbl_res.rowCount(); self.tbl_res.insertRow(r)
        self.tbl_res.setItem(r, 0, QTableWidgetItem(data.get('profile_name', '')))
        self.tbl_res.setItem(r, 1, QTableWidgetItem(str(data.get('iterations', 0))))
        self.tbl_res.setItem(r, 2, QTableWidgetItem("TAK" if data.get('converged') else "NIE"))
        self.tbl_res.setItem(r, 3, QTableWidgetItem(f"{data.get('final_stress',0):.2f}"))

    def on_pilot_done(self):
        self.btn_pilot.setEnabled(True)
        self.btn_batch.setEnabled(True)
        self.con.append("Pilot zakończony.")

    def run_batch(self):
        if not self.cands: return
        self.con.append("\n=== START BATCH ===")
        sets = self.get_settings()
        self.tbl_res.setRowCount(0)
        self.w = FemWorker(self.cands, sets)
        self.w.log_signal.connect(self.con.append)
        self.w.data_signal.connect(self.on_worker_data)
        self.w.finished_signal.connect(lambda: self.con.append("=== BATCH ZAKOŃCZONY ==="))
        self.btn_batch.setEnabled(False); self.btn_pilot.setEnabled(False)
        self.w.start()

    # --- NOWA METODA WYŚWIETLANIA W OKNIE APLIKACJI ---
    def show_mesh(self):
        if not HAS_PYVISTA:
            self.con.append("BŁĄD: Brak biblioteki PyVistaQt.")
            return

        if self.last_pilot_data and 'mesh_path' in self.last_pilot_data:
            path = self.last_pilot_data['mesh_path']
            if os.path.exists(path):
                self.con.append(f"Wczytywanie siatki do widoku 3D: {os.path.basename(path)}")
                try:
                    # 1. Wczytaj siatkę
                    mesh = pv.read(path)
                    
                    # 2. Wyczyść scenę
                    self.plotter.clear()
                    
                    # 3. Dodaj siatkę do sceny
                    # show_edges=True pokazuje linie siatki (ważne dla FEM)
                    self.plotter.add_mesh(mesh, show_edges=True, color="lightblue", edge_color="black")
                    
                    # 4. Dodaj bajery (osie, siatka podłogi)
                    self.plotter.add_axes()
                    self.plotter.show_grid()
                    
                    # 5. Zresetuj kamerę żeby widzieć całość
                    self.plotter.reset_camera()
                    
                except Exception as e:
                    self.con.append(f"Błąd wizualizacji PyVista: {e}")
            else:
                self.con.append("Plik siatki nie istnieje.")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Optymalizator Słupa v4.0 (FEM Integrated)")
        self.resize(1400, 950)
        
        # Główny kontener zakładek
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # --- INICJALIZACJA ZAKŁADEK ---
        self.tab1 = Tab1_Dashboard()
        self.tab2 = Tab2_Knowledge()
        self.tab3 = Tab3_Selector()
        self.tab4 = Tab4_Fem()
        
        # --- DODAWANIE ZAKŁADEK DO WIDOKU ---
        self.tabs.addTab(self.tab1, "1. Dashboard & Analityka")
        self.tabs.addTab(self.tab2, "2. Baza Wiedzy")
        self.tabs.addTab(self.tab3, "3. Selektor Wyników")
        self.tabs.addTab(self.tab4, "4. Analiza FEM")
        
        # --- POŁĄCZENIA MIĘDZY ZAKŁADKAMI (ROUTING SYGNAŁÓW) ---
        
        # 1. Tab3 (Kliknięcie "Przekaż do FEM") -> Tab4 (Odbiór danych)
        self.tab3.request_transfer.connect(self.tab4.receive_data)
        
        # 2. Automatyczne przełączenie na Tab4 po przekazaniu danych
        self.tab3.request_transfer.connect(lambda: self.tabs.setCurrentIndex(3))

# ==============================================================================
# URUCHOMIENIE APLIKACJI
# ==============================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Stylizacja (Ciemny motyw Fusion dla profesjonalnego wyglądu)
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    p.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(p)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())