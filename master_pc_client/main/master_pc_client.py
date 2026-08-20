                      
"""
Master PC client for the Kavix32 ESP32-S3 input bridge.
Captures keyboard/mouse input and sends HID events to ESP32-S3 via serial.
"""

import argparse
import atexit
import ctypes
from ctypes import wintypes
import json
import logging
from collections import deque
import re
import struct
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
LANGUAGE_PACKS_FILE = ROOT_DIR / "language_packs.json"
WINDOWS_LAYOUT_POLL_INTERVAL_S = 0.12

DEFAULT_SETTINGS = {
    "serial": {
        "port": "COM7",
        "baud": 460800,
    },
    "capture": {
        "enabled_by_default": False,
        "toggle_combo": "ctrl+f1"
    },
    "sharing": {"mode": "passive"},
    "keyboard": {
        "layout": "us",
        "layouts": ["us"],
        "use_windows_layout": False,
        "layout_profiles": {"us": {}}
    }
}

MOUSE_SEND_INTERVAL_S = 0.001
MOUSE_ACCUM_LIMIT = 512
MOUSE_LOG_INTERVAL_S = 1.0
MOUSE_SEND_BURST = 12
SERIAL_WRITE_BATCH_BYTES = 384
SERIAL_WRITE_FLUSH_INTERVAL_S = 0.001
CLIPBOARD_SYNC_POLL_INTERVAL_S = 0.30
CLIPBOARD_SYNC_MAX_TEXT_CHARS = 65536
CLIPBOARD_FRAME_START = 0x7D
CLIPBOARD_FRAME_TYPE_TEXT = 0x01
CLIPBOARD_FRAME_MAX_PAYLOAD = 4096

CHAR_TO_HID = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08,
    "f": 0x09, "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D,
    "k": 0x0E, "l": 0x0F, "m": 0x10, "n": 0x11, "o": 0x12,
    "p": 0x13, "q": 0x14, "r": 0x15, "s": 0x16, "t": 0x17,
    "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B, "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "!": 0x1E, "@": 0x1F, "#": 0x20, "$": 0x21, "%": 0x22,
    "^": 0x23, "&": 0x24, "*": 0x25, "(": 0x26, ")": 0x27,
    "-": 0x2D, "_": 0x2D, "=": 0x2E,
    "[": 0x2F, "{": 0x2F, "]": 0x30, "}": 0x30,
    "\\": 0x31, "|": 0x31, ";": 0x33, ":": 0x33,
    "'": 0x34, "\"": 0x34, "`": 0x35, "~": 0x35,
    ",": 0x36, "<": 0x36, ".": 0x37, ">": 0x37,
    "/": 0x38, "?": 0x38,
    " ": 0x2C,
}

TOKEN_TO_HID = {
    "enter": 0x28,
    "return": 0x28,
    "esc": 0x29,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "capslock": 0x39,
    "caps_lock": 0x39,
    "printscreen": 0x46,
    "print_screen": 0x46,
    "scrolllock": 0x47,
    "scroll_lock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "page_up": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "page_down": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "minus": 0x2D,
    "equal": 0x2E,
    "left_bracket": 0x2F,
    "right_bracket": 0x30,
    "backslash": 0x31,
    "semicolon": 0x33,
    "apostrophe": 0x34,
    "grave": 0x35,
    "comma": 0x36,
    "dot": 0x37,
    "period": 0x37,
    "slash": 0x38,
}
for idx in range(1, 13):
    TOKEN_TO_HID[f"f{idx}"] = 0x39 + idx

WINDOWS_VK_TO_HID = {
    0x20: 0x2C,
    0xBB: 0x2E,               
    0xBD: 0x2D,                
    0xDB: 0x2F,                
    0xDD: 0x30,                
    0xDC: 0x31,                
    0xBA: 0x33,                
    0xDE: 0x34,                
    0xC0: 0x35,                
    0xBC: 0x36,                
    0xBE: 0x37,                 
    0xBF: 0x38,                
}

WINDOWS_VK_TO_CHAR = {
    0x20: " ",
    0xBB: "=",
    0xBD: "-",
    0xDB: "[",
    0xDD: "]",
    0xDC: "\\",
    0xBA: ";",
    0xDE: "'",
    0xC0: "`",
    0xBC: ",",
    0xBE: ".",
    0xBF: "/",
}

SPECIAL_KEY_ATTR_TO_HID = {
    "enter": 0x28,
    "return": 0x28,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "caps_lock": 0x39,
    "esc": 0x29,
    "escape": 0x29,
    "up": 0x52,
    "down": 0x51,
    "left": 0x50,
    "right": 0x4F,
    "delete": 0x4C,
    "insert": 0x49,
    "home": 0x4A,
    "end": 0x4D,
    "page_up": 0x4B,
    "page_down": 0x4E,
}
for idx in range(1, 13):
    SPECIAL_KEY_ATTR_TO_HID[f"f{idx}"] = 0x39 + idx


class SerialProtocol:
    """Encode/decode serial protocol packets."""

    FRAME_START = 0x7E

    PKT_TYPE_KEYBOARD = 0x01
    PKT_TYPE_MOUSE_MOVE = 0x02
    PKT_TYPE_MOUSE_WHEEL = 0x03
    PKT_TYPE_HEARTBEAT = 0xFF

    KEY_ACTION_RELEASE = 0x00
    KEY_ACTION_PRESS = 0x01

    MOD_LEFT_CTRL = 0x01
    MOD_LEFT_SHIFT = 0x02
    MOD_LEFT_ALT = 0x04
    MOD_LEFT_GUI = 0x08
    MOD_RIGHT_CTRL = 0x10
    MOD_RIGHT_SHIFT = 0x20
    MOD_RIGHT_ALT = 0x40
    MOD_RIGHT_GUI = 0x80

    @staticmethod
    def crc8(data: bytes) -> int:
        crc = 0x00
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    @staticmethod
    def encode_keyboard(key_code: int, modifiers: int, action: int) -> bytes:
        return SerialProtocol._encode_frame(
            SerialProtocol.PKT_TYPE_KEYBOARD,
            key_code,
            modifiers,
            action,
        )

    @staticmethod
    def _i8_to_u8(value: int) -> int:
        return int(value) & 0xFF

    @staticmethod
    def _encode_frame(pkt_type: int, data1: int, data2: int, data3: int) -> bytes:
        payload = struct.pack("BBBB", pkt_type & 0xFF, data1 & 0xFF, data2 & 0xFF, data3 & 0xFF)
        checksum = SerialProtocol.crc8(payload)
        return bytes([SerialProtocol.FRAME_START]) + payload + bytes([checksum])

    @staticmethod
    def encode_mouse_move(buttons: int, delta_x: int, delta_y: int) -> bytes:
        return SerialProtocol._encode_frame(
            SerialProtocol.PKT_TYPE_MOUSE_MOVE,
            buttons & 0xFF,
            SerialProtocol._i8_to_u8(delta_x),
            SerialProtocol._i8_to_u8(delta_y),
        )

    @staticmethod
    def encode_mouse_wheel(buttons: int, wheel: int, pan: int = 0) -> bytes:
        return SerialProtocol._encode_frame(
            SerialProtocol.PKT_TYPE_MOUSE_WHEEL,
            buttons & 0xFF,
            SerialProtocol._i8_to_u8(wheel),
            SerialProtocol._i8_to_u8(pan),
        )


def encode_clipboard_frame(text: str) -> Optional[bytes]:
    if text is None:
        text = ""
    text = str(text)
    if len(text) > CLIPBOARD_SYNC_MAX_TEXT_CHARS:
        text = text[:CLIPBOARD_SYNC_MAX_TEXT_CHARS]
    payload = text.encode("utf-8", errors="ignore")
    if len(payload) > CLIPBOARD_FRAME_MAX_PAYLOAD:
        payload = payload[:CLIPBOARD_FRAME_MAX_PAYLOAD]
    payload_len = len(payload)
    header = bytes(
        [
            CLIPBOARD_FRAME_TYPE_TEXT,
            (payload_len >> 8) & 0xFF,
            payload_len & 0xFF,
        ]
    )
    checksum = SerialProtocol.crc8(header + payload)
    return bytes([CLIPBOARD_FRAME_START]) + header + payload + bytes([checksum])


class ClipboardFrameParser:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> List[str]:
        if not chunk:
            return []
        self._buf.extend(chunk)
        out: List[str] = []

        while True:
            start_idx = self._buf.find(bytes([CLIPBOARD_FRAME_START]))
            if start_idx < 0:
                self._buf.clear()
                break
            if start_idx > 0:
                del self._buf[:start_idx]
            if len(self._buf) < 5:
                break

            frame_type = self._buf[1]
            payload_len = (self._buf[2] << 8) | self._buf[3]
            if payload_len > CLIPBOARD_FRAME_MAX_PAYLOAD:
                del self._buf[0]
                continue

            total_len = 1 + 3 + payload_len + 1
            if len(self._buf) < total_len:
                break

            frame = bytes(self._buf[:total_len])
            del self._buf[:total_len]

            checksum_expected = frame[-1]
            checksum_actual = SerialProtocol.crc8(frame[1:-1])
            if checksum_expected != checksum_actual:
                continue
            if frame_type != CLIPBOARD_FRAME_TYPE_TEXT:
                continue

            payload = frame[4:-1]
            try:
                text = payload.decode("utf-8", errors="strict")
            except Exception:
                text = payload.decode("utf-8", errors="ignore")
            out.append(text)

        return out


MODIFIER_TOKEN_TO_BIT = {
    "ctrl": SerialProtocol.MOD_LEFT_CTRL,
    "control": SerialProtocol.MOD_LEFT_CTRL,
    "lctrl": SerialProtocol.MOD_LEFT_CTRL,
    "left_ctrl": SerialProtocol.MOD_LEFT_CTRL,
    "rctrl": SerialProtocol.MOD_RIGHT_CTRL,
    "right_ctrl": SerialProtocol.MOD_RIGHT_CTRL,
    "shift": SerialProtocol.MOD_LEFT_SHIFT,
    "lshift": SerialProtocol.MOD_LEFT_SHIFT,
    "left_shift": SerialProtocol.MOD_LEFT_SHIFT,
    "rshift": SerialProtocol.MOD_RIGHT_SHIFT,
    "right_shift": SerialProtocol.MOD_RIGHT_SHIFT,
    "alt": SerialProtocol.MOD_LEFT_ALT,
    "lalt": SerialProtocol.MOD_LEFT_ALT,
    "left_alt": SerialProtocol.MOD_LEFT_ALT,
    "ralt": SerialProtocol.MOD_RIGHT_ALT,
    "right_alt": SerialProtocol.MOD_RIGHT_ALT,
    "altgr": SerialProtocol.MOD_RIGHT_ALT,
    "alt_gr": SerialProtocol.MOD_RIGHT_ALT,
    "win": SerialProtocol.MOD_LEFT_GUI,
    "gui": SerialProtocol.MOD_LEFT_GUI,
    "cmd": SerialProtocol.MOD_LEFT_GUI,
    "meta": SerialProtocol.MOD_LEFT_GUI,
}

VK_TO_MODIFIER_BIT = {
    0x10: SerialProtocol.MOD_LEFT_SHIFT,             
    0x11: SerialProtocol.MOD_LEFT_CTRL,                
    0x12: SerialProtocol.MOD_LEFT_ALT,              
    0x5B: SerialProtocol.MOD_LEFT_GUI,              
    0x5C: SerialProtocol.MOD_RIGHT_GUI,             
    0xA0: SerialProtocol.MOD_LEFT_SHIFT,              
    0xA1: SerialProtocol.MOD_RIGHT_SHIFT,             
    0xA2: SerialProtocol.MOD_LEFT_CTRL,                 
    0xA3: SerialProtocol.MOD_RIGHT_CTRL,                
    0xA4: SerialProtocol.MOD_LEFT_ALT,               
    0xA5: SerialProtocol.MOD_RIGHT_ALT,              
}

ComboSpec = Tuple[int, Tuple[int, ...]]


def _normalize_token(token: str) -> str:
    return token.strip().lower().replace("-", "_").replace(" ", "_")


def _deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = deepcopy(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def sanitize_profile_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(value).strip().lower()).strip("_")
    return cleaned or "layout"


def _normalize_klid(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith("0x"):
        text = text[2:]

    if re.fullmatch(r"[0-9a-fA-F]{8}", text):
        return text.upper()

    try:
        numeric = int(text, 16)
    except Exception:
        return None
    if numeric < 0:
        return None
    return f"{numeric & 0xFFFFFFFF:08X}"


def load_language_packs(path: Path) -> Dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.info("Could not read language packs from '%s': %s", path, exc)
        return {}

    if not isinstance(loaded, dict):
        return {}
    packs = loaded.get("packs")
    return packs if isinstance(packs, dict) else {}


def build_windows_layout_mappings(
    language_packs: Dict[str, Any],
    configured_profiles: Dict[str, Dict[str, str]],
    preferred_pack_id: str = "",
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    profiles: Dict[str, Dict[str, str]] = deepcopy(configured_profiles) if isinstance(configured_profiles, dict) else {}
    profiles.setdefault("us", {})

    klid_to_profile: Dict[str, str] = {}
    klid_source_pack: Dict[str, str] = {}
    klid_remap_size: Dict[str, int] = {}
    preferred_pack_id = str(preferred_pack_id or "").strip()

    for pack_id in sorted(language_packs.keys()):
        pack = language_packs.get(pack_id)
        if not isinstance(pack, dict):
            continue

        raw_profile = str(pack.get("profile", "") or pack_id)
        profile = sanitize_profile_name(raw_profile)

        remap_raw = pack.get("remap", {})
        remap: Dict[str, str] = {}
        if isinstance(remap_raw, dict):
            for src, dst in remap_raw.items():
                src_text = str(src)
                dst_text = str(dst)
                if src_text and dst_text:
                    remap[src_text] = dst_text

        existing_profile = profiles.get(profile)
        if (not isinstance(existing_profile, dict)) or (not existing_profile and remap):
            profiles[profile] = remap
        elif preferred_pack_id and str(pack_id) == preferred_pack_id:
            profiles[profile] = remap

        klids = pack.get("klids", [])
        if not isinstance(klids, list):
            continue

        remap_size = len(remap)
        for raw_klid in klids:
            klid = _normalize_klid(raw_klid)
            if not klid:
                continue

            replace_entry = False
            if klid not in klid_to_profile:
                replace_entry = True
            else:
                existing_pack = klid_source_pack.get(klid, "")
                existing_size = klid_remap_size.get(klid, 0)
                if preferred_pack_id and str(pack_id) == preferred_pack_id and existing_pack != preferred_pack_id:
                    replace_entry = True
                elif existing_size == 0 and remap_size > 0:
                    replace_entry = True

            if replace_entry:
                klid_to_profile[klid] = profile
                klid_source_pack[klid] = str(pack_id)
                klid_remap_size[klid] = remap_size

    return profiles, klid_to_profile


def load_settings(settings_path: Path) -> dict:
    if not settings_path.exists():
        settings_path.write_text(json.dumps(DEFAULT_SETTINGS, indent=2), encoding="utf-8")
        logger.info("Created default settings: %s", settings_path)
        return deepcopy(DEFAULT_SETTINGS)

    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse settings '%s': %s. Using defaults.", settings_path, exc)
        return deepcopy(DEFAULT_SETTINGS)

    if not isinstance(loaded, dict):
        logger.warning("Settings file root must be an object. Using defaults.")
        return deepcopy(DEFAULT_SETTINGS)

    return _deep_merge(DEFAULT_SETTINGS, loaded)


def char_to_hid(char: str, remap: Dict[str, str]) -> Optional[int]:
    mapped = remap.get(char, char)
    if mapped in CHAR_TO_HID:
        return CHAR_TO_HID[mapped]
    if len(mapped) == 1 and mapped.isalpha():
        return CHAR_TO_HID.get(mapped.lower())
    return None


def key_to_vk(key) -> Optional[int]:
    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        return vk
    value = getattr(key, "value", None)
    vk = getattr(value, "vk", None)
    if isinstance(vk, int):
        return vk
    return None


def vk_to_hid(vk: int) -> Optional[int]:
    if 0x41 <= vk <= 0x5A:       
        return 0x04 + (vk - 0x41)
    if 0x31 <= vk <= 0x39:       
        return 0x1E + (vk - 0x31)
    if vk == 0x30:     
        return 0x27
    return WINDOWS_VK_TO_HID.get(vk)


def vk_to_char(vk: int) -> Optional[str]:
    if 0x41 <= vk <= 0x5A:       
        return chr(vk + 32)
    if 0x30 <= vk <= 0x39:       
        return chr(vk)
    return WINDOWS_VK_TO_CHAR.get(vk)


def parse_key_token(token: str, remap: Dict[str, str]) -> Optional[int]:
    normalized = _normalize_token(token)
    if normalized in TOKEN_TO_HID:
        return TOKEN_TO_HID[normalized]

    if len(token) == 1:
        return char_to_hid(token, remap)

    return None


def parse_combo_expression(combo_expr: str, remap: Dict[str, str]) -> ComboSpec:
    tokens = [part.strip() for part in combo_expr.split("+") if part.strip()]
    if not tokens:
        raise ValueError("Empty combo expression")

    modifiers = 0
    key_codes: List[int] = []

    for token in tokens:
        normalized = _normalize_token(token)
        if normalized in MODIFIER_TOKEN_TO_BIT:
            modifiers |= MODIFIER_TOKEN_TO_BIT[normalized]
            continue

        candidate = parse_key_token(token, remap)
        if candidate is None:
            raise ValueError(f"Unknown key token: '{token}'")
        if candidate not in key_codes:
            key_codes.append(candidate)

    return modifiers, tuple(key_codes)


class InputCapture:
    """Capture keyboard input from system."""

    def __init__(self, layout_name: str, layout_profiles: Dict[str, Dict[str, str]]):
        try:
            from pynput import keyboard
            self.keyboard = keyboard
            self.listener = None
            self.blocker = None
            self.block_predicate = lambda: False
            self.toggle_suppress_predicate = lambda _vk, _msg: False
            self.blocking_enabled = False
            self._is_windows = sys.platform.startswith("win")
            self._blocker_lock = threading.Lock()
            self._on_press_cb = None
            self._on_release_cb = None
        except ImportError:
            logger.error("pynput not installed. Install with: pip install pynput")
            sys.exit(1)

        if not isinstance(layout_profiles, dict) or not layout_profiles:
            layout_profiles = {"us": {}}

        self.layout_profiles = layout_profiles
        self.layout_name = "us"
        self.char_remap: Dict[str, str] = {}
        self.set_layout(layout_name)
        self.special_key_map = self._build_special_key_map()

    def _build_special_key_map(self) -> Dict[object, int]:
        key_map: Dict[object, int] = {}
        Key = self.keyboard.Key

        for attr_name, hid in SPECIAL_KEY_ATTR_TO_HID.items():
            key_obj = getattr(Key, attr_name, None)
            if key_obj is not None:
                key_map[key_obj] = hid

        return key_map

    def set_layout(self, layout_name: str) -> None:
        if layout_name not in self.layout_profiles:
            logger.warning("Unknown layout '%s', falling back to 'us'", layout_name)
            layout_name = "us"
        self.layout_name = layout_name
        profile = self.layout_profiles.get(layout_name, {})
        self.char_remap = profile if isinstance(profile, dict) else {}

    def pynput_key_to_hid(self, key) -> Optional[int]:
        if key in self.special_key_map:
            return self.special_key_map[key]

        vk = key_to_vk(key)

        if hasattr(key, "char"):
            char = key.char
            if char is not None:
                hid = char_to_hid(char, self.char_remap)
                if hid is not None:
                    return hid

        if vk is not None:
                                                                                       
            candidate_char = vk_to_char(vk)
            if candidate_char is not None:
                hid = char_to_hid(candidate_char, self.char_remap)
                if hid is not None:
                    return hid
            return vk_to_hid(vk)

        return None

    def _should_block_local_input(self) -> bool:
        try:
            return bool(self.block_predicate())
        except Exception:
            return False

    def _ensure_blocker_listener(self) -> None:
        if not self._is_windows or self.blocker is not None:
            return
        try:
            self.blocker = self.keyboard.Listener(
                on_press=lambda _k: None,
                on_release=lambda _k: None,
                suppress=False,
                win32_event_filter=self._win32_block_filter,
            )
            self.blocker.start()
        except TypeError:
            self.blocker = None
            return

                                                                              
        if self.listener is not None and self._on_press_cb is not None and self._on_release_cb is not None:
            self.listener.stop()
            try:
                self.listener.join(timeout=0.3)
            except Exception:
                pass
            self.listener = self.keyboard.Listener(on_press=self._on_press_cb, on_release=self._on_release_cb)
            self.listener.start()

    def _stop_blocker_listener(self) -> None:
        if self.blocker is None:
            return
        self.blocker.stop()
        try:
            self.blocker.join(timeout=0.3)
        except Exception:
            pass
        self.blocker = None

    def _win32_block_filter(self, msg, data):
        if self.blocker is None:
            return
        vk = getattr(data, "vkCode", None)
        blocking = self._should_block_local_input()
        suppress_toggle = False
        if not blocking and vk is not None:
            try:
                suppress_toggle = bool(self.toggle_suppress_predicate(int(vk), int(msg)))
            except Exception:
                suppress_toggle = False
        if not blocking and not suppress_toggle:
            return

        suppress_fn = getattr(self.blocker, "suppress_event", None)
        if suppress_fn is not None:
            suppress_fn()

    def set_blocking(self, enabled: bool) -> None:
        enabled = bool(enabled)
        with self._blocker_lock:
            if enabled == self.blocking_enabled:
                return
            self.blocking_enabled = enabled

            if not enabled:
                return

            self._ensure_blocker_listener()

    def start_listening(self, on_press, on_release, should_block_input=None):
        if should_block_input is not None:
            self.block_predicate = should_block_input
        self._on_press_cb = on_press
        self._on_release_cb = on_release

        self.listener = self.keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()
        self._ensure_blocker_listener()
        self.set_blocking(self._should_block_local_input())
        logger.info("Keyboard listener started")

    def stop_listening(self):
        self.set_blocking(False)
        self._stop_blocker_listener()
        if self.listener:
            self.listener.stop()
            try:
                self.listener.join(timeout=0.3)
            except Exception:
                pass
            self.listener = None
            logger.info("Keyboard listener stopped")


class WindowsKeyboardLayoutResolver:
    """Resolve active Windows keyboard layout KLID (e.g. 00000409)."""

    def __init__(self) -> None:
        self.available = False
        if not sys.platform.startswith("win"):
            return

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._get_foreground_window = user32.GetForegroundWindow
            self._get_foreground_window.argtypes = []
            self._get_foreground_window.restype = wintypes.HWND

            self._get_window_thread_process_id = user32.GetWindowThreadProcessId
            self._get_window_thread_process_id.argtypes = [wintypes.HWND, wintypes.LPDWORD]
            self._get_window_thread_process_id.restype = wintypes.DWORD

            self._get_keyboard_layout = user32.GetKeyboardLayout
            self._get_keyboard_layout.argtypes = [wintypes.DWORD]
            self._get_keyboard_layout.restype = ctypes.c_void_p
            self.available = True
        except Exception:
            self.available = False

    def current_klid(self) -> Optional[str]:
        if not self.available:
            return None

        try:
            hwnd = self._get_foreground_window()
            thread_id = 0
            if hwnd:
                thread_id = int(self._get_window_thread_process_id(hwnd, None))
            hkl = self._get_keyboard_layout(thread_id)
            if not hkl:
                return None
            return f"{int(hkl) & 0xFFFFFFFF:08X}"
        except Exception:
            return None


class MouseCapture:
    """Capture mouse input from system."""

    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP = 0x0205
    WM_MBUTTONDOWN = 0x0207
    WM_MBUTTONUP = 0x0208
    WM_MOUSEWHEEL = 0x020A
    WM_XBUTTONDOWN = 0x020B
    WM_XBUTTONUP = 0x020C
    WM_MOUSEHWHEEL = 0x020E
    SPI_SETCURSORS = 0x0057

    OCR_IDS = (
        32512,              
        32513,             
        32514,            
        32515,             
        32516,          
        32640,            
        32641,            
        32642,                
        32643,                
        32644,              
        32645,              
        32646,               
        32648,          
        32649,            
        32650,                   
        32651,            
    )

    def __init__(self):
        try:
            from pynput import mouse
            self.mouse = mouse
            self.listener = None
            self.block_predicate = lambda: False
            self.blocking_enabled = False
            self._listener_lock = threading.Lock()
            self._is_windows = sys.platform.startswith("win")
            self._cursor_hidden = False
            self._system_cursor_hidden = False
            self._cursor_confined = False
            self._cursor_lock = threading.Lock()
            self._on_move_cb = None
            self._on_click_cb = None
            self._on_scroll_cb = None
            if self._is_windows:
                user32 = ctypes.windll.user32
                user32.CreateCursor.argtypes = [
                    wintypes.HINSTANCE,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ]
                user32.CreateCursor.restype = wintypes.HCURSOR
                user32.SetSystemCursor.argtypes = [wintypes.HCURSOR, wintypes.DWORD]
                user32.SetSystemCursor.restype = wintypes.BOOL
                user32.SystemParametersInfoW.argtypes = [
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ]
                user32.SystemParametersInfoW.restype = wintypes.BOOL
                user32.ClipCursor.argtypes = [ctypes.c_void_p]
                user32.ClipCursor.restype = wintypes.BOOL
                user32.SetCursor.argtypes = [wintypes.HCURSOR]
                user32.SetCursor.restype = wintypes.HCURSOR
                atexit.register(self._restore_system_cursors)
        except ImportError:
            logger.error("pynput not installed. Install with: pip install pynput")
            sys.exit(1)

        self.button_to_bit = {}
        Button = self.mouse.Button
        mapping = {
            "left": 0x01,
            "right": 0x02,
            "middle": 0x04,
            "x1": 0x08,
            "x2": 0x10,
        }
        for name, bit in mapping.items():
            self.button_to_bit[name] = bit
        for attr_name, bit in mapping.items():
            button_obj = getattr(Button, attr_name, None)
            if button_obj is not None:
                self.button_to_bit[button_obj] = bit

    def button_bit(self, button) -> int:
        if isinstance(button, str):
            return self.button_to_bit.get(button.lower(), 0)
        return self.button_to_bit.get(button, 0)

    def _should_block_local_input(self) -> bool:
        try:
            return bool(self.block_predicate())
        except Exception:
            return False

    def _set_cursor_visibility(self, visible: bool) -> None:
        if not self._is_windows:
            return
        try:
            user32 = ctypes.windll.user32
            show_cursor = user32.ShowCursor
            max_iters = 256

            class CURSORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hCursor", wintypes.HANDLE),
                    ("ptScreenPos", wintypes.POINT),
                ]

            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            current_visible = None
            if user32.GetCursorInfo(ctypes.byref(ci)):
                current_visible = bool(ci.flags & 0x00000001)
                self._cursor_hidden = not current_visible

                                                                             
            if current_visible is not None and current_visible == visible:
                return

            if visible:
                for _ in range(max_iters):
                    if show_cursor(True) >= 0:
                        break
            else:
                                                           
                width = int(user32.GetSystemMetrics(0))
                height = int(user32.GetSystemMetrics(1))
                if width > 4 and height > 4:
                    user32.SetCursorPos(width - 2, height - 2)
                for _ in range(max_iters):
                    if show_cursor(False) < 0:
                        break

            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            if user32.GetCursorInfo(ctypes.byref(ci)):
                self._cursor_hidden = not bool(ci.flags & 0x00000001)
            else:
                self._cursor_hidden = not visible
        except Exception:
            pass

    @staticmethod
    def _create_transparent_cursor_handle():
        user32 = ctypes.windll.user32
        width = 32
        height = 32
        mask_size = (width * height) // 8
        and_mask = (ctypes.c_ubyte * mask_size)(*([0xFF] * mask_size))
        xor_mask = (ctypes.c_ubyte * mask_size)(*([0x00] * mask_size))
        return user32.CreateCursor(
            None,
            0,
            0,
            width,
            height,
            ctypes.byref(and_mask),
            ctypes.byref(xor_mask),
        )

    def _restore_system_cursors(self) -> None:
        if not self._is_windows:
            return
        try:
            ctypes.windll.user32.SystemParametersInfoW(self.SPI_SETCURSORS, 0, None, 0)
        except Exception:
            pass
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass
        self._cursor_confined = False
        self._system_cursor_hidden = False

    def _set_system_cursor_hidden(self, hidden: bool) -> None:
        if not self._is_windows:
            return
        with self._cursor_lock:
            if hidden == self._system_cursor_hidden:
                return
            user32 = ctypes.windll.user32
            if hidden:
                changed = False
                for cursor_id in self.OCR_IDS:
                    handle = self._create_transparent_cursor_handle()
                    if not handle:
                        continue
                    if user32.SetSystemCursor(handle, cursor_id):
                        changed = True
                if changed:
                    self._system_cursor_hidden = True
            else:
                self._restore_system_cursors()

    def _set_cursor_confined(self, enabled: bool) -> None:
        if not self._is_windows:
            return
        with self._cursor_lock:
            if enabled == self._cursor_confined:
                return
            user32 = ctypes.windll.user32
            if enabled:
                width = int(user32.GetSystemMetrics(0))
                height = int(user32.GetSystemMetrics(1))
                if width <= 1 or height <= 1:
                    return
                x = max(0, width - 2)
                y = max(0, height - 2)
                rect = wintypes.RECT(x, y, x + 1, y + 1)
                user32.SetCursorPos(x, y)
                user32.ClipCursor(ctypes.byref(rect))
                user32.SetCursor(None)
                self._cursor_confined = True
            else:
                user32.ClipCursor(None)
                self._cursor_confined = False

    def _win32_capture_filter(self, msg, data):
        blocking = self._should_block_local_input()
        if self._is_windows:
            if blocking:
                                                                               
                self._set_cursor_visibility(False)
                self._set_system_cursor_hidden(True)
                self._set_cursor_confined(True)
            else:
                if self._cursor_hidden or self._system_cursor_hidden or self._cursor_confined:
                    self._set_cursor_visibility(True)
                    self._set_system_cursor_hidden(False)
                    self._set_cursor_confined(False)

        x = 0
        y = 0
        pt = getattr(data, "pt", None)
        if pt is not None:
            try:
                x = int(pt.x)
                y = int(pt.y)
            except Exception:
                pass

        if msg == self.WM_MOUSEMOVE:
            if blocking:
                                                                          
                suppress_fn = getattr(self.listener, "suppress_event", None)
                if suppress_fn is not None:
                    suppress_fn()
                return
            if self._on_move_cb is not None:
                self._on_move_cb(x, y)
        elif msg in (self.WM_LBUTTONDOWN, self.WM_LBUTTONUP):
            if self._on_click_cb is not None:
                self._on_click_cb(x, y, "left", msg == self.WM_LBUTTONDOWN)
        elif msg in (self.WM_RBUTTONDOWN, self.WM_RBUTTONUP):
            if self._on_click_cb is not None:
                self._on_click_cb(x, y, "right", msg == self.WM_RBUTTONDOWN)
        elif msg in (self.WM_MBUTTONDOWN, self.WM_MBUTTONUP):
            if self._on_click_cb is not None:
                self._on_click_cb(x, y, "middle", msg == self.WM_MBUTTONDOWN)
        elif msg in (self.WM_XBUTTONDOWN, self.WM_XBUTTONUP):
            mouse_data = int(getattr(data, "mouseData", 0))
            x_btn = (mouse_data >> 16) & 0xFFFF
            btn_name = "x1" if x_btn == 1 else "x2"
            if self._on_click_cb is not None:
                self._on_click_cb(x, y, btn_name, msg == self.WM_XBUTTONDOWN)
        elif msg == self.WM_MOUSEWHEEL:
            mouse_data = int(getattr(data, "mouseData", 0))
            delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
            steps = int(delta / 120) if delta else 0
            if steps != 0 and self._on_scroll_cb is not None:
                self._on_scroll_cb(x, y, 0, steps)
        elif msg == self.WM_MOUSEHWHEEL:
            mouse_data = int(getattr(data, "mouseData", 0))
            delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
            steps = int(delta / 120) if delta else 0
            if steps != 0 and self._on_scroll_cb is not None:
                self._on_scroll_cb(x, y, steps, 0)

                                                                   
        if not blocking:
            return
        suppressible = {
            self.WM_MOUSEMOVE,
            self.WM_LBUTTONDOWN, self.WM_LBUTTONUP,
            self.WM_RBUTTONDOWN, self.WM_RBUTTONUP,
            self.WM_MBUTTONDOWN, self.WM_MBUTTONUP,
            self.WM_XBUTTONDOWN, self.WM_XBUTTONUP,
            self.WM_MOUSEWHEEL, self.WM_MOUSEHWHEEL,
        }
        if msg in suppressible:
            suppress_fn = getattr(self.listener, "suppress_event", None)
            if suppress_fn is not None:
                suppress_fn()

    def _restart_listener(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            try:
                self.listener.join(timeout=0.3)
            except Exception:
                pass
            self.listener = None

        if self._on_move_cb is None or self._on_click_cb is None or self._on_scroll_cb is None:
            return

        try:
            if self._is_windows:
                                                                               
                self.listener = self.mouse.Listener(
                    on_move=lambda *_args: None,
                    on_click=lambda *_args: None,
                    on_scroll=lambda *_args: None,
                    suppress=False,
                    win32_event_filter=self._win32_capture_filter,
                )
            else:
                self.listener = self.mouse.Listener(
                    on_move=self._on_move_cb,
                    on_click=self._on_click_cb,
                    on_scroll=self._on_scroll_cb,
                    suppress=self.blocking_enabled,
                )
        except TypeError:
                                                                    
            self.listener = self.mouse.Listener(
                on_move=self._on_move_cb,
                on_click=self._on_click_cb,
                on_scroll=self._on_scroll_cb,
            )
            self.blocking_enabled = False
        self.listener.start()

    def set_blocking(self, enabled: bool) -> None:
        enabled = bool(enabled)
        with self._listener_lock:
            if enabled == self.blocking_enabled:
                return
            self.blocking_enabled = enabled
            if self._is_windows:
                self._set_cursor_visibility(not self.blocking_enabled)
                self._set_system_cursor_hidden(self.blocking_enabled)
                self._set_cursor_confined(self.blocking_enabled)
                if self.blocking_enabled:
                    try:
                        user32 = ctypes.windll.user32
                        width = int(user32.GetSystemMetrics(0))
                        height = int(user32.GetSystemMetrics(1))
                        if width > 2 and height > 2:
                            user32.SetCursorPos(width - 2, height - 2)
                    except Exception:
                        pass
            elif self._on_move_cb is not None and self._on_click_cb is not None and self._on_scroll_cb is not None:
                self._restart_listener()

    def start_listening(self, on_move, on_click, on_scroll, should_block_input=None):
        if should_block_input is not None:
            self.block_predicate = should_block_input
        self._on_move_cb = on_move
        self._on_click_cb = on_click
        self._on_scroll_cb = on_scroll

        self.blocking_enabled = self._should_block_local_input()
        with self._listener_lock:
            self._restart_listener()
            if self._is_windows:
                self._set_cursor_visibility(not self.blocking_enabled)
                self._set_system_cursor_hidden(self.blocking_enabled)
                self._set_cursor_confined(self.blocking_enabled)
        logger.info("Mouse listener started")

    def stop_listening(self):
        with self._listener_lock:
            self.blocking_enabled = False
            if self.listener:
                self.listener.stop()
                try:
                    self.listener.join(timeout=0.3)
                except Exception:
                    pass
                self.listener = None
                logger.info("Mouse listener stopped")
            if self._is_windows:
                self._set_cursor_visibility(True)
                self._set_system_cursor_hidden(False)
                self._set_cursor_confined(False)


class WindowsRawMouseCapture:
    """Capture Windows relative mouse movement via RAWINPUT (not screen-position based)."""

    WM_INPUT = 0x00FF
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002

    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE = 0
    RIDEV_INPUTSINK = 0x00000100

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wintypes.USHORT),
            ("usUsage", wintypes.USHORT),
            ("dwFlags", wintypes.DWORD),
            ("hwndTarget", wintypes.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wintypes.DWORD),
            ("dwSize", wintypes.DWORD),
            ("hDevice", wintypes.HANDLE),
            ("wParam", wintypes.WPARAM),
        ]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [
            ("usFlags", wintypes.USHORT),
            ("_reserved", wintypes.USHORT),
            ("ulButtons", wintypes.DWORD),
            ("ulRawButtons", wintypes.DWORD),
            ("lLastX", wintypes.LONG),
            ("lLastY", wintypes.LONG),
            ("ulExtraInformation", wintypes.DWORD),
        ]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    def __init__(self, on_delta_cb: Callable[[int, int], None], capture_predicate: Callable[[], bool]):
        self.on_delta_cb = on_delta_cb
        self.capture_predicate = capture_predicate
        self._is_windows = sys.platform.startswith("win")
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._hwnd = None
        self._wndproc = None
        self._class_name = f"Kavix32RawMouse_{id(self)}"
        self._class_atom = 0
        self._hinstance = None

        if self._is_windows:
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32

            self._user32.RegisterRawInputDevices.argtypes = [
                ctypes.POINTER(self.RAWINPUTDEVICE),
                wintypes.UINT,
                wintypes.UINT,
            ]
            self._user32.RegisterRawInputDevices.restype = wintypes.BOOL

            self._user32.GetRawInputData.argtypes = [
                ctypes.c_void_p,
                wintypes.UINT,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.UINT),
                wintypes.UINT,
            ]
            self._user32.GetRawInputData.restype = wintypes.UINT

            self._user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            self._user32.DefWindowProcW.restype = wintypes.LPARAM

            self._user32.RegisterClassW.argtypes = [ctypes.POINTER(self.WNDCLASSW)]
            self._user32.RegisterClassW.restype = wintypes.ATOM

            self._user32.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.HMENU,
                wintypes.HINSTANCE,
                ctypes.c_void_p,
            ]
            self._user32.CreateWindowExW.restype = wintypes.HWND

            self._user32.DestroyWindow.argtypes = [wintypes.HWND]
            self._user32.DestroyWindow.restype = wintypes.BOOL

            self._user32.PostQuitMessage.argtypes = [ctypes.c_int]
            self._user32.PostQuitMessage.restype = None

            self._user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]
            self._user32.GetMessageW.restype = ctypes.c_int

            self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            self._user32.TranslateMessage.restype = wintypes.BOOL

            self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            self._user32.DispatchMessageW.restype = wintypes.LPARAM

            self._user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            self._user32.PostMessageW.restype = wintypes.BOOL

            self._user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
            self._user32.UnregisterClassW.restype = wintypes.BOOL

            self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            self._kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        else:
            self._user32 = None
            self._kernel32 = None

    def _capture_enabled(self) -> bool:
        try:
            return bool(self.capture_predicate())
        except Exception:
            return False

    def _register_raw_input(self) -> bool:
        rid = self.RAWINPUTDEVICE(
            usUsagePage=0x01,                   
            usUsage=0x02,             
            dwFlags=self.RIDEV_INPUTSINK,
            hwndTarget=self._hwnd,
        )
        return bool(
            self._user32.RegisterRawInputDevices(
                ctypes.byref(rid),
                1,
                ctypes.sizeof(self.RAWINPUTDEVICE),
            )
        )

    def _handle_wm_input(self, lparam) -> None:
        if not self._capture_enabled():
            return

        header_size = ctypes.sizeof(self.RAWINPUTHEADER)
        size = wintypes.UINT(0)
        result = self._user32.GetRawInputData(
            ctypes.c_void_p(lparam),
            self.RID_INPUT,
            None,
            ctypes.byref(size),
            header_size,
        )
        if result == 0xFFFFFFFF or size.value < header_size:
            return

        buf = (ctypes.c_ubyte * size.value)()
        result = self._user32.GetRawInputData(
            ctypes.c_void_p(lparam),
            self.RID_INPUT,
            ctypes.byref(buf),
            ctypes.byref(size),
            header_size,
        )
        if result == 0xFFFFFFFF or size.value < header_size:
            return

        header = self.RAWINPUTHEADER.from_buffer_copy(buf)
        if header.dwType != self.RIM_TYPEMOUSE:
            return

        mouse_offset = ctypes.sizeof(self.RAWINPUTHEADER)
        if size.value < mouse_offset + ctypes.sizeof(self.RAWMOUSE):
            return

        mouse = self.RAWMOUSE.from_buffer_copy(buf, mouse_offset)
        dx = int(mouse.lLastX)
        dy = int(mouse.lLastY)
        if dx == 0 and dy == 0:
            return
        try:
            self.on_delta_cb(dx, dy)
        except Exception:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_INPUT:
            self._handle_wm_input(lparam)
            return 0
        if msg == self.WM_CLOSE:
            self._user32.DestroyWindow(hwnd)
            return 0
        if msg == self.WM_DESTROY:
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _thread_main(self) -> None:
        lresult_t = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        wndproc_t = ctypes.WINFUNCTYPE(lresult_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        self._wndproc = wndproc_t(self._wnd_proc)
        self._hinstance = self._kernel32.GetModuleHandleW(None)

        wnd_class = self.WNDCLASSW()
        wnd_class.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wnd_class.hInstance = self._hinstance
        wnd_class.lpszClassName = self._class_name

        self._class_atom = self._user32.RegisterClassW(ctypes.byref(wnd_class))
        if not self._class_atom:
            last_error = ctypes.get_last_error()
                                        
            if last_error != 1410:
                logger.warning("Raw mouse class registration failed: %s", last_error)
                self._ready.set()
                return

        hwnd = self._user32.CreateWindowExW(
            0,
            self._class_name,
            self._class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._hinstance,
            None,
        )
        if not hwnd:
            logger.warning("Raw mouse window creation failed")
            self._ready.set()
            return

        self._hwnd = hwnd
        if not self._register_raw_input():
            logger.warning("Raw mouse input registration failed")

        self._ready.set()

        msg = wintypes.MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

        self._hwnd = None
        if self._class_atom:
            self._user32.UnregisterClassW(self._class_name, self._hinstance)
            self._class_atom = 0

    def start(self) -> None:
        if not self._is_windows:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.0)

    def stop(self) -> None:
        if not self._is_windows:
            return
        thread = self._thread
        if thread is None:
            return
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, self.WM_CLOSE, 0, 0)
        if thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None


class SerialConnection:
    """Handle serial communication with ESP32."""

    @staticmethod
    def _open_no_reset(port: str, baudrate: int, timeout: float):
        import serial

        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baudrate
        ser.timeout = timeout
        ser.write_timeout = 1
                                                                                
                                                                                     
        ser.dtr = False
        ser.rts = False
        ser.dsrdtr = False
        ser.rtscts = False
        ser.xonxoff = False
        ser.open()
        return ser

    def __init__(self, port: str, baudrate: int = 460800, timeout: float = 0):
        try:
            self.serial = self._open_no_reset(port, baudrate, timeout)
            self._write_lock = threading.Lock()
            self._queue_lock = threading.Lock()
            self._outgoing_packets = deque()
            self._outgoing_event = threading.Event()
            self._writer_stop = threading.Event()
            self._writer_thread: Optional[threading.Thread] = None
            self._writer_error_logged = False
            time.sleep(0.2)
            try:
                self.serial.reset_input_buffer()
            except Exception:
                pass
            self._writer_thread = threading.Thread(target=self._serial_writer_loop, daemon=True)
            self._writer_thread.start()
            logger.info("Serial connection opened: %s @ %d baud", port, baudrate)
        except ImportError:
            logger.error("pyserial not installed. Install with: pip install pyserial")
            sys.exit(1)
        except Exception as e:
            logger.error("Failed to open serial port %s: %s", port, e)
            sys.exit(1)

    def _drain_outgoing_packets(self):
        with self._queue_lock:
            if not self._outgoing_packets:
                self._outgoing_event.clear()
                return None
            packets = self._outgoing_packets
            self._outgoing_packets = deque()
            self._outgoing_event.clear()
            return packets

    def _flush_packet_batch(self, packets) -> None:
        if not packets:
            return
        batch = bytearray()
        with self._write_lock:
            for packet in packets:
                if not packet:
                    continue
                if batch and (len(batch) + len(packet) > SERIAL_WRITE_BATCH_BYTES):
                    self.serial.write(batch)
                    batch.clear()
                batch.extend(packet)
            if batch:
                self.serial.write(batch)

    def _serial_writer_loop(self) -> None:
        while not self._writer_stop.is_set():
            self._outgoing_event.wait(SERIAL_WRITE_FLUSH_INTERVAL_S)
            packets = self._drain_outgoing_packets()
            if not packets:
                continue
            try:
                self._flush_packet_batch(packets)
                self._writer_error_logged = False
            except Exception as e:
                if not self._writer_error_logged:
                    logger.error("Serial writer error: %s", e)
                    self._writer_error_logged = True
                time.sleep(0.01)

    def send_packet(self, packet: bytes) -> bool:
        if self._writer_stop.is_set():
            return False
        with self._queue_lock:
            self._outgoing_packets.append(packet)
            self._outgoing_event.set()
        return True

    def read_available(self) -> bytes:
        try:
            waiting = self.serial.in_waiting
            if waiting:
                return self.serial.read(waiting)
        except Exception as e:
            logger.warning("Read error: %s", e)
        return b""

    def close(self):
        self._writer_stop.set()
        self._outgoing_event.set()
        writer = self._writer_thread
        if writer is not None and writer.is_alive():
            writer.join(timeout=0.5)
        self._writer_thread = None

                                                                     
        pending = self._drain_outgoing_packets()
        if pending and self.serial and self.serial.is_open:
            try:
                self._flush_packet_batch(pending)
            except Exception:
                pass

        if self.serial and self.serial.is_open:
            with self._write_lock:
                self.serial.close()
            logger.info("Serial connection closed")


class WindowsClipboard:
    """Minimal Windows clipboard access via WinAPI."""

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    _api_ready = False
    _user32 = None
    _kernel32 = None

    @classmethod
    def _prepare_api(cls) -> bool:
        if cls._api_ready:
            return True
        if not cls._is_supported():
            return False
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL
            user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
            user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            user32.GetClipboardData.restype = wintypes.HANDLE
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.SetClipboardData.restype = wintypes.HANDLE

            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalSize.restype = ctypes.c_size_t
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree.restype = wintypes.HGLOBAL

            cls._user32 = user32
            cls._kernel32 = kernel32
            cls._api_ready = True
            return True
        except Exception:
            return False

    @staticmethod
    def _is_supported() -> bool:
        return sys.platform.startswith("win")

    @staticmethod
    def _open_clipboard_with_retry(retries: int = 6, delay_s: float = 0.015) -> bool:
        if not WindowsClipboard._prepare_api():
            return False
        user32 = WindowsClipboard._user32
        for _ in range(max(1, retries)):
            if user32.OpenClipboard(None):
                return True
            time.sleep(delay_s)
        return False

    @classmethod
    def get_text(cls) -> Optional[str]:
        if not cls._is_supported():
            return None
        if not cls._prepare_api():
            return None
        user32 = cls._user32
        kernel32 = cls._kernel32
        if not cls._open_clipboard_with_retry():
            return None
        try:
            if not user32.IsClipboardFormatAvailable(cls.CF_UNICODETEXT):
                return ""
            handle = user32.GetClipboardData(cls.CF_UNICODETEXT)
            if not handle:
                return ""
            size_bytes = int(kernel32.GlobalSize(handle) or 0)
            if size_bytes <= 0:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                try:
                    raw = ctypes.string_at(ptr, size_bytes)
                    if not raw:
                        return ""
                    if len(raw) % 2 == 1:
                        raw = raw[:-1]
                    if not raw:
                        return ""
                    return raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]
                except (OSError, ValueError, UnicodeDecodeError):
                    return ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    @classmethod
    def set_text(cls, text: str) -> bool:
        if not cls._is_supported():
            return False
        if not cls._prepare_api():
            return False
        if text is None:
            text = ""
        text = str(text)
        if len(text) > CLIPBOARD_SYNC_MAX_TEXT_CHARS:
            text = text[:CLIPBOARD_SYNC_MAX_TEXT_CHARS]
        data = (text + "\0").encode("utf-16-le")

        kernel32 = cls._kernel32
        user32 = cls._user32

        hmem = kernel32.GlobalAlloc(cls.GMEM_MOVEABLE, len(data))
        if not hmem:
            return False
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            kernel32.GlobalFree(hmem)
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(hmem)

        if not cls._open_clipboard_with_retry():
            kernel32.GlobalFree(hmem)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(cls.CF_UNICODETEXT, hmem):
                kernel32.GlobalFree(hmem)
                return False
            hmem = None
            return True
        finally:
            user32.CloseClipboard()
            if hmem:
                kernel32.GlobalFree(hmem)


class ClipboardSyncAgent:
    """Clipboard sync logic that tunnels text frames over the ESP serial link."""

    def __init__(
        self,
        send_frame_cb: Callable[[bytes], bool],
        active_predicate: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._send_frame_cb = send_frame_cb
        self._active_predicate = active_predicate
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_local_text: Optional[str] = None
        self._last_remote_text: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        worker = self._thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)
        self._thread = None

    def handle_remote_text(self, text: str) -> None:
        if self._active_predicate is not None and not self._active_predicate():
            return
        if len(text) > CLIPBOARD_SYNC_MAX_TEXT_CHARS:
            text = text[:CLIPBOARD_SYNC_MAX_TEXT_CHARS]
        if WindowsClipboard.set_text(text):
            self._last_remote_text = text
            self._last_local_text = text
            logger.info("Clipboard synced from HID side (%d chars)", len(text))

    def _thread_main(self) -> None:
        if not WindowsClipboard._is_supported():
            logger.warning("Clipboard mode requested, but this host platform is not Windows.")
            return

        next_poll_ts = 0.0
        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                if now < next_poll_ts:
                    self._stop_event.wait(0.02)
                    continue
                next_poll_ts = now + CLIPBOARD_SYNC_POLL_INTERVAL_S

                if self._active_predicate is not None and not self._active_predicate():
                    continue

                local_text = WindowsClipboard.get_text()
                if local_text is None:
                    continue
                if len(local_text) > CLIPBOARD_SYNC_MAX_TEXT_CHARS:
                    local_text = local_text[:CLIPBOARD_SYNC_MAX_TEXT_CHARS]

                if self._last_local_text is None:
                    frame = encode_clipboard_frame(local_text)
                    if frame:
                        self._send_frame_cb(frame)
                    self._last_local_text = local_text
                    continue
                if local_text == self._last_local_text:
                    continue
                if local_text == self._last_remote_text:
                    self._last_local_text = local_text
                    continue

                frame = encode_clipboard_frame(local_text)
                if frame and self._send_frame_cb(frame):
                    self._last_local_text = local_text
                    logger.info("Clipboard synced to HID side (%d chars)", len(local_text))
            except Exception as exc:
                logger.warning("Clipboard sync polling error: %s", exc)
                self._stop_event.wait(0.1)


class Kavix32InputBridge:
    """Main application."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        settings: dict,
        layout_override: Optional[str] = None,
        language_packs_path: Optional[Path] = None,
    ):
        self.serial = SerialConnection(port, baudrate)
        self.protocol = SerialProtocol()

        keyboard_settings = settings.get("keyboard", {}) if isinstance(settings, dict) else {}
        configured_profiles = keyboard_settings.get("layout_profiles", {})
        if not isinstance(configured_profiles, dict):
            configured_profiles = {}
        configured_profiles.setdefault("us", {})

        configured_layout = sanitize_profile_name(str(keyboard_settings.get("layout", "us")) or "us")
        start_layout = sanitize_profile_name(str(layout_override or configured_layout) or "us")
        selected_pack_id = str(keyboard_settings.get("selected_pack_id", "")).strip()

        self._enable_windows_layout_tracking = _as_bool(keyboard_settings.get("use_windows_layout", False)) and sys.platform.startswith("win")
        self._windows_layout_resolver: Optional[WindowsKeyboardLayoutResolver] = None
        self._windows_klid_to_profile: Dict[str, str] = {}
        self._unknown_windows_klids: Set[str] = set()
        self._last_windows_layout_poll_ts = 0.0
        self._last_windows_klid: Optional[str] = None
        self._fallback_layout_name = start_layout or "us"

        layout_profiles = configured_profiles
        if self._enable_windows_layout_tracking:
            packs_file = language_packs_path if language_packs_path is not None else LANGUAGE_PACKS_FILE
            packs = load_language_packs(packs_file)
            layout_profiles, self._windows_klid_to_profile = build_windows_layout_mappings(
                packs,
                configured_profiles,
                preferred_pack_id=selected_pack_id,
            )
            self._windows_layout_resolver = WindowsKeyboardLayoutResolver()
            if not self._windows_layout_resolver.available:
                logger.warning("Windows keyboard layout resolver unavailable; dynamic layout remap disabled")
                self._enable_windows_layout_tracking = False

        self.input = InputCapture(start_layout, layout_profiles)
        self.mouse_input = MouseCapture()

        self.modifiers = 0
        self.active_keycode = None
        self.last_heartbeat = None
        self.heartbeat_timeout_s = 0.5
        self.heartbeat_warned = False
        self.modifier_map = self._build_modifier_map()
        self.suppressed_releases: Dict[int, int] = {}
        self._suppressed_toggle_key_releases: Set[int] = set()
        self.pressed_keycodes: Set[int] = set()
        self._pressed_vk_keycodes: Dict[int, int] = {}
        self._is_windows_platform = sys.platform.startswith("win")
        self._right_alt_pressed = False
        self.mouse_buttons = 0
        self.last_mouse_position: Optional[Tuple[int, int]] = None
        self._pre_capture_cursor_pos: Optional[Tuple[int, int]] = None
        self._mouse_lock = threading.Lock()
        self._pending_mouse_dx = 0
        self._pending_mouse_dy = 0
        self._pending_mouse_wheel = 0
        self._pending_mouse_pan = 0
        self._mouse_buttons_dirty = False
        self._mouse_worker_stop = threading.Event()
        self._mouse_worker: Optional[threading.Thread] = None
        self._mouse_log_last_ts = time.monotonic()
        self._mouse_log_dx = 0
        self._mouse_log_dy = 0
        self._mouse_log_wheel = 0
        self._mouse_log_pan = 0
        self._mouse_log_frames = 0
        self._input_listeners_started = False
        self._input_listener_lock = threading.Lock()
                                                                            
        self._use_windows_mouse_poller = False
        self._mouse_poll_worker_stop = threading.Event()
        self._mouse_poll_worker: Optional[threading.Thread] = None
        self._mouse_poll_center: Optional[Tuple[int, int]] = None
        self._use_windows_raw_mouse = sys.platform.startswith("win")
        if self._fallback_layout_name not in self.input.layout_profiles:
            self._fallback_layout_name = "us"
        self._raw_mouse_capture = (
            WindowsRawMouseCapture(self.on_mouse_raw_delta, lambda: self.capture_enabled)
            if self._use_windows_raw_mouse
            else None
        )

        capture_settings = settings.get("capture", {}) if isinstance(settings, dict) else {}
        self.capture_enabled = bool(capture_settings.get("enabled_by_default", False))
        self.capture_toggle_combo_expr = str(capture_settings.get("toggle_combo", "ctrl+f1"))
        self.capture_toggle_combo: Optional[ComboSpec] = None
        self.capture_toggle_latched = False
        self._refresh_capture_toggle_combo()
        self.input.toggle_suppress_predicate = self._should_suppress_toggle_vk
        self._maybe_sync_windows_layout(force=True)

        sharing_settings = settings.get("sharing", {}) if isinstance(settings, dict) else {}
        if not isinstance(sharing_settings, dict):
            sharing_settings = {}
        self.sharing_mode = str(sharing_settings.get("mode", "passive")).strip().lower()
        if self.sharing_mode not in {"passive", "clipboard"}:
            self.sharing_mode = "passive"
        self.clipboard_sync: Optional[ClipboardSyncAgent] = None
        self._clipboard_parser = ClipboardFrameParser()
        if self.sharing_mode == "clipboard":
            self.clipboard_sync = ClipboardSyncAgent(
                send_frame_cb=self.serial.send_packet,
                active_predicate=lambda: True,
            )

        logger.info("Keyboard layout profile: %s", self.input.layout_name)
        if self._enable_windows_layout_tracking:
            logger.info(
                "Windows keyboard layout tracking: enabled (%d KLID mappings)",
                len(self._windows_klid_to_profile),
            )
        logger.info("Mouse forwarding: enabled")
        if self._use_windows_raw_mouse:
            logger.info("Mouse mode: Windows Raw Input delta")
        elif self._use_windows_mouse_poller:
            logger.info("Mouse mode: Windows relative poller")
        else:
            logger.info("Mouse mode: event delta")
        if self.capture_toggle_combo is not None:
            logger.info(
                "Capture mode: %s (toggle: %s)",
                "ENABLED" if self.capture_enabled else "DISABLED",
                self.capture_toggle_combo_expr,
            )
        if self.sharing_mode == "clipboard":
            logger.info("Peripheral mode: Clipboard mode (via ESP USB CDC on Emulation Client PC)")
        else:
            logger.info("Peripheral mode: Passive")

    def _refresh_capture_toggle_combo(self) -> None:
        self.capture_toggle_combo = None
        try:
            self.capture_toggle_combo = parse_combo_expression(self.capture_toggle_combo_expr, self.input.char_remap)
        except ValueError as exc:
            logger.warning("Invalid capture.toggle_combo '%s': %s", self.capture_toggle_combo_expr, exc)

    def _resolve_windows_profile_from_klid(self, klid: str) -> Optional[str]:
        profile = self._windows_klid_to_profile.get(klid)
        if profile:
            return profile
        if len(klid) == 8:
            generic_klid = f"0000{klid[-4:]}"
            return self._windows_klid_to_profile.get(generic_klid)
        return None

    def _maybe_sync_windows_layout(self, force: bool = False) -> None:
        if not self._enable_windows_layout_tracking:
            return
        resolver = self._windows_layout_resolver
        if resolver is None or not resolver.available:
            return

        now = time.monotonic()
        if not force and (now - self._last_windows_layout_poll_ts) < WINDOWS_LAYOUT_POLL_INTERVAL_S:
            return
        self._last_windows_layout_poll_ts = now

        klid = resolver.current_klid()
        if not klid:
            return
        if not force and klid == self._last_windows_klid:
            return
        self._last_windows_klid = klid

        target_layout = self._resolve_windows_profile_from_klid(klid)
        if target_layout is None:
            target_layout = self._fallback_layout_name
            if klid not in self._unknown_windows_klids:
                logger.info("No language-pack profile for Windows layout %s; using '%s'", klid, target_layout)
                self._unknown_windows_klids.add(klid)

        if target_layout not in self.input.layout_profiles:
            target_layout = "us"

        if target_layout != self.input.layout_name:
            self.input.set_layout(target_layout)
            self._refresh_capture_toggle_combo()
            logger.info("Windows keyboard layout %s -> profile '%s'", klid, target_layout)

    def _build_modifier_map(self) -> dict:
        Key = self.input.keyboard.Key
        mod_map = {}

        def add_key(name: str, bit: int) -> None:
            key_obj = getattr(Key, name, None)
            if key_obj is not None:
                mod_map[key_obj] = bit

        add_key("shift", self.protocol.MOD_LEFT_SHIFT)
        add_key("shift_l", self.protocol.MOD_LEFT_SHIFT)
        add_key("shift_r", self.protocol.MOD_RIGHT_SHIFT)
        add_key("ctrl", self.protocol.MOD_LEFT_CTRL)
        add_key("ctrl_l", self.protocol.MOD_LEFT_CTRL)
        add_key("ctrl_r", self.protocol.MOD_RIGHT_CTRL)
        add_key("alt", self.protocol.MOD_LEFT_ALT)
        add_key("alt_l", self.protocol.MOD_LEFT_ALT)
        add_key("alt_r", self.protocol.MOD_RIGHT_ALT)
        add_key("alt_gr", self.protocol.MOD_RIGHT_ALT)
        add_key("cmd", self.protocol.MOD_LEFT_GUI)
        add_key("cmd_l", self.protocol.MOD_LEFT_GUI)
        add_key("cmd_r", self.protocol.MOD_RIGHT_GUI)

        return mod_map

    def _is_left_ctrl_modifier_key(self, key) -> bool:
        vk = key_to_vk(key)
        if isinstance(vk, int):
            return vk in (0xA2, 0x11)                            
        left_ctrl = getattr(self.input.keyboard.Key, "ctrl_l", None)
        return left_ctrl is not None and key == left_ctrl

    def _is_right_alt_modifier_key(self, key) -> bool:
        vk = key_to_vk(key)
        if isinstance(vk, int):
            return vk == 0xA5            
        Key = self.input.keyboard.Key
        alt_r = getattr(Key, "alt_r", None)
        alt_gr = getattr(Key, "alt_gr", None)
        return (alt_r is not None and key == alt_r) or (alt_gr is not None and key == alt_gr)

    def _send_keyboard_packet(self, key_code: int, modifiers: int, action: int) -> bool:
        packet = self.protocol.encode_keyboard(key_code, modifiers, action)
        return self.serial.send_packet(packet)

    def _send_mouse_move_packet(self, buttons: int, delta_x: int, delta_y: int) -> bool:
        packet = self.protocol.encode_mouse_move(buttons, delta_x, delta_y)
        return self.serial.send_packet(packet)

    def _send_mouse_wheel_packet(self, buttons: int, wheel: int, pan: int = 0) -> bool:
        packet = self.protocol.encode_mouse_wheel(buttons, wheel, pan)
        return self.serial.send_packet(packet)

    @staticmethod
    def _clamp_i8(value: int) -> int:
        return max(-127, min(127, int(value)))

    @staticmethod
    def _clamp_accum(value: int) -> int:
        return max(-MOUSE_ACCUM_LIMIT, min(MOUSE_ACCUM_LIMIT, int(value)))

    def _send_state_update(self) -> None:
        keycode = self.active_keycode or 0
        self._send_keyboard_packet(keycode, self.modifiers, self.protocol.KEY_ACTION_PRESS)

    def _release_remote_state(self) -> None:
        self.active_keycode = None
        self._send_keyboard_packet(0, 0, self.protocol.KEY_ACTION_PRESS)
        with self._mouse_lock:
            self.mouse_buttons = 0
            self._pending_mouse_dx = 0
            self._pending_mouse_dy = 0
            self._pending_mouse_wheel = 0
            self._pending_mouse_pan = 0
            self._mouse_buttons_dirty = False
        self._send_mouse_move_packet(0, 0, 0)

    def _accumulate_mouse_delta(self, dx: int, dy: int) -> None:
        with self._mouse_lock:
            self._pending_mouse_dx = self._clamp_accum(self._pending_mouse_dx + dx)
            self._pending_mouse_dy = self._clamp_accum(self._pending_mouse_dy + dy)

    def _accumulate_mouse_wheel(self, wheel: int, pan: int) -> None:
        with self._mouse_lock:
            self._pending_mouse_wheel = self._clamp_accum(self._pending_mouse_wheel + wheel)
            self._pending_mouse_pan = self._clamp_accum(self._pending_mouse_pan + pan)

    def _set_mouse_button(self, bit: int, pressed: bool) -> None:
        with self._mouse_lock:
            if pressed:
                self.mouse_buttons |= bit
            else:
                self.mouse_buttons &= ~bit
            if self.capture_enabled:
                self._mouse_buttons_dirty = True

    def _drain_mouse_frames(self):
        with self._mouse_lock:
            if not self.capture_enabled:
                self._pending_mouse_dx = 0
                self._pending_mouse_dy = 0
                self._pending_mouse_wheel = 0
                self._pending_mouse_pan = 0
                self._mouse_buttons_dirty = False
                return None, None

            buttons = self.mouse_buttons

            send_move = False
            move_dx = 0
            move_dy = 0
            if self._pending_mouse_dx != 0 or self._pending_mouse_dy != 0:
                move_dx = self._clamp_i8(self._pending_mouse_dx)
                move_dy = self._clamp_i8(self._pending_mouse_dy)
                self._pending_mouse_dx -= move_dx
                self._pending_mouse_dy -= move_dy
                send_move = True
            if self._mouse_buttons_dirty:
                self._mouse_buttons_dirty = False
                send_move = True

            send_wheel = False
            wheel = 0
            pan = 0
            if self._pending_mouse_wheel != 0 or self._pending_mouse_pan != 0:
                wheel = self._clamp_i8(self._pending_mouse_wheel)
                pan = self._clamp_i8(self._pending_mouse_pan)
                self._pending_mouse_wheel -= wheel
                self._pending_mouse_pan -= pan
                send_wheel = True

        move_frame = (buttons, move_dx, move_dy) if send_move else None
        wheel_frame = (buttons, wheel, pan) if send_wheel else None
        return move_frame, wheel_frame

    def _mouse_sender_loop(self) -> None:
        while not self._mouse_worker_stop.wait(MOUSE_SEND_INTERVAL_S):
            for _ in range(MOUSE_SEND_BURST):
                move_frame, wheel_frame = self._drain_mouse_frames()
                if move_frame is None and wheel_frame is None:
                    break
                if move_frame is not None:
                    self._send_mouse_move_packet(*move_frame)
                    self._mouse_log_dx += move_frame[1]
                    self._mouse_log_dy += move_frame[2]
                    self._mouse_log_frames += 1
                if wheel_frame is not None:
                    self._send_mouse_wheel_packet(*wheel_frame)
                    self._mouse_log_wheel += wheel_frame[1]
                    self._mouse_log_pan += wheel_frame[2]
                    self._mouse_log_frames += 1

            now = time.monotonic()
            if now - self._mouse_log_last_ts >= MOUSE_LOG_INTERVAL_S and self._mouse_log_frames > 0:
                logger.info(
                    "MOUSE tx dx=%d dy=%d wheel=%d pan=%d frames=%d",
                    self._mouse_log_dx,
                    self._mouse_log_dy,
                    self._mouse_log_wheel,
                    self._mouse_log_pan,
                    self._mouse_log_frames,
                )
                self._mouse_log_last_ts = now
                self._mouse_log_dx = 0
                self._mouse_log_dy = 0
                self._mouse_log_wheel = 0
                self._mouse_log_pan = 0
                self._mouse_log_frames = 0

    def _start_mouse_worker(self) -> None:
        if self._mouse_worker is not None and self._mouse_worker.is_alive():
            return
        self._mouse_worker_stop.clear()
        self._mouse_worker = threading.Thread(target=self._mouse_sender_loop, daemon=True)
        self._mouse_worker.start()

    def _stop_mouse_worker(self) -> None:
        self._mouse_worker_stop.set()
        worker = self._mouse_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=0.5)
        self._mouse_worker = None

    @staticmethod
    def _get_windows_screen_center() -> Optional[Tuple[int, int]]:
        try:
            user32 = ctypes.windll.user32
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            if width <= 0 or height <= 0:
                return None
            return width // 2, height // 2
        except Exception:
            return None

    @staticmethod
    def _get_windows_cursor_pos() -> Optional[Tuple[int, int]]:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        try:
            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            return None
        return None

    @staticmethod
    def _set_windows_cursor_pos(x: int, y: int) -> None:
        try:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        except Exception:
            pass

    def _windows_mouse_poller_loop(self) -> None:
        was_enabled = False
        last_pos: Optional[Tuple[int, int]] = None
        while not self._mouse_poll_worker_stop.wait(MOUSE_SEND_INTERVAL_S):
            if not self.capture_enabled:
                if was_enabled:
                    self._mouse_poll_center = None
                    last_pos = None
                was_enabled = False
                continue

            if not was_enabled or self._mouse_poll_center is None:
                center = self._get_windows_screen_center()
                if center is None:
                    continue
                self._mouse_poll_center = center
                self._set_windows_cursor_pos(center[0], center[1])
                last_pos = None
                was_enabled = True
                continue

            pos = self._get_windows_cursor_pos()
            if pos is None:
                continue

            if last_pos is None:
                last_pos = pos
            else:
                dx = int(pos[0] - last_pos[0])
                dy = int(pos[1] - last_pos[1])
                last_pos = pos
                if dx != 0 or dy != 0:
                    self._accumulate_mouse_delta(dx, dy)

            center_x, center_y = self._mouse_poll_center
            if pos[0] != center_x or pos[1] != center_y:
                                                                          
                self._set_windows_cursor_pos(center_x, center_y)
                last_pos = None

    def _start_windows_mouse_poller(self) -> None:
        if not self._use_windows_mouse_poller:
            return
        if self._mouse_poll_worker is not None and self._mouse_poll_worker.is_alive():
            return
        self._mouse_poll_worker_stop.clear()
        self._mouse_poll_worker = threading.Thread(target=self._windows_mouse_poller_loop, daemon=True)
        self._mouse_poll_worker.start()

    def _stop_windows_mouse_poller(self) -> None:
        self._mouse_poll_worker_stop.set()
        worker = self._mouse_poll_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=0.5)
        self._mouse_poll_worker = None
        self._mouse_poll_center = None

    def _start_input_listeners(self) -> None:
        with self._input_listener_lock:
            if self._input_listeners_started:
                return
            self.last_mouse_position = None
            self.input.start_listening(self.on_press, self.on_release, self._should_block_local_input)
            self.mouse_input.start_listening(
                self.on_mouse_move,
                self.on_mouse_click,
                self.on_mouse_scroll,
                self._should_block_local_mouse_input,
            )
            if self._raw_mouse_capture is not None:
                self._raw_mouse_capture.start()
            self._input_listeners_started = True

    def _stop_input_listeners(self) -> None:
        with self._input_listener_lock:
            if not self._input_listeners_started:
                return
            if self._raw_mouse_capture is not None:
                self._raw_mouse_capture.stop()
            self.input.stop_listening()
            self.mouse_input.stop_listening()
            self._input_listeners_started = False
            self.last_mouse_position = None

    def _mark_suppressed_release(self, key_code: int) -> None:
        self.suppressed_releases[key_code] = self.suppressed_releases.get(key_code, 0) + 1

    def _is_suppressed_release(self, key_code: int) -> bool:
        count = self.suppressed_releases.get(key_code, 0)
        if count <= 0:
            return False
        if count == 1:
            self.suppressed_releases.pop(key_code, None)
        else:
            self.suppressed_releases[key_code] = count - 1
        return True

    def _toggle_combo_keycode_from_vk(self, vk: int) -> Optional[int]:
        key_code = vk_to_hid(vk)
        if key_code is not None:
            return key_code
        candidate_char = vk_to_char(vk)
        if candidate_char is None:
            return None
        return char_to_hid(candidate_char, self.input.char_remap)

    def _should_suppress_toggle_vk(self, vk: int, msg: int) -> bool:
        self._maybe_sync_windows_layout()
        combo = self.capture_toggle_combo
        if combo is None:
            return False

        is_key_down = msg in (0x0100, 0x0104)                              
        is_key_up = msg in (0x0101, 0x0105)                            
        if not is_key_down and not is_key_up:
            return False

        mod_bit = VK_TO_MODIFIER_BIT.get(vk)
        key_code = None if mod_bit is not None else self._toggle_combo_keycode_from_vk(vk)

        if is_key_up:
            if key_code is not None and key_code in self._suppressed_toggle_key_releases:
                self._suppressed_toggle_key_releases.discard(key_code)
                return True
            return False

        required_modifiers, required_keys = combo
        candidate_modifiers = self.modifiers | (mod_bit or 0)
        candidate_keys = set(self.pressed_keycodes)
        if key_code is not None:
            candidate_keys.add(key_code)

        if (candidate_modifiers & required_modifiers) != required_modifiers:
            return False
        if key_code is None or key_code not in required_keys:
            return False

        self._suppressed_toggle_key_releases.add(key_code)
        return True

    def _combo_is_active(self, combo: Optional[ComboSpec]) -> bool:
        if combo is None:
            return False
        required_modifiers, required_keys = combo
        if (self.modifiers & required_modifiers) != required_modifiers:
            return False
        return all(required_key in self.pressed_keycodes for required_key in required_keys)

    def _toggle_capture_mode(self) -> None:
        entering_capture = not self.capture_enabled
        if entering_capture and sys.platform.startswith("win"):
            self._pre_capture_cursor_pos = self._get_windows_cursor_pos()

        self.suppressed_releases.clear()
        self._suppressed_toggle_key_releases.clear()
        if self.capture_enabled and self.capture_toggle_combo is not None:
            _mods, required_keys = self.capture_toggle_combo
            self._suppressed_toggle_key_releases.update(required_keys)
        self.capture_enabled = not self.capture_enabled
        self.modifiers = 0
        self._right_alt_pressed = False
        self.pressed_keycodes.clear()
        self._pressed_vk_keycodes.clear()
        self.capture_toggle_latched = False
        self.last_mouse_position = None
        self.input.set_blocking(self.capture_enabled)
        self.mouse_input.set_blocking(self._should_block_local_mouse_input())
        self._release_remote_state()

        if (not self.capture_enabled) and sys.platform.startswith("win") and self._pre_capture_cursor_pos is not None:
            restore_x, restore_y = self._pre_capture_cursor_pos
            self._pre_capture_cursor_pos = None
            self._set_windows_cursor_pos(restore_x, restore_y)

                                                                                              
            def _restore_once_later() -> None:
                self._set_windows_cursor_pos(restore_x, restore_y)

            threading.Thread(target=lambda: (time.sleep(0.02), _restore_once_later()), daemon=True).start()

        logger.info("Capture mode %s", "ENABLED" if self.capture_enabled else "DISABLED")

    def _send_combo_tuple(self, combo: ComboSpec, hold_s: float = 0.03) -> None:
        modifiers, key_codes = combo

        if not key_codes and modifiers == 0:
            return

        if not key_codes:
            self._send_keyboard_packet(0, modifiers, self.protocol.KEY_ACTION_PRESS)
            time.sleep(hold_s)
            self._send_keyboard_packet(0, 0, self.protocol.KEY_ACTION_PRESS)
            return

        key_code = key_codes[-1]
        self._send_keyboard_packet(key_code, modifiers, self.protocol.KEY_ACTION_PRESS)
        time.sleep(hold_s)
        self._send_keyboard_packet(key_code, modifiers, self.protocol.KEY_ACTION_RELEASE)

        if modifiers:
            self._send_keyboard_packet(0, 0, self.protocol.KEY_ACTION_PRESS)

    def _should_block_local_input(self) -> bool:
        return self.capture_enabled

    def _should_block_local_mouse_input(self) -> bool:
        return self.capture_enabled

    def _remember_pressed_keycode(self, key, keycode: Optional[int]) -> None:
        if keycode is None:
            return
        vk = key_to_vk(key)
        if vk is None:
            return
        self._pressed_vk_keycodes[int(vk)] = int(keycode)

    def _resolve_release_keycode(self, key) -> Optional[int]:
        vk = key_to_vk(key)
        if vk is not None:
            remembered = self._pressed_vk_keycodes.pop(int(vk), None)
            if remembered is not None:
                return remembered
        return self.input.pynput_key_to_hid(key)

    def on_press(self, key):
        self._maybe_sync_windows_layout()
        mod_bit = self.modifier_map.get(key)
        keycode = None

        if mod_bit is not None:
            if self._is_windows_platform and self._is_right_alt_modifier_key(key):
                                                                  
                                                                            
                self._right_alt_pressed = True
                self.modifiers |= self.protocol.MOD_RIGHT_ALT
                self.modifiers &= ~self.protocol.MOD_LEFT_CTRL
            elif self._is_windows_platform and self._is_left_ctrl_modifier_key(key) and self._right_alt_pressed:
                                                                       
                pass
            else:
                self.modifiers |= mod_bit
        else:
            keycode = self.input.pynput_key_to_hid(key)
            if keycode is not None:
                self.pressed_keycodes.add(keycode)
                self._remember_pressed_keycode(key, keycode)

        toggle_active = self._combo_is_active(self.capture_toggle_combo)
        if toggle_active:
            if not self.capture_toggle_latched:
                self.capture_toggle_latched = True
                self._toggle_capture_mode()
            if keycode is not None:
                self._mark_suppressed_release(keycode)
            return

        if self.capture_toggle_latched and not toggle_active:
            self.capture_toggle_latched = False

        if not self.capture_enabled:
            return

        if mod_bit is not None:
            self._send_state_update()
            return

        if keycode is None:
            return

        self._send_keyboard_packet(keycode, self.modifiers, self.protocol.KEY_ACTION_PRESS)
        self.active_keycode = keycode
        logger.debug("PRESS: keycode=%02x, modifiers=%02x", keycode, self.modifiers)

    def on_release(self, key):
        self._maybe_sync_windows_layout()
        mod_bit = self.modifier_map.get(key)
        keycode = None

        if mod_bit is not None:
            if self._is_windows_platform and self._is_right_alt_modifier_key(key):
                self._right_alt_pressed = False
                self.modifiers &= ~self.protocol.MOD_RIGHT_ALT
            elif self._is_windows_platform and self._is_left_ctrl_modifier_key(key) and self._right_alt_pressed:
                                                                       
                pass
            else:
                self.modifiers &= ~mod_bit
        else:
            keycode = self._resolve_release_keycode(key)
            if keycode is not None:
                self.pressed_keycodes.discard(keycode)

        toggle_active = self._combo_is_active(self.capture_toggle_combo)
        if self.capture_toggle_latched and not toggle_active:
            self.capture_toggle_latched = False

        if keycode is not None and self._is_suppressed_release(keycode):
            return

        if not self.capture_enabled:
            return

        if mod_bit is not None:
            self._send_state_update()
            return

        if keycode is None:
            return

        self._send_keyboard_packet(keycode, self.modifiers, self.protocol.KEY_ACTION_RELEASE)
        if self.active_keycode == keycode:
            self.active_keycode = None
        logger.debug("RELEASE: keycode=%02x, modifiers=%02x", keycode, self.modifiers)

    def on_mouse_move(self, x, y):
        if self._use_windows_mouse_poller or self._use_windows_raw_mouse:
            return

        pos = (int(x), int(y))
        if self.last_mouse_position is None:
            self.last_mouse_position = pos
            return

        dx = pos[0] - self.last_mouse_position[0]
        dy = pos[1] - self.last_mouse_position[1]
        self.last_mouse_position = pos

        if not self.capture_enabled:
            return
        if dx == 0 and dy == 0:
            return

        self._accumulate_mouse_delta(dx, dy)

    def on_mouse_raw_delta(self, dx: int, dy: int) -> None:
        if not self.capture_enabled:
            return
        if dx == 0 and dy == 0:
            return
        self._accumulate_mouse_delta(int(dx), int(dy))

    def on_mouse_click(self, x, y, button, pressed):
        bit = self.mouse_input.button_bit(button)
        if bit == 0:
            return

        self._set_mouse_button(bit, pressed)

    def on_mouse_scroll(self, x, y, dx, dy):
        if not self.capture_enabled:
            return

        wheel = self._clamp_i8(dy)
        pan = self._clamp_i8(dx)
        if wheel == 0 and pan == 0:
            return

        self._accumulate_mouse_wheel(wheel, pan)

    def _process_serial(self, data: bytes) -> None:
        for b in data:
            if b == self.protocol.PKT_TYPE_HEARTBEAT:
                self.last_heartbeat = time.monotonic()
                self.heartbeat_warned = False
        if self.clipboard_sync is not None:
            for text in self._clipboard_parser.feed(data):
                logger.info("Clipboard frame received from HID side (%d chars)", len(text))
                self.clipboard_sync.handle_remote_text(text)

    def run(self):
        try:
            logger.info("Kavix32 Master PC runtime started. Press Ctrl+C to stop.")
            if self.clipboard_sync is not None:
                self.clipboard_sync.start()
            self._start_mouse_worker()
            self._start_windows_mouse_poller()
            self._start_input_listeners()
            self.last_heartbeat = time.monotonic()

            while True:
                data = self.serial.read_available()
                if data:
                    self._process_serial(data)

                if self.last_heartbeat is not None:
                    elapsed = time.monotonic() - self.last_heartbeat
                    if elapsed > self.heartbeat_timeout_s and not self.heartbeat_warned:
                        logger.warning("No heartbeat from device for %.1fs", elapsed)
                        self.heartbeat_warned = True

                time.sleep(0.05)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.clipboard_sync is not None:
                self.clipboard_sync.stop()
            self._stop_windows_mouse_poller()
            self._stop_mouse_worker()
            self._release_remote_state()
            self._stop_input_listeners()
            self.serial.close()


def main():
    parser = argparse.ArgumentParser(description="Kavix32 Master PC Client")
    parser.add_argument("--settings", default=str(ROOT_DIR / "config.json"), help="Path to config JSON")
    parser.add_argument("--port", help="Serial port (overrides config JSON)")
    parser.add_argument("--baud", type=int, help="Baud rate (overrides config JSON)")
    parser.add_argument("--layout", help="Keyboard layout profile name (overrides config JSON)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    settings_path = Path(args.settings)
    settings = load_settings(settings_path)

    serial_settings = settings.get("serial", {}) if isinstance(settings, dict) else {}
    keyboard_settings = settings.get("keyboard", {}) if isinstance(settings, dict) else {}

    port = args.port or serial_settings.get("port", "COM7")
    baud = args.baud or int(serial_settings.get("baud", 460800))
    layout = args.layout or keyboard_settings.get("layout", "us")
    language_packs_path = settings_path.with_name("language_packs.json")
    if not language_packs_path.exists():
        language_packs_path = LANGUAGE_PACKS_FILE

    switcher = Kavix32InputBridge(
        port,
        baud,
        settings=settings,
        layout_override=layout,
        language_packs_path=language_packs_path,
    )
    switcher.run()


if __name__ == "__main__":
    main()
