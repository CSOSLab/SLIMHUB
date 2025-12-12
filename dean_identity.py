import string
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

MAC_PREFIX_LEN = 6


def _strip_mac_delimiters(value: str) -> str:
    cleaned = value.replace(":", "").replace("-", "").replace(" ", "").upper()
    return cleaned


def mac_bytes_to_str(mac_bytes: bytes) -> str:
    if len(mac_bytes) != MAC_PREFIX_LEN:
        raise ValueError("MAC byte sequence must be 6 bytes")
    return ":".join(f"{b:02X}" for b in mac_bytes)


def normalize_mac_string(value) -> str:
    if value is None:
        raise ValueError("MAC value is empty")
    if isinstance(value, (bytes, bytearray)):
        return mac_bytes_to_str(bytes(value))
    cleaned = _strip_mac_delimiters(str(value))
    if len(cleaned) != 12 or any(ch not in string.hexdigits.upper() for ch in cleaned):
        raise ValueError(f"Invalid MAC string: {value}")
    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


def try_normalize_mac_string(value) -> Optional[str]:
    try:
        return normalize_mac_string(value)
    except ValueError:
        return None


def mac_str_to_bytes(mac_str: str) -> bytes:
    normalized = normalize_mac_string(mac_str)
    return bytes(int(part, 16) for part in normalized.split(":"))


def strip_mac_prefix(packet: bytes) -> Tuple[str, bytes]:
    if len(packet) < MAC_PREFIX_LEN:
        raise ValueError("Packet shorter than MAC prefix")
    mac_bytes = packet[:MAC_PREFIX_LEN]
    return mac_bytes_to_str(mac_bytes), packet[MAC_PREFIX_LEN:]


@dataclass
class KnownDean:
    mac: str
    relay_address: str
    device_type: str
    name: str = ""
    location: str = ""
    last_seen: float = 0.0
    connected: bool = False


class KnownDeanTable:
    def __init__(self):
        self._entries: Dict[str, KnownDean] = {}

    def _get_entry(self, mac: str) -> Optional[KnownDean]:
        normalized = try_normalize_mac_string(mac)
        if normalized is None:
            return None
        return self._entries.get(normalized)

    def observe(self, mac_bytes: bytes, relay_address: str, device_type: str, location_hint: str = "") -> KnownDean:
        mac_str = mac_bytes_to_str(mac_bytes)
        entry = self._entries.get(mac_str)
        if entry is None:
            entry = KnownDean(mac=mac_str, relay_address=relay_address, device_type=device_type)
            self._entries[mac_str] = entry
        entry.relay_address = relay_address
        entry.device_type = device_type or entry.device_type
        entry.last_seen = time.time()
        entry.connected = True
        if location_hint and not entry.location:
            entry.location = location_hint
        return entry

    def ensure(self, mac: str, relay_address: str = "", device_type: str = "", location_hint: str = "") -> KnownDean:
        normalized = normalize_mac_string(mac)
        entry = self._entries.get(normalized)
        if entry is None:
            entry = KnownDean(mac=normalized, relay_address=relay_address, device_type=device_type)
            self._entries[normalized] = entry
        if relay_address:
            entry.relay_address = relay_address
        if device_type and not entry.device_type:
            entry.device_type = device_type
        if location_hint and not entry.location:
            entry.location = location_hint
        return entry

    def parse_upstream(self, packet: bytes, relay_address: str, device_type: str, location_hint: str = "") -> Tuple[KnownDean, bytes]:
        if len(packet) < MAC_PREFIX_LEN:
            raise ValueError("Packet shorter than MAC prefix")
        mac_bytes = packet[:MAC_PREFIX_LEN]
        payload = packet[MAC_PREFIX_LEN:]
        entry = self.observe(mac_bytes, relay_address, device_type, location_hint)
        return entry, payload

    def build_downstream(self, mac: str, payload: bytes) -> bytes:
        mac_bytes = mac_str_to_bytes(mac)
        return mac_bytes + payload

    def refresh_connection_states(self, timeout: float):
        now = time.time()
        for entry in self._entries.values():
            if entry.last_seen == 0:
                continue
            is_active = (now - entry.last_seen) <= timeout
            entry.connected = is_active

    def get(self, mac: str) -> Optional[KnownDean]:
        return self._get_entry(mac)

    def relay_for(self, mac: str) -> Optional[str]:
        entry = self._get_entry(mac)
        return entry.relay_address if entry else None

    def iter_entries(self) -> Iterable[KnownDean]:
        return list(self._entries.values())

    def mark_disconnected(self, relay_address: str):
        for entry in self._entries.values():
            if entry.relay_address == relay_address:
                entry.connected = False
