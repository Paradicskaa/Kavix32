"""
Kavix32 HID Client (Linux/Debian)

Runs on the Emulation Client PC and syncs clipboard text with the Kavix32 Master PC
runtime over the ESP USB CDC serial interface.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import serial
from serial.tools import list_ports

try:
    import pyperclip
except Exception:
    pyperclip = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("hid_pc_client")

APP_CONFIG_DIR_NAME = "kavix32-hid-client"
BUNDLED_CONFIG_PATH = Path(__file__).with_name("hid_client_config.json")
DEFAULT_CONFIG: Dict[str, Any] = {
    "serial_port": "",
    "baud": 460800,
    "poll_interval_ms": 300,
    "force_resend_ms": 2000,
    "max_text_chars": 65536,
    "connect_retry_ms": 1200,
    "target_vid": "303A",
    "target_pid": "4004",
}


def _xdg_config_home() -> Path:
    xdg_home = str(os.environ.get("XDG_CONFIG_HOME", "")).strip()
    if xdg_home:
        return Path(xdg_home)
    return Path.home() / ".config"


def _resolve_config_path(default_payload: Dict[str, Any]) -> Path:
    bundled_path = BUNDLED_CONFIG_PATH
    user_config_dir = _xdg_config_home() / APP_CONFIG_DIR_NAME
    user_config_path = user_config_dir / "hid_client_config.json"

    if bundled_path.exists() and os.access(bundled_path, os.W_OK):
        return bundled_path
    if user_config_path.exists():
        return user_config_path

    try:
        user_config_dir.mkdir(parents=True, exist_ok=True)
        if bundled_path.exists():
            user_config_path.write_text(bundled_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            user_config_path.write_text(json.dumps(default_payload, indent=2), encoding="utf-8")
        return user_config_path
    except Exception:
        return bundled_path


CONFIG_PATH = _resolve_config_path(DEFAULT_CONFIG)

CLIPBOARD_FRAME_START = 0x7D
CLIPBOARD_FRAME_TYPE_TEXT = 0x01
CLIPBOARD_FRAME_MAX_PAYLOAD = 4096


class SystemClipboard:
    _backend: Optional[Tuple[str, Optional[str], Optional[str]]] = None
    _backend_warned = False

    @classmethod
    def _pick_backend(cls) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        if cls._backend is not None:
            return cls._backend

        wayland = bool(str(os.environ.get("WAYLAND_DISPLAY", "")).strip())
        if shutil.which("wl-copy") and shutil.which("wl-paste"):
            cls._backend = ("wl", "wl-copy", "wl-paste")
            return cls._backend
        if shutil.which("xclip"):
            cls._backend = ("xclip", "xclip", "xclip")
            return cls._backend
        if shutil.which("xsel"):
            cls._backend = ("xsel", "xsel", "xsel")
            return cls._backend
        if pyperclip is not None:
            cls._backend = ("pyperclip", None, None)
            return cls._backend

        if not cls._backend_warned:
            cls._backend_warned = True
            if wayland:
                logger.warning("No clipboard backend found. Install wl-clipboard.")
            else:
                logger.warning("No clipboard backend found. Install xclip or xsel.")
        return None

    @staticmethod
    def _run_capture(args: List[str]) -> Optional[str]:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=1.5,
            )
            if result.returncode != 0:
                return ""
            return result.stdout
        except Exception:
            return None

    @staticmethod
    def _run_set(args: List[str], text: str) -> bool:
        try:
            result = subprocess.run(
                args,
                check=False,
                input=text,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=1.5,
            )
            return result.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_text(cls) -> Optional[str]:
        backend = cls._pick_backend()
        if backend is None:
            return ""
        kind = backend[0]

        if kind == "wl":
            text = cls._run_capture(["wl-paste", "--type", "text/plain"])
            return text if text is not None else ""
        if kind == "xclip":
            text = cls._run_capture(["xclip", "-selection", "clipboard", "-o"])
            return text if text is not None else ""
        if kind == "xsel":
            text = cls._run_capture(["xsel", "--clipboard", "--output"])
            return text if text is not None else ""
        if kind == "pyperclip" and pyperclip is not None:
            try:
                return str(pyperclip.paste() or "")
            except Exception:
                return ""
        return ""

    @classmethod
    def set_text(cls, text: str) -> bool:
        payload = str(text or "")
        backend = cls._pick_backend()
        if backend is None:
            return False
        kind = backend[0]

        if kind == "wl":
            return cls._run_set(["wl-copy", "--type", "text/plain"], payload)
        if kind == "xclip":
            return cls._run_set(["xclip", "-selection", "clipboard"], payload)
        if kind == "xsel":
            return cls._run_set(["xsel", "--clipboard", "--input"], payload)
        if kind == "pyperclip" and pyperclip is not None:
            try:
                pyperclip.copy(payload)
                return True
            except Exception:
                return False
        return False


def crc8(data: bytes) -> int:
    value = 0x00
    for byte in data:
        value ^= byte
        for _ in range(8):
            if value & 0x80:
                value = ((value << 1) ^ 0x07) & 0xFF
            else:
                value = (value << 1) & 0xFF
    return value


def encode_clipboard_frame(text: str, max_text_chars: int) -> Optional[bytes]:
    if text is None:
        text = ""
    text = str(text)
    if len(text) > max_text_chars:
        text = text[:max_text_chars]
    payload = text.encode("utf-8", errors="ignore")
    if len(payload) > CLIPBOARD_FRAME_MAX_PAYLOAD:
        payload = payload[:CLIPBOARD_FRAME_MAX_PAYLOAD]
    payload_len = len(payload)
    header = bytes([CLIPBOARD_FRAME_TYPE_TEXT, (payload_len >> 8) & 0xFF, payload_len & 0xFF])
    checksum = crc8(header + payload)
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
            checksum_actual = crc8(frame[1:-1])
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


def _parse_hex_u16(value: Any, fallback: int) -> int:
    raw = str(value if value is not None else "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    try:
        parsed = int(raw, 16)
    except Exception:
        return fallback
    return max(0, min(0xFFFF, parsed))


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config root must be an object")
    except Exception as exc:
        logger.warning("Failed to parse config (%s). Using defaults.", exc)
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(loaded)
    merged["serial_port"] = str(merged.get("serial_port", "")).strip()
    try:
        merged["baud"] = int(merged.get("baud", 460800))
    except Exception:
        merged["baud"] = 460800
    merged["baud"] = max(9600, min(2000000, merged["baud"]))
    try:
        merged["poll_interval_ms"] = int(merged.get("poll_interval_ms", 300))
    except Exception:
        merged["poll_interval_ms"] = 300
    merged["poll_interval_ms"] = max(50, min(5000, merged["poll_interval_ms"]))
    try:
        merged["force_resend_ms"] = int(merged.get("force_resend_ms", 2000))
    except Exception:
        merged["force_resend_ms"] = 2000
    merged["force_resend_ms"] = max(250, min(30000, merged["force_resend_ms"]))
    try:
        merged["connect_retry_ms"] = int(merged.get("connect_retry_ms", 1200))
    except Exception:
        merged["connect_retry_ms"] = 1200
    merged["connect_retry_ms"] = max(100, min(10000, merged["connect_retry_ms"]))
    try:
        merged["max_text_chars"] = int(merged.get("max_text_chars", 65536))
    except Exception:
        merged["max_text_chars"] = 65536
    merged["max_text_chars"] = max(128, min(500000, merged["max_text_chars"]))
    merged["target_vid"] = _parse_hex_u16(merged.get("target_vid", "303A"), 0x303A)
    merged["target_pid"] = _parse_hex_u16(merged.get("target_pid", "4004"), 0x4004)
    return merged


def _port_label(port_info: Any) -> str:
    details = " | ".join(
        value
        for value in (
            str(getattr(port_info, "description", "") or "").strip(),
            str(getattr(port_info, "manufacturer", "") or "").strip(),
            str(getattr(port_info, "product", "") or "").strip(),
        )
        if value
    )
    return f"{port_info.device} — {details}" if details else str(port_info.device)


def _choose_port(port_infos: List[Any]) -> Optional[str]:
    logger.info("Several serial ports are available:")
    for index, port_info in enumerate(port_infos, start=1):
        logger.info("  %d. %s", index, _port_label(port_info))

    try:
        answer = input("Choose the Kavix32 serial port number: ").strip()
    except EOFError:
        logger.error("No interactive console is available. Set serial_port in hid_client_config.json.")
        return None

    try:
        index = int(answer)
    except ValueError:
        logger.warning("Enter a number from 1 to %d.", len(port_infos))
        return None

    if not 1 <= index <= len(port_infos):
        logger.warning("Enter a number from 1 to %d.", len(port_infos))
        return None
    return str(port_infos[index - 1].device)


def find_target_port(config: Dict[str, Any], selected_port: str = "") -> Optional[str]:
    explicit_port = str(config.get("serial_port", "")).strip()
    if explicit_port:
        return explicit_port

    target_vid = int(config.get("target_vid", 0x303A))
    target_pid = int(config.get("target_pid", 0x4004))
    port_infos = sorted(list(list_ports.comports()), key=lambda port: str(port.device).lower())
    matching_ports = []

    for port_info in port_infos:
        text = f"{port_info.description} {port_info.manufacturer} {port_info.product}".lower()
        if (
            (port_info.vid == target_vid and port_info.pid == target_pid)
            or "kavix32" in text
            or "esp32" in text
        ):
            matching_ports.append(port_info)

    candidates = matching_ports + [port_info for port_info in port_infos if port_info not in matching_ports]
    if selected_port and any(str(port_info.device) == selected_port for port_info in candidates):
        return selected_port
    if len(candidates) == 1:
        return str(candidates[0].device)
    if len(candidates) > 1:
        return _choose_port(candidates)
    return None


def open_serial_no_reset(port: str, baud: int) -> serial.Serial:
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = int(baud)
    ser.timeout = 0
    ser.write_timeout = 1
    ser.dtr = False
    ser.rts = False
    ser.dsrdtr = False
    ser.rtscts = False
    ser.xonxoff = False
    ser.open()
    return ser


class ClipboardSerialClient:
    def __init__(
        self,
        config: Dict[str, Any],
        stop_event: Optional[threading.Event] = None,
        on_state: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.poll_interval_s = float(config["poll_interval_ms"]) / 1000.0
        self.force_resend_s = float(config["force_resend_ms"]) / 1000.0
        self.retry_interval_s = float(config["connect_retry_ms"]) / 1000.0
        self.max_text_chars = int(config["max_text_chars"])
        self._last_local_text: Optional[str] = None
        self._last_remote_text: Optional[str] = None
        self._last_sent_ts: float = 0.0
        self._last_wait_log_ts = 0.0
        self._stop_event = stop_event or threading.Event()
        self._on_state = on_state
        self._selected_port = ""

    def _apply_remote_text(self, text: str) -> None:
        if len(text) > self.max_text_chars:
            text = text[: self.max_text_chars]
        if SystemClipboard.set_text(text):
            self._last_remote_text = text
            self._last_local_text = text
            logger.info("Clipboard synced from master (%d chars)", len(text))

    def _send_local_text(self, ser: serial.Serial, local_text: str, reason: str) -> bool:
        frame = encode_clipboard_frame(local_text, self.max_text_chars)
        if not frame:
            return False
        try:
            ser.write(frame)
            self._last_local_text = local_text
            self._last_sent_ts = time.monotonic()
            logger.info("Clipboard synced to master (%d chars, %s)", len(local_text), reason)
            return True
        except Exception as exc:
            logger.warning("Failed to send clipboard to master: %s", exc)
            return False

    def _sleep_or_stop(self, seconds: float) -> bool:
        seconds = max(0.0, float(seconds))
        return self._stop_event.wait(seconds)

    def _notify_state(self, state: str) -> None:
        if self._on_state is None:
            return
        try:
            self._on_state(str(state))
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()

    def _session(self, ser: serial.Serial) -> None:
        parser = ClipboardFrameParser()
        self._last_local_text = SystemClipboard.get_text()
        self._last_sent_ts = 0.0
        next_poll_ts = 0.0

        while not self._stop_event.is_set():
            try:
                waiting = ser.in_waiting
            except Exception:
                break

            if waiting:
                try:
                    chunk = ser.read(waiting)
                except Exception:
                    break
                for text in parser.feed(chunk):
                    self._apply_remote_text(text)

            now = time.monotonic()
            if now >= next_poll_ts:
                next_poll_ts = now + self.poll_interval_s
                try:
                    local_text = SystemClipboard.get_text()
                except Exception as exc:
                    logger.warning("Clipboard read error: %s", exc)
                    local_text = None
                if local_text is not None:
                    if len(local_text) > self.max_text_chars:
                        local_text = local_text[: self.max_text_chars]
                    if self._last_local_text is None:
                        if not self._send_local_text(ser, local_text, "initial"):
                            break
                    elif local_text != self._last_local_text and local_text != self._last_remote_text:
                        if not self._send_local_text(ser, local_text, "change"):
                            break
                    elif (
                        self.force_resend_s > 0.0
                        and local_text == self._last_local_text
                        and local_text != self._last_remote_text
                        and (now - self._last_sent_ts) >= self.force_resend_s
                    ):
                        if not self._send_local_text(ser, local_text, "resend"):
                            break

            if self._sleep_or_stop(0.01):
                break

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            port = find_target_port(self.config, self._selected_port)
            if not port:
                self._selected_port = ""
                now = time.monotonic()
                if (now - self._last_wait_log_ts) > 5.0:
                    self._last_wait_log_ts = now
                    self._notify_state("waiting")
                    logger.info("No serial port found. Waiting...")
                if self._sleep_or_stop(self.retry_interval_s):
                    break
                continue

            self._selected_port = port
            try:
                ser = open_serial_no_reset(port, int(self.config["baud"]))
            except Exception as exc:
                logger.warning("Failed to open serial port %s: %s", port, exc)
                self._notify_state("disconnected")
                if self._sleep_or_stop(self.retry_interval_s):
                    break
                continue

            self._notify_state(f"connected:{port}")
            logger.info("Connected to ESP CDC serial: %s @ %d", port, int(self.config["baud"]))
            should_stop = False
            try:
                self._session(ser)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
                self._notify_state("disconnected")
                logger.info("Disconnected from %s", port)
                should_stop = self._sleep_or_stop(self.retry_interval_s)
            if should_stop:
                break


def main() -> None:
    config = load_config(CONFIG_PATH)
    logger.info("Config loaded from %s", CONFIG_PATH)
    logger.info(
        "Clipboard mode over ESP CDC serial (VID:PID %04X:%04X)",
        int(config["target_vid"]),
        int(config["target_pid"]),
    )

    client = ClipboardSerialClient(config)
    try:
        client.run_forever()
    except KeyboardInterrupt:
        logger.info("Stopping...")


if __name__ == "__main__":
    main()
