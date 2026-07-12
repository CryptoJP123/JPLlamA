from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "app" / "gui" / "assets"
ICONSET_DIR = ASSETS_DIR / "jpllama.iconset"
SVG_PATH = ASSETS_DIR / "jpllama-logo.svg"
ICNS_PATH = ASSETS_DIR / "jpllama-logo.icns"


def configure_qt_plugin_path() -> None:
    existing_platform = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "").strip()
    if existing_platform:
        return

    from PySide6 import __file__ as pyside_file  # type: ignore

    qt_plugins = Path(pyside_file).resolve().parent / "Qt" / "plugins"
    source_platforms = qt_plugins / "platforms"
    if not source_platforms.exists():
        return

    runtime_platforms = Path(tempfile.gettempdir()) / "jpllama_qt_plugins" / "platforms"
    runtime_platforms.mkdir(parents=True, exist_ok=True)

    for dylib in source_platforms.glob("libq*.dylib"):
        target = runtime_platforms / dylib.name
        if not target.exists() or dylib.stat().st_mtime_ns > target.stat().st_mtime_ns:
            shutil.copyfile(dylib, target)
            target.chmod(0o755)

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(runtime_platforms)
    os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)


def build_logo_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    bg = QColor("#09131f")
    cyan = QColor("#34d8d4")
    amber = QColor("#f0b25f")

    painter.setPen(Qt.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(0, 0, size, size, size * 0.15, size * 0.15)

    trace_pen = QPen(cyan, max(1, size // 40))
    painter.setPen(trace_pen)
    painter.drawLine(int(size * 0.17), int(size * 0.2), int(size * 0.48), int(size * 0.2))
    painter.drawLine(int(size * 0.17), int(size * 0.78), int(size * 0.48), int(size * 0.78))
    painter.drawLine(int(size * 0.82), int(size * 0.35), int(size * 0.62), int(size * 0.35))
    painter.drawLine(int(size * 0.82), int(size * 0.64), int(size * 0.62), int(size * 0.64))

    painter.setBrush(cyan)
    node_r = max(2, int(size * 0.03))
    for x, y in ((0.17, 0.2), (0.17, 0.78), (0.82, 0.35), (0.82, 0.64), (0.48, 0.2), (0.48, 0.78)):
        painter.drawEllipse(int(size * x) - node_r, int(size * y) - node_r, node_r * 2, node_r * 2)

    head = QPainterPath()
    head.moveTo(size * 0.40, size * 0.75)
    head.lineTo(size * 0.40, size * 0.30)
    head.lineTo(size * 0.46, size * 0.16)
    head.lineTo(size * 0.52, size * 0.30)
    head.lineTo(size * 0.66, size * 0.30)
    head.quadTo(size * 0.77, size * 0.36, size * 0.76, size * 0.47)
    head.quadTo(size * 0.75, size * 0.62, size * 0.63, size * 0.67)
    head.lineTo(size * 0.58, size * 0.76)
    head.closeSubpath()

    painter.setPen(QPen(cyan, max(2, size // 60)))
    painter.setBrush(QColor("#0f2333"))
    painter.drawPath(head)

    painter.setBrush(amber)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(int(size * 0.64), int(size * 0.45), int(size * 0.08), int(size * 0.08))

    painter.setPen(QPen(amber, max(2, size // 50)))
    painter.drawLine(int(size * 0.30), int(size * 0.82), int(size * 0.52), int(size * 0.82))

    painter.end()
    return pixmap


def write_svg(path: Path) -> None:
    svg = """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1024 1024\">\n  <rect width=\"1024\" height=\"1024\" rx=\"160\" fill=\"#09131f\"/>\n  <g stroke=\"#34d8d4\" stroke-width=\"24\" fill=\"none\" stroke-linecap=\"round\">\n    <line x1=\"174\" y1=\"205\" x2=\"492\" y2=\"205\"/>\n    <line x1=\"174\" y1=\"798\" x2=\"492\" y2=\"798\"/>\n    <line x1=\"840\" y1=\"358\" x2=\"635\" y2=\"358\"/>\n    <line x1=\"840\" y1=\"655\" x2=\"635\" y2=\"655\"/>\n  </g>\n  <g fill=\"#34d8d4\">\n    <circle cx=\"174\" cy=\"205\" r=\"26\"/>\n    <circle cx=\"174\" cy=\"798\" r=\"26\"/>\n    <circle cx=\"492\" cy=\"205\" r=\"26\"/>\n    <circle cx=\"492\" cy=\"798\" r=\"26\"/>\n    <circle cx=\"840\" cy=\"358\" r=\"26\"/>\n    <circle cx=\"840\" cy=\"655\" r=\"26\"/>\n  </g>\n  <path d=\"M410 768V307l61-143 61 143h143c95 0 151 73 146 165-6 107-57 156-178 188l-51 108z\" fill=\"#0f2333\" stroke=\"#34d8d4\" stroke-width=\"18\" stroke-linejoin=\"round\"/>\n  <circle cx=\"680\" cy=\"472\" r=\"40\" fill=\"#f0b25f\"/>\n  <line x1=\"307\" y1=\"840\" x2=\"532\" y2=\"840\" stroke=\"#f0b25f\" stroke-width=\"24\" stroke-linecap=\"round\"/>\n</svg>\n"""
    path.write_text(svg, encoding="utf-8")


def write_png_assets() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [32, 64, 128, 256, 512, 1024]
    for size in sizes:
        pixmap = build_logo_pixmap(size)
        pixmap.save(str(ASSETS_DIR / f"jpllama-logo-{size}.png"), "PNG")


def write_iconset() -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    mapping = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, size in mapping.items():
        pixmap = build_logo_pixmap(size)
        pixmap.save(str(ICONSET_DIR / name), "PNG")


def write_icns() -> None:
    iconutil = shutil.which("iconutil")
    if not iconutil:
        return
    subprocess.run([iconutil, "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)], check=False)


def main() -> None:
    configure_qt_plugin_path()
    app = QGuiApplication([])
    write_png_assets()
    write_svg(SVG_PATH)
    write_iconset()
    write_icns()
    app.quit()


if __name__ == "__main__":
    main()
