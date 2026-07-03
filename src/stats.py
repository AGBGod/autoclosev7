"""
stats.py
--------
Erfasst einfache Laufzeit-Statistiken ueber automatisch geschlossene Fenster/Programme.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class ClosedItem:
    """Repraesentiert ein einzelnes geschlossenes Fenster/Programm."""

    name: str
    kind: str  # "window" oder "process"
    timestamp: datetime = field(default_factory=datetime.now)


class StatsTracker:
    """
    Thread-sichere Sammlung von Statistiken fuer die aktuelle Sitzung.
    Wird von der GUI ausgelesen, um dem Benutzer eine Uebersicht zu zeigen.
    """

    def __init__(self, history_limit: int = 200):
        self._lock = threading.Lock()
        self._history_limit = history_limit
        self._history: List[ClosedItem] = []
        self.session_start = datetime.now()

    def record_closed(self, name: str, kind: str = "window") -> None:
        """Vermerkt, dass ein Fenster/Prozess geschlossen wurde."""
        with self._lock:
            self._history.append(ClosedItem(name=name, kind=kind))
            if len(self._history) > self._history_limit:
                self._history.pop(0)

    @property
    def total_closed(self) -> int:
        """Gesamtzahl der in dieser Sitzung geschlossenen Elemente."""
        with self._lock:
            return len(self._history)

    @property
    def last_closed(self) -> Optional[ClosedItem]:
        """Das zuletzt geschlossene Element, falls vorhanden."""
        with self._lock:
            return self._history[-1] if self._history else None

    def recent(self, count: int = 10) -> List[ClosedItem]:
        """Gibt die letzten `count` geschlossenen Elemente zurueck."""
        with self._lock:
            return list(self._history[-count:])

    def reset(self) -> None:
        """Setzt die Statistik der aktuellen Sitzung zurueck."""
        with self._lock:
            self._history.clear()
            self.session_start = datetime.now()
