import cv2
import os
import subprocess
import threading
from collections import deque
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

# ─── CONFIGURACIÓN ────────────────────────────────────
CAMARA = 0
TECLA_GUARDAR = 's'
TECLA_SALIR = 'e'

FPS = 30
BUFFER_SEG = 60
MIN_FRAMES_GUARDAR = 30  # mínimo 1 segundo si FPS=30

ANCHO = 1280
ALTO = 720
RESOLUCION = (ANCHO, ALTO)

AUDIO_FS = 44100
AUDIO_CHANNELS = 1
AUDIO_DTYPE = 'int16'

CARPETA = os.path.join(os.path.expanduser("~"), "Desktop", "padelclip")
# ──────────────────────────────────────────────────────

os.makedirs(CARPETA, exist_ok=True)

buffer_video = deque(maxlen=FPS * BUFFER_SEG)
buffer_audio = deque(maxlen=AUDIO_FS * BUFFER_SEG)

salir = threading.Event()
guardando = False
lock_guardado = threading.Lock()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"⚠️ Audio status: {status}")

    if salir.is_set():
        return

    canal = indata[:, 0].copy()
    buffer_audio.extend(canal.tolist())


def convertir_a_mp4(archivo_video_temp, archivo_audio_temp, archivo_final):
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"❌ No se pudo cargar imageio_ffmpeg: {e}")
        return False

    if not ffmpeg_path:
        print("❌ No se encontró ffmpeg.")
        return False

    if archivo_audio_temp and os.path.exists(archivo_audio_temp) and os.path.getsize(archivo_audio_temp) > 0:
        comando = [
            ffmpeg_path,
            "-y",
            "-i", archivo_video_temp,
            "-i", archivo_audio_temp,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            archivo_final
        ]
    else:
        comando = [
            ffmpeg_path,
            "-y",
            "-i", archivo_video_temp,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            archivo_final
        ]

    resultado = subprocess.run(comando, capture_output=True, text=True)

    if resultado.returncode != 0:
        print("❌ ffmpeg falló.")
        print(resultado.stderr)
        return False

    if not os.path.exists(archivo_final):
        print("❌ ffmpeg no generó el archivo final.")
        return False

    if os.path.getsize(archivo_final) == 0:
        print("❌ El MP4 final quedó vacío.")
        return False

    return True


def guardar_clip(frames_video, frames_audio):
    global guardando

    try:
        cantidad_frames = len(frames_video)

        if cantidad_frames < MIN_FRAMES_GUARDAR:
            print(f"⚠️ Muy pocos frames para guardar ({cantidad_frames}).")
            return

        timestamp = datetime.now().strftime("%H%M%S")
        base = os.path.join(CARPETA, f"clip_{timestamp}")

        archivo_video_temp = f"{base}_temp.avi"
        archivo_audio_temp = f"{base}_audio.wav"
        archivo_final = f"{base}.mp4"

        primer_frame = frames_video[0]
        alto_real, ancho_real = primer_frame.shape[:2]
        resolucion_real = (ancho_real, alto_real)

        print(f"💾 Guardando clip con {cantidad_frames} frames (~{cantidad_frames / FPS:.2f}s)")

        writer = cv2.VideoWriter(
            archivo_video_temp,
            cv2.VideoWriter_fourcc(*'MJPG'),
            FPS,
            resolucion_real
        )

        if not writer.isOpened():
            print("❌ No se pudo abrir el VideoWriter.")
            return

        frames_escritos = 0
        for frame in frames_video:
            if frame is None:
                continue

            if len(frame.shape) != 3:
                continue

            if (frame.shape[1], frame.shape[0]) != resolucion_real:
                frame = cv2.resize(frame, resolucion_real)

            writer.write(frame)
            frames_escritos += 1

        writer.release()

        print(f"📹 Frames escritos realmente: {frames_escritos}")

        if frames_escritos == 0:
            print("❌ No se escribió ningún frame al archivo temporal.")
            if os.path.exists(archivo_video_temp):
                os.remove(archivo_video_temp)
            return

        if not os.path.exists(archivo_video_temp):
            print("❌ No se creó el archivo temporal de video.")
            return

        if os.path.getsize(archivo_video_temp) == 0:
            print("❌ El archivo temporal de video quedó vacío.")
            return

        audio_disponible = False
        if len(frames_audio) > 0:
            audio_np = np.array(frames_audio, dtype=np.int16)
            if audio_np.size > 0:
                sf.write(archivo_audio_temp, audio_np, AUDIO_FS)
                if os.path.exists(archivo_audio_temp) and os.path.getsize(archivo_audio_temp) > 0:
                    audio_disponible = True

        if not audio_disponible:
            archivo_audio_temp = None
            print("⚠️ No se pudo guardar audio válido; se exportará solo video.")

        ok = convertir_a_mp4(archivo_video_temp, archivo_audio_temp, archivo_final)
        if not ok:
            print("⚠️ Conversión fallida. Te dejo los temporales para revisar:")
            print(f"   {archivo_video_temp}")
            if archivo_audio_temp:
                print(f"   {archivo_audio_temp}")
            return

        print(f"✅ Clip final guardado correctamente: {archivo_final}")

        try:
            if os.path.exists(archivo_video_temp):
                os.remove(archivo_video_temp)
        except OSError:
            pass

        if archivo_audio_temp:
            try:
                if os.path.exists(archivo_audio_temp):
                    os.remove(archivo_audio_temp)
            except OSError:
                pass

    finally:
        with lock_guardado:
            guardando = False


cam = cv2.VideoCapture(CAMARA)
cam.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
cam.set(cv2.CAP_PROP_FPS, FPS)

if not cam.isOpened():
    print("❌ No se pudo abrir la cámara. Verifica CAMARA = 0 o 1")
    raise SystemExit

try:
    stream_audio = sd.InputStream(
        samplerate=AUDIO_FS,
        channels=AUDIO_CHANNELS,
        dtype=AUDIO_DTYPE,
        callback=audio_callback
    )
    stream_audio.start()
    audio_activo = True
except Exception as e:
    print(f"⚠️ No se pudo iniciar el micrófono: {e}")
    stream_audio = None
    audio_activo = False

print("🎥 Cámara activa. Buffer grabando...")
print(f"🎙️ Micrófono activo: {'sí' if audio_activo else 'no'}")
print(f"⌨️ Presiona '{TECLA_GUARDAR.upper()}' para guardar el buffer actual")
print(f"⌨️ Presiona '{TECLA_SALIR.upper()}' para salir de inmediato")

while not salir.is_set():
    ret, frame = cam.read()
    if not ret:
        print("❌ Error leyendo la cámara")
        break

    frame = cv2.resize(frame, RESOLUCION)
    buffer_video.append(frame.copy())

    seg_video = len(buffer_video) / FPS
    seg_audio = len(buffer_audio) / AUDIO_FS if len(buffer_audio) > 0 else 0.0
    seg_mostrados = seg_video if not audio_activo else min(seg_video, seg_audio)

    texto = (
        f"Buffer: {seg_mostrados:.1f}s | "
        f"[{TECLA_GUARDAR.upper()}] Guardar | "
        f"[{TECLA_SALIR.upper()}] Salir"
    )

    cv2.putText(
        frame,
        texto,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 100),
        2
    )

    cv2.imshow("PadelClip MVP", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord(TECLA_GUARDAR):
        with lock_guardado:
            if guardando:
                print("⏳ Ya hay un guardado en curso.")
                continue
            guardando = True

        frames_video = list(buffer_video)
        frames_audio = list(buffer_audio)

        if len(frames_video) < MIN_FRAMES_GUARDAR:
            print(f"⚠️ Aún no hay suficiente buffer. Frames actuales: {len(frames_video)}")
            with lock_guardado:
                guardando = False
            continue

        hilo = threading.Thread(
            target=guardar_clip,
            args=(frames_video, frames_audio),
            daemon=True
        )
        hilo.start()

    elif key == ord(TECLA_SALIR) or key == ord('q'):
        print(f"\n🛑 Tecla '{TECLA_SALIR.upper()}' presionada — cerrando...")
        salir.set()
        break

cam.release()
cv2.destroyAllWindows()

if stream_audio is not None:
    try:
        stream_audio.stop()
        stream_audio.close()
    except Exception:
        pass

print("👋 Programa cerrado")