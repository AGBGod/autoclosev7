"""
gui.py
-------
Grafische Benutzeroberflaeche (GUI) von AutoCloseV7 im Dark Mode.

Enthaelt:
  - Start/Stop-Button fuer die Ueberwachung
  - Liste der Ziel-Fenstertitel und Ziel-Prozesse mit Hinzufuegen/Entfernen
  - Einstellbares Pruefintervall
  - Statistikanzeige
  - Autostart-Umschalter und Anzeige des aktiven Hotkeys
"""

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from .autostart import AutostartManager
from .config_manager import ConfigManager
from .hotkey import HotkeyManager
from .stats import StatsTracker
from .tray import TrayIcon
from .updater import UpdateChecker
from .window_monitor import PLATFORM_SUPPORTED, WindowMonitor

logger = logging.getLogger("AutoCloseV7.GUI")

# --- Dark-Mode-Farbpalette ---------------------------------------------------
BG_COLOR = "#1e1e2e"
FG_COLOR = "#e4e4ef"
ACCENT_COLOR = "#7c9dff"
DANGER_COLOR = "#ff6b6b"
SUCCESS_COLOR = "#63d29c"
PANEL_COLOR = "#282838"
BORDER_COLOR = "#3a3a4d"


class AutoCloseApp(tk.Tk):
    """Hauptfenster der Anwendung."""

    def __init__(self):
        super().__init__()

        self.title("AutoCloseV7")
        self.geometry("680x600")
        self.minsize(580, 500)
        self.configure(bg=BG_COLOR)

        # --- Kernkomponenten ---------------------------------------------
        self.config_manager = ConfigManager()
        self.stats = StatsTracker()
        self.autostart_manager = AutostartManager()
        self.hotkey_manager = HotkeyManager()
        self.updater = UpdateChecker()

        self.monitor = WindowMonitor(
            config=self.config_manager,
            stats=self.stats,
            on_item_closed=self._on_item_closed,
            on_error=self._on_monitor_error,
        )

        self.tray = TrayIcon(
            on_toggle=self._toggle_monitoring,
            on_show=self._restore_from_tray,
            on_quit=self._quit_app,
            is_running=lambda: self.monitor.is_running,
        )

        self._setup_style()
        self._build_layout()
        self._register_hotkey()

        self.protocol("WM_DELETE_WINDOW", self._on_close_button)

        if not PLATFORM_SUPPORTED:
            self._log_to_ui(
                "Warnung: Diese Windows-Funktionen (Fenstererkennung, Tray, Autostart, "
                "Hotkey) sind auf diesem System nicht verfuegbar. AutoCloseV7 ist fuer "
                "Windows entwickelt."
            )

        if self.config_manager.get("monitoring_enabled_on_start", False):
            self._toggle_monitoring(force_start=True)

        self.tray.start()
        self._refresh_stats_loop()

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _setup_style(self) -> None:
        """Konfiguriert das dunkle Erscheinungsbild aller ttk-Widgets."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG_COLOR)
        style.configure("Panel.TFrame", background=PANEL_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR, font=("Segoe UI", 10))
        style.configure(
            "Header.TLabel", background=BG_COLOR, foreground=FG_COLOR, font=("Segoe UI", 16, "bold")
        )
        style.configure(
            "TButton",
            background=PANEL_COLOR,
            foreground=FG_COLOR,
            borderwidth=0,
            focusthickness=0,
            padding=8,
            font=("Segoe UI", 10),
        )
        style.map("TButton", background=[("active", BORDER_COLOR)])
        style.configure(
            "Start.TButton",
            background=SUCCESS_COLOR,
            foreground="#0a1f14",
            font=("Segoe UI", 11, "bold"),
            padding=10,
        )
        style.map("Start.TButton", background=[("active", "#4fb384")])
        style.configure(
            "Stop.TButton",
            background=DANGER_COLOR,
            foreground="#2a0a0a",
            font=("Segoe UI", 11, "bold"),
            padding=10,
        )
        style.map("Stop.TButton", background=[("active", "#e05252")])
        style.configure("TEntry", fieldbackground=PANEL_COLOR, foreground=FG_COLOR, insertcolor=FG_COLOR)
        style.configure("TSpinbox", fieldbackground=PANEL_COLOR, foreground=FG_COLOR, arrowsize=14)
        style.configure("TCheckbutton", background=BG_COLOR, foreground=FG_COLOR)
        style.configure("TLabelframe", background=BG_COLOR, foreground=FG_COLOR)
        style.configure(
            "TLabelframe.Label", background=BG_COLOR, foreground=FG_COLOR, font=("Segoe UI", 10, "bold")
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        """Baut alle sichtbaren Bereiche des Hauptfensters auf."""
        header = ttk.Frame(self, padding=(16, 16, 16, 8))
        header.pack(fill="x")
        ttk.Label(header, text="AutoCloseV7", style="Header.TLabel").pack(side="left")

        self.status_var = tk.StringVar(value="Gestoppt")
        ttk.Label(header, textvariable=self.status_var).pack(side="right")

        control_frame = ttk.Frame(self, padding=(16, 0, 16, 8))
        control_frame.pack(fill="x")

        self.toggle_button = ttk.Button(
            control_frame, text="Start", style="Start.TButton", command=self._toggle_monitoring
        )
        self.toggle_button.pack(side="left")

        ttk.Label(control_frame, text="Pruefintervall (Sek.):").pack(side="left", padx=(20, 6))
        self.interval_var = tk.StringVar(value=str(self.config_manager.get("check_interval_seconds", 2.0)))
        interval_spin = ttk.Spinbox(
            control_frame,
            from_=0.5,
            to=60.0,
            increment=0.5,
            width=6,
            textvariable=self.interval_var,
            command=self._on_interval_changed,
        )
        interval_spin.pack(side="left")
        interval_spin.bind("<Return>", lambda _e: self._on_interval_changed())
        interval_spin.bind("<FocusOut>", lambda _e: self._on_interval_changed())

        self.autostart_var = tk.BooleanVar(value=self.autostart_manager.is_enabled())
        autostart_check = ttk.Checkbutton(
            control_frame,
            text="Mit Windows starten",
            variable=self.autostart_var,
            command=self._on_autostart_toggled,
        )
        autostart_check.pack(side="right")

        # --- Zielliste -----------------------------------------------------
        targets_frame = ttk.Labelframe(self, text="Zu schliessende Fenster / Programme", padding=12)
        targets_frame.pack(fill="both", expand=True, padx=16, pady=8)

        list_container = ttk.Frame(targets_frame)
        list_container.pack(fill="both", expand=True)

        self.targets_listbox = tk.Listbox(
            list_container,
            bg=PANEL_COLOR,
            fg=FG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground="#0b0b12",
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
        )
        self.targets_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.targets_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.targets_listbox.configure(yscrollcommand=scrollbar.set)

        entry_row = ttk.Frame(targets_frame)
        entry_row.pack(fill="x", pady=(10, 0))

        self.new_target_var = tk.StringVar()
        target_entry = ttk.Entry(entry_row, textvariable=self.new_target_var)
        target_entry.pack(side="left", fill="x", expand=True)
        target_entry.bind("<Return>", lambda _e: self._add_target())

        self.target_type_var = tk.StringVar(value="Fenstertitel")
        type_menu = ttk.OptionMenu(
            entry_row, self.target_type_var, "Fenstertitel", "Fenstertitel", "Prozessname"
        )
        type_menu.pack(side="left", padx=6)

        ttk.Button(entry_row, text="Hinzufuegen", command=self._add_target).pack(side="left", padx=(6, 0))
        ttk.Button(entry_row, text="Entfernen", command=self._remove_selected_target).pack(
            side="left", padx=(6, 0)
        )

        self._reload_target_list()

        # --- Statistik -------------------------------------------------------
        stats_frame = ttk.Labelframe(self, text="Statistik", padding=12)
        stats_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.stats_total_var = tk.StringVar(value="Geschlossen: 0")
        self.stats_last_var = tk.StringVar(value="Zuletzt: -")
        self.stats_hotkey_var = tk.StringVar(
            value=f"Hotkey: {self.config_manager.get('hotkey', 'ctrl+alt+p')}"
        )

        ttk.Label(stats_frame, textvariable=self.stats_total_var).pack(side="left")
        ttk.Label(stats_frame, textvariable=self.stats_last_var).pack(side="left", padx=20)
        ttk.Label(stats_frame, textvariable=self.stats_hotkey_var).pack(side="right")

        # --- Log-Ausgabe -----------------------------------------------------
        log_frame = ttk.Labelframe(self, text="Ereignisse", padding=12)
        log_frame.pack(fill="both", expand=False, padx=16, pady=(0, 16))

        self.log_text = tk.Text(
            log_frame,
            height=6,
            bg=PANEL_COLOR,
            fg=FG_COLOR,
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------
    def _toggle_monitoring(self, force_start: bool = False) -> None:
        """Startet oder stoppt die Ueberwachung (auch vom Tray/Hotkey aufrufbar)."""
        if force_start or not self.monitor.is_running:
            self.monitor.start()
        else:
            self.monitor.stop()
        self.after(0, self._update_toggle_button)
        self.after(0, self.tray.refresh_icon)

    def _update_toggle_button(self) -> None:
        """Passt Text/Farbe des Start/Stop-Buttons an den aktuellen Status an."""
        if self.monitor.is_running:
            self.toggle_button.configure(text="Stop", style="Stop.TButton")
            self.status_var.set("Aktiv")
        else:
            self.toggle_button.configure(text="Start", style="Start.TButton")
            self.status_var.set("Gestoppt")

    def _on_interval_changed(self) -> None:
        """Validiert und uebernimmt das neue Pruefintervall aus dem Eingabefeld."""
        try:
            value = float(self.interval_var.get())
            if value <= 0:
                raise ValueError("Intervall muss positiv sein")
            self.config_manager.set("check_interval_seconds", value)
            self._log_to_ui(f"Pruefintervall auf {value} Sekunden gesetzt.")
        except ValueError:
            messagebox.showerror(
                "Ungueltiger Wert",
                "Bitte eine positive Zahl fuer das Pruefintervall eingeben (z. B. 2.0).",
            )
            self.interval_var.set(str(self.config_manager.get("check_interval_seconds", 2.0)))

    def _on_autostart_toggled(self) -> None:
        """Aktiviert/deaktiviert den Windows-Autostart entsprechend der Checkbox."""
        enabled = self.autostart_var.get()
        success = self.autostart_manager.set_enabled(enabled)
        if not success:
            messagebox.showerror(
                "Autostart",
                "Autostart konnte nicht geaendert werden. Diese Funktion ist nur unter Windows verfuegbar.",
            )
            self.autostart_var.set(self.autostart_manager.is_enabled())
            return
        self.config_manager.set("autostart_enabled", enabled)
        self._log_to_ui(f"Autostart {'aktiviert' if enabled else 'deaktiviert'}.")

    def _add_target(self) -> None:
        """Fuegt den Wert aus dem Eingabefeld als neues Ziel hinzu."""
        value = self.new_target_var.get().strip()
        if not value:
            return
        if self.target_type_var.get() == "Prozessname":
            self.config_manager.add_process_name(value)
        else:
            self.config_manager.add_window_title(value)
        self.new_target_var.set("")
        self._reload_target_list()
        self._log_to_ui(f"Ziel hinzugefuegt: {value}")

    def _remove_selected_target(self) -> None:
        """Entfernt den in der Liste ausgewaehlten Eintrag."""
        selection = self.targets_listbox.curselection()
        if not selection:
            return
        entry = self.targets_listbox.get(selection[0])
        # Format: "[Fenster] Titel" oder "[Prozess] name.exe"
        if entry.startswith("[Prozess] "):
            self.config_manager.remove_process_name(entry.replace("[Prozess] ", "", 1))
        elif entry.startswith("[Fenster] "):
            self.config_manager.remove_window_title(entry.replace("[Fenster] ", "", 1))
        self._reload_target_list()
        self._log_to_ui(f"Ziel entfernt: {entry}")

    def _reload_target_list(self) -> None:
        """Baut die Listbox anhand der aktuellen Konfiguration neu auf."""
        self.targets_listbox.delete(0, tk.END)
        for title in self.config_manager.window_titles:
            self.targets_listbox.insert(tk.END, f"[Fenster] {title}")
        for name in self.config_manager.process_names:
            self.targets_listbox.insert(tk.END, f"[Prozess] {name}")

    def _register_hotkey(self) -> None:
        """Registriert den in der Konfiguration hinterlegten globalen Hotkey."""
        hotkey = self.config_manager.get("hotkey", "ctrl+alt+p")
        registered = self.hotkey_manager.register(hotkey, self._toggle_monitoring)
        if not registered:
            self._log_to_ui(
                f"Hinweis: Hotkey '{hotkey}' konnte nicht registriert werden "
                "(nur unter Windows verfuegbar)."
            )

    # ------------------------------------------------------------------
    # Callbacks vom Ueberwachungs-Thread (laufen NICHT im GUI-Thread!)
    # ------------------------------------------------------------------
    def _on_item_closed(self, name: str, kind: str) -> None:
        """Wird vom Hintergrund-Thread aufgerufen, sobald ein Element geschlossen wurde."""
        # tkinter ist nicht thread-sicher - Updates muessen ueber after() in den GUI-Thread.
        self.after(0, lambda: self._log_to_ui(f"Geschlossen: {name}"))

    def _on_monitor_error(self, message: str) -> None:
        """Wird vom Hintergrund-Thread bei einem Fehler aufgerufen."""
        self.after(0, lambda: self._log_to_ui(f"Fehler: {message}"))

    def _refresh_stats_loop(self) -> None:
        """Aktualisiert periodisch die Statistikanzeige und den Start/Stop-Status."""
        self.stats_total_var.set(f"Geschlossen: {self.stats.total_closed}")
        last = self.stats.last_closed
        self.stats_last_var.set(f"Zuletzt: {last.name}" if last else "Zuletzt: -")
        self._update_toggle_button()
        self.after(1000, self._refresh_stats_loop)

    def _log_to_ui(self, message: str) -> None:
        """Schreibt eine Zeile in das Ereignis-Fenster und in die Logdatei."""
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        logger.info(message)

    # ------------------------------------------------------------------
    # Fenstersteuerung / Tray
    # ------------------------------------------------------------------
    def _restore_from_tray(self) -> None:
        """Zeigt das Hauptfenster wieder an, nachdem es in den Tray minimiert wurde."""
        self.after(0, self.deiconify)

    def _on_close_button(self) -> None:
        """Reagiert auf den Schliessen-Button des Fensters (X)."""
        if self.config_manager.get("minimize_to_tray_on_close", True):
            self.withdraw()
            self._log_to_ui("In den Tray minimiert. Ueber das Tray-Symbol wieder oeffnen.")
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        """Beendet die Anwendung vollstaendig und raeumt alle Ressourcen auf."""
        self.monitor.stop()
        self.hotkey_manager.unregister()
        self.tray.stop()
        self.config_manager.save()
        self.destroy()
