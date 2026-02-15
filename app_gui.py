# -*- coding: utf-8 -*-
##### SEKCJA 1: IMPORTY I KONFIGURACJA GLOBALNA #####

# --- 1. BIBLIOTEKI STANDARDOWE PYTHON ---
import sys
import os
import glob
import json
import subprocess
import importlib
import traceback
from datetime import datetime

# --- 2. BIBLIOTEKI ZEWNĘTRZNE (DATA SCIENCE / OBLICZENIA) ---
import numpy as np
import pandas as pd

# --- 3. BIBLIOTEKI GUI (PYQT6) ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QLabel, QPushButton, QFileDialog, QTableView, 
    QHeaderView, QLineEdit, QFormLayout, QGroupBox, QCheckBox, 
    QSplitter, QProgressBar, QTextBrowser, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QFrame, QComboBox, QColorDialog,
    QSizePolicy, QRadioButton, QButtonGroup, QStackedWidget,
    QMenu, QDoubleSpinBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QDialog, QDialogButtonBox,
    QAbstractItemView, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QUrl, QSize, QThread, 
    pyqtSignal, QTimer, QTime, pyqtSlot
)
from PyQt6.QtGui import (
    QColor, QPalette, QDesktopServices, QAction, 
    QFont, QBrush, QIcon
)

# --- 4. KONFIGURACJA ŚCIEŻEK (Dla importów lokalnych) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# --- 5. MODUŁY WŁASNE (CORE APLIKACJI) ---
import routing
from routing import router
import config_solver
import material_catalogue
import engine_solver
import fem_optimizer
import data_aggregator  # Krytyczny moduł - musi być tu
from fem_optimizer_shell import FemOptimizerShell
from data_aggregator_shell import DataAggregatorShell

# --- 6. IMPORTY OPCJONALNE (WIZUALIZACJA 3D / WYKRESY) ---
# PyVista (3D)
try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
    HAS_PYVISTA = True
except ImportError:
    HAS_PYVISTA = False
    print("Brak biblioteki pyvista/pyvistaqt. Wizualizacja 3D wyłączona.")

# Matplotlib (Wykresy 2D)
try:
    import matplotlib
    # NAPRAWA: Dla PyQt6 używamy 'qtagg', nie 'Qt5Agg'
    matplotlib.use('qtagg') 
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Brak matplotlib. Wykresy 2D wyłączone.")

# --- KONIEC SEKCJI IMPORTÓW ---

# --- GLOBALNE STAŁE GUI ---
HEADER_MAP = {
    # Podstawowe
    "Nazwa_Profilu": ("Profil", "-"),
    "Stop": ("Materiał", "-"),
    "Res_Masa_kg_m": ("Waga", "kg/m"),
    "Status_Wymogow": ("Status", "-"),
    "Res_UR": ("Wytężenie UR", "-"),
    
    # Geometria wejściowa
    "Input_Geo_tp": ("Grubość Płask.", "mm"),
    "Input_Geo_bp": ("Szer. Płask.", "mm"),
    "Input_Geo_b_otw": ("Otwarcie", "mm"),
    
    # Wyniki Wytrzymałościowe
    "Res_Max_VonMises": ("Sigma Red.", "MPa"),
    "Calc_Nb_Rd": ("Nośność Nb", "N"),
    "Res_Stab_M_cr": ("Mcr (Zwich.)", "Nmm"),
    "Res_Stab_N_cr_min": ("Ncr (Min)", "N"),
    "Res_Stab_N_cr_gs": ("Ncr (Gięt-Skręt)", "N"),
    
    # NOWE: Przemieszczenia (z engine_solver v4.0)
    "Res_Disp_U_y_max": ("Ugięcie Y", "mm"),
    "Res_Disp_U_z_max": ("Ugięcie Z", "mm"),
    "Res_Disp_Phi_deg": ("Skręcenie", "deg"),
    
    # Obciążenia
    "Input_Load_Fx": ("Siła Fx", "N"),
    "Res_Force_Fy_Ed": ("Siła Fy", "N"),
    "Res_Force_Fz_Ed": ("Siła Fz", "N"),
    
    # Kontrolne
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
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if section < len(self._df.columns):
                    col_name = self._df.columns[section]
                    if col_name in HEADER_MAP:
                        nazwa, jednostka = HEADER_MAP[col_name]
                        return f"{nazwa}\n[{jednostka}]"
                    return str(col_name)
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
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
        
        if not show_excluded:
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

class MaterialInputDialog(QDialog):
    def __init__(self, material_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Brakujące dane materiałowe")
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(f"Nie znaleziono poprawnych wartości E i G dla materiału: <b>{material_name}</b>"))
        layout.addWidget(QLabel("Proszę podać wartości ręcznie lub anulować symulację dla tego profilu."))
        
        form = QFormLayout()
        self.inp_e = QLineEdit("210000.0")
        self.inp_g = QLineEdit("81000.0")
        form.addRow("Moduł Younga (E) [MPa]:", self.inp_e)
        form.addRow("Moduł Kirchhoffa (G) [MPa]:", self.inp_g)
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        """Zwraca (E, G) lub (None, None) jeśli wartości są nieprawidłowe."""
        try:
            e_val = float(self.inp_e.text())
            g_val = float(self.inp_g.text())
            if e_val > 0 and g_val > 0:
                return e_val, g_val
            else:
                return None, None
        except ValueError:
            return None, None

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
    finished_signal = pyqtSignal(bool) # Sygnał na koniec pracy
    data_signal = pyqtSignal(dict)
    processing_signal = pyqtSignal(str)
    notification_signal = pyqtSignal(str, str)
    
    def __init__(self, candidates, settings):
        super().__init__()
        self.candidates = candidates
        self.settings = settings
        self.optimizer = fem_optimizer.FemOptimizer(router)
        self.summary_data = []
        
    def request_stop(self):
        """Ustawia flagę w optimizerze, aby przerwać pętlę."""
        if hasattr(self, 'optimizer') and self.optimizer:
            self.optimizer.stop_requested = True

    def run(self):
        self.log_signal.emit(">>> START PROCEDURY FEM BATCH...")
        success_count = 0
        
        def interaction_handler(eq, vm):
            """Automatycznie przełącza na solver iteracyjny i wysyła powiadomienie do GUI."""
            msg = f"Model ma ~{eq/1e6:.1f}M równań. Automatyczne przełączenie na solver iteracyjny dla stabilności."
            self.log_signal.emit(f"  ! LIMIT: {msg}")
            self.notification_signal.emit("Zmiana Solvera", msg)
            return "ITERATIVE"

        for i, cand in enumerate(self.candidates):
            prof_name = cand.get('Nazwa_Profilu', 'Unknown')
            tp = float(cand.get("Input_Geo_tp", 10))
            bp = float(cand.get("Input_Geo_bp", 0))
            cid = f"{prof_name}_tp{int(tp)}_bp{int(bp)}"

            # --- [POPRAWKA] Sprawdzenie, czy wynik dla tego kandydata już istnieje ---
            final_dest = self.optimizer.router.get_path("FINAL", "", subdir=cid)
            result_file_path = os.path.join(final_dest, "results.json")

            if os.path.exists(result_file_path):
                self.log_signal.emit(f"\n--- Pomijanie: {prof_name} ({i+1}/{len(self.candidates)}) - wynik już istnieje. ---")
                try:
                    with open(result_file_path, 'r') as f:
                        existing_res = json.load(f)
                    
                    data_for_signal = {
                        'id': cid,
                        'profile_name': prof_name,
                        'iterations': existing_res.get('iterations', 'N/A'),
                        'converged': "IMPORTED",
                        'final_stress': existing_res.get('MODEL_MAX_VM', 0.0),
                        'mesh_path': existing_res.get('mesh_path', None)
                    }
                    self.data_signal.emit(data_for_signal)
                    self.log_signal.emit(f"   [INFO] Zaimportowano istniejący wynik. Max VM: {data_for_signal['final_stress']:.2f} MPa")
                    success_count += 1
                    continue
                except Exception as e:
                    self.log_signal.emit(f"   [WARN] Znaleziono wynik, ale nie można go odczytać: {e}. Przeliczam ponownie.")
            # --------------------------------------------------------------------

            self.processing_signal.emit(cid)
            
            self.log_signal.emit(f"\n--- Przetwarzanie: {prof_name} ({i+1}/{len(self.candidates)}) ---")
            
            try:
                thicknesses = []
                if 'Input_UPE_twc' in cand: thicknesses.append(float(cand['Input_UPE_twc']))
                if 'Input_UPE_tfc' in cand: thicknesses.append(float(cand['Input_UPE_tfc']))
                if 'Input_Geo_tp' in cand: thicknesses.append(float(cand['Input_Geo_tp']))
                
                local_settings = self.settings.copy()
                
                if thicknesses:
                    min_t = min(thicknesses)
                    user_mesh = float(local_settings.get('mesh_start_size', 15.0))
                    if user_mesh > min_t:
                        self.log_signal.emit(f"   [AUTO-CHECK] Korekta siatki: {min_t} mm")
                        local_settings['mesh_start_size'] = min_t

                # Uruchomienie obliczeń (z callbackiem)
                res = self.optimizer.run_single_candidate(
                    cand, 
                    local_settings, 
                    signal_callback=self.log_signal.emit,
                    interaction_callback=interaction_handler
                )
                
                res['profile_name'] = prof_name
                res['final_stress'] = res.get('final_stress', 0.0)
                self.data_signal.emit(res)

                status_text = "ZBIEŻNY" if res['converged'] else "NIEZBIEŻNY"
                self.log_signal.emit(f"   [KONIEC PROFILU] Status: {status_text}, Final Stress: {res['final_stress']:.2f} MPa")
                
                if res['converged']: success_count += 1
                
                # Zbieranie danych do raportu
                self.summary_data.append({
                    "Profil": prof_name,
                    "Material": cand.get("Stop"),
                    "Iteracje": res.get('iterations', 0),
                    "Zbieznosc": "TAK" if res['converged'] else "NIE",
                    "Max_VM": res.get('final_stress', 0)
                })

            except Exception as e:
                self.log_signal.emit(f"CRITICAL ERROR: {str(e)}")
                import traceback
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
        self.update_algo_params(self.combo_algo.currentText())

    def init_ui(self):
        main_split = QHBoxLayout(self)
        
        # --- [MODYFIKACJA] Dodanie QScrollArea dla lewego panelu ---
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        # ---------------------------------------------------------

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setSpacing(10)
        
        # A: Globalne
        g_loads = QGroupBox("1. Obciążenia Globalne")
        g_loads.setFixedHeight(180)
        l_loads = QHBoxLayout()
        f1 = QFormLayout()
        
        self.inp_Fx = QLineEdit("24000.0"); 
        self.inp_Fx.setToolTip("Główna siła osiowa ściskająca słup [N].\nDziała wzdłuż osi X.")
        
        self.inp_L = QLineEdit("1800.0"); 
        self.inp_L.setToolTip("Fizyczna długość słupa [mm] (Wspornik).")
        
        self.inp_Promien = QLineEdit("450.0")
        self.inp_Promien.setToolTip("Ramię działania siły (Mimośród) [mm].\nOdległość punktu przyłożenia siły od osi słupa.\nGeneruje moment zginający Mg = Fx * Ramię.")

        f1.addRow("Fx [N]:", self.inp_Fx); f1.addRow("L [mm]:", self.inp_L); f1.addRow("Ramię [mm]:", self.inp_Promien)
        
        f2 = QFormLayout()
        self.inp_Ty = QLineEdit("0.2"); 
        self.inp_Ty.setToolTip("Współczynnik siły poprzecznej Ty (wzdłuż osi słabej Y).\nFy = Fx * w_Ty.\nPowoduje zginanie względem osi Z.")
        
        self.inp_Tz = QLineEdit("0.2")
        self.inp_Tz.setToolTip("Współczynnik siły poprzecznej Tz (wzdłuż osi mocnej Z).\nFz = Fx * w_Tz.\nDziała na ramieniu, więc powoduje ZGINANIE MY oraz SKRĘCANIE MS!")
        
        self.inp_GM0 = QLineEdit("2.0"); self.inp_GM1 = QLineEdit("2.0"); self.inp_Alfa = QLineEdit("0.49")
        # Tooltipy dla współczynników
        self.inp_GM0.setToolTip("Współczynnik bezpieczeństwa materiałowego Gamma M0 (Nośność przekroju).")
        self.inp_GM1.setToolTip("Współczynnik bezpieczeństwa stateczności Gamma M1 (Wyboczenie).")
        self.inp_Alfa.setToolTip("Parametr imperfekcji (alfa) dla krzywej wyboczeniowej.\n0.49 = Krzywa 'c' (Typowa dla profili spawanych UPE).")

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
        left_layout.addWidget(self.stack)
        # --- [MODYFIKACJA] Ustawienie widgetu w scroll area ---
        left_scroll.setWidget(left_container)
        main_split.addWidget(left_scroll, 6)
        
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
            
            dane["Res_Force_Fy_Ed"] = load['Fx']*load['w_Ty']
            dane["Res_Force_Fz_Ed"] = load['Fx']*load['w_Tz']
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
        if url.toString() == "goto_results": 
            try:
                main_window = self.window()
                main_window.tabs.setCurrentIndex(2)
                if hasattr(self, 'last_res') and self.last_res:
                    if hasattr(main_window, 'tab3'):
                        main_window.tab3.load_csv(self.last_res)
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
        for f in glob.glob("*.pdf")+glob.glob("Baza wiedzy/*")+glob.glob("*.ipynb"):
            i = QListWidgetItem(os.path.basename(f)); i.setData(Qt.ItemDataRole.UserRole, os.path.abspath(f)); self.list.addItem(i)

class Tab3_Selector(QWidget):
    request_transfer = pyqtSignal(list)
    request_transfer_shell = pyqtSignal(list)
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        l = QVBoxLayout(self)
        tb = QHBoxLayout()
        b_load = QPushButton("📂 Wczytaj CSV"); b_load.clicked.connect(lambda: self.load_csv())
        self.chk_sci = QCheckBox("E-notacja"); self.chk_sci.toggled.connect(self.tog_sci)
        b_col = QPushButton("🎨 Kolor"); b_col.clicked.connect(self.col)
        self.b_send_solid = QPushButton("PRZEKAŻ DO SOLID ➡️"); self.b_send_solid.setEnabled(False); self.b_send_solid.clicked.connect(self.send_solid); self.b_send_solid.setStyleSheet("background-color:#2da342;font-weight:bold;")
        self.b_send_shell = QPushButton("PRZEKAŻ DO SHELL ➡️"); self.b_send_shell.setEnabled(False); self.b_send_shell.clicked.connect(self.send_shell); self.b_send_shell.setStyleSheet("background-color:#3498db;font-weight:bold;")

        tb.addWidget(b_load); tb.addWidget(self.chk_sci); tb.addWidget(b_col); tb.addStretch(); tb.addWidget(self.b_send_solid); tb.addWidget(self.b_send_shell); l.addLayout(tb)
        
        spl = QSplitter(); l.addWidget(spl)
        
        ff = QFrame(); ff.setFixedWidth(200); fl = QVBoxLayout(ff)
        sc = QScrollArea(); sc.setWidgetResizable(True); self.w_fil = QWidget(); self.l_fil = QVBoxLayout(self.w_fil); self.l_fil.setAlignment(Qt.AlignmentFlag.AlignTop); sc.setWidget(self.w_fil); fl.addWidget(sc)
        b_af = QPushButton("+ Filtr"); b_af.clicked.connect(self.add_fil); fl.addWidget(b_af)
        b_ap = QPushButton("Zastosuj"); b_ap.clicked.connect(self.apply); fl.addWidget(b_ap)
        
        self.chk_ex = QCheckBox("Pokaż Ukryte")
        self.chk_ex.setChecked(True)
        self.chk_ex.clicked.connect(self.apply) 
        fl.addWidget(self.chk_ex)
        
        fl.addWidget(QLabel("Masowe:")); h=QHBoxLayout(); b1=QPushButton("All P"); b1.clicked.connect(lambda: self.bulk("PRZEKAZ", True)); b2=QPushButton("No P"); b2.clicked.connect(lambda: self.bulk("PRZEKAZ", False)); h.addWidget(b1); h.addWidget(b2); fl.addLayout(h)
        h2=QHBoxLayout(); b3=QPushButton("All W"); b3.clicked.connect(lambda: self.bulk("WYKLUCZ", True)); b4=QPushButton("No W"); b4.clicked.connect(lambda: self.bulk("WYKLUCZ", False)); h2.addWidget(b3); h2.addWidget(b4); fl.addLayout(h2)
        spl.addWidget(ff)
        
        self.tab = QTableView(); self.head = CustomHeaderView(self.tab); self.tab.setHorizontalHeader(self.head); spl.addWidget(self.tab)
        self.det = QTextBrowser(); self.det.setStyleSheet("font-family:Consolas;"); spl.addWidget(self.det)
        spl.setStretchFactor(0, 0)
        spl.setStretchFactor(1, 1)
        spl.setSizes([200, 1200])


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
                self.b_send_solid.setEnabled(True)
                self.b_send_shell.setEnabled(True)
            except Exception as e: QMessageBox.critical(self, "Err", str(e))

    def click(self, c, p):
        self.model.set_highlight(c.row(), c.column())
        r = self.model._df.iloc[c.row()]
        
        # Mapa opisów (dla czytelności w panelu bocznym)
        LMAP = {
            "Nazwa_Profilu":"Profil", "Stop":"Materiał", 
            "Res_Masa_kg_m":"Masa [kg/m]", "Res_UR":"Wytężenie UR", 
            "Status_Wymogow":"Status",
            "Res_Max_VonMises": "Max VonMises [MPa]",
            "Res_Disp_U_y_max": "Ugięcie Y (Słabe) [mm]",
            "Res_Disp_U_z_max": "Ugięcie Z (Mocne) [mm]",
            "Res_Disp_Phi_deg": "Kąt Skręcenia [deg]",
            "Res_Stab_N_cr_gs": "Ncr Giętno-Skrętne [N]"
        }
        
        # Zaktualizowana kolejność wyświetlania
        ORDER = [
            "Status_Wymogow", "Nazwa_Profilu", "Stop", 
            "Res_UR", "Res_Max_VonMises", 
            "Res_Disp_U_y_max", "Res_Disp_U_z_max", "Res_Disp_Phi_deg", # <-- Nowe
            "Res_Masa_kg_m", "Input_Geo_tp", "Input_Geo_bp"
        ]
        
        html = "<h3>Detale Wyniku</h3><table border=0 cellspacing=5>"
        for k in ORDER:
            if k in r:
                val = r[k]
                sv = f"{val:.4f}" if isinstance(val, (float, np.floating)) else str(val)
                col = "#fff"
                if k=="Status_Wymogow": col="#0f0" if val=="SPEŁNIA" else "#ff4444"
                elif k=="Res_UR": col="#0f0" if isinstance(val, (int, float)) and val<=1.0 else "#ff4444"
                
                html += f"<tr><td style='color:#bbb; font-weight:bold;'>{LMAP.get(k,k)}:</td><td style='color:{col}; padding-left:10px;'>{sv}</td></tr>"
        
        html += "<tr><td colspan=2><hr style='border:1px solid #444'></td></tr>"
        for k, v in r.items():
            if k not in ORDER and (str(k).startswith("Input") or str(k).startswith("Calc") or str(k).startswith("Res")):
                sv = f"{v:.4f}" if isinstance(v, (float, np.floating)) else str(v)
                html += f"<tr><td style='color:#888; font-size:10px;'>{k}:</td><td style='font-size:10px;'>{sv}</td></tr>"
        html += "</table>"
        self.det.setHtml(html)

    def send_solid(self):
        if not hasattr(self, 'model'): return
        sel = self.model._df[self.model._df["PRZEKAZ"]==True].to_dict('records')
        if not sel: QMessageBox.warning(self,"Info","Zaznacz profile (PRZEKAZ)."); return
        self.request_transfer.emit(sel)
        QMessageBox.information(self, "OK", f"Przekazano {len(sel)} profili do analizy SOLID.")

    def send_shell(self):
        if not hasattr(self, 'model'): return
        sel = self.model._df[self.model._df["PRZEKAZ"]==True].to_dict('records')
        if not sel: QMessageBox.warning(self,"Info","Zaznacz profile (PRZEKAZ)."); return
        # Nowy sygnał dla Shell
        if hasattr(self, 'request_transfer_shell'):
            self.request_transfer_shell.emit(sel)
            QMessageBox.information(self, "OK", f"Przekazano {len(sel)} profili do analizy SHELL.")

    def tog_sci(self, s): 
        if hasattr(self, 'model'): self.model.set_scientific_notation(s)
    def col(self): 
        c = QColorDialog.getColor()
        if c.isValid(): self.model.colors["bg_highlight"]=c; self.model.layoutChanged.emit()
    def add_fil(self): 
        if hasattr(self, 'avail'): self.l_fil.addWidget(FilterWidget(columns=self.avail))
    def bulk(self, col, v): 
        if hasattr(self, 'model'): self.model.toggle_column_all(col)
    def apply(self):
        if not hasattr(self, 'model'): return
        fs = []
        for i in range(self.l_fil.count()):
            w = self.l_fil.itemAt(i).widget()
            if isinstance(w, FilterWidget):
                try: fs.append((w.combo_col.currentText(), float(w.inp_min.text()) if w.inp_min.text() else None, float(w.inp_max.text()) if w.inp_max.text() else None))
                except: pass
        self.model.apply_advanced_filter(fs, self.chk_ex.isChecked())

class Tab4_Fem(QWidget):
    batch_finished = pyqtSignal() # Nowy sygnał
    pilot_finished = pyqtSignal() # Sygnał po zakończeniu pilota
    profile_started = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.cands = []
        self.last_pilot_data = None
        self.pilot_final_mesh_size = None
        self.notification_popup = None
        self.plotter = None
        self.actors = {}
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.time_start = None
        
        self.init_ui()

    def stop_worker(self):
        if hasattr(self, 'w') and self.w.isRunning():
            self.con.append("<b style='color:orange'>Żądanie przerwania...</b>")
            self.w.request_stop()
            self.btn_stop.setEnabled(False)

    def on_yc_mode_changed(self, btn_id, checked):
        """Obsługuje zmianę trybu dla Y punktu referencyjnego."""
        if not checked:
            return
        
        is_manual = (btn_id == 0)
        self.inp_fem_yc.setDisabled(not is_manual)

        # Jeśli wybrano opcję analityczną i mamy dane, wypełnij pole
        if not is_manual and self.cands:
            cand = self.cands[0]
            if btn_id == 1: # Ramię
                self.inp_fem_yc.setText(f"{cand.get('Input_Load_F_promien', 0.0):.4f}")
            elif btn_id == 2: # Yc
                self.inp_fem_yc.setText(f"{cand.get('Res_Geo_Yc', 0.0):.4f}")

    def init_ui(self):
        # Zmiana na QSplitter dla elastycznego layoutu
        l = QSplitter(Qt.Orientation.Horizontal)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(l)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        w_inp = QWidget()
        l_inp = QVBoxLayout(w_inp)
        l_inp.setSpacing(10)
        l_inp.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        g_par = QGroupBox("1. Parametry Siatki")
        f_par = QFormLayout(g_par)
        
        field_width = 120
        
        # --- NOWOŚĆ: Przełącznik trybu siatkowania ---
        self.combo_mesh_mode = QComboBox()
        self.combo_mesh_mode.addItems(["Bezwzględna (mm)", "Względna (el/grubość)"])
        self.combo_mesh_mode.setFixedWidth(field_width)
        self.combo_mesh_mode.currentIndexChanged.connect(self.update_mesh_input_style)
        
        # Spinbox rozmiaru (zmienne znaczenie)
        self.sp_mesh = QDoubleSpinBox()
        self.sp_mesh.setFixedWidth(field_width)
        # Domyślne ustawienie (zostanie nadpisane przez update_mesh_input_style)
        self.update_mesh_input_style() 
        
        self.sp_fact = QDoubleSpinBox(); self.sp_fact.setValue(0.85); self.sp_fact.setSingleStep(0.1); self.sp_fact.setRange(0.1, 0.99)
        self.sp_fact.setFixedWidth(field_width)
        self.sp_tol = QDoubleSpinBox(); self.sp_tol.setValue(4.0); self.sp_tol.setSuffix(" %")
        self.sp_tol.setFixedWidth(field_width)
        self.sp_iter = QSpinBox(); self.sp_iter.setValue(3); self.sp_iter.setRange(1, 10)
        self.sp_iter.setFixedWidth(field_width)
        self.sp_step = QDoubleSpinBox(); self.sp_step.setValue(50.0); self.sp_step.setRange(10.0, 500.0); self.sp_step.setSuffix(" mm")
        self.sp_step.setFixedWidth(field_width)
        
        f_par.addRow("Tryb rozmiaru:", self.combo_mesh_mode) # <--- DODANO
        f_par.addRow("Wartość startowa:", self.sp_mesh)
        f_par.addRow("Wsp. zagęszczania:", self.sp_fact)
        f_par.addRow("Tolerancja:", self.sp_tol)
        f_par.addRow("Max iteracji:", self.sp_iter)
        f_par.addRow("Krok sondy (X):", self.sp_step)
        
        l_inp.addWidget(g_par)
        
        # --- [NOWOŚĆ] Obciążenia FEM ---
        g_loads_fem = QGroupBox("2. Obciążenia FEM")
        f_loads_fem = QFormLayout(g_loads_fem)

        h_yc_mode = QHBoxLayout()
        self.rb_yc_manual = QRadioButton("Ręcznie")
        self.rb_yc_ramie = QRadioButton("Ramię (z analityki)")
        self.rb_yc_yc = QRadioButton("Środek ciężkości (z analityki)")
        self.yc_mode_group = QButtonGroup(self)
        self.yc_mode_group.addButton(self.rb_yc_manual, 0)
        self.yc_mode_group.addButton(self.rb_yc_ramie, 1)
        self.yc_mode_group.addButton(self.rb_yc_yc, 2)
        h_yc_mode.addWidget(self.rb_yc_manual); h_yc_mode.addWidget(self.rb_yc_ramie); h_yc_mode.addWidget(self.rb_yc_yc)
        h_yc_mode.addStretch()

        self.inp_fem_yc = QLineEdit()
        self.inp_fem_yc.setFixedWidth(field_width)
        f_loads_fem.addRow("Źródło Y punktu ref.:", h_yc_mode)
        f_loads_fem.addRow("Wartość Y [mm]:", self.inp_fem_yc)

        h_fx = QHBoxLayout()
        self.inp_fem_fx = QLineEdit(); self.chk_fem_fx = QCheckBox("Z analityki"); self.chk_fem_fx.setChecked(True)
        self.inp_fem_fx.setFixedWidth(field_width)
        h_fx.addWidget(self.inp_fem_fx); h_fx.addWidget(self.chk_fem_fx)
        f_loads_fem.addRow("Siła Fx [N] (CCX):", h_fx)
        self.inp_fem_fx.setToolTip("Konwencja CalculiX: wartość ujemna = ściskanie.")

        h_fy = QHBoxLayout(); self.inp_fem_fy = QLineEdit(); self.chk_fem_fy = QCheckBox("Z analityki"); self.chk_fem_fy.setChecked(True)
        self.inp_fem_fy.setFixedWidth(field_width)
        h_fy.addWidget(self.inp_fem_fy); h_fy.addWidget(self.chk_fem_fy)
        f_loads_fem.addRow("Siła Fy [N]:", h_fy)

        h_fz = QHBoxLayout(); self.inp_fem_fz = QLineEdit(); self.chk_fem_fz = QCheckBox("Z analityki"); self.chk_fem_fz.setChecked(True)
        self.inp_fem_fz.setFixedWidth(field_width)
        h_fz.addWidget(self.inp_fem_fz); h_fz.addWidget(self.chk_fem_fz)
        f_loads_fem.addRow("Siła Fz [N]:", h_fz)

        self.inp_fem_mx = QLineEdit("0"); self.inp_fem_mx.setFixedWidth(field_width)
        self.inp_fem_my = QLineEdit("0"); self.inp_fem_my.setFixedWidth(field_width)
        self.inp_fem_mz = QLineEdit("0"); self.inp_fem_mz.setFixedWidth(field_width)
        self.inp_fem_mx.setToolTip("Moment skręcający (wokół X)."); self.inp_fem_my.setToolTip("Moment zginający (wokół Y)."); self.inp_fem_mz.setToolTip("Moment zginający (wokół Z).")
        f_loads_fem.addRow("Moment Mx [Nmm]:", self.inp_fem_mx)
        f_loads_fem.addRow("Moment My [Nmm]:", self.inp_fem_my)
        f_loads_fem.addRow("Moment Mz [Nmm]:", self.inp_fem_mz)

        g_vars_fem = QGroupBox("3. Zmienne w wyrażeniach")
        l_vars_fem = QVBoxLayout(g_vars_fem)
        vars_text = """<p style="font-size:10px; margin:0;">Dostępne zmienne w polach momentów:</p>
        <ul style="font-size:10px; margin:0; padding-left:15px; list-style-type:square;">
            <li><b>Fx, Fy, Fz</b>: Siły z pól powyżej [N]</li>
            <li><b>L</b>: Długość belki [mm]</li>
            <li><b>Yc</b>: Y środka ciężkości (z analityki) [mm]</li>
            <li><b>Ys</b>: Y środka ścinania (z analityki) [mm]</li>
            <li><b>Y_ref</b>: Y punktu referencyjnego (z pola) [mm]</li>
        </ul>"""
        lbl_vars = QLabel(vars_text); lbl_vars.setWordWrap(True)
        l_vars_fem.addWidget(lbl_vars)

        g_zones = QGroupBox("4. Strefy Zagęszczania")
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
        hz.addWidget(b_zadd); hz.addWidget(b_zdel); hz.addStretch()
        l_zones.addLayout(hz)

        g_sys = QGroupBox("5. Zasoby")
        f_sys = QFormLayout(g_sys)
        self.combo_ord = QComboBox(); self.combo_ord.addItems(["Order 1", "Order 2"]); self.combo_ord.setCurrentIndex(0)
        self.combo_ord.setFixedWidth(field_width)
        self.sp_cores_mesh = QSpinBox(); self.sp_cores_mesh.setRange(1, 128); self.sp_cores_mesh.setValue(20)
        self.sp_cores_mesh.setFixedWidth(field_width)
        self.sp_cores_ccx = QSpinBox(); self.sp_cores_ccx.setRange(1, 128); self.sp_cores_ccx.setValue(20)
        self.sp_cores_ccx.setFixedWidth(field_width)
        self.sp_eq_limit = QSpinBox(); self.sp_eq_limit.setRange(100000, 10000000); self.sp_eq_limit.setValue(2000000)
        self.sp_eq_limit.setSingleStep(100000)
        self.sp_eq_limit.setToolTip("Limit równań, po którym nastąpi automatyczne przełączenie na solver iteracyjny.")
        self.sp_eq_limit.setFixedWidth(field_width)

        f_sys.addRow("Rząd:", self.combo_ord)
        f_sys.addRow("Rdzenie (M/S):", self.sp_cores_mesh)
        f_sys.addRow("Rdzenie (Solver):", self.sp_cores_ccx)
        f_sys.addRow("Limit równań:", self.sp_eq_limit)

        g_prob = QGroupBox("6. Punkty Pomiarowe (Sondy)")
        l_prob = QVBoxLayout(g_prob)
        self.tbl_prob = QTableWidget(0, 3)
        self.tbl_prob.setHorizontalHeaderLabels(["Nazwa", "Formuła Y", "Formuła Z"])
        self.tbl_prob.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_prob.setFixedHeight(100)
        l_prob.addWidget(self.tbl_prob)
        hp = QHBoxLayout()
        b_padd = QPushButton("+"); b_padd.setFixedSize(30, 25); b_padd.clicked.connect(self.add_probe_row)
        b_pdel = QPushButton("-"); b_pdel.setFixedSize(30, 25); b_pdel.clicked.connect(self.del_probe_row)
        hp.addWidget(b_padd); hp.addWidget(b_pdel); hp.addStretch()
        l_prob.addLayout(hp)
        self.add_probe_row("User_Center", "0", "0")

        # Dodawanie widgetów do lewego panelu w poprawnej kolejności
        l_inp.addWidget(g_loads_fem)
        l_inp.addWidget(g_vars_fem)
        l_inp.addWidget(g_zones)
        l_inp.addWidget(g_sys)
        l_inp.addWidget(g_prob)

        scroll.setWidget(w_inp)
        l.addWidget(scroll) # Dodanie do splittera

        # --- PRAWY PANEL (WYNIKI) ---
        # --- [MODYFIKACJA] Dodanie QScrollArea dla prawego panelu ---
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        # ----------------------------------------------------------

        w_res = QWidget()
        l_res = QVBoxLayout(w_res)
        
        f_ctrl = QFrame(); f_ctrl.setStyleSheet("background:#2a2a2a; border-radius:5px;")
        l_ctrl = QVBoxLayout(f_ctrl)
        h_pilot = QHBoxLayout()
        self.btn_pilot = QPushButton("1. URUCHOM PILOTA")
        self.btn_pilot.setStyleSheet("background-color:#d35400; font-weight:bold; padding:8px;")
        self.btn_pilot.clicked.connect(self.run_pilot)
        self.btn_pilot.setEnabled(False)
        
        self.btn_stop = QPushButton("🛑 PRZERWIJ")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_worker)
        self.btn_stop.setStyleSheet("background-color:#c0392b; font-weight:bold; padding:8px;")
        self.btn_stop.setToolTip("Bezpiecznie przerywa aktualnie trwające obliczenia.")
        
        h_pilot.addWidget(self.btn_pilot); h_pilot.addWidget(self.btn_stop)
        l_ctrl.addLayout(h_pilot)
        
        self.btn_batch = QPushButton("2. URUCHOM PEŁNY BATCH")
        self.btn_batch.setStyleSheet("background-color:#27ae60; font-weight:bold; padding:8px;")
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self.run_batch)
        l_ctrl.addWidget(self.btn_batch)
        l_res.addWidget(f_ctrl)
        
        splitter_vis = QSplitter(Qt.Orientation.Horizontal)
        self.frame_3d = QFrame()
        if HAS_PYVISTA:
            l_3d = QVBoxLayout(self.frame_3d); l_3d.setContentsMargins(0,0,0,0)
            self.plotter = QtInteractor(self.frame_3d)
            self.plotter.set_background("#303030")
            l_3d.addWidget(self.plotter.interactor)
        else:
            l_3d = QVBoxLayout(self.frame_3d); l_3d.addWidget(QLabel("Brak PyVista"))
        splitter_vis.addWidget(self.frame_3d)
        
        self.tree_vis = QTreeWidget()
        self.tree_vis.setHeaderLabel("Elementy Sceny")
        self.tree_vis.setFixedWidth(200)
        self.tree_vis.itemChanged.connect(self.on_tree_item_changed)
        splitter_vis.addWidget(self.tree_vis)
        splitter_vis.setStretchFactor(0, 4); splitter_vis.setStretchFactor(1, 1)
        l_res.addWidget(splitter_vis, stretch=4)

        self.tbl_res = QTableWidget(0, 4)
        self.tbl_res.setHorizontalHeaderLabels(["Profil", "Iter", "Conv", "Max VM"])
        self.tbl_res.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_res.setFixedHeight(120)
        l_res.addWidget(self.tbl_res)
        
        splitter_logs = QSplitter(Qt.Orientation.Horizontal)
        self.con = QTextBrowser()
        self.con.setStyleSheet("font-family:Consolas; font-size:10px; background:#111; color:#0f0;")
        splitter_logs.addWidget(self.con)
        
        self.status_panel = self.create_status_panel()
        splitter_logs.addWidget(self.status_panel)
        
        splitter_logs.setStretchFactor(0, 2); splitter_logs.setStretchFactor(1, 1)
        splitter_logs.setFixedHeight(180)
        
        l_res.addWidget(splitter_logs)
        l.addWidget(w_res) # Dodanie do splittera
        # --- [MODYFIKACJA] Ustawienie widgetu w scroll area ---
        right_scroll.setWidget(w_res)
        l.addWidget(right_scroll) # Dodanie do splittera
        # ----------------------------------------------------

        # Ustawienie domyślnych proporcji splittera
        l.setSizes([380, 970])

        # Połączenia dla nowych kontrolek
        self.yc_mode_group.idToggled.connect(self.on_yc_mode_changed)
        self.chk_fem_fx.toggled.connect(lambda checked: self.inp_fem_fx.setDisabled(checked))
        self.chk_fem_fy.toggled.connect(lambda checked: self.inp_fem_fy.setDisabled(checked))
        self.chk_fem_fz.toggled.connect(lambda checked: self.inp_fem_fz.setDisabled(checked))
        
        self.rb_yc_ramie.setChecked(True)
        self.inp_fem_fx.setDisabled(True)
        self.inp_fem_fy.setDisabled(True)
        self.inp_fem_fz.setDisabled(True)

    def create_status_panel(self):
        w = QGroupBox("Status Symulacji (Live)")
        w.setStyleSheet("""
            QGroupBox { border: 1px solid #555; background: #222; font-weight: bold; color: #aaa; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel { color: #ddd; font-size: 11px; }
            QLabel#val { color: #fff; font-weight: bold; font-size: 12px; }
        """)
        lay = QFormLayout(w)
        lay.setSpacing(5)
        
        self.lbl_status_step = QLabel("-")
        self.lbl_status_nodes = QLabel("-")
        self.lbl_status_eq = QLabel("-")
        self.lbl_status_ram = QLabel("-")
        self.lbl_status_time = QLabel("00:00")
        
        for l in [self.lbl_status_step, self.lbl_status_nodes, self.lbl_status_eq, self.lbl_status_ram, self.lbl_status_time]:
            l.setObjectName("val")

        lay.addRow("Aktualny Krok:", self.lbl_status_step)
        lay.addRow("Węzły Siatki:", self.lbl_status_nodes)
        lay.addRow("Układ Równań:", self.lbl_status_eq)
        lay.addRow("Est. Pamięć RAM:", self.lbl_status_ram)
        lay.addRow("Czas Trwania:", self.lbl_status_time)
        return w

    def update_mesh_input_style(self):
        """Aktualizuje wygląd pola rozmiaru siatki w zależności od trybu."""
        
        # ### NOWOŚĆ: Resetujemy wynik pilota ###
        self.pilot_final_mesh_size = None 
        
        # --- POPRAWKA (Fix błędu startowego) ---
        # Sprawdzamy czy przyciski zostały już utworzone przez init_ui.
        # Przy starcie programu ta funkcja jest wołana zanim przyciski powstaną.
        # [ZMIANA] Usunięto blokowanie przycisku Batch. Teraz można uruchomić batch
        # bez wcześniejszego pilota, używając ustawień z GUI.
        # Przycisk pilota jest zarządzany przez receive_data.

        if hasattr(self, 'con'):
            # To też warto zabezpieczyć, żeby nie spamować konsoli przy starcie
            if hasattr(self, 'btn_batch'): 
                self.con.append("<i style='color:gray'>Zmieniono tryb siatki. Poprzedni wynik pilota został wyczyszczony.</i>")

        if self.combo_mesh_mode.currentIndex() == 0: 
            # Tryb Absolutny (mm)
            self.sp_mesh.setSuffix(" mm")
            self.sp_mesh.setRange(1.0, 100.0)
            self.sp_mesh.setValue(15.0)
            self.sp_mesh.setToolTip("Globalny, startowy rozmiar elementu w milimetrach.")
            self.sp_mesh.setSingleStep(1.0)
        else: 
            # Tryb Względny (elementy na grubość)
            self.sp_mesh.setSuffix(" el/gr")
            self.sp_mesh.setRange(0.5, 10.0)
            self.sp_mesh.setValue(1.0) # Domyślnie 1 element na grubość
            self.sp_mesh.setToolTip("Liczba elementów przypadająca na grubość najcieńszej ścianki.\n"
                                    "Np. 2.0 oznacza, że rozmiar elementu będzie połową grubości ścianki.\n"
                                    "Wartość ta jest startowa i będzie zagęszczana w kolejnych iteracjach.")
            self.sp_mesh.setSingleStep(0.5)
    
    def reset_status_panel(self):
        self.lbl_status_step.setText("Oczekiwanie...")
        self.lbl_status_nodes.setText("-")
        self.lbl_status_eq.setText("-")
        self.lbl_status_ram.setText("-")
        self.lbl_status_time.setText("00:00")
        self.lbl_status_step.setStyleSheet("color: #fff")

    def update_timer(self):
        if self.time_start:
            elapsed = self.time_start.secsTo(QTime.currentTime())
            m, s = divmod(elapsed, 60)
            self.lbl_status_time.setText(f"{m:02d}:{s:02d}")

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
        """Odbiera dane z Tab 3 i ładuje je do pamięci Tab 4."""
        self.cands = d
        self.con.clear()
        self.tbl_res.setRowCount(0)
        self.con.append(f"Załadowano {len(d)} kandydatów. Uruchom Pilota lub Pełny Batch.")
        
        # Wstępne wypełnienie tabeli profili do przetworzenia
        self.tbl_res.setRowCount(len(d))
        for i, cand in enumerate(d):
            prof_name = cand.get('Nazwa_Profilu', 'Unknown')
            tp = float(cand.get("Input_Geo_tp", 10))
            bp = float(cand.get("Input_Geo_bp", 0))
            cid = f"{prof_name}_tp{int(tp)}_bp{int(bp)}"
            
            item_prof = QTableWidgetItem(cid)
            item_prof.setData(Qt.ItemDataRole.UserRole, cid)
            self.tbl_res.setItem(i, 0, item_prof)
            for j in range(1, 4):
                self.tbl_res.setItem(i, j, QTableWidgetItem("-"))
        
        # Aktywacja przycisków
        self.btn_pilot.setEnabled(True)
        self.btn_batch.setEnabled(True) # Od razu aktywujemy Batch

        if d:
            c = d[0]
            # Ręczne wywołanie aktualizacji Y_ref na podstawie domyślnego radio
            self.on_yc_mode_changed(self.yc_mode_group.checkedId(), True)

            # Wypełnienie pól obciążeń FEM wartościami z analityki
            ana_fx = float(c.get('Input_Load_Fx', 0.0))
            self.inp_fem_fx.setText(f"{-ana_fx:.1f}") # Konwersja na konwencję CCX (ujemne ściskanie)
            self.inp_fem_fy.setText(f"{c.get('Res_Force_Fy_Ed', 0.0):.1f}")
            self.inp_fem_fz.setText(f"{c.get('Res_Force_Fz_Ed', 0.0):.1f}")        

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

        # Pobieranie trybu
        mode_str = "absolute" if self.combo_mesh_mode.currentIndex() == 0 else "relative"

        fem_loads = {
            "yc_ref_mode": self.yc_mode_group.checkedId(),
            "yc_ref_manual_value": self.inp_fem_yc.text(),
            "fx": {"use_ana": self.chk_fem_fx.isChecked(), "value": self.inp_fem_fx.text()},
            "fy": {"use_ana": self.chk_fem_fy.isChecked(), "value": self.inp_fem_fy.text()},
            "fz": {"use_ana": self.chk_fem_fz.isChecked(), "value": self.inp_fem_fz.text()},
            "mx_expr": self.inp_fem_mx.text(),
            "my_expr": self.inp_fem_my.text(),
            "mz_expr": self.inp_fem_mz.text(),
        }

        return {
            "mesh_mode": mode_str,  # <--- NOWY KLUCZ
            "mesh_start_size": self.sp_mesh.value(), # Wartość w mm LUB mnożnik gęstości
            "refinement_factor": self.sp_fact.value(),
            "tolerance": self.sp_tol.value()/100.0,
            "max_iterations": self.sp_iter.value(),
            "mesh_order": 2 if self.combo_ord.currentIndex() == 1 else 1,
            "refinement_zones": zones, # zdefiniowane wcześniej w metodzie
            "custom_probes": probes,   # zdefiniowane wcześniej w metodzie
            "cores_mesh": self.sp_cores_mesh.value(),
            "cores_solver": self.sp_cores_ccx.value(),
            "eq_limit": self.sp_eq_limit.value(),
            "fem_loads": fem_loads,    # zdefiniowane wcześniej w metodzie
            "step": self.sp_step.value()
        }

    def validate_and_get_candidates(self):
        """
        Iteruje po kandydatach, sprawdza właściwości materiałowe i pyta użytkownika, jeśli ich brakuje.
        Zwraca listę poprawnych, zaktualizowanych kandydatów lub pustą listę.
        """
        if not self.cands:
            return []

        validated_candidates = []
        for cand in self.cands:
            e_mod = cand.get("Input_Load_E")
            g_mod = cand.get("Input_Load_G")

            is_valid = False
            try:
                e_mod_f = float(e_mod)
                g_mod_f = float(g_mod)
                if e_mod_f > 0 and g_mod_f > 0:
                    is_valid = True
            except (ValueError, TypeError):
                is_valid = False

            if not is_valid:
                material_name = cand.get("Stop", "Nieznany")
                dialog = MaterialInputDialog(material_name, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    new_e, new_g = dialog.get_values()
                    if new_e is not None and new_g is not None:
                        cand["Input_Load_E"] = new_e
                        cand["Input_Load_G"] = new_g
                        self.con.append(f"INFO: Ręcznie wprowadzono dane dla '{material_name}': E={new_e}, G={new_g}")
                        validated_candidates.append(cand)
                    else:
                        QMessageBox.warning(self, "Błąd", "Wprowadzono nieprawidłowe wartości liczbowe. Profil zostanie pominięty.")
                        self.con.append(f"WARN: Pominięto profil '{material_name}' z powodu nieprawidłowych danych.")
                else:
                    self.con.append(f"INFO: Anulowano przetwarzanie profilu '{material_name}'.")
            else:
                validated_candidates.append(cand)
        
        return validated_candidates

    def process_log_message(self, msg):
        msg = msg.strip()
        if not msg: return

        log_content = msg
        
        if "|||" in msg:
            parts = msg.split("|||")
            log_content = parts[0].strip()
            
            if len(parts) > 1:
                extra = parts[1].strip().replace('[', '').replace(']', '')
                if ":" in extra:
                    key, val = extra.split(":", 1)
                    key = key.strip().lower(); val = val.strip()
                    
                    if "status" in key:
                        self.lbl_status_step.setText(val)
                        if "błąd" in val.lower() or "przerwano" in val.lower(): self.lbl_status_step.setStyleSheet("color: #e74c3c")
                        elif "solver" in val.lower(): self.lbl_status_step.setStyleSheet("color: #f1c40f")
                        elif "siatki" in val.lower(): self.lbl_status_step.setStyleSheet("color: #3498db")
                        else: self.lbl_status_step.setStyleSheet("color: #fff")
                    elif "węzły" in key: self.lbl_status_nodes.setText(val)
                    elif "równań" in key: self.lbl_status_eq.setText(val)
                    elif "ram" in key: self.lbl_status_ram.setText(val)
        else:
            l_msg = msg.lower()
            if "equation system has" in l_msg:
                try:
                    eq_count_str = l_msg.split("has")[1].split("equations")[0].strip()
                    eq_count = int(eq_count_str)
                    self.lbl_status_eq.setText(f"{eq_count:,}".replace(',', ' '))
                    ram_est_gb = eq_count * 1.2 / 1e6 
                    self.lbl_status_ram.setText(f"~{ram_est_gb:.2f} GB")
                except: pass
            elif "calculating stiffness" in l_msg:
                self.lbl_status_step.setText("Obliczanie macierzy sztywności..."); self.lbl_status_step.setStyleSheet("color: #9b59b6")
            elif "buckling factor" in l_msg:
                self.lbl_status_step.setText("Analiza wyboczenia..."); self.lbl_status_step.setStyleSheet("color: #3498db")
            elif "job finished" in l_msg:
                self.lbl_status_step.setText("Solver zakończył pracę."); self.lbl_status_step.setStyleSheet("color: #2ecc71")

        if log_content: self.con.append(log_content)

    def run_pilot(self):
        if not self.cands: return
        self.con.clear(); self.con.append("=== START PILOTA ===")
        self.pilot_final_mesh_size = None # Reset ustawień z poprzedniego pilota
        
        validated_cands = self.validate_and_get_candidates()
        if not validated_cands:
            self.con.append("Brak poprawnych kandydatów do uruchomienia.")
            self.btn_pilot.setEnabled(True)
            return

        self.reset_status_panel()
        self.time_start = QTime.currentTime()
        self.timer.start(1000)
        
        sets = self.get_settings()
        self.w = FemWorker([validated_cands[0]], sets)
        self.w.processing_signal.connect(self.profile_started)
        self.w.notification_signal.connect(self.show_notification)
        self.w.log_signal.connect(self.process_log_message)
        self.w.data_signal.connect(self.on_worker_data)
        self.w.finished_signal.connect(self.on_pilot_done)
        self.btn_pilot.setEnabled(False); self.btn_stop.setEnabled(True)
        self.w.start()

    def on_worker_data(self, data):
        self.last_pilot_data = data
        if 'mesh_path' in data and data['mesh_path'] and HAS_PYVISTA:
            self.show_mesh()

        cid_to_update = data.get('id')
        if not cid_to_update:
            # Fallback - jeśli coś pójdzie nie tak, dodaj na końcu
            r = self.tbl_res.rowCount(); self.tbl_res.insertRow(r)
            self.tbl_res.setItem(r, 0, QTableWidgetItem(data.get('profile_name', '')))
            self.tbl_res.setItem(r, 1, QTableWidgetItem(str(data.get('iterations', 0))))
            self.tbl_res.setItem(r, 2, QTableWidgetItem("TAK" if data.get('converged') else "NIE"))
            self.tbl_res.setItem(r, 3, QTableWidgetItem(f"{data.get('final_stress',0):.2f}"))
            return

        for r in range(self.tbl_res.rowCount()):
            item = self.tbl_res.item(r, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == cid_to_update:
                self.tbl_res.setItem(r, 1, QTableWidgetItem(str(data.get('iterations', 0))))
                c_status = data.get('converged')
                if c_status == "NOT_DEFINED":
                    conv_item = QTableWidgetItem("BATCH")
                    conv_item.setBackground(QColor(100, 100, 50))
                elif c_status == "IMPORTED":
                    conv_item = QTableWidgetItem("IMPORT")
                    conv_item.setBackground(QColor(50, 100, 100))
                else:
                    conv_item = QTableWidgetItem("TAK" if c_status else "NIE")
                    conv_item.setBackground(QColor(50, 100, 50) if c_status else QColor(100, 50, 50))
                self.tbl_res.setItem(r, 2, conv_item)
                self.tbl_res.setItem(r, 3, QTableWidgetItem(f"{data.get('final_stress',0):.2f}"))
                self.tbl_res.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    def _get_candidate_thickness(self, cand):
        """Pomocnicza funkcja do wyznaczania grubości krytycznej kandydata (dla GUI)."""
        thicknesses = []
        # Pobieramy te same klucze co w fem_optimizer
        if 'Input_UPE_twc' in cand: thicknesses.append(float(cand['Input_UPE_twc']))
        if 'Input_UPE_tfc' in cand: thicknesses.append(float(cand['Input_UPE_tfc']))
        if 'Input_Geo_tp' in cand: thicknesses.append(float(cand['Input_Geo_tp']))
        return min(thicknesses) if thicknesses else 10.0

    def on_pilot_done(self):
        self.timer.stop()
        self.lbl_status_step.setText("ZAKOŃCZONO")
        self.lbl_status_step.setStyleSheet("color: #2ecc71")
        self.btn_pilot.setEnabled(True); self.btn_stop.setEnabled(False)
        self.btn_batch.setEnabled(True)
        self.con.append("Pilot zakończony.")

        # [ZMIANA] Emituj sygnał po zakończeniu pilota, aby odświeżyć wyniki
        self.pilot_finished.emit()
        # --- INTELIGENTNE PRZEKAZANIE WYNIKÓW PILOTA DO BATCHA ---
        if self.last_pilot_data and self.last_pilot_data.get('converged'):
            final_mesh_size_mm = self.last_pilot_data.get('final_mesh_size')
            
            if final_mesh_size_mm:
                mode = "relative" if self.combo_mesh_mode.currentIndex() == 1 else "absolute"
                
                if mode == "absolute":
                    # Tryb Bezwzględny: Przekazujemy wymiar w mm
                    self.pilot_final_mesh_size = final_mesh_size_mm
                    self.con.append(f"<b>[INFO] Pilot (Abs): Ustawiono start Batcha na {final_mesh_size_mm:.2f} mm</b>")
                
                else:
                    # Tryb Względny: Musimy odtworzyć GĘSTOŚĆ (elementy na grubość)
                    # Density = Grubość_Pilota / Siatka_Pilota
                    
                    # 1. Znajdź kandydata pilota (zazwyczaj pierwszy na liście)
                    # W idealnym świecie ID w last_pilot_data pozwoliłoby go znaleźć, 
                    # ale tutaj założymy, że pilotem był self.candidates[0].
                    if self.candidates:
                        pilot_cand = self.candidates[0]
                        min_t = self._get_candidate_thickness(pilot_cand)
                        
                        # Obliczamy zagęszczenie jakie osiągnął pilot
                        # np. Grubość 4.5mm / Siatka 4.27mm = 1.05 el/grubość
                        optimized_density = min_t / final_mesh_size_mm
                        
                        self.pilot_final_mesh_size = optimized_density
                        self.con.append(f"<b>[INFO] Pilot (Rel): Grubość {min_t}mm -> Siatka {final_mesh_size_mm:.2f}mm</b>")
                        self.con.append(f"<b>[INFO] Ustawiono start Batcha na gęstość: {optimized_density:.2f} el/grubość</b>")
                    else:
                        self.con.append("Błąd: Nie można wyznaczyć gęstości względnej (brak danych kandydata).")

    def run_batch(self):
        if not self.cands: return
        self.con.append("\n=== START BATCH ===")
        
        validated_cands = self.validate_and_get_candidates()
        if not validated_cands:
            self.con.append("Brak poprawnych kandydatów do uruchomienia.")
            self.btn_batch.setEnabled(True); self.btn_pilot.setEnabled(True)
            return

        self.reset_status_panel()
        self.time_start = QTime.currentTime()
        self.timer.start(1000)
        
        sets = self.get_settings()

        # Logika dla trybu BATCH:
        if self.pilot_final_mesh_size is not None:
            mode = "relative" if self.combo_mesh_mode.currentIndex() == 1 else "absolute"
            unit = "el/gr" if mode == "relative" else "mm"
            
            self.con.append(f"<b>[INFO] Batch używa zoptymalizowanego parametru z pilota: {self.pilot_final_mesh_size:.2f} {unit}</b>")
            
            # Nadpisujemy parametr startowy. 
            # W trybie relative 'mesh_start_size' to gęstość, w absolute to mm.
            # Dzięki logice w on_pilot_done, self.pilot_final_mesh_size ma już poprawną jednostkę.
            sets['mesh_start_size'] = self.pilot_final_mesh_size
        else:
            self.con.append("<b>[INFO] Używam ustawień z GUI (bez optymalizacji z pilota)...</b>")
        
        # Batch zawsze wykonuje 1 iterację na profil (zakładamy, że parametry z pilota są wystarczające)
        sets['max_iterations'] = 1

        self.w = FemWorker(validated_cands, sets)
        self.w.processing_signal.connect(self.profile_started)
        self.w.notification_signal.connect(self.show_notification)
        self.w.log_signal.connect(self.process_log_message)
        self.w.data_signal.connect(self.on_worker_data)
        self.w.finished_signal.connect(self.on_batch_done)
        self.btn_batch.setEnabled(False); self.btn_pilot.setEnabled(False); self.btn_stop.setEnabled(True)
        self.w.start()

    def on_batch_done(self):
        self.timer.stop()
        self.lbl_status_step.setText("ZAKOŃCZONO BATCH")
        self.lbl_status_step.setStyleSheet("color: #2ecc71")
        self.con.append("=== BATCH ZAKOŃCZONY ===")
        self.btn_batch.setEnabled(True); self.btn_pilot.setEnabled(True); self.btn_stop.setEnabled(False)
        self.batch_finished.emit()

    @pyqtSlot(str, str)
    def show_notification(self, title, text):
        """Wyświetla nieblokujące okno z informacją."""
        self.notification_popup = QMessageBox(self)
        self.notification_popup.setIcon(QMessageBox.Icon.Information)
        self.notification_popup.setWindowTitle(title)
        self.notification_popup.setText(text)
        self.notification_popup.setStandardButtons(QMessageBox.StandardButton.Ok)
        self.notification_popup.setModal(False)
        self.notification_popup.show()

    def show_mesh(self):
        if not HAS_PYVISTA: return
        if not self.last_pilot_data: return
        mesh_path = self.last_pilot_data.get('mesh_path')
        if not mesh_path or not os.path.exists(mesh_path): return
        
        self.plotter.clear(); self.tree_vis.clear(); self.actors = {}
        try:
            mesh = pv.read(mesh_path)
            # Zapisujemy długość belki z siatki jako fallback
            self.beam_length_from_mesh = mesh.bounds[1]
            act = self.plotter.add_mesh(mesh, show_edges=True, color="lightblue", edge_color="black", opacity=0.3)
            self.add_tree_item("Siatka FEM", "mesh_main", act, True)
        except Exception as e: self.con.append(f"Błąd siatki: {e}")

        work_dir = os.path.dirname(mesh_path)
        base_name = os.path.splitext(os.path.basename(mesh_path))[0]
        groups_path = os.path.join(work_dir, f"{base_name}_groups.json")
        analytical_json_path = os.path.join(work_dir, "analytical.json")
        
        if os.path.exists(analytical_json_path):
            try:
                with open(analytical_json_path, 'r') as f: ana_data = json.load(f)
                
                ys = ana_data.get("Res_Geo_Ys", 0.0)
                yc = ana_data.get("Res_Geo_Yc", 0.0)
                # Fallback dla starszych plików, które nie miały bezpośrednio 'Res_Geo_Yc'
                if yc == 0.0 and "Res_Geo_Delta_Ys" in ana_data:
                    d_ys = ana_data.get("Res_Geo_Delta_Ys", 0.0)
                    yc = ys + d_ys

                p_yc = pv.Sphere(radius=5, center=(0, yc, 0))
                act_yc = self.plotter.add_mesh(p_yc, color="red", label="Yc")
                self.add_tree_item("Środek Ciężkości (Yc)", "pt_yc", act_yc, True)
                
                p_ys = pv.Sphere(radius=5, center=(0, ys, 0))
                act_ys = self.plotter.add_mesh(p_ys, color="green", label="Ys")
                self.add_tree_item("Środek Ścinania (Ys)", "pt_ys", act_ys, True)

                # --- WIZUALIZACJA SIŁ ---
                # --- [POPRAWKA] DYNAMICZNA WIZUALIZACJA SIŁ Z GUI ---
                # Pobieramy aktualne ustawienia z GUI, a nie ze statycznego pliku
                settings = self.get_settings()
                fem_loads = settings.get("fem_loads", {})
                
                # Długość belki z danych analitycznych
                L = float(ana_data.get("Input_Load_L", self.beam_length_from_mesh))
                F_promien = float(ana_data.get("Input_Load_F_promien", 0))
                Fx = float(ana_data.get("Input_Load_Fx", 0))
                w_Ty = float(ana_data.get("Input_Load_w_Ty", 0))
                w_Tz = float(ana_data.get("Input_Load_w_Tz", 0))
                
                Fy = Fx * w_Ty
                Fz = Fx * w_Tz
                # Położenie Y punktu referencyjnego z GUI
                try:
                    y_ref_val = float(fem_loads.get("yc_ref_manual_value", "0.0"))
                except ValueError:
                    y_ref_val = 0.0

                # Siły z GUI (pamiętając o konwencji CCX dla Fx)
                try: Fx = float(fem_loads.get("fx", {}).get("value", "0.0"))
                except ValueError: Fx = 0.0
                try: Fy = float(fem_loads.get("fy", {}).get("value", "0.0"))
                except ValueError: Fy = 0.0
                try: Fz = float(fem_loads.get("fz", {}).get("value", "0.0"))
                except ValueError: Fz = 0.0

                if L > 0 and abs(Fx) > 1e-6:
                    load_point = np.array([L, F_promien, 0])
                    load_point = np.array([L, y_ref_val, 0])
                    
                    p_load = pv.Sphere(radius=max(5, L/400), center=load_point)
                    act_load_pt = self.plotter.add_mesh(p_load, color="cyan", label="Load Point")
                    self.add_tree_item("Punkt Przyłożenia Siły", "pt_load", act_load_pt, True)

                    forces = {
                        "Fx": {"vec": np.array([-1, 0, 0]), "mag": abs(Fx), "color": "red"},
                        "Fy": {"vec": np.array([0, 1, 0]), "mag": abs(Fy), "color": "green"},
                        "Fy": {"vec": np.array([0, 1, 0]), "mag": Fy, "color": "green"},
                        "Fz": {"vec": np.array([0, 0, 1]), "mag": abs(Fz), "color": "blue"},
                    }
                    
                    arrow_base_length = L * 0.15
                    max_force_mag = max(f["mag"] for f in forces.values())

                    if max_force_mag > 1e-6:
                        parent_force = QTreeWidgetItem(self.tree_vis, ["Wektory Sił"])
                        parent_force.setCheckState(0, Qt.CheckState.Checked)
                        self.tree_vis.expandItem(parent_force)
                        for name, f_data in forces.items():
                            if f_data["mag"] > 1e-6:
                                arrow_len = (f_data["mag"] / max_force_mag) * arrow_base_length
                                arrow_geom = pv.Arrow(start=load_point, direction=f_data["vec"], scale=arrow_len, shaft_radius=0.02 * arrow_len, tip_length=0.2 * arrow_len)
                                # Dla Fy, kierunek zależy od znaku
                                direction = f_data["vec"] if name != "Fy" else np.sign(f_data["mag"]) * f_data["vec"]
                                
                                arrow_geom = pv.Arrow(start=load_point, direction=direction, scale=arrow_len, shaft_radius=0.02 * arrow_len, tip_length=0.2 * arrow_len)
                                actor = self.plotter.add_mesh(arrow_geom, color=f_data["color"])
                                item = QTreeWidgetItem(parent_force, [name])
                                item.setCheckState(0, Qt.CheckState.Checked)
                                self.actors[id(item)] = actor
            except Exception as e: self.con.append(f"Błąd wizualizacji Yc/Ys: {e}")

        if os.path.exists(groups_path):
            try:
                with open(groups_path, 'r') as f: groups = json.load(f)
                nodes_csv = groups_path.replace("_groups.json", "_nodes.csv")
                if os.path.exists(nodes_csv):
                    import pandas as pd
                    df_nodes = pd.read_csv(nodes_csv)
                    node_map = {row['NodeID']: [row['X'], row['Y'], row['Z']] for _, row in df_nodes.iterrows()}
                    parent_gr = QTreeWidgetItem(self.tree_vis, ["Grupy Węzłów"])
                    parent_gr.setCheckState(0, Qt.CheckState.Checked)
                    self.tree_vis.expandItem(parent_gr)
                    colors = {"SURF_SUPPORT": "orange", "SURF_LOAD": "magenta", "GRP_INTERFACE": "yellow"}
                    for g_name, node_ids in groups.items():
                        pts = []
                        for nid in node_ids:
                            if nid in node_map: pts.append(node_map[nid])
                        if pts:
                            pc = pv.PolyData(pts)
                            act = self.plotter.add_mesh(pc, color=colors.get(g_name, "white"), point_size=6, render_points_as_spheres=True)
                            item = QTreeWidgetItem(parent_gr, [g_name])
                            item.setCheckState(0, Qt.CheckState.Checked)
                            self.actors[id(item)] = act
            except: pass
            
        self.plotter.add_axes(); self.plotter.show_grid(); self.plotter.reset_camera()

    def add_tree_item(self, name, key, actor, checked=True):
        item = QTreeWidgetItem(self.tree_vis, [name])
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        item.setCheckState(0, state)
        self.actors[id(item)] = actor # Klucz 'key' nie był używany, id(item) jest lepsze
        
    def on_tree_item_changed(self, item, col):
        if id(item) in self.actors:
            actor = self.actors[id(item)]
            visible = (item.checkState(0) == Qt.CheckState.Checked)
            actor.SetVisibility(visible)
            self.plotter.render()
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, item.checkState(0))

class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        # Ciemny motyw dla wykresów
        self.fig.patch.set_facecolor('#2b2b2b')
        self.axes = self.fig.add_subplot(111)
        self.axes.set_facecolor('#2b2b2b')
        self.axes.tick_params(colors='white')
        self.axes.xaxis.label.set_color('white')
        self.axes.yaxis.label.set_color('white')
        self.axes.title.set_color('white')
        for spine in self.axes.spines.values():
            spine.set_edgecolor('white')
        super().__init__(self.fig)

class GeometryPreviewWorker(QThread):
    finished_signal = pyqtSignal(str) # Zwraca ścieżkę do pliku .msh
    log_signal = pyqtSignal(str)

    def __init__(self, geo_engine, params):
        super().__init__()
        self.geo_engine = geo_engine
        self.params = params

    def run(self):
        self.log_signal.emit("Generowanie podglądu geometrii...")
        res = self.geo_engine.generate_model(self.params)
        if res and "paths" in res and "msh" in res["paths"]:
            self.finished_signal.emit(res["paths"]["msh"])
            self.log_signal.emit("Geometria gotowa do podglądu.")
        else:
            self.finished_signal.emit("")
            self.log_signal.emit("Błąd generowania geometrii podglądu.")

class ShellWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    progress_signal = pyqtSignal(int)

    def __init__(self, optimizer_shell, candidates, load_conditions, mesh_settings):
        super().__init__()
        self.optimizer = optimizer_shell
        self.candidates = candidates
        self.loads = load_conditions
        self.mesh = mesh_settings
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True

    def run(self):
        self.log_signal.emit(">>> START PROCEDURY SHELL BATCH...")
        total = len(self.candidates)
        for i, cand in enumerate(self.candidates):
            if self.stop_requested:
                self.log_signal.emit("...Przerwano na żądanie.")
                break
            
            self.progress_signal.emit(i)
            
            try:
                # run_batch z optimizer_shell oczekuje listy, więc opakowujemy pojedynczego kandydata
                self.optimizer.run_batch([cand], self.loads, self.mesh)
            except Exception as e:
                self.log_signal.emit(f"BŁĄD podczas przetwarzania {cand.get('Name', 'N/A')}: {e}")
                self.log_signal.emit(traceback.format_exc())

        self.progress_signal.emit(total)
        self.log_signal.emit(">>> ZAKOŃCZONO BATCH SHELL.")
        self.finished_signal.emit(True)

class Tab6_Shell_Settings(QWidget):
    analysis_finished = pyqtSignal()

    def __init__(self, optimizer_shell, parent=None):
        super().__init__(parent)
        self.candidates = []
        self.optimizer = optimizer_shell
        self.init_ui()

    def init_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout = QHBoxLayout(self); main_layout.addWidget(splitter)

        # --- LEWY PANEL: USTAWIENIA ---
        left_panel = QWidget(); l_layout = QVBoxLayout(left_panel)
        
        # 1. Obciążenia
        g_loads = QGroupBox("1. Warunki Brzegowe i Obciążenia"); f_loads = QFormLayout(g_loads)
        self.inp_fx = QLineEdit("-24000.0"); self.chk_fx = QCheckBox("Z analityki"); self.chk_fx.setChecked(True)
        h_fx = QHBoxLayout(); h_fx.addWidget(self.inp_fx); h_fx.addWidget(self.chk_fx); f_loads.addRow("Siła Fx [N]:", h_fx)
        
        self.inp_fy = QLineEdit("0.0"); self.chk_fy = QCheckBox("Z analityki"); self.chk_fy.setChecked(True)
        h_fy = QHBoxLayout(); h_fy.addWidget(self.inp_fy); h_fy.addWidget(self.chk_fy); f_loads.addRow("Siła Fy [N]:", h_fy)

        self.inp_fz = QLineEdit("0.0"); self.chk_fz = QCheckBox("Z analityki"); self.chk_fz.setChecked(True)
        h_fz = QHBoxLayout(); h_fz.addWidget(self.inp_fz); h_fz.addWidget(self.chk_fz); f_loads.addRow("Siła Fz [N]:", h_fz)

        # Ramię siły (Y)
        self.inp_y_ref = QLineEdit("0.0")
        h_y_ref_mode = QHBoxLayout()
        self.rb_y_ref_manual = QRadioButton("Ręcznie"); self.rb_y_ref_ramie = QRadioButton("Ramię"); self.rb_y_ref_yc = QRadioButton("Śr. ciężkości")
        self.y_ref_group = QButtonGroup(self); self.y_ref_group.addButton(self.rb_y_ref_manual, 0); self.y_ref_group.addButton(self.rb_y_ref_ramie, 1); self.y_ref_group.addButton(self.rb_y_ref_yc, 2)
        h_y_ref_mode.addWidget(self.rb_y_ref_manual); h_y_ref_mode.addWidget(self.rb_y_ref_ramie); h_y_ref_mode.addWidget(self.rb_y_ref_yc)
        f_loads.addRow("Położenie Y siły:", h_y_ref_mode)
        f_loads.addRow("Wartość Y [mm]:", self.inp_y_ref)
        self.rb_y_ref_ramie.setChecked(True)

        self.inp_mx = QLineEdit("0.0"); f_loads.addRow("Moment Mx [Nmm]:", self.inp_mx)
        self.inp_my = QLineEdit("0.0"); f_loads.addRow("Moment My [Nmm]:", self.inp_my)
        self.inp_mz = QLineEdit("0.0"); f_loads.addRow("Moment Mz [Nmm]:", self.inp_mz)
        l_layout.addWidget(g_loads)

        # 2. Siatka
        g_mesh = QGroupBox("2. Parametry Dyskretyzacji"); f_mesh = QFormLayout(g_mesh)
        self.sp_mesh_size = QDoubleSpinBox(); self.sp_mesh_size.setRange(1.0, 100.0); self.sp_mesh_size.setValue(20.0)
        self.sp_iter = QSpinBox(); self.sp_iter.setRange(1, 10); self.sp_iter.setValue(5)
        self.sp_conv_tol = QDoubleSpinBox(); self.sp_conv_tol.setRange(0.1, 10.0); self.sp_conv_tol.setValue(2.0); self.sp_conv_tol.setSuffix(" %")
        self.sp_ref_factor = QDoubleSpinBox(); self.sp_ref_factor.setRange(0.1, 0.95); self.sp_ref_factor.setValue(0.7); self.sp_ref_factor.setSingleStep(0.05)
        self.combo_order = QComboBox(); self.combo_order.addItems(["1 (Liniowe)", "2 (Kwadratowe)"]); self.combo_order.setCurrentIndex(1)
        f_mesh.addRow("Startowy rozmiar siatki [mm]:", self.sp_mesh_size)
        f_mesh.addRow("Max iteracji:", self.sp_iter)
        f_mesh.addRow("Warunek zbieżności:", self.sp_conv_tol)
        f_mesh.addRow("Wsp. zagęszczenia:", self.sp_ref_factor)
        f_mesh.addRow("Rząd elementów:", self.combo_order)
        l_layout.addWidget(g_mesh)

        # 3. Sterowanie
        g_ctrl = QGroupBox("3. Sterowanie"); l_ctrl = QVBoxLayout(g_ctrl)
        self.list_cands = QListWidget(); self.list_cands.setFixedHeight(80); l_ctrl.addWidget(QLabel("Kandydaci do analizy:")); l_ctrl.addWidget(self.list_cands)
        self.btn_run = QPushButton("URUCHOM OBLICZENIA SHELL"); self.btn_run.setStyleSheet("background-color:#27ae60; font-weight:bold; padding:8px;")
        self.console = QTextBrowser(); self.console.setStyleSheet("font-family:Consolas; font-size:10px; background:#111; color:#0f0;")
        self.progress = QProgressBar()
        l_ctrl.addWidget(self.btn_run); l_ctrl.addWidget(self.console); l_ctrl.addWidget(self.progress)
        l_layout.addWidget(g_ctrl)
        l_layout.addStretch()
        splitter.addWidget(left_panel)

        # --- PRAWY PANEL: WIZUALIZACJA ---
        right_panel = QWidget(); r_layout = QVBoxLayout(right_panel)
        self.view_3d_panel = QFrame()
        if HAS_PYVISTA:
            l_3d = QVBoxLayout(self.view_3d_panel); l_3d.setContentsMargins(0,0,0,0)
            self.plotter = QtInteractor(self.view_3d_panel); self.plotter.set_background("#303030")
            l_3d.addWidget(self.plotter.interactor)
        else:
            l_3d = QVBoxLayout(self.view_3d_panel); l_3d.addWidget(QLabel("Brak PyVista"))
        
        btn_preview = QPushButton("Pokaż/Odśwież Geometrię"); btn_preview.clicked.connect(self.preview_geometry)
        r_layout.addWidget(btn_preview)
        r_layout.addWidget(self.view_3d_panel)
        splitter.addWidget(right_panel)

        splitter.setSizes([400, 600])
        
        # Podpięcie loggera do konsoli
        if self.optimizer:
            self.optimizer.logger = self.console.append

        # Połączenia sygnałów
        self.btn_run.clicked.connect(self.run_analysis)
        self.chk_fx.toggled.connect(lambda c: self.inp_fx.setDisabled(c))
        self.chk_fy.toggled.connect(lambda c: self.inp_fy.setDisabled(c))
        self.chk_fz.toggled.connect(lambda c: self.inp_fz.setDisabled(c))
        self.y_ref_group.idToggled.connect(self.on_y_ref_mode_changed)

    def receive_data(self, candidates):
        self.candidates = candidates
        self.list_cands.clear()
        for cand in candidates:
            name = cand.get("Nazwa_Profilu", "N/A")
            tp = cand.get("Input_Geo_tp", 0); bp = cand.get("Input_Geo_bp", 0)
            self.list_cands.addItem(f"{name} (tp={tp}, bp={bp})")
        self.console.append(f"Załadowano {len(candidates)} kandydatów.")

        if candidates:
            c = candidates[0]
            if self.chk_fx.isChecked(): self.inp_fx.setText(f"{-float(c.get('Input_Load_Fx', 0.0)):.1f}")
            if self.chk_fy.isChecked(): self.inp_fy.setText(f"{float(c.get('Res_Force_Fy_Ed', 0.0)):.1f}")
            if self.chk_fz.isChecked(): self.inp_fz.setText(f"{float(c.get('Res_Force_Fz_Ed', 0.0)):.1f}")
            self.on_y_ref_mode_changed(self.y_ref_group.checkedId(), True)

    def on_y_ref_mode_changed(self, btn_id, checked):
        if not checked: return
        is_manual = (btn_id == 0)
        self.inp_y_ref.setDisabled(not is_manual)
        if not is_manual and self.candidates:
            cand = self.candidates[0]
            if btn_id == 1: # Ramię
                self.inp_y_ref.setText(f"{cand.get('Input_Load_F_promien', 0.0):.4f}")
            elif btn_id == 2: # Yc
                self.inp_y_ref.setText(f"{cand.get('Res_Geo_Yc', 0.0):.4f}")

    def _translate_candidate(self, c):
        e_mod = c.get("Input_Load_E")
        g_mod = c.get("Input_Load_G")
        nu = 0.3
        if e_mod and g_mod and g_mod > 0:
            nu = (e_mod / (2.0 * g_mod)) - 1.0
        
        translated = {
            "Name": f"{c.get('Nazwa_Profilu', 'Unk')}_tp{int(c.get('Input_Geo_tp', 0))}",
            "Geom_h_c": c.get("Input_UPE_hc"), "Geom_b_c": c.get("Input_UPE_bc"),
            "Geom_t_w": c.get("Input_UPE_twc"), "Geom_t_f": c.get("Input_UPE_tfc"),
            "Geom_r_c": c.get("Input_UPE_rc", 0.0), "Geom_t_p": c.get("Input_Geo_tp"),
            "Geom_b_p": c.get("Input_Geo_bp"), "Input_Length": c.get("Input_Load_L"),
            "Mat_Name": c.get("Stop"), "Mat_E": e_mod, "Mat_nu": nu,
        }
        translated.update(c) # Przekaż resztę danych dla pliku analitycznego
        return translated

    def run_analysis(self):
        if not self.candidates:
            QMessageBox.warning(self, "Brak danych", "Najpierw przekaż kandydatów z zakładki 'Selektor Wyników'.")
            return
        
        # --- Zbieranie ustawień z GUI ---
        load_conditions = {
            "Fx": float(self.inp_fx.text()), "Fy": float(self.inp_fy.text()), "Fz": float(self.inp_fz.text()),
            "Mx": float(self.inp_mx.text()), "My": float(self.inp_my.text()), "Mz": float(self.inp_mz.text()),
            "Y_load_level": float(self.inp_y_ref.text())
        }
        mesh_settings = {
            "mesh_start": self.sp_mesh_size.value(),
            "max_iter": self.sp_iter.value(),
            "conv_tol": self.sp_conv_tol.value() / 100.0, # % na ułamek
            "mesh_factor": self.sp_ref_factor.value(),
            "order": self.combo_order.currentIndex() + 1
        }
        
        translated_candidates = [self._translate_candidate(c) for c in self.candidates]

        self.worker = ShellWorker(self.optimizer, translated_candidates, load_conditions, mesh_settings)
        self.worker.log_signal.connect(self.console.append)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(self.on_analysis_finished)
        
        self.progress.setRange(0, len(self.candidates))
        self.btn_run.setEnabled(False)
        self.console.clear()
        self.worker.start()

    def on_analysis_finished(self, success):
        self.btn_run.setEnabled(True)
        if success:
            self.console.append("Analiza zakończona pomyślnie.")
            self.analysis_finished.emit()
        else:
            self.console.append("Analiza zakończona z błędami.")

    def preview_geometry(self):
        if not self.candidates:
            QMessageBox.warning(self, "Brak danych", "Najpierw przekaż kandydatów z zakładki 'Selektor Wyników'.")
            return
        
        cand = self.candidates[0]
        params = self.optimizer._prepare_run_params(cand, {}, 15.0) # Obciążenia i siatka nieistotne dla geometrii
        
        # Używamy folderu tymczasowego dla podglądu
        preview_dir = os.path.join(self.optimizer.work_dir, "_preview_temp")
        params['output_dir'] = preview_dir
        params['model_name'] = "preview"

        # Uruchomienie generatora w osobnym wątku
        self.preview_worker = GeometryPreviewWorker(self.optimizer.geo_engine, params)
        self.preview_worker.log_signal.connect(self.console.append)
        self.preview_worker.finished_signal.connect(self.show_preview_mesh)
        self.preview_worker.start()

    def show_preview_mesh(self, msh_path):
        if not HAS_PYVISTA or not msh_path or not os.path.exists(msh_path):
            self.console.append("Nie można wyświetlić podglądu.")
            return
            
        self.plotter.clear()
        try:
            mesh = pv.read(msh_path)
            self.plotter.add_mesh(mesh, style='surface', show_edges=True, edge_color='black', color='lightblue')
            self.plotter.add_axes(); self.plotter.reset_camera()
        except Exception as e:
            self.console.append(f"Błąd ładowania podglądu siatki: {e}")

class Tab7_Shell_Results(QWidget):
    def __init__(self, router, aggregator_shell, parent=None):
        super().__init__(parent)
        self.router = router
        self.aggregator = aggregator_shell
        self.init_ui()

    def init_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = QWidget(); l_layout = QVBoxLayout(left_panel)
        self.results_list = QListWidget(); self.results_list.itemClicked.connect(self.on_result_selected)
        btn_refresh = QPushButton("🔄 Odśwież"); btn_refresh.clicked.connect(self.refresh_list)
        l_layout.addWidget(btn_refresh); l_layout.addWidget(self.results_list)
        
        right_panel = QWidget(); r_layout = QVBoxLayout(right_panel)
        self.vis_tabs = QTabWidget(); r_layout.addWidget(self.vis_tabs)
        
        self.plot_panel = QWidget(); self.plot_layout = QVBoxLayout(self.plot_panel)
        self.vis_tabs.addTab(self.plot_panel, "Wykresy 2D")
        
        self.view_3d_panel = QFrame()
        if HAS_PYVISTA:
            l_3d = QVBoxLayout(self.view_3d_panel); l_3d.setContentsMargins(0,0,0,0)
            self.plotter = QtInteractor(self.view_3d_panel); self.plotter.set_background("#303030")
            l_3d.addWidget(self.plotter.interactor)
        else:
            l_3d = QVBoxLayout(self.view_3d_panel); l_3d.addWidget(QLabel("Brak PyVista"))
        self.vis_tabs.addTab(self.view_3d_panel, "Podgląd 3D")

        splitter.addWidget(left_panel); splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])
        
        main_layout = QHBoxLayout(self); main_layout.addWidget(splitter)
        self.refresh_list()

    def refresh_list(self):
        self.results_list.clear()
        comparisons = self.aggregator.get_available_comparisons()
        for comp in comparisons:
            item = QListWidgetItem(comp['label'])
            item.setData(Qt.ItemDataRole.UserRole, comp['id'])
            self.results_list.addItem(item)

    def on_result_selected(self, item):
        comp_id = item.data(Qt.ItemDataRole.UserRole)
        data_package = self.aggregator.load_data(comp_id)
        if not data_package: return
        self.update_charts(data_package)
        self.update_3d_view(comp_id)

    def update_charts(self, data_package):
        for i in reversed(range(self.plot_layout.count())): 
            self.plot_layout.itemAt(i).widget().setParent(None)
            
        plots_data = self.aggregator.prepare_plots_data(data_package)
        
        for key, p_info in plots_data.items():
            canvas = MplCanvas(self)
            ax = canvas.axes
            
            if p_info.get("type") == "bar":
                ax.bar(p_info["categories"], p_info["series"][0]["y"], color=p_info["series"][0].get("color", "blue"))
            else:
                for s in p_info["series"]:
                    style = s.get("style", "-")
                    if "o" in style:
                        ax.plot(s["x"], s["y"], marker='o', markersize=s.get("size", 5), linestyle='None', color=s.get("color"), label=s["name"])
                    else:
                        ax.plot(s["x"], s["y"], style, color=s.get("color"), label=s["name"])
                ax.legend()
            
            ax.set_title(p_info["title"]); ax.set_xlabel(p_info["xlabel"]); ax.set_ylabel(p_info["ylabel"])
            ax.grid(True, linestyle='--', alpha=0.3)
            if "Ugięcie" in p_info["title"]: ax.invert_yaxis()
            self.plot_layout.addWidget(canvas)

    def update_3d_view(self, comp_id):
        if not HAS_PYVISTA: return
        self.plotter.clear()
        
        fem_dir = self.router.get_path("FINAL", "", subdir=comp_id)
        msh_files = [f for f in os.listdir(fem_dir) if f.endswith(".msh")]
        if msh_files:
            try:
                path_msh = os.path.join(fem_dir, msh_files[0])
                mesh = pv.read(path_msh)
                self.plotter.add_mesh(mesh, style='surface', show_edges=True, edge_color='black', color='lightblue')
            except Exception as e:
                self.plotter.add_text(f"Błąd ładowania siatki:\n{e}", color='red')
        else:
            self.plotter.add_text("Nie znaleziono pliku .msh", color='red')

        self.plotter.add_axes(); self.plotter.reset_camera()

# =============================================================================
# TAB 5: PEŁNA ANALIZA WYNIKÓW (DASHBOARD)
# =============================================================================

class Tab5_Comparison(QWidget):
    def __init__(self, router, aggregator):
        super().__init__()
        self.router = router
        self.aggregator = aggregator
        self.current_data = None
        self.highlight_color = QColor(60, 60, 100)
        self.last_highlighted_row = -1
        self.init_ui()
        self.refresh_list()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # --- GÓRA: TABELA ZBIORCZA WSZYSTKICH SYMULACJI ---
        top_group = QGroupBox("Dostępne wyniki symulacji")
        top_layout = QVBoxLayout(top_group)
        
        self.sim_table = QTableWidget()
        self.sim_table.setColumnCount(7)
        self.sim_table.setHorizontalHeaderLabels(["ID Profilu", "Płaskownik [mm]", "Masa [kg/m]", "Max VM [MPa]", "Max U [mm]", "Wyboczenie", "Status"])
        self.sim_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sim_table.setAlternatingRowColors(True)
        self.sim_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sim_table.itemClicked.connect(self.on_sim_selected)
        
        top_layout.addWidget(self.sim_table)
        
        btn_refresh = QPushButton("🔄 Odśwież listę wyników")
        btn_refresh.clicked.connect(self.refresh_list)
        top_layout.addWidget(btn_refresh)
        
        layout.addWidget(top_group, 35) # 35% wysokości

        # --- DÓŁ: SZCZEGÓŁY (SPLITTER) ---
        details_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(details_splitter, 65) # 65% wysokości

        # LEWA STRONA: Info + Wykresy
        left_panel = QWidget()
        l_layout = QVBoxLayout(left_panel)
        l_layout.setContentsMargins(0,0,0,0)

        # 1. Info Box (Podsumowanie Analityka vs FEM)
        self.info_box = QTextBrowser()
        self.info_box.setMaximumHeight(160)
        self.info_box.setStyleSheet("background-color: #222; color: #eee; font-size: 11px; border: 1px solid #444;")
        l_layout.addWidget(self.info_box)

        # --- [NOWOŚĆ] Opis obliczeń spoiny ---
        weld_info_group = QGroupBox("Opis Obliczeń Spoiny (FEM)")
        weld_info_group.setStyleSheet("QGroupBox { font-weight: normal; }")
        weld_layout = QVBoxLayout(weld_info_group)
        weld_layout.setContentsMargins(5, 5, 5, 5)
        weld_desc_html = """
        <div style="font-size:10px;">
        <p>Model FEM wyznacza naprężenia w spoinie (oznaczone jako <b>INTERFACE_DATA</b> lub <b>INTERFACE_MAX_SHEAR</b>) w następujący sposób:</p>
        <ul style="margin-left: 0px; padding-left: 15px;">
            <li><b>Lokalizacja:</b> Identyfikacja węzłów na styku ceowników z płaskownikiem (grupa <b>GRP_INTERFACE</b>).</li>
            <li><b>Wartość fizyczna:</b> Pobranie składowych tensora naprężeń tnących: &tau;<sub>xy</sub> (wzdłuż belki) oraz &tau;<sub>yz</sub> (poprzecznie do spoiny).</li>
            <li><b>Wypadkowa:</b> Prezentowana wartość to wypadkowe naprężenie tnące, obliczane ze wzoru:<br>
            <p align="center" style="font-size:12px; font-family: Consolas; color: #aaffff;">&tau;<sub>total</sub> = &radic;(&tau;<sub>12</sub><sup>2</sup> + &tau;<sub>23</sub><sup>2</sup>)</p>
            <p>gdzie 12 i 23 to indeksy kierunków w systemie CalculiX odpowiadające płaszczyźnie styku.</p></li>
        </ul>
        </div>
        """
        weld_label = QLabel(weld_desc_html)
        weld_label.setWordWrap(True)
        weld_label.setTextFormat(Qt.TextFormat.RichText)
        weld_label.setStyleSheet("background-color: #282828; padding: 5px; border-radius: 3px;")
        weld_layout.addWidget(weld_label)
        weld_info_group.setMaximumHeight(180)
        l_layout.addWidget(weld_info_group)

        # 2. Zakładki z Wykresami
        self.chart_tabs = QTabWidget()
        l_layout.addWidget(self.chart_tabs)
        
        details_splitter.addWidget(left_panel)

        # PRAWA STRONA: Wizualizacja 3D
        right_panel = QFrame()
        right_panel.setFrameShape(QFrame.Shape.StyledPanel)
        r_layout = QVBoxLayout(right_panel)
        r_layout.setContentsMargins(0,0,0,0)
        
        r_layout.addWidget(QLabel("<b>Heatmapa Naprężeń (Von Mises)</b>"))
        
        if HAS_PYVISTA:
            self.plotter = QtInteractor(right_panel)
            self.plotter.set_background("#303030")
            r_layout.addWidget(self.plotter.interactor)
        else:
            lbl = QLabel("Brak biblioteki PyVista.\nZainstaluj: pip install pyvistaqt")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            r_layout.addWidget(lbl)

        details_splitter.addWidget(right_panel)
        details_splitter.setSizes([550, 450])

    def refresh_list(self):
        """Skanuje dysk i wypełnia górną tabelę."""
        self.sim_table.setRowCount(0)
        self.last_highlighted_row = -1
        if not self.aggregator: return

        pairs = self.aggregator.get_available_comparisons()
        self.sim_table.setRowCount(len(pairs))
        
        # Zmieniamy nagłówek na "FEM Factor", żeby było jasne co pokazujemy
        self.sim_table.setHorizontalHeaderItem(5, QTableWidgetItem("FEM Factor [-]"))

        for i, p in enumerate(pairs):
            try:
                data = self.aggregator.load_comparison_data(p["id"])
                if not data: continue
                
                ana = data["ana"]
                fem = data["fem"]
                
                # Podstawowe wyniki
                mass = ana.get("Res_Masa_kg_m", 0.0)
                vm = fem.get("MODEL_MAX_VM", 0.0)
                u = fem.get("MODEL_MAX_U", 0.0)
                
                # --- Wyboczenie (Odczyt surowego mnożnika) ---
                buckling = fem.get("BUCKLING_FACTORS", [])
                if buckling:
                    # Bierzemy pierwszy (najniższy) mnożnik
                    b_val = buckling[0]
                    buckling_str = f"{b_val:.4f}"
                else:
                    buckling_str = "-"
                
                # Status
                converged = fem.get("converged", False)
                if converged == "NOT_DEFINED":
                    status_str = "BATCH"
                    col_bg = QColor(100, 100, 50)
                else:
                    status_str = "OK" if converged else "FAIL"
                    col_bg = QColor(50, 100, 50) if converged else QColor(100, 50, 50)
                s_item = QTableWidgetItem(status_str)
                s_item.setBackground(col_bg)

                # Wypełnianie tabeli
                bp = ana.get("Input_Geo_bp", 0.0)
                tp = ana.get("Input_Geo_tp", 0.0)
                plate_dims = f"{bp:.0f} x {tp:.0f}"
                
                self.sim_table.setItem(i, 0, QTableWidgetItem(p["id"]))
                self.sim_table.setItem(i, 1, QTableWidgetItem(plate_dims))
                self.sim_table.setItem(i, 2, QTableWidgetItem(f"{mass:.2f}"))
                self.sim_table.setItem(i, 3, QTableWidgetItem(f"{vm:.2f}"))
                self.sim_table.setItem(i, 4, QTableWidgetItem(f"{u:.2f}"))
                self.sim_table.setItem(i, 5, QTableWidgetItem(buckling_str)) # Tu wstawiamy factor
                self.sim_table.setItem(i, 6, s_item)
                
                self.sim_table.item(i, 0).setData(Qt.ItemDataRole.UserRole, p["id"])
                
            except Exception as e:
                print(f"Błąd tabeli dla {p['id']}: {e}")
                self.sim_table.setItem(i, 0, QTableWidgetItem("Błąd danych"))

    def on_sim_selected(self, item):
        row = item.row()
        sim_id = self.sim_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.load_details(sim_id)

    def load_details(self, sim_id):
        """Ładuje szczegóły wybranej symulacji (wykresy, info, 3d)."""
        data = self.aggregator.load_comparison_data(sim_id)
        if not data: return
        
        fem = data["fem"]
        ana = data["ana"]
        
        # 1. INFO BOX (HTML) - Tu robimy porównanie "Delta" w tekście
        vm_ana = ana.get('Res_Max_VonMises', 0)
        vm_fem = fem.get('MODEL_MAX_VM', 0)
        
        html = f"""
        <h3 style='margin:0; color:#4CAF50'>{sim_id}</h3>
        <table width='100%' cellpadding='3'>
        <tr>
            <td><b>Parametr</b></td> <td><b>FEM</b></td> <td><b>Analityka</b></td>
        </tr>
        <tr>
            <td>Max Napr. (VM)</td> 
            <td style='color:#aaf'><b>{vm_fem:.2f} MPa</b></td> 
            <td>{vm_ana:.2f} MPa</td>
        </tr>
        <tr>
            <td>Max Ugięcie</td> 
            <td style='color:#aaf'><b>{fem.get('MODEL_MAX_U',0):.2f} mm</b></td> 
            <td>{ana.get('Res_Disp_U_y_max',0):.2f} mm</td>
        </tr>
        </table>
        <hr>
        """
        
        # Sekcja Reakcji
#        if "REACTIONS" in fem:
#            r = fem["REACTIONS"]
#            html += f"<b>Reakcje (Podpora):</b> Rx={r.get('Fx',0):.0f}N, Ry={r.get('Fy',0):.0f}N, Rz={r.get('Fz',0):.0f}N<br>"
        
        # Sekcja Wyboczenia
        if "BUCKLING_FACTORS" in fem and fem["BUCKLING_FACTORS"]:
            html += f"<b>Krytyczne mnożniki (Buckling):</b> {fem['BUCKLING_FACTORS'][:3]}<br>"
            
        # Sekcja Spoiny
        if "INTERFACE_MAX_SHEAR" in fem:
             html += f"<b>Spoina (Tau Max):</b> {fem['INTERFACE_MAX_SHEAR']:.2f} MPa"

        self.info_box.setHtml(html)

        # 2. WYKRESY 2D (Dynamiczne z Aggregatora)
        self.update_charts(data)

        # 3. HEATMAPA 3D
        self.update_3d_view(data)

    def highlight_profile(self, profile_id: str):
        """Znajduje wiersz i go podświetla, resetując poprzedni."""
        # 1. Zresetuj poprzednio podświetlony wiersz
        if self.last_highlighted_row >= 0 and self.last_highlighted_row < self.sim_table.rowCount():
            # Przywróć domyślne tło dla wszystkich komórek
            for j in range(self.sim_table.columnCount()):
                item = self.sim_table.item(self.last_highlighted_row, j)
                if item:
                    item.setBackground(QBrush()) # Resetuje do tła z palety (uwzględnia alternating)

            # Ponownie zastosuj specjalny kolor dla kolumny statusu
            status_item = self.sim_table.item(self.last_highlighted_row, 6) # Kolumna "Status"
            if status_item and status_item.text():
                is_ok = (status_item.text() == "OK")
                status_item.setBackground(QColor(50, 100, 50) if is_ok else QColor(100, 50, 50))

        self.last_highlighted_row = -1

        # 2. Znajdź i podświetl nowy wiersz
        for i in range(self.sim_table.rowCount()):
            item = self.sim_table.item(i, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == profile_id:
                for j in range(self.sim_table.columnCount()):
                    self.sim_table.item(i, j).setBackground(self.highlight_color)
                self.sim_table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                self.last_highlighted_row = i
                break

    def update_charts(self, data):
        """Rysuje wykresy przygotowane przez aggregator."""
        self.chart_tabs.clear()
        
        # Aggregator zwraca gotowe słowniki z seriami danych
        plots_data = self.aggregator.prepare_plots_data(data)
        
        import matplotlib.pyplot as plt
        
        # Ustawiamy styl wykresów pasujący do ciemnego GUI
        try: plt.style.use('dark_background')
        except: pass
        
        for key, p_info in plots_data.items():
            canvas = MplCanvas(self, width=5, height=4, dpi=100)
            ax = canvas.axes # Używamy istniejących osi z naszego widgetu
            
            # Logika rysowania w zależności od typu wykresu
            if p_info.get("type") == "scatter":
                s = p_info["series"][0] # Zakładamy jedną serię dla mapy
                scatter = ax.scatter(
                    s["x"], s["y"], 
                    c=s["c"], 
                    cmap=s.get("cmap", "jet"),
                    s=10, # rozmiar markera
                    alpha=0.8
                )
                canvas.fig.colorbar(scatter, ax=ax, label="Naprężenie [MPa]")
            else: # Domyślna logika dla wykresów liniowych
                for s in p_info["series"]:
                    ax.plot(
                        s["x"], s["y"], 
                        s.get("style", "-"), 
                        label=s["name"], 
                        color=s.get("color"),
                        linewidth=2 if "Ana" in s["name"] else 1.5,
                        marker='o' if 'FEM' in s["name"] else None,
                        markersize=3
                    )
                ax.legend(fontsize=8)
            
            ax.set_title(p_info["title"], color='white', fontsize=9)
            ax.set_xlabel(p_info["xlabel"], color='#aaa', fontsize=8)
            ax.set_ylabel(p_info["ylabel"], color='#aaa', fontsize=8)
            ax.grid(True, linestyle='--', alpha=0.3)
            
            # Odwrócenie osi Y dla ugięć (żeby wykres szedł "w dół")
            if "Deflection" in key or "Ugięcie" in p_info["title"]:
                ax.invert_yaxis()
            
            # Dodanie do zakładki
            self.chart_tabs.addTab(canvas, p_info["title"])

    def update_3d_view(self, data):
        """Rysuje chmurę punktów (Heatmapę) na podstawie FULL_NODAL_RESULTS."""
        if not HAS_PYVISTA: return
        
        self.plotter.clear()
        
        # 1. Rysowanie siatki (Wireframe) jako tła
        msh_path, _ = self.aggregator.get_mesh_data_path(data)
        if msh_path and os.path.exists(msh_path):
            try:
                mesh = pv.read(msh_path)
                self.plotter.add_mesh(mesh, style='wireframe', color='white', opacity=0.1, label="Mesh")
            except: pass

        # 2. Rysowanie HEATMAPY (Kluczowy element!)
        res_map = data["fem"].get("FULL_NODAL_RESULTS", {})
        
        if res_map:
            vals = list(res_map.values()) # [[x,y,z,vm...], ...]
            
            try:
                import numpy as np
                arr = np.array(vals) 
                
                # Wyciągamy kolumny: X, Y, Z (0-2) i VM (3)
                points = arr[:, 0:3]
                scalars = arr[:, 3]
                
                cloud = pv.PolyData(points)
                cloud.point_data["Stress VM [MPa]"] = scalars
                
                self.plotter.add_mesh(
                    cloud, 
                    scalars="Stress VM [MPa]", 
                    cmap="jet", 
                    point_size=4, 
                    render_points_as_spheres=True,
                    show_scalar_bar=True
                )
                self.plotter.add_text(f"Model: {len(points)} węzłów", font_size=8)
                
            except ImportError:
                # Wersja wolniejsza (gdy brak numpy)
                pts_list = []
                sc_list = []
                for v in vals:
                    pts_list.append([v[0], v[1], v[2]])
                    sc_list.append(v[3])
                cloud = pv.PolyData(pts_list)
                self.plotter.add_mesh(cloud, scalars=sc_list, cmap="jet", point_size=4)
        else:
            self.plotter.add_text("Brak wyników węzłowych w pliku .json", color='red')

        # --- WIZUALIZACJA PUNKTÓW CHARAKTERYSTYCZNYCH I SIŁ ---
        ana = data["ana"]
        try:
            # Punkty Yc, Ys
            ys = ana.get("Res_Geo_Ys", 0.0)
            yc = ana.get("Res_Geo_Yc", 0.0)
            if yc == 0.0 and "Res_Geo_Delta_Ys" in ana:
                yc = ys + ana.get("Res_Geo_Delta_Ys", 0.0)

            self.plotter.add_mesh(pv.Sphere(radius=5, center=(0, yc, 0)), color="red", label="Yc")
            self.plotter.add_mesh(pv.Sphere(radius=5, center=(0, ys, 0)), color="green", label="Ys")

            # Wektory sił
            L = float(ana.get("Input_Load_L", 0))
            F_promien = float(ana.get("Input_Load_F_promien", 0))
            Fx = float(ana.get("Input_Load_Fx", 0))
            w_Ty = float(ana.get("Input_Load_w_Ty", 0))
            w_Tz = float(ana.get("Input_Load_w_Tz",0))
            
            Fy = Fx * w_Ty
            Fz = Fx * w_Tz

            if L > 0 and abs(Fx) > 1e-6:
                load_point = np.array([L, F_promien, 0])
                
                self.plotter.add_mesh(pv.Sphere(radius=max(5, L/400), center=load_point), color="cyan", label="Load Point")

                forces = {
                    "Fx": {"vec": np.array([-1, 0, 0]), "mag": abs(Fx), "color": "red"},
                    "Fy": {"vec": np.array([0, 1, 0]), "mag": abs(Fy), "color": "green"},
                    "Fz": {"vec": np.array([0, 0, 1]), "mag": abs(Fz), "color": "blue"},
                }
                
                arrow_base_length = L * 0.15
                max_force_mag = max(f["mag"] for f in forces.values())

                if max_force_mag > 1e-6:
                    for name, f_data in forces.items():
                        if f_data["mag"] > 1e-6:
                            arrow_len = (f_data["mag"] / max_force_mag) * arrow_base_length
                            arrow_geom = pv.Arrow(start=load_point, direction=f_data["vec"], scale=arrow_len, shaft_radius=0.02 * arrow_len, tip_length=0.2 * arrow_len)
                            self.plotter.add_mesh(arrow_geom, color=f_data["color"], label=name)
        except Exception as e:
            self.plotter.add_text(f"Błąd wizualizacji sił: {e}", color='red')

        self.plotter.show_axes()
        self.plotter.reset_camera()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Optymalizator Słupa v4.1 (FEM Integrated)")
        self.resize(1350, 850)
        self.resize(1350, 800)
        
        # Inicjalizacja routera i agregatora
        self.router = router
        self.aggregator = data_aggregator.DataAggregator(self.router)
        self.aggregator_shell = DataAggregatorShell(self.router)
        self.optimizer_shell = FemOptimizerShell(self.router.base_output_dir)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.tab1 = Tab1_Dashboard()
        self.tab2 = Tab2_Knowledge()
        self.tab3 = Tab3_Selector()
        self.tab4 = Tab4_Fem()
        self.tab5 = Tab5_Comparison(self.router, self.aggregator)
        self.tab6 = Tab6_Shell_Settings(self.optimizer_shell)
        self.tab7 = Tab7_Shell_Results(self.router, self.aggregator_shell)

        self.tabs.addTab(self.tab1, "1. Dashboard")
        self.tabs.addTab(self.tab2, "2. Baza Wiedzy")
        self.tabs.addTab(self.tab3, "3. Selektor Wyników")
        self.tabs.addTab(self.tab4, "4. Analiza FEM (Solid)")
        self.tabs.addTab(self.tab5, "5. Post-processing (Solid)")
        self.tabs.addTab(self.tab6, "6. Analiza FEM (Shell)")
        self.tabs.addTab(self.tab7, "7. Post-processing (Shell)")

        self.tab3.request_transfer.connect(self.tab4.receive_data)
        self.tab3.request_transfer.connect(lambda: self.tabs.setCurrentIndex(3))
        self.tab3.request_transfer_shell.connect(self.tab6.receive_data)
        self.tab3.request_transfer_shell.connect(lambda: self.tabs.setCurrentIndex(5))

        # Połączenie sygnałów z Tab4 (FEM Solid)
        self.tab4.batch_finished.connect(self.on_fem_finished)
        self.tab4.pilot_finished.connect(self.on_fem_pilot_finished)
        self.tab4.profile_started.connect(self.tab5.highlight_profile)
        
        self.tab6.analysis_finished.connect(self.on_shell_fem_finished)

    def on_fem_pilot_finished(self):
        """Slot wywoływany po zakończeniu pojedynczej analizy 'Pilot'."""
        self.tabs.setCurrentIndex(4) # Przełącz na Tab 5 (Post-processing)
        if hasattr(self, 'tab5'):
            self.tab5.refresh_list()
        if self.statusBar():
            self.statusBar().showMessage("✅ Pilot zakończony. Wynik dostępny w Post-processingu.", 10000)

    def on_fem_finished(self):
        self.tabs.setCurrentIndex(4) # Przełącz na Tab 5
        if hasattr(self, 'tab5'):
            self.tab5.refresh_list()
            
        if self.statusBar():
            self.statusBar().showMessage("✅ Analiza FEM zakończona. Wyniki gotowe.", 10000)

    def on_shell_fem_finished(self):
        self.tabs.setCurrentIndex(6) # Przełącz na Tab 7
        if hasattr(self, 'tab7'):
            self.tab7.refresh_list()
            
        if self.statusBar():
            self.statusBar().showMessage("✅ Analiza SHELL zakończona. Wyniki gotowe.", 10000)

    def closeEvent(self, event):
        """Przechwytuje zdarzenie zamknięcia okna, aby bezpiecznie zamknąć zasoby."""
        print("Zamykanie aplikacji, czyszczenie zasobów PyVista...")
        # Zamknięcie plotterów PyVista, aby uniknąć błędów vtkWin32OpenGLRenderWin
        if hasattr(self, 'tab4') and hasattr(self.tab4, 'plotter') and self.tab4.plotter:
            self.tab4.plotter.close()
        if hasattr(self, 'tab5') and hasattr(self.tab5, 'plotter') and self.tab5.plotter:
            self.tab5.plotter.close()
        if hasattr(self, 'tab6') and hasattr(self.tab6, 'plotter') and self.tab6.plotter:
            self.tab6.plotter.close()
        if hasattr(self, 'tab7') and hasattr(self.tab7, 'plotter') and self.tab7.plotter:
            self.tab7.plotter.close()
        event.accept()

# ==============================================================================
# ENTRY POINT (TO BYŁO BRAKUJĄCE)
# ==============================================================================

# Funkcja do wyłapywania błędów startowych (Silent Crash Fix)
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print("!!! KRYTYCZNY BŁĄD !!!", err_msg)
    
    # Próba wyświetlenia okna z błędem
    try:
        app = QApplication.instance()
        if not app: app = QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("Wystąpił krytyczny błąd aplikacji")
        msg.setInformativeText(str(exc_value))
        msg.setDetailedText(err_msg)
        msg.exec()
    except:
        pass
    sys.exit(1)

# Podpięcie łapacza błędów
sys.excepthook = handle_exception

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Konfiguracja ciemnego motywu
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
    
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)