"""Penghasil dan pemutar suara klik audio radar (Non-blocking)."""

import math
import os
import shutil
import struct
import subprocess
import sys
import wave

CLICK_WAV_PATH = "/tmp/wavehound_click.wav"
_PLAYER_CMD = None


def _ensure_click_wav(freq: int = 1200, duration: float = 0.015) -> str:
    """Membuat file WAV audio klik radar pendek jika belum ada di cache."""
    if os.path.exists(CLICK_WAV_PATH) and os.path.getsize(CLICK_WAV_PATH) > 100:
        return CLICK_WAV_PATH

    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    with wave.open(CLICK_WAV_PATH, "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(n_samples):
            # Kurva peluruhan eksponensial agar suaranya berupa bunyi 'klik/tik' bersih
            decay = (1.0 - (i / n_samples)) ** 2
            val = int(32767 * decay * math.sin(2 * math.pi * freq * (i / sample_rate)))
            wav.writeframes(struct.pack("<h", val))

    return CLICK_WAV_PATH


def _detect_player() -> list[str] | None:
    global _PLAYER_CMD
    if _PLAYER_CMD is not None:
        return _PLAYER_CMD

    if shutil.which("paplay"):
        _PLAYER_CMD = ["paplay"]
    elif shutil.which("aplay"):
        _PLAYER_CMD = ["aplay", "-q"]
    elif shutil.which("pw-play"):
        _PLAYER_CMD = ["pw-play"]
    else:
        _PLAYER_CMD = []

    return _PLAYER_CMD


def play_click():
    """Membunyikan satu klik audio non-blocking melalui speaker/headphone."""
    cmd = _detect_player()
    if cmd:
        wav_path = _ensure_click_wav()
        try:
            # Jalankan di background tanpa memblokir thread BLE
            subprocess.Popen(
                cmd + [wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return
        except Exception:
            pass

    # Fallback ke terminal bell ASCII jika tidak ada audio server
    sys.stdout.write("\a")
    sys.stdout.flush()
