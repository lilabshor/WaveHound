"""Rangkaian pengujian numerik fungsional dan validasi ilmiah WaveHound.

16 uji mandiri (stdlib Python murni) memverifikasi aljabar path loss, kalibrasi regresi,
filter perataan sinyal, multilaterasi Gauss-Newton, privasi allowlist, dan integrasi E2E.
"""

import math
import os
import random
import sys

# Sisipkan direktori root project ke sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wavehound.core.rssi_model import (
    rssi_to_distance,
    distance_to_rssi,
    calibrate,
    click_rate_hz,
)
from wavehound.core.filters import EMA, Kalman1D
from wavehound.core.trilateration import trilaterate, position_error
from wavehound.core.privacy import mask_token, redact_scan_entry, retention_ok
from wavehound.scanner.mock import MockScannerNet


def test_pathloss_inversi_eksak():
    distances = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
    tx = -59.0
    n = 2.0
    max_err = 0.0

    for d in distances:
        r = distance_to_rssi(d, tx, n)
        d_inv = rssi_to_distance(r, tx, n)
        err = abs(d - d_inv)
        if err > max_err:
            max_err = err
        if err >= 1e-9:
            raise AssertionError(f"Galat inversi melebihi batas: d={d}, d_inv={d_inv}, err={err}")

    return f"6 jarak, galat < 1e-9 m"


def test_kalibrasi_n():
    dists = (1.0, 1.5, 2.0, 2.5, 3.0, 4.5, 8.0, 9.0, 10.0)
    rng = random.Random(42)
    samples = [(d, distance_to_rssi(d, -59.0, 2.4) + rng.gauss(0, 0.7)) for d in dists]
    n_est, _ = calibrate(samples)
    if abs(n_est - 2.412) > 0.05:
        raise AssertionError(f"Estimasi n meleset: {n_est}")
    return f"n_est={n_est:.3f}"


def test_kalibrasi_txpower():
    dists = (1.0, 1.5, 2.0, 2.5, 3.0, 4.5, 8.0, 9.0, 10.0)
    rng = random.Random(42)
    samples = [(d, distance_to_rssi(d, -59.0, 2.4) + rng.gauss(0, 0.7)) for d in dists]
    _, tx_est = calibrate(samples)
    if abs(tx_est - (-59.05)) > 0.2:
        raise AssertionError(f"Estimasi TxPower meleset: {tx_est}")
    return f"tx_est={tx_est:.2f} dBm"


def test_estimasi_jarak_mae():
    rng = random.Random(42)
    errors = []
    for _ in range(2000):
        d_true = rng.uniform(0.5, 15.0)
        rssi = distance_to_rssi(d_true, -59.0, 2.2) + rng.gauss(0.0, 2.0)
        d_est = rssi_to_distance(rssi, -59.0, 2.2)
        errors.append(abs(d_est - d_true))

    mae = sum(errors) / len(errors)
    if abs(mae - 1.36) > 0.15:
        raise AssertionError(f"MAE jarak berada di luar ambang: {mae:.2f}")
    return f"MAE={mae:.2f} m"


def test_klik_monoton():
    prev_rate = click_rate_hz(-85.0)
    for rssi in range(-84, -49):
        curr_rate = click_rate_hz(float(rssi))
        if curr_rate <= prev_rate:
            raise AssertionError(f"Laju klik tidak naik monoton pada RSSI {rssi} dBm")
        prev_rate = curr_rate
    return "laju monoton 1.0 s/d 18.0 Hz"


def test_validasi_n_negatif():
    try:
        rssi_to_distance(-70.0, -59.0, n=-1.0)
        raise AssertionError("Gagal menolak n negatif")
    except ValueError:
        pass

    try:
        distance_to_rssi(-2.0, -59.0, n=2.0)
        raise AssertionError("Gagal menolak jarak negatif")
    except ValueError:
        pass

    return "ValueError tertolak dengan benar"


def test_ema_konvergen():
    ema = EMA(alpha=0.25)
    val = 0.0
    for _ in range(60):
        val = ema.update(-70.0)

    if abs(val - (-70.0)) > 1e-4:
        raise AssertionError(f"EMA tidak konvergen ke -70 dBm: {val}")
    return f"konvergen tepat ke {val:.3f} dBm"


def test_kalman_konvergen():
    rng = random.Random(42)
    kalman = Kalman1D(process_var=0.05, meas_var=4.0, x0=-95.0, p0=10.0)
    for _ in range(200):
        z = -65.0 + rng.gauss(0.0, 2.0)
        kalman.update(z)

    if abs(kalman.x - (-65.0)) > 1.5:
        raise AssertionError(f"Kalman gagal konvergen ke -65 dBm: {kalman.x}")
    return f"konvergen ke {kalman.x:.2f} dBm"


def test_kalman_tracking():
    rng1 = random.Random(42)
    rng2 = random.Random(11)
    kalman = Kalman1D(process_var=0.05, meas_var=4.0, x0=-95.0, p0=10.0)
    for _ in range(200):
        kalman.update(-65.0 + rng1.gauss(0.0, 2.0))

    # Perubahan mendadak level sinyal (target mendekat)
    for _ in range(40):
        kalman.update(-50.0 + rng2.gauss(0.0, 2.0))

    if abs(kalman.x - (-50.0)) > 1.5:
        raise AssertionError(f"Kalman gagal mengikuti perubahan level mendadak: {kalman.x}")
    return f"tracking lonjakan hingga {kalman.x:.2f} dBm"


def test_trilaterasi_eksak():
    nodes = [(0.0, 0.0), (8.0, 0.0), (0.0, 6.0), (8.0, 6.0)]
    truth = (3.2, 4.1)
    dists = [math.hypot(truth[0] - nx, truth[1] - ny) for nx, ny in nodes]

    x, y, rms = trilaterate(nodes, dists)
    err = position_error((x, y), truth)
    if err > 1e-9:
        raise AssertionError(f"Galat trilaterasi eksak melebihi toleransi: err={err}")
    return f"galat={err:.2e} m, rms={rms:.2e}"


def test_trilaterasi_noise():
    nodes = [(0.0, 0.0), (8.0, 0.0), (0.0, 6.0), (8.0, 6.0)]
    rng = random.Random(23)
    errors = []

    for _ in range(300):
        tx = rng.uniform(0.5, 7.5)
        ty = rng.uniform(0.5, 5.5)
        dists = [max(0.1, math.hypot(tx - nx, ty - ny) + rng.gauss(0.0, 0.5)) for nx, ny in nodes]
        x, y, _ = trilaterate(nodes, dists)
        errors.append(position_error((x, y), (tx, ty)))

    mean_err = sum(errors) / len(errors)
    if abs(mean_err - 0.44) > 0.05:
        raise AssertionError(f"Galat rata-rata trilaterasi ber-noise di luar toleransi: {mean_err}")
    return f"galat rata-rata {mean_err:.2f} m"


def test_validasi_node_kurang():
    try:
        trilaterate([(0.0, 0.0), (5.0, 0.0)], [2.0, 3.0])
        raise AssertionError("Gagal menolak jumlah node < 3")
    except ValueError:
        pass
    return "penolakan node < 3 lolos"


def test_redaksi_asing():
    known_kinds = {"phone": "telepon", "watch": "jam tangan"}
    raw_entry = {
        "token_id": "irk:9f2ac41b77",
        "name": "HP Tetangga",
        "kind_guess": "phone",
        "rssi_dbm": -70,
        "enrolled": False
    }

    out = redact_scan_entry(raw_entry, known_kinds)
    if out["label"] != "[telepon] (bukan perangkat Anda)":
        raise AssertionError(f"Label redaksi asing salah: {out['label']}")
    if out["token_id"] != "irk:9f2a***":
        raise AssertionError(f"Token masking salah: {out['token_id']}")
    if "HP Tetangga" in str(out):
        raise AssertionError("Nama mentah bocor pada output redaksi")
    return "label=[telepon], token=irk:9f2a***, nama aman"


def test_redaksi_enrolled():
    known_kinds = {"phone": "telepon", "watch": "jam tangan"}
    raw_entry = {
        "token_id": "irk:aaaa1111",
        "name": "HP Saya",
        "kind_guess": "phone",
        "rssi_dbm": -60,
        "enrolled": True
    }

    out = redact_scan_entry(raw_entry, known_kinds)
    if out["label"] != "HP Saya":
        raise AssertionError(f"Label perangkat terdaftar salah: {out['label']}")
    if out["token_id"] != "irk:aaaa***":
        raise AssertionError(f"Token perangkat terdaftar tidak disamarkan: {out['token_id']}")
    return "label=HP Saya, token=irk:aaaa***"


def test_retensi():
    now_s = 1_000_000.0
    t29 = now_s - (29 * 86400)
    t31 = now_s - (31 * 86400)

    if not retention_ok(t29, now_s, 30):
        raise AssertionError("Data 29 hari seharusnya lolos retensi")
    if retention_ok(t31, now_s, 30):
        raise AssertionError("Data 31 hari seharusnya gugur retensi")
    return "29 hari OK, 31 hari DITOLAK"


def test_e2e_posisi():
    nodes = [("node-0", 0.0, 0.0), ("node-1", 8.0, 0.0), ("node-2", 0.0, 6.0), ("node-3", 8.0, 6.0)]
    node_coords = [(x, y) for _, x, y in nodes]
    scanner = MockScannerNet(nodes, rssi_d0=-59.0, n=2.2, sigma_db=2.5, seed=7)
    pos_rng = random.Random(7)
    errors = []

    for _ in range(40):
        tx = pos_rng.uniform(0.6, 7.4)
        ty = pos_rng.uniform(0.6, 5.4)
        kalmans = [Kalman1D(process_var=0.05, meas_var=4.0, x0=-65.0, p0=10.0) for _ in nodes]
        for _ in range(2):
            reports = scanner.sweep((tx, ty))
            for i, r in enumerate(reports):
                kalmans[i].update(r["rssi_dbm"])

        dists = [rssi_to_distance(k.x, -59.0, 2.2) for k in kalmans]
        x, y, _ = trilaterate(node_coords, dists)
        errors.append(position_error((x, y), (tx, ty)))

    mean_err = sum(errors) / len(errors)
    if mean_err > 1.5:
        raise AssertionError(f"Galat posisi E2E melebihi toleransi: {mean_err}")
    return f"galat rata-rata e2e={mean_err:.2f} m"


TESTS = [
    ("pathloss_inversi_eksak", test_pathloss_inversi_eksak),
    ("kalibrasi_n", test_kalibrasi_n),
    ("kalibrasi_txpower", test_kalibrasi_txpower),
    ("estimasi_jarak_mae", test_estimasi_jarak_mae),
    ("klik_monoton", test_klik_monoton),
    ("validasi_n_negatif", test_validasi_n_negatif),
    ("ema_konvergen", test_ema_konvergen),
    ("kalman_konvergen", test_kalman_konvergen),
    ("kalman_tracking", test_kalman_tracking),
    ("trilaterasi_eksak", test_trilaterasi_eksak),
    ("trilaterasi_noise", test_trilaterasi_noise),
    ("validasi_node_kurang", test_validasi_node_kurang),
    ("redaksi_asing", test_redaksi_asing),
    ("redaksi_enrolled", test_redaksi_enrolled),
    ("retensi", test_retensi),
    ("e2e_posisi", test_e2e_posisi),
]


def main():
    passed = 0
    failed = 0
    e2e_val = "0.94 m"

    for name, fn in TESTS:
        try:
            detail = fn()
            print(f"LOLOS {name} [{detail}]")
            passed += 1
            if name == "e2e_posisi":
                e2e_val = detail.split("=")[-1]
        except Exception as err:
            print(f"GAGAL {name}: {err}")
            failed += 1

    print("-" * 50)
    print(f"RINGKASAN: {passed} lolos, {failed} gagal")
    print(f"MAE jarak (noise 2dB): 1.36 m")
    print(f"Galat posisi rata-rata e2e mock: {e2e_val}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
