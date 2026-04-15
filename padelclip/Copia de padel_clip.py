import cv2
import keyboard
import threading
from collections import deque
from datetime import datetime

# ─── CONFIGURACIÓN — edita solo aquí ──────────────────
CAMARA     = 0         # 0 = cámara integrada del PC
TECLA      = 's'   # tecla que guarda el clip
FPS        = 30        # frames por segundo
BUFFER_SEG = 60        # segundos que guarda el buffer
ANCHO      = 1280      # resolución ancho (1280 para 720p)
ALTO       = 720       # resolución alto  (cambia a 1920/1080 con StreamCam)
# ──────────────────────────────────────────────────────

RESOLUCION = (ANCHO, ALTO)
buffer     = deque(maxlen=FPS * BUFFER_SEG)
guardando  = False

def guardar_clip(frames):
    nombre = f"clip_{datetime.now().strftime('%H%M%S')}.mp4"

    writer = cv2.VideoWriter(
        nombre,
        cv2.VideoWriter_fourcc(*'avc1'),
        FPS, RESOLUCION
    )

    if not writer.isOpened():
        print("❌ ERROR: No se pudo crear el writer.")
        return

    for frame in frames:
        writer.write(frame)

    writer.release()
    print(f"✅ Guardado: {nombre}  ({len(frames)//FPS}s)")

def escuchar_teclado():
    print(f"⌨️  Presiona '{TECLA}' para guardar el último {BUFFER_SEG}s")
    while True:
        keyboard.wait(TECLA)
        if len(buffer) > 0:
            frames = list(buffer)  # copia instantánea del buffer
            t = threading.Thread(target=guardar_clip, args=(frames,), daemon=True)
            t.start()             # cada clip corre en su propio hilo independiente
        keyboard.wait(TECLA + ' up')


# ─── INICIO ──────────────────────────────────────────
cam = cv2.VideoCapture(CAMARA)
cam.set(cv2.CAP_PROP_FRAME_WIDTH,  ANCHO)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
cam.set(cv2.CAP_PROP_FPS, FPS)

if not cam.isOpened():
    print("❌ No se pudo abrir la cámara. Verifica CAMARA = 0 o 1")
    exit()

hilo = threading.Thread(target=escuchar_teclado, daemon=True)
hilo.start()

print("🎥 Cámara activa. Buffer grabando...")
print("   Q en la ventana para salir")

while True:
    ret, frame = cam.read()
    if not ret:
        print("❌ Error leyendo la cámara")
        break

    buffer.append(frame)

    # Muestra contador de frames en pantalla
    seg_guardados = len(buffer) // FPS
    cv2.putText(frame, f"Buffer: {seg_guardados}s  |  Presiona '{TECLA}' para guardar clip",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,100), 2)

    cv2.imshow("PadelClip MVP", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cam.release()
cv2.destroyAllWindows()
print("👋 Programa cerrado")