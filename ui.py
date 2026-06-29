from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar, QDialog, QCheckBox, QGridLayout,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc    = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class HackerPrankOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(0, 8, 4, 240);")
        
        # Matrix Columns
        self.cols = 50
        self.drops = [0] * self.cols
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 50, 50, 50)
        
        self.logs_label = QLabel()
        self.logs_label.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self.logs_label.setStyleSheet("color: #00ff88; background: transparent; border: none;")
        self.logs_label.setWordWrap(True)
        self.logs_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.logs_label)
        
        self.logs_list = [
            "◈  JARVIS MAIN DECRYPTION PROTOCOL ACTIVE  ◈",
            "==================================================",
            "[SYSTEM] Bypassing Windows local firewalls...",
            "[NET] Scanning local subnet nodes...",
            "[SEC] Intercepting SSL handshake certificates...",
            "[KEY] Injecting visual exploit buffer...",
            "[SUCCESS] MAINFRAME DIRECT ACCESS GRANTED.",
            "[INFO] Downloading partition tables...",
            "[!] ENCRYPTING USER INTERFACE PROTOCOLS...",
        ]
        self.current_logs = []
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.add_log_line)
        self.log_timer.start(800)
        self.add_log_line()

    def add_log_line(self):
        if len(self.current_logs) < len(self.logs_list):
            self.current_logs.append(self.logs_list[len(self.current_logs)])
            self.logs_label.setText("\n".join(self.current_logs))
        else:
            self.log_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(QFont("Courier New", 8))
        
        # Draw matrix rain
        for i in range(self.cols):
            x = i * 20
            if x > self.width():
                break
            y = self.drops[i] * 16
            
            char = random.choice("01010101ABCDEFHIJKLMNOPQRSTUVWXYZ$#@%&")
            painter.setPen(QColor(0, 255, 136, 80))
            painter.drawText(x, y, char)
            
            if y > self.height() or random.random() > 0.96:
                self.drops[i] = 0
            else:
                self.drops[i] += 1
        painter.end()

    def mousePressEvent(self, event):
        self.timer.stop()
        self.log_timer.stop()
        self.hide()
        self.deleteLater()


class ClickableLabel(QLabel):
    clicked = pyqtSignal(int, int)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self.clicked.emit(int(pos.x()), int(pos.y()))


class PhoneMirrorWorker(QObject):
    frame_ready = pyqtSignal(bytes)
    error_occurred = pyqtSignal(str)

    def __init__(self, serial):
        super().__init__()
        self.serial = serial
        self.running = True

    def start_loop(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        from actions.screen_processor import _capture_phone
        while self.running:
            try:
                img_bytes, _ = _capture_phone(self.serial, compress=False)
                if self.running:
                    self.frame_ready.emit(img_bytes)
            except Exception as e:
                if self.running:
                    self.error_occurred.emit(str(e))
            time.sleep(0.3)  # ~3 FPS is good and doesn't overload ADB/CPU


class PhoneMirrorWindow(QDialog):
    def __init__(self, serial, model_name="Android Device", parent=None):
        super().__init__(parent)
        self.serial = serial
        self.model_name = model_name
        self.setWindowTitle(f"JARVIS Mirror — {model_name}")
        self.resize(450, 850)
        self.setMinimumSize(320, 600)
        self.setStyleSheet(f"background-color: {C.BG}; border: 1px solid {C.BORDER};")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Header Info
        hdr = QHBoxLayout()
        lbl_title = QLabel(f"📱 REMOTE SCREEN: {model_name}")
        lbl_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {C.PRI}; border: none; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        layout.addLayout(hdr)

        # Live Frame Canvas
        self._screen_label = ClickableLabel()
        self._screen_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._screen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screen_label.setStyleSheet(f"border: 1px solid {C.BORDER_A}; background: #000000; border-radius: 4px;")
        self._screen_label.clicked.connect(self._on_screen_clicked)
        layout.addWidget(self._screen_label)

        # Bottom Simulator Buttons
        nav_lay = QHBoxLayout()
        nav_lay.setSpacing(6)

        def _nav_btn(txt, cb):
            btn = QPushButton(txt)
            btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.PANEL2}; color: {C.TEXT_MED}; border: 1px solid {C.BORDER_A}; border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI};
                }}
            """)
            btn.clicked.connect(cb)
            return btn

        nav_lay.addWidget(_nav_btn("◀ BACK", self._on_back_clicked))
        nav_lay.addWidget(_nav_btn("⬡ HOME", self._on_home_clicked))
        nav_lay.addWidget(_nav_btn("■ RECENTS", self._on_recents_clicked))
        layout.addLayout(nav_lay)

        # Mirror Worker
        self._worker = PhoneMirrorWorker(self.serial)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start_loop()

    def _on_frame_ready(self, img_bytes):
        pix = QPixmap()
        if pix.loadFromData(img_bytes):
            self._last_pixmap = pix
            self._screen_label.setPixmap(pix.scaled(
                self._screen_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

    def _on_error(self, err_msg):
        pass

    def _on_screen_clicked(self, lx, ly):
        if not hasattr(self, "_last_pixmap") or self._last_pixmap.isNull():
            return
        
        pw = self._last_pixmap.width()
        ph = self._last_pixmap.height()
        lw = self._screen_label.width()
        lh = self._screen_label.height()
        
        if lw <= 0 or lh <= 0 or pw <= 0 or ph <= 0:
            return
            
        scale = min(lw / pw, lh / ph)
        disp_w = pw * scale
        disp_h = ph * scale
        
        dx = (lw - disp_w) / 2
        dy = (lh - disp_h) / 2
        
        rx = lx - dx
        ry = ly - dy
        
        if 0 <= rx <= disp_w and 0 <= ry <= disp_h:
            px = int((rx / disp_w) * pw)
            py = int((ry / disp_h) * ph)
            
            def _tap_worker():
                try:
                    from actions.phone_control import _tap
                    _tap(self.serial, px, py)
                except Exception:
                    pass
            threading.Thread(target=_tap_worker, daemon=True).start()

    def _send_keyevent(self, keycode):
        def _key_worker():
            try:
                from actions.phone_control import _adb_shell
                _adb_shell(self.serial, "input", "keyevent", str(keycode))
            except Exception:
                pass
        threading.Thread(target=_key_worker, daemon=True).start()

    def _on_back_clicked(self):
        self._send_keyevent(4)

    def _on_home_clicked(self):
        self._send_keyevent(3)

    def _on_recents_clicked(self):
        self._send_keyevent(187)

    def closeEvent(self, event):
        self._worker.running = False
        super().closeEvent(event)


class BackupDialog(QDialog):
    log_added = pyqtSignal(str)
    progress_updated = pyqtSignal(int)
    backup_finished = pyqtSignal(str)

    def __init__(self, serial, parent=None):
        super().__init__(parent)
        self.serial = serial
        self.setWindowTitle("JARVIS — Phone Backup Utility")
        self.setFixedSize(480, 520)
        self.setStyleSheet(f"background-color: {C.BG}; border: 1px solid {C.BORDER};")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # Header Info
        hdr = QHBoxLayout()
        lbl_title = QLabel("📦 PHONE BACKUP UTILITY")
        lbl_title.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {C.PRI}; border: none; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        layout.addLayout(hdr)

        # Device info
        lbl_dev = QLabel(f"Target Device Serial: {self.serial}")
        lbl_dev.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_dev.setStyleSheet(f"color: {C.TEXT_MED}; border: none; background: transparent;")
        layout.addWidget(lbl_dev)

        # Checkboxes for what to backup
        self.cb_contacts = self._create_checkbox("Contacts (Phone Numbers & Names)")
        self.cb_photos = self._create_checkbox("Camera Photos & DCIM Images")
        self.cb_documents = self._create_checkbox("Documents Folder (/sdcard/Documents)")
        self.cb_downloads = self._create_checkbox("Downloads Folder (/sdcard/Download)")

        # Select all by default
        self.cb_contacts.setChecked(True)
        self.cb_photos.setChecked(True)
        self.cb_documents.setChecked(True)
        self.cb_downloads.setChecked(True)

        layout.addWidget(self.cb_contacts)
        layout.addWidget(self.cb_photos)
        layout.addWidget(self.cb_documents)
        layout.addWidget(self.cb_downloads)

        # Destination selector
        dest_lay = QHBoxLayout()
        lbl_dest = QLabel("Destination:")
        lbl_dest.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_dest.setStyleSheet(f"color: {C.TEXT_DIM}; border: none; background: transparent;")
        dest_lay.addWidget(lbl_dest)

        self.txt_dest = QLineEdit()
        self.txt_dest.setFont(QFont("Courier New", 8))
        default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
        self.txt_dest.setText(default_dir)
        self.txt_dest.setStyleSheet(f"color: {C.TEXT}; background: {C.DARK}; border: 1px solid {C.BORDER_A}; padding: 3px;")
        dest_lay.addWidget(self.txt_dest)

        btn_browse = QPushButton("Browse")
        btn_browse.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setFixedHeight(24)
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.PRI}; border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 2px 6px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI};
            }}
        """)
        btn_browse.clicked.connect(self._on_browse)
        dest_lay.addWidget(btn_browse)
        layout.addLayout(dest_lay)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C.DARK}; border: 1px solid {C.BORDER_A}; border-radius: 4px; text-align: center; color: {C.WHITE};
            }}
            QProgressBar::chunk {{
                background-color: {C.GREEN}; border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # Log Console
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFont(QFont("Courier New", 8))
        self.log_console.setStyleSheet(f"background-color: {C.DARK}; color: {C.GREEN}; border: 1px solid {C.BORDER_A}; border-radius: 4px;")
        layout.addWidget(self.log_console)

        # Buttons
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(10)

        self.btn_start = QPushButton("⚡ START BACKUP")
        self.btn_start.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.btn_start.setFixedHeight(30)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #002b20, stop:1 #004d33);
                color: {C.GREEN}; border: 1px solid {C.GREEN_D}; border-radius: 4px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #003d2e, stop:1 #006644);
                border: 1px solid {C.GREEN};
            }}
            QPushButton:disabled {{
                background: #111111; color: #555555; border: 1px solid #222222;
            }}
        """)
        self.btn_start.clicked.connect(self._on_start_backup)
        btn_lay.addWidget(self.btn_start)

        self.btn_close = QPushButton("CLOSE")
        self.btn_close.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.btn_close.setFixedHeight(30)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.TEXT_MED}; border: 1px solid {C.BORDER_A}; border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI};
            }}
        """)
        self.btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(self.btn_close)

        layout.addLayout(btn_lay)

        # Wire up custom signals
        self.log_added.connect(self._add_log)
        self.progress_updated.connect(self.progress_bar.setValue)
        self.backup_finished.connect(self._on_backup_finished)

        self._add_log("Ready to backup.")

    def _create_checkbox(self, text):
        cb = QCheckBox(text)
        cb.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        cb.setStyleSheet(f"""
            QCheckBox {{
                color: {C.TEXT}; spacing: 8px; border: none; background: transparent;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px; border: 1px solid {C.BORDER_A}; border-radius: 2px; background: {C.DARK};
            }}
            QCheckBox::indicator:checked {{
                background: {C.PRI}; border: 1px solid {C.PRI};
            }}
        """)
        return cb

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Backup Directory", self.txt_dest.text())
        if folder:
            self.txt_dest.setText(folder)

    def _add_log(self, text):
        self.log_console.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    def _on_start_backup(self):
        self.btn_start.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_console.clear()
        
        backup_types = []
        if self.cb_contacts.isChecked(): backup_types.append("contacts")
        if self.cb_photos.isChecked(): backup_types.append("photos")
        if self.cb_documents.isChecked(): backup_types.append("documents")
        if self.cb_downloads.isChecked(): backup_types.append("downloads")

        if not backup_types:
            self._add_log("Error: Please select at least one item to backup.")
            self.btn_start.setEnabled(True)
            self.btn_close.setEnabled(True)
            return

        dest_dir = self.txt_dest.text().strip()
        if not dest_dir:
            self._add_log("Error: Please select a valid destination folder.")
            self.btn_start.setEnabled(True)
            self.btn_close.setEnabled(True)
            return

        self._add_log(f"Starting backup process in background...")
        
        def run_thread():
            try:
                from actions.phone_control import _backup_phone
                def log_cb(msg):
                    self.log_added.emit(msg)
                def prog_cb(val):
                    self.progress_updated.emit(val)

                total = len(backup_types)
                for idx, t in enumerate(backup_types):
                    log_cb(f"Backup item: {t.upper()} in progress...")
                    prog_cb(int((idx / total) * 100))
                    _backup_phone(
                        serial=self.serial,
                        backup_type=t,
                        local_dest_dir=dest_dir,
                        log_callback=log_cb,
                        progress_callback=None
                    )
                
                prog_cb(100)
                self.backup_finished.emit("SUCCESS")
            except Exception as e:
                self.log_added.emit(f"Backup critical error: {e}")
                self.backup_finished.emit(f"ERROR: {e}")

        threading.Thread(target=run_thread, daemon=True).start()

    def _on_backup_finished(self, status):
        self.btn_start.setEnabled(True)
        self.btn_close.setEnabled(True)
        if status == "SUCCESS":
            self._add_log("Backup process finished successfully.")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Backup Complete", "Your phone data backup completed successfully.")
        else:
            self._add_log(f"Backup process failed: {status}")


class PairOverlay(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PairOverlay {{
                background: rgba(0, 6, 10, 250);
                border: 2px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("◈  WIRELESS ADB PHONE PAIRING")
        title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent; border: none;")
        hdr.addWidget(title)
        
        close_btn = QPushButton("✕")
        close_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C.RED}; background: transparent; border: 1px solid {C.RED}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: #fff; background: {C.RED};
            }}
        """)
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        layout.addWidget(sep)

        # Content split in columns: Left (QR & Instructions), Right (Manual Fields)
        body = QHBoxLayout()
        body.setSpacing(15)

        # Left Column: QR Code
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        
        instructions = QLabel(
            "1. Enable Developer Options\n"
            "2. Turn on Wireless Debugging\n"
            "3. Choose 'Pair device with QR code'\n"
            "   and scan this QR code:"
        )
        instructions.setFont(QFont("Courier New", 7))
        instructions.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        left_col.addWidget(instructions)

        self._qr_label = QLabel()
        self._qr_label.setFixedSize(160, 160)
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setStyleSheet(f"border: 1px solid {C.BORDER}; background: #00060a; border-radius: 4px;")
        left_col.addWidget(self._qr_label)
        
        left_col.addStretch()
        body.addLayout(left_col, stretch=1)

        # Right Column: Manual Entry Form
        right_col = QVBoxLayout()
        right_col.setSpacing(4)

        def _lbl(txt):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
            return l

        right_col.addWidget(_lbl("MANUAL PAIR / CONNECT"))

        right_col.addWidget(_lbl("PHONE IP ADDRESS"))
        self._ip_input = QLineEdit()
        self._ip_input.setFont(QFont("Courier New", 8))
        self._ip_input.setStyleSheet(f"background: #000c12; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 3px; border-radius: 2px;")
        right_col.addWidget(self._ip_input)

        # Pairing Port and Code row
        row1 = QHBoxLayout()
        v1 = QVBoxLayout(); v1.addWidget(_lbl("PAIR PORT")); self._pair_port = QLineEdit("5555"); self._pair_port.setFont(QFont("Courier New", 8)); self._pair_port.setStyleSheet(f"background: #000c12; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 3px; border-radius: 2px;"); v1.addWidget(self._pair_port); row1.addLayout(v1)
        v2 = QVBoxLayout(); v2.addWidget(_lbl("PAIR CODE")); self._pair_code = QLineEdit(); self._pair_code.setFont(QFont("Courier New", 8)); self._pair_code.setStyleSheet(f"background: #000c12; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 3px; border-radius: 2px;"); v2.addWidget(self._pair_code); row1.addLayout(v2)
        right_col.addLayout(row1)

        # Connection Port
        right_col.addWidget(_lbl("CONNECTION PORT (if different)"))
        self._conn_port = QLineEdit()
        self._conn_port.setPlaceholderText("Defaults to Pair Port")
        self._conn_port.setFont(QFont("Courier New", 8))
        self._conn_port.setStyleSheet(f"background: #000c12; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 3px; border-radius: 2px;")
        right_col.addWidget(self._conn_port)

        right_col.addSpacing(6)

        # Action Buttons
        self._btn_pair = QPushButton("⚡ PAIR DEVICE")
        self._btn_pair.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._btn_pair.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pair.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI_DIM}; border-radius: 3px; padding: 4px;
            }}
            QPushButton:hover {{
                background: {C.PRI}; color: #000; border: 1px solid {C.PRI};
            }}
        """)
        self._btn_pair.clicked.connect(self._on_pair_clicked)
        right_col.addWidget(self._btn_pair)

        self._btn_connect = QPushButton("🔌 CONNECT ONLY")
        self._btn_connect.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_connect.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.GREEN}; border: 1px solid {C.GREEN_D}; border-radius: 3px; padding: 4px;
            }}
            QPushButton:hover {{
                background: {C.GREEN_D}; color: #000; border: 1px solid {C.GREEN};
            }}
        """)
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        right_col.addWidget(self._btn_connect)

        right_col.addStretch()
        body.addLayout(right_col, stretch=1)
        layout.addLayout(body)

        # Status Bar
        self._status = QLabel("Status: Ready")
        self._status.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._status.setStyleSheet(f"color: {C.TEXT_MED}; background: #000c12; border: 1px solid {C.BORDER}; padding: 4px; border-radius: 3px;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Load QR Data
        self._load_qr()

    def _load_qr(self):
        try:
            from actions.qr_pairing import generate_pairing_qr
            # We will use 5555 as default pairing port (adb standard default)
            png, ip, text = generate_pairing_qr(5555)
            pix = QPixmap()
            if pix.loadFromData(png):
                self._qr_label.setPixmap(pix.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
            self._ip_input.setText(ip)
            self._status.setText(f"QR Generated. Local IP detected: {ip}")
        except Exception as e:
            self._status.setText(f"QR Error: {e}")

    def _set_status(self, text, color=None):
        color = color or C.TEXT_MED
        self._status.setText(f"Status: {text}")
        self._status.setStyleSheet(f"color: {color}; background: #000c12; border: 1px solid {C.BORDER}; padding: 4px; border-radius: 3px;")

    def _on_pair_clicked(self):
        ip = self._ip_input.text().strip()
        port = self._pair_port.text().strip()
        code = self._pair_code.text().strip()
        conn_port = self._conn_port.text().strip() or port

        if not ip or not port or not code:
            self._set_status("IP, Port, and Code are required for pairing!", C.RED)
            return

        self._set_status("Pairing in progress...", C.PRI)
        self._btn_pair.setEnabled(False)

        def _worker():
            try:
                from actions.qr_pairing import pair_device, connect_device
                res_pair = pair_device(ip, int(port), code)
                if "Successfully paired" in res_pair:
                    # Successfully paired, now try to connect
                    res_conn = connect_device(ip, int(conn_port))
                    self._set_status(f"Paired! {res_conn}", C.GREEN)
                else:
                    self._set_status(res_pair, C.RED)
            except Exception as e:
                self._set_status(f"Error: {e}", C.RED)
            finally:
                self._btn_pair.setEnabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_connect_clicked(self):
        ip = self._ip_input.text().strip()
        port = self._conn_port.text().strip() or self._pair_port.text().strip()

        if not ip or not port:
            self._set_status("IP and Port are required to connect!", C.RED)
            return

        self._set_status("Connecting...", C.PRI)
        self._btn_connect.setEnabled(False)

        def _worker():
            try:
                from actions.qr_pairing import connect_device
                res = connect_device(ip, int(port))
                if "Connected" in res:
                    self._set_status(res, C.GREEN)
                else:
                    self._set_status(res, C.RED)
            except Exception as e:
                self._set_status(f"Error: {e}", C.RED)
            finally:
                self._btn_connect.setEnabled(True)

        threading.Thread(target=_worker, daemon=True).start()


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _hacker_prank_sig = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S — MARK XXXIX")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None
        self.active_device: str | None = None
        self._phone_widgets = {}

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()
        self._update_phone_list()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._hacker_prank_sig.connect(self._show_hacker_prank)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            if isinstance(self._overlay, PairOverlay):
                ow, oh = 520, 330
            else:
                ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )

    def _update_metrics(self):
        if hasattr(self, "_send_to_phone_btn"):
            curr = self._drop_zone.current_file()
            if not curr and self._send_to_phone_btn.isEnabled():
                self._current_file = None
                self._send_to_phone_btn.setEnabled(False)
                self._send_to_phone_btn.setText("📤 SEND TO ACTIVE PHONE")

        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")

        self._update_phone_list()


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MARK XXXIX", C.PRI_DIM))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("J.A.R.V.I.S")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Just A Rather Very Intelligent System")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        hdr_phone = QLabel("◈ PHONE MANAGER")
        hdr_phone.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr_phone.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                                 f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr_phone)
        lay.addSpacing(2)

        self._phone_scroll = QScrollArea()
        self._phone_scroll.setWidgetResizable(True)
        self._phone_scroll.setFixedHeight(120)
        self._phone_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: #000c12;
                border: 1px solid {C.BORDER};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background: #000c12;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C.PRI_DIM};
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self._phone_container = QWidget()
        self._phone_container.setStyleSheet("background: transparent;")
        self._phone_layout = QVBoxLayout(self._phone_container)
        self._phone_layout.setContentsMargins(4, 4, 4, 4)
        self._phone_layout.setSpacing(4)
        
        self._phone_scroll.setWidget(self._phone_container)
        lay.addWidget(self._phone_scroll)

        # ── QR Pairing Button ──
        self._pair_btn = QPushButton("📱 PAIR NEW DEVICE")
        self._pair_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._pair_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pair_btn.setFixedHeight(28)
        self._pair_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001a2e, stop:1 #002a1a);
                color: {C.GREEN};
                border: 1px solid {C.GREEN_D};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #002a3e, stop:1 #003a2a);
                border: 1px solid {C.GREEN};
            }}
        """)
        self._pair_btn.clicked.connect(self._show_qr_overlay)
        lay.addWidget(self._pair_btn)

        # ── View Screen Button ──
        self._view_screen_btn = QPushButton("🖥️ VIEW PHONE SCREEN")
        self._view_screen_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._view_screen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_screen_btn.setFixedHeight(28)
        self._view_screen_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001220, stop:1 #002230);
                color: {C.PRI};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #002235, stop:1 #003245);
                border: 1px solid {C.PRI};
            }}
        """)
        self._view_screen_btn.clicked.connect(self._show_phone_mirror)
        lay.addWidget(self._view_screen_btn)

        # ── Backup Button ──
        self._backup_btn = QPushButton("📦 PHONE BACKUP")
        self._backup_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._backup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._backup_btn.setFixedHeight(28)
        self._backup_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001220, stop:1 #002230);
                color: {C.PRI};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #002235, stop:1 #003245);
                border: 1px solid {C.PRI};
            }}
        """)
        self._backup_btn.clicked.connect(self._show_phone_backup)
        lay.addWidget(self._backup_btn)

        # ── Share Clipboard Button ──
        self._share_clip_btn = QPushButton("📋 SHARE CLIPBOARD")
        self._share_clip_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._share_clip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._share_clip_btn.setFixedHeight(28)
        self._share_clip_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001220, stop:1 #002230);
                color: {C.PRI};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #002235, stop:1 #003245);
                border: 1px solid {C.PRI};
            }}
        """)
        self._share_clip_btn.clicked.connect(self._on_share_clipboard_clicked)
        lay.addWidget(self._share_clip_btn)

        # ── Register Face ID Button ──
        self._register_face_btn = QPushButton("👤 REGISTER FACE ID")
        self._register_face_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._register_face_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_face_btn.setFixedHeight(28)
        self._register_face_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001220, stop:1 #002230);
                color: {C.PRI};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #002235, stop:1 #003245);
                border: 1px solid {C.PRI};
            }}
        """)
        self._register_face_btn.clicked.connect(self._on_register_face_clicked)
        lay.addWidget(self._register_face_btn)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",     C.GREEN),
            ("SEC\nCLEARED",        C.PRI),
            ("PROTOCOL\nXXXVIII",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            lay.addWidget(lbl)

        self._routines_badge = QLabel()
        self._routines_badge.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._routines_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._routines_badge.setStyleSheet(
            f"color: {C.GREEN}; background: {C.PANEL2};"
            f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
        )
        lay.addWidget(self._routines_badge)
        self.update_routines_badge()

        return w

    def _build_iot_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {C.BORDER_A}; border-radius: 4px;")
        grid = QGridLayout(panel)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(6)

        def _iot_btn(icon, title, color_on, click_cb):
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(54)
            v_lay = QVBoxLayout(btn)
            v_lay.setContentsMargins(2, 2, 2, 2)
            v_lay.setSpacing(2)
            
            lbl_ico = QLabel(icon)
            lbl_ico.setFont(QFont("Courier New", 12))
            lbl_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_ico.setStyleSheet("border: none; background: transparent;")
            v_lay.addWidget(lbl_ico)
            
            lbl_txt = QLabel(title)
            lbl_txt.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl_txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_txt.setStyleSheet("border: none; background: transparent; color: #5ab8cc;")
            v_lay.addWidget(lbl_txt)
            
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
            btn.clicked.connect(click_cb)
            btn._lbl_ico = lbl_ico
            btn._lbl_txt = lbl_txt
            btn._icon_char = icon
            btn._title_base = title
            btn._color_on = color_on
            return btn

        self._iot_light = _iot_btn("💡", "LIGHT: OFF", C.ACC2, self._on_iot_light_clicked)
        self._iot_ac = _iot_btn("❄️", "AC: OFF", C.PRI, self._on_iot_ac_clicked)
        self._iot_fan = _iot_btn("🌀", "FAN: OFF", C.GREEN, self._on_iot_fan_clicked)
        self._iot_lock = _iot_btn("🔒", "DOOR: LOCKED", C.RED, self._on_iot_lock_clicked)

        grid.addWidget(self._iot_light, 0, 0)
        grid.addWidget(self._iot_ac, 0, 1)
        grid.addWidget(self._iot_fan, 1, 0)
        grid.addWidget(self._iot_lock, 1, 1)

        QTimer.singleShot(500, self.update_smart_home_ui)
        return panel

    def _on_iot_light_clicked(self):
        try:
            from actions.smart_home import _load_state, smart_home
            state = _load_state()
            new_act = "turn_off" if state.get("light") == "ON" else "turn_on"
            smart_home({"action": new_act, "device": "light"}, player=self)
        except Exception:
            pass

    def _on_iot_ac_clicked(self):
        try:
            from actions.smart_home import _load_state, smart_home
            state = _load_state()
            new_act = "turn_off" if state.get("ac_status") == "ON" else "turn_on"
            smart_home({"action": new_act, "device": "ac"}, player=self)
        except Exception:
            pass

    def _on_iot_fan_clicked(self):
        try:
            from actions.smart_home import _load_state, smart_home
            state = _load_state()
            speed = state.get("fan", "OFF")
            new_act = "turn_off" if speed != "OFF" and speed != "0" else "turn_on"
            smart_home({"action": new_act, "device": "fan"}, player=self)
        except Exception:
            pass

    def _on_iot_lock_clicked(self):
        try:
            from actions.smart_home import _load_state, smart_home
            state = _load_state()
            new_act = "turn_off" if state.get("door_lock") == "LOCKED" else "turn_on"
            smart_home({"action": new_act, "device": "lock"}, player=self)
        except Exception:
            pass

    def update_smart_home_ui(self):
        try:
            from actions.smart_home import _load_state
            state = _load_state()
            
            # 1. Update Light
            is_light_on = state.get("light") == "ON"
            self._iot_light._lbl_txt.setText("LIGHT: ON" if is_light_on else "LIGHT: OFF")
            self._iot_light._lbl_ico.setStyleSheet(f"color: {self._iot_light._color_on if is_light_on else C.TEXT_DIM};")
            self._iot_light.setStyleSheet(f"""
                QPushButton {{
                    background: {C.DARK}; border: 1px solid {C.PRI if is_light_on else C.BORDER}; border-radius: 3px;
                }}
            """)
            
            # 2. Update AC
            is_ac_on = state.get("ac_status") == "ON"
            temp = state.get("ac_temp", 24)
            self._iot_ac._lbl_txt.setText(f"AC: {temp}°C" if is_ac_on else "AC: OFF")
            self._iot_ac._lbl_ico.setStyleSheet(f"color: {self._iot_ac._color_on if is_ac_on else C.TEXT_DIM};")
            self._iot_ac.setStyleSheet(f"""
                QPushButton {{
                    background: {C.DARK}; border: 1px solid {C.PRI if is_ac_on else C.BORDER}; border-radius: 3px;
                }}
            """)

            # 3. Update Fan
            fan_val = state.get("fan", "OFF")
            is_fan_on = fan_val != "OFF" and fan_val != "0"
            self._iot_fan._lbl_txt.setText(f"FAN: SPD {fan_val}" if is_fan_on else "FAN: OFF")
            self._iot_fan._lbl_ico.setStyleSheet(f"color: {self._iot_fan._color_on if is_fan_on else C.TEXT_DIM};")
            self._iot_fan.setStyleSheet(f"""
                QPushButton {{
                    background: {C.DARK}; border: 1px solid {C.GREEN if is_fan_on else C.BORDER}; border-radius: 3px;
                }}
            """)

            # 4. Update Door Lock
            is_locked = state.get("door_lock") == "LOCKED"
            self._iot_lock._lbl_txt.setText("DOOR: LOCKED" if is_locked else "DOOR: OPEN")
            self._iot_lock._lbl_ico.setText("🔒" if is_locked else "🔓")
            self._iot_lock._lbl_ico.setStyleSheet(f"color: {self._iot_lock._color_on if is_locked else C.GREEN};")
            self._iot_lock.setStyleSheet(f"""
                QPushButton {{
                    background: {C.DARK}; border: 1px solid {C.RED if is_locked else C.GREEN_D}; border-radius: 3px;
                }}
            """)

        except Exception as e:
            print(f"[UI] Smart home repaint failed: {e}")

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("🧠 COGNITIVE BRAIN (THOUGHT LOG)"))
        self._thought_log = LogWidget()
        self._thought_log.setFixedHeight(110)
        lay.addWidget(self._thought_log)

        sep_thought = QFrame(); sep_thought.setFrameShape(QFrame.Shape.HLine)
        sep_thought.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep_thought)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        # ── Send to Phone Button ──
        self._send_to_phone_btn = QPushButton("📤 SEND TO ACTIVE PHONE")
        self._send_to_phone_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._send_to_phone_btn.setFixedHeight(24)
        self._send_to_phone_btn.setEnabled(False)
        self._send_to_phone_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_to_phone_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM}; border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:enabled {{
                background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI_DIM};
            }}
            QPushButton:enabled:hover {{
                background: {C.PRI}; color: #000; border: 1px solid {C.PRI};
            }}
        """)
        self._send_to_phone_btn.clicked.connect(self._on_send_to_phone_clicked)
        lay.addWidget(self._send_to_phone_btn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        # ── Smart Home IoT Panel ──
        lay.addWidget(_sec("SMART HOME IoT"))
        self._iot_panel = self._build_iot_panel()
        lay.addWidget(self._iot_panel)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep3)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("FatihMakes Industries  ·  MARK XXXIX  ·  CLASSIFIED"))
        lay.addStretch()
        lay.addWidget(_fl("© FATIHMAKES", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell JARVIS what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        
        self._send_to_phone_btn.setEnabled(True)
        self._send_to_phone_btn.setText(f"📤 SEND '{p.name}' TO PHONE")
        
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _on_send_to_phone_clicked(self):
        if not self._current_file:
            return
        if not self.active_device:
            self._log.append_log("SYS: Cannot transfer file — no phone connected.")
            return
        
        file_path = self._current_file
        self._send_to_phone_btn.setEnabled(False)
        self._send_to_phone_btn.setText("Sending...")
        
        def _worker():
            try:
                from actions.phone_control import _push_file
                res = _push_file(self.active_device, file_path, "/sdcard/Download/")
                self._log.append_log(f"SYS: {res}")
            except Exception as e:
                self._log.append_log(f"SYS: Transfer failed: {e}")
            finally:
                QTimer.singleShot(0, lambda: self._reset_send_button())
                
        threading.Thread(target=_worker, daemon=True).start()

    def _reset_send_button(self):
        curr = self._drop_zone.current_file()
        if not curr:
            self._current_file = None
            self._send_to_phone_btn.setText("📤 SEND TO ACTIVE PHONE")
            self._send_to_phone_btn.setEnabled(False)
            return

        self._send_to_phone_btn.setEnabled(True)
        if self._current_file:
            name = Path(self._current_file).name
            self._send_to_phone_btn.setText(f"📤 SEND '{name}' TO PHONE")
        else:
            self._send_to_phone_btn.setText("📤 SEND TO ACTIVE PHONE")
            self._send_to_phone_btn.setEnabled(False)

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _show_qr_overlay(self):
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        
        ov = PairOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 520, 330
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(self._close_overlay)
        ov.show()
        self._overlay = ov

    def _close_overlay(self):
        if self._overlay:
            self._overlay.hide()
            self._overlay = None

    def _show_phone_mirror(self):
        if not self.active_device:
            self._log.append_log("SYS: No active device connected to mirror screen.")
            return
        
        model = "Android Device"
        widget = self._phone_widgets.get(self.active_device)
        if widget:
            tip = widget.toolTip()
            for line in tip.split("\n"):
                if line.startswith("Model:"):
                    model = line.split(":", 1)[1].strip()
                    break

        dialog = PhoneMirrorWindow(self.active_device, model, self)
        dialog.show()

    def _show_phone_backup(self):
        if not self.active_device:
            self._log.append_log("SYS: No active device connected to run backup.")
            return
        
        dialog = BackupDialog(self.active_device, self)
        dialog.exec()

    def _on_share_clipboard_clicked(self):
        if not self.active_device:
            self._log.append_log("SYS: No active device connected to share clipboard.")
            return
        
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if not text:
            self._log.append_log("SYS: PC clipboard is empty.")
            return
            
        self._log.append_log(f"SYS: Sharing PC clipboard to phone: '{text[:25]}...'")
        
        def run_share():
            try:
                from actions.phone_control import _share_clipboard
                res = _share_clipboard(self.active_device, text)
                self._log_sig.emit(f"SYS: {res}")
            except Exception as e:
                self._log_sig.emit(f"SYS: Clipboard share error: {e}")
        
        threading.Thread(target=run_share, daemon=True).start()

    def _on_register_face_clicked(self):
        self._log.append_log("SYS: Opening camera to register Face ID...")
        def run_reg():
            try:
                from actions.face_auth import register_face_id
                res = register_face_id(player=self)
                self._log_sig.emit(f"SYS: {res}")
            except Exception as e:
                self._log_sig.emit(f"SYS: Face ID registration error: {e}")
        threading.Thread(target=run_reg, daemon=True).start()

    def update_routines_badge(self):
        try:
            from actions.jarvis_learning import _load_routines
            count = len(_load_routines())
        except Exception:
            count = 0
        if hasattr(self, "_routines_badge"):
            self._routines_badge.setText(f"ROUTINES\n{count} LEARNED")

    def _show_hacker_prank(self):
        ov = HackerPrankOverlay(self.centralWidget())
        cw = self.centralWidget()
        ov.setGeometry(0, 0, cw.width(), cw.height())
        ov.show()

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. JARVIS online.")

    def _select_phone(self, serial: str):
        self.active_device = serial
        self._style_phone_items()
        self._log.append_log(f"SYS: Active phone set to '{serial}'.")

    def _style_phone_items(self):
        for serial, btn in self._phone_widgets.items():
            if serial == self.active_device:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PRI_GHO};
                        color: {C.PRI};
                        border: 1px solid {C.PRI};
                        border-radius: 3px;
                        padding: 4px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PANEL2};
                        color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER_A};
                        border-radius: 3px;
                        padding: 4px;
                    }}
                    QPushButton:hover {{
                        color: {C.WHITE};
                        border: 1px solid {C.BORDER_B};
                    }}
                """)

    def _update_phone_list(self):
        try:
            from actions.phone_control import _list_devices
            devices = _list_devices()
        except Exception as e:
            print(f"[UI] [!] Failed to list devices: {e}")
            return

        current_serials = {d["serial"] for d in devices}
        cached_serials = set(self._phone_widgets.keys())

        if current_serials == cached_serials:
            if self.active_device not in current_serials:
                if devices:
                    self.active_device = devices[0]["serial"]
                else:
                    self.active_device = None
                self._style_phone_items()
            return

        while self._phone_layout.count():
            item = self._phone_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._phone_widgets = {}

        if not devices:
            lbl = QLabel("No devices\nconnected")
            lbl.setFont(QFont("Courier New", 7))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._phone_layout.addWidget(lbl)
            self.active_device = None
            return

        if self.active_device not in current_serials:
            self.active_device = devices[0]["serial"]

        for d in devices:
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Model: {d['model']}\nSerial: {d['serial']}\nClick to set active")
            
            btn_lay = QVBoxLayout(btn)
            btn_lay.setContentsMargins(4, 4, 4, 4)
            btn_lay.setSpacing(0)
            
            lbl_model = QLabel(d["model"])
            lbl_model.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl_model.setStyleSheet("color: inherit; background: transparent; border: none;")
            
            short = d["serial"]
            if len(short) > 10:
                short = short[:4] + "..." + short[-3:]
            lbl_serial = QLabel(short)
            lbl_serial.setFont(QFont("Courier New", 6))
            lbl_serial.setStyleSheet("color: inherit; background: transparent; border: none; opacity: 0.7;")
            
            btn_lay.addWidget(lbl_model)
            btn_lay.addWidget(lbl_serial)
            
            btn.clicked.connect(lambda _, s=d["serial"]: self._select_phone(s))
            
            self._phone_layout.addWidget(btn)
            self._phone_widgets[d["serial"]] = btn

        self._phone_layout.addStretch()
        self._style_phone_items()


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def active_device(self) -> str | None:
        return self._win.active_device

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def update_routines_badge(self):
        self._win.update_routines_badge()

    def show_hacker_prank(self):
        self._win._hacker_prank_sig.emit()

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
