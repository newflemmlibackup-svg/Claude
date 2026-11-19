"""Tests für den Notfall-Viewer: Volumen laden, Schnittebenen, Panorama, 3D und Oberfläche."""
import os
import sys
import time

import numpy as np
import pytest

from dvt_importer.scanner import scan_source
from dvt_importer.viewer import AX, COR, SAG, VolumeData, angle_deg, distance_mm
from tests.test_pipeline import SIZE, _pixels, make_export


@pytest.fixture
def volume(tmp_path):
    make_export(tmp_path / "usb", [i for i in range(1, 13) if i != 5])   # Schicht 5 fehlt
    series = scan_source(tmp_path / "usb").series[0]
    return series, VolumeData.load(series)


def test_load_volume_fills_missing_slice(volume):
    _series, data = volume
    assert data.shape == (12, SIZE, SIZE)
    assert data.missing == {4}
    assert np.array_equal(data.vol[0], _pixels(1))
    assert np.array_equal(data.vol[11], _pixels(12))
    assert (data.vol[4] == data.vol.min()).all()
    assert data.spacing == pytest.approx((0.25, 0.25, 0.25))


def test_planes_orientation(volume):
    _series, data = volume
    img, sp = data.plane(AX, 3)
    assert img.shape == (SIZE, SIZE) and sp == pytest.approx((0.25, 0.25))
    cor, _ = data.plane(COR, 16)
    sag, _ = data.plane(SAG, 16)
    assert cor.shape == (12, SIZE) and sag.shape == (12, SIZE)
    assert cor[0, 16] == data.vol[11, 16, 16]      # oberste Zeile = kranialste Schicht
    slab, _ = data.plane(AX, 6, slab_mm=0.5)         # 3 Schichten gemittelt
    assert slab[16, 16] == pytest.approx(data.vol[5:8, 16, 16].mean())


def test_reversed_slice_order_is_normalised(tmp_path):
    make_export(tmp_path / "usb", range(1, 9), z_step=-0.25)       # erste Schicht liegt oben
    data = VolumeData.load(scan_source(tmp_path / "usb").series[0])
    assert data.vol[0, 16, 16] < data.vol[-1, 16, 16] or np.array_equal(data.vol[0], _pixels(8))


def test_panorama_and_3d(volume):
    _series, data = volume
    pts = [(4, 20), (16, 28), (28, 20)]
    img, (ry, rx), base = data.panorama(pts, 0.0, 2.0)
    assert img.shape[0] == 12 and img.shape[1] == len(base) > 10
    for mode in ("surface", "mip"):
        rgb = data.render3d(0.3, 0.2, 64, mode, (data.lo + data.hi) / 2)
        assert rgb.shape == (64, 64, 3) and rgb.max() > 30


def test_measure_helpers():
    assert distance_mm((0, 0), (3, 4)) == pytest.approx(5)
    assert angle_deg((1, 0), (0, 0), (0, 1)) == pytest.approx(90)


tk = pytest.importorskip("tkinter")


@pytest.mark.skipif(sys.platform.startswith("linux") and not os.environ.get("DISPLAY"), reason="Kein Display")
def test_viewer_window_interaction(volume):
    series, _ = volume
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk kann kein Fenster öffnen")
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    from dvt_importer.viewer import ViewerWindow

    v = ViewerWindow(root, series=series)
    try:
        end = time.time() + 20
        while v.data is None and time.time() < end:
            root.update()
            time.sleep(0.02)
        assert v.data is not None
        root.update()
        assert v.cursor[0] != 4                      # startet nicht auf der fehlenden Schicht
        ax = v.panels[AX]
        ax._redraw()
        z0 = v.cursor[0]
        ax.scroll(1)
        assert v.cursor[0] == z0 + 1

        v.tool_var.set("distance")
        v._tool_changed()
        x0, y0 = ax.mm_to_canvas(1.0, 1.0)
        x1, y1 = ax.mm_to_canvas(4.0, 5.0)
        ax.canvas.event_generate("<ButtonPress-1>", x=int(x0), y=int(y0))
        ax.canvas.event_generate("<B1-Motion>", x=int(x1), y=int(y1))
        ax.canvas.event_generate("<ButtonRelease-1>", x=int(x1), y=int(y1))
        root.update()
        assert len(v.measurements) == 1
        assert distance_mm(*v.measurements[0]["pts"]) == pytest.approx(5.0, abs=0.3)

        v.tool_var.set("curve")
        v._tool_changed()
        for mx, my in ((1.5, 4.0), (4.0, 6.5), (6.5, 4.0)):
            cx, cy = ax.mm_to_canvas(mx, my)
            ax.canvas.event_generate("<ButtonPress-1>", x=int(cx), y=int(cy))
        ax._double(None)
        root.update()
        assert v.curve_done and v.q4_var.get() == "panorama"
        v.panel_pan._redraw()
        assert v.panel_pan._geom is not None

        v.toggle_maximize(v.panels[COR])
        root.update()
        v.reset_views()
        v.q4_var.set("3d")
        v._q4_changed()
        v.panel3d.render()
        root.update()
        assert v.panel3d._photo is not None
        assert not errors, errors
    finally:
        v.close()
        root.destroy()
