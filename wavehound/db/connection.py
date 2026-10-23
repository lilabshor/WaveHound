"""Manajer koneksi dan repositori database relasional (MySQL / SQLite)."""

import hashlib
import json
import sqlite3
import time
from typing import Any


class Database:
    """Abstraksi database WaveHound dengan dukungan MySQL dan SQLite."""

    def __init__(self, db_type: str = "sqlite", **kwargs):
        self.db_type = db_type.lower()
        self.kwargs = kwargs
        self._conn = None

    def connect(self):
        if self.db_type == "sqlite":
            path = self.kwargs.get("path", ":memory:")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            # Aktifkan Foreign Keys di SQLite
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn
        elif self.db_type == "mysql":
            try:
                import pymysql
                return pymysql.connect(
                    host=self.kwargs.get("host", "127.0.0.1"),
                    user=self.kwargs.get("user", "root"),
                    password=self.kwargs.get("password", ""),
                    database=self.kwargs.get("database", "wavehound"),
                    port=self.kwargs.get("port", 3306),
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=True
                )
            except ImportError:
                raise RuntimeError("Library pymysql belum terpasang. Jalankan: pip install pymysql")
        else:
            raise ValueError(f"Tipe database '{self.db_type}' tidak didukung")

    def init_schema(self, conn=None):
        """Mengeksekusi skema tabel awal."""
        should_close = False
        if conn is None:
            conn = self.connect()
            should_close = True

        cursor = conn.cursor()
        
        # SQLite vs MySQL statement handling
        if self.db_type == "sqlite":
            # Ganti dialek MySQL auto_increment ke SQLite AUTOINCREMENT jika perlu
            statements = [
                """CREATE TABLE IF NOT EXISTS sites (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );""",
                """CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    z REAL NOT NULL,
                    floor INTEGER NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_seen_at TEXT,
                    created_at TEXT NOT NULL
                );""",
                """CREATE TABLE IF NOT EXISTS devices_enrolled (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    identity_type TEXT NOT NULL,
                    identity_secret TEXT NOT NULL,
                    enrolled_at TEXT NOT NULL,
                    enrolled_by TEXT NOT NULL,
                    consent_ref TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE (site_id, label)
                );""",
                """CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL REFERENCES devices_enrolled(id) ON DELETE CASCADE,
                    opened_by TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    closed_at TEXT,
                    note TEXT
                );""",
                """CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    device_id TEXT REFERENCES devices_enrolled(id) ON DELETE SET NULL,
                    seen_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    rssi INTEGER NOT NULL,
                    rssi_smooth REAL,
                    distance_m REAL,
                    channel INTEGER
                );""",
                """CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    device_id TEXT NOT NULL REFERENCES devices_enrolled(id) ON DELETE CASCADE,
                    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    estimated_at TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    floor INTEGER NOT NULL,
                    confidence TEXT NOT NULL,
                    residual REAL NOT NULL,
                    node_count INTEGER NOT NULL
                );""",
                """CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ref_id TEXT,
                    created_at TEXT NOT NULL,
                    acked_by TEXT,
                    acked_at TEXT
                );""",
                """CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );""",
                """CREATE TABLE IF NOT EXISTS roles (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    PRIMARY KEY (user_id, site_id, role)
                );""",
                """CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_ref TEXT,
                    detail TEXT,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );"""
            ]
            for stmt in statements:
                cursor.execute(stmt)

            # Pastikan site default tersedia untuk foreign key constraint
            cursor.execute("SELECT id FROM sites WHERE id='default_site'")
            if not cursor.fetchone():
                now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                cursor.execute("INSERT INTO sites (id, name, created_at) VALUES ('default_site', 'Gedung Utama', ?)", (now_str,))

            conn.commit()
        else:
            # MySQL execution
            from wavehound.db import SCHEMA_SQL_PATH
            with open(SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            for stmt in content.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)

            cursor.execute("SELECT id FROM sites WHERE id='default_site'")
            if not cursor.fetchone():
                now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                cursor.execute("INSERT INTO sites (id, name, created_at) VALUES ('default_site', 'Gedung Utama', %s)", (now_str,))
            conn.commit()

        if should_close:
            conn.close()

    def append_audit(
        self,
        conn,
        actor_id: str,
        action: str,
        target_ref: str | None = None,
        detail: dict | None = None
    ) -> str:
        """Menulis catatan audit baru dengan tautan hash SHA-256 (tamper-evident)."""
        cursor = conn.cursor()
        
        # Ambil hash entri terakhir
        cursor.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        prev_hash = row[0] if (row and isinstance(row, tuple)) else (row["entry_hash"] if row else "0" * 64)

        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        detail_json = json.dumps(detail or {}, sort_keys=True)

        payload = f"{prev_hash}|{now_str}|{actor_id}|{action}|{target_ref or ''}|{detail_json}"
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        if self.db_type == "sqlite":
            cursor.execute(
                """INSERT INTO audit_log (at, actor_id, action, target_ref, detail, prev_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (now_str, actor_id, action, target_ref, detail_json, prev_hash, entry_hash)
            )
        else:
            cursor.execute(
                """INSERT INTO audit_log (at, actor_id, action, target_ref, detail, prev_hash, entry_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (now_str, actor_id, action, target_ref, detail_json, prev_hash, entry_hash)
            )

        conn.commit()
        return entry_hash
