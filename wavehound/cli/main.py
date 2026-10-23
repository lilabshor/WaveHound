

import argparse
import asyncio
import math
import os
import sys
import time

from wavehound.core.filters import EMA
from wavehound.core.privacy import mask_token, redact_scan_entry
from wavehound.core.rssi_model import click_rate_hz, rssi_to_distance, calibrate
from wavehound.core.audio import play_click
from wavehound.db.connection import Database
from wavehound.scanner.live import live_survey_scan, LiveHunter


KNOWN_KINDS = {
    "phone": "telepon",
    "watch": "jam tangan",
    "laptop": "laptop",
    "beacon": "suar",
}


def render_bar(rssi: float, r_min: float = -90.0, r_max: float = -40.0, width: int = 24) -> str:
    """Menggambar batang visual sinyal ASCII."""
    clamped = max(r_min, min(r_max, rssi))
    ratio = (clamped - r_min) / (r_max - r_min)
    hashes = int(round(ratio * width))
    dashes = width - hashes
    return f"[{'#' * hashes}{'-' * dashes}]"


def run_survey(redact: bool = False, use_mock: bool = False, timeout: float = 3.5, db: Database | None = None):
    print("MODE SURVEY - Memindai sinyal radio Bluetooth di sekitar...")

    enrolled_secrets = set()
    enrolled_names = {}
    if db:
        try:
            conn = db.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT identity_secret, label FROM devices_enrolled WHERE status='active'")
            for r in cursor.fetchall():
                sec = r["identity_secret"] if hasattr(r, "keys") else r[0]
                lbl = r["label"] if hasattr(r, "keys") else r[1]
                enrolled_secrets.add(sec.lower())
                enrolled_names[sec.lower()] = lbl
            conn.close()
        except Exception:
            pass

    raw_samples = []

    if not use_mock:
        try:
            raw_samples = asyncio.run(live_survey_scan(timeout=timeout))
        except Exception as e:
            print(f"[Info] Pemindaian hardware gagal ({e}), beralih ke mode simulasi.")
            use_mock = True

    if use_mock or not raw_samples:
        if not use_mock and not raw_samples:
            print("[Info] Tidak ada sinyal tertangkap di udara, menampilkan data simulasi.")
        raw_samples = [
            {"token_id": "irk:9f2ac41b77aa", "name": "iPhone Kantor", "kind_guess": "phone", "rssi_dbm": -62, "enrolled": True},
            {"token_id": "irk:55bc00de12ff", "name": "HP Tamu Lantai 3", "kind_guess": "phone", "rssi_dbm": -78, "enrolled": False},
            {"token_id": "irk:77aa99bb1100", "name": "Smartwatch Anonim", "kind_guess": "watch", "rssi_dbm": -84, "enrolled": False},
        ]

    # Cocokkan status pendaftaran dengan database lokal
    for s in raw_samples:
        t_id = str(s.get("token_id", "")).lower()
        is_apple = bool(s.get("is_apple", False))
        matched = False
        for sec in enrolled_secrets:
            if (sec in ("apple", "iphone", "ios") and is_apple) or (sec == t_id or sec in t_id or t_id in sec):
                s["enrolled"] = True
                s["name"] = enrolled_names.get(sec, s.get("name"))
                matched = True
                break
        if not matched and not s.get("enrolled"):
            s["enrolled"] = False

    raw_samples.sort(key=lambda x: x["rssi_dbm"], reverse=True)

    print(f"\nDitemukan {len(raw_samples)} perangkat di udara:")
    for item in raw_samples:
        rssi = item["rssi_dbm"]
        bar = render_bar(rssi)

        if redact:
            redacted = redact_scan_entry(item, KNOWN_KINDS)
            ownership = "[milik Anda]" if redacted["enrolled"] else ""
            print(f" {rssi:3d} dBm  {bar}  {redacted['label']} {ownership}".rstrip())
        else:
            ownership = "[milik Anda]" if item["enrolled"] else ""
            name_label = item.get("name") or mask_token(item["token_id"])
            print(f" {rssi:3d} dBm  {bar}  {name_label} {ownership}".rstrip())
    print()


def run_hunt(target_name: str, sound: bool = False, use_mock: bool = False, db: Database | None = None):
    print(f"MODE HUNT - Melacak perangkat: '{target_name}'")
    print("Tekan Ctrl+C untuk menghentikan pelacakan.")
    print("Panduan: Berjalan perlahan, percayai tren perubahan sinyal.\n")

    tx_power = -59.0
    n_exponent = 2.2

    # Cari apakah target terdaftar di database untuk mengambil token / address
    target_identifier = target_name
    if db:
        try:
            conn = db.connect()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT identity_secret, label FROM devices_enrolled WHERE (LOWER(label)=LOWER(?) OR LOWER(label) LIKE LOWER(?)) AND status='active'",
                (target_name, f"%{target_name}%")
            )
            row = cursor.fetchone()
            if row:
                target_identifier = row["identity_secret"] if hasattr(row, "keys") else row[0]
                target_name = row["label"] if hasattr(row, "keys") else row[1]
            conn.close()
        except Exception:
            pass

    if not use_mock:
        hunter = LiveHunter(
            target_identifier=target_identifier,
            sound=sound,
            tx_power=tx_power,
            n_exponent=n_exponent
        )

        def on_update(raw_rssi: float, smooth_rssi: float, dist_m: float, click_hz: float, pkt_num: int, addr: str, is_stale: bool):
            bar = render_bar(smooth_rssi)
            if is_stale:
                print(f"[!] Sinyal terputus / berhenti memancar > 5 detik (menunggu pulsa siaran berikutnya...)")
            else:
                click_str = f"klik {click_hz:4.1f}/dtk"
                click_label = "KLIK" if sound else ""
                masked_addr = f"[{addr[:8]}***]" if addr else ""
                print(f"#{pkt_num:<3d} rssi={raw_rssi:4.0f} dBm (halus={smooth_rssi:5.1f}) jarak~ {dist_m:4.1f} m  {click_str} {click_label:4s} {bar} {masked_addr}".rstrip())
                if sound:
                    play_click()

        try:
            print(f"[Live] Antena Bluetooth aktif mendengarkan '{target_name}'...")
            asyncio.run(hunter.run(on_update))
        except KeyboardInterrupt:
            hunter.stop()
            print("\nPelacakan langsung dihentikan oleh operator.")
            return
        except Exception as e:
            print(f"[Info] Pelacakan live hardware terkendala ({e}), beralih ke simulasi.\n")
            use_mock = True

    if use_mock:
        ema = EMA(alpha=0.25)
        synthetic_trace = [
            -80.5, -79.8, -78.9, -77.6, -76.3, -74.6, -73.1, -71.2,
            -69.5, -67.5, -65.8, -63.7, -61.9, -59.8, -58.0, -55.9, -54.0
        ]
        try:
            for raw_rssi in synthetic_trace:
                smooth_rssi = ema.update(raw_rssi)
                dist_m = rssi_to_distance(smooth_rssi, tx_power, n_exponent)
                click_hz = click_rate_hz(smooth_rssi)
                bar = render_bar(smooth_rssi)

                click_label = "KLIK" if sound else ""
                print(
                    f"rssi={smooth_rssi:6.1f} dBm  jarak~ {dist_m:4.1f} m  "
                    f"klik {click_hz:4.1f}/detik {click_label:4s} {bar}"
                )

                if sound:
                    play_click()

                time.sleep(0.4)

            print("\nTarget terdeteksi dalam jangkauan fisik sangat dekat (< 1 meter).")
        except KeyboardInterrupt:
            print("\nPelacakan simulasi dihentikan oleh operator.")


def run_list(db: Database | None = None):
    print("PERINGATAN: Daftar ini memuat inventaris internal. Tidak aman difilmkan / disebarkan.")
    database = db or Database(db_type="sqlite", path="wavehound.db")
    conn = database.connect()
    database.init_schema(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT id, label, identity_type, identity_secret, enrolled_at FROM devices_enrolled WHERE status='active'")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("Belum ada perangkat yang terdaftar.")
        return

    print(f"{'ID':<16} {'LABEL':<24} {'TIPE':<16} {'TOKEN/SECRET':<18} {'ENROLLED AT'}")
    print("-" * 85)
    for r in rows:
        dev_id = r["id"] if hasattr(r, "keys") else r[0]
        label = r["label"] if hasattr(r, "keys") else r[1]
        itype = r["identity_type"] if hasattr(r, "keys") else r[2]
        secret = r["identity_secret"] if hasattr(r, "keys") else r[3]
        at = r["enrolled_at"] if hasattr(r, "keys") else r[4]
        print(f"{dev_id:<16} {label:<24} {itype:<16} {mask_token(secret):<18} {at}")


def run_enroll(name: str, id_type: str, secret: str, db: Database | None = None):
    database = db or Database(db_type="sqlite", path="wavehound.db")
    conn = database.connect()
    database.init_schema(conn)

    dev_id = f"dev_{int(time.time())}"
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    cursor = conn.cursor()
    cursor.execute("DELETE FROM devices_enrolled WHERE site_id='default_site' AND label=?", (name,))
    cursor.execute(
        """INSERT INTO devices_enrolled 
           (id, site_id, label, owner_ref, identity_type, identity_secret, enrolled_at, enrolled_by, consent_ref, status)
           VALUES (?, 'default_site', ?, 'admin', ?, ?, ?, 'cli_user', 'manual_cli_consent', 'active')""",
        (dev_id, name, id_type, secret, now_str)
    )
    conn.commit()
    database.append_audit(conn, "cli_user", "device.enroll", dev_id, {"label": name, "identity_type": id_type})
    conn.close()

    print(f"Perangkat '{name}' berhasil didaftarkan (ID: {dev_id}).")
    print(f"Token identitas: {mask_token(secret)}")


def run_calibrate(points: int = 5):
    print(f"WIZARD KALIBRASI RUANGAN - {points} Titik Pengukuran")
    print("Letakkan pemancar acuan pada jarak-jarak yang telah diukur dengan meteran.\n")

    samples = [
        (1.0, -59.2),
        (2.0, -66.1),
        (3.0, -70.4),
        (4.5, -74.8),
        (8.0, -80.9),
    ][:points]

    for d, r in samples:
        print(f" Titik d = {d:4.1f} meter -> terukur RSSI = {r:5.1f} dBm")

    n_est, tx_est = calibrate(samples)
    print("\n--- HASIL KALIBRASI REGRESI LINIER ---")
    print(f" Parameter n (eksponen path loss) : {n_est:.3f}")
    print(f" Parameter TxPower @ 1m (rssi_d0) : {tx_est:.2f} dBm")
    print("Gunakan parameter ini pada konfigurasi ruangan gedung Anda.\n")


def main():
    parser = argparse.ArgumentParser(
        prog="wavehound",
        description="WaveHound: Sistem Pelacak Perangkat Hilang Indoor Berbasis Bluetooth RSSI"
    )

    parser.add_argument("--survey", action="store_true", help="Pindai perangkat di sekitar dan urutkan berdasar RSSI")
    parser.add_argument("--hunt", type=str, metavar="NAMA", help="Lacak satu perangkat terdaftar secara kontinu")
    parser.add_argument("--sound", action="store_true", help="Nyalakan bunyi klik audio pada mode hunt")
    parser.add_argument("--redact", action="store_true", help="Samarkan identitas perangkat asing pada keluaran")
    parser.add_argument("--list", action="store_true", help="Tampilkan daftar perangkat terdaftar")
    parser.add_argument("--mock", action="store_true", help="Gunakan data simulasi sintetis alih-alih radio fisik")
    parser.add_argument("--timeout", type=float, default=3.5, help="Durasi pemindaian survey (detik)")

    subparsers = parser.add_subparsers(dest="subcommand")

    # Subcommand enroll
    enroll_parser = subparsers.add_parser("enroll", help="Daftarkan perangkat baru")
    enroll_parser.add_argument("--name", required=True, help="Nama atau label perangkat")
    enroll_parser.add_argument("--type", default="companion_token", choices=["irk", "companion_token", "mdm"], help="Jenis identitas")
    enroll_parser.add_argument("--secret", required=True, help="Kunci rahasia / UUID / Alamat perangkat")

    # Subcommand calibrate
    cal_parser = subparsers.add_parser("calibrate", help="Kalibrasi parameter radio gedung")
    cal_parser.add_argument("--points", type=int, default=5, help="Jumlah titik sampel kalibrasi")

    args = parser.parse_args()

    db = Database(db_type="sqlite", path="wavehound.db")

    if args.subcommand == "enroll":
        run_enroll(args.name, args.type, args.secret, db=db)
    elif args.subcommand == "calibrate":
        run_calibrate(args.points)
    elif args.survey:
        run_survey(redact=args.redact, use_mock=args.mock, timeout=args.timeout, db=db)
    elif args.hunt:
        run_hunt(args.hunt, sound=args.sound, use_mock=args.mock, db=db)
    elif args.list:
        run_list(db=db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
