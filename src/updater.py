"""
updater.py
-----------
Vorbereitung fuer automatische Updates.

WICHTIG: Dies ist aktuell nur ein Platzhalter/Stub. Es gibt noch keinen echten
Update-Server. Die Struktur ist aber bereits so aufgebaut, dass spaeter einfach
eine echte URL/API angebunden werden kann (siehe TODO unten).
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("AutoCloseV9.0.Updater")

CURRENT_VERSION = "1.0.0"

# TODO: Durch eine echte URL ersetzen, sobald ein Update-Server existiert,
#       z. B. "https://example.com/autoclosev7/latest_version.json"
UPDATE_CHECK_URL: Optional[str] = None


@dataclass
class UpdateInfo:
    """Ergebnis einer Update-Pruefung."""

    current_version: str
    latest_version: str
    update_available: bool
    notes: str = ""


class UpdateChecker:
    """
    Stub-Implementierung der Update-Pruefung.

    Sobald `UPDATE_CHECK_URL` gesetzt ist, kann `check_for_update()` so
    erweitert werden, dass sie per `requests.get(UPDATE_CHECK_URL)` die
    neueste Version abruft und mit `CURRENT_VERSION` vergleicht.
    """

    def check_for_update(self) -> UpdateInfo:
        """Prueft (aktuell simuliert), ob eine neuere Version verfuegbar ist."""
        if not UPDATE_CHECK_URL:
            logger.debug("Kein Update-Server konfiguriert - Update-Pruefung uebersprungen.")
            return UpdateInfo(
                current_version=CURRENT_VERSION,
                latest_version=CURRENT_VERSION,
                update_available=False,
                notes="Automatische Updates sind noch nicht aktiv (kein Server konfiguriert).",
            )

        # Platzhalter fuer die zukuenftige echte Implementierung, z. B.:
        #
        # import requests
        # response = requests.get(UPDATE_CHECK_URL, timeout=5)
        # response.raise_for_status()
        # data = response.json()
        # latest = data["version"]
        # return UpdateInfo(
        #     current_version=CURRENT_VERSION,
        #     latest_version=latest,
        #     update_available=latest != CURRENT_VERSION,
        #     notes=data.get("notes", ""),
        # )
        logger.info("Update-Pruefung ist vorbereitet, aber noch nicht mit einem Server verbunden.")
        return UpdateInfo(
            current_version=CURRENT_VERSION,
            latest_version=CURRENT_VERSION,
            update_available=False,
            notes="Update-Funktion vorbereitet, noch nicht aktiv.",
        )
