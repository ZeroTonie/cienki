# -*- coding: utf-8 -*-
# ==============================================================================
# APP GUI v7.0 FINAL - "BULLETPROOF" EDITION
# ==============================================================================

import sys
import os
import glob
import json
import traceback
import importlib
import csv
from datetime import datetime
import gmsh
import subprocess

# --- DATA SCIENCE ---
import numpy as np
import pandas as pd

# --- PYQT6 ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QLabel, QPushButton, QFileDialog, QTableView, 
    QHeaderView, QLineEdit, QFormLayout, QGroupBox, QCheckBox, 
    QSplitter, QProgressBar, QTextBrowser, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QFrame, QComboBox, QColorDialog,
    QSizePolicy, QRadioButton, QButtonGroup, QStackedWidget,
    QMenu, QDoubleSpinBox, QSpinBox, QTableWidget, QTableWidgetItem, 
    QAbstractItemView, QTreeWidget, QTreeWidgetItem, QStyle, QSpacerItem, QGridLayout
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QUrl, QSize, QThread, 
    pyqtSignal, QTimer, QTime
)
from PyQt6.QtGui import (
    QColor, QPalette, QDesktopServices, QAction, 
    QFont, QBrush, QIcon
)

# --- MODUŁY LOKALNE ---
import config_solver
import material_catalogue
import engine_solver
import engine_geometry
import ccx_preparer

# --- WIZUALIZACJA (Fail-safe) ---
try:
    from pyvistaqt import QtInteractor
    HAS_PYVISTA = True
except ImportError:
    HAS_PYVISTA = False

try:
    import matplotlib
    matplotlib.use('qtagg')
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ==============================================================================
# MAPOWANIE NAZW I KONFIGURACJA
# ==============================================================================

# Tłumaczenie technicznych nazw kolumn na język inżynierski
HEADER_MAP = {
    # Identyfikacja
    "Nazwa_Profilu": ("Profil", "-"),
    "Stop": ("Materiał", "-"),
    "Status_Wymogow": ("Status", "-"),
    "Raport_Etap": ("Etap", "-"),
    
    # Wyniki Główne
    "Res_Masa_kg_m": ("Masa", "kg/m"),
    "Res_UR": ("Wytężenie UR", "-"),
    "Res_Max_VonMises": ("Sigma Red.", "MPa"),
    
    # Geometria
    "Input_Geo_tp": ("Grubość Płask.", "mm"),
    "Input_Geo_bp": ("Szerokość Płask.", "mm"),
    "Input_Geo_b_otw": ("Otwarcie", "mm"),
    
    # Stateczność
    "Calc_Nb_Rd": ("Nośność Nb", "N"),
    "Res_Stab_M_cr": ("Mcr (Zwich.)", "Nmm"),
    "Res_Stab_N_cr_min": ("Ncr (Min)", "N"),
    
    # Przemieszczenia
    "Res_Disp_U_y_max": ("Ugięcie Y", "mm"),
    "Res_Disp_U_z_max": ("Ugięcie Z", "mm"),
    "Res_Disp_Phi_deg": ("Skręcenie", "deg"),
    
    # Obciążenia
    "Input_Load_Fx": ("Siła Fx", "N"),
    "Calc_Fy": ("Siła Fy", "N"),
    "Calc_Fz": ("Siła Fz", "N"),
    
    # Kontrolne
    "PRZEKAZ": ("MES", "Przekaż"),
    "WYKLUCZ": ("Ukryj", "Ignoruj")
}

# ==============================================================================
# WIDGETY POMOCNICZE
# ==============================================================================

class CustomHeaderView(QHeaderView):
    """Nagłówek tabeli z sortowaniem i filtrowaniem."""
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsMovable(True)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive) 
        
    def mousePressEvent(self, event):
        idx = self.logicalIndexAt(event.pos())
        if idx == -1: super().mousePressEvent(event); return
        
        # Obsługa sortowania (prawa krawędź)
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
        if self.model() and logicalIndex < self.model().columnCount():
            # Rysowanie ikonki sortowania
            btn_rect = rect.adjusted(rect.width() - 20, 4, -4, -4)
            painter.setBrush(QColor(60, 60, 60))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(btn_rect, 3, 3)
            painter.setPen(QColor(220, 220, 220))
            font = painter.font(); font.setPixelSize(9); painter.setFont(font)
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "⇅")
        painter.restore()

class AdvancedPandasModel(QAbstractTableModel):
    """Model danych obsługujący Pandas DataFrame w Qt."""
    def __init__(self, df=pd.DataFrame()):
        super().__init__()
        self._df_original = df.copy()
        self._df = df.copy()
        self.use_scientific = False
        self.show_excluded = True
        self.highlight_row = -1
        self.highlight_col = -1
        self.colors = {
            "bg_base": QColor(30, 30, 30),
            "bg_alt": QColor(38, 38, 38),
            "bg_excluded": QColor(60, 25, 25),
            "bg_passed": QColor(25, 60, 25),
            "bg_sel": QColor(70, 70, 140),
            "text": QColor(230, 230, 230)
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
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section < len(self._df.columns):
                col_name = self._df.columns[section]
                if col_name in HEADER_MAP:
                    nazwa, jedn = HEADER_MAP[col_name]
                    return f"{nazwa}\n[{jedn}]"
                return str(col_name)
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return None
        
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        row, col = index.row(), index.column()
        col_name = self._df.columns[col]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col_name in ["PRZEKAZ", "WYKLUCZ"]: return None
            val = self._df.iloc[row, col]
            if isinstance(val, (int, float)):
                if self.use_scientific: return f"{val:.2e}"
                return f"{val:.4f}"
            return str(val)

        if role == Qt.ItemDataRole.CheckStateRole and col_name in ["PRZEKAZ", "WYKLUCZ"]:
            return Qt.CheckState.Checked if self._df.iloc[row, col] else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.BackgroundRole:
            if row == self.highlight_row or col == self.highlight_col: return self.colors["bg_sel"]
            if self._df.iloc[row]["WYKLUCZ"]: return self.colors["bg_excluded"]
            if self._df.iloc[row]["PRZEKAZ"]: return self.colors["bg_passed"]
            return self.colors["bg_alt"] if row % 2 else self.colors["bg_base"]

        if role == Qt.ItemDataRole.ForegroundRole: return self.colors["text"]
        return None

    def setData(self, index, value, role):
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole: return False
        col_name = self._df.columns[index.column()]
        if col_name in ["PRZEKAZ", "WYKLUCZ"]:
            new_val = (value == Qt.CheckState.Checked.value)
            self._df.iloc[index.row(), index.column()] = new_val
            # Sync with original
            real_idx = self._df.index[index.row()]
            if real_idx in self._df_original.index:
                c_idx = self._df_original.columns.get_loc(col_name)
                self._df_original.iloc[real_idx, c_idx] = new_val
            self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.BackgroundRole])
            return True
        return False

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._df.columns[index.column()] in ["PRZEKAZ", "WYKLUCZ"]:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def sort(self, column, order):
        colname = self._df.columns[column]
        self.layoutAboutToBeChanged.emit()
        self._df.sort_values(by=colname, ascending=(order == Qt.SortOrder.AscendingOrder), inplace=True)
        self.layoutChanged.emit()

    def set_scientific_notation(self, enable): self.use_scientific = enable; self.layoutChanged.emit()
    def set_highlight(self, row, col): self.highlight_row = row; self.highlight_col = col; self.layoutChanged.emit()
    def set_highlight_col_only(self, col): self.highlight_row = -1; self.highlight_col = col; self.layoutChanged.emit()
    
    def toggle_column_all(self, col_name):
        if col_name not in self._df.columns: return
        self.layoutAboutToBeChanged.emit()
        curr = self._df[col_name].iloc[0] if len(self._df) > 0 else False
        self._df[col_name] = not curr
        self._df_original.loc[self._df.index, col_name] = not curr
        self.layoutChanged.emit()

    def apply_advanced_filter(self, filters_list, show_excluded):
        self.layoutAboutToBeChanged.emit()
        df_t = self._df_original.copy()
        if not show_excluded:
            df_t = df_t[ (df_t["WYKLUCZ"] == False) | (df_t["WYKLUCZ"] == 0) ]
        
        for col, vmin, vmax in filters_list:
            if col in df_t.columns:
                try:
                    df_t[col] = pd.to_numeric(df_t[col], errors='coerce')
                    if vmin is not None: df_t = df_t[df_t[col] >= vmin]
                    if vmax is not None: df_t = df_t[df_t[col] <= vmax]
                except: pass
        self._df = df_t
        self.layoutChanged.emit()

# ==============================================================================
# SEKCJA WORKERÓW (WĄTKI TŁA)
# ==============================================================================

class OptimizationWorker(QThread):
    """Wątek dla Solvera Analitycznego (Tab 1)."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    found_file_signal = pyqtSignal(str)

    def __init__(self, router_instance):
        super().__init__()
        self.router = router_instance

    def run(self):
        # --- POPRAWKA: Definicja zmiennej PRZED blokami try/class ---
        original_stdout = sys.__stdout__ 
        
        # Klasa wewnętrzna do przechwytywania printów
        class StreamToSignal:
            def __init__(self, s): self.s = s
            def write(self, t): 
                try: self.s.emit(str(t)); original_stdout.write(str(t))
                except: pass
            def flush(self): original_stdout.flush()
        
        # Podmiana sys.stdout
        sys.stdout = StreamToSignal(self.log_signal)
        
        try:
            self.log_signal.emit(">>> Inicjalizacja Solvera Analitycznego...\n")
            
            # Przeładowanie modułów
            import config_solver; importlib.reload(config_solver)
            
            # Pobranie nazwy solvera
            module_name = getattr(config_solver, "SELECTED_SOLVER_MODULE", "solver_1_standard")
            self.log_signal.emit(f">>> Wybrano silnik: {module_name}\n")
            
            import engine_solver; importlib.reload(engine_solver)
            
            if importlib.util.find_spec(module_name) is None:
                raise ImportError(f"Nie znaleziono modułu solvera: {module_name}")
                
            solver_module = importlib.import_module(module_name)
            importlib.reload(solver_module)
            
            self.log_signal.emit(">>> Start obliczeń...\n")
            path = solver_module.glowna_petla_optymalizacyjna(router_instance=self.router)
            
            if path: self.found_file_signal.emit(str(path))
            self.finished_signal.emit(True, str(path))
            
        except Exception as e:
            # Tutaj błąd występował, bo original_stdout nie był widoczny
            sys.stdout = original_stdout 
            self.log_signal.emit(f"\n!!! BŁĄD KRYTYCZNY SOLVERA !!!\n{traceback.format_exc()}")
            self.finished_signal.emit(False, "")
        finally:
            # Przywrócenie standardowego wyjścia
            sys.stdout = original_stdout

class FemWorker(QThread):
    """
    Wątek dla Solvera FEM (Tab 4).
    Deleguje całą pracę do engine_geometry i ccx_preparer.
    """
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    preview_signal = pyqtSignal(dict)
    
    def __init__(self, candidates, settings, router_instance):
        super().__init__()
        self.candidates = candidates
        self.settings = settings
        self.router = router_instance
        self.is_running = True
        
    def stop(self):
        self.is_running = False

    def run(self):
        self.log_signal.emit(">>> START PROCEDURY WSADOWEJ FEM...")
        success_count = 0
        
        for i, cand in enumerate(self.candidates):
            if not self.is_running: 
                self.log_signal.emit(">>> Przerwano przez użytkownika.")
                break

            model_name = f"{cand.get('Nazwa_Profilu', f'Case_{i}')}_tp{cand.get('Input_Geo_tp', 0)}"
            self.log_signal.emit(f"\n" + "="*60)
            self.log_signal.emit(f"   PRZETWARZANIE: {model_name} ({i+1}/{len(self.candidates)})")
            self.log_signal.emit("="*60)

            try:
                fem_dir = self.router.get_path("FEM", create=True)
                job_name = model_name

                # --- 1. GEOMETRIA (GMSH) ---
                self.log_signal.emit("1. Generowanie geometrii i siatki (Engine Geometry)...")
                geo_p = {
                    "L": float(cand.get("Input_Load_L", 1800.0)),
                    "tp": float(cand.get("Input_Geo_tp", 10.0)),
                    "bp": float(cand.get("Input_Geo_bp", 300.0)),
                    "hc": float(cand.get("Input_UPE_hc", 200.0)),
                    "bc": float(cand.get("Input_UPE_bc", 80.0)),
                    "twc": float(cand.get("Input_UPE_twc", 6.0)),
                    "tfc": float(cand.get("Input_UPE_tfc", 11.0)),
                    "yc_global": float(cand.get("Res_Geo_Ys", 0.0)) + float(cand.get("Res_Geo_Delta_Ys", 0.0))
                }
                
                # Wywołanie zewnętrznego generatora
                geo_results = engine_geometry.create_and_mesh_model(geo_p, self.settings, job_name, fem_dir)
                self.log_signal.emit(f"   [OK] Siatka: {geo_results['msh_file']}")
                self.preview_signal.emit(geo_results)

                # --- 2. PREPARACJA CALCULIX ---
                self.log_signal.emit("2. Przygotowanie pliku .inp (CCX Preparer)...")
                inp_path = os.path.join(fem_dir, f"{job_name}.inp")
                
                mat_name = cand.get("Stop", "S355")
                mat_props = material_catalogue.baza_materialow().get(mat_name, {})
                mat_p = { "name": mat_name, "E": mat_props.get('E', 210000), "nu": 0.3 }
                
                r = float(cand.get("Input_Load_F_promien", 0.0))
                ys = float(cand.get("Res_Geo_Ys", 0.0))
                # yc_global z geometrii
                yc_glob = geo_p['yc_global'] 
                
                # Obliczenie momentów
                Fy = float(cand.get("Calc_Fy", 0.0))
                Fx = float(cand.get("Input_Load_Fx", 0.0))
                
                load_p = {
                    "Fx": Fx,
                    "Fy": Fy,
                    "Fz": float(cand.get("Calc_Fz", 0.0)),
                    "Mx": Fy * (r + yc_glob - ys), # Ms = Fy * ramię_skrętne
                    "My": 0.0, 
                    "Mz": Fx * r # Moment gnący od Fx (mimośród)
                }

                ccx_preparer.generate_inp_file(job_name, inp_path, geo_results, mat_p, load_p, self.settings)
                self.log_signal.emit(f"   [OK] Plik .inp gotowy.")

                # --- 3. URUCHOMIENIE CALCULIX ---
                self.log_signal.emit(f"3. Uruchamianie solvera CCX...")
                ccx_path = os.path.join(os.getcwd(), "ccx", "ccx.exe")
                if not os.path.exists(ccx_path):
                    ccx_path = "ccx" # Fallback to PATH

                proc = subprocess.run(
                    [ccx_path, "-i", job_name],
                    cwd=fem_dir,
                    capture_output=True, text=True, encoding='utf-8'
                )

                if proc.returncode == 0:
                    self.log_signal.emit(f"   [OK] Obliczenia zakończone.")
                    success_count += 1
                else:
                    self.log_signal.emit(f"   [BŁĄD] Kod błędu: {proc.returncode}")
                    self.log_signal.emit(proc.stdout)
                    self.log_signal.emit(proc.stderr)
                
            except Exception as e:
                self.log_signal.emit(f"!!! FEM ERROR: {str(e)}")
                self.log_signal.emit(traceback.format_exc())
        
        self.log_signal.emit(f"\n>>> ZAKOŃCZONO. Sukces: {success_count}/{len(self.candidates)}")
        self.finished_signal.emit(True)

# ==============================================================================
# TAB 1: DASHBOARD (Z ScrollArea)
# ==============================================================================

class Tab1_Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.profile_widgets = []
        self.init_ui()

    def init_ui(self):
        # Główny layout poziomy: Panel Lewy (Scroll) | Panel Prawy (Logi)
        main_layout = QHBoxLayout(self)
        
        # --- LEWA STRONA (Scroll Area) ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.setSpacing(15)
        
        # 1. Obciążenia
        g_load = QGroupBox("1. Obciążenia i Parametry Materiałowe")
        fl_load = QFormLayout(g_load)
        
        self.inp_Fx = QDoubleSpinBox(); self.inp_Fx.setRange(0, 1e9); self.inp_Fx.setValue(24000.0); self.inp_Fx.setMaximumWidth(120)
        self.inp_Fx.setToolTip("Siła osiowa ściskająca [N] przyłożona na mimośrodzie.")
        
        self.inp_L = QDoubleSpinBox(); self.inp_L.setRange(100, 1e5); self.inp_L.setValue(1800.0); self.inp_L.setMaximumWidth(120)
        self.inp_L.setToolTip("Długość fizyczna słupa [mm].")
        
        self.inp_Promien = QDoubleSpinBox(); self.inp_Promien.setRange(-1e5, 1e5); self.inp_Promien.setValue(450.0); self.inp_Promien.setMaximumWidth(120)
        self.inp_Promien.setToolTip("Ramię działania siły (mimośród) [mm] względem osi płaskownika.")
        
        self.inp_Ty = QDoubleSpinBox(); self.inp_Ty.setValue(0.2); self.inp_Ty.setSingleStep(0.05); self.inp_Ty.setMaximumWidth(120)
        self.inp_Ty.setToolTip("Współczynnik siły poprzecznej Ty (Fy = Fx * w_Ty).")
        
        self.inp_Tz = QDoubleSpinBox(); self.inp_Tz.setValue(0.2); self.inp_Tz.setSingleStep(0.05); self.inp_Tz.setMaximumWidth(120)
        self.inp_Tz.setToolTip("Współczynnik siły poprzecznej Tz (Fz = Fx * w_Tz).")
        
        fl_load.addRow("Siła Osiowa Fx [N]:", self.inp_Fx)
        fl_load.addRow("Długość L [mm]:", self.inp_L)
        fl_load.addRow("Mimośród Siły [mm]:", self.inp_Promien)
        fl_load.addRow("Wsp. Siły Poprz. Ty:", self.inp_Ty)
        fl_load.addRow("Wsp. Siły Poprz. Tz:", self.inp_Tz)
        
        # Bezpieczeństwo
        h_safe = QHBoxLayout()
        self.inp_GM0 = QDoubleSpinBox(); self.inp_GM0.setValue(1.0); self.inp_GM0.setMaximumWidth(70); self.inp_GM0.setToolTip("Wsp. Gamma M0")
        self.inp_GM1 = QDoubleSpinBox(); self.inp_GM1.setValue(1.0); self.inp_GM1.setMaximumWidth(70); self.inp_GM1.setToolTip("Wsp. Gamma M1")
        self.inp_Alfa = QDoubleSpinBox(); self.inp_Alfa.setValue(0.49); self.inp_Alfa.setMaximumWidth(70); self.inp_Alfa.setToolTip("Imperfeckja (alfa)")
        
        h_safe.addWidget(QLabel("GM0:")); h_safe.addWidget(self.inp_GM0)
        h_safe.addWidget(QLabel("GM1:")); h_safe.addWidget(self.inp_GM1)
        h_safe.addWidget(QLabel("Alfa:")); h_safe.addWidget(self.inp_Alfa)
        h_safe.addStretch()
        fl_load.addRow("Wsp. Bezpieczeństwa:", h_safe)
        
        left_layout.addWidget(g_load)
        
        # 2. Tryb Pracy
        g_mode = QGroupBox("Tryb Pracy")
        hl_mode = QHBoxLayout(g_mode)
        self.rb_auto = QRadioButton("🤖 AUTOMAT (Optymalizacja)"); self.rb_auto.setChecked(True)
        self.rb_manual = QRadioButton("📐 MANUAL (Sprawdzenie)")
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.rb_auto, 0); self.mode_group.addButton(self.rb_manual, 1)
        self.mode_group.idToggled.connect(self.on_mode_changed)
        hl_mode.addWidget(self.rb_auto); hl_mode.addStretch(); hl_mode.addWidget(self.rb_manual)
        left_layout.addWidget(g_mode)
        
        # 3. Stack (Zmienna zawartość)
        self.stack = QStackedWidget()
        
        # --- STRONA AUTO ---
        page_auto = QWidget(); l_auto = QVBoxLayout(page_auto); l_auto.setContentsMargins(0,0,0,0)
        
        # Materiały
        g_mat = QGroupBox("2. Materiały"); l_mat = QVBoxLayout(g_mat)
        self.material_selector = MaterialSelectorWidget()
        l_mat.addWidget(self.material_selector)
        l_auto.addWidget(g_mat)
        
        # Parametry Optymalizacji
        g_opt = QGroupBox("3. Algorytm i Strategia Optymalizacji (Waga -> Pareto)")
        
        # Używamy Grid Layout dla dwóch kolumn
        grid_opt = QGridLayout(g_opt)
        grid_opt.setColumnStretch(1, 1) # Kolumna inputów 1
        grid_opt.setColumnStretch(3, 1) # Kolumna inputów 2
        
        # -- Kolumna Lewa: Geometria Graniczna --
        self.inp_MinOtw = QDoubleSpinBox(); self.inp_MinOtw.setValue(70.0); self.inp_MinOtw.setMaximumWidth(90)
        self.inp_MinOtw.setToolTip("Minimalny prześwit wewnątrz słupa [mm].\nDecyduje o możliwości spawania od środka.")
        
        self.inp_MaxTp = QDoubleSpinBox(); self.inp_MaxTp.setValue(25.0); self.inp_MaxTp.setMaximumWidth(90)
        self.inp_MaxTp.setToolTip("Maksymalna grubość płaskownika brana do analizy [mm].\nGrubsze warianty zostaną pominięte.")
        
        self.combo_solver = QComboBox(); self.combo_solver.setMaximumWidth(150)
        self.combo_solver.setToolTip("Wybierz moduł solvera analitycznego (skrypt Pythona w folderze głównym).")
        self.refresh_solvers() # Funkcja do napisania niżej
        
        grid_opt.addWidget(QLabel("Min. Otwarcie [mm]:"), 0, 0)
        grid_opt.addWidget(self.inp_MinOtw, 0, 1)
        grid_opt.addWidget(QLabel("Max. Grubość Płask. [mm]:"), 1, 0)
        grid_opt.addWidget(self.inp_MaxTp, 1, 1)
        grid_opt.addWidget(QLabel("Silnik Solvera:"), 2, 0)
        grid_opt.addWidget(self.combo_solver, 2, 1)
        
        # -- Kolumna Prawa: Parametry Pętli Szukania --
        # Dodajemy brakujące parametry z solver_1_standard.py
        
        self.inp_Offset = QSpinBox(); self.inp_Offset.setValue(2); self.inp_Offset.setMaximumWidth(90)
        self.inp_Offset.setToolTip("Offset Startowy (Tabela Grubości).\nO ile pozycji w tabeli grubości cofnąć się względem optimum poprzedniego profilu.\nWiększa wartość = dokładniejsze, ale wolniejsze szukanie.")
        
        self.inp_KrokOtw = QDoubleSpinBox(); self.inp_KrokOtw.setValue(10.0); self.inp_KrokOtw.setMaximumWidth(90)
        self.inp_KrokOtw.setToolTip("Krok poszerzania [mm].\nO ile mm zwiększać szerokość w pętli szukania max nośności.")
        
        self.inp_LimitOtw = QDoubleSpinBox(); self.inp_LimitOtw.setValue(1.5); self.inp_LimitOtw.setSingleStep(0.1); self.inp_LimitOtw.setMaximumWidth(90)
        self.inp_LimitOtw.setToolTip("Limit poszerzania (Mnożnik x MinOtwarcie).\nNp. 1.5 oznacza, że sprawdzamy otwarcia do 1.5 * 70mm = 105mm.")
        
        self.inp_MaxWzrost = QSpinBox(); self.inp_MaxWzrost.setValue(2); self.inp_MaxWzrost.setMaximumWidth(90)
        self.inp_MaxWzrost.setToolTip("Warunek Stopu (Max Wzrostów Masy).\nIle razy z rzędu masa minimalna może wzrosnąć w kolejnych profilach,\nzanim przerwiemy symulację (zakładając, że optimum już minęliśmy).")

        grid_opt.addWidget(QLabel("Offset Startowy (Index):"), 0, 2)
        grid_opt.addWidget(self.inp_Offset, 0, 3)
        grid_opt.addWidget(QLabel("Krok Poszerzania [mm]:"), 1, 2)
        grid_opt.addWidget(self.inp_KrokOtw, 1, 3)
        grid_opt.addWidget(QLabel("Limit Poszerzania (Mnożnik):"), 2, 2)
        grid_opt.addWidget(self.inp_LimitOtw, 2, 3)
        grid_opt.addWidget(QLabel("Max Wzrostów Masy (Stop):"), 3, 2)
        grid_opt.addWidget(self.inp_MaxWzrost, 3, 3)
        
        l_auto.addWidget(g_opt)
        
        # Zapis
        g_save = QGroupBox("4. Projekt")
        fs = QFormLayout(g_save)
        self.inp_ProjName = QLineEdit(""); self.inp_ProjName.setPlaceholderText("Auto_Project...")
        self.chk_Wspolny = QCheckBox("Wspólny folder wyników")
        fs.addRow("Nazwa Projektu:", self.inp_ProjName)
        fs.addRow("", self.chk_Wspolny)
        l_auto.addWidget(g_save)
        
        l_auto.addStretch()
        self.stack.addWidget(page_auto)
        
        # --- STRONA MANUAL ---
        page_man = QWidget(); l_man = QVBoxLayout(page_man); l_man.setContentsMargins(0,0,0,0)
        
        lbl_man = QLabel("Dodaj konkretne profile do sprawdzenia:")
        l_man.addWidget(lbl_man)
        
        self.scroll_prof = QScrollArea(); self.scroll_prof.setWidgetResizable(True)
        self.prof_cont = QWidget(); self.prof_lay = QVBoxLayout(self.prof_cont); self.prof_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_prof.setWidget(self.prof_cont)
        
        l_man.addWidget(self.scroll_prof)
        
        btn_add_prof = QPushButton("+ Dodaj Profil Manualny")
        btn_add_prof.clicked.connect(self.add_manual_profile)
        l_man.addWidget(btn_add_prof)
        
        self.stack.addWidget(page_man)
        self.add_manual_profile() # Dodaj jeden domyślny
        
        left_layout.addWidget(self.stack)
        scroll.setWidget(left_content)
        
        # --- PRAWA STRONA (Logi i Start) ---
        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        
        self.btn_run = QPushButton("URUCHOM OPTYMALIZACJĘ 🚀")
        self.btn_run.setFixedHeight(60)
        self.btn_run.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
        self.btn_run.clicked.connect(self.run_process)
        
        self.console = QTextBrowser()
        self.console.setStyleSheet("background:#1e1e1e; color:#00ff00; font-family:Consolas; font-size:12px; border: 1px solid #444;")
        self.console.setMaximumHeight(400)
        self.console.setOpenExternalLinks(False)
        self.console.anchorClicked.connect(self.on_link_clicked)
        
        self.progress = QProgressBar()
        self.progress.setStyleSheet("QProgressBar::chunk { background-color: #27ae60; }")
        self.progress.setTextVisible(True)
        
        right_layout.addWidget(QLabel("<b>Logi Systemowe:</b>"))
        right_layout.addWidget(self.console)
        right_layout.addWidget(self.progress)
        right_layout.addWidget(self.btn_run)
        
        # SPLITTER GŁÓWNY
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(right_content)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        
        main_layout.addWidget(splitter)

    def refresh_solvers(self):
        self.combo_solver.clear()
        # Szukamy plików zaczynających się od 'solver_' w bieżącym katalogu
        files = glob.glob("solver_*.py")
        if not files:
            self.combo_solver.addItem("solver_1_standard") # Domyślny
            return
            
        for f in files:
            # Usuwamy rozszerzenie .py
            name = os.path.splitext(os.path.basename(f))[0]
            self.combo_solver.addItem(name)
            
        # Próbujemy ustawić domyślny standardowy
        idx = self.combo_solver.findText("solver_1_standard")
        if idx >= 0: self.combo_solver.setCurrentIndex(idx)
    
    # --- LOGIKA UI ---
    def on_mode_changed(self, id, checked):
        if checked:
            self.stack.setCurrentIndex(id)
            if id == 0:
                self.btn_run.setText("URUCHOM OPTYMALIZACJĘ 🚀")
                self.btn_run.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
            else:
                self.btn_run.setText("OBLICZ PROFILE RĘCZNIE 📐")
                self.btn_run.setStyleSheet("background-color: #d35400; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")

    def add_manual_profile(self):
        w = SingleProfileWidget(len(self.profile_widgets)+1)
        self.prof_lay.addWidget(w)
        self.profile_widgets.append(w)

    def save_config(self):
        mats = self.material_selector.get_selected_materials()
        if self.mode_group.checkedId() == 0 and not mats:
            QMessageBox.warning(self, "Błąd", "Wybierz przynajmniej jeden materiał!")
            return False
            
        # Pobieramy nazwę wybranego modułu solvera
        selected_solver = self.combo_solver.currentText()
            
        # Zapis pliku config_solver.py z pełnym zestawem parametrów
        cfg = f"""# AUTO-GENERATED CONFIG
LOAD_PARAMS = {{ "Fx": {self.inp_Fx.value()}, "F_promien": {self.inp_Promien.value()}, "L": {self.inp_L.value()}, "w_Ty": {self.inp_Ty.value()}, "w_Tz": {self.inp_Tz.value()} }}
LISTA_MATERIALOW = {mats if self.mode_group.checkedId()==0 else []}
MIN_SZEROKOSC_OTWARCIA = {self.inp_MinOtw.value()}
MAX_GRUBOSC_PLASKOWNIKA = {self.inp_MaxTp.value()}
SAFETY_PARAMS = {{ "gamma_M0": {self.inp_GM0.value()}, "gamma_M1": {self.inp_GM1.value()}, "alfa_imp": {self.inp_Alfa.value()} }}
NAZWA_BADANIA = "{self.inp_ProjName.text()}"
WSPOLNY_KATALOG = {self.chk_Wspolny.isChecked()}
POKAZUJ_KROKI_POSREDNIE = False

# --- PARAMETRY STERUJĄCE OPTYMALIZACJĄ ---
START_SEARCH_OFFSET = {self.inp_Offset.value()}
KROK_POSZERZANIA = {self.inp_KrokOtw.value()}
LIMIT_POSZERZANIA = {self.inp_LimitOtw.value()}
MAX_N_WZROSTOW_WAGI = {self.inp_MaxWzrost.value()}
ILE_KROKOW_W_GORE = 2 # Domyślnie, można też dodać do GUI
SELECTED_SOLVER_MODULE = "{selected_solver}"
"""
        try:
            with open("config_solver.py", "w", encoding="utf-8") as f:
                f.write(cfg)
            return True
        except Exception as e:
            self.console.append(f"Błąd zapisu configu: {e}")
            return False

    def run_process(self):
        self.console.clear()
        if self.mode_group.checkedId() == 0: # AUTO
            if not self.save_config(): return
            
            pname = self.inp_ProjName.text() or f"Auto_{datetime.now().strftime('%H%M%S')}"
            router.set_project(pname)
            
            self.worker = OptimizationWorker(router)
            self.worker.log_signal.connect(self.console.append)
            self.worker.finished_signal.connect(self.on_finished)
            self.worker.found_file_signal.connect(lambda p: setattr(self, 'last_res_path', p))
            
            self.btn_run.setEnabled(False)
            self.progress.setValue(10)
            self.worker.start()
            
        else: # MANUAL
            self.run_manual_calculation()

    def run_manual_calculation(self):
        self.console.append(">>> Uruchamianie trybu manualnego...")
        router.set_project(f"Manual_{datetime.now().strftime('%H%M%S')}")
        
        # Zbieranie danych wspólnych
        load_data = {
            "Fx": self.inp_Fx.value(), "L": self.inp_L.value(), "F_promien": self.inp_Promien.value(),
            "w_Ty": self.inp_Ty.value(), "w_Tz": self.inp_Tz.value(), 
            "gamma_M0": self.inp_GM0.value(), "gamma_M1": self.inp_GM1.value(), "alfa_imp": self.inp_Alfa.value()
        }
        
        results = []
        try:
            # Przeładowanie silnika
            import engine_solver
            importlib.reload(engine_solver)
            import material_catalogue
            
            self.progress.setValue(10)
            
            for i, w in enumerate(self.profile_widgets):
                d = w.get_data()
                self.console.append(f"   Obliczanie: {d['Profil']} ({d['Material']})...")
                
                mat_db = material_catalogue.baza_materialow().get(d['Material'])
                prof_db = material_catalogue.pobierz_ceownik(d['Profil'])
                
                if not mat_db: 
                    self.console.append(f"   ! Błąd: Brak materiału {d['Material']}")
                    continue
                if not prof_db:
                    self.console.append(f"   ! Błąd: Brak profilu {d['Profil']}")
                    continue
                
                # Scalanie
                full_load = {**load_data, **mat_db}
                geo = {"tp": d['tp'], "bp": d['bp']}
                
                # Obliczenia
                res = engine_solver.analizuj_przekroj_pelna_dokladnosc(prof_db, geo, full_load, load_data)
                masa = engine_solver.oblicz_mase_metra(prof_db, geo, full_load)
                
                # Spłaszczanie
                flat = engine_solver.splaszcz_wyniki_do_wiersza(prof_db, geo, full_load, load_data, res)
                
                # Uzupełnianie pól wymaganych przez GUI
                flat["Nazwa_Profilu"] = d['Profil']
                flat["Stop"] = d['Material']
                flat["Res_Masa_kg_m"] = masa
                flat["Input_Geo_b_otw"] = d['b_otw']
                flat["Calc_Fy"] = full_load["Fx"] * full_load["w_Ty"]
                flat["Calc_Fz"] = full_load["Fx"] * full_load["w_Tz"]
                flat["Status_Wymogow"] = "SPEŁNIA" if res['Wskazniki']['UR'] <= 1.0 else "NIE SPEŁNIA"
                flat["Raport_Etap"] = "MANUAL"
                
                results.append(flat)
                self.progress.setValue(10 + int(80*(i+1)/len(self.profile_widgets)))
            
            if results:
                path = router.get_path("ANALYTICAL", "manual_results.csv")
                pd.DataFrame(results).to_csv(path, index=False)
                self.last_res_path = path
                self.on_finished(True, path)
            else:
                self.console.append("Brak wyników do zapisania.")
                self.progress.setValue(0)
                
        except Exception as e:
            self.console.append(f"Błąd manualny: {e}")
            self.console.append(traceback.format_exc())
            self.progress.setValue(0)

    def on_finished(self, success, path):
        self.btn_run.setEnabled(True)
        if success:
            self.progress.setValue(100)
            self.console.append(f"<b style='color:#0f0'>ZAKOŃCZONO POMYŚLNIE.</b>")
            self.console.append(f"Plik: {path}")
            self.console.append('<a href="goto_results" style="color:#3498db; font-size:14px;">>>> KLIKNIJ, ABY ZOBACZYĆ WYNIKI <<<</a>')
        else:
            self.progress.setValue(0)
            self.console.append("<b style='color:red'>ZAKOŃCZONO Z BŁĘDEM.</b>")

    def on_link_clicked(self, url):
        if url.toString() == "goto_results":
            mw = self.window()
            mw.tabs.setCurrentIndex(2) # Przełącz na Tab 3
            if hasattr(self, 'last_res_path'):
                mw.tab3.load_csv(self.last_res_path)

class MaterialSelectorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        l.setContentsMargins(0,0,0,0)
        
        self.btn_add = QPushButton(" + Wybierz Materiał z Bazy")
        self.btn_add.setStyleSheet("background-color: #27ae60; color: white; padding: 6px;")
        
        self.menu = QMenu(self)
        self.btn_add.setMenu(self.menu)
        l.addWidget(self.btn_add)
        
        self.list = QListWidget()
        self.list.setFixedHeight(80)
        l.addWidget(self.list)
        
        self.refresh_menu()
        self.add_item("S355")

    def refresh_menu(self):
        self.menu.clear()
        try:
            db = material_catalogue.baza_materialow()
            gr = {}
            for k, v in db.items():
                t = v.get("Typ", "Inne")
                if t not in gr: gr[t] = []
                gr[t].append(k)
            
            for g in sorted(gr.keys()):
                sub = self.menu.addMenu(g)
                for m in sorted(gr[g]):
                    a = sub.addAction(m)
                    a.triggered.connect(lambda ch, x=m: self.add_item(x))
        except: pass

    def add_item(self, name):
        exist = [self.list.item(i).text() for i in range(self.list.count())]
        if name not in exist:
            self.list.addItem(name)

    def get_selected_materials(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

class SingleProfileWidget(QGroupBox):
    def __init__(self, idx):
        super().__init__(f"Profil Manualny #{idx}")
        self.setStyleSheet("QGroupBox { border: 1px solid #555; margin-top: 10px; font-weight: bold; }")
        l = QFormLayout()
        l.setContentsMargins(10, 10, 10, 10)
        
        self.c_mat = QComboBox()
        try:
            for m in sorted(material_catalogue.baza_materialow().keys()): self.c_mat.addItem(m)
        except: pass
        self.c_mat.setMaximumWidth(150)
        
        self.i_prof = QLineEdit("UPE200"); self.i_prof.setMaximumWidth(100)
        self.i_tp = QDoubleSpinBox(); self.i_tp.setValue(10); self.i_tp.setMaximumWidth(100)
        self.i_bp = QDoubleSpinBox(); self.i_bp.setValue(300); self.i_bp.setRange(10,1000); self.i_bp.setMaximumWidth(100)
        self.i_otw = QDoubleSpinBox(); self.i_otw.setValue(100); self.i_otw.setRange(10,1000); self.i_otw.setMaximumWidth(100)
        
        l.addRow("Materiał:", self.c_mat)
        l.addRow("Profil (Symbol):", self.i_prof)
        l.addRow("Grubość Płask. [mm]:", self.i_tp)
        l.addRow("Szerokość Płask. [mm]:", self.i_bp)
        l.addRow("Otwarcie [mm]:", self.i_otw) # Informacyjnie dla usera
        self.setLayout(l)

    def get_data(self):
        return {
            "Material": self.c_mat.currentText(),
            "Profil": self.i_prof.text(),
            "tp": self.i_tp.value(),
            "bp": self.i_bp.value(),
            "b_otw": self.i_otw.value()
        }

# ==============================================================================
# TAB 2: WIEDZA
# ==============================================================================

class Tab2_Knowledge(QWidget):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        
        lbl = QLabel("Baza Wiedzy (Dokumentacja Techniczna)")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #ccc;")
        l.addWidget(lbl)
        
        self.list = QListWidget()
        self.list.setStyleSheet("background: #252525; padding: 10px; font-size: 13px;")
        self.list.itemDoubleClicked.connect(lambda i: QDesktopServices.openUrl(QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole))))
        l.addWidget(self.list)
        
        b = QPushButton("🔄 Odśwież"); b.clicked.connect(self.refresh)
        l.addWidget(b)
        self.refresh()

    def refresh(self):
        self.list.clear()
        files = glob.glob("*.pdf") + glob.glob("Baza wiedzy/*") + glob.glob("*.ipynb")
        if not files: self.list.addItem("Brak plików w folderze roboczym.")
        for f in files:
            ic = "📓" if f.endswith(".ipynb") else "📄"
            item = QListWidgetItem(f"{ic}  {os.path.basename(f)}")
            item.setData(Qt.ItemDataRole.UserRole, os.path.abspath(f))
            self.list.addItem(item)

# ==============================================================================
# TAB 3: SELEKCJA (Filtr Kropka/Przecinek)
# ==============================================================================

class Tab3_Selector(QWidget):
    request_transfer = pyqtSignal(list)
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        
        # Toolbar
        h = QHBoxLayout()
        b_load = QPushButton("📂 Wczytaj CSV"); b_load.clicked.connect(lambda: self.load_csv())
        
        lbl_hint = QLabel("💡 Filtry obsługują kropkę (.) i przecinek (,)")
        lbl_hint.setStyleSheet("color: #aaa; font-style: italic; margin-left: 15px;")
        
        b_send = QPushButton("PRZEKAŻ DO ANALIZY MES ➡️")
        b_send.setStyleSheet("background-color: #27ae60; font-weight: bold; padding: 8px 15px;")
        b_send.clicked.connect(self.send)
        
        h.addWidget(b_load); h.addWidget(lbl_hint); h.addStretch(); h.addWidget(b_send)
        l.addLayout(h)
        
        # Splitter
        spl = QSplitter()
        l.addWidget(spl)
        
        # Panel filtrów
        w_fil = QWidget(); l_fil = QVBoxLayout(w_fil)
        self.area_fil = QVBoxLayout(); self.area_fil.setAlignment(Qt.AlignmentFlag.AlignTop)
        l_fil.addLayout(self.area_fil)
        
        b_addf = QPushButton("+ Dodaj Filtr"); b_addf.clicked.connect(self.add_fil)
        b_apply = QPushButton("Zastosuj Filtry"); b_apply.clicked.connect(self.apply)
        self.chk_hidden = QCheckBox("Pokaż ukryte (WYKLUCZ)"); self.chk_hidden.setChecked(True); self.chk_hidden.clicked.connect(self.apply)
        
        l_fil.addWidget(b_addf); l_fil.addWidget(self.chk_hidden); l_fil.addWidget(b_apply)
        
        # Masowe
        g_mass = QGroupBox("Masowe Zaznaczanie")
        lm = QVBoxLayout(g_mass)
        h1 = QHBoxLayout(); b1=QPushButton("All FEM"); b1.clicked.connect(lambda: self.bulk("PRZEKAZ",1)); b2=QPushButton("No FEM"); b2.clicked.connect(lambda: self.bulk("PRZEKAZ",0)); h1.addWidget(b1); h1.addWidget(b2)
        h2 = QHBoxLayout(); b3=QPushButton("All Hide"); b3.clicked.connect(lambda: self.bulk("WYKLUCZ",1)); b4=QPushButton("No Hide"); b4.clicked.connect(lambda: self.bulk("WYKLUCZ",0)); h2.addWidget(b3); h2.addWidget(b4)
        lm.addLayout(h1); lm.addLayout(h2)
        l_fil.addWidget(g_mass); l_fil.addStretch()
        
        spl.addWidget(w_fil)
        
        # Tabela
        self.tab = QTableView(); self.head = CustomHeaderView(); self.tab.setHorizontalHeader(self.head)
        self.tab.setAlternatingRowColors(True)
        spl.addWidget(self.tab)
        
        # Detale
        self.det = QTextBrowser()
        spl.addWidget(self.det)
        spl.setSizes([250, 800, 300])

    def load_csv(self, path=None):
        if not path: path, _ = QFileDialog.getOpenFileName(self, "CSV", "", "*.csv")
        if path:
            try:
                df = pd.read_csv(path)
                self.model = AdvancedPandasModel(df)
                self.tab.setModel(self.model)
                self.cols = list(df.columns)
                self.tab.selectionModel().currentChanged.connect(self.click)
            except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

    def add_fil(self): 
        if hasattr(self, 'cols'): self.area_fil.addWidget(FilterWidget(columns=self.cols))

    def apply(self):
        if not hasattr(self, 'model'): return
        fs = []
        for i in range(self.area_fil.count()):
            w = self.area_fil.itemAt(i).widget()
            if isinstance(w, FilterWidget):
                col = w.combo_col.currentText()
                # Obsługa przecinka
                mn_s = w.inp_min.text().replace(',', '.')
                mx_s = w.inp_max.text().replace(',', '.')
                mn = float(mn_s) if mn_s else None
                mx = float(mx_s) if mx_s else None
                fs.append((col, mn, mx))
        self.model.apply_advanced_filter(fs, self.chk_hidden.isChecked())

    def bulk(self, col, val):
        if hasattr(self, 'model'): self.model.toggle_column_all(col)

    def click(self, c, p):
        if not c.isValid(): return
        r = self.model._df.iloc[c.row()]
        t = "<h3>Szczegóły</h3>"
        for k, v in r.items(): t += f"<b>{k}:</b> {v}<br>"
        self.det.setHtml(t)

    def send(self):
        if not hasattr(self, 'model'): return
        sel = self.model._df[self.model._df["PRZEKAZ"]==True].to_dict('records')
        if sel: self.request_transfer.emit(sel)
        else: QMessageBox.warning(self, "Info", "Brak zaznaczonych wierszy w kolumnie PRZEKAZ.")

class FilterWidget(QWidget):
    def __init__(self, parent=None, columns=[]):
        super().__init__(parent)
        l = QHBoxLayout(self); l.setContentsMargins(0,2,0,2)
        self.combo_col = QComboBox(); self.combo_col.addItems(columns); self.combo_col.setMinimumWidth(120)
        self.inp_min = QLineEdit(); self.inp_min.setPlaceholderText("Min"); self.inp_min.setFixedWidth(60)
        self.inp_max = QLineEdit(); self.inp_max.setPlaceholderText("Max"); self.inp_max.setFixedWidth(60)
        btn = QPushButton("X"); btn.setFixedWidth(25); btn.setStyleSheet("background:#802020; font-weight:bold;")
        btn.clicked.connect(self.deleteLater)
        l.addWidget(self.combo_col); l.addWidget(self.inp_min); l.addWidget(self.inp_max); l.addWidget(btn)


class Tab4_Fem(QSplitter):
    """Zakładka do konfiguracji i uruchamiania analiz MES - Wersja V7 Generator."""
    def __init__(self, router_instance):
        super().__init__(Qt.Orientation.Horizontal)
        self.router = router_instance
        self.candidates = []
        self.plotter = None
        self.surface_actors = {}
        self.init_ui()

    def init_ui(self):
        # --- LEWA KOLUMNA: KANDYDACI I USTAWIENIA ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_widget.setMinimumWidth(350)
        left_widget.setMaximumWidth(450)
        
        # 1. Kandydaci
        g_cand = QGroupBox("1. Kandydaci do analizy (z Tab 3)")
        l_cand = QVBoxLayout(g_cand)
        self.list_candidates = QListWidget()
        self.list_candidates.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_candidates.setStyleSheet("background-color: #1e1e1e;")
        l_cand.addWidget(self.list_candidates)
        left_layout.addWidget(g_cand)

        # 2. Ustawienia siatki
        g_mesh = QGroupBox("2. Parametry Siatki (GMSH)")
        f_mesh = QFormLayout(g_mesh)
        self.inp_mesh_factor = QDoubleSpinBox(); self.inp_mesh_factor.setRange(0.1, 10.0); self.inp_mesh_factor.setValue(1.0); self.inp_mesh_factor.setSingleStep(0.1)
        self.inp_mesh_factor.setToolTip("Mnożnik dla bazowej wielkości elementu (min. grubości ścianki)")
        
        self.inp_mesh_order = QComboBox(); self.inp_mesh_order.addItems(["1 (Liniowe)", "2 (Kwadratowe)"]); self.inp_mesh_order.setCurrentIndex(1)
        self.inp_mesh_cores = QSpinBox(); self.inp_mesh_cores.setRange(1, os.cpu_count() or 1); self.inp_mesh_cores.setValue(4)
        
        f_mesh.addRow("Wsp. rozmiaru el.:", self.inp_mesh_factor)
        f_mesh.addRow("Rząd elementów:", self.inp_mesh_order)
        f_mesh.addRow("Liczba rdzeni:", self.inp_mesh_cores)
        left_layout.addWidget(g_mesh)

        # 3. Ustawienia Solvera
        g_solver = QGroupBox("3. Parametry Analizy (CalculiX)")
        f_solver = QFormLayout(g_solver)
        self.inp_solver_cores = QSpinBox(); self.inp_solver_cores.setRange(1, os.cpu_count() or 1); self.inp_solver_cores.setValue(4)
        
        f_solver.addRow("Liczba rdzeni CCX:", self.inp_solver_cores)
        left_layout.addWidget(g_solver)

        left_layout.addStretch()
        self.addWidget(left_widget)

        # --- PRAWA STRONA: LOGI ---
        # (Wizualizację można dodać później, skupiamy się na generatorze)
        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)

        self.btn_run = QPushButton("🚀 URUCHOM GENERATOR I SOLVER")
        self.btn_run.setFixedHeight(50)
        self.btn_run.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; font-size: 16px;")
        self.btn_run.clicked.connect(self.run_batch)

        self.console = QTextBrowser()
        self.console.setStyleSheet("background:#1e1e1e; color:#ddd; font-family:Consolas; font-size:12px;")

        log_layout.addWidget(self.btn_run)
        log_layout.addWidget(QLabel("<b>Logi Procesu FEM:</b>"))
        log_layout.addWidget(self.console)

        self.addWidget(log_panel)
        self.setSizes([400, 800])

    def receive_data(self, candidates):
        self.candidates = candidates
        self.list_candidates.clear()
        if not candidates:
            self.list_candidates.addItem("Brak kandydatów.")
            self.btn_run.setEnabled(False)
            return
        self.btn_run.setEnabled(True)
        for cand in candidates:
            prof = cand.get('Nazwa_Profilu', '?')
            tp = cand.get('Input_Geo_tp', '?')
            self.list_candidates.addItem(f"{prof} + Płaskownik {tp}mm")

    def run_batch(self):
        if not self.candidates: return
        
        settings = {
            "mesh_size_factor": self.inp_mesh_factor.value(),
            "mesh_order": 2 if "2" in self.inp_mesh_order.currentText() else 1,
            "mesh_cores": self.inp_mesh_cores.value(),
            "solver_cores": self.inp_solver_cores.value()
        }

        self.worker = FemWorker(self.candidates, settings, self.router)
        self.worker.log_signal.connect(self.console.append)
        # self.worker.preview_signal.connect(...) # Opcjonalnie
        self.worker.finished_signal.connect(lambda s: self.btn_run.setEnabled(True))
        
        self.btn_run.setEnabled(False)
        self.console.clear()
        self.worker.start()

# ==============================================================================
# GŁÓWNE OKNO
# ==============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Optymalizacji Słupa v7.1 (Final)")
        self.resize(1280, 800) # Bezpieczny rozmiar
        
        self.router = router
        
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Inicjalizacja zakładek
        self.tab1 = Tab1_Dashboard()
        self.tab2 = Tab2_Knowledge()
        self.tab3 = Tab3_Selector()
        self.tab4 = Tab4_Fem(self.router)
        
        self.tabs.addTab(self.tab1, "1. Definicja i Analityka")
        self.tabs.addTab(self.tab2, "2. Baza Wiedzy")
        self.tabs.addTab(self.tab3, "3. Selekcja Wyników")
        self.tabs.addTab(self.tab4, "4. Symulacja MES")

        # Connections
        self.tab3.request_transfer.connect(self.tab4.receive_data)
        self.tab3.request_transfer.connect(lambda: self.tabs.setCurrentIndex(3))

    def closeEvent(self, event):
        """
        To jest kluczowa metoda, której brakowało w Twoim fragmencie.
        Zapobiega błędom 'wglMakeCurrent failed' i zawieszaniu wątków przy wyjściu.
        """
        # 1. Zatrzymanie wątku obliczeniowego (jeśli działa)
        for tab in [self.tab1, self.tab4]:
            if hasattr(tab, 'worker') and tab.worker.isRunning():
                if hasattr(tab.worker, 'stop'):
                    tab.worker.stop()
                else:
                    tab.worker.quit() # Ogólna metoda QThread
                tab.worker.wait(2000) # Czekaj max 2s na czyste zamknięcie

        event.accept()

# ==============================================================================
# ENTRY POINT
# ==============================================================================

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print("!!! GUI ERROR:", err_msg)
    QMessageBox.critical(None, "Krytyczny Błąd", err_msg)

sys.excepthook = handle_exception

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Ciemny motyw
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
    
    # --- FIX GMSH THREADING ---
    # Import tutaj, aby upewnić się, że jest dostępny w main scope
    import gmsh
    
    # Inicjalizujemy Gmsh w wątku głównym RAZ.
    # Zapobiega to błędowi "signal only works in main thread" w wątkach roboczych.
    try:
        if not gmsh.isInitialized():
            gmsh.initialize()
            gmsh.option.setNumber("General.Terminal", 1)
            # print("[MAIN] Gmsh initialized explicitly.")
    except Exception as e:
        print(f"[MAIN] Warning: Gmsh init failed: {e}")

    w = MainWindow()
    w.show()
    
    # Czyste zamknięcie aplikacji
    exit_code = app.exec()
    
    # Finalizacja Gmsh dopiero po zamknięciu okien Qt
    try:
        if gmsh.isInitialized(): 
            gmsh.finalize()
    except: pass
    
    sys.exit(exit_code)