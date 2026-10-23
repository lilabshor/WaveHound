"""Mekanisme Privacy by Design: redaksi data perangkat asing, masking token, dan retensi."""


def mask_token(token: str) -> str:
    """Menyamarkan token identitas dengan hanya mengekspos 4 karakter awal."""
    head, _, tail = token.partition(":")
    if not tail:
        return head[:4] + "***"
    return head + ":" + tail[:4] + "***"


def redact_scan_entry(entry: dict, known_kinds: dict[str, str]) -> dict:
    """Menerapkan filter allowlist redaksi pada satu entri hasil pindaian BLE."""
    is_enrolled = bool(entry.get("enrolled"))
    out = {
        "rssi_dbm": entry["rssi_dbm"],
        "enrolled": is_enrolled,
    }

    token_raw = str(entry.get("token_id", ""))
    masked = mask_token(token_raw)

    if is_enrolled:
        out["label"] = entry.get("name") or masked
        out["token_id"] = masked
    else:
        brand = entry.get("brand_guess")
        if brand:
            kind = brand
        else:
            guess = entry.get("kind_guess", "")
            kind = known_kinds.get(guess, "unknown-kind")
        out["label"] = f"[{kind}] (bukan perangkat Anda)"
        out["token_id"] = masked

    return out


def retention_ok(recorded_at_s: float, now_s: float, ttl_days: int = 30) -> bool:
    """Verifikasi apakah data masih berada dalam jendela retensi sah."""
    return (now_s - recorded_at_s) <= (ttl_days * 86400)
