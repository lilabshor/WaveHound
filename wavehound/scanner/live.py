"""Pemindai Bluetooth Low Energy (BLE) perangkat keras fisik secara langsung (Real-Time)."""

import asyncio
import time
from typing import Callable

from wavehound.core.filters import EMA
from wavehound.core.privacy import mask_token, redact_scan_entry
from wavehound.core.rssi_model import click_rate_hz, rssi_to_distance


# Bluetooth SIG Manufacturer Identifiers penting
APPLE_COMPANY_ID = 0x004C
GOOGLE_COMPANY_ID = 0x00E0
SAMSUNG_COMPANY_ID = 0x0075
MICROSOFT_COMPANY_ID = 0x0006
XIAOMI_COMPANY_ID = 0x038F
OPPO_COMPANY_ID = 0x015D
VIVO_COMPANY_ID = 0x02E5
GARMIN_COMPANY_ID = 0x0087
HUAWEI_COMPANY_ID = 0x0822

VENDOR_BRANDS = {
    APPLE_COMPANY_ID: "Apple iPhone / iOS",
    SAMSUNG_COMPANY_ID: "Samsung Galaxy / Android",
    GOOGLE_COMPANY_ID: "Google Pixel / Android",
    XIAOMI_COMPANY_ID: "Xiaomi / Redmi",
    OPPO_COMPANY_ID: "OPPO / Realme",
    VIVO_COMPANY_ID: "Vivo Phone",
    MICROSOFT_COMPANY_ID: "Microsoft Windows Device",
    GARMIN_COMPANY_ID: "Garmin Smartwatch",
    HUAWEI_COMPANY_ID: "Huawei Device",
}


def guess_device_brand(adv_data) -> str:
    """Mendeteksi merek perangkat dari Manufacturer Specific Data atau nama siaran."""
    mfg = adv_data.manufacturer_data or {}
    for cid, brand in VENDOR_BRANDS.items():
        if cid in mfg:
            return brand

    if adv_data.local_name:
        name_clean = adv_data.local_name.strip()
        if len(name_clean) > 1:
            return f"Perangkat: {name_clean}"

    return "Ponsel / BLE Device"


def guess_device_kind(adv_data) -> str:
    """Menebak jenis perangkat berdasarkan struktur AD dan manufacturer ID."""
    mfg = adv_data.manufacturer_data or {}
    if APPLE_COMPANY_ID in mfg or GOOGLE_COMPANY_ID in mfg or SAMSUNG_COMPANY_ID in mfg:
        return "phone"
    elif adv_data.local_name:
        name_lower = adv_data.local_name.lower()
        if "watch" in name_lower or "band" in name_lower:
            return "watch"
        if "phone" in name_lower or "iphone" in name_lower:
            return "phone"
        if "laptop" in name_lower or "pc" in name_lower:
            return "laptop"
    return "phone"


async def live_survey_scan(timeout: float = 4.0) -> list[dict]:
    """Memindai udara secara pasif selama 'timeout' detik dan mengembalikan daftar perangkat nyata."""
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []

    for dev, adv in devices.values():
        kind = guess_device_kind(adv)
        brand = guess_device_brand(adv)
        name = dev.name or adv.local_name
        is_apple = APPLE_COMPANY_ID in (adv.manufacturer_data or {})

        if not name and is_apple:
            name = brand
        elif not name:
            name = brand

        results.append({
            "token_id": dev.address,
            "name": name,
            "kind_guess": kind,
            "brand_guess": brand,
            "rssi_dbm": int(adv.rssi),
            "enrolled": False,
            "is_apple": is_apple,
        })

    results.sort(key=lambda x: x["rssi_dbm"], reverse=True)
    return results


class LiveHunter:
    """Pelacak sinyal Bluetooth fisik secara kontinu dengan umpan balik audio frekuensi dinamis."""

    def __init__(
        self,
        target_identifier: str,
        sound: bool = True,
        tx_power: float = -59.0,
        n_exponent: float = 2.2,
        stale_timeout_s: float = 5.0
    ):
        self.target = target_identifier.lower()
        self.sound = sound
        self.tx_power = tx_power
        self.n_exponent = n_exponent
        self.stale_timeout_s = stale_timeout_s

        self.ema = EMA(alpha=0.30)
        self.last_seen_time = 0.0
        self.is_running = False

    def _matches_target(self, address: str, name: str | None, adv_data) -> bool:
        addr = address.lower()
        if addr == self.target or self.target in addr:
            return True

        if name and (self.target in name.lower() or name.lower() in self.target):
            return True

        m_data = adv_data.manufacturer_data or {}

        # Apple / iPhone
        if any(k in self.target for k in ("iphone", "apple", "ios")):
            if APPLE_COMPANY_ID in m_data:
                return True

        # Samsung
        if "samsung" in self.target and 0x0075 in m_data:
            return True

        # Google / Pixel
        if any(k in self.target for k in ("google", "pixel")) and 0x00E0 in m_data:
            return True

        # Xiaomi
        if "xiaomi" in self.target and 0x038F in m_data:
            return True

        return False

    async def run(self, on_update: Callable[[float, float, float, float, int, str, bool], None]):
        from bleak import BleakScanner

        self.is_running = True
        self.last_seen_time = time.time()
        packet_count = 0
        stale_alerted = False

        def detection_callback(device, adv_data):
            nonlocal packet_count, stale_alerted
            if not self.is_running:
                return

            if self._matches_target(device.address, device.name or adv_data.local_name, adv_data):
                packet_count += 1
                self.last_seen_time = time.time()
                stale_alerted = False

                raw_rssi = float(adv_data.rssi)
                smooth_rssi = self.ema.update(raw_rssi)
                dist_m = rssi_to_distance(smooth_rssi, self.tx_power, self.n_exponent)
                click_hz = click_rate_hz(smooth_rssi)

                on_update(raw_rssi, smooth_rssi, dist_m, click_hz, packet_count, device.address, False)

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()

        try:
            while self.is_running:
                await asyncio.sleep(0.5)
                now = time.time()
                if self.last_seen_time > 0 and (now - self.last_seen_time) > self.stale_timeout_s:
                    if not stale_alerted and self.ema.value is not None:
                        stale_alerted = True
                        dist_m = rssi_to_distance(self.ema.value, self.tx_power, self.n_exponent)
                        on_update(self.ema.value, self.ema.value, dist_m, 0.0, packet_count, "", True)
        finally:
            await scanner.stop()

    def stop(self):
        self.is_running = False
