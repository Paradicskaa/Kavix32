                      
"""Kavix32 UI for configuring and launching the Master PC runtime."""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter.font as tkfont
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None

try:
    import pystray
except Exception:
    pystray = None
FIXED_BAUD = 460800
SERIAL_FRAME_START = 0x7E
STATUS_PROBE_BASE_TIMEOUT_S = 1.6
STATUS_PROBE_MOUNT_WAIT_S = 2.6
STATUS_PROBE_PING_INTERVAL_S = 0.25
ROOT_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
DEFAULT_CONFIG_FILE = ROOT_DIR / "config.json"
LEGACY_SETTINGS_FILE = ROOT_DIR / "settings.json"
LANGUAGE_PACKS_FILE = ROOT_DIR / "language_packs.json"
TRAY_ICON_DIR = ROOT_DIR / "assets" / "icon"
PROFILE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
DEFAULT_SETTINGS: Dict[str, Any] = {
    "ui": {"theme": "light", "start_on_boot": False},
    "serial": {"port": "COM7", "baud": FIXED_BAUD},
    "capture": {"enabled_by_default": False, "toggle_combo": "ctrl+f1"},
    "sharing": {"mode": "passive"},
    "keyboard": {
        "layout": "us",
        "layouts": ["us"],
        "use_windows_layout": False,
        "layout_profiles": {"us": {}},
    },
}

DEFAULT_LANGUAGE_PACKS: Dict[str, Any] = {"version": 1, "packs": {}}

UI_COLORS = {
    "bg": "#EEF3F9",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "surface_soft": "#EFF4FB",
    "border": "#D9E2EE",
    "text": "#10233D",
    "muted": "#64748B",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_soft": "#DBEAFE",
    "hero": "#123A6B",
    "hero_edge": "#0E2D53",
    "hero_text": "#FFFFFF",
    "hero_muted": "#D6E7FF",
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
    "console_bg": "#0F172A",
    "console_fg": "#E2E8F0",
    "console_border": "#1E293B",
}

DARK_UI_COLORS = {
    "bg": "#0B1220",
    "surface": "#111827",
    "surface_alt": "#0F172A",
    "surface_soft": "#172033",
    "border": "#263246",
    "text": "#E5EEF8",
    "muted": "#94A3B8",
    "accent": "#60A5FA",
    "accent_hover": "#3B82F6",
    "accent_soft": "#1E3A8A",
    "hero": "#020617",
    "hero_edge": "#172554",
    "hero_text": "#F8FAFC",
    "hero_muted": "#BFDBFE",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "console_bg": "#020617",
    "console_fg": "#E2E8F0",
    "console_border": "#1E293B",
}


def _crc8(data: bytes) -> int:
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def _make_probe_keyboard_packet() -> bytes:
                                         
                                                              
    payload = bytes([0x01, 0x00, 0x00, 0x01])
    return bytes([SERIAL_FRAME_START]) + payload + bytes([_crc8(payload)])

UI_TEXTS: Dict[str, Dict[str, str]] = {
    "en": {
        "window_title": "Kavix32",
        "tab_basic": "Basic Setup",
        "tab_runtime": "Runtime",
        "root": "App folder:",
        "language_packs": "Language packs:",
        "config_file": "Config file:",
        "serial": "Serial",
        "port": "Port",
        "refresh_ports": "Refresh ports",
        "baud": "Baud",
        "baud_fixed": "{baud}",
        "capture": "Capture",
        "toggle_combo_1": "Toggle combo 1",
        "toggle_combo_2": "Toggle combo 2",
        "toggle_combo_3": "Toggle combo 3",
        "set_key": "Set",
        "unset_key": "Unset",
        "press_key": "Press key...",
        "peripheral_mode": "Forwarding Mode",
        "mode_passive": "Passive mode",
        "mode_clipboard": "Clipboard mode",
        "mode_passive_desc": "Low-level hardware forwarding only. Kavix32 captures input on the Master PC and emulates it on the Emulation Client PC. No software is required on the Emulation Client PC, so it can also be used in BIOS/UEFI.",
        "mode_clipboard_desc": "Uses the same hardware forwarding pipeline as Passive mode and adds bidirectional clipboard synchronization over the ESP USB CDC serial channel. Run the Kavix32 clipboard runtime script on the Emulation Client PC.",
        "keyboard_profiles": "Keyboard Profiles",
        "active_profile": "Active profile",
        "cycle_order": "Cycle order (comma)",
        "language_search": "Keyboard Language Search",
        "search": "Search",
        "clear": "Clear",
        "language": "Language",
        "refresh_list": "Refresh list",
        "apply_selected": "Apply selected",
        "use_windows_languages": "Use current Windows keyboard layout",
        "use_windows_languages_hint": "Always follow the keyboard layout currently active in Windows and apply the matching remap profile.",
        "launcher": "Launcher",
        "start": "Start",
        "stop": "Stop",
        "restart": "Restart",
        "runtime_logs_hint": "Runtime logs are in the Runtime tab",
        "load_files": "Load config",
        "save_form": "Save config",
        "start_on_boot": "Start on boot in background",
        "dlg_load_config_title": "Load config file",
        "dlg_save_config_title": "Save config file",
        "msg_config_saved_title": "Config saved",
        "msg_config_saved_body": "Saved config to:\n{path}",
        "runtime_clear": "Clear",
        "theme": "Theme:",
        "theme_toggle_dark": "Dark mode",
        "theme_toggle_light": "Light mode",
        "map_rules": "map rules",
        "pack_none_selected": "No language pack selected.",
        "pack_no_match": "No matching language packs.",
        "pack_info": "Profile: {profile} | Languages: {langs} | Remap rules: {count}",
        "n_a": "n/a",
        "status_idle": "Idle",
        "status_running": "Running",
        "status_stopped": "Stopped (exit {code})",
        "msg_parse_title": "Parse error",
        "msg_parse_body": "Failed to parse {name}:\n{error}\n\nUsing defaults.",
        "msg_save_failed_title": "Save failed",
        "msg_apply_failed_title": "Apply failed",
        "msg_apply_select_pack": "Select a language pack first.",
        "msg_apply_invalid_pack": "Selected language pack is invalid.",
        "msg_pack_applied_title": "Pack applied",
        "msg_pack_applied_body": "Applied {pack_id} as profile '{profile}'.\nRemap rules: {count}",
        "msg_already_running_title": "Already running",
        "msg_already_running_body": "master_pc_client.py is already running.",
        "msg_launch_failed_title": "Launch failed",
        "msg_launch_failed_body": "Could not start master_pc_client.py:\n{error}",
        "msg_start_blocked_title": "Start blocked",
        "msg_start_blocked_body": "Cannot start runtime.\n\n{detail}",
        "log_settings_changed_restarting": "[info] Settings changed, restarting runtime...",
        "log_pack_applied_restarting": "[info] Language pack applied, restarting runtime...",
        "log_exit": "[info] master_pc_client.py exited with code {code}",
        "log_restart_requested": "[info] Restart requested...",
        "log_stopping": "[info] Stopping master_pc_client.py...",
        "log_terminate_failed": "[warn] terminate() failed: {error}",
        "log_kill_failed": "[warn] kill() failed: {error}",
        "device_status_label": "Device status check",
        "check_now": "Check",
        "device_status_checking": "Checking...",
        "device_status_red_port": "ESP not connected on selected COM port.",
        "device_status_red_fw": "ESP connected, but firmware is missing/unsupported.",
        "device_status_orange_client": "ESP firmware OK, but the Emulation Client PC software is not ready.",
        "device_status_green_ok": "ESP firmware OK, and the Emulation Client PC software is ready.",
        "device_status_red_error": "Status check failed: {error}",
        "tray_open": "Open Kavix32",
        "tray_exit": "Exit Kavix32",
        "tray_hidden_message": "Kavix32 is still running in the background.",
        "tray_hidden_title": "Running in background",
        "tray_hidden_dialog": "Kavix32 was moved to the Windows hidden icons menu and will keep running in the background.",
        "log_autostart_waiting": "[info] Startup launch waiting for device check...",
        "log_autostart_skipped": "[info] Startup launch skipped because the selected COM port is unavailable.",
    },
}

def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    return override


def deep_copy_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(data))


def sanitize_profile_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    return cleaned or "layout"


def split_combo_expression(combo_expr: str, max_parts: int = 3) -> List[str]:
    parts = [part.strip() for part in combo_expr.split("+") if part.strip()]
    parts = parts[:max_parts]
    while len(parts) < max_parts:
        parts.append("")
    return parts


def build_combo_expression(parts: List[str], default_expr: str = "ctrl+f1") -> str:
    tokens = [part.strip() for part in parts if part.strip()]
    return "+".join(tokens) or default_expr


def tkinter_event_to_combo_token(event: tk.Event) -> Optional[str]:
    keysym = str(getattr(event, "keysym", "") or "")
    if not keysym:
        return None

    normalized = keysym.lower()
    direct_map = {
        "control_l": "ctrl",
        "control_r": "ctrl",
        "shift_l": "shift",
        "shift_r": "shift",
        "alt_l": "alt",
        "alt_r": "alt",
        "meta_l": "win",
        "meta_r": "win",
        "super_l": "win",
        "super_r": "win",
        "prior": "pageup",
        "next": "pagedown",
        "return": "enter",
        "escape": "esc",
        "backspace": "backspace",
        "space": "space",
    }
    if normalized in direct_map:
        return direct_map[normalized]
    if normalized.startswith("f") and normalized[1:].isdigit():
        return normalized
    if normalized in {"tab", "home", "end", "left", "right", "up", "down", "insert", "delete"}:
        return normalized

    char = str(getattr(event, "char", "") or "")
    if len(char) == 1 and char.isprintable() and char != "+":
        return char.lower()
    if len(normalized) == 1 and normalized.isprintable() and normalized != "+":
        return normalized
    return None


def parse_launch_flags(argv: List[str]) -> tuple[bool, bool]:
    start_hidden = False
    auto_start_runtime = False
    for arg in argv[1:]:
        if arg in {"--background", "--tray", "--minimized"}:
            start_hidden = True
        elif arg in {"--autostart", "--startup"}:
            auto_start_runtime = True
    return start_hidden, auto_start_runtime


class SwitcherUI(tk.Tk):
    def __init__(self, start_hidden: bool = False, auto_start_runtime: bool = False) -> None:
        super().__init__()
        self.ui_lang = "en"
        self.ui_theme = "light"
        self.title(self._tr("window_title"))
        self.geometry("1060x820")
        self.minsize(920, 680)

        self.current_config_path = DEFAULT_CONFIG_FILE
        self.language_packs_path = LANGUAGE_PACKS_FILE
        self.settings: Dict[str, Any] = {}
        self.language_packs: Dict[str, Any] = {}
        self.process: Optional[subprocess.Popen] = None
        self.restart_requested = False
        self.output_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        self.pack_display_to_id: Dict[str, str] = {}

        self.port_var = tk.StringVar(value="COM7")
        self.capture_toggle_vars = [
            tk.StringVar(value="ctrl"),
            tk.StringVar(value="f1"),
            tk.StringVar(value=""),
        ]
        self.capture_toggle_buttons: List[ttk.Button] = []
        self.capture_toggle_capture_index: Optional[int] = None
        self._capture_combo_bind_id: Optional[str] = None
        self.peripheral_mode_var = tk.StringVar(value="passive")
        self.peripheral_mode_desc_var = tk.StringVar(value=self._tr("mode_passive_desc"))
        self.pack_var = tk.StringVar(value="")
        self.pack_search_var = tk.StringVar(value="")
        self.pack_info_var = tk.StringVar(value=self._tr("pack_none_selected"))
        self.use_windows_layout_var = tk.BooleanVar(value=False)
        self.start_on_boot_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value=self._tr("status_idle"))
        self.theme_toggle_text_var = tk.StringVar(value="")
        self.root_path_var = tk.StringVar(value="%APP_ROOT%")
        self.language_packs_path_var = tk.StringVar(value="")
        self.config_path_var = tk.StringVar(value="")
        self.device_status_var = tk.StringVar(value=self._tr("device_status_checking"))
        self.device_status_level = "red"
        self.device_status_key = "device_status_checking"
        self.device_status_kwargs: Dict[str, Any] = {}
        self._status_check_in_progress = False
        self._tray_icon: Optional[Any] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._tray_enabled = False
        self._tray_notification_shown = False
        self._tray_dialog_shown = False
        self._exiting = False
        self._start_hidden = start_hidden
        self._auto_start_runtime = auto_start_runtime
        self._autostart_wait_logged = False
        self._window_icon_image: Optional[tk.PhotoImage] = None
        self._suspend_keyboard_toggle_save = False

        self.colors = {}
        self._apply_theme_palette()
        self.pack_search_var.trace_add("write", self._on_pack_search_changed)
        self._apply_window_icon()
        self._refresh_path_labels()
        self._build_ui()
        self._refresh_ports()
        self._load_all_files()
        self._schedule_queue_drain()
        self._init_system_tray()
        if os.name == "nt":
                                                                             
            self.after(350, self._terminate_other_kavix32_instances)
        if self._start_hidden:
            self.after(200, lambda: self._hide_to_tray(show_dialog=False, show_notification=False))
        if self._auto_start_runtime:
            self.after(350, self._maybe_autostart_runtime)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _tr(self, key: str, **kwargs: Any) -> str:
        lang = UI_TEXTS.get(self.ui_lang, UI_TEXTS["en"])
        template = lang.get(key, UI_TEXTS["en"].get(key, key))
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def _portable_path_text(self, path: Path) -> str:
        try:
            resolved_root = ROOT_DIR.resolve()
            resolved_path = Path(path).resolve()
            if resolved_path == resolved_root:
                return "%APP_ROOT%"
            relative = resolved_path.relative_to(resolved_root)
            relative_text = str(relative).replace("/", "\\")
            return f"%APP_ROOT%\\{relative_text}" if relative_text else "%APP_ROOT%"
        except Exception:
            name = Path(path).name.strip()
            return name or "%APP_ROOT%"

    def _refresh_path_labels(self) -> None:
        self.root_path_var.set("%APP_ROOT%")
        self.language_packs_path_var.set(self._portable_path_text(self.language_packs_path))
        self.config_path_var.set(self._portable_path_text(self.current_config_path))

    def _startup_bootstrap_path(self) -> Optional[Path]:
        if os.name != "nt":
            return None
        appdata = str(os.environ.get("APPDATA", "")).strip()
        if not appdata:
            return None
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Kavix32Master.vbs"

    def _startup_launch_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}" --background --autostart'

        python_exe = Path(sys.executable).resolve()
        if python_exe.name.lower() == "python.exe":
            pythonw_exe = python_exe.with_name("pythonw.exe")
            if pythonw_exe.exists():
                python_exe = pythonw_exe
        return f'"{python_exe}" "{Path(__file__).resolve()}" --background --autostart'

    def _sync_startup_bootstrap(self) -> None:
        startup_path = self._startup_bootstrap_path()
        if startup_path is None:
            return
        ui_settings = self.settings.get("ui", {})
        enabled = bool(ui_settings.get("start_on_boot", False)) if isinstance(ui_settings, dict) else False

        try:
            if enabled:
                command = self._startup_launch_command().replace('"', '""')
                script_text = 'Set WshShell = CreateObject("WScript.Shell")\n'
                script_text += f'WshShell.Run "{command}", 0, False\n'
                startup_path.parent.mkdir(parents=True, exist_ok=True)
                startup_path.write_text(script_text, encoding="utf-8")
            else:
                if startup_path.exists():
                    startup_path.unlink()
        except Exception as exc:
            self._append_runtime_line(f"[warn] Failed to update startup entry: {exc}")

    def _normalize_ui_theme(self, theme_name: Any) -> str:
        normalized = str(theme_name or "").strip().lower()
        return normalized if normalized in {"light", "dark"} else "light"

    def _refresh_theme_toggle_text(self) -> None:
        next_mode_key = "theme_toggle_light" if self.ui_theme == "dark" else "theme_toggle_dark"
        self.theme_toggle_text_var.set(self._tr(next_mode_key))

    def _apply_theme_palette(self) -> None:
        palette = DARK_UI_COLORS if self.ui_theme == "dark" else UI_COLORS
        self.colors = dict(palette)
        self._configure_styles()
        self._refresh_theme_toggle_text()

    def _configure_styles(self) -> None:
        self.configure(bg=self.colors["bg"])
        self.option_add("*Font", "{Segoe UI} 10")
        self.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        base_font = tkfont.Font(family="Segoe UI", size=10)
        semibold_font = tkfont.Font(family="Segoe UI Semibold", size=10)
        title_font = tkfont.Font(family="Segoe UI Variable Display", size=34, weight="bold")
        card_title_font = tkfont.Font(family="Segoe UI Semibold", size=11)

        style.configure(".", background=self.colors["bg"], foreground=self.colors["text"], font=base_font)
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["surface"])
        style.configure("Hero.TFrame", background=self.colors["hero"])
        style.configure("SectionTitle.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=card_title_font)
        style.configure("Body.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=base_font)
        style.configure("Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=base_font)
        style.configure("Hint.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=base_font)
        style.configure("Value.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=semibold_font)
        style.configure("HeroTitle.TLabel", background=self.colors["hero"], foreground=self.colors["hero_text"], font=title_font)
        style.configure("StatusTitle.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=semibold_font)
        style.configure("StatusText.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=base_font)
        style.configure("Footer.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=base_font)
        style.configure(
            "Card.TCheckbutton",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=base_font,
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", self.colors["surface"])],
            foreground=[("disabled", self.colors["muted"])],
        )
        style.configure(
            "Card.TRadiobutton",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=base_font,
        )
        style.map(
            "Card.TRadiobutton",
            background=[("active", self.colors["surface"])],
            foreground=[("disabled", self.colors["muted"])],
        )

        style.configure(
            "Accent.TButton",
            background=self.colors["accent"],
            foreground="#FFFFFF",
            font=semibold_font,
            padding=(14, 8),
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", self.colors["accent_hover"]), ("disabled", self.colors["accent_soft"])],
            foreground=[("disabled", self.colors["hero_muted"])],
        )

        style.configure(
            "Neutral.TButton",
            background=self.colors["surface_soft"],
            foreground=self.colors["text"],
            font=semibold_font,
            padding=(14, 8),
            borderwidth=1,
            focusthickness=0,
        )
        style.map(
            "Neutral.TButton",
            background=[("active", self.colors["accent_soft"]), ("disabled", self.colors["surface_soft"])],
            foreground=[("disabled", self.colors["muted"])],
        )

        style.configure(
            "Small.TButton",
            background=self.colors["surface_soft"],
            foreground=self.colors["text"],
            font=base_font,
            padding=(10, 6),
            borderwidth=1,
            focusthickness=0,
        )
        style.map("Small.TButton", background=[("active", self.colors["accent_soft"])])
        style.configure("Flag.TButton", background=self.colors["surface_soft"], padding=4, borderwidth=1, focusthickness=0)
        style.map("Flag.TButton", background=[("active", self.colors["accent_soft"])])

        style.configure(
            "TEntry",
            fieldbackground=self.colors["surface_soft"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            insertcolor=self.colors["text"],
            padding=8,
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.colors["surface_soft"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            arrowsize=16,
            padding=8,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors["surface_soft"])],
            foreground=[("readonly", self.colors["text"])],
            selectbackground=[("readonly", self.colors["accent_soft"])],
            selectforeground=[("readonly", self.colors["text"])],
        )
        style.configure(
            "TNotebook",
            background=self.colors["bg"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=self.colors["surface_soft"],
            foreground=self.colors["muted"],
            padding=(18, 10),
            borderwidth=0,
            font=semibold_font,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.colors["surface"]), ("active", self.colors["accent_soft"])],
            foreground=[("selected", self.colors["text"]), ("active", self.colors["text"])],
        )
        style.configure("Vertical.TScrollbar", background=self.colors["surface_soft"], troughcolor=self.colors["surface_alt"])

    def _create_card(
        self,
        parent: ttk.Frame,
        title: str,
        row: int,
        column: int,
        *,
        columnspan: int = 1,
        rowspan: int = 1,
        padx: tuple[int, int] = (0, 0),
        pady: tuple[int, int] = (0, 0),
        sticky: str = "nsew",
        subtitle: Optional[str] = None,
    ) -> ttk.Frame:
        shell = tk.Frame(parent, bg=self.colors["border"], highlightthickness=0)
        shell.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky=sticky, padx=padx, pady=pady)

        card = ttk.Frame(shell, style="Card.TFrame", padding=(18, 16, 18, 16))
        card.pack(fill="both", expand=True, padx=1, pady=1)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text=title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        next_row = 1
        if subtitle:
            ttk.Label(card, text=subtitle, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
            next_row = 2

        ttk.Separator(card, orient="horizontal").grid(row=next_row, column=0, sticky="ew", pady=(12, 14))

        body = ttk.Frame(card, style="Card.TFrame")
        body.grid(row=next_row + 1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        card.rowconfigure(next_row + 1, weight=1)
        return body

    def _persist_ui_preferences(self) -> None:
        if not isinstance(self.settings, dict):
            self.settings = deep_copy_dict(DEFAULT_SETTINGS)
        ui_settings = self.settings.setdefault("ui", {})
        if not isinstance(ui_settings, dict):
            ui_settings = {}
            self.settings["ui"] = ui_settings
        ui_settings["theme"] = self.ui_theme
        try:
            self._write_json(self.current_config_path, self.settings)
        except Exception:
            pass

    def _toggle_ui_theme(self) -> None:
        self.ui_theme = "dark" if self.ui_theme != "dark" else "light"
        self._persist_ui_preferences()
        self._apply_theme_palette()
        self.title(self._tr("window_title"))
        self._refresh_tray_menu()
        self._rebuild_ui()

    def _apply_window_icon(self) -> None:
        icon_candidates = ["app.ico", "icon.ico", "app.png", "icon.png", "ico.png"]
        for name in icon_candidates:
            icon_path = TRAY_ICON_DIR / name
            if not icon_path.exists():
                continue

            if icon_path.suffix.lower() == ".ico":
                try:
                    self.iconbitmap(default=str(icon_path))
                    return
                except Exception:
                    pass

            try:
                self._window_icon_image = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self._window_icon_image)
                return
            except Exception:
                continue

    def _load_tray_icon_image(self) -> Optional[Any]:
        if Image is None:
            return None

        candidates = ["app.ico", "icon.ico", "app.png", "icon.png", "ico.png"]
        for name in candidates:
            icon_path = TRAY_ICON_DIR / name
            if not icon_path.exists():
                continue
            try:
                return Image.open(icon_path).convert("RGBA")
            except Exception:
                continue

                                                                 
        img = Image.new("RGBA", (64, 64), "#1E293B")
        if ImageDraw is not None:
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill="#2563EB")
            draw.rectangle((16, 32, 48, 40), fill="#FFFFFF")
        return img

    def _on_tray_open(self, _icon: Any, _item: Any) -> None:
        self.after(0, self._restore_from_tray)

    def _build_tray_menu(self) -> Any:
        return pystray.Menu(
            pystray.MenuItem(self._tr("tray_open"), self._on_tray_open, default=True),
            pystray.MenuItem(self._tr("tray_exit"), self._on_tray_exit),
        )

    def _refresh_tray_menu(self) -> None:
        if self._tray_icon is None or pystray is None:
            return
        try:
            self._tray_icon.title = self._tr("window_title")
            self._tray_icon.menu = self._build_tray_menu()
            self._tray_icon.update_menu()
        except Exception:
            pass

    def _on_tray_exit(self, icon: Any, _item: Any) -> None:
        if icon is not None:
            try:
                icon.visible = False
            except Exception:
                pass
            try:
                icon.stop()
            except Exception:
                pass
        self.after(0, lambda: self._quit_application(force_hard_exit=True, cleanup_other_instances=True))

    def _init_system_tray(self) -> None:
        if os.name != "nt" or pystray is None:
            return
        tray_image = self._load_tray_icon_image()
        if tray_image is None:
            return

        try:
            self._tray_icon = pystray.Icon("kavix32", tray_image, self._tr("window_title"), self._build_tray_menu())
            self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
            self._tray_thread.start()
            self._tray_enabled = True
        except Exception as exc:
            self._tray_icon = None
            self._tray_thread = None
            self._tray_enabled = False
            self._append_runtime_line(f"[warn] Tray icon disabled: {exc}")

    def _hide_to_tray(self, show_dialog: bool = False, show_notification: bool = False) -> None:
        if not self._tray_enabled:
            self._quit_application()
            return

        if self.capture_toggle_capture_index is not None:
            self._finish_capture_combo_part()
        if show_dialog and not self._tray_dialog_shown:
            messagebox.showinfo(self._tr("tray_hidden_title"), self._tr("tray_hidden_dialog"))
            self._tray_dialog_shown = True

        self.withdraw()
        if self._tray_icon is not None and show_notification and not self._tray_notification_shown:
            try:
                self._tray_icon.notify(self._tr("tray_hidden_message"), self._tr("window_title"))
            except Exception:
                pass
            self._tray_notification_shown = True

    def _restore_from_tray(self) -> None:
        if self._exiting:
            return
        self.deiconify()
        self.state("normal")
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass

    def _stop_tray_icon(self) -> None:
        icon = self._tray_icon
        self._tray_icon = None
        self._tray_enabled = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        if self._tray_thread is not None and self._tray_thread.is_alive():
            self._tray_thread.join(timeout=1.0)
        self._tray_thread = None

    def _list_windows_kavix32_processes(self) -> List[Dict[str, Any]]:
        if os.name != "nt":
            return []
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "$procs = Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -in @('Kavix32.exe','master_pc_client.exe') -or "
                "$_.Name -match '^python(w)?\\.exe$' }; "
                "$procs | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
            ),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                creationflags=create_no_window,
                timeout=4.0,
                check=False,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        raw = completed.stdout.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return []

    def _terminate_other_kavix32_instances(self) -> None:
        if os.name != "nt":
            return

        processes = self._list_windows_kavix32_processes()
        if not processes:
            return

        current_pid = os.getpid()
        current_runtime_pid = self.process.pid if self.process is not None and self.process.poll() is None else None
        parent_by_pid: Dict[int, int] = {}
        for proc_info in processes:
            try:
                pid = int(proc_info.get("ProcessId", 0))
                parent_pid = int(proc_info.get("ParentProcessId", 0))
            except Exception:
                continue
            if pid > 0:
                parent_by_pid[pid] = parent_pid

        skip_pids: set[int] = {current_pid}
        if current_runtime_pid is not None and current_runtime_pid > 0:
            skip_pids.add(current_runtime_pid)

        ancestor_pid = parent_by_pid.get(current_pid, 0)
        while ancestor_pid and ancestor_pid > 0 and ancestor_pid not in skip_pids:
            skip_pids.add(ancestor_pid)
            ancestor_pid = parent_by_pid.get(ancestor_pid, 0)

        target_pids: List[int] = []

        for proc_info in processes:
            try:
                pid = int(proc_info.get("ProcessId", 0))
            except Exception:
                continue
            if pid <= 0 or pid in skip_pids:
                continue

            name = str(proc_info.get("Name", "") or "").strip().lower()
            command_line = str(proc_info.get("CommandLine", "") or "").strip().lower()
            if name in {"kavix32.exe", "master_pc_client.exe"}:
                target_pids.append(pid)
                continue
            if "switcher_ui.py" in command_line or "master_pc_client.py" in command_line:
                target_pids.append(pid)

        if not target_pids:
            return

        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for pid in sorted(set(target_pids)):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=create_no_window,
                    timeout=3.0,
                    check=False,
                )
            except Exception:
                pass

    def _quit_application(self, force_hard_exit: bool = False, cleanup_other_instances: bool = False) -> None:
        if self._exiting:
            return
        self._exiting = True
        if self.capture_toggle_capture_index is not None:
            self._finish_capture_combo_part()
        proc = self.process
        if proc is not None and proc.poll() is None:
            self._stop_switcher()
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if cleanup_other_instances:
            self._terminate_other_kavix32_instances()
        self._stop_tray_icon()
        try:
            self.quit()
        except Exception:
            pass
        self.destroy()
        if force_hard_exit:
            os._exit(0)

    def _maybe_autostart_runtime(self) -> None:
        if self._exiting or self.process is not None:
            return
        self._start_switcher()

    def _rebuild_ui(self) -> None:
        runtime_snapshot = ""
        if hasattr(self, "runtime_text"):
            try:
                runtime_snapshot = self.runtime_text.get("1.0", tk.END)
            except Exception:
                runtime_snapshot = ""

        for child in self.winfo_children():
            child.destroy()

        self._apply_theme_palette()
        self._build_ui()
        self._form_from_data()
        self._refresh_ports()
        self._refresh_pack_choices()

        if runtime_snapshot.strip():
            self.runtime_text.configure(state="normal")
            self.runtime_text.insert("1.0", runtime_snapshot)
            self.runtime_text.configure(state="disabled")

        if self.process is not None and self.process.poll() is None:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.restart_btn.configure(state="normal")
            self.status_var.set(self._tr("status_running"))
        else:
            self.status_var.set(self._tr("status_idle"))

    def _status_level_to_color(self, level: str) -> str:
        if level == "green":
            return "#22a447"
        if level == "orange":
            return "#d98a00"
        return "#c0392b"

    def _refresh_device_status_text(self) -> None:
        self.device_status_var.set(self._tr(self.device_status_key, **self.device_status_kwargs))

    def _set_device_status(self, level: str, message_key: str, **kwargs: Any) -> None:
        self.device_status_level = level
        self.device_status_key = message_key
        self.device_status_kwargs = kwargs
        self._refresh_device_status_text()
        self._apply_device_status_visuals()

    def _apply_device_status_visuals(self) -> None:
        if hasattr(self, "device_status_dot"):
            self.device_status_dot.configure(
                fg=self._status_level_to_color(self.device_status_level),
                bg=self.colors["surface"],
                font=("Segoe UI Symbol", 13),
            )

    def _kick_device_status_check(self) -> None:
        if self._status_check_in_progress:
            return
        if self.process is not None and self.process.poll() is None:
            return

        port = self.port_var.get().strip() or "COM7"
        self._status_check_in_progress = True
        self._set_device_status("orange", "device_status_checking")
        threading.Thread(target=self._probe_device_status_worker, args=(port,), daemon=True).start()

    def _probe_device_status_worker(self, port: str) -> None:
        level = "red"
        message_key = "device_status_red_port"
        message_kwargs: Dict[str, Any] = {}
        debug_line: Optional[str] = None
        try:
            level, message_key, message_kwargs = self._probe_device_status_once(port)
            debug_line = message_kwargs.pop("_debug", None)
        except Exception as exc:
            level = "red"
            message_key = "device_status_red_error"
            message_kwargs = {"error": str(exc)}
            debug_line = f"[check] port={port} exception={exc}"

        def _done() -> None:
            self._status_check_in_progress = False
            self._set_device_status(level, message_key, **message_kwargs)
            if debug_line:
                self._append_runtime_line(debug_line)

        self.after(0, _done)

    def _probe_device_status_once(self, port: str) -> tuple[str, str, Dict[str, Any]]:
        try:
            import serial
        except Exception:
            return "red", "device_status_red_error", {"error": "pyserial missing"}

        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = FIXED_BAUD
            ser.timeout = 0.15
            ser.write_timeout = 0.15
                                                                                                      
            ser.dtr = False
            ser.rts = False
            ser.dsrdtr = False
            ser.rtscts = False
            ser.xonxoff = False
            ser.open()
        except Exception:
            return "red", "device_status_red_port", {}

        heartbeat_seen = False
        hid_mounted_seen = False
        hid_unmounted_seen = False
        hid_ready_ack_seen = False
        hid_not_ready_ack_seen = False
        ff_count = 0
        c1_count = 0
        c0_count = 0
        a1_count = 0
        e1_count = 0
        total_bytes = 0

        try:
            started = time.monotonic()
            base_deadline = started + STATUS_PROBE_BASE_TIMEOUT_S
            hard_deadline = started + STATUS_PROBE_BASE_TIMEOUT_S + STATUS_PROBE_MOUNT_WAIT_S
            deadline = base_deadline
            try:
                ser.reset_input_buffer()
            except Exception:
                pass

            while time.monotonic() < deadline:
                chunk = ser.read(64)
                if not chunk:
                    if (
                        deadline < hard_deadline
                        and heartbeat_seen
                        and (hid_unmounted_seen or hid_not_ready_ack_seen)
                        and not hid_mounted_seen
                        and not hid_ready_ack_seen
                    ):
                        deadline = hard_deadline
                    continue
                total_bytes += len(chunk)
                for byte in chunk:
                    if byte == 0xFF:
                        heartbeat_seen = True
                        ff_count += 1
                    elif byte == 0xC1:
                        hid_mounted_seen = True
                        c1_count += 1
                        deadline = time.monotonic()
                    elif byte == 0xC0:
                        hid_unmounted_seen = True
                        c0_count += 1
                    elif byte == 0xA1:
                        hid_ready_ack_seen = True
                        a1_count += 1
                        deadline = time.monotonic()
                    elif byte == 0xE1:
                        hid_not_ready_ack_seen = True
                        e1_count += 1
                if (
                    deadline < hard_deadline
                    and heartbeat_seen
                    and (hid_unmounted_seen or hid_not_ready_ack_seen)
                    and not hid_mounted_seen
                    and not hid_ready_ack_seen
                ):
                                                                                            
                    deadline = hard_deadline
        finally:
            try:
                ser.close()
            except Exception:
                pass

        debug = (
            f"[check] port={port} bytes={total_bytes} "
            f"ff={ff_count} c1={c1_count} c0={c0_count} a1={a1_count} e1={e1_count}"
        )

        if hid_ready_ack_seen or hid_mounted_seen:
            return "green", "device_status_green_ok", {"_debug": debug}
        if hid_not_ready_ack_seen:
            return "orange", "device_status_orange_client", {"_debug": debug}
        if heartbeat_seen:
                                                                                                    
            return "green", "device_status_green_ok", {"_debug": debug}
        if not heartbeat_seen and not hid_not_ready_ack_seen:
                                                                                                              
            return "orange", "device_status_orange_client", {"_debug": debug}
        if hid_unmounted_seen:
            return "orange", "device_status_orange_client", {"_debug": debug}
        return "orange", "device_status_orange_client", {"_debug": debug}

    def _build_ui(self) -> None:
        self.configure(bg=self.colors["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top_bar = ttk.Frame(self, style="App.TFrame", padding=(18, 18, 18, 10))
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.columnconfigure(0, weight=1)

        hero_shell = tk.Frame(top_bar, bg=self.colors["hero_edge"], highlightthickness=0)
        hero_shell.grid(row=0, column=0, sticky="ew")
        hero = ttk.Frame(hero_shell, style="Hero.TFrame", padding=(26, 20, 26, 20))
        hero.pack(fill="both", expand=True, padx=1, pady=1)
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)
        ttk.Label(hero, text=self._tr("window_title"), style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(
            hero,
            textvariable=self.theme_toggle_text_var,
            style="Small.TButton",
            command=self._toggle_ui_theme,
        ).grid(row=0, column=1, rowspan=2, sticky="ne", padx=(14, 0))

        main_frame = ttk.Frame(self, style="App.TFrame", padding=(18, 0, 18, 18))
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.basic_tab = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.runtime_tab = ttk.Frame(self.notebook, style="App.TFrame", padding=12)
        self.notebook.add(self.basic_tab, text=self._tr("tab_basic"))
        self.notebook.add(self.runtime_tab, text=self._tr("tab_runtime"))

        self._build_basic_tab(self.basic_tab)
        self._build_runtime_tab(self.runtime_tab)

    def _build_basic_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

                                                                                                          
        scroll_shell = tk.Frame(parent, bg=self.colors["bg"], highlightthickness=0)
        scroll_shell.grid(row=0, column=0, sticky="nsew")
        scroll_shell.columnconfigure(0, weight=1)
        scroll_shell.rowconfigure(0, weight=1)

        self.basic_scroll_canvas = tk.Canvas(
            scroll_shell,
            bg=self.colors["bg"],
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
        self.basic_scroll_canvas.grid(row=0, column=0, sticky="nsew")

        self.basic_scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=self.basic_scroll_canvas.yview)
        self.basic_scrollbar.grid(row=0, column=1, sticky="ns")
        self.basic_scroll_canvas.configure(yscrollcommand=self.basic_scrollbar.set)

        content = ttk.Frame(self.basic_scroll_canvas, style="App.TFrame", padding=12)
        self.basic_canvas_window = self.basic_scroll_canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scrollregion(_event: Optional[tk.Event] = None) -> None:
            self.basic_scroll_canvas.configure(scrollregion=self.basic_scroll_canvas.bbox("all"))

        def _sync_content_width(event: tk.Event) -> None:
            self.basic_scroll_canvas.itemconfigure(self.basic_canvas_window, width=event.width)

        content.bind("<Configure>", _sync_scrollregion)
        self.basic_scroll_canvas.bind("<Configure>", _sync_content_width)

        parent = content
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        serial_box = self._create_card(parent, self._tr("serial"), 0, 0, padx=(0, 10), pady=(0, 12))
        serial_box.columnconfigure(1, weight=1)

        ttk.Label(serial_box, text=self._tr("port"), style="Body.TLabel").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(serial_box, textvariable=self.port_var, state="normal")
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ttk.Button(serial_box, text=self._tr("refresh_ports"), style="Small.TButton", command=self._refresh_ports).grid(row=0, column=2, padx=(10, 0))

        ttk.Label(serial_box, text=self._tr("baud"), style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Label(serial_box, text=self._tr("baud_fixed", baud=FIXED_BAUD), style="Value.TLabel").grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=(12, 0)
        )

        capture_box = self._create_card(parent, self._tr("capture"), 1, 0, padx=(0, 10), pady=(0, 12))
        capture_box.columnconfigure(1, weight=1)
        self.capture_toggle_buttons = []

        ttk.Label(capture_box, text=self._tr("toggle_combo_1"), style="Body.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(capture_box, textvariable=self.capture_toggle_vars[0], state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )
        btn = ttk.Button(capture_box, text=self._tr("set_key"), style="Small.TButton", command=lambda: self._begin_capture_combo_part(0))
        btn.grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.capture_toggle_buttons.append(btn)
        ttk.Button(
            capture_box,
            text=self._tr("unset_key"),
            style="Small.TButton",
            command=lambda: self._unset_capture_combo_part(0),
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(capture_box, text=self._tr("toggle_combo_2"), style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(capture_box, textvariable=self.capture_toggle_vars[1], state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=(12, 0)
        )
        btn = ttk.Button(capture_box, text=self._tr("set_key"), style="Small.TButton", command=lambda: self._begin_capture_combo_part(1))
        btn.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(12, 0))
        self.capture_toggle_buttons.append(btn)
        ttk.Button(
            capture_box,
            text=self._tr("unset_key"),
            style="Small.TButton",
            command=lambda: self._unset_capture_combo_part(1),
        ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(12, 0))
        ttk.Label(capture_box, text=self._tr("toggle_combo_3"), style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(capture_box, textvariable=self.capture_toggle_vars[2], state="readonly").grid(
            row=2, column=1, sticky="ew", padx=(10, 0), pady=(12, 0)
        )
        btn = ttk.Button(capture_box, text=self._tr("set_key"), style="Small.TButton", command=lambda: self._begin_capture_combo_part(2))
        btn.grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(12, 0))
        self.capture_toggle_buttons.append(btn)
        ttk.Button(
            capture_box,
            text=self._tr("unset_key"),
            style="Small.TButton",
            command=lambda: self._unset_capture_combo_part(2),
        ).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(12, 0))
        self._refresh_capture_combo_buttons()

        sharing_box = self._create_card(parent, self._tr("peripheral_mode"), 2, 0, padx=(0, 10), pady=(0, 12))
        sharing_box.columnconfigure(1, weight=1)

        ttk.Radiobutton(
            sharing_box,
            text=self._tr("mode_passive"),
            variable=self.peripheral_mode_var,
            value="passive",
            style="Card.TRadiobutton",
            command=self._on_peripheral_mode_changed,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            sharing_box,
            text=self._tr("mode_clipboard"),
            variable=self.peripheral_mode_var,
            value="clipboard",
            style="Card.TRadiobutton",
            command=self._on_peripheral_mode_changed,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(
            sharing_box,
            textvariable=self.peripheral_mode_desc_var,
            style="Hint.TLabel",
            wraplength=460,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._apply_peripheral_mode_ui_state()

        keyboard_box = self._create_card(parent, self._tr("keyboard_profiles"), 0, 1, rowspan=3, pady=(0, 12))
        keyboard_box.columnconfigure(1, weight=1)

        ttk.Label(keyboard_box, text=self._tr("search"), style="Body.TLabel").grid(row=0, column=0, sticky="w")
        self.pack_search_entry = ttk.Entry(keyboard_box, textvariable=self.pack_search_var)
        self.pack_search_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.pack_clear_btn = ttk.Button(
            keyboard_box,
            text=self._tr("clear"),
            style="Small.TButton",
            command=self._clear_pack_search,
        )
        self.pack_clear_btn.grid(row=0, column=2, padx=(10, 0))

        ttk.Label(keyboard_box, text=self._tr("language"), style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.pack_combo = ttk.Combobox(keyboard_box, textvariable=self.pack_var, state="readonly")
        self.pack_combo.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(12, 0))
        self.pack_combo.bind("<<ComboboxSelected>>", self._on_pack_selected)
        self.pack_apply_btn = ttk.Button(
            keyboard_box,
            text=self._tr("apply_selected"),
            style="Accent.TButton",
            command=self._apply_selected_pack,
        )
        self.pack_apply_btn.grid(row=1, column=2, padx=(10, 0), pady=(12, 0))

        ttk.Label(
            keyboard_box,
            textvariable=self.pack_info_var,
            style="Hint.TLabel",
            wraplength=320,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(14, 0))

        ttk.Checkbutton(
            keyboard_box,
            text=self._tr("use_windows_languages"),
            variable=self.use_windows_layout_var,
            style="Card.TCheckbutton",
            command=self._on_windows_layout_toggle_changed,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Label(
            keyboard_box,
            text=self._tr("use_windows_languages_hint"),
            style="Hint.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        launcher_box = self._create_card(parent, self._tr("launcher"), 3, 0, columnspan=2, pady=(0, 12))
        launcher_box.columnconfigure(4, weight=1)

        self.start_btn = ttk.Button(launcher_box, text=self._tr("start"), style="Accent.TButton", command=self._start_switcher)
        self.start_btn.grid(row=0, column=0, sticky="w")

        self.stop_btn = ttk.Button(launcher_box, text=self._tr("stop"), style="Neutral.TButton", command=self._stop_switcher, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.restart_btn = ttk.Button(launcher_box, text=self._tr("restart"), style="Neutral.TButton", command=self._restart_switcher, state="disabled")
        self.restart_btn.grid(row=0, column=2, sticky="w", padx=(10, 0))

        ttk.Label(launcher_box, text=self._tr("runtime_logs_hint"), style="Hint.TLabel").grid(row=0, column=3, sticky="w", padx=(18, 0))
        ttk.Label(launcher_box, textvariable=self.status_var, style="Value.TLabel").grid(row=0, column=4, sticky="e", padx=(14, 0))

        launcher_footer = ttk.Frame(launcher_box, style="Card.TFrame")
        launcher_footer.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        launcher_footer.columnconfigure(0, weight=1)
        launcher_footer.columnconfigure(1, weight=0)
        launcher_footer.columnconfigure(2, weight=1)

        actions = ttk.Frame(launcher_footer, style="Card.TFrame")
        actions.grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text=self._tr("load_files"), style="Neutral.TButton", command=self._load_config_dialog).grid(row=0, column=0, sticky="w")
        ttk.Button(
            actions,
            text=self._tr("save_form"),
            style="Accent.TButton",
            command=lambda: self._save_config_dialog(restart_if_running=True),
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Checkbutton(
            actions,
            text=self._tr("start_on_boot"),
            variable=self.start_on_boot_var,
            style="Card.TCheckbutton",
            command=self._on_start_on_boot_changed,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

                                                                      
        self._bind_basic_scroll_wheel_events()

    def _bind_basic_scroll_wheel_events(self) -> None:
                                                                                  
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")
        self.bind_all("<MouseWheel>", self._on_basic_scroll_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_basic_scroll_linux_up, add="+")
        self.bind_all("<Button-5>", self._on_basic_scroll_linux_down, add="+")
        self._bind_basic_scroll_events_recursive(self.basic_tab)

    def _bind_basic_scroll_events_recursive(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_basic_scroll_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_basic_scroll_linux_up, add="+")
        widget.bind("<Button-5>", self._on_basic_scroll_linux_down, add="+")
        for child in widget.winfo_children():
            self._bind_basic_scroll_events_recursive(child)

    def _widget_is_descendant(self, widget: tk.Misc, ancestor: tk.Misc) -> bool:
        current: Optional[tk.Misc] = widget
        while current is not None:
            if current is ancestor:
                return True
            try:
                parent_name = current.winfo_parent()
                if not parent_name:
                    break
                current = current.nametowidget(parent_name)
            except Exception:
                break
        return False

    def _is_pointer_over_basic_tab(self) -> bool:
        if not hasattr(self, "basic_tab"):
            return False
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            hovered = self.winfo_containing(pointer_x, pointer_y)
        except Exception:
            hovered = None
        if hovered is None:
            return False
        return self._widget_is_descendant(hovered, self.basic_tab)

    def _is_basic_tab_active(self) -> bool:
        if not hasattr(self, "notebook") or not hasattr(self, "basic_tab"):
            return False
        try:
            selected = self.notebook.select()
            if not selected:
                return False
            return self.nametowidget(selected) is self.basic_tab
        except Exception:
            return False

    def _scroll_basic_tab(self, units: int) -> None:
        if units == 0 or not self._is_basic_tab_active():
            return
        canvas = getattr(self, "basic_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_scroll(int(units), "units")
        except Exception:
            pass

    def _on_basic_scroll_mousewheel(self, event: tk.Event) -> Optional[str]:
        if not self._is_basic_tab_active() or not self._is_pointer_over_basic_tab():
            return None
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return None
        steps = int(-delta / 120)
        if steps == 0:
            steps = -1 if delta > 0 else 1
        self._scroll_basic_tab(steps * 3)
        return "break"

    def _on_basic_scroll_linux_up(self, _event: tk.Event) -> Optional[str]:
        if not self._is_basic_tab_active() or not self._is_pointer_over_basic_tab():
            return None
        self._scroll_basic_tab(-3)
        return "break"

    def _on_basic_scroll_linux_down(self, _event: tk.Event) -> Optional[str]:
        if not self._is_basic_tab_active() or not self._is_pointer_over_basic_tab():
            return None
        self._scroll_basic_tab(3)
        return "break"

    def _on_peripheral_mode_changed(self) -> None:
        self._apply_peripheral_mode_ui_state()
        self.after(0, lambda: self._save_from_form(restart_if_running=True))

    def _apply_peripheral_mode_ui_state(self) -> None:
        mode = str(self.peripheral_mode_var.get() or "passive").strip().lower()
        if mode not in {"passive", "clipboard"}:
            mode = "passive"
            self.peripheral_mode_var.set(mode)

        desc_key = "mode_clipboard_desc" if mode == "clipboard" else "mode_passive_desc"
        self.peripheral_mode_desc_var.set(self._tr(desc_key))
    def _on_windows_layout_toggle_changed(self) -> None:
        self._apply_keyboard_mode_ui_state()
        if self._suspend_keyboard_toggle_save:
            return
        self.after(0, lambda: self._save_from_form(restart_if_running=True))

    def _on_start_on_boot_changed(self) -> None:
        self.after(0, lambda: self._save_from_form(restart_if_running=False))

    def _apply_keyboard_mode_ui_state(self) -> None:
        windows_mode = bool(self.use_windows_layout_var.get())

        if hasattr(self, "pack_search_entry"):
            self.pack_search_entry.configure(state="disabled" if windows_mode else "normal")

        if hasattr(self, "pack_combo"):
            self.pack_combo.configure(state="disabled" if windows_mode else "readonly")

        if hasattr(self, "pack_clear_btn"):
            self.pack_clear_btn.configure(state="disabled" if windows_mode else "normal")

        if hasattr(self, "pack_apply_btn"):
            self.pack_apply_btn.configure(state="disabled" if windows_mode else "normal")

    def _refresh_capture_combo_buttons(self) -> None:
        for index, button in enumerate(self.capture_toggle_buttons):
            text_key = "press_key" if index == self.capture_toggle_capture_index else "set_key"
            button.configure(text=self._tr(text_key))

    def _begin_capture_combo_part(self, index: int) -> None:
        if self.capture_toggle_capture_index is not None:
            self._finish_capture_combo_part()
        self.capture_toggle_capture_index = index
        self._refresh_capture_combo_buttons()
        self._capture_combo_bind_id = self.bind("<KeyPress>", self._on_capture_combo_keypress, add="+")
        self.focus_force()

    def _finish_capture_combo_part(self) -> None:
        self.capture_toggle_capture_index = None
        if self._capture_combo_bind_id is not None:
            self.unbind("<KeyPress>", self._capture_combo_bind_id)
            self._capture_combo_bind_id = None
        self._refresh_capture_combo_buttons()

    def _unset_capture_combo_part(self, index: int) -> None:
        if index < 0 or index >= len(self.capture_toggle_vars):
            return
        if self.capture_toggle_capture_index is not None:
            self._finish_capture_combo_part()

        previous_combo = build_combo_expression([var.get() for var in self.capture_toggle_vars])
        if not self.capture_toggle_vars[index].get().strip():
            return

        self.capture_toggle_vars[index].set("")
        updated_combo = build_combo_expression([var.get() for var in self.capture_toggle_vars])
        if updated_combo != previous_combo:
            self.after(0, lambda: self._save_from_form(restart_if_running=True))

    def _on_capture_combo_keypress(self, event: tk.Event) -> str:
        index = self.capture_toggle_capture_index
        if index is None:
            return "break"

        previous_combo = build_combo_expression([var.get() for var in self.capture_toggle_vars])
        token = tkinter_event_to_combo_token(event)
        if token is not None:
            self.capture_toggle_vars[index].set(token)
        updated_combo = build_combo_expression([var.get() for var in self.capture_toggle_vars])
        self._finish_capture_combo_part()
        if token is not None and updated_combo != previous_combo:
            self.after(0, lambda: self._save_from_form(restart_if_running=True))
        return "break"

    def _build_runtime_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        shell = tk.Frame(parent, bg=self.colors["border"], highlightthickness=0)
        shell.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        card = ttk.Frame(shell, style="Card.TFrame", padding=(18, 16, 18, 16))
        card.pack(fill="both", expand=True, padx=1, pady=1)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        ttk.Label(card, text=self._tr("tab_runtime"), style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text=self._tr("runtime_logs_hint"), style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 12))
        ttk.Button(card, text=self._tr("runtime_clear"), style="Small.TButton", command=self._clear_runtime_log).grid(row=0, column=1, sticky="e")

        console_shell = tk.Frame(card, bg=self.colors["console_border"], highlightthickness=0)
        console_shell.grid(row=2, column=0, columnspan=2, sticky="nsew")
        console_shell.columnconfigure(0, weight=1)
        console_shell.rowconfigure(0, weight=1)

        self.runtime_text = tk.Text(
            console_shell,
            wrap="word",
            bg=self.colors["console_bg"],
            fg=self.colors["console_fg"],
            insertbackground=self.colors["console_fg"],
            selectbackground="#1D4ED8",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Cascadia Mono", 10),
            padx=12,
            pady=12,
        )
        self.runtime_text.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.runtime_text.configure(state="disabled")

        yscroll = ttk.Scrollbar(console_shell, orient="vertical", command=self.runtime_text.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.runtime_text.configure(yscrollcommand=yscroll.set)
    def _append_runtime_line(self, line: str) -> None:
        self.output_queue.put(("line", line))

    def _clear_runtime_log(self) -> None:
        self.runtime_text.configure(state="normal")
        self.runtime_text.delete("1.0", tk.END)
        self.runtime_text.configure(state="disabled")

    def _schedule_queue_drain(self) -> None:
        self._drain_queue()
        self.after(100, self._schedule_queue_drain)

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "line":
                self.runtime_text.configure(state="normal")
                self.runtime_text.insert(tk.END, payload + "\n")
                self.runtime_text.see(tk.END)
                self.runtime_text.configure(state="disabled")
            elif kind == "status":
                self.status_var.set(payload)

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _read_or_default(self, path: Path, default_data: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            data = deep_copy_dict(default_data)
            self._write_json(path, data)
            return data

        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("JSON root must be an object")
            return deep_merge(default_data, loaded)
        except Exception as exc:
            messagebox.showwarning(
                self._tr("msg_parse_title"),
                self._tr("msg_parse_body", name=path.name, error=exc),
            )
            return deep_copy_dict(default_data)

    def _ensure_default_config_file(self) -> None:
        if not self.current_config_path.exists() and LEGACY_SETTINGS_FILE.exists():
            self.current_config_path.write_text(LEGACY_SETTINGS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                LEGACY_SETTINGS_FILE.unlink()
            except Exception:
                pass

        if not self.current_config_path.exists():
            self._write_json(self.current_config_path, deep_copy_dict(DEFAULT_SETTINGS))

    def _load_config_file(self, path: Path) -> None:
        self.current_config_path = path
        self._refresh_path_labels()
        self.settings = self._read_or_default(self.current_config_path, DEFAULT_SETTINGS)

        ui_settings = self.settings.setdefault("ui", {})
        if not isinstance(ui_settings, dict):
            ui_settings = {}
            self.settings["ui"] = ui_settings
        stored_ui_theme = self._normalize_ui_theme(ui_settings.get("theme", "light"))
        stored_start_on_boot = bool(ui_settings.get("start_on_boot", False))
        ui_settings.pop("language", None)
        ui_settings["theme"] = stored_ui_theme
        ui_settings["start_on_boot"] = stored_start_on_boot
        ui_theme_changed = stored_ui_theme != self.ui_theme
        self.ui_lang = "en"
        self.ui_theme = stored_ui_theme
        self.start_on_boot_var.set(stored_start_on_boot)
        self._apply_theme_palette()

        sharing_settings = self.settings.setdefault("sharing", {})
        if not isinstance(sharing_settings, dict):
            sharing_settings = {}
            self.settings["sharing"] = sharing_settings
        sharing_mode = str(sharing_settings.get("mode", "passive")).strip().lower()
        if sharing_mode not in {"passive", "clipboard"}:
            sharing_mode = "passive"
        sharing_settings["mode"] = sharing_mode
        sharing_settings.pop("clipboard", None)

        self.settings.setdefault("serial", {})["baud"] = FIXED_BAUD
        self.settings.setdefault("serial", {}).setdefault("port", "COM7")

        capture = self.settings.setdefault("capture", {})
        capture["enabled_by_default"] = False
        capture.setdefault("toggle_combo", "ctrl+f1")
        if str(capture.get("toggle_combo", "")).strip().lower() == "f1":
            capture["toggle_combo"] = "ctrl+f1"

        keyboard = self.settings.setdefault("keyboard", {})
        profiles = keyboard.get("layout_profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        profiles.setdefault("us", {})
        keyboard["layout_profiles"] = profiles

        current_layout = str(keyboard.get("layout", "us")).strip() or "us"
        keyboard["layout"] = current_layout

        layouts = keyboard.get("layouts")
        if not isinstance(layouts, list):
            layouts = ["us"]
        layouts_norm = [str(item).strip() for item in layouts if str(item).strip()]
        if "us" not in layouts_norm:
            layouts_norm.insert(0, "us")
        if current_layout not in layouts_norm:
            layouts_norm.insert(0, current_layout)
        keyboard["layouts"] = layouts_norm
        keyboard["use_windows_layout"] = bool(keyboard.get("use_windows_layout", False))
        keyboard.pop("layout_switch_key", None)
        keyboard.pop("language_switch_combo", None)

        self._sync_startup_bootstrap()

        if ui_theme_changed:
            self.title(self._tr("window_title"))
            self._refresh_tray_menu()
            self._rebuild_ui()

    def _load_config_dialog(self) -> None:
        selected = filedialog.askopenfilename(
            title=self._tr("dlg_load_config_title"),
            initialdir=str(ROOT_DIR),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return

        self._load_config_file(Path(selected))
        self._form_from_data()
        self._refresh_pack_choices()
        if self.process is not None and self.process.poll() is None:
            self._append_runtime_line(self._tr("log_settings_changed_restarting"))
            self._restart_switcher()

    def _save_config_dialog(self, restart_if_running: bool = False) -> None:
        try:
            previous_toggle_combo = str(self.settings.get("capture", {}).get("toggle_combo", "")).strip().lower()
            new_settings = self._settings_from_form()
        except Exception as exc:
            messagebox.showerror(self._tr("msg_save_failed_title"), str(exc))
            return

        selected = filedialog.asksaveasfilename(
            title=self._tr("dlg_save_config_title"),
            initialdir=str(ROOT_DIR),
            initialfile=self.current_config_path.name,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return

        target_path = Path(selected)
        self._write_json(target_path, new_settings)
        self.current_config_path = target_path
        self.settings = new_settings
        self._sync_startup_bootstrap()
        self._refresh_path_labels()
        self._form_from_data()

        toggle_combo_changed = previous_toggle_combo != str(new_settings.get("capture", {}).get("toggle_combo", "")).strip().lower()
        if self.process is not None and self.process.poll() is None and (restart_if_running or toggle_combo_changed):
            self._append_runtime_line(self._tr("log_settings_changed_restarting"))
            self._restart_switcher()

        messagebox.showinfo(
            self._tr("msg_config_saved_title"),
            self._tr("msg_config_saved_body", path=target_path),
        )

    def _load_all_files(self) -> None:
        self.language_packs = self._read_or_default(self.language_packs_path, DEFAULT_LANGUAGE_PACKS)
        self._ensure_default_config_file()
        self._load_config_file(self.current_config_path)

        self._form_from_data()
        self._refresh_pack_choices()

    def _form_from_data(self) -> None:
        ui_settings = self.settings.get("ui", {})
        serial = self.settings.get("serial", {})
        capture = self.settings.get("capture", {})
        sharing = self.settings.get("sharing", {})
        keyboard = self.settings.get("keyboard", {})

        self.start_on_boot_var.set(bool(ui_settings.get("start_on_boot", False)) if isinstance(ui_settings, dict) else False)
        self.port_var.set(str(serial.get("port", "COM7")))
        combo_parts = split_combo_expression(str(capture.get("toggle_combo", "ctrl+f1")))
        for index, part in enumerate(combo_parts):
            self.capture_toggle_vars[index].set(part)

        mode = str(sharing.get("mode", "passive")).strip().lower() if isinstance(sharing, dict) else "passive"
        if mode not in {"passive", "clipboard"}:
            mode = "passive"
        self.peripheral_mode_var.set(mode)
        self._apply_peripheral_mode_ui_state()

        profiles = keyboard.get("layout_profiles", {})
        if not isinstance(profiles, dict):
            profiles = {"us": {}}
        profiles.setdefault("us", {})
        keyboard["layout_profiles"] = profiles

        selected_layout = sanitize_profile_name(str(keyboard.get("layout", "us")) or "us")
        layout_order = keyboard.get("layouts", [])
        if not isinstance(layout_order, list):
            layout_order = []

        ordered: List[str] = []
        for name in layout_order:
            n = sanitize_profile_name(str(name))
            if n and PROFILE_NAME_RE.match(n) and n not in ordered:
                ordered.append(n)
        if selected_layout not in ordered:
            ordered.insert(0, selected_layout)
        if "us" not in ordered:
            ordered.insert(0, "us")

        keyboard["layout"] = selected_layout
        keyboard["layouts"] = ordered
        self._suspend_keyboard_toggle_save = True
        try:
            self.use_windows_layout_var.set(bool(keyboard.get("use_windows_layout", False)))
        finally:
            self._suspend_keyboard_toggle_save = False
        self._apply_keyboard_mode_ui_state()

    def _settings_from_form(self) -> Dict[str, Any]:
        settings = deep_merge({}, self.settings if isinstance(self.settings, dict) else DEFAULT_SETTINGS)

        ui_settings = settings.setdefault("ui", {})
        serial = settings.setdefault("serial", {})
        capture = settings.setdefault("capture", {})
        sharing = settings.setdefault("sharing", {})
        keyboard = settings.setdefault("keyboard", {})

        if not isinstance(ui_settings, dict):
            ui_settings = {}
            settings["ui"] = ui_settings
        ui_settings.pop("language", None)
        ui_settings["theme"] = self._normalize_ui_theme(self.ui_theme)
        ui_settings["start_on_boot"] = bool(self.start_on_boot_var.get())

        serial["port"] = self.port_var.get().strip() or "COM7"
        serial["baud"] = FIXED_BAUD

        capture["enabled_by_default"] = False
        capture["toggle_combo"] = build_combo_expression([var.get() for var in self.capture_toggle_vars])

        if not isinstance(sharing, dict):
            sharing = {}
            settings["sharing"] = sharing
        mode = str(self.peripheral_mode_var.get() or "passive").strip().lower()
        if mode not in {"passive", "clipboard"}:
            mode = "passive"
        sharing["mode"] = mode
        sharing.pop("clipboard", None)

        selected_layout = sanitize_profile_name(str(keyboard.get("layout", "us")) or "us")
        raw_order = keyboard.get("layouts", [])
        if not isinstance(raw_order, list):
            raw_order = []
        order: List[str] = []
        for item in raw_order:
            normalized = sanitize_profile_name(str(item))
            if normalized and PROFILE_NAME_RE.match(normalized) and normalized not in order:
                order.append(normalized)

        if selected_layout not in order:
            order.insert(0, selected_layout)
        if "us" not in order:
            order.insert(0, "us")

        profiles = keyboard.get("layout_profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        profiles.setdefault("us", {})
        profiles.setdefault(selected_layout, {})

        selected_display = self.pack_var.get().strip()
        selected_pack_id = self.pack_display_to_id.get(selected_display, "")

        keyboard["layout"] = selected_layout
        keyboard["layouts"] = order
        keyboard["layout_profiles"] = profiles
        keyboard["selected_pack_id"] = selected_pack_id
        keyboard["use_windows_layout"] = bool(self.use_windows_layout_var.get())
        keyboard.pop("layout_switch_key", None)
        keyboard.pop("language_switch_combo", None)

        return settings

    def _save_from_form(self, restart_if_running: bool = False) -> bool:
        try:
            previous_toggle_combo = str(self.settings.get("capture", {}).get("toggle_combo", "")).strip().lower()
            new_settings = self._settings_from_form()
            self._write_json(self.current_config_path, new_settings)
            self.settings = new_settings
            self._sync_startup_bootstrap()
            self._refresh_path_labels()
            self._form_from_data()
            toggle_combo_changed = previous_toggle_combo != str(new_settings.get("capture", {}).get("toggle_combo", "")).strip().lower()
            if self.process is not None and self.process.poll() is None and (restart_if_running or toggle_combo_changed):
                self._append_runtime_line(self._tr("log_settings_changed_restarting"))
                self._restart_switcher()
            return True
        except Exception as exc:
            messagebox.showerror(self._tr("msg_save_failed_title"), str(exc))
            return False

    def _refresh_ports(self) -> None:
        ports: List[str] = []
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            pass

        existing = self.port_var.get().strip()
        if existing and existing not in ports:
            ports.insert(0, existing)

        self.port_combo["values"] = ports

    def _build_pack_display(self, pack_id: str, pack: Dict[str, Any]) -> str:
        langs = pack.get("langs", [])
        remap = pack.get("remap", {})
        lang_text = ",".join(str(item) for item in langs[:2]) if isinstance(langs, list) and langs else self._tr("n_a")
        remap_count = len(remap) if isinstance(remap, dict) else 0
        return f"{lang_text} | {pack_id} | {remap_count} {self._tr('map_rules')}"

    def _on_pack_search_changed(self, *_args: Any) -> None:
        if hasattr(self, "pack_combo"):
            self._refresh_pack_choices()

    def _clear_pack_search(self) -> None:
        if self.pack_search_var.get():
            self.pack_search_var.set("")

    def _pack_matches_search(self, pack_id: str, pack: Dict[str, Any], query: str) -> bool:
        if not query:
            return True

        langs = pack.get("langs", [])
        profile = str(pack.get("profile", "") or pack_id)
        remap = pack.get("remap", {})
        lang_text = " ".join(str(item) for item in langs) if isinstance(langs, list) else ""
        remap_count = len(remap) if isinstance(remap, dict) else 0
        haystack = " ".join(
            [
                pack_id,
                profile,
                lang_text,
                self._build_pack_display(pack_id, pack),
                str(remap_count),
            ]
        ).lower()
        return query in haystack

    def _preferred_pack_id_from_settings(self, packs: Dict[str, Any]) -> Optional[str]:
        keyboard = self.settings.get("keyboard", {}) if isinstance(self.settings, dict) else {}
        if not isinstance(keyboard, dict):
            return None

        selected_pack_id = str(keyboard.get("selected_pack_id", "")).strip()
        if selected_pack_id and selected_pack_id in packs:
            return selected_pack_id

        current_layout = sanitize_profile_name(str(keyboard.get("layout", "")) or "")
        if not current_layout:
            return None

        for pack_id, pack in packs.items():
            if not isinstance(pack, dict):
                continue
            profile = sanitize_profile_name(str(pack.get("profile", "")) or pack_id)
            if profile == current_layout:
                return pack_id

        return None

    def _refresh_pack_choices(self) -> None:
        self.pack_display_to_id = {}
        packs = self.language_packs.get("packs", {}) if isinstance(self.language_packs, dict) else {}
        if not isinstance(packs, dict):
            packs = {}
        search_query = self.pack_search_var.get().strip().lower()

        choices: List[str] = []
        id_to_display: Dict[str, str] = {}
        for pack_id in sorted(packs.keys()):
            pack = packs.get(pack_id)
            if not isinstance(pack, dict):
                continue
            if not self._pack_matches_search(pack_id, pack, search_query):
                continue
            display = self._build_pack_display(pack_id, pack)
            self.pack_display_to_id[display] = pack_id
            id_to_display[pack_id] = display
            choices.append(display)

        self.pack_combo["values"] = choices

        selected = ""
        current_display = self.pack_var.get().strip()
        if current_display in self.pack_display_to_id:
            selected = current_display
        else:
            preferred_pack_id = self._preferred_pack_id_from_settings(packs)
            if preferred_pack_id and preferred_pack_id in id_to_display:
                selected = id_to_display[preferred_pack_id]
            elif choices:
                selected = choices[0]
        self.pack_var.set(selected)

        if selected:
            self._set_pack_info(selected)
        else:
            self.pack_info_var.set(self._tr("pack_no_match"))

    def _set_pack_info(self, display_text: str) -> None:
        pack_id = self.pack_display_to_id.get(display_text)
        if not pack_id:
            self.pack_info_var.set(self._tr("pack_none_selected"))
            return

        packs = self.language_packs.get("packs", {})
        pack = packs.get(pack_id, {}) if isinstance(packs, dict) else {}
        if not isinstance(pack, dict):
            self.pack_info_var.set(self._tr("pack_none_selected"))
            return

        profile = str(pack.get("profile", ""))
        langs = pack.get("langs", [])
        lang_text = ", ".join(str(item) for item in langs[:4]) if isinstance(langs, list) else ""
        remap_count = len(pack.get("remap", {})) if isinstance(pack.get("remap"), dict) else 0
        self.pack_info_var.set(
            self._tr(
                "pack_info",
                profile=profile or self._tr("n_a"),
                langs=lang_text or self._tr("n_a"),
                count=remap_count,
            )
        )

    def _on_pack_selected(self, _event: Optional[tk.Event] = None) -> None:
        self._set_pack_info(self.pack_var.get().strip())

    def _apply_selected_pack(self) -> None:
        if bool(self.use_windows_layout_var.get()):
            return

        display = self.pack_var.get().strip()
        pack_id = self.pack_display_to_id.get(display)
        if not pack_id:
            messagebox.showerror(self._tr("msg_apply_failed_title"), self._tr("msg_apply_select_pack"))
            return

        packs = self.language_packs.get("packs", {}) if isinstance(self.language_packs, dict) else {}
        pack = packs.get(pack_id) if isinstance(packs, dict) else None
        if not isinstance(pack, dict):
            messagebox.showerror(self._tr("msg_apply_failed_title"), self._tr("msg_apply_invalid_pack"))
            return

        if not self._save_from_form(restart_if_running=False):
            return

        profile = sanitize_profile_name(str(pack.get("profile", "")) or pack_id)
        remap = pack.get("remap", {})
        if not isinstance(remap, dict):
            remap = {}

        keyboard = self.settings.setdefault("keyboard", {})
        profiles = keyboard.get("layout_profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        profiles.setdefault("us", {})
        profiles[profile] = remap
        keyboard["layout_profiles"] = profiles

        layouts = keyboard.get("layouts")
        if not isinstance(layouts, list):
            layouts = []
        normalized_layouts = [sanitize_profile_name(str(name)) for name in layouts if str(name).strip()]
        if "us" not in normalized_layouts:
            normalized_layouts.insert(0, "us")
        if profile not in normalized_layouts:
            normalized_layouts.append(profile)

        keyboard["layouts"] = normalized_layouts
        keyboard["layout"] = profile
        keyboard["selected_pack_id"] = pack_id

        self._write_json(self.current_config_path, self.settings)
        self._refresh_path_labels()
        self._form_from_data()
        if self.process is not None and self.process.poll() is None:
            self._append_runtime_line(self._tr("log_pack_applied_restarting"))
            self._restart_switcher()

        messagebox.showinfo(
            self._tr("msg_pack_applied_title"),
            self._tr("msg_pack_applied_body", pack_id=pack_id, profile=profile, count=len(remap)),
        )
    def _resolve_python_exe(self) -> str:
        return os.environ.get("PYTHON", sys.executable)

    def _resolve_switcher_command(self) -> List[str]:
        if getattr(sys, "frozen", False):
            switcher_exe = ROOT_DIR / "master_pc_client.exe"
            if not switcher_exe.exists():
                raise FileNotFoundError(f"Missing runtime executable: {switcher_exe}")
            return [
                str(switcher_exe),
                "--settings",
                str(self.current_config_path),
            ]
        return [
            self._resolve_python_exe(),
            "master_pc_client.py",
            "--settings",
            str(self.current_config_path),
        ]

    def _start_switcher(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo(self._tr("msg_already_running_title"), self._tr("msg_already_running_body"))
            return

        if not self._save_from_form(restart_if_running=False):
            return

        try:
            cmd = self._resolve_switcher_command()
        except Exception as exc:
            messagebox.showerror(self._tr("msg_launch_failed_title"), self._tr("msg_launch_failed_body", error=exc))
            return

        self._append_runtime_line("[run] " + " ".join(cmd))
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                creationflags=create_no_window,
            )
        except Exception as exc:
            messagebox.showerror(self._tr("msg_launch_failed_title"), self._tr("msg_launch_failed_body", error=exc))
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.restart_btn.configure(state="normal")
        self.status_var.set(self._tr("status_running"))

        threading.Thread(target=self._stream_process_output, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._wait_process, args=(self.process,), daemon=True).start()

    def _stream_process_output(self, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            self._append_runtime_line(line.rstrip("\n"))
        try:
            proc.stdout.close()
        except Exception:
            pass

    def _wait_process(self, proc: subprocess.Popen) -> None:
        code = proc.wait()

        def _update() -> None:
            if self.process is proc:
                self.process = None
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.restart_btn.configure(state="disabled")
            self.output_queue.put(("status", self._tr("status_stopped", code=code)))
            self.output_queue.put(("line", self._tr("log_exit", code=code)))

            if self.restart_requested:
                self.restart_requested = False
                self.after(250, self._start_switcher)

        self.after(0, _update)

    def _restart_switcher(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._append_runtime_line(self._tr("log_restart_requested"))
            self.restart_requested = True
            self._stop_switcher()
            return

        self.restart_requested = False
        self._start_switcher()

    def _stop_switcher(self) -> None:
        proc = self.process
        if proc is None or proc.poll() is not None:
            return

        self._append_runtime_line(self._tr("log_stopping"))

        try:
            proc.terminate()
        except Exception as exc:
            self._append_runtime_line(self._tr("log_terminate_failed", error=exc))
            try:
                proc.kill()
            except Exception as kill_exc:
                self._append_runtime_line(self._tr("log_kill_failed", error=kill_exc))

    def _on_close(self) -> None:
        if self._tray_enabled and not self._exiting:
            self._hide_to_tray(show_dialog=True, show_notification=False)
            return
        self._quit_application()


def main() -> None:
    if os.name == "nt":
        try:
            import ctypes

            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    start_hidden, auto_start_runtime = parse_launch_flags(sys.argv)
    app = SwitcherUI(start_hidden=start_hidden, auto_start_runtime=auto_start_runtime)
    app.mainloop()


if __name__ == "__main__":
    main()

