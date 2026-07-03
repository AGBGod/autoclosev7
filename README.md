# AutoCloseV7

Ein Windows-Programm, das automatisch bestimmte Pop-up-Fenster oder Anwendungen
erkennt und schliesst. Mit modernem Dark-Mode-Interface, Tray-Icon, Autostart,
globalem Hotkey und einfacher Statistik.

> **Wichtig:** AutoCloseV7 nutzt Windows-spezifische Funktionen (Fenster-API,
> Registry, Tray-Icon) und funktioniert daher **nur unter Windows** (10/11).

## Funktionsumfang

- Automatische Erkennung und Schliessung von Fenstern anhand des Fenstertitels
  oder Prozessnamens
- Modernes Dark-Mode-GUI mit Start/Stop-Button
- Verwaltbare Liste der Zielprogramme/-fenster (Hinzufuegen/Entfernen)
- Einstellbares Pruefintervall (CPU-/RAM-schonend, kein Dauer-Polling)
- Automatisches Speichern aller Einstellungen in `config.json`
- Logging in eine rotierende Logdatei (`logs/autoclosev7.log`)
- Verstaendliche Fehlermeldungen statt Abstuerzen
- System-Tray-Icon (Minimieren statt Beenden, Schnellzugriff auf Start/Stop)
- Autostart mit Windows (optional, ueber die Registry des aktuellen Benutzers)
- Globaler Hotkey zum Ein-/Ausschalten der Ueberwachung
- Statistik ueber automatisch geschlossene Fenster (Sitzung)
- Vorbereitete (aber noch nicht aktive) Update-Pruefung fuer zukuenftige Versionen

## Schnellstart: Einfach die .exe starten (empfohlen)

**Es ist keine Python-Installation noetig.** Einfach die Datei
`AutoCloseV7.exe` per Doppelklick starten - fertig.

- Die .exe ist eigenstaendig und kann beliebig kopiert werden (Desktop,
  USB-Stick, anderer Rechner mit Windows 10/11).
- Einstellungen und Logs werden automatisch unter
  `%APPDATA%\AutoCloseV7` gespeichert (z. B.
  `C:\Users\<Name>\AppData\Roaming\AutoCloseV7`), damit sie unabhaengig vom
  Speicherort der .exe erhalten bleiben.
- Beim ersten Start meldet sich ggf. der Windows SmartScreen-Filter
  ("Unbekannter Herausgeber"). In dem Fall auf **"Weitere Informationen" →
  "Trotzdem ausfuehren"** klicken.

Falls noch keine `AutoCloseV7.exe` vorliegt, siehe Abschnitt
[".exe selbst bauen"](#exe-selbst-bauen-fuer-entwickler) weiter unten.

## Installation aus dem Quellcode (nur fuer Entwickler)

1. **Python installieren** (empfohlen: Python 3.11 oder neuer) von
   [python.org](https://www.python.org/downloads/windows/). Bei der Installation
   die Option "Add Python to PATH" aktivieren.

2. **Projekt herunterladen** und in einen beliebigen Ordner entpacken, z. B.
   `C:\Tools\AutoCloseV7`.

3. **Abhaengigkeiten installieren** – in diesem Ordner ein Terminal (PowerShell
   oder CMD) oeffnen und ausfuehren:

   ```
   pip install -r requirements.txt
   ```

## Nutzung

1. Anwendung starten:

   - **Als .exe:** Doppelklick auf `AutoCloseV7.exe`.
   - **Aus dem Quellcode:**

     ```
     python main.py
     ```

2. Im Hauptfenster:
   - Ueber das Eingabefeld unten kannst du **Fenstertitel** (Teilstring genuegt,
     z. B. "Update Available") oder **Prozessnamen** (z. B. `notepad.exe`) zur
     Liste hinzufuegen.
   - Mit **Start** beginnt die Ueberwachung im Hintergrund; mit **Stop** wird sie
     angehalten.
   - Das **Pruefintervall** (in Sekunden) bestimmt, wie oft nach passenden
     Fenstern gesucht wird. Kleinere Werte reagieren schneller, groessere Werte
     schonen CPU/RAM.
   - Ueber die Checkbox **"Mit Windows starten"** wird AutoCloseV7 automatisch
     beim Windows-Start mitgestartet.
   - Der Standard-Hotkey `Strg + Alt + P` schaltet die Ueberwachung jederzeit
     ein oder aus, auch wenn das Fenster nicht im Vordergrund ist (Hotkey in
     `config.json` unter `hotkey` anpassbar).
   - Beim Klick auf das Schliessen-Symbol (X) wird die Anwendung standardmaessig
     in den System-Tray minimiert, nicht beendet. Ueber das Tray-Symbol
     (Rechtsklick) kann sie wieder angezeigt oder vollstaendig beendet werden.

3. Alle Einstellungen werden automatisch in `config.json` gespeichert und beim
   naechsten Start wieder geladen.

## .exe selbst bauen (fuer Entwickler)

Die eigenstaendige `AutoCloseV7.exe` wird mit [PyInstaller](https://pyinstaller.org)
erstellt. Der Build muss **auf einem Windows-Rechner** ausgefuehrt werden
(PyInstaller kann keine Windows-.exe unter Linux/macOS erzeugen).

**Variante 1 - ein Doppelklick (empfohlen):**

1. Python 3.11+ installieren (nur auf dem Build-Rechner noetig).
2. Doppelklick auf `build.bat`.

Das Skript installiert automatisch alle Abhaengigkeiten inkl. PyInstaller und
erstellt die fertige Datei unter **`dist\AutoCloseV7.exe`**.

**Variante 2 - manuell im Terminal:**

```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean AutoCloseV7.spec
```

Die Datei `AutoCloseV7.spec` enthaelt die komplette Build-Konfiguration
(einzelne Datei, kein Konsolenfenster, alle benoetigten Module wie
`pystray`, `keyboard` und die Windows-API-Module).

Hinweise:

- Die fertige `dist\AutoCloseV7.exe` ist die **einzige Datei**, die
  weitergegeben werden muss. Sie laeuft ohne Python auf jedem
  Windows-10/11-Rechner (Tray-Icon, Autostart, Hotkey und
  Konfigurationsspeicherung funktionieren wie gewohnt).
- Als .exe speichert die Anwendung `config.json` und `logs\` unter
  `%APPDATA%\AutoCloseV7` (beim Start aus dem Quellcode wie bisher im
  Projektordner). So funktioniert auch der Windows-Autostart zuverlaessig,
  egal von wo die .exe gestartet wird.
- Der Autostart-Eintrag in der Registry zeigt automatisch auf die .exe
  selbst - kein Python-Aufruf noetig.

## Konfigurationsdatei (`config.json`)

```json
{
    "targets": {
        "window_titles": ["Update Available"],
        "process_names": ["notepad.exe"]
    },
    "check_interval_seconds": 2.0,
    "autostart_enabled": false,
    "hotkey": "ctrl+alt+p",
    "monitoring_enabled_on_start": false,
    "close_method": "graceful",
    "minimize_to_tray_on_close": true
}
```

- `close_method`: `"graceful"` sendet ein Schliessen-Signal an das Fenster
  (WM_CLOSE); alternativ `"force"`, um den zugehoerigen Prozess sofort zu
  beenden.
- `monitoring_enabled_on_start`: Wenn `true`, startet die Ueberwachung
  automatisch beim Programmstart.

Die Datei kann auch direkt bearbeitet werden, solange die Anwendung
geschlossen ist.

## Projektstruktur

```
autoclosev7/
├── main.py                 # Einstiegspunkt
├── config.json              # Standardkonfiguration
├── requirements.txt          # Python-Abhaengigkeiten
├── AutoCloseV7.spec           # PyInstaller-Build-Konfiguration (.exe)
├── build.bat                  # Ein-Klick-Build der AutoCloseV7.exe (Windows)
├── dist/                      # Wird beim Build erstellt (enthaelt AutoCloseV7.exe)
├── logs/                     # Wird automatisch erstellt (Logdateien)
└── src/
    ├── paths.py               # Zentrale Pfad-Logik (Skript vs. gepackte .exe)
    ├── config_manager.py     # Laden/Speichern von config.json
    ├── logger_setup.py       # Zentrale Logging-Konfiguration
    ├── window_monitor.py     # Fenster-/Prozesserkennung und -schliessung
    ├── stats.py               # Sitzungsstatistik
    ├── autostart.py           # Windows-Autostart (Registry)
    ├── hotkey.py               # Globaler Hotkey
    ├── tray.py                 # System-Tray-Icon
    ├── updater.py              # Vorbereitete Update-Pruefung (Stub)
    └── gui.py                  # Dark-Mode-Benutzeroberflaeche (tkinter)
```

## Fehlerbehebung

- **"pywin32/psutil nicht verfuegbar"**: `pip install -r requirements.txt`
  erneut ausfuehren; stellt sicher, dass alle Pakete unter Windows installiert
  wurden.
- **Hotkey funktioniert nicht**: Manche Programme (z. B. Spiele im
  Vollbildmodus) blockieren globale Hotkeys. Die Bibliothek `keyboard`
  benoetigt unter Umstaenden erhoehte Rechte – Terminal ggf. als
  Administrator starten.
- **Autostart laesst sich nicht aktivieren**: Pruefen, ob dein Windows-Konto
  Schreibrechte auf `HKEY_CURRENT_USER` hat (Standard bei normalen
  Benutzerkonten).
- **Die .exe startet nicht / SmartScreen blockiert**: Beim ersten Start auf
  "Weitere Informationen" → "Trotzdem ausfuehren" klicken. Manche
  Virenscanner pruefen unbekannte .exe-Dateien kurz - einen Moment warten
  oder eine Ausnahme hinzufuegen.
- Detaillierte Fehlermeldungen finden sich immer in der Logdatei
  `autoclosev7.log`:
  - **Als .exe:** `%APPDATA%\AutoCloseV7\logs\autoclosev7.log`
  - **Aus dem Quellcode:** `logs/autoclosev7.log` im Projektordner

## Geplante Erweiterungen (vorbereitet, noch nicht aktiv)

- **Automatische Updates**: `src/updater.py` enthaelt bereits das Geruest fuer
  eine Versionspruefung gegen einen zukuenftigen Update-Server (`UPDATE_CHECK_URL`
  in dieser Datei setzen, sobald ein Server existiert).

## Lizenz

Frei nutz- und anpassbar fuer den privaten und internen Gebrauch.
