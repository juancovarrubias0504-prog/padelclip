import cv2
import os
import time
import threading
from collections import deque
from datetime import datetime


# ─── CONFIGURACIÓN ────────────────────────────────────
FPS_OBJETIVO = 30
SEGUNDOS_CLIP = 30

ANCHO_DESEADO = 1280
ALTO_DESEADO = 720

TECLA_GUARDAR = ord('s')
TECLA_SALIR = ord('q')

INDICES_CAMARA = [0, 1, 2, 3]
BACKENDS = [
    ("CAP_DSHOW", cv2.CAP_DSHOW),
    ("CAP_MSMF", cv2.CAP_MSMF),
    ("CAP_ANY", cv2.CAP_ANY),
]
# ──────────────────────────────────────────────────────


CARPETA_BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA_CLIPS = os.path.join(CARPETA_BASE, "clips")
os.makedirs(CARPETA_CLIPS, exist_ok=True)

guardando = False
lock_guardado = threading.Lock()


def formatear_tiempo(segundos):
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    segundos_restantes = int(segundos % 60)
    return f"{horas:02d}:{minutos:02d}:{segundos_restantes:02d}"


def abrir_camara():
    print("🔎 Buscando cámara disponible...")

    for nombre_backend, backend in BACKENDS:
        for indice in INDICES_CAMARA:
            cap = cv2.VideoCapture(indice, backend)

            if not cap.isOpened():
                cap.release()
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO_DESEADO)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO_DESEADO)
            cap.set(cv2.CAP_PROP_FPS, FPS_OBJETIVO)

            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                print(f"✅ Cámara encontrada | índice={indice} | backend={nombre_backend}")
                return cap, indice, nombre_backend

            cap.release()

    return None, None, None


def crear_writer(base_sin_extension, fps, resolucion):
    intentos = [
        (f"{base_sin_extension}.mp4", cv2.VideoWriter_fourcc(*"mp4v")),
        (f"{base_sin_extension}.avi", cv2.VideoWriter_fourcc(*"XVID")),
        (f"{base_sin_extension}.avi", cv2.VideoWriter_fourcc(*"MJPG")),
    ]

    for ruta, fourcc in intentos:
        writer = cv2.VideoWriter(ruta, fourcc, fps, resolucion)
        if writer.isOpened():
            return writer, ruta

    return None, None


def guardar_clip(frames, fps_guardado):
    global guardando

    try:
        if len(frames) == 0:
            print("❌ No hay frames para guardar.")
            return

        primer_frame = frames[0]
        alto, ancho = primer_frame.shape[:2]
        resolucion = (ancho, alto)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(CARPETA_CLIPS, f"clip_{timestamp}")

        writer, ruta_final = crear_writer(base, fps_guardado, resolucion)
        if writer is None:
            print("❌ No se pudo crear el archivo de video.")
            return

        escritos = 0
        for frame in frames:
            if frame is None:
                continue

            if frame.shape[:2] != (alto, ancho):
                frame = cv2.resize(frame, resolucion)

            writer.write(frame)
            escritos += 1

        writer.release()

        duracion = escritos / fps_guardado if fps_guardado > 0 else 0
        print(f"✅ Clip guardado: {ruta_final}")
        print(f"📹 Frames escritos: {escritos} | duración aprox: {duracion:.2f}s")

    finally:
        with lock_guardado:
            guardando = False


cap, indice_camara, backend_usado = abrir_camara()

if cap is None:
    print("❌ No se pudo abrir ninguna cámara.")
    raise SystemExit

fps_real = cap.get(cv2.CAP_PROP_FPS)
if fps_real is None or fps_real <= 1 or fps_real > 120:
    fps_real = FPS_OBJETIVO

FPS_USADO = int(round(fps_real))
MAX_FRAMES_BUFFER = FPS_USADO * SEGUNDOS_CLIP
buffer_frames = deque(maxlen=MAX_FRAMES_BUFFER)

tiempo_inicio = time.time()

print("🎥 Cámara activa")
print(f"📷 Índice cámara: {indice_camara}")
print(f"🧩 Backend: {backend_usado}")
print(f"🎞️ FPS usado: {FPS_USADO}")
print(f"💾 Carpeta de clips: {CARPETA_CLIPS}")
print("⌨️ S = guardar últimos 30 segundos")
print("⌨️ Q = salir")

while True:
    ok, frame = cap.read()

    if not ok or frame is None or frame.size == 0:
        print("⚠️ No se pudo leer un frame de la cámara.")
        time.sleep(0.01)
        continue

    buffer_frames.append(frame.copy())

    tiempo_total = time.time() - tiempo_inicio
    segundos_en_buffer = len(buffer_frames) / FPS_USADO

    overlay = frame.copy()

    texto_1 = f"Tiempo corriendo: {formatear_tiempo(tiempo_total)}"
    texto_2 = f"Buffer: {segundos_en_buffer:05.1f}s / {SEGUNDOS_CLIP}s"
    texto_3 = "[S] Guardar clip | [Q] Salir"

    cv2.putText(overlay, texto_1, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
    cv2.putText(overlay, texto_2, (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
    cv2.putText(overlay, texto_3, (15, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

    if segundos_en_buffer < SEGUNDOS_CLIP:
        faltan = SEGUNDOS_CLIP - segundos_en_buffer
        texto_4 = f"Aun faltan {faltan:.1f}s para poder guardar un clip completo"
        cv2.putText(overlay, texto_4, (15, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)

    cv2.imshow("PadelClip - Instant Replay", overlay)
    tecla = cv2.waitKey(1) & 0xFF

    if tecla == TECLA_GUARDAR:
        if len(buffer_frames) < MAX_FRAMES_BUFFER:
            print("⚠️ Todavía no hay 30 segundos completos en el buffer.")
            continue

        with lock_guardado:
            if guardando:
                print("⏳ Ya se está guardando un clip.")
                continue
            guardando = True

        frames_a_guardar = list(buffer_frames)

        hilo = threading.Thread(
            target=guardar_clip,
            args=(frames_a_guardar, FPS_USADO),
            daemon=True
        )
        hilo.start()

    elif tecla == TECLA_SALIR:
        print("🛑 Cerrando programa...")
        break

cap.release()
cv2.destroyAllWindows()
print("👋 Programa cerrado.")
