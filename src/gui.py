"""
gui.py
-------
Grafische Benutzeroberflaeche (GUI) von AutoCloseV8 im klassischen Windows-Look
(angelehnt an AutoCloseV4).

Aufbau:
  - Liste "Programme fuer OPEN"  mit [+]/[-] Knoepfen und eigener
    Automatik-Zeile (Auto an/aus, Intervall ms/s/m/h, nach Start, nach Neustart)
  - Liste "Programme fuer CLOSE" mit [+]/[-] Knoepfen und eigener
    Automatik-Zeile (gleiche Optionen, getrennt einstellbar)
  - Knopfleiste unten: Open | Close | ActivateAuto | AutoClose
  - Statuszeile am unteren Rand

Die Knoepfe:
  - Open:         startet das markierte Programm der OPEN-Liste
                  (ohne Markierung: alle Programme der Liste)
  - Close:        schliesst das markierte Ziel der CLOSE-Liste sofort
                  (ohne Markierung: alle Ziele der Liste)
  - ActivateAuto: schaltet BEIDE Automatiken (OPEN + CLOSE) ein/aus
  - AutoClose:    schliesst sofort alle Ziele der CLOSE-Liste (ein Durchlauf)

Die Automatiken:
  - OPEN-Automatik:  prueft im eingestellten Intervall, ob die Programme der
                     OPEN-Liste laufen - fehlende werden automatisch gestartet.
  - CLOSE-Automatik: prueft im eingestellten Intervall, ob Ziele der
                     CLOSE-Liste auftauchen - Treffer werden geschlossen.
  - "nach Start":    Automatik ist sofort aktiv, wenn das Programm geoeffnet wird.
  - "nach Neustart": Programm wird in den Windows-Autostart eingetragen und die
                     Automatik ist nach einem PC-Neustart sofort aktiv.
"""

import logging
import math
import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from .autostart import AutostartManager
from .config_manager import ConfigManager
from .hotkey import HotkeyManager
from .process_list import (
    list_installed_apps,
    list_open_windows,
    list_running_programs,
    resolve_shortcut_target,
)
from .program_opener import ProgramOpener
from .stats import StatsTracker
from .tray import TrayIcon
from .updater import UpdateChecker
from .window_monitor import PLATFORM_SUPPORTED, WindowMonitor

logger = logging.getLogger("AutoCloseV8.GUI")

# Umrechnungsfaktoren der Intervall-Einheiten in Sekunden.
UNIT_FACTORS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}

# Bekannte Windows-Programme, die man ohne Dateisuche hinzufuegen kann.
KNOWN_WINDOWS_PROGRAMS = [
    ("Task-Manager", "taskmgr.exe"),
    ("Editor (Notepad)", "notepad.exe"),
    ("Rechner", "calc.exe"),
    ("Explorer (Dateien)", "explorer.exe"),
    ("Eingabeaufforderung", "cmd.exe"),
    ("Systemsteuerung", "control.exe"),
    ("Einstellungen", "ms-settings:"),
]


class AutoCloseApp(tk.Tk):
    """Hauptfenster der Anwendung im klassischen V4-Stil."""

    def __init__(self):
        super().__init__()

        self.title("AutoCloseV8")
        self.geometry("760x600")
        self.minsize(640, 520)

        # --- UI-Warteschlange ----------------------------------------------
        # tkinter ist nicht thread-sicher. Alle Aktionen, die von fremden
        # Threads ausgeloest werden (Tray-Menue, globaler Hotkey,
        # Automatik-Threads), landen in dieser Warteschlange und werden
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
        self.opener = ProgramOpener(
            config=self.config_manager,
            on_opened=self._on_program_opened,
            on_error=self._on_monitor_error,
        )

        # Tray-Callbacks kommen aus dem Tray-Thread - nur in die Warteschlange
        # legen, niemals direkt Tk-Methoden aufrufen.
        self.tray = TrayIcon(
            on_toggle=lambda: self._run_on_ui_thread(self._toggle_monitoring),
            on_show=lambda: self._run_on_ui_thread(self._restore_from_tray),
            on_quit=lambda: self._run_on_ui_thread(self._quit_app),
            is_running=lambda: self.monitor.is_running or self.opener.is_running,
        )

        self._build_layout()
        self._register_hotkey()

        self.protocol("WM_DELETE_WINDOW", self._on_close_button)

        if not PLATFORM_SUPPORTED:
            self._set_status(
                "Warnung: Windows-Funktionen sind auf diesem System nicht verfuegbar."
            )

        self._activate_on_startup()

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
        """Baut das Fenster auf: zwei Listen mit +/- , Automatik-Zeilen, Knopfleiste."""
        # --- Bereich "Programme fuer OPEN" -----------------------------------
        tk.Label(self, text="Programme für OPEN").pack(pady=(8, 0))

        open_row = tk.Frame(self)
        open_row.pack(fill="both", expand=True, padx=8, pady=(2, 0))

        self.open_listbox = tk.Listbox(open_row, bg="white", activestyle="none")
        self.open_listbox.pack(side="left", fill="both", expand=True)

        open_buttons = tk.Frame(open_row)
        open_buttons.pack(side="right", fill="y", padx=(8, 0))
        tk.Label(open_buttons, text="Apps").pack(pady=(6, 0))
        tk.Button(open_buttons, text="+", width=8, command=self._add_open_app).pack(
            pady=(0, 2)
        )
        tk.Button(open_buttons, text="-", width=8, command=self._remove_open_program).pack()
        tk.Label(open_buttons, text="Task-Manager").pack(pady=(10, 0))
        tk.Button(open_buttons, text="+", width=8, command=self._add_open_program).pack(
            pady=(0, 2)
        )
        tk.Button(open_buttons, text="-", width=8, command=self._remove_open_program).pack()

        # Automatik-Zeile fuer OPEN
        self.open_vars = self._build_auto_row("open_auto", "OPEN-Automatik")

        # --- Bereich "Programme fuer CLOSE" ----------------------------------
        tk.Label(self, text="Programme für CLOSE").pack(pady=(6, 0))

        close_row = tk.Frame(self)
        close_row.pack(fill="both", expand=True, padx=8, pady=(2, 0))

        self.close_listbox = tk.Listbox(close_row, bg="white", activestyle="none")
        self.close_listbox.pack(side="left", fill="both", expand=True)

        close_buttons = tk.Frame(close_row)
        close_buttons.pack(side="right", fill="y", padx=(8, 0))
        tk.Label(close_buttons, text="Apps").pack(pady=(6, 0))
        tk.Button(close_buttons, text="+", width=8, command=self._add_close_app).pack(
            pady=(0, 2)
        )
        tk.Button(close_buttons, text="-", width=8, command=self._remove_close_target).pack()
        tk.Label(close_buttons, text="Task-Manager").pack(pady=(10, 0))
        tk.Button(close_buttons, text="+", width=8, command=self._add_close_target).pack(
            pady=(0, 2)
        )
        tk.Button(close_buttons, text="-", width=8, command=self._remove_close_target).pack()

        # Automatik-Zeile fuer CLOSE
        self.close_vars = self._build_auto_row("close_auto", "CLOSE-Automatik")

        # --- Knopfleiste ------------------------------------------------------
        button_row = tk.Frame(self)
        button_row.pack(pady=8)

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

        # --- Statuszeile ------------------------------------------------------
        self.status_var = tk.StringVar(value="Bereit")
        tk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            fill="x", side="bottom"
        )

        self._reload_lists()

    def _build_auto_row(self, section_key: str, label: str) -> dict:
        """
        Baut eine Automatik-Einstellungszeile fuer eine Sektion (OPEN oder CLOSE)
        und liefert die zugehoerigen Variablen zurueck.
        """
        section = self.config_manager.get_auto_section(section_key)

        row = tk.Frame(self)
        row.pack(padx=8, pady=(2, 4))

        active_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row,
            text="Auto",
            variable=active_var,
            command=lambda: self._toggle_section_auto(section_key),
        ).pack(side="left")

        tk.Label(row, text="prüfen alle:").pack(side="left", padx=(6, 2))

        value_var = tk.StringVar(value=self._format_number(section.get("interval_value", 2.0)))
        entry = tk.Entry(row, textvariable=value_var, width=6)
        entry.pack(side="left", padx=(0, 2))
        entry.bind("<Return>", lambda _e: self._apply_section_interval(section_key))
        entry.bind("<FocusOut>", lambda _e: self._apply_section_interval(section_key))

        unit_var = tk.StringVar(value=section.get("interval_unit", "s"))
        unit_menu = tk.OptionMenu(
            row,
            unit_var,
            "ms",
            "s",
            "m",
            "h",
            command=lambda _v: self._apply_section_interval(section_key),
        )
        unit_menu.configure(width=3)
        unit_menu.pack(side="left", padx=(0, 10))

        after_start_var = tk.BooleanVar(value=bool(section.get("after_start", False)))
        tk.Checkbutton(
            row,
            text="nach Start",
            variable=after_start_var,
            command=lambda: self._apply_section_flags(section_key),
        ).pack(side="left", padx=(0, 8))

        after_restart_var = tk.BooleanVar(value=bool(section.get("after_restart", False)))
        tk.Checkbutton(
            row,
            text="nach Neustart",
            variable=after_restart_var,
            command=lambda: self._apply_section_flags(section_key),
        ).pack(side="left")

        return {
            "label": label,
            "active": active_var,
            "value": value_var,
            "unit": unit_var,
            "after_start": after_start_var,
            "after_restart": after_restart_var,
        }

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
        """
        Oeffnet einen Auswahl-Dialog fuer die OPEN-Liste:
          - bekannte Windows-Programme (z. B. Task-Manager)
          - gerade laufende Programme (wie im Task-Manager)
          - eigene Datei auswaehlen oder Namen/Befehl eintippen
        """
        dialog = tk.Toplevel(self)
        dialog.title("Programm für OPEN hinzufügen")
        dialog.geometry("540x560")
        dialog.transient(self)
        dialog.grab_set()

        def add_value(value: str, shown: str = "") -> None:
            value = (value or "").strip()
            if not value:
                return
            self.config_manager.add_open_program(value)
            self._reload_lists()
            self._set_status(f"Hinzugefügt: {shown or value}")

        # --- Bekannte Windows-Programme --------------------------------
        tk.Label(dialog, text="Windows-Programme (Doppelklick zum Hinzufügen):").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        known_box = tk.Listbox(dialog, bg="white", height=7, activestyle="none")
        for label, command in KNOWN_WINDOWS_PROGRAMS:
            known_box.insert(tk.END, f"{label}   ({command})")
        known_box.pack(fill="x", padx=8)

        def add_known(_event=None):
            selection = known_box.curselection()
            if not selection or selection[0] >= len(KNOWN_WINDOWS_PROGRAMS):
                return
            label, command = KNOWN_WINDOWS_PROGRAMS[selection[0]]
            add_value(command, label)

        known_box.bind("<Double-Button-1>", add_known)

        # --- Gerade laufende Programme ----------------------------------
        tk.Label(dialog, text="Gerade laufende Programme (Doppelklick zum Hinzufügen):").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        running_box = tk.Listbox(dialog, bg="white", activestyle="none")
        running_box.pack(fill="both", expand=True, padx=8)
        running_programs: list = []

        def refresh_running():
            running_programs.clear()
            running_box.delete(0, tk.END)
            for name, exe in list_running_programs():
                running_programs.append((name, exe))
                running_box.insert(tk.END, name)
            if not running_programs:
                running_box.insert(tk.END, "(keine Einträge - nur unter Windows verfügbar)")

        refresh_running()

        def add_running(_event=None):
            selection = running_box.curselection()
            if not selection or selection[0] >= len(running_programs):
                return
            name, exe = running_programs[selection[0]]
            add_value(exe or name, name)

        running_box.bind("<Double-Button-1>", add_running)

        # --- Eigener Name/Befehl ----------------------------------------
        entry_row = tk.Frame(dialog)
        entry_row.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(entry_row, text="Name/Befehl:").pack(side="left")
        manual_var = tk.StringVar()
        manual_entry = tk.Entry(entry_row, textvariable=manual_var)
        manual_entry.pack(side="left", fill="x", expand=True, padx=4)

        def add_manual(_event=None):
            add_value(manual_var.get())
            manual_var.set("")

        manual_entry.bind("<Return>", add_manual)
        tk.Button(entry_row, text="Hinzufügen", command=add_manual).pack(side="left")

        # --- Untere Knopfleiste ------------------------------------------
        button_row = tk.Frame(dialog)
        button_row.pack(pady=8)

        def choose_file():
            path = filedialog.askopenfilename(
                parent=dialog,
                title="Programm auswählen",
                filetypes=[
                    ("Programme", "*.exe"),
                    ("Verknüpfungen", "*.lnk"),
                    ("Alle Dateien", "*.*"),
                ],
            )
            if path:
                add_value(path, os.path.basename(path))

        tk.Button(button_row, text="Datei auswählen…", command=choose_file).pack(
            side="left", padx=4
        )
        tk.Button(button_row, text="Aktualisieren", command=refresh_running).pack(
            side="left", padx=4
        )
        tk.Button(button_row, text="Fertig", command=dialog.destroy).pack(side="left", padx=4)

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

    def _show_app_picker(self, title: str, on_pick) -> None:
        """
        Gemeinsamer Auswahl-Dialog fuer "normale" installierte Apps
        (aus dem Windows-Startmenue), mit Suchfeld.

        `on_pick(name, lnk_path)` wird beim Doppelklick aufgerufen.
        """
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("540x560")
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="Installierte Apps (Doppelklick zum Hinzufügen):").pack(
            anchor="w", padx=8, pady=(8, 0)
        )

        # --- Suchfeld -----------------------------------------------------
        search_row = tk.Frame(dialog)
        search_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(search_row, text="Suchen:").pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_row, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=4)
        search_entry.focus_set()

        # --- Liste der Apps -------------------------------------------------
        apps_box = tk.Listbox(dialog, bg="white", activestyle="none")
        apps_box.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        all_apps: list = []
        shown_apps: list = []

        def apply_filter(*_args):
            term = search_var.get().strip().lower()
            shown_apps.clear()
            apps_box.delete(0, tk.END)
            for name, lnk_path in all_apps:
                if term and term not in name.lower():
                    continue
                shown_apps.append((name, lnk_path))
                apps_box.insert(tk.END, name)
            if not shown_apps:
                apps_box.insert(
                    tk.END,
                    "(keine Einträge - nur unter Windows verfügbar)"
                    if not all_apps
                    else "(keine Treffer)",
                )

        def refresh_apps():
            all_apps.clear()
            all_apps.extend(list_installed_apps())
            apply_filter()

        search_var.trace_add("write", apply_filter)
        refresh_apps()

        def add_selected(_event=None):
            selection = apps_box.curselection()
            if not selection or selection[0] >= len(shown_apps):
                return
            name, lnk_path = shown_apps[selection[0]]
            on_pick(name, lnk_path)

        apps_box.bind("<Double-Button-1>", add_selected)

        # --- Untere Knopfleiste ----------------------------------------------
        button_row = tk.Frame(dialog)
        button_row.pack(pady=8)
        tk.Button(button_row, text="Hinzufügen", command=add_selected).pack(
            side="left", padx=4
        )
        tk.Button(button_row, text="Aktualisieren", command=refresh_apps).pack(
            side="left", padx=4
        )
        tk.Button(button_row, text="Fertig", command=dialog.destroy).pack(side="left", padx=4)

    def _add_open_app(self) -> None:
        """'+'-Knopf (Apps) bei OPEN: installierte App auswaehlen und hinzufuegen."""

        def on_pick(name: str, lnk_path: str) -> None:
            self.config_manager.add_open_program(lnk_path)
            self._reload_lists()
            self._set_status(f"Hinzugefügt: {name}")

        self._show_app_picker("App für OPEN hinzufügen", on_pick)

    def _add_close_app(self) -> None:
        """
        '+'-Knopf (Apps) bei CLOSE: installierte App auswaehlen. Es wird der
        Prozessname der App (z. B. chrome.exe) in die CLOSE-Liste eingetragen;
        falls der nicht ermittelbar ist, der App-Name als Fenstertitel.
        """

        def on_pick(name: str, lnk_path: str) -> None:
            exe_name = resolve_shortcut_target(lnk_path)
            if exe_name:
                self.config_manager.add_process_name(exe_name)
                self._reload_lists()
                self._set_status(f"Hinzugefügt: {name} ({exe_name})")
            else:
                self.config_manager.add_window_title(name)
                self._reload_lists()
                self._set_status(f"Hinzugefügt: {name}")

        self._show_app_picker("App für CLOSE hinzufügen", on_pick)

    def _add_close_target(self) -> None:
        """
        Oeffnet einen Auswahl-Dialog fuer die CLOSE-Liste - wie im Task-Manager:
          - Liste der gerade offenen Fenster (Titel)
          - Liste der gerade laufenden Programme (Prozesse)
          - eigenes Feld fuer Fenstertitel oder Prozessnamen
        """
        dialog = tk.Toplevel(self)
        dialog.title("Programm für CLOSE hinzufügen")
        dialog.geometry("540x560")
        dialog.transient(self)
        dialog.grab_set()

        def added(value: str) -> None:
            self._reload_lists()
            self._set_status(f"Hinzugefügt: {value}")

        # --- Offene Fenster ----------------------------------------------
        tk.Label(dialog, text="Offene Fenster (Doppelklick zum Hinzufügen):").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        windows_box = tk.Listbox(dialog, bg="white", height=9, activestyle="none")
        windows_box.pack(fill="both", expand=True, padx=8)
        window_titles: list = []

        # --- Laufende Programme --------------------------------------------
        tk.Label(dialog, text="Laufende Programme (Doppelklick zum Hinzufügen):").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        process_box = tk.Listbox(dialog, bg="white", height=9, activestyle="none")
        process_box.pack(fill="both", expand=True, padx=8)
        process_names: list = []

        def refresh_lists():
            window_titles.clear()
            windows_box.delete(0, tk.END)
            for title in list_open_windows():
                window_titles.append(title)
                windows_box.insert(tk.END, title)
            if not window_titles:
                windows_box.insert(tk.END, "(keine Einträge - nur unter Windows verfügbar)")

            process_names.clear()
            process_box.delete(0, tk.END)
            for name, _exe in list_running_programs():
                process_names.append(name)
                process_box.insert(tk.END, name)
            if not process_names:
                process_box.insert(tk.END, "(keine Einträge - nur unter Windows verfügbar)")

        refresh_lists()

        def add_window(_event=None):
            selection = windows_box.curselection()
            if not selection or selection[0] >= len(window_titles):
                return
            title = window_titles[selection[0]]
            self.config_manager.add_window_title(title)
            added(title)

        def add_process(_event=None):
            selection = process_box.curselection()
            if not selection or selection[0] >= len(process_names):
                return
            name = process_names[selection[0]]
            self.config_manager.add_process_name(name)
            added(name)

        windows_box.bind("<Double-Button-1>", add_window)
        process_box.bind("<Double-Button-1>", add_process)

        # --- Eigene Eingabe -------------------------------------------------
        entry_row = tk.Frame(dialog)
        entry_row.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(entry_row, text="Titel/Name:").pack(side="left")
        manual_var = tk.StringVar()
        manual_entry = tk.Entry(entry_row, textvariable=manual_var)
        manual_entry.pack(side="left", fill="x", expand=True, padx=4)

        def add_manual(_event=None):
            value = manual_var.get().strip()
            if not value:
                return
            if value.lower().endswith(".exe"):
                self.config_manager.add_process_name(value)
            else:
                self.config_manager.add_window_title(value)
            manual_var.set("")
            added(value)

        manual_entry.bind("<Return>", add_manual)
        tk.Button(entry_row, text="Hinzufügen", command=add_manual).pack(side="left")

        # --- Untere Knopfleiste ----------------------------------------------
        button_row = tk.Frame(dialog)
        button_row.pack(pady=8)
        tk.Button(button_row, text="Aktualisieren", command=refresh_lists).pack(
            side="left", padx=4
        )
        tk.Button(button_row, text="Fertig", command=dialog.destroy).pack(side="left", padx=4)

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
    # Automatik-Einstellungen (getrennt fuer OPEN und CLOSE)
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

    def _section_vars(self, section_key: str) -> dict:
        """Liefert die GUI-Variablen der Sektion ('open_auto' oder 'close_auto')."""
        return self.open_vars if section_key == "open_auto" else self.close_vars

    def _section_automation(self, section_key: str):
        """Liefert die Automatik der Sektion (Opener bzw. Monitor)."""
        return self.opener if section_key == "open_auto" else self.monitor

    def _apply_section_interval(self, section_key: str) -> None:
        """Liest Wert + Einheit einer Sektion, rechnet in Sekunden um und speichert."""
        vars_ = self._section_vars(section_key)
        raw = vars_["value"].get().strip().replace(",", ".")
        unit = vars_["unit"].get()
        try:
            value = float(raw)
        except ValueError:
            self._set_status("Ungültige Zahl beim Intervall - bitte z. B. 2 oder 0,5 eingeben.")
            return
        if not math.isfinite(value) or value <= 0:
            self._set_status("Das Intervall muss größer als 0 sein.")
            return

        seconds = value * UNIT_FACTORS.get(unit, 1.0)
        clamped = False
        if seconds < 0.2:
            seconds = 0.2
            clamped = True

        self.config_manager.set_auto_section(
            section_key,
            interval_value=value,
            interval_unit=unit,
            interval_seconds=seconds,
        )
        # Rueckwaerts-Kompatibilitaet: der CLOSE-Monitor liest weiterhin den
        # alten Schluessel check_interval_seconds.
        if section_key == "close_auto":
            self.config_manager.set("check_interval_seconds", seconds)

        # Laeuft die Automatik gerade, kurz neu starten, damit das neue
        # Intervall sofort gilt (sonst wuerde erst der alte Wartezyklus enden).
        automation = self._section_automation(section_key)
        if automation.is_running:
            automation.stop()
            automation.start()

        pretty = f"{self._format_number(value)} {unit}"
        name = vars_["label"]
        if clamped:
            self._set_status(
                f"{name}: Intervall {pretty} gespeichert (Minimum ist 200 ms - es gilt 200 ms)."
            )
        else:
            self._set_status(f"{name}: prüft jetzt alle {pretty}.")

    def _apply_section_flags(self, section_key: str) -> None:
        """Speichert 'nach Start' / 'nach Neustart' einer Sektion und pflegt den Autostart."""
        vars_ = self._section_vars(section_key)
        after_start = bool(vars_["after_start"].get())
        after_restart = bool(vars_["after_restart"].get())
        self.config_manager.set_auto_section(
            section_key, after_start=after_start, after_restart=after_restart
        )

        # Windows-Autostart aktivieren, sobald mindestens eine Sektion
        # "nach Neustart" verlangt - sonst deaktivieren. Der Registry-Eintrag
        # wird bewusst IMMER neu geschrieben (idempotent), damit auch aeltere
        # Eintraege ohne --autostart-Parameter aktualisiert werden.
        open_restart = bool(self.open_vars["after_restart"].get())
        close_restart = bool(self.close_vars["after_restart"].get())
        want_autostart = open_restart or close_restart
        ok = self.autostart_manager.set_enabled(want_autostart)
        if ok:
            self.config_manager.set("autostart_enabled", want_autostart)
        elif want_autostart:
            self._set_status(
                "Hinweis: Autostart konnte nicht eingetragen werden (nur unter Windows möglich). "
                "Die Einstellung wurde trotzdem gespeichert."
            )
            return

        name = vars_["label"]
        parts = []
        if after_start:
            parts.append("nach Programmstart")
        if after_restart:
            parts.append("nach PC-Neustart")
        if parts:
            self._set_status(f"{name}: startet automatisch {' und '.join(parts)}.")
        else:
            self._set_status(f"{name}: startet nicht mehr automatisch.")

    def _toggle_section_auto(self, section_key: str) -> None:
        """Schaltet die Automatik einer einzelnen Sektion ein/aus (Checkbox 'Auto')."""
        vars_ = self._section_vars(section_key)
        automation = self._section_automation(section_key)
        if vars_["active"].get():
            automation.start()
            self._set_status(f"{vars_['label']} aktiviert.")
        else:
            automation.stop()
            self._set_status(f"{vars_['label']} gestoppt.")
        self._sync_auto_states()
        self.tray.refresh_icon()

    def _toggle_monitoring(self, force_start: bool = False) -> None:
        """
        Master-Schalter (ActivateAuto-Knopf, Tray, Hotkey): schaltet BEIDE
        Automatiken gemeinsam ein oder aus.
        """
        any_running = self.monitor.is_running or self.opener.is_running
        if force_start or not any_running:
            self.opener.start()
            self.monitor.start()
            self._set_status("Automatik aktiv - OPEN und CLOSE laufen im Hintergrund.")
        else:
            self.opener.stop()
            self.monitor.stop()
            self._set_status("Automatik gestoppt.")
        self._sync_auto_states()
        self.tray.refresh_icon()

    def _sync_auto_states(self) -> None:
        """Gleicht Knopf-Text und Auto-Checkboxen mit dem echten Zustand ab."""
        any_running = self.monitor.is_running or self.opener.is_running
        wanted_text = "DeactivateAuto" if any_running else "ActivateAuto"
        if self.auto_button.cget("text") != wanted_text:
            self.auto_button.configure(text=wanted_text)
        if bool(self.open_vars["active"].get()) != self.opener.is_running:
            self.open_vars["active"].set(self.opener.is_running)
        if bool(self.close_vars["active"].get()) != self.monitor.is_running:
            self.close_vars["active"].set(self.monitor.is_running)

    def _activate_on_startup(self) -> None:
        """
        Aktiviert Automatiken beim Programmstart:
          - Start durch Windows-Autostart (--autostart): Sektionen mit 'nach Neustart'
          - normaler Start: Sektionen mit 'nach Start'
        """
        launched_by_windows = "--autostart" in sys.argv
        flag = "after_restart" if launched_by_windows else "after_start"

        # Bestehenden Autostart-Eintrag beim Start auffrischen, damit er den
        # aktuellen Pfad und den --autostart-Parameter enthaelt (aeltere
        # Versionen haben den Eintrag ohne diesen Parameter geschrieben).
        if self.config_manager.get("autostart_enabled", False):
            self.autostart_manager.enable()

        open_section = self.config_manager.get_auto_section("open_auto")
        close_section = self.config_manager.get_auto_section("close_auto")

        started = []
        if open_section.get(flag):
            self.opener.start()
            started.append("OPEN")
        if close_section.get(flag):
            self.monitor.start()
            started.append("CLOSE")

        if started:
            reason = "PC-Neustart" if launched_by_windows else "Programmstart"
            self._set_status(f"Automatik nach {reason} aktiv: {' + '.join(started)}")
        self._sync_auto_states()

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
    # Callbacks der Automatik-Threads (laufen NICHT im GUI-Thread!)
    # ------------------------------------------------------------------
    def _on_item_closed(self, name: str, kind: str) -> None:
        """Wird vom CLOSE-Thread aufgerufen, sobald ein Element geschlossen wurde."""
        # tkinter ist nicht thread-sicher - Updates laufen ueber die UI-Warteschlange.
        self._run_on_ui_thread(lambda: self._set_status(f"Geschlossen: {name}"))

    def _on_program_opened(self, program: str) -> None:
        """Wird vom OPEN-Thread aufgerufen, sobald ein Programm gestartet wurde."""
        base = os.path.basename(program)
        self._run_on_ui_thread(lambda: self._set_status(f"Automatisch gestartet: {base}"))

    def _on_monitor_error(self, message: str) -> None:
        """Wird von den Automatik-Threads bei einem Fehler aufgerufen."""
        self._run_on_ui_thread(lambda: self._set_status(f"Fehler: {message}"))

    def _refresh_status_loop(self) -> None:
        """Gleicht periodisch die Anzeige mit dem echten Zustand ab (Tray/Hotkey)."""
        self._sync_auto_states()
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
        self.opener.stop()
        self.hotkey_manager.unregister()
        self.tray.stop()
        self.config_manager.save()
        self.destroy()
