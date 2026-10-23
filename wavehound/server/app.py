"""Server pusat WaveHound berbasis HTTP REST API murni (zero-dependency stdlib)."""

import json
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from wavehound.db.connection import Database
from wavehound.server.pipeline import SignalPipeline
from wavehound.core.privacy import mask_token


class WaveHoundHandler(BaseHTTPRequestHandler):
    pipeline: SignalPipeline = None
    db: Database = None

    def log_message(self, format, *args):
        # Format logging ringkas tanpa spam
        pass

    def _send_json(self, status: int, data: dict | list):
        self.close_connection = True
        try:
            payload = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/healthz":
            self._send_json(200, {"status": "ok", "service": "WaveHound Engine", "time": time.time()})
            return

        if path == "/api/v1/devices":
            conn = self.db.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT id, site_id, label, owner_ref, identity_type, identity_secret, enrolled_at FROM devices_enrolled WHERE status='active'")
            rows = cursor.fetchall()
            devices = []
            for r in rows:
                row_dict = dict(r) if hasattr(r, "keys") else {
                    "id": r[0], "site_id": r[1], "label": r[2], "owner_ref": r[3],
                    "identity_type": r[4], "identity_secret": r[5], "enrolled_at": r[6]
                }
                row_dict["identity_secret"] = mask_token(row_dict["identity_secret"])
                devices.append(row_dict)
            conn.close()
            self._send_json(200, {"devices": devices})
            return

        if path == "/api/v1/positions/latest":
            dev_id = query.get("device_id", [None])[0]
            if not dev_id:
                self._send_json(400, {"error": "parameter device_id wajib disertakan"})
                return

            conn = self.db.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets WHERE device_id=? AND status='open'", (dev_id,))
            ticket = cursor.fetchone()
            if not ticket:
                conn.close()
                self._send_json(403, {"error": "Akses ditolak: pencarian posisi wajib terikat tiket laporan kehilangan aktif"})
                return

            cursor.execute("SELECT * FROM positions WHERE device_id=? ORDER BY id DESC LIMIT 1", (dev_id,))
            pos_row = cursor.fetchone()
            conn.close()

            if not pos_row:
                self._send_json(404, {"error": "Posisi perangkat belum terdeteksi oleh 3 node"})
                return

            pos_data = dict(pos_row) if hasattr(pos_row, "keys") else {
                "id": pos_row[0], "site_id": pos_row[1], "device_id": pos_row[2],
                "ticket_id": pos_row[3], "estimated_at": pos_row[4], "x": pos_row[5],
                "y": pos_row[6], "floor": pos_row[7], "confidence": pos_row[8],
                "residual": pos_row[9], "node_count": pos_row[10]
            }
            self._send_json(200, pos_data)
            return

        self._send_json(404, {"error": "Endpoint tidak ditemukan"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype and body:
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "JSON tidak valid"})
                return
        elif "application/x-www-form-urlencoded" in ctype and body:
            data = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8")).items()}
        else:
            data = {}

        if path == "/api/v1/devices":
            label = data.get("label")
            secret = data.get("identity_secret")
            id_type = data.get("identity_type", "companion_token")
            owner = data.get("owner_ref", "anonymous")
            consent = data.get("consent_ref", "explicit_consent")

            if not label or not secret:
                self._send_json(400, {"error": "label dan identity_secret wajib diisi"})
                return

            dev_id = f"dev_{int(time.time())}_{abs(hash(label)) % 10000}"
            now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            conn = self.db.connect()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM devices_enrolled WHERE site_id='default_site' AND label=?", (label,))
                cursor.execute(
                    """INSERT INTO devices_enrolled 
                       (id, site_id, label, owner_ref, identity_type, identity_secret, enrolled_at, enrolled_by, consent_ref, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                    (dev_id, "default_site", label, owner, id_type, secret, now_str, "system", consent)
                )
                conn.commit()
                self.db.append_audit(conn, "system", "device.enroll", dev_id, {"label": label, "consent": consent})
                conn.close()
                self._send_json(201, {"status": "enrolled", "device_id": dev_id, "label": label})
            except Exception as e:
                conn.close()
                self._send_json(409, {"error": f"Pendaftaran gagal: {e}"})
            return

        if path == "/api/v1/tickets":
            dev_id = data.get("device_id")
            note = data.get("note", "Laporan kehilangan dari operator")
            if not dev_id:
                self._send_json(400, {"error": "device_id wajib disertakan"})
                return

            ticket_id = f"tick_{int(time.time())}"
            now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            conn = self.db.connect()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO tickets (id, site_id, device_id, opened_by, opened_at, status, note)
                   VALUES (?, ?, ?, ?, ?, 'open', ?)""",
                (ticket_id, "default_site", dev_id, "operator", now_str, note)
            )
            conn.commit()
            self.db.append_audit(conn, "operator", "ticket.open", ticket_id, {"device_id": dev_id})
            conn.close()
            self._send_json(201, {"ticket_id": ticket_id, "status": "open", "device_id": dev_id})
            return

        if path == "/api/v1/ingest":
            node_id = data.get("node_id", "node-unknown")
            readings = data.get("readings", [])

            conn = self.db.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT id, identity_secret FROM devices_enrolled WHERE status='active'")
            enrolled = {r["identity_secret"]: r["id"] for r in cursor.fetchall()} if hasattr(cursor, "fetchall") else {}

            now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            processed_count = 0

            for r in readings:
                adv_id = r.get("adv_id", "")
                rssi = float(r.get("rssi", -99))

                matched_device_id = None
                for secret, did in enrolled.items():
                    if secret in adv_id or adv_id in secret:
                        matched_device_id = did
                        break

                res = self.pipeline.process_reading(
                    node_id=node_id,
                    device_id=matched_device_id or "anonymous",
                    raw_rssi=rssi
                )

                cursor.execute(
                    """INSERT INTO readings (site_id, node_id, device_id, seen_at, received_at, rssi, rssi_smooth, distance_m, channel)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("default_site", node_id, matched_device_id, r.get("seen_at", now_str), now_str,
                     int(rssi), res["rssi_smooth"], res["distance_m"], r.get("channel", 37))
                )

                if matched_device_id and res.get("position"):
                    pos = res["position"]
                    cursor.execute("SELECT id FROM tickets WHERE device_id=? AND status='open'", (matched_device_id,))
                    trow = cursor.fetchone()
                    ticket_id = trow["id"] if trow else "none"

                    cursor.execute(
                        """INSERT INTO positions (site_id, device_id, ticket_id, estimated_at, x, y, floor, confidence, residual, node_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        ("default_site", matched_device_id, ticket_id, now_str, pos["x"], pos["y"], pos["floor"],
                         pos["confidence"], pos["residual"], pos["node_count"])
                    )

                processed_count += 1

            conn.commit()
            conn.close()
            self._send_json(202, {"status": "accepted", "readings_processed": processed_count})
            return

        self._send_json(404, {"error": "Endpoint tidak ditemukan"})


def run_server(host: str = "0.0.0.0", port: int = 8080, db: Database | None = None):
    database = db or Database(db_type="sqlite", path="wavehound.db")
    conn = database.connect()
    database.init_schema(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sites WHERE id='default_site'")
    if not cursor.fetchone():
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cursor.execute("INSERT INTO sites (id, name, created_at) VALUES ('default_site', 'Gedung Utama', ?)", (now_str,))
        conn.commit()
    conn.close()

    pipeline = SignalPipeline()
    pipeline.register_node("node-01", 0.0, 0.0, floor=1)
    pipeline.register_node("node-02", 8.0, 0.0, floor=1)
    pipeline.register_node("node-03", 0.0, 6.0, floor=1)
    pipeline.register_node("node-04", 8.0, 6.0, floor=1)

    WaveHoundHandler.db = database
    WaveHoundHandler.pipeline = pipeline

    server = ThreadingHTTPServer((host, port), WaveHoundHandler)
    print(f"WaveHound REST API Server aktif di http://{host}:{port}")
    print("Endpoint tersedia:")
    print("  GET  /healthz")
    print("  GET  /api/v1/devices")
    print("  POST /api/v1/devices")
    print("  POST /api/v1/tickets")
    print("  GET  /api/v1/positions/latest?device_id=...")
    print("  POST /api/v1/ingest")
    print("Tekan Ctrl+C untuk menghentikan server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMematikan server WaveHound...")
        server.server_close()


if __name__ == "__main__":
    run_server()
