"""Model propagasi radio log-distance path loss dan estimasi jarak RSSI.

Rumus dasar:
    RSSI(d) = RSSI(d0) - 10 * n * log10(d / d0)
dengan d0 = 1.0 meter (jarak acuan), n = eksponen path loss lingkungan.
"""

import math
import random


def rssi_to_distance(rssi: float, rssi_d0: float, n: float, d0: float = 1.0) -> float:
    """Konversi RSSI terukur (dBm) menjadi estimasi jarak (meter)."""
    if n <= 0:
        raise ValueError("n harus positif")
    return d0 * (10.0 ** ((rssi_d0 - rssi) / (10.0 * n)))


def distance_to_rssi(d: float, rssi_d0: float, n: float, d0: float = 1.0) -> float:
    """Model maju: prediksi RSSI pada jarak d (meter)."""
    if d <= 0:
        raise ValueError("jarak harus positif")
    return rssi_d0 - (10.0 * n * math.log10(d / d0))


def calibrate(samples: list[tuple[float, float]]) -> tuple[float, float]:
    """Estimasi parameter (n, rssi_d0) via regresi linier kuadrat terkecil.
    
    Format sample: [(jarak_meter, rssi_dbm), ...]
    Persamaan linier: RSSI = a + b * log10(d), dimana a = rssi_d0 dan b = -10*n.
    """
    if len(samples) < 2:
        raise ValueError("butuh minimal 2 titik kalibrasi")

    xs = [math.log10(d) for d, _ in samples]
    ys = [r for _, r in samples]
    m = len(samples)

    mx = sum(xs) / m
    my = sum(ys) / m

    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx < 1e-12:
        raise ValueError("variasi jarak kalibrasi terlalu kecil")

    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - (b * mx)

    return (-b / 10.0, a)


def noisy_rssi(d: float, rssi_d0: float, n: float, sigma_db: float = 2.0, rng=None) -> float:
    """Sintesis pembacaan RSSI dengan gangguan noise Gaussian."""
    r = rng if rng is not None else random
    return distance_to_rssi(d, rssi_d0, n) + r.gauss(0.0, sigma_db)


def click_rate_hz(
    rssi_smooth: float,
    r_min: float = -85.0,
    r_max: float = -50.0,
    f_min: float = 1.0,
    f_max: float = 18.0
) -> float:
    """Pemetaan RSSI halus ke frekuensi audio klik (Hz).
    
    Makin mendekati 0 dBm (semakin dekat secara fisik), frekuensi klik semakin tinggi.
    """
    r = max(r_min, min(r_max, rssi_smooth))
    frac = (r - r_min) / (r_max - r_min)
    return f_min + (frac * (f_max - f_min))
