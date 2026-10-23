

import time
from wavehound.core.filters import Kalman1D
from wavehound.core.rssi_model import rssi_to_distance
from wavehound.core.trilateration import trilaterate


class SignalPipeline:


    def __init__(self, default_tx: float = -59.0, default_n: float = 2.2):
        self.default_tx = default_tx
        self.default_n = default_n
        # key: (device_id, node_id) -> Kalman1D
        self.kalman_states: dict[tuple[str, str], Kalman1D] = {}
        # key: device_id -> dict[node_id, (timestamp, distance, rssi_smooth)]
        self.recent_distances: dict[str, dict[str, tuple[float, float, float]]] = {}
        # Node metadata: node_id -> (x, y, floor)
        self.node_positions: dict[str, tuple[float, float, int]] = {}

    def register_node(self, node_id: str, x: float, y: float, floor: int = 1):
        self.node_positions[node_id] = (x, y, floor)

    def process_reading(
        self,
        node_id: str,
        device_id: str,
        raw_rssi: float,
        timestamp: float | None = None,
        tx_hint: float | None = None,
        n_hint: float | None = None
    ) -> dict:
        """Memproses satu pembacaan RSSI dan memperbarui posisi jika titik memenuhi syarat."""
        now = timestamp or time.time()
        tx = tx_hint if tx_hint is not None else self.default_tx
        n = n_hint if n_hint is not None else self.default_n

        pair_key = (device_id, node_id)
        if pair_key not in self.kalman_states:
            self.kalman_states[pair_key] = Kalman1D(process_var=0.05, meas_var=4.0, x0=raw_rssi)

        kalman = self.kalman_states[pair_key]
        rssi_smooth = kalman.update(raw_rssi)
        dist_m = rssi_to_distance(rssi_smooth, tx, n)

        if device_id not in self.recent_distances:
            self.recent_distances[device_id] = {}
        self.recent_distances[device_id][node_id] = (now, dist_m, rssi_smooth)


        obs_nodes = []
        obs_dists = []
        target_floor = None

        cutoff = now - 10.0
        for nid, (seen_time, d, _) in self.recent_distances[device_id].items():
            if seen_time >= cutoff and nid in self.node_positions:
                nx, ny, floor = self.node_positions[nid]
                if target_floor is None:
                    target_floor = floor
                obs_nodes.append((nx, ny))
                obs_dists.append(d)

        result = {
            "device_id": device_id,
            "node_id": node_id,
            "rssi_raw": raw_rssi,
            "rssi_smooth": round(rssi_smooth, 2),
            "distance_m": round(dist_m, 2),
            "position": None
        }

        if len(obs_nodes) >= 3:
            try:
                x, y, rms = trilaterate(obs_nodes, obs_dists)
                confidence = "high" if rms < 4.0 else ("medium" if rms < 12.0 else "low")
                result["position"] = {
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "floor": target_floor or 1,
                    "confidence": confidence,
                    "residual": round(rms, 3),
                    "node_count": len(obs_nodes)
                }
            except Exception:

                result["position"] = None

        return result
