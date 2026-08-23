"""Bildschirmfotos und Bildschirm-Geometrie.

Bevorzugt wird der direkte Weg ueber Quartz (PyObjC), weil er schnell genug
ist, um waehrend der Aufnahme mehrmals pro Sekunde ein Foto zu ziehen. Ohne
PyObjC wird auf das Systemwerkzeug ``screencapture`` ausgewichen.

Koordinaten: macOS beschreibt Mausposition und Fenster in *Punkten* mit
Ursprung links oben ueber alle Bildschirme hinweg. Bildschirmfotos liegen
dagegen in *Pixeln* vor (auf Retina-Displays doppelt so fein). ``Frame``
kennt beide Welten und rechnet um.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import imaging


@dataclass
class Display:
    display_id: int
    origin: Tuple[float, float]
    size: Tuple[float, float]
    scale: float = 1.0
    main: bool = False

    def contains(self, point: Tuple[float, float]) -> bool:
        x, y = point
        return (
            self.origin[0] <= x < self.origin[0] + self.size[0]
            and self.origin[1] <= y < self.origin[1] + self.size[1]
        )


@dataclass
class Frame:
    """Ein Bildschirmfoto samt Lage- und Massstabsinformation."""

    image: np.ndarray
    origin: Tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0
    display_id: int = 0
    timestamp: float = field(default_factory=time.time)
    _gray: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    @property
    def gray(self) -> np.ndarray:
        if self._gray is None:
            self._gray = imaging.to_gray(self.image)
        return self._gray

    def point_to_pixel(self, point: Tuple[float, float]) -> Tuple[float, float]:
        return (
            (point[0] - self.origin[0]) * self.scale,
            (point[1] - self.origin[1]) * self.scale,
        )

    def pixel_to_point(self, pixel: Tuple[float, float]) -> Tuple[float, float]:
        return (
            self.origin[0] + pixel[0] / self.scale,
            self.origin[1] + pixel[1] / self.scale,
        )

    def contains_point(self, point: Tuple[float, float]) -> bool:
        x, y = self.point_to_pixel(point)
        return 0 <= x < self.image.shape[1] and 0 <= y < self.image.shape[0]


class ScreenSource:
    """Schnittstelle fuer Bildschirmfotos (fuer Tests austauschbar)."""

    def displays(self) -> List[Display]:  # pragma: no cover - Schnittstelle
        raise NotImplementedError

    def capture(self, display: Optional[Display] = None) -> Frame:  # pragma: no cover
        raise NotImplementedError

    def display_at(self, point: Tuple[float, float]) -> Display:
        available = self.displays()
        for display in available:
            if display.contains(point):
                return display
        for display in available:
            if display.main:
                return display
        return available[0]

    def display_by_id(self, display_id: int) -> Optional[Display]:
        for display in self.displays():
            if display.display_id == display_id:
                return display
        return None


class QuartzScreen(ScreenSource):
    """Bildschirmfotos ueber CoreGraphics (schnell, ohne Zwischendatei)."""

    def __init__(self):
        import Quartz  # noqa: F401  (Importfehler = Backend nicht verfuegbar)

        self._quartz = Quartz
        self._cache: List[Display] = []
        self._cache_time = 0.0

    def displays(self) -> List[Display]:
        if self._cache and time.time() - self._cache_time < 5.0:
            return self._cache
        quartz = self._quartz
        error, ids, _count = quartz.CGGetActiveDisplayList(16, None, None)
        if error:
            raise RuntimeError(f"Bildschirme konnten nicht ermittelt werden (Fehler {error}).")
        main_id = quartz.CGMainDisplayID()
        found: List[Display] = []
        for display_id in ids:
            bounds = quartz.CGDisplayBounds(display_id)
            width = float(bounds.size.width)
            height = float(bounds.size.height)
            scale = 1.0
            try:
                mode = quartz.CGDisplayCopyDisplayMode(display_id)
                if mode is not None and width:
                    scale = float(quartz.CGDisplayModeGetPixelWidth(mode)) / width
            except Exception:  # pragma: no cover - aeltere Systeme
                scale = 1.0
            found.append(
                Display(
                    display_id=int(display_id),
                    origin=(float(bounds.origin.x), float(bounds.origin.y)),
                    size=(width, height),
                    scale=scale if scale > 0 else 1.0,
                    main=int(display_id) == int(main_id),
                )
            )
        self._cache = found
        self._cache_time = time.time()
        return found

    def capture(self, display: Optional[Display] = None) -> Frame:
        quartz = self._quartz
        target = display or self.display_at(_mouse_point_fallback())
        image_ref = quartz.CGDisplayCreateImage(target.display_id)
        if image_ref is None:
            raise PermissionError(
                "Kein Bildschirmfoto moeglich. Bitte in den Systemeinstellungen unter "
                "'Datenschutz & Sicherheit > Bildschirmaufnahme' die Freigabe erteilen."
            )
        array = _cgimage_to_array(quartz, image_ref)
        scale = array.shape[1] / target.size[0] if target.size[0] else target.scale
        return Frame(
            image=array,
            origin=target.origin,
            scale=scale or 1.0,
            display_id=target.display_id,
            timestamp=time.time(),
        )


def _cgimage_to_array(quartz, image_ref) -> np.ndarray:
    width = int(quartz.CGImageGetWidth(image_ref))
    height = int(quartz.CGImageGetHeight(image_ref))
    bytes_per_row = int(quartz.CGImageGetBytesPerRow(image_ref))
    provider = quartz.CGImageGetDataProvider(image_ref)
    data = quartz.CGDataProviderCopyData(provider)
    raw = np.frombuffer(data, dtype=np.uint8)
    raw = raw[: height * bytes_per_row].reshape(height, bytes_per_row // 4, 4)
    # CoreGraphics liefert BGRA (little endian) - in RGB umsortieren.
    return np.ascontiguousarray(raw[:, :width, [2, 1, 0]])


class ScreencaptureScreen(ScreenSource):
    """Rueckfallebene ohne PyObjC: Systemwerkzeug /usr/sbin/screencapture."""

    def __init__(self):
        if not os.path.exists("/usr/sbin/screencapture"):
            raise RuntimeError("screencapture nicht gefunden - kein macOS?")
        self._displays: List[Display] = []

    def displays(self) -> List[Display]:
        if self._displays:
            return self._displays
        frame = self._grab(1)
        # Ohne Quartz ist die Punktgroesse unbekannt; Retina wird angenommen,
        # wenn das Foto breiter als 1920 Pixel ist.
        scale = 2.0 if frame.shape[1] > 1920 else 1.0
        self._displays = [
            Display(
                display_id=1,
                origin=(0.0, 0.0),
                size=(frame.shape[1] / scale, frame.shape[0] / scale),
                scale=scale,
                main=True,
            )
        ]
        return self._displays

    def _grab(self, index: int) -> np.ndarray:
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            result = subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-o", f"-D{index}", "-t", "png", path],
                capture_output=True,
            )
            if result.returncode != 0 or os.path.getsize(path) == 0:
                raise PermissionError(
                    "Kein Bildschirmfoto moeglich. Bitte in den Systemeinstellungen unter "
                    "'Datenschutz & Sicherheit > Bildschirmaufnahme' die Freigabe erteilen."
                )
            return imaging.load_image(path)
        finally:
            os.unlink(path)

    def capture(self, display: Optional[Display] = None) -> Frame:
        target = display or self.displays()[0]
        array = self._grab(1)
        scale = array.shape[1] / target.size[0] if target.size[0] else target.scale
        return Frame(array, target.origin, scale or 1.0, target.display_id, time.time())


def _mouse_point_fallback() -> Tuple[float, float]:
    try:
        from .inputs import get_input_backend

        return get_input_backend().mouse_position()
    except Exception:
        return (0.0, 0.0)


def get_screen() -> ScreenSource:
    """Liefert das beste verfuegbare Backend fuer Bildschirmfotos."""
    try:
        return QuartzScreen()
    except Exception:
        return ScreencaptureScreen()


class ScreenBuffer:
    """Haelt im Hintergrund das letzte Bildschirmfoto je Bildschirm bereit.

    Waehrend der Aufnahme wird laufend fotografiert. Beim Klick wird dann das
    Foto *vor* dem Klick verwendet - sonst waere der Dialog auf dem Bild
    schon wieder geschlossen und die Schablone wertlos.
    """

    def __init__(self, screen: ScreenSource, fps: float = 6.0, locator=None):
        self.screen = screen
        self.interval = 1.0 / max(0.5, float(fps))
        self._frames: Dict[int, Frame] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._locator = locator or _mouse_point_fallback

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="klickpilot-screenbuffer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while self._running.is_set():
            started = time.time()
            try:
                display = self.screen.display_at(self._locator())
                frame = self.screen.capture(display)
                with self._lock:
                    self._frames[frame.display_id] = frame
            except Exception:
                time.sleep(0.5)
            remaining = self.interval - (time.time() - started)
            if remaining > 0:
                time.sleep(remaining)

    def latest(self, point: Optional[Tuple[float, float]] = None, max_age: float = 1.5) -> Optional[Frame]:
        """Juengstes Foto, das den Punkt enthaelt und nicht zu alt ist."""
        with self._lock:
            frames = list(self._frames.values())
        frames.sort(key=lambda frame: frame.timestamp, reverse=True)
        now = time.time()
        for frame in frames:
            if now - frame.timestamp > max_age:
                continue
            if point is None or frame.contains_point(point):
                return frame
        return None

    def capture_now(self, point: Optional[Tuple[float, float]] = None) -> Frame:
        display = self.screen.display_at(point) if point else None
        frame = self.screen.capture(display)
        with self._lock:
            self._frames[frame.display_id] = frame
        return frame

    def frame_for(self, point: Tuple[float, float], max_age: float = 1.5,
                  not_before: Optional[float] = None) -> Frame:
        """Foto zum Klickzeitpunkt - aus dem Puffer, sonst frisch geknipst.

        ``not_before`` verhindert, dass ein Foto verwendet wird, das aelter
        ist als die vorige Aktion: sonst zeigte die Schablone noch den
        Zustand *vor* dem gerade erst geoeffneten Dialog.
        """
        frame = self.latest(point, max_age=max_age)
        if frame is not None and (not_before is None or frame.timestamp >= not_before):
            return frame
        return self.capture_now(point)
