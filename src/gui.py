"""
gui.py
-------
Grafische Benutzeroberflaeche (GUI) von AutoCloseV7 im klassischen Windows-Look
(angelehnt an AutoCloseV4).

Aufbau:
  - Liste "Programme fuer OPEN"  mit [+]/[-] Knoepfen (Programme, die per
    Open-Knopf gestartet werden)
  - Liste "Programme fuer CLOSE" mit [+]/[-] Knoepfen (Fenstertitel oder
    Prozessnamen, die geschlossen werden sollen)
  - Knopfleiste unten: Open | Close | ActivateAuto | AutoClose
  - Statuszeile am unteren Rand

Die Knoepfe:
  - Open:         startet das markierte Programm der OPEN-Liste
                  (ohne Markierung: alle Programme der Liste)
  - Close:        schliesst das markierte Ziel der CLOSE-Liste sofort
                  (ohne Markierung: alle Ziele der Liste)
  - ActivateAuto: schaltet die automatische Dauerueberwachung ein/aus
                  (laeuft im Hintergrund und schliesst Ziele automatisch)
  - AutoClose:    schliesst sofort alle Ziele der CLOSE-Liste (ein Durchlauf)
"""

import logging
import math
import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from .autostart import AutostartManager
from .config_manager import ConfigManager
from .hotkey import HotkeyManager
from .stats import StatsTracker
from .tray import TrayIcon
from .updater import UpdateChecker
from .window_monitor import PLATFORM_SUPPORTED, WindowMonitor

logger = logging.getLogger("AutoCloseV7.GUI")


class AutoCloseApp(tk.Tk):
    """Hauptfenster der Anwendung im klassischen V4-Stil."""

    def __init__(self):
        super().__init__()

        self.title("AutoCloseV7")
        self.geometry("720x540")
        self.minsize(600, 460)

        # --- UI-Warteschlange ----------------------------------------------
        # tkinter ist nicht thread-sicher. Alle Aktionen, die von fremden
        # Threads ausgeloest werden (Tray-Menue, globaler Hotkey,
        # Ueberwachungs-Thread), landen in dieser Warteschlange und werden
        # periodisch im GUI-Thread abgearbeitet (siehe _process_ui_queue).
        self._ui_queue: "queue.Queue" = queue.Queue()

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

        # Tray-Callbacks kommen aus dem Tray-Thread - nur in die Warteschlange
        # legen, niemals direkt Tk-Methoden aufrufen.
        self.tray = TrayIcon(
            on_toggle=lambda: self._run_on_ui_thread(self._toggle_monitoring),
            on_show=lambda: self._run_on_ui_thread(self._restore_from_tray),
            on_quit=lambda: self._run_on_ui_thread(self._quit_app),
            is_running=lambda: self.monitor.is_running,
        )

        self._build_layout()
        self._register_hotkey()

        self.protocol("WM_DELETE_WINDOW", self._on_close_button)

        if not PLATFORM_SUPPORTED:
            self._set_status(
                "Warnung: Windows-Funktionen sind auf diesem System nicht verfuegbar."
            )

        if self.config_manager.get("monitoring_enabled_on_start", False):
            self._toggle_monitoring(force_start=True)

        self.tray.start()
        self._process_ui_queue()
        self._refresh_status_loop()

    # ------------------------------------------------------------------
    # Thread-sichere Bruecke in den GUI-Thread
    # ------------------------------------------------------------------
    def _run_on_ui_thread(self, func) -> None:
        """
        Legt `func` in die UI-Warteschlange, damit sie im GUI-Thread ausgefuehrt
        wird. Darf gefahrlos aus beliebigen Threads aufgerufen werden
        (queue.Queue ist thread-sicher, es werden keine Tk-APIs beruehrt).
        """
        self._ui_queue.put(func)

    def _process_ui_queue(self) -> None:
        """Arbeitet anstehende UI-Aktionen ab - laeuft ausschliesslich im GUI-Thread."""
        try:
            while True:
                func = self._ui_queue.get_nowait()
                try:
                    func()
                except tk.TclError:
                    # Fenster wurde evtl. gerade zerstoert (Beenden) - ignorieren.
                    return
                except Exception:
                    logger.exception("Fehler bei einer UI-Aktion aus der Warteschlange.")
        except queue.Empty:
            pass
        self.after(100, self._process_ui_queue)

    # ------------------------------------------------------------------
    # Layout (klassischer heller V4-Look)
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        """Baut das Fenster auf: zwei Listen mit +/- und die Knopfleiste unten."""
        # --- Bereich "Programme fuer OPEN" -----------------------------------
        tk.Label(self, text="Programme für OPEN").pack(pady=(8, 0))

        open_row = tk.Frame(self)
        open_row.pack(fill="both", expand=True, padx=8, pady=(2, 4))

        self.open_listbox = tk.Listbox(open_row, bg="white", activestyle="none")
        self.open_listbox.pack(side="left", fill="both", expand=True)

        open_buttons = tk.Frame(open_row)
        open_buttons.pack(side="right", fill="y", padx=(8, 0))
        tk.Button(open_buttons, text="+", width=8, command=self._add_open_program).pack(
            pady=(16, 4)
        )
        tk.Button(open_buttons, text="-", width=8, command=self._remove_open_program).pack()

        # --- Bereich "Programme fuer CLOSE" ----------------------------------
        tk.Label(self, text="Programme für CLOSE").pack()

        close_row = tk.Frame(self)
        close_row.pack(fill="both", expand=True, padx=8, pady=(2, 4))

        self.close_listbox = tk.Listbox(close_row, bg="white", activestyle="none")
        self.close_listbox.pack(side="left", fill="both", expand=True)

        close_buttons = tk.Frame(close_row)
        close_buttons.pack(side="right", fill="y", padx=(8, 0))
        tk.Button(close_buttons, text="+", width=8, command=self._add_close_target).pack(
            pady=(16, 4)
        )
        tk.Button(close_buttons, text="-", width=8, command=self._remove_close_target).pack()

        # --- Knopfleiste ------------------------------------------------------
        button_row = tk.Frame(self)
        button_row.pack(pady=10)

        tk.Button(button_row, text="Open", width=10, command=self._open_programs).pack(
            side="left", padx=6
        )
        tk.Button(button_row, text="Close", width=10, command=self._close_selected).pack(
            side="left", padx=6
        )
        self.auto_button = tk.Button(
            button_row, text="ActivateAuto", width=12, command=self._toggle_monitoring
        )
        self.auto_button.pack(side="left", padx=6)
        tk.Button(button_row, text="AutoClose", width=10, command=self._auto_close_now).pack(
            side="left", padx=6
        )

        # --- Einstellungen fuer die Automatik --------------------------------
        settings_row = tk.Frame(self)
        settings_row.pack(pady=(0, 6))

        tk.Label(settings_row, text="Prüfen alle:").pack(side="left")

        self.interval_value_var = tk.StringVar(
            value=self._format_number(self.config_manager.get("check_interval_value", 2.0))
        )
        interval_entry = tk.Entry(settings_row, textvariable=self.interval_value_var, width=6)
        interval_entry.pack(side="left", padx=(4, 2))
        interval_entry.bind("<Return>", lambda _e: self._apply_interval())
        interval_entry.bind("<FocusOut>", lambda _e: self._apply_interval())

        self.interval_unit_var = tk.StringVar(
            value=self.config_manager.get("check_interval_unit", "s")
        )
        unit_menu = tk.OptionMenu(
            settings_row,
            self.interval_unit_var,
            "ms",
            "s",
            "m",
            "h",
            command=lambda _v: self._apply_interval(),
        )
        unit_menu.configure(width=3)
        unit_menu.pack(side="left", padx=(0, 12))

        self.auto_on_start_var = tk.BooleanVar(
            value=bool(self.config_manager.get("monitoring_enabled_on_start", False))
        )
        tk.Checkbutton(
            settings_row,
            text="Automatik nach Start",
            variable=self.auto_on_start_var,
            command=self._apply_auto_on_start,
        ).pack(side="left", padx=(0, 12))

        self.autostart_var = tk.BooleanVar(
            value=bool(self.config_manager.get("autostart_enabled", False))
        )
        tk.Checkbutton(
            settings_row,
            text="Mit Windows starten (nach Neustart)",
            variable=self.autostart_var,
            command=self._apply_autostart,
        ).pack(side="left")

        # --- Statuszeile ------------------------------------------------------
        self.status_var = tk.StringVar(value="Bereit")
        tk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            fill="x", side="bottom"
        )

        self._reload_lists()

    # ------------------------------------------------------------------
    # Listenpflege
    # ------------------------------------------------------------------
    def _reload_lists(self) -> None:
        """Baut beide Listen anhand der aktuellen Konfiguration neu auf."""
        self.open_listbox.delete(0, tk.END)
        for program in self.config_manager.open_programs:
            self.open_listbox.insert(tk.END, program)

        self.close_listbox.delete(0, tk.END)
        for title in self.config_manager.window_titles:
            self.close_listbox.insert(tk.END, title)
        for name in self.config_manager.process_names:
            self.close_listbox.insert(tk.END, name)

    def _add_open_program(self) -> None:
        """Waehlt per Dateidialog ein Programm aus und fuegt es zur OPEN-Liste hinzu."""
        path = filedialog.askopenfilename(
            title="Programm auswählen",
            filetypes=[("Programme", "*.exe"), ("Verknüpfungen", "*.lnk"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        self.config_manager.add_open_program(path)
        self._reload_lists()
        self._set_status(f"Hinzugefügt: {os.path.basename(path)}")

    def _remove_open_program(self) -> None:
        """Entfernt den markierten Eintrag aus der OPEN-Liste."""
        selection = self.open_listbox.curselection()
        if not selection:
            self._set_status("Bitte zuerst einen Eintrag in der OPEN-Liste markieren.")
            return
        entry = self.open_listbox.get(selection[0])
        self.config_manager.remove_open_program(entry)
        self._reload_lists()
        self._set_status(f"Entfernt: {os.path.basename(entry)}")

    def _add_close_target(self) -> None:
        """Fragt einen Fenstertitel oder Prozessnamen ab und fuegt ihn zur CLOSE-Liste hinzu."""
        value = simpledialog.askstring(
            "Programm für CLOSE hinzufügen",
            "Fenstertitel oder Prozessname eingeben\n(z. B. \"Update verfügbar\" oder \"notepad.exe\"):",
            parent=self,
        )
        if not value:
            return
        value = value.strip()
        if not value:
            return
        if value.lower().endswith(".exe"):
            self.config_manager.add_process_name(value)
        else:
            self.config_manager.add_window_title(value)
        self._reload_lists()
        self._set_status(f"Hinzugefügt: {value}")

    def _remove_close_target(self) -> None:
        """Entfernt den markierten Eintrag aus der CLOSE-Liste."""
        selection = self.close_listbox.curselection()
        if not selection:
            self._set_status("Bitte zuerst einen Eintrag in der CLOSE-Liste markieren.")
            return
        entry = self.close_listbox.get(selection[0])
        if entry in self.config_manager.process_names:
            self.config_manager.remove_process_name(entry)
        elif entry in self.config_manager.window_titles:
            self.config_manager.remove_window_title(entry)
        self._reload_lists()
        self._set_status(f"Entfernt: {entry}")

    # ------------------------------------------------------------------
    # Knopf-Aktionen
    # ------------------------------------------------------------------
    def _open_programs(self) -> None:
        """Startet das markierte Programm (oder alle, wenn nichts markiert ist)."""
        selection = self.open_listbox.curselection()
        if selection:
            programs = [self.open_listbox.get(selection[0])]
        else:
            programs = self.config_manager.open_programs

        if not programs:
            self._set_status("Die OPEN-Liste ist leer - mit [+] ein Programm hinzufügen.")
            return

        started = 0
        for program in programs:
            try:
                if sys.platform == "win32":
                    os.startfile(program)  # noqa: S606 - bewusster Programmstart
                else:
                    subprocess.Popen([program])
                started += 1
                logger.info("Gestartet: %s", program)
            except Exception as exc:
                logger.error("Konnte '%s' nicht starten: %s", program, exc)
                messagebox.showerror(
                    "Open", f"Programm konnte nicht gestartet werden:\n{program}\n\n{exc}"
                )
        self._set_status(f"{started} Programm(e) gestartet.")

    def _close_selected(self) -> None:
        """Schliesst das markierte Ziel sofort (oder alle, wenn nichts markiert ist)."""
        selection = self.close_listbox.curselection()
        if selection:
            entry = self.close_listbox.get(selection[0])
            if entry in self.config_manager.process_names:
                closed = self.monitor.close_now(window_titles=[], process_names=[entry])
            else:
                closed = self.monitor.close_now(window_titles=[entry], process_names=[])
        else:
            closed = self.monitor.close_now()
        self._set_status(f"{closed} Fenster/Programm(e) geschlossen.")

    def _auto_close_now(self) -> None:
        """Schliesst sofort alle Ziele der CLOSE-Liste (ein kompletter Durchlauf)."""
        closed = self.monitor.close_now()
        self._set_status(f"AutoClose: {closed} Fenster/Programm(e) geschlossen.")

    # ------------------------------------------------------------------
    # Automatik-Einstellungen (Intervall + Startverhalten)
    # ------------------------------------------------------------------
    @staticmethod
    def _format_number(value) -> str:
        """Formatiert eine Zahl huebsch fuer das Eingabefeld (2.0 -> '2')."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "2"
        if number == int(number):
            return str(int(number))
        return str(number)

    def _apply_interval(self) -> None:
        """Liest Wert + Einheit, rechnet in Sekunden um und speichert das Intervall."""
        raw = self.interval_value_var.get().strip().replace(",", ".")
        unit = self.interval_unit_var.get()
        try:
            value = float(raw)
        except ValueError:
            self._set_status("Ungültige Zahl beim Intervall - bitte z. B. 2 oder 0,5 eingeben.")
            return
        if not math.isfinite(value) or value <= 0:
            self._set_status("Das Intervall muss größer als 0 sein.")
            return

        factor = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}.get(unit, 1.0)
        seconds = value * factor

        clamped = False
        if seconds < 0.2:
            seconds = 0.2
            clamped = True

        self.config_manager.set("check_interval_value", value, autosave=False)
        self.config_manager.set("check_interval_unit", unit, autosave=False)
        self.config_manager.set("check_interval_seconds", seconds)

        # Laeuft die Automatik gerade, kurz neu starten, damit das neue
        # Intervall sofort gilt (sonst wuerde erst der alte Wartezyklus enden).
        if self.monitor.is_running:
            self.monitor.stop()
            self.monitor.start()

        pretty = f"{self._format_number(value)} {unit}"
        if clamped:
            self._set_status(
                f"Intervall gespeichert: {pretty} (Minimum ist 200 ms - es gilt 200 ms)."
            )
        else:
            self._set_status(f"Automatik prüft jetzt alle {pretty}.")

    def _apply_auto_on_start(self) -> None:
        """Speichert, ob die Automatik beim Programmstart sofort aktiv sein soll."""
        enabled = bool(self.auto_on_start_var.get())
        self.config_manager.set("monitoring_enabled_on_start", enabled)
        if enabled:
            self._set_status("Automatik startet künftig automatisch beim Programmstart.")
        else:
            self._set_status("Automatik startet nicht mehr automatisch beim Programmstart.")

    def _apply_autostart(self) -> None:
        """Traegt das Programm in den Windows-Autostart ein bzw. aus."""
        enabled = bool(self.autostart_var.get())
        ok = self.autostart_manager.set_enabled(enabled)
        if not ok:
            # Zuruecksetzen, wenn es nicht geklappt hat (z. B. kein Windows).
            self.autostart_var.set(not enabled)
            self._set_status("Autostart konnte nicht geändert werden (nur unter Windows möglich).")
            return
        self.config_manager.set("autostart_enabled", enabled)
        if enabled:
            self._set_status(
                "Programm startet künftig mit Windows. Tipp: zusätzlich 'Automatik nach Start' "
                "anhaken, damit nach dem Neustart sofort geschlossen wird."
            )
        else:
            self._set_status("Programm startet nicht mehr automatisch mit Windows.")

    def _toggle_monitoring(self, force_start: bool = False) -> None:
        """Schaltet die Dauerueberwachung ein/aus (auch vom Tray/Hotkey aufrufbar)."""
        if force_start or not self.monitor.is_running:
            self.monitor.start()
        else:
            self.monitor.stop()
        self._update_auto_button()
        self.tray.refresh_icon()

    def _update_auto_button(self) -> None:
        """Passt den Text des Auto-Knopfs und die Statuszeile an den Status an."""
        if self.monitor.is_running:
            self.auto_button.configure(text="DeactivateAuto")
            self._set_status("Automatik aktiv - Ziele werden im Hintergrund geschlossen.")
        else:
            self.auto_button.configure(text="ActivateAuto")
            self._set_status("Automatik gestoppt.")

    def _register_hotkey(self) -> None:
        """Registriert den in der Konfiguration hinterlegten globalen Hotkey."""
        hotkey = self.config_manager.get("hotkey", "ctrl+alt+p")
        # Der Hotkey-Callback kommt aus dem keyboard-Thread - deshalb nur in
        # die UI-Warteschlange legen statt direkt Tk-Methoden aufzurufen.
        registered = self.hotkey_manager.register(
            hotkey, lambda: self._run_on_ui_thread(self._toggle_monitoring)
        )
        if registered:
            self._set_status(f"Bereit - Hotkey für Automatik: {hotkey}")

    # ------------------------------------------------------------------
    # Callbacks vom Ueberwachungs-Thread (laufen NICHT im GUI-Thread!)
    # ------------------------------------------------------------------
    def _on_item_closed(self, name: str, kind: str) -> None:
        """Wird vom Hintergrund-Thread aufgerufen, sobald ein Element geschlossen wurde."""
        # tkinter ist nicht thread-sicher - Updates laufen ueber die UI-Warteschlange.
        self._run_on_ui_thread(lambda: self._set_status(f"Geschlossen: {name}"))

    def _on_monitor_error(self, message: str) -> None:
        """Wird vom Hintergrund-Thread bei einem Fehler aufgerufen."""
        self._run_on_ui_thread(lambda: self._set_status(f"Fehler: {message}"))

    def _refresh_status_loop(self) -> None:
        """Aktualisiert periodisch den Auto-Knopf (z. B. nach Tray/Hotkey-Aktionen)."""
        if self.monitor.is_running and self.auto_button.cget("text") != "DeactivateAuto":
            self.auto_button.configure(text="DeactivateAuto")
        elif not self.monitor.is_running and self.auto_button.cget("text") != "ActivateAuto":
            self.auto_button.configure(text="ActivateAuto")
        self.after(1000, self._refresh_status_loop)

    def _set_status(self, message: str) -> None:
        """Schreibt eine Meldung in die Statuszeile und in die Logdatei."""
        self.status_var.set(message)
        logger.info(message)

    # ------------------------------------------------------------------
    # Fenstersteuerung / Tray
    # ------------------------------------------------------------------
    def _restore_from_tray(self) -> None:
        """Zeigt das Hauptfenster wieder an (laeuft ueber die UI-Warteschlange im GUI-Thread)."""
        self.deiconify()
        self.lift()

    def _on_close_button(self) -> None:
        """Reagiert auf den Schliessen-Button des Fensters (X)."""
        if self.config_manager.get("minimize_to_tray_on_close", True):
            self.withdraw()
            self._set_status("In den Tray minimiert. Über das Tray-Symbol wieder öffnen.")
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        """Beendet die Anwendung vollstaendig und raeumt alle Ressourcen auf."""
        self.monitor.stop()
        self.hotkey_manager.unregister()
        self.tray.stop()
        self.config_manager.save()
        self.destroy()
