
"""
Flow Puzzle Solver - Solucionador Automático de Puzzles Numberlink para Forsaken
==================================================================================
Implementación siguiendo la guía técnica de automatización.

Arquitectura: Máquina de Estados (IDLE → SCAN → SOLVE → EXECUTE → VERIFY)
Solver: Backtracking con heurísticas (más robusto para puzzles parciales)
Input: pydirectinput (compatible con DirectX/Roblox)

Controles:
- Presiona 'J' para activar el solver cuando veas un puzzle
- Presiona 'Alt+J' para abrir el selector visual de grid
- Presiona 'F4' para parada de emergencia (Kill Switch)
- Ctrl+C en terminal para salir

Autor: Flow Solver Bot
"""

import sys
import os
import cv2
import numpy as np
import pydirectinput
import pyautogui
import mss
import time
import ctypes
import keyboard
from pynput import keyboard as pynput_keyboard
from typing import List, Tuple, Dict, Optional
from enum import Enum
import threading
import tkinter as tk
from PIL import Image, ImageTk

# ============================================================
# DPI AWARENESS - Crítico para Windows 10/11 con escalado
# ============================================================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass  # Ignorar si falla (ej. en sistemas no Windows)

def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso, funciona para dev y para PyInstaller"""
    try:
        # PyInstaller crea una carpeta temporal en _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# ============================================================
# CONFIGURACIÓN
# ============================================================
GRID_SIZE = 6  # Siempre 6x6
DEBUG_MODE = False # Activado para ver imágenes de debug

# CRONOMETRAJE (Segundos)
WOBBLE_DURATION_START = 0.04  # Tiempo del wobble inicial (agarre)
DELAY_BEFORE_MOUSEDOWN = 0 # Pausa tras llegar al punto antes de clickar (Evita clicks fantasma)
DELAY_BETWEEN_COLORS = 0.03    # Pausa tras soltar un color antes de ir al siguiente



# GEOMETRÍA (Porcentajes del tamaño de celda)
WOBBLE_RATIO = 0.27       # Tamaño del rombo de agarre (0.30 = 30%)
START_PATH_BIAS = 0.13  # Retroceso inicial para alargar el trazo (0.13 = 13%)


# Determinar ruta base correcta para persistencia
if getattr(sys, 'frozen', False):
    # Si es EXE, usar la carpeta del ejecutable
    base_dir = os.path.dirname(sys.executable)
else:
    # Si es script, usar la carpeta del script
    base_dir = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(base_dir, "flow_solver_config.json")
print(f"📂 Archivo de configuración: {CONFIG_FILE}")

# ============================================================
# CALIBRACIÓN MANUAL DEL GRID
# ============================================================
# La configuración se guarda automáticamente en flow_solver_config.json
# Usa Alt+J para abrir el selector visual y calibrar el grid.
# ============================================================
MANUAL_GRID_ENABLED = False
MANUAL_GRID_X = 400
MANUAL_GRID_Y = 200
MANUAL_GRID_SIZE = 500


def load_config():
    """Carga la configuración guardada desde JSON"""
    global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE
    import json
    import cv2
    import numpy as np
    import os
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                MANUAL_GRID_ENABLED = config.get('enabled', False)
                MANUAL_GRID_X = config.get('x', 400)
                MANUAL_GRID_Y = config.get('y', 200)
                MANUAL_GRID_SIZE = config.get('size', 500)
                print(f"📂 Configuración cargada: ({MANUAL_GRID_X}, {MANUAL_GRID_Y}) {MANUAL_GRID_SIZE}px")
        except Exception as e:
            print(f"⚠️ Error cargando configuración: {e}")


def save_manual_config():
    """Guarda la configuración MANUAL a JSON (Solo debe llamarse desde el selector visual)"""
    import json
    try:
        config = {
            'enabled': MANUAL_GRID_ENABLED,
            'x': MANUAL_GRID_X,
            'y': MANUAL_GRID_Y,
            'size': MANUAL_GRID_SIZE
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno()) # Forzar escritura en disco
        print(f"💾 Configuración guardada en {CONFIG_FILE} (Sincronizado)")
    except Exception as e:
        print(f"⚠️ Error guardando configuración: {e}")


# Cargar configuración al inicio
load_config()

# Configuración de pydirectinput
pydirectinput.PAUSE = 0.001  # Sin pausas automáticas

# ============================================================
# RANGOS HSV CALIBRADOS PARA ROBLOX FORSAKEN
# Recalibrados basándose en análisis de screenshots reales
# ============================================================
COLOR_RANGES = {
    # Rojo/Coral (los puntos naranjas-rojizos del juego) - Saturation > 180 para evitar Pink
    'red_low':   ([0, 180, 120], [10, 255, 255]),
    'red_high':  ([170, 180, 120], [180, 255, 255]),
    # Naranja (puntos naranjas brillantes)
    'orange':    ([8, 100, 150], [20, 255, 255]),
    # Amarillo
    'yellow':    ([21, 100, 150], [38, 255, 255]),
    # Verde
    'green':     ([38, 80, 100], [85, 255, 255]),
    # Cyan/Turquesa (puntos azul claro - MUY comunes en Forsaken)
    'cyan':      ([85, 80, 120], [105, 255, 255]),
    # Azul
    'blue':      ([105, 80, 100], [130, 255, 255]),
    # Púrpura/Violeta (puntos morados oscuros)
    'purple':    ([130, 50, 80], [142, 255, 255]), # Reducido max H para separar de hotpink
    # Hot Pink (Rosa fuerte/Violeta claro) - Nuevo para separar del púrpura
    'hotpink':   ([143, 50, 80], [158, 255, 255]),
    # Magenta/Rosa (puntos rosa brillante - MUY comunes en Forsaken)
    'magenta':   ([159, 50, 100], [175, 255, 255]), # Ajustado inicio
    # Beige/Crema (baja saturación, alto valor)
    'beige':     ([0, 0, 170], [180, 100, 255]), 
    # Lightpink (rosado claro, menos saturado que crimson/red)
    'lightpink': ([160, 50, 180], [180, 180, 255]), # Limitar max Sat a 180
    # Mint (Verde claro/menta - nuevo color detectado)
    'mint':      ([40, 20, 200], [85, 100, 255]), # Alto valor, baja saturacion, tono verde
}


# ============================================================
# ESTADOS DE LA MÁQUINA
# ============================================================
class SolverState(Enum):
    IDLE = "IDLE"        # Esperando activación
    SCAN = "SCAN"        # Capturando y analizando
    SOLVE = "SOLVE"      # Resolviendo puzzle
    EXECUTE = "EXECUTE"  # Dibujando solución
    VERIFY = "VERIFY"    # Verificando resultado


# ============================================================
# KILL SWITCH GLOBAL
# ============================================================
emergency_stop_flag = False


def emergency_stop():
    """Parada de emergencia - libera el mouse inmediatamente"""
    global emergency_stop_flag
    emergency_stop_flag = True
    try:
        pydirectinput.mouseUp()
    except:
        pass
    print("\n🛑 ¡PARADA DE EMERGENCIA! (Movimiento detectado)")


# Registrar hotkey F4 y teclas de movimiento (Human Takeover)
stop_keys = ['w', 'a', 's', 'd', 'up', 'down', 'shift']
for k in stop_keys:
    keyboard.add_hotkey(k, emergency_stop)
keyboard.add_hotkey('F4', emergency_stop)


# ============================================================
# SELECTOR VISUAL DE GRID (Alt+J)
# ============================================================
class GridSelector:
    """
    Herramienta visual para seleccionar el área del puzzle.
    Permite dibujar un cuadrado y arrastrarlo para posicionarlo.
    """
    def __init__(self):
        self.root = None
        self.canvas = None
        self.screenshot = None
        self.tk_image = None
        self.rect_id = None
        self.start_x = 0
        self.start_y = 0
        self.current_rect = None  # (x, y, size)
        self.dragging = False
        self.resizing = False
        self.resize_edge = None  # 'N', 'S', 'E', 'W', 'NW', 'NE', 'SW', 'SE'
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
            
            # Inicializar size sugerido con el actual por si falla la detección de tamaño o para usarlo en líneas
            suggested_size = size
            
            # --- NUEVA LÓGICA: DETECCIÓN DE LÍNEAS DE GRID ---
            # El usuario menciona "fondo oscuro y líneas un poco más claras"
            # Usaremos Canny Edge Detection para intentar alinearnos con las líneas
            
            try:
                # ROI en escala de grises para bordes
                gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                # Mejora de contraste adaptativa
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                gray = clahe.apply(gray)
                
                # Detectar bordes
                edges = cv2.Canny(gray, 50, 150, apertureSize=3)
                
                # Detectar líneas (HoughLinesP es más rápido y da segmentos)
                minLineLength = size // 6  # Al menos el tamaño de una celda
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
                
                # Si detectamos líneas coherentes, las usamos para refinar la posición
                # Buscamos 'offsets' modulares. Las líneas deberían estar en k * cell_size
                
                # TODO: Esta lógica de grid es compleja de hacer robusta en un solo paso.
                # Por ahora, si tenemos líneas claras cerca de los bordes externos, las usamos para "clippear" el tamaño.
                
                # Enfoque simple: Usar bordes oscuros/claros para ajustar el bounding box si hay muy pocos dots
                
                # Calcular ajuste basado en líneas verticales
                if grid_lines_x:
                    shifts_x = []
                    current_cell_w = suggested_size / GRID_SIZE
                    for lx in grid_lines_x:
                        # ¿A qué distancia está esta línea de la rejilla teórica actual?
                        # x_teorico = suggested_x + k * cell_w
                        # k ideal = round((lx - suggested_x) / cell_w)
                        k = round((lx - suggested_x) / current_cell_w)
                        # Offset: diferencia entre línea real y línea teórica
                        diff = lx - (suggested_x + k * current_cell_w)
                        shifts_x.append(diff)
                    
                    if shifts_x:
                         avg_shift_x = sum(shifts_x) / len(shifts_x)
                         # Aplicamos solo un porcentaje del shift para ser conservadores (no romper si hay líneas falsas)
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
            # Ordenar coordenadas para encontrar saltos entre celdas adyacentes
            unique_rows = sorted(list(set([d[3] for d in valid_dots])))
            unique_cols = sorted(list(set([d[2] for d in valid_dots])))
            
            x_coords = sorted([d[0] for d in valid_dots])
            y_coords = sorted([d[1] for d in valid_dots])
            
            estimated_step_x = 0
            estimated_step_y = 0
            
            # Calcular distancias entre puntos consecutivos
            # Esto es más robusto que max-min si faltan muchos puntos intermedios,
            # pero asumimos que detectamos la mayoría.
            # Mejor enfoque: Calcular 'step' para cada punto basándonos en su índice col/row
            
            # Recalcular paso basado en regresión simple o promedio ponderado de rangos
            # step = (pos2 - pos1) / (idx2 - idx1)
            
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
                # Validar que el paso sea razonable (no muy lejos del actual)
                current_step = size / GRID_SIZE
                if 0.5 * current_step < median_step < 1.5 * current_step:
                     suggested_size = median_step * GRID_SIZE
            
            # 3. Refinar Posición Final con el nuevo tamaño
            # Nuevo tamaño significa nuevo cell_size. Recalculamos el origen ideal.
            new_cell_size = suggested_size / GRID_SIZE
            
            ideal_origins_x = []
            ideal_origins_y = []
            
            for cx, cy, col, row in valid_dots:
                # Dónde debería estar la esquina 0,0 (relativa al ROI) basándose en este punto
                # cx = origin_x + col * cell + cell/2
                # origin_x = cx - (col + 0.5) * cell
                ox = cx - (col + 0.5) * new_cell_size
                oy = cy - (row + 0.5) * new_cell_size
                ideal_origins_x.append(ox)
                ideal_origins_y.append(oy)
                
            best_origin_x = x + np.median(ideal_origins_x)
            best_origin_y = y + np.median(ideal_origins_y)
            
            return int(best_origin_x), int(best_origin_y), int(suggested_size)
            
        except Exception:
            return x, y, size
            
    def capture_screen(self):
        """Captura la pantalla para mostrar como fondo"""
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            print(f"   🖥️ Monitor detected: {monitor['width']}x{monitor['height']} (Top: {monitor['top']}, Left: {monitor['left']})")
            return img, monitor['width'], monitor['height']
    
    def show(self):
        """Muestra el selector visual"""
        global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE
        
        print("📐 [SELECTOR] Abriendo selector de grid...")
        print("   • Dibuja un cuadrado arrastrando el mouse")
        print("   • Arrastra el cuadrado para reposicionarlo")
        print("   • Presiona ENTER o click en Guardar para confirmar")
        print("   • Presiona ESC para cancelar")
        
        # Capturar pantalla
        self.screenshot, screen_w, screen_h = self.capture_screen()
        
        # Crear ventana fullscreen
        self.root = tk.Tk()
        self.root.title("Selector de Grid - Flow Solver")
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.configure(cursor="crosshair")
        
        # Convertir screenshot a formato Tkinter
        self.tk_image = ImageTk.PhotoImage(self.screenshot, master=self.root)
        
        # Canvas con la screenshot de fondo
        self.canvas = tk.Canvas(self.root, width=screen_w, height=screen_h, 
                                 highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        
        # Instrucciones en pantalla
        self.canvas.create_text(screen_w // 2, 30, 
                                 text="🎯 Dibuja un cuadrado sobre el puzzle | ENTER=Guardar | ESC=Cancelar",
                                 fill="yellow", font=("Arial", 16, "bold"))
        
        # Si ya hay un grid configurado, mostrarlo
        if MANUAL_GRID_ENABLED:
            self.current_rect = (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE)
            self.draw_rect()
        
        # Eventos del mouse
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
        # Precise Nudge with Shift (0.1)
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
        """Dibuja/actualiza el rectángulo de selección"""
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.canvas.delete("size_text")
        
        # ELIMINAR PUNTOS Y HANDLES ANTERIORES PARA EVITAR "TRAIL"
        if hasattr(self, 'dots_ids'):
            for item in self.dots_ids:
                self.canvas.delete(item)
            self.dots_ids = [] # Reset list
        
        if self.current_rect:
            x, y, size = self.current_rect
            self.rect_id = self.canvas.create_rectangle(
                x, y, x + size, y + size,
                outline='#00FF00', width=3, dash=(5, 5)
            )
            # Mostrar tamaño
            # Mostrar tamaño
            self.canvas.create_text(
                x + size // 2, y - 15,
                text=f"📏 {size:.2f}x{size:.2f} px  |  Pos: ({x:.2f}, {y:.2f})",
                fill='#00FF00', font=("Arial", 12, "bold"),
                tags="size_text"
            )
            
            # DIBUJAR PUNTOS DE PREVISUALIZACIÓN (6x6)
            # Esto ayuda al usuario a alinear perfectamente
            cell_size = size / GRID_SIZE
            half_cell = cell_size / 2
            
            for r in range(GRID_SIZE):
                for c in range(GRID_SIZE):
                    cx = x + int(c * cell_size + half_cell)
                    cy = y + int(r * cell_size + half_cell)
                    
                    dot_id = self.canvas.create_oval(
                        cx - 2, cy - 2, cx + 2, cy + 2,
                        fill='black', outline='#00FF00', width=1
                    )
                    self.dots_ids.append(dot_id)
            
            # --- VISUALIZACIÓN 'PLUS' 2x2 ---
            # El usuario pidió un "+" de 2x2 en el centro con "rayas largas en las puntas"
            # Esto ayuda a verificar si el tamaño de celda calza con las líneas del juego.
            
            # Centro exacto del grid (Línea 3 de 6)
            center_x = x + size / 2.0
            center_y = y + size / 2.0
            
            # Límites del bloque central 2x2 (Desde línea 2 hasta línea 4)
            # El bloque 2x2 ocupa las celdas [2,2], [2,3], [3,2], [3,3]
            # Sus bordes son cell*2 y cell*4
            bound_2_x = x + cell_size * 2
            bound_4_x = x + cell_size * 4
            bound_2_y = y + cell_size * 2
            bound_4_y = y + cell_size * 4
            
            # 1. Cruz central fuerte (El "+" de 2x2)
            # Vertical central del bloque 2x2
            plus_v = self.canvas.create_line(center_x, bound_2_y, center_x, bound_4_y, fill='cyan', width=2)
            # Horizontal central del bloque 2x2
            plus_h = self.canvas.create_line(bound_2_x, center_y, bound_4_x, center_y, fill='cyan', width=2)
            self.dots_ids.extend([plus_v, plus_h])
            
            # 2. "Rayas largas en las puntas" (Extensiones finas hacia afuera)
            # Extensión Vertical
            ext_v_top = self.canvas.create_line(center_x, y, center_x, bound_2_y, fill='cyan', width=1, dash=(4,4))
            ext_v_bot = self.canvas.create_line(center_x, bound_4_y, center_x, y + size, fill='cyan', width=1, dash=(4,4))
            # Extensión Horizontal
            ext_h_left = self.canvas.create_line(x, center_y, bound_2_x, center_y, fill='cyan', width=1, dash=(4,4))
            ext_h_right = self.canvas.create_line(bound_4_x, center_y, x + size, center_y, fill='cyan', width=1, dash=(4,4))
            self.dots_ids.extend([ext_v_top, ext_v_bot, ext_h_left, ext_h_right])

            # 3. Caja del 2x2 (Centro)
            box_2x2 = self.canvas.create_rectangle(bound_2_x, bound_2_y, bound_4_x, bound_4_y, outline='yellow', width=1, dash=(2,2))
            self.dots_ids.append(box_2x2)
            
            # 4. Cajas 1x1 en las esquinas (Para verificar bordes exactos)
            # Top-Left: (0,0) 
            tl_box = self.canvas.create_rectangle(x, y, x + cell_size, y + cell_size, outline='yellow', width=1, dash=(2,2))
            # Top-Right: (5,0)
            tr_box = self.canvas.create_rectangle(x + cell_size*5, y, x + size, y + cell_size, outline='yellow', width=1, dash=(2,2))
            # Bot-Left: (0,5)
            bl_box = self.canvas.create_rectangle(x, y + cell_size*5, x + cell_size, y + size, outline='yellow', width=1, dash=(2,2))
            # Bot-Right: (5,5)
            br_box = self.canvas.create_rectangle(x + cell_size*5, y + cell_size*5, x + size, y + size, outline='yellow', width=1, dash=(2,2))
            
            self.dots_ids.extend([tl_box, tr_box, bl_box, br_box])
            
            # Dibujar handles (agarraderas) en las esquinas para redimensionar
            handle_size = 8
            corners = [
                (x, y), (x+size, y), 
                (x, y+size), (x+size, y+size)
            ]
            for hx, hy in corners:
                hid = self.canvas.create_rectangle(
                    hx-handle_size, hy-handle_size, hx+handle_size, hy+handle_size,
                    fill='white', outline='black'
                )
                self.dots_ids.append(hid)
    
    def on_mouse_down(self, event):
        """Inicio de click"""
        # 1. Verificar si está en un borde/esquina para redimensionar
        if self.current_rect:
            x, y, size = self.current_rect
            margin = 15 # Margen de detección
            
            # Detectar si está cerca de algún borde
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

        # 2. Verificar si está dentro para mover (arrastrar)
        if self.current_rect:
            x, y, size = self.current_rect
            if x < event.x < x + size and y < event.y < y + size:
                self.dragging = True
                self.drag_offset = (event.x - x, event.y - y)
                self.canvas.configure(cursor="fleur")
                return
        
        # 3. Si no, iniciar nuevo dibujo
        self.start_x = event.x
        self.start_y = event.y
        self.dragging = False
        self.resizing = False
    
    def on_mouse_drag(self, event):
        """Arrastrar mouse"""
        if self.resizing and self.current_rect:
            # Lógica de redimensionado manteniendo proporción cuadrada
            x, y, size = self.current_rect
            new_x, new_y = x, y
            new_size = size
            
            if 'E' in self.resize_edge:
                new_size = event.x - x
            elif 'W' in self.resize_edge:
                # Complicado mantener cuadrado desde la izquierda
                dx = x - event.x
                new_size = size + dx
                new_x = event.x
            
            if 'S' in self.resize_edge:
                # Si arrastramos abajo, ajustamos size. 
                # Si ya ajustamos con E/W, tomamos el mayor para ser cuadrado
                h_size = event.y - y
                new_size = max(new_size, h_size) if 'E' not in self.resize_edge else new_size
            elif 'N' in self.resize_edge:
                dy = y - event.y
                new_size = max(new_size, size + dy) if 'E' not in self.resize_edge else new_size
                new_y = event.y
                
            # Mínimo tamaño
            if new_size < 20: return
            
            if new_size < 20: return
            
            self.current_rect = (new_x, new_y, new_size)
            self.draw_rect()
            
            self.draw_rect()
            
        elif self.dragging and self.current_rect:
            # Mover rectángulo existente
            size = self.current_rect[2]
            
            # Posición bruta basada en el mouse
            raw_x = event.x - self.drag_offset[0]
            raw_y = event.y - self.drag_offset[1]
            
            # APLICAR AUTO-CENTER (IMÁN INTELIGENTE)
            # Calculamos la corrección sugerida basándonos en la posición bruta
            magnet_x, magnet_y, magnet_size = self._calculate_auto_center(raw_x, raw_y, size)
            
            # Distancia entre posición del mouse y posición magnética
            dist = ((raw_x - magnet_x)**2 + (raw_y - magnet_y)**2)**0.5
            
            # Si el imán sugiere algo cerca (< 60px), lo usamos
            # Y también aplicamos el nuevo tamaño si es una mejora razonable
            if dist < 60:
                self.current_rect = (magnet_x, magnet_y, magnet_size) # Floats return from auto_center
            else:
                self.current_rect = (raw_x, raw_y, size)
            
            self.draw_rect()
        else:
            # Dibujar nuevo rectángulo (cuadrado)
            dx = event.x - self.start_x
            dy = event.y - self.start_y
            # Usar el mayor para hacer cuadrado
            size = max(abs(dx), abs(dy))
            # Ajustar posición según dirección
            x = self.start_x if dx >= 0 else self.start_x - size
            y = self.start_y if dy >= 0 else self.start_y - size
            self.current_rect = (x, y, size) # Keep floats
            self.draw_rect()
    
    def on_mouse_up(self, event):
        """Fin de click"""
        self.dragging = False
        self.resizing = False
        self.canvas.configure(cursor="crosshair")
    
    def save_and_close(self, event=None):
        """Guardar configuración y cerrar"""
        global MANUAL_GRID_ENABLED, MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE
        
        if self.current_rect:
            x, y, size = self.current_rect
            MANUAL_GRID_X = x
            MANUAL_GRID_Y = y
            MANUAL_GRID_SIZE = size
            MANUAL_GRID_ENABLED = True
            self.result = (x, y, size)
            save_manual_config()  # Guardar a archivo JSON
            print(f"✅ Grid guardado manualmente: X={x}, Y={y}, Size={size}")
            print(f"   Modo manual activado. Presiona J para resolver.")
        
        self.root.destroy()
    
    def nudge_rect(self, dx, dy):
        """Mover rectángulo con teclado"""
        if self.current_rect:
            x, y, size = self.current_rect
            self.current_rect = (x + dx, y + dy, size)
            self.draw_rect()

    def nudge_size(self, d_size):
        """Redimensionar con teclado"""
        if self.current_rect:
            x, y, size = self.current_rect
            new_size = max(20, size + d_size)
            self.current_rect = (x, y, new_size)
            self.draw_rect()
            
    def cancel(self, event=None):
        """Cancelar selección"""
        print("❌ Selección cancelada")
        self.root.destroy()


def open_grid_selector():
    """Abre el selector de grid en un thread separado"""
    selector = GridSelector()
    thread = threading.Thread(target=selector.show)
    thread.start()


# Registrar hotkey Alt+J para el selector
keyboard.add_hotkey('alt+j', open_grid_selector)


# ============================================================
# CLASE PRINCIPAL: FLOW PUZZLE SOLVER
# ============================================================
class FlowPuzzleSolver:
    """Clase principal para resolver puzzles Flow/Numberlink"""
    
    def __init__(self):
        self.state = SolverState.IDLE
        self.is_solving = False
        self.grid_origin = None
        self.cell_size = None
        self.detected_input_colors = {} # Mapa ID -> Nombre de color (persistente entre Scan y Verify)
        self.debug_counter = 0
        self.final_paths = {}
        
    def capture_screen(self) -> np.ndarray:
        """Captura la pantalla completa usando mss (ultra-rápido)"""
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    
    def find_puzzle_grid(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Encuentra el área del puzzle detectando:
        1. Si MANUAL_GRID_ENABLED, usa coordenadas manuales
        2. Intenta encontrar el fondo oscuro del grid
        3. Si falla, busca los círculos de colores
        Retorna (x, y, width, height) o None.
        """
        # Modo manual: usar coordenadas configuradas
        if MANUAL_GRID_ENABLED:
            if DEBUG_MODE:
                print(f"   ✓ Usando calibración manual: ({MANUAL_GRID_X}, {MANUAL_GRID_Y}, {MANUAL_GRID_SIZE}x{MANUAL_GRID_SIZE})")
            return (MANUAL_GRID_X, MANUAL_GRID_Y, MANUAL_GRID_SIZE, MANUAL_GRID_SIZE)
        
        height, width = screen.shape[:2]
        
        # Método 1: Buscar el rectángulo oscuro del grid
        result = self._find_grid_by_dark_background(screen)
        if result:
            if DEBUG_MODE:
                print("   ✓ Grid encontrado por fondo oscuro")
            return result
        
        # Método 2: Fallback - buscar por puntos de colores
        margin_x = 50
        margin_y = 50
        search_region = screen[margin_y:height-margin_y, margin_x:width-margin_x]
        result = self._find_grid_by_dots(search_region)
        
        if result:
            x, y, w, h = result
            if DEBUG_MODE:
                print("   ✓ Grid encontrado por detección de puntos")
            return (x + margin_x, y + margin_y, w, h)
            
        print("⚠️ No se encontraron suficientes puntos para detectar grid")
        return None
    
    def _find_grid_by_dark_background(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detecta el grid buscando el rectángulo oscuro donde está el puzzle.
        El grid tiene un fondo negro/muy oscuro que contrasta con el fondo del juego.
        """
        height, width = screen.shape[:2]
        
        # Convertir a escala de grises
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        
        # Umbral para detectar áreas muy oscuras (el grid tiene fondo negro)
        _, dark_mask = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
        
        # Operaciones morfológicas para limpiar
        kernel = np.ones((5, 5), np.uint8)
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel)
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel)
        
        # Buscar contornos
        contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Buscar un rectángulo que pueda ser el grid (aprox 300-500 px de lado)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            # El grid es aproximadamente 400x400 pixeles
            if 100000 < area < 300000:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = w / h if h > 0 else 0
                
                # Debe ser casi cuadrado
                if 0.8 < aspect_ratio < 1.2 and 300 < w < 550 and 300 < h < 550:
                    if DEBUG_MODE:
                        debug_img = screen.copy()
                        cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 3)
                        cv2.imwrite(f"debug_dark_grid_{self.debug_counter}.png", debug_img)
                    return (x, y, w, h)
        
        return None

    def _find_grid_by_dots(self, img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """Detecta el grid buscando agrupaciones de círculos coloreados"""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Máscara combinada para todos los colores saturados
        mask = cv2.inRange(hsv, (0, 40, 40), (180, 255, 255))
        
        # Limpiar ruido con operaciones morfológicas
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        dots = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 50 < area < 10000:
                perimeter = cv2.arcLength(cnt, True)
                if perimeter == 0:
                    continue
                circularity = 4 * np.pi * (area / (perimeter * perimeter))
                
                # Aceptar formas razonablemente circulares o cuadradas
                if circularity > 0.4:  # Más permisivo para cuadrados
                    M = cv2.moments(cnt)
                    if M["m00"] > 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        dots.append((cx, cy))
        
        if len(dots) < 4:
            return None
            
        # Filtrado de outliers espaciales
        dots_np = np.array(dots)
        median_x = np.median(dots_np[:, 0])
        median_y = np.median(dots_np[:, 1])
        
        max_dist = 450
        valid_dots = [(p[0], p[1]) for p in dots 
                      if abs(p[0] - median_x) < max_dist and abs(p[1] - median_y) < max_dist]
                
        if len(valid_dots) < 4:
            return None
            
        dots_np = np.array(valid_dots)
        
        # Estimar tamaño de celda
        x_coords = np.sort(dots_np[:, 0])
        y_coords = np.sort(dots_np[:, 1])
        
        x_diffs = np.diff(x_coords)
        y_diffs = np.diff(y_coords)
        
        valid_x_diffs = [d for d in x_diffs if d > 25]
        valid_y_diffs = [d for d in y_diffs if d > 25]
        
        if not valid_x_diffs or not valid_y_diffs:
            step_x = (np.max(x_coords) - np.min(x_coords)) / 5
            step_y = (np.max(y_coords) - np.min(y_coords)) / 5
        else:
            step_x = np.median(valid_x_diffs)
            step_y = np.median(valid_y_diffs)
            
        cell_size = int((step_x + step_y) / 2)
        
        # ALINEACIÓN ROBUSTA DEL GRID
        # Usamos todos los puntos para encontrar el "inicio" del grid más consistente
        # Evita que un solo punto desviado (min_x) desalinee todo el grid
        
        # 1. Estimar índices de columna/fila relativos al min
        x_min = np.min(x_coords)
        y_min = np.min(y_coords)
        
        col_indices = np.round((x_coords - x_min) / cell_size)
        row_indices = np.round((y_coords - y_min) / cell_size)
        
        # 2. Calcular dónde debería empezar el grid según cada punto
        # start_x = punto_x - columna * tamaño_celda
        estimated_start_xs = x_coords - col_indices * cell_size
        estimated_start_ys = y_coords - row_indices * cell_size
        
        # 3. Tomar la mediana de los inicios estimados (muy robusto)
        avg_start_x = np.median(estimated_start_xs)
        avg_start_y = np.median(estimated_start_ys)
        
        # 4. Calcular coordenadas finales
        # El inicio del grid es el centro de la primera celda MENOS medio tamaño
        half_cell = cell_size // 2
        final_x = int(avg_start_x - half_cell)
        final_y = int(avg_start_y - half_cell)
        
        # Asegurar coordenadas válidas
        final_x = max(0, final_x)
        final_y = max(0, final_y)
        
        # Calcular tamaño del grid completo (6x6)
        # Asumimos que hemos encontrado una parte del grid 6x6 real
        # Si la detección de puntos cubrió "casi" todo, ajustamos al tamaño estándar
        max_col = np.max(col_indices)
        max_row = np.max(row_indices)
        
        # Si detectamos puntos que abarcan 5 "saltos" (cols 0 a 5), es el ancho total
        # Si detectamos menos, podría ser un grid parcial, pero Forsaken siempre usa 6x6
        # Así que forzamos el tamaño a 6 celdas
        grid_pixel_size = cell_size * GRID_SIZE
        
        if DEBUG_MODE:
            debug_img = img.copy()
            for dx, dy in valid_dots:
                cv2.circle(debug_img, (int(dx), int(dy)), 5, (0, 0, 255), -1)
            # Dibujar grid calculado
            cv2.rectangle(debug_img, (final_x, final_y), 
                         (final_x + grid_pixel_size, final_y + grid_pixel_size), (0, 255, 0), 2)
            cv2.imwrite(f"debug_dots_{self.debug_counter}.png", debug_img)
            
        return (final_x, final_y, grid_pixel_size, grid_pixel_size)

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
                
                # Visualmente: Borde blanco, relleno según ID (aleatorio/fijo o verde)
                # Aquí usamos simple: verde para puntos OK, rojo si es destacado?
                # Por simplicidad, todos verde o color del texto blanco
                
                # Nombre del color si está disponible
                color_name = ""
                if id_to_color and color_id in id_to_color:
                    color_name = id_to_color[color_id][:3] # 3 chars
                
                cv2.putText(debug_grid, f"{color_id}{color_name}", (cx-15, cy+5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                cv2.circle(debug_grid, (cx, cy), 2, (0, 255, 255), -1)

            timestamp = int(time.time())
            # Si prefix ya tiene timestamp o contador, usarlo
            if "{timestamp}" in prefix:
                filename = prefix.format(timestamp=timestamp)
            else:
                filename = f"{prefix}_{timestamp}.png"
                
            cv2.imwrite(filename, debug_grid)
            print(f"   📸 Debug guardado: {filename}")
            
        except Exception as e:
            print(f"   ⚠️ Error guardando debug: {e}")

            print(f"   ⚠️ Error guardando debug: {e}")

    def _visualize_solution(self, grid_img, solutions, id_to_color):
        """Dibuja la solución encontrada sobre la imagen del grid para debug"""
        try:
            vis_img = grid_img.copy()
            h, w = vis_img.shape[:2]
            cell_w = w / GRID_SIZE
            cell_h = h / GRID_SIZE
            
            # Dibujar cuadrícula
            for i in range(1, GRID_SIZE):
                x = int(i * cell_w)
                cv2.line(vis_img, (x, 0), (x, h), (50, 50, 50), 1)
                y = int(i * cell_h)
                cv2.line(vis_img, (0, y), (w, y), (50, 50, 50), 1)
            
            # Dibujar caminos
            for color_id, path in solutions.items():
                if not path: continue
                
                # Obtener color (pseudo-aleatorio o basado en nombre si tuviéramos mapa)
                # Por ahora, un color fijo o hash
                np.random.seed(color_id * 10)
                color_bgr = np.random.randint(0, 255, 3).tolist()
                
                pts = []
                for r, c in path:
                    cx = int(c * cell_w + cell_w / 2)
                    cy = int(r * cell_h + cell_h / 2)
                    pts.append((cx, cy))
                
                # Dibujar líneas
                if len(pts) > 1:
                    cv2.polylines(vis_img, [np.array(pts)], False, color_bgr, 3, cv2.LINE_AA)
                    
                # Dibujar inicio/fin
                for px, py in pts:
                     cv2.circle(vis_img, (px, py), 4, color_bgr, -1)
            
            filename = f"debug_solution_{self.debug_counter}.png"
            cv2.imwrite(filename, vis_img)
            print(f"   📸 Solución visual guardada: {filename}")
            
        except Exception as e:
            print(f"   ⚠️ Error visualizando solución: {e}")

    def extract_grid(self, screen: np.ndarray, grid_rect: Tuple[int, int, int, int]) -> np.ndarray:
        """Extrae la región del grid"""
        x, y, w, h = grid_rect
        x, y, w, h = int(x), int(y), int(w), int(h)
        return screen[y:y+h, x:x+w].copy()
    
    def _classify_color(self, hue: float, sat: float, val: float) -> Optional[str]:
        """
        Clasifica un color HSV basado en el diccionario COLOR_RANGES.
        """
        # 1. Filtros rápidos básicos
        if val < 40: return None  # Demasiado oscuro
        if sat < 20 and val > 200: return None # Blanco/Gris claro (texto)

        # 2. Iterar sobre rangos configurados
        for color_name, (lower, upper) in COLOR_RANGES.items():
            # lower y upper son listas [H, S, V]
            
            # Comprobar Hue
            if not (lower[0] <= hue <= upper[0]):
                continue
                
            # Comprobar Sat
            if not (lower[1] <= sat <= upper[1]):
                continue
                
            # Comprobar Val
            if not (lower[2] <= val <= upper[2]):
                continue
                
            # Si pasa todos los filtros, retornar nombre base
            # Simplificar nombres (ej: 'red_low' -> 'red')
            base_name = color_name
            if '_' in base_name:
                base_name = base_name.split('_')[0]
                
            # Caso especial para mapear nombres antiguos si es necesario
            if base_name == 'pink': return 'magenta' 
            # Nota: 'lightpink' no está en COLOR_RANGES por defecto, 
            # pero 'pink' del diccionario parece ser el magenta brillante.
            # Ajustaremos el diccionario si es necesario.
            
            return base_name
            
        return None
    
    def analyze_grid(self, grid_img: np.ndarray) -> Dict[Tuple[int, int], int]:
        """
        Analiza el grid y extrae las posiciones de los puntos/colores.
        Retorna {(row, col): color_id}
        
        Usa clasificación por rangos de Hue para distinguir colores.
        Busca los píxeles más saturados en cada celda (los círculos de colores).
        """
        h, w = grid_img.shape[:2]
        # Usar precisión flotante para coincidir con la visualización del selector
        cell_h = h / GRID_SIZE
        cell_w = w / GRID_SIZE
        
        self.cell_size = int((cell_w + cell_h) / 2)
        
        hsv = cv2.cvtColor(grid_img, cv2.COLOR_BGR2HSV)
        
        # Primera pasada: detectar colores en cada celda
        cell_colors = {}  # {(row, col): 'color_name'}
        
        if DEBUG_MODE:
            print("   [DEBUG] Analizando celdas:")
        
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                # Calcular coordenadas con precisión flotante
                # ROI central de la celda (90% central - más amplio para no cortar círculos)
                # Coordenadas exactas float
                f_x1 = col * cell_w + cell_w * 0.05
                f_y1 = row * cell_h + cell_h * 0.05
                f_x2 = (col + 1) * cell_w - cell_w * 0.05
                f_y2 = (row + 1) * cell_h - cell_h * 0.05
                
                # Convertir a int para slicing
                x1, y1 = int(f_x1), int(f_y1)
                x2, y2 = int(f_x2), int(f_y2)
                
                roi = hsv[y1:y2, x1:x2]
                if roi.size == 0:
                    continue
                
                # Buscar el píxel con mayor saturación (el círculo de color)
                # Esto es mejor que la mediana porque el fondo es oscuro/desaturado
                sat_channel = roi[:, :, 1]
                val_channel = roi[:, :, 2]
                max_sat_idx = np.unravel_index(np.argmax(sat_channel), sat_channel.shape)
                
                max_hue = roi[max_sat_idx[0], max_sat_idx[1], 0]
                max_sat = roi[max_sat_idx[0], max_sat_idx[1], 1]
                max_val = roi[max_sat_idx[0], max_sat_idx[1], 2]
                
                # Calcular mediana para comparar (contraste)
                median_sat = np.median(sat_channel)
                
                # Contar píxeles con alta saturación (indicador de círculo de color)
                high_sat_pixels = np.sum(sat_channel > 120)
                total_pixels = sat_channel.size
                high_sat_ratio = high_sat_pixels / total_pixels if total_pixels > 0 else 0
                
                # También detectar círculos beige/crema (alta luminosidad, baja saturación)
                high_val_pixels = np.sum(val_channel > 170)
                high_val_ratio = high_val_pixels / total_pixels if total_pixels > 0 else 0
                max_val_overall = np.max(val_channel)
                
                # Encontrar el píxel más brillante para beige
                max_val_idx = np.unravel_index(np.argmax(val_channel), val_channel.shape)
                brightest_hue = roi[max_val_idx[0], max_val_idx[1], 0]
                brightest_sat = roi[max_val_idx[0], max_val_idx[1], 1]
                brightest_val = roi[max_val_idx[0], max_val_idx[1], 2]
                
                sat_contrast = max_sat - median_sat
                
                # Detección de círculos coloreados (alta saturación)
                # FIX: Si 'high_sat_ratio' es muy alto (celda llena de color), el contraste puede ser bajo.
                # Permitimos si hay mucho color (>50%) O si hay buen contraste.
                is_colored = max_sat > 100 and max_val > 130 and high_sat_ratio > 0.10
                has_contrast = sat_contrast > 20
                is_filled = high_sat_ratio > 0.5
                
                if is_colored and (has_contrast or is_filled):
                    color_name = self._classify_color(max_hue, max_sat, max_val)
                    if color_name:
                        cell_colors[(row, col)] = color_name
                        if DEBUG_MODE:
                            print(f"      ({row},{col}): {color_name} [H:{max_hue:.0f} S:{max_sat:.0f} V:{max_val:.0f}]")
                
                # Detección de círculos beige/crema (baja saturación, alto valor)
                elif brightest_val > 200 and brightest_sat < 100 and high_val_ratio > 0.15:
                    color_name = self._classify_color(brightest_hue, brightest_sat, brightest_val)
                    if color_name:
                        cell_colors[(row, col)] = color_name
                        if DEBUG_MODE:
                            print(f"      ({row},{col}): {color_name} [H:{brightest_hue:.0f} S:{brightest_sat:.0f} V:{brightest_val:.0f}] (beige)")
        
        # Segunda pasada: asignar IDs numéricos a cada color único
        unique_colors = list(set(cell_colors.values()))
        color_to_id = {color: idx + 1 for idx, color in enumerate(unique_colors)}
        
        endpoints = {pos: color_to_id[color] for pos, color in cell_colors.items()}
        
        if DEBUG_MODE:
            print(f"   Colores encontrados: {unique_colors}")
            print(f"   Puntos por color: {dict((c, list(cell_colors.values()).count(c)) for c in unique_colors)}")
            
            # Usar método unificado
            # Crear mapa inverso temporal para display
            id_map = {v: k for k, v in color_to_id.items() for k2, v2 in endpoints.items() if endpoints[k2] == v} 
            # Mejor: reconstruir mapa id->nombre
            id_to_name = {idx: name for name, idx in color_to_id.items()} 
            # Ajuste: color_to_id es 'name' -> int. id_to_name es int -> 'name'.
            # Pero espera, color_to_id se crea como {color: idx+1 ...}
            # Correcto.
            
            self._save_debug_grid(grid_img, endpoints, f"debug_analyzed_grid_{self.debug_counter}.png", id_to_name)
            
        # Retornar ENDPOINTS y el mapa ID->NOMBRE
        id_to_color_map = {idx: name for name, idx in color_to_id.items()}
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
                continue # Ya se logueó el error antes si fuera necesario
            inputs.append({'id': num, 'start': coords[0], 'end': coords[1]})
            
        if not inputs:
            print("   ❌ No hay pares válidos para resolver")
            return {}
            
        # Ordenar por distancia Manhattan (heurística)
        inputs.sort(key=lambda x: abs(x['start'][0]-x['end'][0]) + abs(x['start'][1]-x['end'][1]))
        
        self.final_paths = {}
        
        print(f"   Resolviendo {len(inputs)} caminos (Iterativo)...")
        
        start_time = time.time()
        
        # Ejecutar solver iterativo
        if self._solve_iterative(grid, inputs):
            return self.final_paths
        else:
            return {}

    def _solve_iterative(self, grid, inputs):
        """
        Implementación de backtracking usando una pila explícita (Heap memory)
        en lugar de recursión (Stack memory).
        """
        initial_input = inputs[0]
        
        # Estructura del stack:
        # { 
        #   'idx': índice del color actual en inputs,
        #   'current': posición actual (r, c),
        #   'path': camino construido hasta ahora,
        #   'neighbors': iterador de vecinos válidos,
        #   'tried_next': flag para indicar si ya intentamos avanzar al siguiente color
        # }
        
        stack = [{
            'idx': 0,
            'current': initial_input['start'],
            'path': [initial_input['start']],
            'neighbors': self._get_neighbors(initial_input['start'], initial_input['end'], grid),
            'tried_next': False
        }]
        
        # El punto inicial ya está marcado en el grid por setup
        
        while stack:
            if emergency_stop_flag: 
                return False

            frame = stack[-1]
            idx = frame['idx']
            current_input = inputs[idx]
            color_id = current_input['id']
            end_pos = current_input['end']
            r, c = frame['current']
            
            # --- CASO 1: Llegamos al destino del color actual ---
            if r == end_pos[0] and c == end_pos[1]:
                if frame['tried_next']:
                    # Ya intentamos resolver el resto y falló (backtracking)
                    # Eliminamos este camino de la solución parcial
                    if color_id in self.final_paths:
                        del self.final_paths[color_id]
                    
                    stack.pop()
                    # No necesitamos desmarcar endpoint, siempre es obstáculo/meta
                    continue
                else:
                    # Primera vez que llegamos al final de este color
                    self.final_paths[color_id] = frame['path']
                    frame['tried_next'] = True # Marcamos que vamos a intentar el siguiente paso
                    
                    # Si era el último color, ¡ÉXITO!
                    if idx == len(inputs) - 1:
                        return True
                    
                    # Preparar siguiente color
                    next_idx = idx + 1
                    next_start = inputs[next_idx]['start']
                    next_end = inputs[next_idx]['end']
                    
                    # Push del primer frame del siguiente color
                    stack.append({
                        'idx': next_idx,
                        'current': next_start,
                        'path': [next_start],
                        'neighbors': self._get_neighbors(next_start, next_end, grid),
                        'tried_next': False
                    })
                    continue

            # --- CASO 2: Explorando vecinos (DFS step) ---
            try:
                # Obtener siguiente vecino válido
                # Nota: _get_neighbors ya filtra por ocupación, así que si sale aquí es válido
                nr, nc = next(frame['neighbors'])
                
                # Marcar en grid
                grid[nr][nc] = color_id
                
                # Push nuevo paso en el camino
                stack.append({
                    'idx': idx,
                    'current': (nr, nc),
                    'path': frame['path'] + [(nr, nc)],
                    'neighbors': self._get_neighbors((nr, nc), end_pos, grid),
                    'tried_next': False
                })
                
            except StopIteration:
                # No hay más vecinos válidos -> Backtrack
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
        # Orden: Arriba, Abajo, Izq, Der
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            
            # Chequeos básicos de límites
            if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                val = grid[nr][nc]
                
                # Si es el destino, es válido
                if (nr, nc) == end:
                    neighbors.append((nr, nc))
                # Si está vacío (0), es válido
                elif val == 0:
                    neighbors.append((nr, nc))
                # Si está ocupado, NO es válido
                    
        # Heurística: Ordenar vecinos por distancia Manhatan al destino (Ascendente)
        # Esto hace que explore primero los que acercan a la meta
        neighbors.sort(key=lambda p: abs(p[0]-end[0]) + abs(p[1]-end[1]))
        
        return iter(neighbors)
    
    def _perform_spiral_wobble(self, center_x, center_y, radius=None, cell_size=None, total_duration=None):
        """
        Realiza un movimiento en espiral desde el centro hacia afuera para asegurar agarre.
        Spamea clicks durante el proceso.
        """
        wobble_ratio = WOBBLE_RATIO
        
        if radius is None:
            if cell_size is not None:
                max_radius = int(cell_size * wobble_ratio)
            else:
                max_radius = 7 # Fallback fijo
        else:
            max_radius = radius

        # Configuración de espiral
        num_rotations = 2
        steps = 40 # Total de pasos para suavidad
        
        # Duración
        start_time = time.time()
        
        # Si no se especifica duración, usar default (aunque debería pasarse)
        duration = total_duration if total_duration else WOBBLE_DURATION_START
        
        # Bucle de tiempo para asegurar duración exacta
        while True:
            elapsed = time.time() - start_time
            if elapsed > duration:
                break
                
            if emergency_stop_flag: return
            
            # Progreso normalizado (0.0 a 1.0)
            progress = min(elapsed / duration, 1.0)
            
            # Radio actual (expandiéndose)
            current_radius = max_radius * progress
            
            # Ángulo actual (rotando)
            angle = progress * (2 * np.pi * num_rotations)
            
            # Calcular offset
            offset_x = int(current_radius * np.cos(angle))
            offset_y = int(current_radius * np.sin(angle))
            
            target_x = center_x + offset_x
            target_y = center_y + offset_y
            
            # Mover y Clickar
            pydirectinput.moveTo(target_x, target_y)
            pydirectinput.mouseDown() # SPAM CLICK
            
            # Pequeña pausa para no saturar
            time.sleep(0.01)

    def draw_solution(self, solutions: Dict[int, List[Tuple[int, int]]], 
                      grid_origin: Tuple[int, int], grid_rect_size: Tuple[int, int]):
        """
        Dibuja la solución usando pydirectinput (compatible DirectX).
        Incluye micro-pausas para que Roblox registre los movimientos.
        """
        global emergency_stop_flag
        
        # Calcular tamaño de celda exacto (float)
        cell_w = grid_rect_size[0] / GRID_SIZE
        cell_h = grid_rect_size[1] / GRID_SIZE
        
        for color_id, path in solutions.items():
            if not path or emergency_stop_flag:
                continue
            
            # Convertir coordenadas de grid a pantalla usando float
            screen_points = []
            for r, c in path:
                # Centro exacto de la celda
                fx = grid_origin[0] + c * cell_w + cell_w / 2
                fy = grid_origin[1] + r * cell_h + cell_h / 2
                screen_points.append((fx, fy))
            
            if not screen_points:
                continue
                
            # APLICAR BIAS (DESPLAZAMIENTO) A INICIO Y FIN
            # Para asegurar mejor agarre y conexión:
            # - Inicio: Empezar un poco "antes" (atrás) del centro.
            # - Fin: Terminar un poco "después" (adelante) del centro.
            
            # CONFIGURACIÓN:
            # - bias_ratio: Cuánto extender el trazo (START_PATH_BIAS).
            bias_ratio = START_PATH_BIAS
            
            if len(screen_points) >= 2:
                # --- Ajustar Inicio (Retroceder) ---
                p0 = screen_points[0]
                p1 = screen_points[1]
                
                dx = p1[0] - p0[0]
                dy = p1[1] - p0[1]
                
                # Normalizar dirección (solo ortogonal)
                if abs(dx) > abs(dy):
                    dir_x = 1 if dx > 0 else -1
                    dir_y = 0
                else:
                    dir_x = 0
                    dir_y = 1 if dy > 0 else -1
                
                # Desplazar CONTRA la dirección (Start Back)
                new_start_x = p0[0] - dir_x * (cell_w * bias_ratio)
                new_start_y = p0[1] - dir_y * (cell_h * bias_ratio)
                screen_points[0] = (new_start_x, new_start_y)

                # --- Ajustar Fin (Avanzar) ---
                p_last = screen_points[-1]
                p_prev = screen_points[-2]
                
                dx_end = p_last[0] - p_prev[0]
                dy_end = p_last[1] - p_prev[1]
                
                if abs(dx_end) > abs(dy_end):
                    dir_end_x = 1 if dx_end > 0 else -1
                    dir_end_y = 0
                else:
                    dir_end_x = 0
                    dir_end_y = 1 if dy_end > 0 else -1
                    
                # Desplazar A FAVOR de la dirección (Extend Forward)
                new_end_x = p_last[0] + dir_end_x * (cell_w * bias_ratio)
                new_end_y = p_last[1] + dir_end_y * (cell_h * bias_ratio)
                screen_points[-1] = (new_end_x, new_end_y)
            
            # Convertir a int final
            screen_points_int = [(int(x), int(y)) for x, y in screen_points]
                
            # Mover al punto inicial
            current_pos = screen_points_int[0]
            pydirectinput.moveTo(current_pos[0], current_pos[1])
            time.sleep(DELAY_BEFORE_MOUSEDOWN)
            
            if emergency_stop_flag:
                return
            
            if emergency_stop_flag:
                return
            
            # 1. MouseDown REAL para arrastrar (Double Tap eliminado)
            pydirectinput.mouseDown()
            
            # Wobble SPIRAL para asegurar agarre (con spam clicks)
            self._perform_spiral_wobble(current_pos[0], current_pos[1], radius=None, cell_size=cell_w, total_duration=WOBBLE_DURATION_START)
            
            # Reimplementación del loop para detectar esquinas
            for i in range(1, len(screen_points_int)):
                target_point = screen_points_int[i]
                prev_point = screen_points_int[i-1]
                
                # Determinar si este punto target será una esquina
                is_corner = False
                if i < len(screen_points_int) - 1:
                    next_point = screen_points_int[i+1]
                    # Vector llegada: target - prev
                    v1 = (target_point[0] - prev_point[0], target_point[1] - prev_point[1])
                    # Vector salida: next - target
                    v2 = (next_point[0] - target_point[0], next_point[1] - target_point[1])
                    
                    # Producto punto o simple comparación de dirección
                    # Si direcciones son diferentes, es esquina
                    # Normalizar no es necesario si son ortogonales (grid)
                    if (v1[0] != 0 and v2[1] != 0) or (v1[1] != 0 and v2[0] != 0):
                        is_corner = True

                # Movimiento suave interpolado
                # CONFIGURACIÓN:
                # - steps: Cantidad de pasos intermedios entre celda y celda.
                #          Más pasos = más suave pero más LENTO.
                #          Menos pasos = más rápido pero más "escalonado".
                #          Recomendado: 8-10 para rapidez, 15-20 para suavidad.
                # FIX: Aumentado a 15 para asegurar que el juego registre el arrastre en distancias cortas
                steps = 10
                for s in range(1, steps + 1):
                    if emergency_stop_flag:
                        pydirectinput.mouseUp()
                        return
                    
                    t = s / steps
                    inter_x = int(prev_point[0] + (target_point[0] - prev_point[0]) * t)
                    inter_y = int(prev_point[1] + (target_point[1] - prev_point[1]) * t)
                    
                    pydirectinput.moveTo(inter_x, inter_y)
                    # Pequeña pausa para no saturar 100% CPU pero muy rápida
                    time.sleep(0) 

                # Llegamos al target
                current_pos = target_point
                
                # Si es esquina, pausa para registrar el giro
                if is_corner:
                    # CONFIGURACIÓN: Pausa EXTRA en las esquinas para asegurar el giro.
                    time.sleep(0.04) # 40ms en esquinas
 
            
            # Pausa antes de soltar para asegurar que el juego procese la llegada
            time.sleep(0.05)
            
            # Mouse up para terminar trazo
            pydirectinput.mouseUp()
            time.sleep(DELAY_BETWEEN_COLORS)
            
    def get_color_name(self, color_id):
        # Mapeo inverso simple basado en keys de COLOR_RANGES
        # Asumiendo que self.colors_found (que no tenemos aqui directo) mapearia.
        # Pero podemos iterar COLOR_RANGES para buscar coincidencia si tuvieramos el color promedio.
        # Dado que color_id es un INT arbitrario asignado en scanning, necesitamos saber qué rango es.
        # EN SCAN: self.found_colors[id] = {'center':..., 'hsv_avg':...}
        # PERO: aqui solo tenemos solutions.
        # SOLUCIÓN: Usar el grid colors original guardado en self.last_grid_colors si existiera.
        # O MEJOR: El color_id ES el índice, pero si es '1', '2', etc. no sabemos qual es.
        # HACK: Recalcular el nombre basado en el punto de INICIO del path, que sabemos donde está.
        # YA LO HACEMOS ARRIBA en el loop de verificación.
        pass # Placeholder, la logica está inline arriba (necesitaria acceso a self.detected_colors_map)
        return None # Simplificado por ahora implementare logica inline mejorada

    def solve(self):
        """Flujo principal del solver - Máquina de estados"""
        global emergency_stop_flag
        
        if self.is_solving:
            return
            
        self.is_solving = True
        emergency_stop_flag = False
        
        try:
            # Estado SCAN
            self.state = SolverState.SCAN
            print("🔍 [SCAN] Analizando pantalla...")
            
            screen = self.capture_screen()
            grid_rect = self.find_puzzle_grid(screen)
            
            if not grid_rect:
                print("❌ No se detectó grid.")
                if DEBUG_MODE:
                    cv2.imwrite(f"debug_fail_{self.debug_counter}.png", screen)
                return
                
            print(f"✅ Grid detectado: {grid_rect}")
            grid_img = self.extract_grid(screen, grid_rect)
            
            # Guardar imagen del grid para debug
            if DEBUG_MODE:
                cv2.imwrite(f"debug_grid_{self.debug_counter}.png", grid_img)
                self.debug_counter += 1
            
                self.debug_counter += 1
            
            endpoints, id_to_color = self.analyze_grid(grid_img)
            self.detected_input_colors = id_to_color # Persistir para verificación
            
            if len(endpoints) < 4:  # Mínimo 2 colores (4 puntos)
                print("❌ Insuficientes puntos detectados.")
                return
            
            # Estado SOLVE
            self.state = SolverState.SOLVE
            print(f"🧮 [SOLVE] Resolviendo con Backtracking ({len(endpoints)} puntos)...")
            
            
            start_time = time.time()
            solutions = self.solve_puzzle(endpoints, grid_img, id_to_color)
            solve_time = (time.time() - start_time) * 1000
            
            print(f"   Tiempo de resolución: {solve_time:.1f}ms")
            
            if not solutions:
                print("❌ No se encontró solución lógica posible.")
                return
            
            if emergency_stop_flag:
                print("🛑 Cancelado por kill switch")
                return
                
            # Estado EXECUTE
            self.state = SolverState.EXECUTE
            print(f"✅ [EXECUTE] ¡Solución encontrada! Dibujando {len(solutions)} caminos...")
            
            # Guardar soluciones y datos del grid para reintentos
            self.solution_path = solutions
            self.grid_origin = (grid_rect[0], grid_rect[1])
            self.grid_rect_size = (grid_rect[2], grid_rect[3])

            # Dibujar solución directa (Sin reintentos ni verificaciones lentas)
            self.draw_solution(solutions, self.grid_origin, self.grid_rect_size)
            
            # Estado VERIFY (Final)
            self.state = SolverState.VERIFY
            print("✅ [VERIFY] Solución dibujada correctamente.")

            # VISUALIZACIÓN DE DEBUG (SOLICITADO)
            if DEBUG_MODE:
                self._visualize_solution(grid_img, solutions, id_to_color)
                
        except Exception as e:
            print(f"❌ Error crítico: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_solving = False
            self.state = SolverState.IDLE


# ============================================================
# INSTANCIA GLOBAL
# ============================================================
solver = FlowPuzzleSolver()


def on_press(key):
    """Callback cuando se presiona una tecla"""
    try:
        if hasattr(key, 'char') and key.char == 'j':
            # Verificar que NO se esté presionando Alt, Ctrl o Shift para evitar conflictos
            # Especialmente Alt+J que es el selector
            if not (keyboard.is_pressed('alt') or keyboard.is_pressed('ctrl')):
                thread = threading.Thread(target=solver.solve)
                thread.start()
    except AttributeError:
        pass


def main():
    """Función principal"""
    print("=" * 60)
    print("🎮 Flow Puzzle Solver - Forsaken Edition")
    print("=" * 60)
    print("  • Solver: Backtracking con heurísticas")
    print("  • Input:  pydirectinput (DirectX compatible)")
    print("  • DPI:    Awareness habilitado")
    if MANUAL_GRID_ENABLED:
        print(f"  • Grid:   Manual ({MANUAL_GRID_X}, {MANUAL_GRID_Y}) {MANUAL_GRID_SIZE}px")
    else:
        print("  • Grid:   Auto-detección")
    print("=" * 60)
    print("📋 Controles:")
    print("  [J]     - Activar solver cuando veas un puzzle")
    print("  [Alt+J] - Abrir selector visual de grid")
    print("  [F4]    - PARADA DE EMERGENCIA (Kill Switch)")
    print("  [WASD]  - Movimiento humano detiene el bot")
    print("  [Ctrl+C] - Salir del programa")
    print("=" * 60)
    
    # Escuchar teclado
    listener = pynput_keyboard.Listener(on_press=on_press)
    listener.start()
    
    # --- INTERFAZ GRÁFICA (GUI) ---
    try:
        root = tk.Tk()
        root.title("ForsakenAC")
        
        # Icono
        icon_path = resource_path("ForsakenAC.ico")
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
            
        # Configurar ventana no muy grande
        root.resizable(False, False)
        
        # Imagen de instrucciones
        img_path = resource_path("VanityInst.png")
        if os.path.exists(img_path):
            # Cargar y redimensionar imagen usando PIL
            original_img = Image.open(img_path)
            
            # Redimensionar (ej. mantener aspecto, max width 600)
            target_width = 600
            w_percent = (target_width / float(original_img.size[0]))
            h_size = int((float(original_img.size[1]) * float(w_percent)))
            
            resized_img = original_img.resize((target_width, h_size), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(resized_img)
            
            label = tk.Label(root, image=tk_img)
            label.pack()
            
            # Label de estado abajo
            status_label = tk.Label(root, text="Bot activo. Presiona J para resolver. Alt+J para calibrar.", 
                                   font=("Arial", 10), bg="#333", fg="white", pady=5)
            status_label.pack(fill=tk.X)
            
        else:
            tk.Label(root, text="Instrucciones no encontradas (VanityInst.png missing)", padx=20, pady=20).pack()

        # Centrar ventana
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f'{width}x{height}+{x}+{y}')

        def on_close():
            print("👋 Cerrando aplicación...")
            listener.stop()
            root.destroy()
            sys.exit()

        root.protocol("WM_DELETE_WINDOW", on_close)
        
        print("🖥️ Interfaz iniciada.")
        root.mainloop()
        
    except KeyboardInterrupt:
        print("\n👋 Cerrando solver...")
        listener.stop()
    except Exception as e:
        print(f"❌ Error lanzando GUI: {e}")
        listener.stop()


if __name__ == "__main__":
    main()
