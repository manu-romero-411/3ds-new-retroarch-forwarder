#!/usr/bin/env python3
"""
Genera assets PLACEHOLDER (icon.png, banner.png, audio.wav) para poder
empaquetar el stub como .cia con bannertool/makerom sin depender de tener
ya arte final. Solo usa la stdlib de Python (zlib, struct, wave) para no
añadir dependencias nuevas a la imagen Docker.

Reemplaza estos 3 archivos por los definitivos cuando tengas icono/banner
propios (mismo nombre y ruta: icon.png 48x48, banner.png 256x128,
audio.wav para la musiquita del banner en el HOME Menu).

Uso:
    python3 tools/generate_placeholder_assets.py
"""
import os
import struct
import wave
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Color placeholder: un azul oscuro genérico (RGB)
COLOR = (0x2E, 0x3A, 0x59)


def write_png(path, width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    row = bytes([0]) + bytes(rgb) * width  # filter byte 0 + raw pixels
    raw = row * height
    idat = zlib.compress(raw, 9)

    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def write_silence_wav(path, seconds=1, rate=44100, channels=2, sampwidth=2):
    n_frames = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (n_frames * channels * sampwidth))


def main():
    icon_path = os.path.join(ROOT, "icon.png")
    banner_path = os.path.join(ROOT, "banner.png")
    audio_path = os.path.join(ROOT, "audio.wav")

    if not os.path.exists(icon_path):
        write_png(icon_path, 48, 48, COLOR)
        print(f"[assets] Generado placeholder: {icon_path}")
    if not os.path.exists(banner_path):
        write_png(banner_path, 256, 128, COLOR)
        print(f"[assets] Generado placeholder: {banner_path}")
    if not os.path.exists(audio_path):
        write_silence_wav(audio_path, seconds=1)
        print(f"[assets] Generado placeholder: {audio_path}")


if __name__ == "__main__":
    main()
