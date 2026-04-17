import cv2
import os
import time
import threading
import subprocess
import struct
import wave
from collections import deque
from datetime import datetime

try:
    import pyaudio
    AUDIO_DISPONIBLE = True
except ImportError:
    AUDIO_DISPONIBLE = False
    print("⚠️  pyaudio no instalado — el audio no será capturado.")
    print("    Instala con: pip install pyaudio")


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

# Audio
AUDIO_TASA = 44100        # Hz — frecuencia de muestreo estándar
AUDIO_CANALES = 1         # mono (usa 2 para estéreo si el mic lo soporta)
AUDIO_CHUNK = 1024        # frames por bloque leído
# ──────────────────────────────────────────────────────


CARPETA_BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA_CLIPS = os.path.join(CARPETA_BASE, "clips")
os.makedirs(CARPETA_CLIPS, exist_ok=True)

guardando = False
hilo_guardado = None
lock_guardado = threading.Lock()
lock_buffer = threading.Lock()
lock_audio = threading.Lock()

# Buffer de audio: cada elemento es un bloque de bytes crudos (PCM)
# Calculamos cuántos chunks caben en SEGUNDOS_CLIP segundos
CHUNKS_POR_SEGUNDO = AUDIO_TASA / AUDIO_CHUNK
MAX_CHUNKS_AUDIO = int(CHUNKS_POR_SEGUNDO * SEGUNDOS_CLIP) + 1
buffer_audio = deque(maxlen=MAX_CHUNKS_AUDIO)


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


def abrir_microfono():
    """Abre el micrófono por defecto con pyaudio. Devuelve (stream, pa) o (None, None)."""
    if not AUDIO_DISPONIBLE:
        return None, None
    try:
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=AUDIO_CANALES,
            rate=AUDIO_TASA,
            input=True,
            frames_per_buffer=AUDIO_CHUNK,
        )
        print("🎙️  Micrófono abierto correctamente")
        return stream, pa
    except Exception as e:
        print(f"⚠️  No se pudo abrir el micrófono: {e}")
        return None, None


def capturar_audio(stream, evento_parar):
    """Hilo que lee continuamente del micrófono y llena buffer_audio."""
    while not evento_parar.is_set():
        try:
            datos = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
            with lock_audio:
                buffer_audio.append(datos)
        except Exception:
            time.sleep(0.01)


def guardar_wav_temporal(chunks, ruta_wav):
    """Escribe los chunks de audio crudo en un archivo WAV temporal."""
    with wave.open(ruta_wav, 'wb') as wf:
        wf.setnchannels(AUDIO_CANALES)
        wf.setsampwidth(2)          # paInt16 = 2 bytes por muestra
        wf.setframerate(AUDIO_TASA)
        wf.writeframes(b"".join(chunks))


def combinar_video_audio(ruta_video, ruta_wav, ruta_final_mp4):
    """
    Usa ffmpeg para mezclar video sin audio + WAV en un MP4 final.
    Si ffmpeg no está instalado, deja el video sin audio.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", ruta_video,
            "-i", ruta_wav,
            "-c:v", "copy",        # copia el video sin re-encodear (rápido)
            "-c:a", "aac",         # codifica audio en AAC (compatible con MP4)
            "-shortest",           # corta al track más corto
            ruta_final_mp4,
        ]
        resultado = subprocess.run(cmd, capture_output=True, timeout=60)
        if resultado.returncode == 0:
            os.remove(ruta_video)
            os.remove(ruta_wav)
            return True
        else:
            print(f"⚠️  ffmpeg falló: {resultado.stderr.decode()}")
            return False
    except FileNotFoundError:
        print("⚠️  ffmpeg no encontrado — el clip se guardará sin audio.")
        print("    Descarga ffmpeg en: https://ffmpeg.org/download.html")
        return False
    except subprocess.TimeoutExpired:
        print("⚠️  ffmpeg tardó demasiado — el clip se guardará sin audio.")
        return False


def crear_writer(base_sin_extension, fps, resolucion):
    intentos = [
        # FIX #3: avc1 primero — produce MP4 reproducible en casi todos los players
        (f"{base_sin_extension}.mp4", cv2.VideoWriter_fourcc(*"avc1")),
        (f"{base_sin_extension}.mp4", cv2.VideoWriter_fourcc(*"mp4v")),
        (f"{base_sin_extension}.avi", cv2.VideoWriter_fourcc(*"XVID")),
        (f"{base_sin_extension}.avi", cv2.VideoWriter_fourcc(*"MJPG")),
    ]

    for ruta, fourcc in intentos:
        writer = cv2.VideoWriter(ruta, fourcc, fps, resolucion)
        if writer.isOpened():
            return writer, ruta

    return None, None


def guardar_clip(frames, fps_guardado, chunks_audio):
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

        tiene_audio = len(chunks_audio) > 0

        # Si hay audio, el video va a un archivo temporal primero
        if tiene_audio:
            ruta_video_tmp = f"{base}_video_tmp.mp4"
        else:
            ruta_video_tmp = None

        writer, ruta_video = crear_writer(
            base if not tiene_audio else base + "_video_tmp",
            fps_guardado,
            resolucion,
        )
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

        if tiene_audio:
            ruta_wav = f"{base}_audio_tmp.wav"
            guardar_wav_temporal(chunks_audio, ruta_wav)

            ruta_final_mp4 = f"{base}.mp4"
            exito = combinar_video_audio(ruta_video, ruta_wav, ruta_final_mp4)

            if exito:
                print(f"✅ Clip con audio guardado: {ruta_final_mp4}")
            else:
                # Si falló ffmpeg, el video temporal queda sin audio
                print(f"✅ Clip guardado (sin audio): {ruta_video}")
        else:
            print(f"✅ Clip guardado (sin audio — micrófono no disponible): {ruta_video}")

        print(f"📹 Frames escritos: {escritos} | duración aprox: {duracion:.2f}s")

    finally:
        with lock_guardado:
            guardando = False


cap, indice_camara, backend_usado = abrir_camara()

if cap is None:
    print("❌ No se pudo abrir ninguna cámara.")
    raise SystemExit

fps_real = cap.get(cv2.CAP_PROP_FPS)

# Cualquier valor fuera del rango realista [10, 120] se considera inválido
if fps_real is None or fps_real < 10 or fps_real > 120:
    fps_real = FPS_OBJETIVO

FPS_USADO = int(round(fps_real))
MAX_FRAMES_BUFFER = FPS_USADO * SEGUNDOS_CLIP
buffer_frames = deque(maxlen=MAX_FRAMES_BUFFER)

# ── Micrófono ──────────────────────────────────────────
stream_mic, pa_mic = abrir_microfono()
evento_parar_audio = threading.Event()

if stream_mic is not None:
    hilo_audio = threading.Thread(
        target=capturar_audio,
        args=(stream_mic, evento_parar_audio),
        daemon=True,   # el hilo de captura sí puede ser daemon: no tiene estado crítico
    )
    hilo_audio.start()
else:
    hilo_audio = None
# ───────────────────────────────────────────────────────

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
        # FIX #4: sleep corto para no quemar CPU en caso de fallo continuo de cámara
        time.sleep(0.05)
        continue

    # FIX #1: proteger escritura al buffer con lock
    with lock_buffer:
        buffer_frames.append(frame.copy())

    tiempo_total = time.time() - tiempo_inicio

    # FIX #1: proteger lectura del len también
    with lock_buffer:
        frames_en_buffer = len(buffer_frames)

    segundos_en_buffer = frames_en_buffer / FPS_USADO

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
        with lock_buffer:
            frames_listos = len(buffer_frames)

        if frames_listos < MAX_FRAMES_BUFFER:
            print("⚠️ Todavía no hay 30 segundos completos en el buffer.")
            continue

        with lock_guardado:
            if guardando:
                print("⏳ Ya se está guardando un clip.")
                continue
            guardando = True

        # Copiar ambos buffers bajo sus locks
        with lock_buffer:
            frames_a_guardar = list(buffer_frames)

        with lock_audio:
            chunks_a_guardar = list(buffer_audio)

        hilo_guardado = threading.Thread(
            target=guardar_clip,
            args=(frames_a_guardar, FPS_USADO, chunks_a_guardar),
            daemon=False,
        )
        hilo_guardado.start()

    elif tecla == TECLA_SALIR:
        print("🛑 Cerrando programa...")
        break

cap.release()
cv2.destroyAllWindows()

# Detener captura de audio
evento_parar_audio.set()
if stream_mic is not None:
    stream_mic.stop_stream()
    stream_mic.close()
if pa_mic is not None:
    pa_mic.terminate()

# Esperar a que termine de guardar antes de salir del proceso
if hilo_guardado is not None and hilo_guardado.is_alive():
    print("⏳ Esperando a que termine de guardarse el clip...")
    hilo_guardado.join()

print("👋 Programa cerrado.")
