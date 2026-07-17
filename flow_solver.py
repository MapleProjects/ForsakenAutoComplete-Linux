
"""
Flow Puzzle Solver - Solucionador Automático de Puzzles Numberlink para Forsaken
==================================================================================
Implementación siguiendo la guía técnica de automatización.
ADAPTADO PARA LINUX (MSS + evdev)

Arquitectura: Máquina de Estados (IDLE → SCAN → SOLVE → EXECUTE → VERIFY)
Solver: Backtracking con heurísticas (más robusto para puzzles parciales)
Input: evdev/uinput
Vision: MSS (ScreenShot)

Controles:
- Presiona 'J' para activar el solver cuando veas un puzzle
- Presiona 'Alt+J' para abrir el selector visual de grid
- Presiona 'F4' para parada de emergencia (Kill Switch)
- Ctrl+C en terminal para salir

Autor: Flow Solver Bot (Refactored by Antigravity)
"""

import sys
import os
import cv2
import numpy as np
import time
import threading
import tkinter as tk
from threading import Thread
from PIL import Image, ImageTk
from typing import List, Tuple, Dict, Optional
from enum import Enum
import platformdirs

# --- CORE IMPORTS ---
from core.factory import get_platform_adapters, get_hotkey_manager
from core.input_interface import InputInterface
from core.vision_interface import VisionInterface

# Keyboard input handled by evdev (platforms/linux/shortcuts.py)

# ============================================================
# INITIALIZATION OF ADAPTERS
# ============================================================
try:
    INPUT_ADAPTER, VISION_ADAPTER = get_platform_adapters()
    HOTKEY_MANAGER = get_hotkey_manager()
    print(f"✅ Input Adapter: {INPUT_ADAPTER.__class__.__name__}")
    print(f"✅ Vision Adapter: {VISION_ADAPTER.__class__.__name__}")
except Exception as e:
    print(f"❌ Error initializing adapters: {e}")
    sys.exit(1)


def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso, funciona para dev y para PyInstaller"""
    try:
        # PyInstaller crea una carpeta temporal en _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # En desarrollo, usar la ruta del script, no CWD
        base_path = os.path.dirname(os.path.abspath(__file__))

    full_path = os.path.join(base_path, relative_path)
    print(f"DEBUG Resource: {relative_path} -> {full_path}") # Debug log
    return full_path

# ============================================================
# CONFIGURACIÓN
# ============================================================
GRID_SIZE = 6  # Siempre 6x6
DEBUG_MODE = True # Temporal: ver detección de colores auto
AUTO_ADJUST_GRID_ON_SOLVE = True # Si True, intenta detectar y centrar el grid automáticamente al pulsar J

# CRONOMETRAJE (Segundos)
WOBBLE_DURATION_START = 0.09  # Tiempo del wobble inicial (agarre)
DELAY_BEFORE_MOUSEDOWN = 0.01 # Pausa tras llegar al punto antes de clickar (Evita clicks fantasma)
DELAY_BETWEEN_COLORS = 0.004    # Pausa tras soltar un color antes de ir al siguiente
END_NODE_HOLD_TIME_MS = 35       # (NUEVO) Milisegundos de espera antes de soltar el click al final del trazo
MOUSE_INTERPOLATION_STEPS = 13 # Pasos de interpolación entre puntos (Más alto = más suave, más lento)
WOBBLE_LOOP_SLEEP = 0.01       # Pausa dentro del bucle de wobble (Afecta velocidad de giro)

# GEOMETRÍA (Porcentajes del tamaño de celda)
WOBBLE_RATIO = 0.26       # Tamaño del rombo de agarre (0.30 = 30%)
START_PATH_BIAS = 0.11  # Retroceso inicial para alargar el trazo (0.13 = 13%)
END_PATH_BIAS = 0.12    # Adelantamiento final para alargar el trazo (0.12 = 12%)
MIN_COLORS_TO_SOLVE = 3 # Cantidad mínima de colores para intentar resolver

STEP_DELAY_MS = 1         # Delay por paso entre casillas (general)
FINAL_STEP_DELAY_MS = 1   # Delay por paso en la recta final

# Configuración Persistente usando platformdirs
CONFIG_DIR = platformdirs.user_config_dir("forsaken_ac", "RickStyles")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
CONFIG_FILE = os.path.join(CONFIG_DIR, "flow_solver_config.json")
print(f"📂 Archivo de configuración: {CONFIG_FILE}")

# ============================================================
# CALIBRACIÓN MANUAL DEL GRID
# ============================================================
MANUAL_GRID_ENABLED = False
MANUAL_GRID_X = 400
MANUAL_GRID_Y = 200
MANUAL_GRID_SIZE = 500
GRID_DETECTION_MODE = "auto"  # "auto" o "manual"

# Sistema de estabilidad del grid
STABLE_GRID_SIZE = None       # Tamaño estable del grid (None = no calibrado)
STABLE_CELL_SIZE = None       # Tamaño estable de celda (None = no calibrado)
STABLE_SUCCESS_COUNT = 0      # Contador de éxitos consecutivos con mismo tamaño
STABLE_THRESHOLD = 2          # Éxitos necesarios para marcar como estable
STABLE_SIZE_TOLERANCE = 10    # Tolerancia en px para considerar "mismo tamaño"
LAST_DETECTED_SIZE = None     # Último tamaño detectado (para comparar)

def load_config():
    """Carga la configuración guardada desde JSON"""
    global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, GRID_DETECTION_MODE
    global STABLE_GRID_SIZE, STABLE_CELL_SIZE, STABLE_SUCCESS_COUNT, MOUSE_INTERPOLATION_STEPS
    global END_NODE_HOLD_TIME_MS, STEP_DELAY_MS, FINAL_STEP_DELAY_MS
    import json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                MANUAL_GRID_ENABLED = config.get('enabled', False)
                MANUAL_GRID_X = config.get('x', 400)
                MANUAL_GRID_Y = config.get('y', 200)
                MANUAL_GRID_SIZE = config.get('size', 500)
                GRID_DETECTION_MODE = config.get('grid_detection_mode', 'auto')
                # Cargar config estable
                STABLE_GRID_SIZE = config.get('stable_grid_size', None)
                STABLE_CELL_SIZE = config.get('stable_cell_size', None)
                STABLE_SUCCESS_COUNT = config.get('stable_success_count', 0)
                MOUSE_INTERPOLATION_STEPS = config.get('mouse_speed', 6)
                END_NODE_HOLD_TIME_MS = config.get('end_node_hold_time', 25)
                STEP_DELAY_MS = float(config.get('step_delay', 0.3))
                FINAL_STEP_DELAY_MS = float(config.get('final_step_delay', 10.0))
                
                if STABLE_GRID_SIZE:
                    print(f"📂 Config estable: Grid {STABLE_GRID_SIZE}px, Celda {STABLE_CELL_SIZE}px ({STABLE_SUCCESS_COUNT} éxitos)")
                else:
                    print(f"📂 Configuración cargada: ({MANUAL_GRID_X}, {MANUAL_GRID_Y}) {MANUAL_GRID_SIZE}px [Modo: {GRID_DETECTION_MODE}] [Velocidad: {MOUSE_INTERPOLATION_STEPS}]")
        except Exception as e:
            print(f"⚠️ Error cargando configuración: {e}")

def save_manual_config():
    """Guarda la configuración MANUAL y ESTABLE a JSON"""
    global GRID_DETECTION_MODE, MOUSE_INTERPOLATION_STEPS, END_NODE_HOLD_TIME_MS, STEP_DELAY_MS, FINAL_STEP_DELAY_MS
    import json
    try:
        config = {
            'enabled': MANUAL_GRID_ENABLED,
            'x': MANUAL_GRID_X,
            'y': MANUAL_GRID_Y,
            'size': MANUAL_GRID_SIZE,
            'grid_detection_mode': GRID_DETECTION_MODE,
            # Config estable
            'stable_grid_size': STABLE_GRID_SIZE,
            'stable_cell_size': STABLE_CELL_SIZE,
            'stable_success_count': STABLE_SUCCESS_COUNT,
            'mouse_speed': MOUSE_INTERPOLATION_STEPS,
            'end_node_hold_time': END_NODE_HOLD_TIME_MS,
            'step_delay': STEP_DELAY_MS,
            'final_step_delay': FINAL_STEP_DELAY_MS
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"💾 Configuración guardada en {CONFIG_FILE}")
    except Exception as e:
        print(f"⚠️ Error guardando configuración: {e}")

load_config()

# ============================================================
# DETECCIÓN DE COLORES GENÉRICA (sin hardcodear rangos)
# ============================================================
# Solo se usa para detección del grid (áreas coloridas genéricas)
GENERIC_COLOR_MASK_LOW  = (0, 50, 50)    # Cualquier píxel con algo de saturación
GENERIC_COLOR_MASK_HIGH = (180, 255, 255)

def _hsv_distance(h1, s1, v1, h2, s2, v2):
    """Distancia perceptual entre dos colores HSV (OpenCV: H=0-180)."""
    dh = min(abs(int(h1) - int(h2)), 180 - abs(int(h1) - int(h2)))
    ds = abs(int(s1) - int(s2))
    dv = abs(int(v1) - int(v2))
    # H tiene más peso porque es el diferenciador principal de color
    return (dh * 2.0) ** 2 + ds ** 2 + (dv * 0.5) ** 2

# ============================================================
# ESTADOS DE LA MÁQUINA
# ============================================================
class SolverState(Enum):
    IDLE = "IDLE"
    SCAN = "SCAN"
    SOLVE = "SOLVE"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"

# ============================================================
# KILL SWITCH GLOBAL
# ============================================================
emergency_stop_flag = False

def emergency_stop():
    """Parada de emergencia - libera el mouse inmediatamente"""
    global emergency_stop_flag
    emergency_stop_flag = True
    try:
        INPUT_ADAPTER.mouse_up()
    except:
        pass
    print("\n🛑 ¡PARADA DE EMERGENCIA!")

# Setup Hotkey Manager (Platform Specific)
if HOTKEY_MANAGER:
    HOTKEY_MANAGER.register('F4', emergency_stop)
    HOTKEY_MANAGER.start()
    # Also register movement keys to stop if possible?
    # HOTKEY_MANAGER.register('w', emergency_stop) ...

# ============================================================
# SELECTOR VISUAL DE GRID (Alt+J)
# ============================================================
class GridSelector:
    """
    Herramienta visual para seleccionar el área del puzzle.
    """
    def __init__(self):

        self.root = None
        self.canvas = None
        self.screenshot = None
        self.tk_image = None
        self.rect_id = None
        self.start_x = 0
        self.start_y = 0
        self.current_rect = None
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        self.drag_offset = (0, 0)
        self.result = None
        self.dots_ids = [] # IDs de los puntos visuales
        
    def _calculate_auto_center(self, x, y, size):
        """
        Calcula posición Y TAMAÑO óptimos ("Smart Magnet").
        Retorna (x_sugerido, y_sugerido, size_sugerido)
        """
        try:
            # Límites de seguridad
            h, w = self.screenshot.size[1], self.screenshot.size[0]
            if x < 0 or y < 0 or x+size > w or y+size > h:
                return x, y, size
                
            # Extraer ROI de la imagen original (PIL) -> Convertir a CV2
            roi = self.screenshot.crop((x, y, x+size, y+size))
            roi_np = np.array(roi)
            # PIL es RGB, OpenCV usa BGR
            roi_cv = cv2.cvtColor(roi_np, cv2.COLOR_RGB2BGR)
            hsv = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2HSV)
            
            # Máscara rápida para detectar puntos brillantes/coloridos
            mask = cv2.inRange(hsv, (0, 80, 80), (180, 255, 255))
            kernel = np.ones((3,3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if len(contours) < 2:
                return x, y, size
                
            cell_size = size / GRID_SIZE
            valid_dots = [] # (cx, cy, col, row)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 20 < area < 5000:
                    M = cv2.moments(cnt)
                    if M["m00"] == 0: continue
                    
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    # Estimar columna/fila basado en la rejilla actual
                    col = int(cx / cell_size)
                    row = int(cy / cell_size)
                    
                    if col >= GRID_SIZE or row >= GRID_SIZE: continue
                    valid_dots.append((cx, cy, col, row))
            
            if len(valid_dots) >= 2:
                # 1. Refinar Posición (Centrado) basado en Puntos
                diff_x_sum = 0
                diff_y_sum = 0
                for cx, cy, col, row in valid_dots:
                    target_cx = col * cell_size + cell_size / 2
                    target_cy = row * cell_size + cell_size / 2
                    diff_x_sum += (cx - target_cx)
                    diff_y_sum += (cy - target_cy)
                
                avg_dx = diff_x_sum / len(valid_dots)
                avg_dy = diff_y_sum / len(valid_dots)
                suggested_x = x + avg_dx
                suggested_y = y + avg_dy
            else:
                suggested_x = x
                suggested_y = y
            
            # Inicializar size sugerido con el actual
            suggested_size = size
            
            # --- NUEVA LÓGICA: DETECCIÓN DE LÍNEAS DE GRID ---
            try:
                # ROI en escala de grises para bordes
                gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                # Mejora de contraste adaptativa
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                gray = clahe.apply(gray)
                
                # Detectar bordes
                edges = cv2.Canny(gray, 50, 150, apertureSize=3)
                
                # Detectar líneas (HoughLinesP)
                minLineLength = size // 6  
                maxLineGap = size // 20
                lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=minLineLength, maxLineGap=maxLineGap)
                
                grid_lines_x = []
                grid_lines_y = []
                
                if lines is not None:
                    for line in lines:
                        x1, y1, x2, y2 = line[0]
                        # Verticales (aprox)
                        if abs(x1 - x2) < 5 and abs(y1 - y2) > size/4:
                            grid_lines_x.append((x1 + x2) / 2)
                        # Horizontales (aprox)
                        elif abs(y1 - y2) < 5 and abs(x1 - x2) > size/4:
                            grid_lines_y.append((y1 + y2) / 2)
                
                # Calcular ajuste basado en líneas verticales
                if grid_lines_x:
                    shifts_x = []
                    current_cell_w = suggested_size / GRID_SIZE
                    for lx in grid_lines_x:
                        k = round((lx - suggested_x) / current_cell_w)
                        diff = lx - (suggested_x + k * current_cell_w)
                        shifts_x.append(diff)
                    
                    if shifts_x:
                         avg_shift_x = sum(shifts_x) / len(shifts_x)
                         suggested_x += avg_shift_x * 0.5

                # Calcular ajuste basado en líneas horizontales
                if grid_lines_y:
                    shifts_y = []
                    current_cell_h = suggested_size / GRID_SIZE
                    for ly in grid_lines_y:
                        k = round((ly - suggested_y) / current_cell_h)
                        diff = ly - (suggested_y + k * current_cell_h)
                        shifts_y.append(diff)
                    
                    if shifts_y:
                         avg_shift_y = sum(shifts_y) / len(shifts_y)
                         suggested_y += avg_shift_y * 0.5
    
            except Exception as e:
                print(f"⚠️ Error en detección de líneas: {e}")
    
            # 2. Refinar Tamaño (Escalado Robusto usando Mediana)
            steps_samples = []
            
            # Comparar pares de puntos para obtener muestras de 'cell_size'
            for i in range(len(valid_dots)):
                for j in range(i + 1, len(valid_dots)):
                    p1 = valid_dots[i]
                    p2 = valid_dots[j]
                    
                    d_col = abs(p1[2] - p2[2])
                    d_row = abs(p1[3] - p2[3])
                    
                    if d_col > 0:
                        steps_samples.append(abs(p1[0] - p2[0]) / d_col)
                    if d_row > 0:
                        steps_samples.append(abs(p1[1] - p2[1]) / d_row)
            
            suggested_size = size
            if steps_samples:
                # Filtrar outliers y tomar mediana
                median_step = np.median(steps_samples)
                current_step = size / GRID_SIZE
                if 0.5 * current_step < median_step < 1.5 * current_step:
                     suggested_size = median_step * GRID_SIZE
            
            # 3. Refinar Posición Final con el nuevo tamaño
            new_cell_size = suggested_size / GRID_SIZE
            
            ideal_origins_x = []
            ideal_origins_y = []
            
            for cx, cy, col, row in valid_dots:
                ox = cx - (col + 0.5) * new_cell_size
                oy = cy - (row + 0.5) * new_cell_size
                ideal_origins_x.append(ox)
                ideal_origins_y.append(oy)
                
            if ideal_origins_x:
                best_origin_x = x + np.median(ideal_origins_x)
                best_origin_y = y + np.median(ideal_origins_y)
                return int(best_origin_x), int(best_origin_y), int(suggested_size)
            else:
                 return int(suggested_x), int(suggested_y), int(suggested_size)
            
        except Exception as e:
            print(f"Error auto_center: {e}")
            return x, y, size
        self.dots_ids = [] # IDs de los puntos visuales
        self.resize_edge = None # 'N', 'S', 'E', 'W', 'NW', 'NE', 'SW', 'SE'
        
    def _calculate_auto_center(self, x, y, size):
        """
        Calcula posición Y TAMAÑO óptimos ("Smart Magnet").
        Retorna (x_sugerido, y_sugerido, size_sugerido)
        """
        try:
            # Límites de seguridad
            h, w = self.screenshot.size[1], self.screenshot.size[0]
            if x < 0 or y < 0 or x+size > w or y+size > h:
                return x, y, size
                
            # Extraer ROI de la imagen original (PIL) -> Convertir a CV2
            roi = self.screenshot.crop((x, y, x+size, y+size))
            roi_np = np.array(roi)
            # PIL es RGB, OpenCV usa BGR
            roi_cv = cv2.cvtColor(roi_np, cv2.COLOR_RGB2BGR)
            hsv = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2HSV)
            
            # Máscara rápida para detectar puntos brillantes/coloridos
            mask = cv2.inRange(hsv, (0, 80, 80), (180, 255, 255))
            kernel = np.ones((3,3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if len(contours) < 2:
                return x, y, size
                
            cell_size = size / GRID_SIZE
            valid_dots = [] # (cx, cy, col, row)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 20 < area < 5000:
                    M = cv2.moments(cnt)
                    if M["m00"] == 0: continue
                    
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    # Estimar columna/fila basado en la rejilla actual
                    col = int(cx / cell_size)
                    row = int(cy / cell_size)
                    
                    if col >= GRID_SIZE or row >= GRID_SIZE: continue
                    valid_dots.append((cx, cy, col, row))
            
            if len(valid_dots) >= 2:
                # 1. Refinar Posición (Centrado) basado en Puntos
                diff_x_sum = 0
                diff_y_sum = 0
                for cx, cy, col, row in valid_dots:
                    target_cx = col * cell_size + cell_size / 2
                    target_cy = row * cell_size + cell_size / 2
                    diff_x_sum += (cx - target_cx)
                    diff_y_sum += (cy - target_cy)
                
                avg_dx = diff_x_sum / len(valid_dots)
                avg_dy = diff_y_sum / len(valid_dots)
                suggested_x = x + avg_dx
                suggested_y = y + avg_dy
            else:
                suggested_x = x
                suggested_y = y
            
            # Inicializar size sugerido con el actual
            suggested_size = size
            
            # --- NUEVA LÓGICA: DETECCIÓN DE LÍNEAS DE GRID ---
            try:
                # ROI en escala de grises para bordes
                gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                # Mejora de contraste adaptativa
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                gray = clahe.apply(gray)
                
                # Detectar bordes
                edges = cv2.Canny(gray, 50, 150, apertureSize=3)
                
                # Detectar líneas (HoughLinesP)
                minLineLength = size // 6  
                maxLineGap = size // 20
                lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=minLineLength, maxLineGap=maxLineGap)
                
                grid_lines_x = []
                grid_lines_y = []
                
                if lines is not None:
                    for line in lines:
                        x1, y1, x2, y2 = line[0]
                        # Verticales (aprox)
                        if abs(x1 - x2) < 5 and abs(y1 - y2) > size/4:
                            grid_lines_x.append((x1 + x2) / 2)
                        # Horizontales (aprox)
                        elif abs(y1 - y2) < 5 and abs(x1 - x2) > size/4:
                            grid_lines_y.append((y1 + y2) / 2)
                
                # Calcular ajuste basado en líneas verticales
                if grid_lines_x:
                    shifts_x = []
                    current_cell_w = suggested_size / GRID_SIZE
                    for lx in grid_lines_x:
                        k = round((lx - suggested_x) / current_cell_w)
                        diff = lx - (suggested_x + k * current_cell_w)
                        shifts_x.append(diff)
                    
                    if shifts_x:
                         avg_shift_x = sum(shifts_x) / len(shifts_x)
                         suggested_x += avg_shift_x * 0.5

                # Calcular ajuste basado en líneas horizontales
                if grid_lines_y:
                    shifts_y = []
                    current_cell_h = suggested_size / GRID_SIZE
                    for ly in grid_lines_y:
                        k = round((ly - suggested_y) / current_cell_h)
                        diff = ly - (suggested_y + k * current_cell_h)
                        shifts_y.append(diff)
                    
                    if shifts_y:
                         avg_shift_y = sum(shifts_y) / len(shifts_y)
                         suggested_y += avg_shift_y * 0.5
    
            except Exception as e:
                print(f"⚠️ Error en detección de líneas: {e}")
    
            # 2. Refinar Tamaño (Escalado Robusto usando Mediana)
            steps_samples = []
            
            # Comparar pares de puntos para obtener muestras de 'cell_size'
            for i in range(len(valid_dots)):
                for j in range(i + 1, len(valid_dots)):
                    p1 = valid_dots[i]
                    p2 = valid_dots[j]
                    
                    d_col = abs(p1[2] - p2[2])
                    d_row = abs(p1[3] - p2[3])
                    
                    if d_col > 0:
                        steps_samples.append(abs(p1[0] - p2[0]) / d_col)
                    if d_row > 0:
                        steps_samples.append(abs(p1[1] - p2[1]) / d_row)
            
            suggested_size = size
            if steps_samples:
                # Filtrar outliers y tomar mediana
                median_step = np.median(steps_samples)
                current_step = size / GRID_SIZE
                if 0.5 * current_step < median_step < 1.5 * current_step:
                     suggested_size = median_step * GRID_SIZE
            
            # 3. Refinar Posición Final con el nuevo tamaño
            new_cell_size = suggested_size / GRID_SIZE
            
            ideal_origins_x = []
            ideal_origins_y = []
            
            for cx, cy, col, row in valid_dots:
                ox = cx - (col + 0.5) * new_cell_size
                oy = cy - (row + 0.5) * new_cell_size
                ideal_origins_x.append(ox)
                ideal_origins_y.append(oy)
                
            if ideal_origins_x:
                best_origin_x = x + np.median(ideal_origins_x)
                best_origin_y = y + np.median(ideal_origins_y)
                return int(best_origin_x), int(best_origin_y), int(suggested_size)
            else:
                 return int(suggested_x), int(suggested_y), int(suggested_size)
            
        except Exception as e:
            print(f"Error auto_center: {e}")
            return x, y, size
        
    def capture_screen(self):
        """Captura la pantalla para mostrar como fondo"""
        # Usamos el Vision Adapter
        try:
            img_bgr = VISION_ADAPTER.capture()
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(img_rgb)
            w, h = img.size
            return img, w, h
        except Exception as e:
            print(f"Error capturing screen: {e}")
            return Image.new('RGB', (1920, 1080)), 1920, 1080

    def show(self):
        """Muestra el selector visual"""
        global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE
        
        print("📐 [SELECTOR] Abriendo selector de grid...")
        
        self.screenshot, screen_w, screen_h = self.capture_screen()
        
        self.root = tk.Tk()
        self.root.title("Selector de Grid - Flow Solver")
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.configure(cursor="crosshair")
        
        self.tk_image = ImageTk.PhotoImage(self.screenshot, master=self.root)
        
        self.canvas = tk.Canvas(self.root, width=screen_w, height=screen_h, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        
        self.canvas.create_text(screen_w // 2, 30, 
                                 text="🎯 Dibuja un cuadrado | ENTER=Guardar | ESC=Cancelar",
                                 fill="yellow", font=("Arial", 16, "bold"))
        
        if MANUAL_GRID_ENABLED:
            self.current_rect = (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE)
            self.draw_rect()
        
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        
        # Eventos de teclado
        self.root.bind("<Return>", self.save_and_close)
        self.root.bind("<Escape>", self.cancel)
        self.root.bind("<Up>", lambda e: self.nudge_rect(0, -0.5))
        self.root.bind("<Down>", lambda e: self.nudge_rect(0, 0.5))
        self.root.bind("<Left>", lambda e: self.nudge_rect(-0.5, 0))
        self.root.bind("<Right>", lambda e: self.nudge_rect(0.5, 0))
        self.root.bind("<Shift-Up>", lambda e: self.nudge_rect(0, -0.1))
        self.root.bind("<Shift-Down>", lambda e: self.nudge_rect(0, 0.1))
        self.root.bind("<Shift-Left>", lambda e: self.nudge_rect(-0.1, 0))
        self.root.bind("<Shift-Right>", lambda e: self.nudge_rect(0.1, 0))
        
        # Resize with +/- keys
        self.root.bind("<plus>", lambda e: self.nudge_size(0.5))
        self.root.bind("<minus>", lambda e: self.nudge_size(-0.5))
        
        # Botones
        btn_frame = tk.Frame(self.root, bg='#333333')
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        save_btn = tk.Button(btn_frame, text="✅ Guardar (Enter)", 
                              command=self.save_and_close, 
                              bg='#4CAF50', fg='white', font=("Arial", 12, "bold"),
                              padx=20, pady=10)
        save_btn.pack(side=tk.LEFT, padx=10)
        
        cancel_btn = tk.Button(btn_frame, text="❌ Cancelar (Esc)", 
                                command=self.cancel,
                                bg='#f44336', fg='white', font=("Arial", 12, "bold"),
                                padx=20, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)
        
        self.root.mainloop()
        return self.result
    
    def draw_rect(self):
        # 1. Limpiar TODO el dibujo anterior usando TAGS (Más robusto que IDs individuales)
        self.canvas.delete("overlay")
            
        if self.current_rect:
            x, y, size = self.current_rect
            # Usar tag 'overlay' para todo lo que dibujamos
            self.canvas.create_rectangle(x, y, x + size, y + size, outline='#00FF00', width=3, dash=(5, 5), tags="overlay")
            
        if self.current_rect:
            x, y, size = self.current_rect
            self.rect_id = self.canvas.create_rectangle(x, y, x + size, y + size, outline='#00FF00', width=3, dash=(5, 5), tags="overlay")
            
            # Mostrar tamaño
            self.canvas.create_text(
                x + size // 2, y - 15,
                text=f"📏 {size:.2f}x{size:.2f} px  |  Pos: ({x:.2f}, {y:.2f})",
                fill='#00FF00', font=("Arial", 12, "bold"),
                tags="overlay" # TAG UNIFICADO
            )
            
            # DIBUJAR PUNTOS DE PREVISUALIZACIÓN (6x6)
            cell_size = size / GRID_SIZE
            half_cell = cell_size / 2
            
            for r in range(GRID_SIZE):
                for c in range(GRID_SIZE):
                    cx = x + int(c * cell_size + half_cell)
                    cy = y + int(r * cell_size + half_cell)
                    
                    self.canvas.create_oval(
                        cx - 2, cy - 2, cx + 2, cy + 2,
                        fill='black', outline='#00FF00', width=1,
                        tags="overlay"
                    )
            
            # --- VISUALIZACIÓN 'PLUS' 2x2 ---
            center_x = x + size / 2.0
            center_y = y + size / 2.0
            
            bound_2_x = x + cell_size * 2
            bound_4_x = x + cell_size * 4
            bound_2_y = y + cell_size * 2
            bound_4_y = y + cell_size * 4
            
            # 1. Cruz central fuerte (El "+" de 2x2)
            # 1. Cruz central fuerte (El "+" de 2x2)
            self.canvas.create_line(center_x, bound_2_y, center_x, bound_4_y, fill='cyan', width=2, tags="overlay")
            self.canvas.create_line(bound_2_x, center_y, bound_4_x, center_y, fill='cyan', width=2, tags="overlay")
            
            # 2. "Rayas largas en las puntas"
            # 2. "Rayas largas en las puntas"
            self.canvas.create_line(center_x, y, center_x, bound_2_y, fill='cyan', width=1, dash=(4,4), tags="overlay")
            self.canvas.create_line(center_x, bound_4_y, center_x, y + size, fill='cyan', width=1, dash=(4,4), tags="overlay")
            self.canvas.create_line(x, center_y, bound_2_x, center_y, fill='cyan', width=1, dash=(4,4), tags="overlay")
            self.canvas.create_line(bound_4_x, center_y, x + size, center_y, fill='cyan', width=1, dash=(4,4), tags="overlay")

            # 3. Caja del 2x2 (Centro)
            # 3. Caja del 2x2 (Centro)
            self.canvas.create_rectangle(bound_2_x, bound_2_y, bound_4_x, bound_4_y, outline='yellow', width=1, dash=(2,2), tags="overlay")
            
            # 4. Cajas 1x1 en las esquinas
            # 4. Cajas 1x1 en las esquinas
            self.canvas.create_rectangle(x, y, x + cell_size, y + cell_size, outline='yellow', width=1, dash=(2,2), tags="overlay")
            self.canvas.create_rectangle(x + cell_size*5, y, x + size, y + cell_size, outline='yellow', width=1, dash=(2,2), tags="overlay")
            self.canvas.create_rectangle(x, y + cell_size*5, x + size, y + size, outline='yellow', width=1, dash=(2,2), tags="overlay")
            self.canvas.create_rectangle(x + cell_size*5, y + cell_size*5, x + size, y + size, outline='yellow', width=1, dash=(2,2), tags="overlay")
            
            # Dibujar handles (agarraderas)
            handle_size = 8
            corners = [(x, y), (x+size, y), (x, y+size), (x+size, y+size)]
            for hx, hy in corners:
                self.canvas.create_rectangle(hx-handle_size, hy-handle_size, hx+handle_size, hy+handle_size, fill='white', outline='black', tags="overlay")

    def on_mouse_down(self, event):
        if self.current_rect:
            x, y, size = self.current_rect
            # 1. Verificar si está en un borde/esquina para redimensionar (simplificado)
            margin = 15
            on_left = abs(event.x - x) < margin
            on_right = abs(event.x - (x + size)) < margin
            on_top = abs(event.y - y) < margin
            on_bottom = abs(event.y - (y + size)) < margin
            
            self.resize_edge = ''
            if on_top: self.resize_edge += 'N'
            if on_bottom: self.resize_edge += 'S'
            if on_left: self.resize_edge += 'W'
            if on_right: self.resize_edge += 'E'
            
            if self.resize_edge:
                self.resizing = True
                self.canvas.configure(cursor="sizing")
                return



            if x < event.x < x+size and y < event.y < y+size:
                self.dragging = True
                self.drag_offset = (event.x - x, event.y - y)
                self.canvas.configure(cursor="fleur")
                return
        
        self.start_x = event.x
        self.start_y = event.y
        self.dragging = False

    def on_mouse_drag(self, event):
        if self.resizing and self.current_rect:
            x, y, size = self.current_rect
            new_x, new_y = x, y
            new_size = size
            
            if 'E' in self.resize_edge: new_size = event.x - x
            elif 'W' in self.resize_edge:
                dx = x - event.x
                new_size = size + dx
                new_x = event.x
            
            if 'S' in self.resize_edge:
                h_size = event.y - y
                new_size = max(new_size, h_size) if 'E' not in self.resize_edge else new_size
            elif 'N' in self.resize_edge:
                dy = y - event.y
                new_size = max(new_size, size + dy) if 'E' not in self.resize_edge else new_size
                new_y = event.y
            
            if new_size < 20: return
            self.current_rect = (new_x, new_y, new_size)
            self.draw_rect()
            
        elif self.dragging and self.current_rect:
            size = self.current_rect[2]
            
            raw_x = event.x - self.drag_offset[0]
            raw_y = event.y - self.drag_offset[1]
            
            # APLICAR AUTO-CENTER "Smart Magnet"
            magnet_x, magnet_y, magnet_size = self._calculate_auto_center(raw_x, raw_y, size)
            
            dist = ((raw_x - magnet_x)**2 + (raw_y - magnet_y)**2)**0.5
            
            if dist < 60:
                self.current_rect = (magnet_x, magnet_y, magnet_size)
            else:
                self.current_rect = (raw_x, raw_y, size)
            
            self.draw_rect()
        else:
            dx = event.x - self.start_x
            dy = event.y - self.start_y
            size = max(abs(dx), abs(dy))
            x = self.start_x if dx >= 0 else self.start_x - size
            y = self.start_y if dy >= 0 else self.start_y - size
            self.current_rect = (x, y, size)
            self.draw_rect()
    
    def on_mouse_up(self, event):
        self.dragging = False
        self.resizing = False
        self.canvas.configure(cursor="crosshair")

    def nudge_rect(self, dx, dy):
        if self.current_rect:
            x, y, size = self.current_rect
            self.current_rect = (x + dx, y + dy, size)
            self.draw_rect()

    def nudge_size(self, d_size):
        if self.current_rect:
            x, y, size = self.current_rect
            new_size = max(20, size + d_size)
            self.current_rect = (x, y, new_size)
            self.draw_rect()
    
    def save_and_close(self, event=None):
        global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE
        if self.current_rect:
            x, y, size = self.current_rect
            MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE = x, y, size
            MANUAL_GRID_ENABLED = True
            save_manual_config()
        self.root.destroy()
        
    def cancel(self, event=None):
        self.root.destroy()

def open_grid_selector():
    selector = GridSelector()
    thread = threading.Thread(target=selector.show)
    thread.start()

# ============================================================
# CLASE PRINCIPAL: FLOW PUZZLE SOLVER
# ============================================================
class FlowPuzzleSolver:
    
    def __init__(self, input_adapter: InputInterface, vision_adapter: VisionInterface):
        self.input = input_adapter
        self.vision = vision_adapter
        self.state = SolverState.IDLE
        self.is_solving = False
        self.grid_origin = None
        self.cell_size = None
        self.debug_counter = 0
        self.final_paths = {}
        
        # Configure vision resolution in input logic if needed
        w, h = self.vision.get_resolution()
        if hasattr(self.input, 'set_screen_resolution'):
            self.input.set_screen_resolution(w, h)
        
    def capture_screen(self) -> np.ndarray:
        return self.vision.capture()
    
    def find_puzzle_grid(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        return None

    def _find_grid_by_white_border(self, screen: np.ndarray, hint_center: Tuple[int, int] = None, min_contain_rect: Tuple[int, int, int, int] = None) -> Optional[Tuple[int, int, int, int]]:
        """
        Detecta el grid combinando FONDO OSCURO + COLORES.
        LÓGICA:
        1. Detecta el fondo oscuro del puzzle (área negra)
        2. Detecta los colores dentro del área oscura
        3. Calcula el grid como un cuadrado centrado en los colores
        4. Ajusta el tamaño basado en el espaciado entre colores
        """
        try:
            screen_h, screen_w = screen.shape[:2]
            
            # ====== PASO 1: DETECTAR FONDO OSCURO ======
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            
            # Rango para NEGRO del puzzle
            dark_lower = np.array([0, 0, 0])
            dark_upper = np.array([180, 50, 30])
            dark_mask = cv2.inRange(hsv, dark_lower, dark_upper)
            
            # Morfología para unir el área oscura
            kernel_large = np.ones((15, 15), np.uint8)
            dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel_large)
            dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            
            # Encontrar el área oscura más grande
            dark_contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            dark_rect = None
            max_dark_area = 0
            for cnt in dark_contours:
                area = cv2.contourArea(cnt)
                x, y, w, h = cv2.boundingRect(cnt)
                aspect = float(w) / h if h > 0 else 0
                # El fondo debe ser grande y cuadrado-ish
                if area > max_dark_area and 0.7 < aspect < 1.4 and w > 200 and h > 200:
                    max_dark_area = area
                    dark_rect = (x, y, w, h)
            
            if DEBUG_MODE:
                if dark_rect:
                    print(f"   [GridDetect] Fondo oscuro: ({dark_rect[0]},{dark_rect[1]}) {dark_rect[2]}x{dark_rect[3]}")
                else:
                    print("   [GridDetect] ⚠️ No se detectó fondo oscuro")
            
            # ====== PASO 2: DETECTAR COLORES ======
            combined_color_mask = cv2.inRange(hsv, np.array(GENERIC_COLOR_MASK_LOW), np.array(GENERIC_COLOR_MASK_HIGH))
            
            kernel = np.ones((3,3), np.uint8)
            combined_color_mask = cv2.morphologyEx(combined_color_mask, cv2.MORPH_OPEN, kernel)
            
            color_contours, _ = cv2.findContours(combined_color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Recopilar candidatos de color
            color_candidates = []
            for cnt in color_contours:
                area = cv2.contourArea(cnt)
                if 50 < area < 2500:
                    x, y, w, h = cv2.boundingRect(cnt)
                    aspect_ratio = float(w) / h
                    if 0.6 < aspect_ratio < 1.6:
                        cx, cy = x + w//2, y + h//2
                        size = (w + h) / 2
                        color_candidates.append({
                            'center': (cx, cy),
                            'size': size
                        })
            
            # Filtrar por tamaño consistente (±5%)
            if len(color_candidates) >= 3:
                sizes = [c['size'] for c in color_candidates]
                sizes_sorted = sorted(sizes)
                median_size = sizes_sorted[len(sizes_sorted) // 2]
                tolerance = 0.05
                min_size = median_size * (1 - tolerance)
                max_size = median_size * (1 + tolerance)
                color_candidates = [c for c in color_candidates if min_size <= c['size'] <= max_size]
            
            if DEBUG_MODE:
                print(f"   [GridDetect] Puntos de color válidos: {len(color_candidates)}")
            
            if len(color_candidates) < 2:
                if DEBUG_MODE:
                    print("   ⚠️ [GridDetect] Muy pocos puntos de color")
                return None
            
            # Calcular bounding box de colores
            all_cx = [c['center'][0] for c in color_candidates]
            all_cy = [c['center'][1] for c in color_candidates]
            color_min_x, color_max_x = min(all_cx), max(all_cx)
            color_min_y, color_max_y = min(all_cy), max(all_cy)
            color_center_x = (color_min_x + color_max_x) // 2
            color_center_y = (color_min_y + color_max_y) // 2
            color_span_x = color_max_x - color_min_x
            color_span_y = color_max_y - color_min_y
            
            if DEBUG_MODE:
                print(f"   [GridDetect] Centro colores: ({color_center_x}, {color_center_y}), span: {color_span_x}x{color_span_y}")
            
            # ====== PASO 3: CALCULAR TAMAÑO DEL GRID ======
            # El span de colores representa (GRID_SIZE - 1) celdas
            # porque los puntos están en los centros de las celdas extremas
            cell_size_estimate = max(color_span_x, color_span_y) / (GRID_SIZE - 1)
            grid_size = int(cell_size_estimate * GRID_SIZE)
            
            # Limitar tamaño razonable
            grid_size = max(250, min(grid_size, 650))
            
            # Si tenemos fondo oscuro, usarlo para validar/ajustar el tamaño
            if dark_rect:
                dx, dy, dw, dh = dark_rect
                dark_size = min(dw, dh)
                
                # El grid no puede ser más grande que el fondo oscuro
                if grid_size > dark_size:
                    grid_size = dark_size
                    if DEBUG_MODE:
                        print(f"   [GridDetect] Grid ajustado a fondo oscuro: {grid_size}px")
            
            # ====== PASO 4: CENTRAR EL GRID EN LOS COLORES ======
            # El grid debe estar centrado de forma que los colores queden en los centros de las celdas
            final_cell_size = grid_size / GRID_SIZE
            
            # El punto mínimo de color debería estar en el centro de la celda (0,0)
            # Por lo tanto: grid_x + 0.5*cell_size = color_min_x - offset
            # Usamos el centro de colores para centrar
            grid_x = int(color_center_x - grid_size / 2)
            grid_y = int(color_center_y - grid_size / 2)
            
            # Ajustar para que los puntos extremos estén en celdas válidas
            # La celda del punto mínimo: grid_x + cell_size/2 debe ser <= color_min_x
            min_cell_center_x = color_min_x - final_cell_size / 2
            min_cell_center_y = color_min_y - final_cell_size / 2
            
            # Recalcular grid_x basado en el punto mínimo
            grid_x = int(min_cell_center_x)
            grid_y = int(min_cell_center_y)
            
            # Asegurar que el grid no se salga de la pantalla
            grid_x = max(0, min(grid_x, screen_w - grid_size))
            grid_y = max(0, min(grid_y, screen_h - grid_size))
            
            if DEBUG_MODE:
                debug_img = screen.copy()
                
                # Dibujar fondo oscuro en rojo
                if dark_rect:
                    dx, dy, dw, dh = dark_rect
                    cv2.rectangle(debug_img, (dx, dy), (dx+dw, dy+dh), (0, 0, 255), 2)
                    cv2.putText(debug_img, "Dark BG", (dx, dy-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                
                # Dibujar bounding box de colores en magenta
                cv2.rectangle(debug_img, (color_min_x, color_min_y), (color_max_x, color_max_y), (255, 0, 255), 2)
                
                # Dibujar puntos de color
                for c in color_candidates:
                    cx, cy = c['center']
                    cv2.circle(debug_img, (int(cx), int(cy)), 5, (0, 255, 0), -1)
                
                # Dibujar grid final en verde
                cv2.rectangle(debug_img, (grid_x, grid_y), (grid_x+grid_size, grid_y+grid_size), (0, 255, 0), 3)
                
                # Dibujar líneas del grid
                for i in range(GRID_SIZE + 1):
                    line_pos = int(i * final_cell_size)
                    cv2.line(debug_img, (grid_x + line_pos, grid_y), (grid_x + line_pos, grid_y + grid_size), (100, 255, 100), 1)
                    cv2.line(debug_img, (grid_x, grid_y + line_pos), (grid_x + grid_size, grid_y + line_pos), (100, 255, 100), 1)
                
                cv2.putText(debug_img, f"GRID: {grid_size}x{grid_size}", (grid_x, grid_y-10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                cv2.imwrite("debug_grid_white_border_best.png", debug_img)
                print(f"   ✅ [GridDetect] Grid final: ({grid_x}, {grid_y}) {grid_size}x{grid_size}")
            
            return (grid_x, grid_y, grid_size, grid_size)

        except Exception as e:
            print(f"⚠️ Error grid detection: {e}")
            import traceback
            traceback.print_exc()
            return None



    def _find_grid_by_border_color(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detecta el grid buscando el COLOR ESPECÍFICO del borde en HSV.
        Similar a _find_grid_by_colors pero para el borde blanco/gris brillante.
        """
        try:
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            
            # Rango para BLANCO BRILLANTE / GRIS CLARO (el borde del puzzle)
            # H: 0-180 (cualquier tono), S: 0-50 (baja saturación = gris/blanco), V: 180-255 (muy brillante)
            border_lower = np.array([0, 0, 180])
            border_upper = np.array([180, 50, 255])
            
            mask = cv2.inRange(hsv, border_lower, border_upper)
            
            # Morfología para conectar líneas del borde
            kernel = np.ones((7, 7), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            
            if DEBUG_MODE:
                cv2.imwrite("debug_grid_border_color_mask.png", mask)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            candidates = []
            screen_h, screen_w = screen.shape[:2]
            margin = 10
            
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = float(w) / h if h > 0 else 0
                area = cv2.contourArea(cnt)
                
                # Filtros: tamaño razonable, cuadrado, no toca bordes
                if x < margin or y < margin or (x+w) > (screen_w-margin) or (y+h) > (screen_h-margin):
                    continue
                if not (100 < w < 900 and 100 < h < 900):
                    continue
                if not (0.7 < aspect_ratio < 1.3):
                    continue
                if area < 5000:  # Mínimo área para ser un grid válido
                    continue
                
                # Score: cuadratura + tamaño + centralidad
                score = 0
                score += (1.0 - abs(1.0 - aspect_ratio)) * 100  # Squareness
                score += (w + h) * 0.1  # Size bonus
                cx, cy = x + w // 2, y + h // 2
                score -= abs(cx - screen_w // 2) * 0.3  # Centrality penalty
                score -= abs(cy - screen_h // 2) * 0.3
                
                candidates.append({'rect': (x, y, w, h), 'score': score})
            
            if not candidates:
                return None
            
            candidates.sort(key=lambda c: c['score'], reverse=True)
            best = candidates[0]['rect']
            
            if DEBUG_MODE:
                debug_img = screen.copy()
                for c in candidates[:5]:  # Top 5 candidates
                    rx, ry, rw, rh = c['rect']
                    color = (0, 255, 0) if c == candidates[0] else (0, 255, 255)
                    cv2.rectangle(debug_img, (rx, ry), (rx+rw, ry+rh), color, 2)
                    cv2.putText(debug_img, f"{int(c['score'])}", (rx, ry-5), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
                cv2.imwrite("debug_grid_border_color_result.png", debug_img)
            
            return best
            
        except Exception as e:
            print(f"⚠️ Error border color detection: {e}")
            return None

    def _find_dark_background(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detecta el área de FONDO OSCURO del puzzle.
        El fondo oscuro es una constante que define los límites exactos del grid.
        Retorna (x, y, w, h) del área oscura o None si no se encuentra.
        """
        try:
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            
            # Rango para NEGRO del puzzle: RGB(10,10,10) = HSV(0, 0, ~10)
            # H: 0-180 (cualquier tono - negro no tiene tono)
            # S: 0-50 (muy baja saturación - gris/negro puro)
            # V: 0-30 (muy oscuro, el fondo es V≈10)
            dark_lower = np.array([0, 0, 0])
            dark_upper = np.array([180, 50, 30])
            
            mask = cv2.inRange(hsv, dark_lower, dark_upper)
            
            # Morfología para limpiar y unir la región oscura
            kernel = np.ones((15, 15), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return None
            
            # Encontrar el contorno más grande (debería ser el fondo del puzzle)
            screen_h, screen_w = screen.shape[:2]
            min_area = (screen_w * 0.15) * (screen_h * 0.15)  # Mínimo 15% del área
            
            valid_dark_regions = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = float(w) / h if h > 0 else 0
                
                # El fondo del puzzle debe ser cuadrado-ish y grande
                if area > min_area and 0.7 < aspect_ratio < 1.4:
                    # Priorizar regiones centradas
                    cx, cy = x + w//2, y + h//2
                    dist_to_center = abs(cx - screen_w//2) + abs(cy - screen_h//2)
                    valid_dark_regions.append((x, y, w, h, area, dist_to_center))
            
            if not valid_dark_regions:
                return None
            
            # Ordenar por área (mayor primero), luego por cercanía al centro
            valid_dark_regions.sort(key=lambda r: (-r[4], r[5]))
            best = valid_dark_regions[0][:4]
            
            if DEBUG_MODE:
                debug_img = screen.copy()
                x, y, w, h = best
                
                # Dibujar patrón de rayas diagonales en el área oscura detectada
                overlay = debug_img.copy()
                stripe_color = (50, 50, 150)  # Rojo oscuro para las rayas
                stripe_spacing = 15
                
                # Dibujar rayas diagonales
                for i in range(-h, w + h, stripe_spacing):
                    pt1 = (x + i, y)
                    pt2 = (x + i + h, y + h)
                    cv2.line(overlay, pt1, pt2, stripe_color, 2)
                
                # Blend con alpha
                cv2.addWeighted(overlay, 0.3, debug_img, 0.7, 0, debug_img)
                
                # Borde del área oscura
                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 3)
                cv2.putText(debug_img, f"Dark BG: {w}x{h}", (x, y-10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                
                cv2.imwrite("debug_dark_background.png", debug_img)
                cv2.imwrite("debug_dark_mask.png", mask)
                print(f"   [DarkBG] Detectado: ({x}, {y}) {w}x{h}")
            
            return best
            
        except Exception as e:
            print(f"⚠️ Error dark background detection: {e}")
            return None

    def _find_grid_by_colors(self, screen: np.ndarray, is_tight_crop: bool = False, debug_suffix: str = "") -> Optional[Tuple[int, int, int, int]]:
        """
        Detecta el grid buscando agrupaciones de puntos de colores del juego.
        Reconstruye el grid basándose en la dispersión de los puntos (factor 1.2x).
        """
        try:
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            combined_mask = cv2.inRange(hsv, np.array(GENERIC_COLOR_MASK_LOW), np.array(GENERIC_COLOR_MASK_HIGH))
            
            kernel = np.ones((3,3), np.uint8)
            combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
            
            if DEBUG_MODE:
                cv2.imwrite("debug_grid_colors_mask.png", combined_mask)
                
                # DIAGNÓSTICO HSV: Buscar CUALQUIER área saturada y mostrar sus valores
                # Esto ayuda a calibrar los rangos de color
                sat_channel = hsv[:,:,1]
                val_channel = hsv[:,:,2]
                
                # Máscara de áreas "coloridas" (alta saturación Y alto valor)
                colorful_mask = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([180, 255, 255]))
                
                debug_hsv = screen.copy()
                hsv_contours, _ = cv2.findContours(colorful_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                print(f"   [HSV DEBUG] Encontradas {len(hsv_contours)} áreas coloridas")
                
                for cnt in hsv_contours[:20]:  # Máximo 20 para no saturar
                    area = cv2.contourArea(cnt)
                    if area > 50:
                        x, y, w, h = cv2.boundingRect(cnt)
                        # Obtener HSV promedio del área
                        roi = hsv[y:y+h, x:x+w]
                        avg_h = int(np.mean(roi[:,:,0]))
                        avg_s = int(np.mean(roi[:,:,1]))
                        avg_v = int(np.mean(roi[:,:,2]))
                        
                        cv2.rectangle(debug_hsv, (x, y), (x+w, y+h), (0, 255, 0), 1)
                        cv2.putText(debug_hsv, f"H{avg_h} S{avg_s} V{avg_v}", (x, y-3), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1)
                        print(f"   HSV: H={avg_h}, S={avg_s}, V={avg_v}")
                
                cv2.imwrite("debug_hsv_samples.png", debug_hsv)
            
            contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            valid_dots = []
            screen_h, screen_w = screen.shape[:2]
            
            # Margen para filtrar puntos (relajado si es crop ajustado)
            margin_ratio = 0.01 if is_tight_crop else 0.1
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                # Área más estricta para puntos de puzzle (típicamente 100-2000px)
                if 50 < area < 2500:
                    x, y, w, h = cv2.boundingRect(cnt)
                    if 0.6 < float(w)/h < 1.6:  # Más circular
                        # Filtrar: solo considerar puntos dentro del margen seguro
                        cx, cy = x + w//2, y + h//2
                        if screen_w * margin_ratio < cx < screen_w * (1 - margin_ratio) and \
                           screen_h * margin_ratio < cy < screen_h * (1 - margin_ratio):
                            valid_dots.append((x, y, w, h))
            
            if len(valid_dots) < 2:
                if DEBUG_MODE: print("⚠️ [ColorDetect] Muy pocos puntos encontrados.")
                return None
            
            # CLUSTERING SIMPLE: Encontrar el grupo más denso de puntos
            # Calcular centros
            centers = [(d[0] + d[2]/2, d[1] + d[3]/2) for d in valid_dots]
            
            # Buscar el "centro de masa" de todos los puntos
            avg_x = sum(c[0] for c in centers) / len(centers)
            avg_y = sum(c[1] for c in centers) / len(centers)
            
            # Filtrar: solo mantener puntos a menos de 400px del centro de masa
            MAX_DIST = 400
            clustered_dots = []
            for i, c in enumerate(centers):
                dist = ((c[0] - avg_x)**2 + (c[1] - avg_y)**2)**0.5
                if dist < MAX_DIST:
                    clustered_dots.append(valid_dots[i])
            
            if len(clustered_dots) < 2:
                if DEBUG_MODE: print("⚠️ [ColorDetect] Cluster muy pequeño.")
                clustered_dots = valid_dots  # Fallback a todos
            
            # ====== FILTRADO POR TAMAÑO CONSISTENTE ======
            # Los dots de puzzle REALES tienen todos el mismo tamaño
            # Encontrar el tamaño más común y filtrar outliers
            
            dot_sizes = [(d[2] + d[3]) / 2 for d in clustered_dots]  # Promedio w,h
            
            if len(dot_sizes) >= 3:
                # Encontrar el tamaño más frecuente (moda aproximada)
                dot_sizes_sorted = sorted(dot_sizes)
                median_size = dot_sizes_sorted[len(dot_sizes_sorted) // 2]
                
                # Tolerancia: ±30% del tamaño mediano
                tolerance = 0.30
                size_filtered_dots = []
                for i, d in enumerate(clustered_dots):
                    dot_size = (d[2] + d[3]) / 2
                    if median_size * (1 - tolerance) <= dot_size <= median_size * (1 + tolerance):
                        size_filtered_dots.append(d)
                
                if len(size_filtered_dots) >= 2:
                    if DEBUG_MODE and len(size_filtered_dots) < len(clustered_dots):
                        print(f"   [SizeFilter] {len(clustered_dots)} → {len(size_filtered_dots)} (mediana: {median_size:.0f}px)")
                    clustered_dots = size_filtered_dots
            
            # Calcular centros del cluster
            centers_x = [d[0] + d[2]/2 for d in clustered_dots]
            centers_y = [d[1] + d[3]/2 for d in clustered_dots]
            
            min_cx, max_cx = min(centers_x), max(centers_x)
            min_cy, max_cy = min(centers_y), max(centers_y)
            
            span_w = max_cx - min_cx
            span_h = max_cy - min_cy
            
            if span_w < 50 or span_h < 50:
                return None
            
            # ====== NUEVO: CALCULAR TAMAÑO DE CELDA DESDE ESPACIADO ======
            # Ordenar centros y calcular distancias entre vecinos
            sorted_x = sorted(set(centers_x))
            sorted_y = sorted(set(centers_y))
            
            # Calcular distancias entre centros adyacentes
            x_dists = [sorted_x[i+1] - sorted_x[i] for i in range(len(sorted_x)-1) if sorted_x[i+1] - sorted_x[i] > 20]
            y_dists = [sorted_y[i+1] - sorted_y[i] for i in range(len(sorted_y)-1) if sorted_y[i+1] - sorted_y[i] > 20]
            
            # Usar mediana o mínimo como tamaño de celda (espaciado entre celdas)
            if x_dists and y_dists:
                # Tomar la mediana de las distancias como tamaño de celda
                all_dists = x_dists + y_dists
                all_dists.sort()
                cell_size = int(all_dists[len(all_dists)//2])  # Mediana
            else:
                # Fallback: usar span / (GRID_SIZE-1) asumiendo 6x6
                cell_size = int(max(span_w, span_h) / 5)
            
            # El tamaño del grid completo es GRID_SIZE celdas
            grid_size = cell_size * GRID_SIZE
            
            # LIMITAR TAMAÑO (mín 250, máx 650)
            grid_size = max(250, min(grid_size, 650))
            cell_size = grid_size / GRID_SIZE
            
            # ====== ALINEACIÓN DIRECTA: POSICIONAR GRID BASADO EN DOTS EXTREMOS ======
            # El dot más a la izquierda/arriba debería estar centrado en la celda (0,0)
            # Entonces: grid_x = min_cx - cell_size/2
            # Pero necesitamos considerar que puede haber dots en otras posiciones
            
            # El dot mínimo está en la celda (0,0), centrado
            # El dot máximo está en la celda (N-1, N-1), centrado
            # Por lo tanto, el span debería ser exactamente (N-1) * cell_size
            # donde N es el número de filas/columnas con dots
            
            # Calculamos grid_x tal que min_cx esté centrado en SU celda
            # La celda del dot mínimo tiene su centro en: grid_x + (col + 0.5) * cell_size
            # Queremos que min_cx == grid_x + (col_min + 0.5) * cell_size
            # Si asumimos col_min = 0: grid_x = min_cx - 0.5 * cell_size
            
            grid_x = int(min_cx - cell_size / 2)
            grid_y = int(min_cy - cell_size / 2)
            
            # Verificar que el grid cubra todos los dots
            # Ajustar grid_size si es necesario para que max_cx también quede dentro
            needed_width = max_cx - min_cx + cell_size
            needed_height = max_cy - min_cy + cell_size
            grid_size = int(max(needed_width, needed_height, grid_size))
            
            # Recalcular cell_size con el grid_size ajustado
            cell_size = grid_size / GRID_SIZE
            
            # LIMITAR TAMAÑO (mín 250, máx 650)
            if grid_size > 650:
                grid_size = 650
                cell_size = grid_size / GRID_SIZE
            
            # CLAMPAR A COORDENADAS VÁLIDAS
            grid_x = max(0, min(grid_x, screen_w - grid_size))
            grid_y = max(0, min(grid_y, screen_h - grid_size))
            
            if DEBUG_MODE:
                debug_img = screen.copy()
                
                # Dibujar líneas del grid calculado
                for i in range(GRID_SIZE + 1):
                    gx_line = grid_x + int(i * cell_size)
                    gy_line = grid_y + int(i * cell_size)
                    cv2.line(debug_img, (gx_line, grid_y), (gx_line, grid_y + grid_size), (100, 100, 100), 1)
                    cv2.line(debug_img, (grid_x, gy_line), (grid_x + grid_size, gy_line), (100, 100, 100), 1)
                
                # Dots del cluster (amarillo)
                for vx, vy, vw, vh in clustered_dots:
                    cv2.rectangle(debug_img, (vx, vy), (vx+vw, vy+vh), (0, 255, 255), 2)
                
                # Grid exterior
                cv2.rectangle(debug_img, (grid_x, grid_y), (grid_x+grid_size, grid_y+grid_size), (0, 0, 255), 2)
                cv2.putText(debug_img, f"Cluster: {len(clustered_dots)}, Cell: {int(cell_size)}px", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.imwrite("debug_grid_colors_result.png", debug_img)
                print(f"📸 Debug Color Grid: {len(clustered_dots)} dots, cell={int(cell_size)}px, grid={grid_size}px")
                
            return (grid_x, grid_y, grid_size, grid_size)
            
        except Exception as e:
            print(f"⚠️ Error color grid detection: {e}")
            return None

    def find_puzzle_grid(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, GRID_DETECTION_MODE

        # === MODO MANUAL: Saltar TODA la detección automática ===
        if GRID_DETECTION_MODE == "manual":
            if MANUAL_GRID_ENABLED:
                print(f"🔧 [Modo Manual] Usando grid guardado: ({MANUAL_GRID_X}, {MANUAL_GRID_Y}) {MANUAL_GRID_SIZE}px")
                return (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, MANUAL_GRID_SIZE)
            else:
                print("⚠️ [Modo Manual] No hay grid configurado. Usa Alt+J para calibrar.")
                return None

        # === MODO AUTOMÁTICO (comportamiento existente) ===
        if AUTO_ADJUST_GRID_ON_SOLVE:
             # === OPTIMIZACIÓN: CONFIG ESTABLE ===
             # Si ya tenemos una configuración estable, USARLA DIRECTAMENTE sin escanear.
             # Si falla el solve, se invalidará la config y la próxima vez escaneará.
             if STABLE_GRID_SIZE is not None:
                 print(f"⚡ [Instant] Usando configuración estable (Grid={STABLE_GRID_SIZE}px)")
                 return (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, MANUAL_GRID_SIZE)

             print("🔎 [Auto-Align] Buscando grid...")

             # --- ROI: CENTRAL SQUARE --- 
             # El usuario pide analizar solo el cuadrado central (ej: 1080x1080 en 1920x1080)
             sh, sw = screen.shape[:2]
             roi_size = min(sh, sw)
             roi_x = (sw - roi_size) // 2
             roi_y = (sh - roi_size) // 2
             
             # Crop screen for analysis
             roi_screen = screen[roi_y:roi_y+roi_size, roi_x:roi_x+roi_size]
             print(f"   ✂️ ROI Central: {roi_size}x{roi_size} en ({roi_x}, {roi_y})")
             
             # Debug: guardar el ROI raw para verificar captura
             if DEBUG_MODE:
                 cv2.imwrite("debug_roi_raw.png", roi_screen)
                 print(f"   📸 ROI raw guardado: debug_roi_raw.png ({roi_screen.shape})")

             # ====== PASO 1 (NUEVO): DETECTAR BORDE BLANCO FINO (PRIORIDAD) ======
             white_border_rect = self._find_grid_by_white_border(roi_screen)
             
             final_rect = None
             method = ""
             
             if white_border_rect:
                 wx, wy, ww, wh = white_border_rect
                 
                 # Validar que contiene colores (OBLIGATORIO)
                 roi_border = roi_screen[wy:wy+wh, wx:wx+ww]
                 # Usar is_tight_crop=True para permitir puntos cerca del borde
                 color_rect_inside = self._find_grid_by_colors(roi_border, is_tight_crop=True, debug_suffix="_WhiteBorder")
                 
                 if color_rect_inside:
                     print(f"   ◻️ Border blanco detectado y VALIDADO: ({wx}, {wy}) {ww}x{wh}")
                 else:
                     print(f"   ⚠️ [WhiteBorder] No se detectaron colores, pero se acepta por prioridad.")
                 
                 final_rect = white_border_rect
                 method = "White Border (Canny)"
             
             # ====== PASO 2: SI FALLA BORDE BLANCO, DETECTAR FONDO OSCURO ======
             if not final_rect:
                 dark_rect = self._find_dark_background(roi_screen)
                 
                 if dark_rect:
                     dx, dy, dw, dh = dark_rect
                 
                     # Validar con colores (OBLIGATORIO para evitar falsos positivos en zonas oscuras vacías)
                     dark_region = roi_screen[dy:dy+dh, dx:dx+dw]
                     # También es un tight crop si detectó el fondo correctamente
                     color_rect = self._find_grid_by_colors(dark_region, is_tight_crop=True, debug_suffix="_DarkBG")

                     if not color_rect:
                          print(f"   ⚠️ [DarkBG] Rechazado: ({dx}, {dy}) {dw}x{dh} - No contiene colores.")
                          dark_rect = None # DESCARTAR ESTE CANDIDATO
                     else:
                         print(f"   🖤 Fondo oscuro detectado y VALIDADO: ({dx}, {dy}) {dw}x{dh}")
                         
                         # El fondo oscuro DEFINE el grid
                         # Hacer el grid cuadrado usando el menor de w/h
                         dark_size = min(dw, dh)
                         
                         # Centrar el grid cuadrado dentro del área oscura
                         grid_x = dx + (dw - dark_size) // 2
                         grid_y = dy + (dh - dark_size) // 2

                         method = "Dark BG + Colors"
                         
                         # USAR COLORES PARA POSICIÓN PRECISA
                         cx, cy, cw, ch = color_rect
                         grid_x = dx + cx
                         grid_y = dy + cy
                         
                         # Usar tamaño estable si existe, sino el detectado
                         if STABLE_GRID_SIZE is not None:
                             dark_size = STABLE_GRID_SIZE
                             method = "Estable + Position"
                         else:
                             dark_size = max(cw, ch)
                         
                         final_rect = (grid_x, grid_y, dark_size, dark_size)
                         print(f"   📐 Grid ajustado por colores: ({grid_x}, {grid_y}) {dark_size}x{dark_size}")
                     
                     # LOG: Mostrar el grid final que se usará
                     if final_rect:
                          print(f"   📐 Grid FINAL: ({final_rect[0]}, {final_rect[1]}) {final_rect[2]}x{final_rect[3]}")
             else:
                 # Fallback: buscar por colores si no hay fondo oscuro
                 print("   ⚠️ No hay fondo oscuro. Buscando solo por colores...")
                 # Aquí no es tight crop (es todo el ROI screen)
                 color_rect = self._find_grid_by_colors(roi_screen, is_tight_crop=False, debug_suffix="_Fallback")
                 
                 if color_rect:
                     # Color rect está en coordenadas RELATIVAS al ROI
                     print(f"   📍 (ROI) Grid colores: {color_rect}")
                     final_rect = color_rect
                     method = "Color Grid (No Dark BG)"
                 else:
                     print("   ⚠️ No colores. Probando detección por borde...")
                     
                     # Intentar método de COLOR del borde (HSV)
                     border_color_rect = self._find_grid_by_border_color(roi_screen)
                     if border_color_rect:
                         final_rect = border_color_rect
                         method = "Border Color (HSV)"
                         print(f"   ✓ Border por color: {border_color_rect}")
                     else:
                         # Fallback: método threshold clásico
                         border_rect = self._find_grid_by_white_border(roi_screen)
                         if border_rect:
                             final_rect = border_rect
                             method = "White Border (Threshold)"
             
             # Draw ROI Debug
             if DEBUG_MODE:
                 debug_full = screen.copy()
                 # ROI box (azul)
                 cv2.rectangle(debug_full, (roi_x, roi_y), (roi_x+roi_size, roi_y+roi_size), (255, 0, 0), 2)
                 if final_rect:
                     rx, ry, rw, rh = final_rect
                     global_x, global_y = rx + roi_x, ry + roi_y
                     # Final grid (verde)
                     cv2.rectangle(debug_full, (global_x, global_y), (global_x+rw, global_y+rh), (0, 255, 0), 3)
                     # Método usado (texto)
                     cv2.putText(debug_full, f"Method: {method}", (global_x, global_y - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                 else:
                     cv2.putText(debug_full, "NO GRID FOUND", (roi_x + 20, roi_y + 40), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                 cv2.imwrite("debug_grid_roi_analysis.png", debug_full)

             if final_rect:
                 # Convert ROI coords to Global coords
                 rx, ry, rw, rh = final_rect
                 gx = rx + roi_x
                 gy = ry + roi_y
                 
                 # ENFORCE SQUARE STRICT (W=H)
                 final_size = (rw + rh) // 2
                 
                 print(f"✅ Grid detectado ({method}): ({gx}, {gy}) {final_size}x{final_size}px")
                 
                 MANUAL_GRID_X = gx
                 MANUAL_GRID_Y = gy
                 MANUAL_GRID_SIZE = final_size
                 MANUAL_GRID_ENABLED = True
                 save_manual_config()
                 return (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, MANUAL_GRID_SIZE)
             else:
                 print("⚠️ Auto-Align falló. Usando configuración guardada.")

        if MANUAL_GRID_ENABLED:
            return (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, MANUAL_GRID_SIZE)
        
        bg_rect = self._find_grid_by_dark_background(screen)
        if bg_rect:
             return bg_rect
             
        return None

    def _find_grid_by_dark_background(self, screen: np.ndarray):
        try:
            gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            _, dark_mask = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
            kernel = np.ones((5, 5), np.uint8)
            dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 100000 < area < 300000:
                    x, y, w, h = cv2.boundingRect(cnt)
                    if 0.8 < w/h < 1.2 and 300 < w < 550:
                        return (x, y, w, h)
            return None
        except:
            return None

    def _get_cell_dominant_hsv(self, roi):
        """Obtiene el HSV dominante de una ROI de celda."""
        sat_channel = roi[:, :, 1]
        val_channel = roi[:, :, 2]
        
        # Píxel con mayor saturación (el del color del dot)
        max_sat_idx = np.unravel_index(np.argmax(sat_channel), sat_channel.shape)
        h = int(roi[max_sat_idx[0], max_sat_idx[1], 0])
        s = int(roi[max_sat_idx[0], max_sat_idx[1], 1])
        v = int(roi[max_sat_idx[0], max_sat_idx[1], 2])
        
        median_sat = float(np.median(sat_channel))
        high_sat_pixels = int(np.sum(sat_channel > 80))
        total_pixels = sat_channel.size
        high_sat_ratio = high_sat_pixels / total_pixels if total_pixels > 0 else 0
        
        # Brightest pixel (for low-sat colors like beige/white)
        max_val_idx = np.unravel_index(np.argmax(val_channel), val_channel.shape)
        bh = int(roi[max_val_idx[0], max_val_idx[1], 0])
        bs = int(roi[max_val_idx[0], max_val_idx[1], 1])
        bv = int(roi[max_val_idx[0], max_val_idx[1], 2])
        
        return h, s, v, median_sat, high_sat_ratio, bh, bs, bv

    def _is_cell_colored(self, h, s, v, median_sat, high_sat_ratio, bh, bs, bv):
        """Determina si una celda tiene un dot de color (genérico, sin hardcodear)."""
        # Caso 1: Color saturado (la mayoría de los dots) — incluye dots oscuros
        if s > 60 and v > 35 and high_sat_ratio > 0.02:
            return (h, s, v)
        # Caso 2: Color claro/bajo (beige, blanco, pastel)
        if bv > 140 and bs < 140 and high_sat_ratio < 0.20:
            if bv > 180:
                return (bh, bs, bv)
        # Caso 3: Saturación moderada pero consistente — relajado
        if median_sat > 30 and s > 40 and v > 60:
            return (h, s, v)
        # Caso 4: Dot pequeño pero visible — cualquier píxel saturado
        if s > 100 and v > 80:
            return (h, s, v)
        return None

    def _save_debug_grid(self, grid_img: np.ndarray, endpoints: Dict[Tuple[int, int], int], 
                         prefix: str = "debug", id_to_color: Dict[int, str] = None):
        """Método reutilizable para guardar imágenes de debug con anotaciones"""
        try:
            debug_grid = grid_img.copy()
            h, w = debug_grid.shape[:2]
            cell_h = h / GRID_SIZE
            cell_w = w / GRID_SIZE
            
            # Dibujar líneas del grid
            for i in range(1, GRID_SIZE):
                x = int(i * cell_w)
                cv2.line(debug_grid, (x, 0), (x, h), (0, 255, 0), 1)
                y = int(i * cell_h)
                cv2.line(debug_grid, (0, y), (w, y), (0, 255, 0), 1)

            # Dibujar puntos
            for (r, c), color_id in endpoints.items():
                cx = int(c * cell_w + cell_w / 2)
                cy = int(r * cell_h + cell_h / 2)
                
                # Nombre del color si está disponible
                color_name = ""
                if id_to_color and color_id in id_to_color:
                    color_name = id_to_color[color_id][:3] # 3 chars
                
                cv2.putText(debug_grid, f"{color_id}{color_name}", (cx-15, cy+5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                cv2.circle(debug_grid, (cx, cy), 2, (0, 255, 255), -1)

            timestamp = int(time.time())
            filename = f"{prefix}_{timestamp}.png"
                
            cv2.imwrite(filename, debug_grid)
            print(f"   📸 Debug guardado: {filename}")
            
        except Exception as e:
            print(f"   ⚠️ Error guardando debug: {e}")

    def analyze_grid(self, grid_img: np.ndarray):
        """
        Detecta endpoints del puzzle auto-detectando colores por clustering HSV.
        No necesita rangos hardcodeados — agrupa celdas con colores similares.
        """
        h, w = grid_img.shape[:2]
        cell_h, cell_w = h / GRID_SIZE, w / GRID_SIZE
        hsv = cv2.cvtColor(grid_img, cv2.COLOR_BGR2HSV)
        
        # === PASO 1: Recopilar celdas con color ===
        colored_cells = []  # [(row, col, h, s, v)]
        
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                x1 = int(col * cell_w + cell_w * 0.05)
                y1 = int(row * cell_h + cell_h * 0.05)
                x2 = int((col + 1) * cell_w - cell_w * 0.05)
                y2 = int((row + 1) * cell_h - cell_h * 0.05)
                
                roi = hsv[y1:y2, x1:x2]
                if roi.size == 0: continue
                
                result = self._get_cell_dominant_hsv(roi)
                h_val, s_val, v_val, med_sat, sat_ratio, bh, bs, bv = result
                
                color_hsv = self._is_cell_colored(h_val, s_val, v_val, med_sat, sat_ratio, bh, bs, bv)
                if color_hsv:
                    colored_cells.append((row, col, color_hsv[0], color_hsv[1], color_hsv[2]))
                    if DEBUG_MODE:
                        print(f"      ({row},{col}): H={color_hsv[0]} S={color_hsv[1]} V={color_hsv[2]}")
                elif DEBUG_MODE and s_val > 30:
                    # Show rejected cells too — helps debug missing colors
                    print(f"      ({row},{col}): H={h_val} S={s_val} V={v_val} [REJECTED med_sat={med_sat:.0f} ratio={sat_ratio:.3f}]")
        
        if DEBUG_MODE:
            print(f"   [AutoDetect] Celdas con color: {len(colored_cells)}")
        
        if len(colored_cells) < 2:
            if DEBUG_MODE:
                print("   ⚠️ [AutoDetect] Muy pocas celdas con color")
            return {}, {}
        
        # === PASO 2: Clustering por similitud HSV ===
        # Umbral adaptativo: calcular distancias medias y usar un umbral relativo
        CLUSTER_THRESHOLD = 600  # Distancia HSV al cuadrado (bajado para separar rojo/naranja)
        
        # Filtrar celdas achromáticas (S<30) — no son dots de puzzle, son UI/ruido
        colored_cells = [c for c in colored_cells if c[3] > 30]
        if DEBUG_MODE:
            print(f"   [AutoDetect] Después de filtrar achromáticos: {len(colored_cells)} celdas")
        
        # Asignar clusters greedy: cada celda se une al cluster más cercano o crea uno nuevo
        clusters = []  # Cada cluster: lista de (row, col, h, s, v)
        
        for cell in colored_cells:
            row, col, ch, cs, cv = cell
            best_cluster = -1
            best_dist = float('inf')
            
            for i, cluster in enumerate(clusters):
                # Distancia al promedio del cluster
                avg_h = np.mean([c[2] for c in cluster])
                avg_s = np.mean([c[3] for c in cluster])
                avg_v = np.mean([c[4] for c in cluster])
                dist = _hsv_distance(ch, cs, cv, avg_h, avg_s, avg_v)
                if dist < best_dist:
                    best_dist = dist
                    best_cluster = i
            
            if best_cluster >= 0 and best_dist < CLUSTER_THRESHOLD:
                clusters[best_cluster].append(cell)
            else:
                clusters.append([cell])
        
        if DEBUG_MODE:
            print(f"   [AutoDetect] Clusters encontrados: {len(clusters)}")
            for i, cluster in enumerate(clusters):
                avg_h = int(np.mean([c[2] for c in cluster]))
                avg_s = int(np.mean([c[3] for c in cluster]))
                avg_v = int(np.mean([c[4] for c in cluster]))
                positions = [(c[0], c[1]) for c in cluster]
                print(f"      Cluster {i+1}: H={avg_h} S={avg_s} V={avg_v} → {positions}")
        
        # === PASO 3: Construir endpoints ===
        # Cada cluster = un color. Si tiene exactamente 2 celdas = endpoints perfectos.
        # Si tiene más, podría ser ruido — intentar sub-clusters.
        endpoints = {}
        id_to_color_map = {}
        color_id = 0
        
        for cluster in clusters:
            if len(cluster) < 2:
                if DEBUG_MODE:
                    print(f"      ⚠️ Cluster con 1 sola celda ignorado: ({cluster[0][0]},{cluster[0][1]})")
                continue
            
            color_id += 1
            avg_h = int(np.mean([c[2] for c in cluster]))
            avg_s = int(np.mean([c[3] for c in cluster]))
            avg_v = int(np.mean([c[4] for c in cluster]))
            
            for (row, col, _, _, _) in cluster:
                endpoints[(row, col)] = color_id
            
            id_to_color_map[color_id] = f"C{color_id}(H{avg_h}S{avg_s}V{avg_v})"
        
        if DEBUG_MODE:
            print(f"   [AutoDetect] Total endpoints: {len(endpoints)}, Colores: {color_id}")
            self._save_debug_grid(grid_img, endpoints, "debug_analyzed", id_to_color_map)
            
        return endpoints, id_to_color_map

    def solve_puzzle(self, endpoints: Dict[Tuple[int, int], int], grid_img: Optional[np.ndarray] = None, 
                     id_to_color: Dict[int, str] = None) -> Dict[int, List[Tuple[int, int]]]:
        """
        Resuelve usando backtracking ITERATIVO para evitar RecursionError.
        """
        # Preparar grid y mapa de endpoints
        grid = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.endpoints_map = {} # Pos -> ID (para restauración correcta al hacer backtrack)
        
        for (r, c), num in endpoints.items():
            grid[r][c] = num
            self.endpoints_map[(r,c)] = num
            
        # Identificar pares (start, end)
        pairs_dict = {}
        for (r, c), num in endpoints.items():
            if num not in pairs_dict:
                pairs_dict[num] = []
            pairs_dict[num].append((r, c))
            
        # Validar pares
        inputs = []
        for num, coords in pairs_dict.items():
            if len(coords) != 2:
                continue 
            inputs.append({'id': num, 'start': coords[0], 'end': coords[1]})
            
        if not inputs:
            print("   ❌ No hay pares válidos para resolver")
            return {}
            
        # Ordenar por distancia Manhattan (heurística)
        inputs.sort(key=lambda x: abs(x['start'][0]-x['end'][0]) + abs(x['start'][1]-x['end'][1]))
        
        self.final_paths = {}
        
        print(f"   Resolviendo {len(inputs)} caminos (Iterativo)...")
        
        # Ejecutar solver iterativo
        if self._solve_iterative(grid, inputs):
            return self.final_paths
        else:
            return {}

    def _solve_iterative(self, grid, inputs):
        """
        Implementación de backtracking usando una pila explícita.
        """
        if not inputs: return True
        initial_input = inputs[0]
        
        stack = [{
            'idx': 0,
            'current': initial_input['start'],
            'path': [initial_input['start']],
            'neighbors': self._get_neighbors(initial_input['start'], initial_input['end'], grid),
            'tried_next': False
        }]
        
        while stack:
            if emergency_stop_flag: return False

            frame = stack[-1]
            idx = frame['idx']
            current_input = inputs[idx]
            color_id = current_input['id']
            end_pos = current_input['end']
            r, c = frame['current']
            
            # --- CASO 1: Llegamos al destino del color actual ---
            if r == end_pos[0] and c == end_pos[1]:
                if frame['tried_next']:
                    # Backtracking: Eliminamos este camino
                    if color_id in self.final_paths:
                        del self.final_paths[color_id]
                    stack.pop()
                    continue
                else:
                    # Éxito parcial: Guardamos camino e intentamos el siguiente color
                    self.final_paths[color_id] = frame['path']
                    frame['tried_next'] = True
                    
                    if idx == len(inputs) - 1:
                        return True # ¡SOLUCIÓN COMPLETA!
                    
                    next_idx = idx + 1
                    next_start = inputs[next_idx]['start']
                    next_end = inputs[next_idx]['end']
                    
                    stack.append({
                        'idx': next_idx,
                        'current': next_start,
                        'path': [next_start],
                        'neighbors': self._get_neighbors(next_start, next_end, grid),
                        'tried_next': False
                    })
                    continue

            # --- CASO 2: Explorando vecinos ---
            try:
                # Obtener siguiente vecino válido
                nr, nc = next(frame['neighbors'])
                
                grid[nr][nc] = color_id
                
                stack.append({
                    'idx': idx,
                    'current': (nr, nc),
                    'path': frame['path'] + [(nr, nc)],
                    'neighbors': self._get_neighbors((nr, nc), end_pos, grid),
                    'tried_next': False
                })
                
            except StopIteration:
                # Dead end -> Backtrack
                stack.pop()
                if (r,c) in self.endpoints_map:
                    grid[r][c] = self.endpoints_map[(r,c)]
                else:
                    grid[r][c] = 0
                    
        return False

    def _get_neighbors(self, current, end, grid):
        """Generador de vecinos válidos ordenados por heurística"""
        r, c = current
        neighbors = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                val = grid[nr][nc]
                if (nr, nc) == end:
                    neighbors.append((nr, nc))
                elif val == 0:
                    neighbors.append((nr, nc))
                    
        # Heurística: Ordenar vecinos por distancia Manhatan al destino
        neighbors.sort(key=lambda p: abs(p[0]-end[0]) + abs(p[1]-end[1]))
        return iter(neighbors)

    def _perform_spiral_wobble(self, center_x, center_y, radius=None, cell_size=None, duration=None):
        """
        Realiza un movimiento en espiral desde el centro hacia afuera para asegurar agarre.
        El radio se calcula como cell_size * WOBBLE_RATIO si se proporciona cell_size.
        """
        if duration is None:
            duration = WOBBLE_DURATION_START
        
        # Calcular radio usando WOBBLE_RATIO si tenemos cell_size
        if radius is not None:
            max_radius = radius
        elif cell_size is not None:
            max_radius = int(cell_size * WOBBLE_RATIO)
        else:
            max_radius = 7  # Fallback
        
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > duration: break
            if emergency_stop_flag: return
            
            progress = min(elapsed / duration, 1.0)
            # Radius envelope: expand then contract back to 0
            # Ensures the wobble ends at the exact center position
            if progress < 0.5:
                current_radius = max_radius * (progress * 2.0)
            else:
                current_radius = max_radius * ((1.0 - progress) * 2.0)
            angle = progress * (4 * np.pi)
            
            offset_x = int(current_radius * np.cos(angle))
            offset_y = int(current_radius * np.sin(angle))
            
            self.input.move_mouse(center_x + offset_x, center_y + offset_y)
            self.input.move_mouse(center_x + offset_x, center_y + offset_y)
            self.input.mouse_down() # Spam down
            time.sleep(WOBBLE_LOOP_SLEEP)

    def _get_cursor_pos(self):
        """Query actual cursor position from Hyprland."""
        try:
            result = subprocess.run(
                ["hyprctl", "cursorpos"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().replace(" ", "").split(",")
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None, None

    def draw_solution(self, solutions, grid_origin, grid_rect_size):
        cell_w = grid_rect_size[0] / GRID_SIZE
        cell_h = grid_rect_size[1] / GRID_SIZE
        
        if DEBUG_MODE:
            print(f"   [EXEC] Grid origin: ({grid_origin[0]}, {grid_origin[1]}), size: ({grid_rect_size[0]}, {grid_rect_size[1]})")
            print(f"   [EXEC] Cell size: {cell_w:.1f} x {cell_h:.1f}")
        
        # === SCALE DETECTION: grim resolution vs ydotool coordinate space ===
        # grim captures at physical pixel resolution (Wayland output).
        # ydotool absolute uses the compositor's logical coordinate space.
        # If display scaling or mirrored outputs differ, we need a scale factor.
        grim_w = grid_origin[0] + grid_rect_size[0]  # right edge in grim coords
        grim_h = grid_origin[1] + grid_rect_size[1]  # bottom edge in grim coords
        
        # Move cursor to grid center using grim coords
        grid_cx = grid_origin[0] + grid_rect_size[0] // 2
        grid_cy = grid_origin[1] + grid_rect_size[1] // 2
        if hasattr(self.input, 'absolute_move'):
            self.input.absolute_move(grid_cx, grid_cy)
        else:
            self.input.move_mouse(grid_cx, grid_cy)
        time.sleep(0.15)  # Pause for cursor to settle
        
        # Measure actual cursor position to verify hyprctl works
        actual_x, actual_y = None, None
        if hasattr(self.input, 'sync_cursor_position'):
            self.input.sync_cursor_position()
        actual_x = getattr(self.input, '_cursor_x', None)
        actual_y = getattr(self.input, '_cursor_y', None)
        if actual_x is not None:
            print(f"   [CAL] Cursor at ({actual_x}, {actual_y}) — using hyprctl+EV_REL (no ydotool)")
        else:
            print("   [CAL] WARNING: hyprctl cursorpos failed, EV_REL may drift")
        
        for color_id, path in solutions.items():
            if emergency_stop_flag: return
            
            # Calcular puntos en float para mayor precisión
            screen_points = []
            for r, c in path:
                fx = grid_origin[0] + c * cell_w + cell_w/2
                fy = grid_origin[1] + r * cell_h + cell_h/2
                screen_points.append((fx, fy))
                
            if not screen_points: continue
            
            if DEBUG_MODE and color_id <= 2:
                print(f"   [EXEC] Color {color_id}: primer punto → ({int(screen_points[0][0])}, {int(screen_points[0][1])}), último → ({int(screen_points[-1][0])}, {int(screen_points[-1][1])})")
                
            # --- APPLY BIAS (Start Back, End Forward) ---
            if len(screen_points) >= 2:
                # Adjust Start (Backward)
                p0, p1 = screen_points[0], screen_points[1]
                dx, dy = p1[0]-p0[0], p1[1]-p0[1]
                
                # Normalize direction
                if abs(dx) > abs(dy): dir_x, dir_y = (1 if dx>0 else -1), 0
                else: dir_x, dir_y = 0, (1 if dy>0 else -1)
                
                # Backtrack start
                nsx = p0[0] - dir_x * (cell_w * START_PATH_BIAS)
                nsy = p0[1] - dir_y * (cell_h * START_PATH_BIAS)
                screen_points[0] = (nsx, nsy)
                
                # Adjust End (Forward)
                pl, pp = screen_points[-1], screen_points[-2]
                dx_end, dy_end = pl[0]-pp[0], pl[1]-pp[1]
                
                if abs(dx_end) > abs(dy_end): dex, dey = (1 if dx_end>0 else -1), 0
                else: dex, dey = 0, (1 if dy_end>0 else -1)
                
                nex = pl[0] + dex * (cell_w * END_PATH_BIAS)
                ney = pl[1] + dey * (cell_h * END_PATH_BIAS)
                screen_points[-1] = (nex, ney)
            
            # Integer conversion just before drawing
            points_int = [(int(x), int(y)) for x, y in screen_points]
            
            # Use absolute move to start of each color — prevents accumulated EV_REL drift
            # start_p is already in ydotool coords (scale applied to screen_points above)
            start_p = points_int[0]
            target_x = start_p[0]
            target_y = start_p[1]
            if hasattr(self.input, 'absolute_move'):
                self.input.absolute_move(target_x, target_y)
            else:
                self.input.move_mouse(target_x, target_y)
            time.sleep(DELAY_BEFORE_MOUSEDOWN)
            
            if emergency_stop_flag: return
            self.input.mouse_down()
            
            # Wobble (usar promedio de cell_w y cell_h para el cálculo del radio)
            avg_cell_size = (cell_w + cell_h) / 2
            # Wobble center must also be in ydotool coords (already scaled in points_int)
            self._perform_spiral_wobble(target_x, target_y, cell_size=avg_cell_size)
            
            # Draw Path
            for i in range(1, len(points_int)):
                if emergency_stop_flag: 
                    self.input.mouse_up()
                    return
                p = points_int[i]
                
                # Check if this is the final segment of the path
                is_final_segment = (i == len(points_int) - 1)
                
                # Smooth move interpolation
                steps = MOUSE_INTERPOLATION_STEPS
                curr = points_int[i-1]
                for s in range(1, steps+1):
                    t = s/steps
                    ix = int(curr[0] + (p[0] - curr[0])*t)
                    iy = int(curr[1] + (p[1] - curr[1])*t)
                    self.input.move_mouse(ix, iy)
                    
                    if is_final_segment:
                        time.sleep(FINAL_STEP_DELAY_MS / 1000.0)
                    else:
                        time.sleep(STEP_DELAY_MS / 1000.0)
                    
            # --- FIX: Asegurar conexión al final ---
            # Esperamos la retención configurada por el usuario (END_NODE_HOLD_TIME_MS)
            time.sleep(END_NODE_HOLD_TIME_MS / 1000.0)
            self.input.mouse_up()
            time.sleep(DELAY_BETWEEN_COLORS)

    def solve(self):
        global emergency_stop_flag
        global STABLE_GRID_SIZE, STABLE_CELL_SIZE, STABLE_SUCCESS_COUNT, LAST_DETECTED_SIZE
        
        if self.is_solving: return
        self.is_solving = True
        emergency_stop_flag = False
        
        try:
            print("🔍 [SCAN] Analizando pantalla...")
            screen = self.capture_screen()
            grid_rect = self.find_puzzle_grid(screen)
            
            if not grid_rect:
                print("❌ No se detectó grid. ¿No hay puzzle en pantalla?")
                # Invalidar config estable si falla detección
                self._invalidate_stable_config("No grid detectado")
                return
                
            print(f"✅ Grid: {grid_rect}")
            current_grid_size = grid_rect[2]  # Width of grid
            
            grid_img = self.extract_grid(screen, grid_rect)
            
            # Validación de Grid Válido (Evitar negro)
            if np.mean(grid_img) < 5:
                print("❌ Grid negro/inválido (Error de visión).")
                self._invalidate_stable_config("Grid negro")
                return

            endpoints, id_to_color = self.analyze_grid(grid_img)
            
            # === VALIDACIÓN MEJORADA ===
            # Mínimo puntos dinámico según MIN_COLORS_TO_SOLVE
            min_points = MIN_COLORS_TO_SOLVE * 2
            if len(endpoints) < min_points:
                print(f"❌ Insuficientes puntos ({len(endpoints)} < {min_points}). ¿No hay puzzle?")
                self._invalidate_stable_config(f"Pocos puntos (<{min_points})")
                return
            
            # Mínimo 5 colores diferentes
            unique_colors = set()
            for _, color_id in endpoints.items():
                unique_colors.add(color_id)
            
            if len(unique_colors) < MIN_COLORS_TO_SOLVE:
                print(f"❌ Insuficientes colores ({len(unique_colors)} < {MIN_COLORS_TO_SOLVE}). ¿No hay puzzle válido?")
                self._invalidate_stable_config(f"Pocos colores (<{MIN_COLORS_TO_SOLVE})")
                return
                
            print(f"🧮 [SOLVE] Resolviendo...")
            solutions = self.solve_puzzle(endpoints, grid_img, id_to_color)
            
            if not solutions:
                print("❌ No solución.")
                self._invalidate_stable_config("Sin solución")
                return
                
            if emergency_stop_flag: return
            
            print(f"✅ [EXECUTE] Dibujando...")
            # NO sync cursor position here — hyprctl returns system cursor pos,
            # but Roblox warps cursor after each draw. Internal tracking is more reliable.
            self.draw_solution(solutions, (grid_rect[0], grid_rect[1]), (grid_rect[2], grid_rect[3]))
            print("✅ [DONE] Finalizado.")
            
            # === ACTUALIZAR ESTABILIDAD ===
            self._update_stability_on_success(current_grid_size)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            self._invalidate_stable_config(f"Excepción: {e}")
        finally:
            self.is_solving = False
    
    def _update_stability_on_success(self, detected_size):
        """Actualiza el contador de estabilidad cuando hay éxito."""
        global STABLE_GRID_SIZE, STABLE_CELL_SIZE, STABLE_SUCCESS_COUNT, LAST_DETECTED_SIZE
        
        cell_size = detected_size / GRID_SIZE
        
        # ¿Es el mismo tamaño que antes (con tolerancia)?
        if LAST_DETECTED_SIZE is not None:
            size_diff = abs(detected_size - LAST_DETECTED_SIZE)
            if size_diff <= STABLE_SIZE_TOLERANCE:
                STABLE_SUCCESS_COUNT += 1
                print(f"📊 Estabilidad: {STABLE_SUCCESS_COUNT}/{STABLE_THRESHOLD} (size={detected_size})")
                
                # ¿Alcanzamos el umbral?
                if STABLE_SUCCESS_COUNT >= STABLE_THRESHOLD and STABLE_GRID_SIZE is None:
                    STABLE_GRID_SIZE = detected_size
                    STABLE_CELL_SIZE = int(cell_size)
                    print(f"🔒 ¡CONFIG ESTABLE! Grid={STABLE_GRID_SIZE}px, Celda={STABLE_CELL_SIZE}px")
                    save_manual_config()
            else:
                # Tamaño diferente, reiniciar contador
                print(f"📊 Tamaño cambió ({LAST_DETECTED_SIZE}→{detected_size}). Reiniciando estabilidad.")
                STABLE_SUCCESS_COUNT = 1
        else:
            STABLE_SUCCESS_COUNT = 1
        
        LAST_DETECTED_SIZE = detected_size
        save_manual_config()
    
    def _invalidate_stable_config(self, reason):
        """Invalida la configuración estable cuando hay un fallo."""
        global STABLE_GRID_SIZE, STABLE_CELL_SIZE, STABLE_SUCCESS_COUNT
        
        if STABLE_GRID_SIZE is not None:
            print(f"⚠️ Config estable invalidada: {reason}")
            STABLE_GRID_SIZE = None
            STABLE_CELL_SIZE = None
            STABLE_SUCCESS_COUNT = 0
            save_manual_config()

    def extract_grid(self, screen, rect):
        x, y, w, h = rect
        return screen[y:y+h, x:x+w].copy()

# ============================================================
# MAIN
# ============================================================
solver = FlowPuzzleSolver(INPUT_ADAPTER, VISION_ADAPTER)

def _on_movement_interrupt():
    """Called by evdev when user presses WASD/arrows/space/shift"""
    global emergency_stop_flag
    if solver.is_solving:
        print(f"\n🛑 Movimiento detectado. Cancelando solver.")
    emergency_stop_flag = True

def main():
    print("=" * 60)
    print("🎮 Forsaken AutoComplete (Linux Edition)")
    print(f"   Platform: {sys.platform}")
    print("=" * 60)

    # 1. Setup all hotkeys via evdev (no pynput needed)
    if HOTKEY_MANAGER:
        print("   ⌨️  Using evdev Hotkey Manager")

        # F4 = emergency stop
        def on_f4():
            global emergency_stop_flag
            print("\n🛑 [F4] PARADA DE EMERGENCIA ACTIVADA")
            emergency_stop_flag = True
        HOTKEY_MANAGER.register('F4', on_f4)

        # J = solve puzzle
        HOTKEY_MANAGER.register('j', lambda: threading.Thread(target=solver.solve).start())

        # Alt+J = grid selector
        HOTKEY_MANAGER.register_combo('alt+j', open_grid_selector)

        # WASD/arrows/space/shift = movement interrupt
        HOTKEY_MANAGER.register_movement_interrupt(_on_movement_interrupt)

        HOTKEY_MANAGER.start()
    else:
        print("   ⚠️  No evdev hotkey manager available!")

    # --- INTERFAZ GRÁFICA (GUI) ---
    try:
        root = tk.Tk()
        root.title("ForsakenAC")
        # Set WM class for Hyprland rules
        try:
            root.tk.call('wm', 'class', root._w, 'forsaken-ac')
        except Exception:
            pass

        # Make window float on Hyprland
        try:
            import subprocess
            subprocess.run(
                ["hyprctl", "keyword", "windowrulev2", "float,class:^(forsaken-ac)$"],
                capture_output=True, timeout=2
            )
        except Exception:
            pass
        
        # Icono (Linux)
        try:
            icon_path_png = resource_path(os.path.join("assets", "ForsakenAC.png"))
            if os.path.exists(icon_path_png):
                img_icon = tk.PhotoImage(file=icon_path_png)
                root.iconphoto(True, img_icon)
        except Exception as e:
            print(f"⚠️ Warning loading icon: {e}")
            
        # Configurar ventana no muy grande
        root.resizable(False, False)
        
        # Cargar AMBAS imágenes de instrucciones según el modo
        img_path_auto = resource_path(os.path.join("assets", "VanityInst_auto.png"))
        img_path_manual = resource_path(os.path.join("assets", "VanityInst_manual.png"))
        
        # Verificar que existan las imágenes
        has_auto_img = os.path.exists(img_path_auto)
        has_manual_img = os.path.exists(img_path_manual)
        
        if has_auto_img or has_manual_img:
            try:
                target_width = 600
                
                # Cargar imagen AUTO
                tk_img_auto = None
                if has_auto_img:
                    original_auto = Image.open(img_path_auto)
                    w_percent = (target_width / float(original_auto.size[0]))
                    h_size_auto = int((float(original_auto.size[1]) * float(w_percent)))
                    resized_auto = original_auto.resize((target_width, h_size_auto), Image.Resampling.LANCZOS)
                    tk_img_auto = ImageTk.PhotoImage(resized_auto)
                
                # Cargar imagen MANUAL
                tk_img_manual = None
                if has_manual_img:
                    original_manual = Image.open(img_path_manual)
                    w_percent = (target_width / float(original_manual.size[0]))
                    h_size_manual = int((float(original_manual.size[1]) * float(w_percent)))
                    resized_manual = original_manual.resize((target_width, h_size_manual), Image.Resampling.LANCZOS)
                    tk_img_manual = ImageTk.PhotoImage(resized_manual)
                
                # Elegir imagen inicial según el modo actual
                initial_img = tk_img_manual if GRID_DETECTION_MODE == "manual" else tk_img_auto
                if initial_img is None:
                    initial_img = tk_img_auto or tk_img_manual
                
                # Main layout frame
                main_layout = tk.Frame(root, bg="#1a1a1a")
                main_layout.pack(fill=tk.BOTH, expand=True)
                
                left_panel = tk.Frame(main_layout, bg="#1a1a1a")
                left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                
                right_panel = tk.Frame(main_layout, bg="#212121")
                right_panel.pack(side=tk.RIGHT, fill=tk.Y)

                # Label de imagen (se actualizará al cambiar de modo)
                img_label = tk.Label(left_panel, image=initial_img, bg="#1a1a1a")
                img_label.image = initial_img  # KEEP REFERENCE!
                img_label.pack(pady=(10, 0), padx=10)
                
                # Guardar referencias para poder cambiar después
                img_label.tk_img_auto = tk_img_auto
                img_label.tk_img_manual = tk_img_manual
                
                # Label de estado abajo
                status_label = tk.Label(left_panel, text="Bot activo. Presiona J para resolver. Alt+J para calibrar.", 
                                       font=("Arial", 10), bg="#333", fg="white", pady=5)
                status_label.pack(side=tk.BOTTOM, fill=tk.X, pady=10, padx=10)
                
                # --- SWITCH DE MODO (Auto/Manual) ---
                switch_frame = tk.Frame(right_panel, bg="#2a2a2a", pady=10)
                switch_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
                
                # Mode Label
                mode_label = tk.Label(switch_frame, text="Modo Detección:", 
                                      font=("Arial", 10, "bold"), bg="#2a2a2a", fg="white")
                mode_label.pack(side=tk.LEFT, padx=(20, 10))
                
                # Auto label
                auto_label = tk.Label(switch_frame, text="Auto", 
                                      font=("Arial", 9, "bold"), bg="#2a2a2a", 
                                      fg="#00FF00" if GRID_DETECTION_MODE == "auto" else "#666666")
                auto_label.pack(side=tk.LEFT)
                
                # Switch Canvas
                switch_canvas = tk.Canvas(switch_frame, width=50, height=24, bg="#2a2a2a", 
                                          highlightthickness=0, cursor="hand2")
                switch_canvas.pack(side=tk.LEFT, padx=5)
                
                # Manual label (creado antes para que toggle_mode pueda referenciarlo)
                manual_label = tk.Label(switch_frame, text="Manual", 
                                        font=("Arial", 9, "bold"), bg="#2a2a2a", 
                                        fg="#00FF00" if GRID_DETECTION_MODE == "manual" else "#666666")
                manual_label.pack(side=tk.LEFT)
                
                # Info tooltip
                info_label = tk.Label(switch_frame, 
                                      text="(Auto: detecta grid | Manual: usa Alt+J)", 
                                      font=("Arial", 8), bg="#2a2a2a", fg="#888888")
                info_label.pack(side=tk.LEFT, padx=(15, 0))
                
                def update_switch_visual(is_manual):
                    switch_canvas.delete("all")
                    # Track background
                    track_color = "#4CAF50" if is_manual else "#555555"
                    switch_canvas.create_oval(0, 2, 48, 22, fill=track_color, outline=track_color)
                    # Knob position
                    knob_x = 28 if is_manual else 4
                    switch_canvas.create_oval(knob_x, 4, knob_x+16, 20, fill="white", outline="#cccccc")
                
                def update_mode_image(is_manual):
                    """Cambia la imagen según el modo seleccionado"""
                    if is_manual and img_label.tk_img_manual:
                        img_label.config(image=img_label.tk_img_manual)
                        img_label.image = img_label.tk_img_manual
                    elif not is_manual and img_label.tk_img_auto:
                        img_label.config(image=img_label.tk_img_auto)
                        img_label.image = img_label.tk_img_auto
                
                def toggle_mode(event=None):
                    global GRID_DETECTION_MODE
                    if GRID_DETECTION_MODE == "auto":
                        GRID_DETECTION_MODE = "manual"
                        auto_label.config(fg="#666666")
                        manual_label.config(fg="#00FF00")
                        update_switch_visual(True)
                        update_mode_image(True)
                    else:
                        GRID_DETECTION_MODE = "auto"
                        auto_label.config(fg="#00FF00")
                        manual_label.config(fg="#666666")
                        update_switch_visual(False)
                        update_mode_image(False)
                    save_manual_config()
                    print(f"🔄 Modo cambiado a: {GRID_DETECTION_MODE.upper()}")
                
                switch_canvas.bind("<Button-1>", toggle_mode)
                update_switch_visual(GRID_DETECTION_MODE == "manual")
                
                # --- SLIDER DE VELOCIDAD DE RATÓN ---
                speed_frame = tk.Frame(right_panel, bg="#212121", pady=10)
                speed_frame.pack(fill=tk.X, padx=10, pady=5)
                
                speed_label = tk.Label(speed_frame, text="Velocidad (Pasos de interpolación):", 
                                      font=("Arial", 9, "bold"), bg="#212121", fg="white")
                speed_label.pack(side=tk.TOP, padx=(20, 10))
                
                def on_speed_change(val):
                    global MOUSE_INTERPOLATION_STEPS
                    MOUSE_INTERPOLATION_STEPS = int(val)
                    save_manual_config()
                
                # Menos pasos = más rápido. Slider de 1 a 25.
                speed_slider = tk.Scale(speed_frame, from_=1, to=25, orient=tk.HORIZONTAL, 
                                        command=on_speed_change, bg="#212121", fg="#00FF00", 
                                        troughcolor="#333333", highlightthickness=0, length=300)
                speed_slider.set(MOUSE_INTERPOLATION_STEPS) # Valor actual
                speed_slider.pack(side=tk.TOP, pady=(5, 0))
                
                speed_info = tk.Label(speed_frame, text="(1 = Muy Rápido, 6 = Normal, 25 = Lento)", 
                                      font=("Arial", 8), bg="#212121", fg="#888888")
                speed_info.pack(side=tk.TOP, pady=(0, 10))
                
                # --- NUEVO SLIDER: Espera para soltar click ---
                hold_label = tk.Label(speed_frame, text="Espera para soltar click (ms):", 
                                      font=("Arial", 9, "bold"), bg="#212121", fg="white")
                hold_label.pack(side=tk.TOP, padx=(20, 10))
                
                def on_hold_change(val):
                    global END_NODE_HOLD_TIME_MS
                    END_NODE_HOLD_TIME_MS = int(val)
                    save_manual_config()
                
                hold_slider = tk.Scale(speed_frame, from_=0, to=100, resolution=5, orient=tk.HORIZONTAL, 
                                        command=on_hold_change, bg="#212121", fg="#00FF00", 
                                        troughcolor="#333333", highlightthickness=0, length=300)
                hold_slider.set(END_NODE_HOLD_TIME_MS) # Valor actual
                hold_slider.pack(side=tk.TOP, pady=(5, 0))
                
                hold_info = tk.Label(speed_frame, text="(0 = Sin espera, 25 = Predeterminado, 100 = ⅒ segundo)", 
                                      font=("Arial", 8), bg="#212121", fg="#888888")
                hold_info.pack(side=tk.TOP)

                # --- DELAYS EN PASOS DE INTERPOLACIÓN ---
                step_delays_frame = tk.Frame(right_panel, bg="#2a2a2a", pady=10)
                step_delays_frame.pack(fill=tk.X, padx=10, pady=(5, 10))
                
                # Delay general en los pasos
                step_delay_label = tk.Label(step_delays_frame, text="Delay entre micropasos (General) (ms):", 
                                            font=("Arial", 9, "bold"), bg="#2a2a2a", fg="white")
                step_delay_label.pack(side=tk.TOP, padx=(20, 10))
                
                def on_step_delay_change(val):
                    global STEP_DELAY_MS
                    STEP_DELAY_MS = float(val)
                    save_manual_config()
                
                step_delay_slider = tk.Scale(step_delays_frame, from_=0, to=10, resolution=0.1, orient=tk.HORIZONTAL, 
                                             command=on_step_delay_change, bg="#2a2a2a", fg="#00FF00", 
                                             troughcolor="#333333", highlightthickness=0, length=300)
                step_delay_slider.set(STEP_DELAY_MS)
                step_delay_slider.pack(side=tk.TOP, pady=(2, 0))
                
                # Delay final en los pasos (Recta Final)
                final_step_delay_label = tk.Label(step_delays_frame, text="Delay micropasos (Recta final) (ms):", 
                                                  font=("Arial", 9, "bold"), bg="#2a2a2a", fg="white")
                final_step_delay_label.pack(side=tk.TOP, padx=(20, 10), pady=(10, 0))
                
                def on_final_step_delay_change(val):
                    global FINAL_STEP_DELAY_MS
                    FINAL_STEP_DELAY_MS = float(val)
                    save_manual_config()
                
                final_step_delay_slider = tk.Scale(step_delays_frame, from_=0, to=10, resolution=0.1, orient=tk.HORIZONTAL, 
                                                   command=on_final_step_delay_change, bg="#2a2a2a", fg="#00FF00", 
                                                   troughcolor="#333333", highlightthickness=0, length=300)
                final_step_delay_slider.set(FINAL_STEP_DELAY_MS)
                final_step_delay_slider.pack(side=tk.TOP, pady=(2, 0))
                
            except Exception as e:
                 print(f"⚠️ Error cargando imagen: {e}")
            
        else:
            tk.Label(root, text="Instrucciones no encontradas (VanityInst.png missing)", padx=20, pady=20).pack()

        # Centrar ventana
        root.update_idletasks()
        try:
            width = root.winfo_width()
            height = root.winfo_height()
            x = (root.winfo_screenwidth() // 2) - (width // 2)
            y = (root.winfo_screenheight() // 2) - (height // 2)
            root.geometry(f'{width}x{height}+{x}+{y}')
        except: pass

        def on_close():
            print("👋 Cerrando aplicación...")
            # listener.stop() # Local listener might not be scope accessible here easily depending on setup
            root.destroy()
            sys.exit()

        root.protocol("WM_DELETE_WINDOW", on_close)
        
        print("🖥️ Interfaz iniciada.")
        root.mainloop()
        
    except KeyboardInterrupt:
        print("\n👋 Cerrando solver...")
    except Exception as e:
        print(f"❌ Error lanzando GUI: {e}")

if __name__ == "__main__":
    main()
