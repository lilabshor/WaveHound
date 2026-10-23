"""Simulator jaringan pemindai Bluetooth LE untuk pengujian deterministik tanpa hardware."""

import math
import random
import time
from wavehound.core.rssi_model import distance_to_rssi


class MockScannerNet:
    """Simulator jaringan sensor n-node di posisi tetap dengan interferensi realistis."""

    def __init__(
        self,
        nodes: list[tuple[str, float, float]],
        rssi_d0: float = -59.0,
        n: float = 2.2,
        sigma_db: float = 2.5,
        seed: int = 7
    ):
        self.nodes = nodes
        self.rssi_d0 = rssi_d0
        self.n = n
        self.sigma = sigma_db
        self.rng = random.Random(seed)
        self.t = 0

    def sweep(
        self,
        target_xy: tuple[float, float],
        token: str = "dev:enrolled-01"
    ) -> list[dict]:
        """Menjalankan satu siklus pemindaian serentak dari semua node terhadap koordinat target."""
        self.t += 1
        ts = int(time.time() * 1000) + self.t
        out = []

        for nid, nx, ny in self.nodes:
            d = max(0.3, math.hypot(target_xy[0] - nx, target_xy[1] - ny))
            rssi = distance_to_rssi(d, self.rssi_d0, self.n)
            rssi += self.rng.gauss(0.0, self.sigma)
            out.append({
                "node_id": nid,
                "timestamp_ms": ts,
                "token_id": token,
                "rssi_dbm": round(rssi, 1),
            })

        return out
