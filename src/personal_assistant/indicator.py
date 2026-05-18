"""Overlay flotante minimalista.

- Sin fondo. Sólo los iconos en el mismo color para todos los estados.
- Tamaño reducido (~140x36 px por defecto).
- Transiciones "morph through center": el icono anterior se contrae al
  punto central mientras se desvanece, y el nuevo crece desde el centro.
  Visualmente parece que uno se transforma en otro.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
    Property,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .config import OverlayConfig

STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"

_ALL_STATES = (STATE_IDLE, STATE_RECORDING, STATE_THINKING, STATE_SPEAKING)


class Overlay(QWidget):
    sig_state = Signal(str)
    sig_level = Signal(float)
    sig_menu_requested = Signal()

    def __init__(self, cfg: OverlayConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cfg = cfg
        self._fg = (cfg.color_r, cfg.color_g, cfg.color_b)
        self._state = STATE_IDLE
        self._prev_state = STATE_IDLE
        self._transition = 1.0
        self._audio_level = 0.0
        self._target_level = 0.0
        self._phase = 0.0

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)

        self.resize(cfg.width, cfg.height)
        self._position_bottom_center()

        self.sig_state.connect(self._on_state)
        self.sig_level.connect(self._on_level)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(33)
        self._timer.start()

        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._ensure_on_top)
        self._raise_timer.setInterval(2000)
        self._raise_timer.start()

        self._trans_anim = QPropertyAnimation(self, b"transition")
        self._trans_anim.setDuration(420)
        self._trans_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.show()
        self.raise_()

    # ---- Property: progreso de transición (0=anterior, 1=actual) ----

    def get_transition(self) -> float:
        return self._transition

    def set_transition(self, v: float) -> None:
        self._transition = max(0.0, min(1.0, v))
        self.update()

    transition = Property(float, get_transition, set_transition)

    # ---- Posicionamiento ----

    def _position_bottom_center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - self.cfg.margin_bottom
        self.move(x, y)

    # ---- Slots de daemon ----

    def _on_state(self, new_state: str) -> None:
        if new_state not in _ALL_STATES or new_state == self._state:
            return
        self._prev_state = self._state
        self._state = new_state
        if new_state == STATE_IDLE:
            self._target_level = 0.0
        self._trans_anim.stop()
        self.set_transition(0.0)
        self._trans_anim.setStartValue(0.0)
        self._trans_anim.setEndValue(1.0)
        self._trans_anim.start()

    def _on_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        self._phase += 0.06
        self._audio_level = self._audio_level * 0.6 + self._target_level * 0.4
        self.update()

    def _ensure_on_top(self) -> None:
        if not self.isVisible():
            self.show()
        self._position_bottom_center()
        self.raise_()

    # ---- Mouse ----

    def mousePressEvent(self, event):
        if self._state == STATE_IDLE:
            self.sig_menu_requested.emit()
        event.accept()

    # ---- Pintado ----

    @staticmethod
    def _a(base: int, mul: float) -> int:
        return max(0, min(255, int(base * mul)))

    def _color(self, base: int, mul: float) -> QColor:
        return QColor(self._fg[0], self._fg[1], self._fg[2], self._a(base, mul))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()

        # SIN FONDO. Sólo iconos.
        t = self._transition

        if t < 1.0 and self._prev_state != self._state:
            # Estado anterior: encoge hacia el centro y se desvanece.
            self._draw_morphed(p, rect, self._prev_state, scale=1.0 - t, alpha=1.0 - t)
            # Estado nuevo: emerge desde el centro creciendo y apareciendo.
            self._draw_morphed(p, rect, self._state, scale=t, alpha=t)
        else:
            # Sin transición — estado actual a tamaño completo.
            self._draw_morphed(p, rect, self._state, scale=1.0, alpha=1.0)

    def _draw_morphed(
        self, p: QPainter, rect: QRectF, state: str, scale: float, alpha: float
    ) -> None:
        if alpha <= 0.01 or scale <= 0.01:
            return
        p.save()
        cx = rect.width() / 2
        cy = rect.height() / 2
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)
        if state == STATE_IDLE:
            self._draw_idle(p, rect, alpha)
        elif state == STATE_RECORDING:
            self._draw_recording(p, rect, alpha)
        elif state == STATE_THINKING:
            self._draw_thinking(p, rect, alpha)
        elif state == STATE_SPEAKING:
            self._draw_speaking(p, rect, alpha)
        p.restore()

    # --- IDLE: una raya centrada con micro-respiración ---
    def _draw_idle(self, p: QPainter, rect: QRectF, alpha: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        w = 36 + 4 * math.sin(self._phase * 1.2)
        h = 2.5
        breathe = 0.5 + 0.5 * math.sin(self._phase * 0.7)
        a = int(180 + 60 * breathe)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color(a, alpha))
        p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), h / 2, h / 2)

    # --- RECORDING: micro centrado que pulsa con el audio ---
    def _draw_recording(self, p: QPainter, rect: QRectF, alpha: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        # Escala global con el nivel de audio (efecto pulse).
        pulse = 1.0 + 0.25 * self._audio_level
        mic_w = 9 * pulse
        mic_h = 13 * pulse

        color = self._color(255, alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        # Cápsula del mic
        p.drawRoundedRect(
            QRectF(cx - mic_w / 2, cy - mic_h / 2 - 1, mic_w, mic_h),
            mic_w / 2, mic_w / 2,
        )
        # Arco U alrededor
        p.setPen(QPen(color, 1.4))
        p.setBrush(Qt.NoBrush)
        arc_w = mic_w + 8
        arc_h = mic_h
        p.drawArc(
            QRectF(cx - arc_w / 2, cy - 1, arc_w, arc_h - 1),
            200 * 16, 140 * 16,
        )
        # Tallo y base
        p.setPen(QPen(color, 1.4))
        stem_y0 = cy + mic_h / 2 - 1
        stem_y1 = cy + mic_h / 2 + 4
        p.drawLine(QPointF(cx, stem_y0), QPointF(cx, stem_y1))
        p.drawLine(QPointF(cx - 4, stem_y1), QPointF(cx + 4, stem_y1))

    # --- THINKING: 3 puntos rebotando ---
    def _draw_thinking(self, p: QPainter, rect: QRectF, alpha: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        p.setPen(Qt.NoPen)
        spacing = 12
        for i in range(3):
            t = self._phase * 3 - i * 0.5
            y_off = -abs(math.sin(t)) * 5
            a = int(180 + 75 * abs(math.sin(t)))
            p.setBrush(self._color(a, alpha))
            x = cx - spacing + i * spacing
            r = 3.0 + abs(math.sin(t)) * 0.8
            p.drawEllipse(QPointF(x, cy + y_off), r, r)

    # --- SPEAKING: 8 barras en envelope gaussiano ---
    def _draw_speaking(self, p: QPainter, rect: QRectF, alpha: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        p.setPen(Qt.NoPen)
        n = 9
        bar_w = 2.6
        spacing = 6.5
        start_x = cx - (n - 1) * spacing / 2
        for i in range(n):
            x = start_x + i * spacing
            d = (i - n / 2) / (n / 2)
            envelope = math.exp(-d * d * 1.8)
            phase = self._phase * 6 + i * 0.4
            h = max(3, (3 + 13 * envelope) * (0.55 + 0.45 * math.sin(phase)))
            p.setBrush(self._color(240, alpha))
            p.drawRoundedRect(QRectF(x - bar_w / 2, cy - h / 2, bar_w, h), 1.3, 1.3)


def create_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app
