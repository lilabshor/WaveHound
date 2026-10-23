"""Modul manajemen database WaveHound."""

import os
from wavehound.db.connection import Database

SCHEMA_SQL_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

__all__ = ["Database", "SCHEMA_SQL_PATH"]
