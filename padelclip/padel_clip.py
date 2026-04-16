import cv2
import keyboard
import threading
import os
from collections import deque
from datetime import datetime

# ─── CONFIGURACIÓN — edita solo aquí ──────────────────
CAMARA = 0             # 0 = cámara integrada del PC
TECLA = 's'            # tecla que guarda el clip
TECLA_SALIR = 'e'      # tecla para terminar el programa
FPS = 30               # frames por segundo
BUFFER_SEG = 60        # segundos que guarda el buffer
ANCHO = 1280           # resolución ancho (1280 para 720p)
ALTO = 720             # resolución alto
CARPETA = os.path.join(os.path.expanduser("~"), "Desktop", "padelclip")  # carpeta donde se guardan los clips
# ──────────────────────────────────────────────────────

RESOLUCION = (ANCHO, ALTO)
buffer = deque(maxlen=FPS * BUFFER_SEG)
salir = threading.Event()

os.makedirs(CARPETA, exist_ok=True)

def guardar_clip(frames):
    nombre = os.path.join(CARPETA, f"clip_{datetime.now().strftime('%H%M%S')}.mp4")

    writer = cv2.VideoWriter(
        nombre,
        cv2.VideoWriter_fourcc(*'avc1'),
        FPS, RESOLUCION
    )

    if not writer.isOpened():
        writer = cv2.VideoWriter(
            nombre,
            cv2.VideoWriter_fourcc(*'mp4v'),
            FPS, RESOLUCION
        )

    if not writer.isOpened():
        print("❌ ERROR: No se pudo crear el writer.")
        return

    for frame in frames:
        writer.write(frame)

    writer.release()
    print(f"✅ Guardado: {nombre} ({len(frames)//FPS}s, {len(frames)} frames)")

def escuchar_teclado():
    print(f"⌨️  Presiona '{TECLA.upper()}' para guardar el último {BUFFER_SEG}s")
    print(f"⌨️  Presiona '{TECLA_SALIR.upper()}' para cerrar el programa")
    while not salir.is_set():
        if keyboard.is_pressed(TECLA):
            if len(buffer) > 0:
                frames = list(buffer)
                t = threading.Thread(target=guardar_clip, args=(frames,), daemon=True)
                t.start()
            import time; time.sleep(0.5)  # evita doble disparo

        if keyboard.is_pressed(TECLA_SALIR):
            print(f"\n🛑 Tecla '{TECLA_SALIR.upper()}' presionada — cerrando...")
            salir.set()
            break

# ─── INICIO ──────────────────────────────────────────
cam = cv2.VideoCapture(CAMARA)
cam.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
cam.set(cv2.CAP_PROP_FPS, FPS)

if not cam.isOpened():
    print("❌ No se pudo abrir la cámara. Verifica CAMARA = 0 o 1")
    exit()

hilo = threading.Thread(target=escuchar_teclado, daemon=True)
hilo.start()

print("🎥 Cámara activa. Buffer grabando...")

while not salir.is_set():
    ret, frame = cam.read()
    if not ret:
        print("❌ Error leyendo la cámara")
        break

    buffer.append(frame)

    seg_guardados = len(buffer) // FPS
    cv2.putText(frame, f"Buffer: {seg_guardados}s | [{TECLA.upper()}] Guardar  [{TECLA_SALIR.upper()}] Salir",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 100), 2)

    cv2.imshow("PadelClip MVP", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == ord(TECLA_SALIR):
        salir.set()
        break

cam.release()
cv2.destroyAllWindows()
print("👋 Programa cerrado")