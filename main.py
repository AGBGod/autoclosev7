"""
main.py
--------
Einstiegspunkt fuer AutoCloseV8.

Startet das Logging, faengt unerwartete Fehler ab und oeffnet die grafische
Oberflaeche. Nur unter Windows voll lauffaehig (siehe README.md).

Aufruf:
    python main.py
"""

import logging
import sys
import tkinter as tk
from tkinter import messagebox

from src.gui import AutoCloseApp
from src.logger_setup import setup_logging


def main() -> int:
    """Startet die Anwendung und liefert den Exit-Code zurueck."""
    logger = setup_logging(level=logging.INFO)
    logger.info("AutoCloseV8 wird gestartet...")

    if sys.platform != "win32":
        logger.warning(
            "AutoCloseV8 wurde fuer Windows entwickelt. Auf diesem Betriebssystem "
            "funktionieren Fenstererkennung, Tray-Icon, Autostart und Hotkey nicht."
        )

    try:
        app = AutoCloseApp()
        app.mainloop()
        return 0
    except Exception as exc:  # Letztes Sicherheitsnetz - zeigt eine verstaendliche Meldung.
        logger.exception("Unerwarteter Fehler beim Start der Anwendung: %s", exc)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "AutoCloseV8 - Fehler",
                f"Die Anwendung konnte nicht gestartet werden:\n\n{exc}\n\n"
                "Details findest du in logs/autoclosev7.log.",
            )
            root.destroy()
        except Exception:
            print(f"Kritischer Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
