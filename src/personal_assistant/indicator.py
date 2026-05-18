"""Overlay flotante con idle bar siempre visible + transiciones morfantes.

La barra vive en bottom-center y nunca se oculta. Cambia de forma cuando el
asistente pasa de estado: idle (barrita fina) → recording (mic + audio bars)
→ thinking (3 puntos) → speaking (onda) → idle.

Las transiciones se cross-fadean con easing InOutCubic. El bg de la píldora
también se interpola: muy translúcido en idle, opaco en estados activos.
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
        self._state = STATE_IDLE
        self._prev_state = STATE_IDLE
        self._transition = 1.0  # 1.0 = totalmente en el estado actual
        self._audio_level = 0.0
        self._target_level = 0.0
        self._phase = 0.0

        # Ventana siempre visible, sin foco, encima de todo.
        # OJO: NO usamos WA_TransparentForMouseEvents → queremos clicks para abrir menú.
        # X11Bypass + Tool + StaysOnTop = el WM no lo reordena ni añade decoración.
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

        # Slots thread-safe (auto-queued cross-thread)
        self.sig_state.connect(self._on_state)
        self.sig_level.connect(self._on_level)

        # Ticker animación 30 fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(33)
        self._timer.start()

        # Re-raise periódico: algunos compositores nos pierden el always-on-top
        # cuando lanzan una ventana fullscreen o cambian de workspace.
        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._ensure_on_top)
        self._raise_timer.setInterval(2000)
        self._raise_timer.start()

        # Animación de transición entre estados
        self._trans_anim = QPropertyAnimation(self, b"transition")
        self._trans_anim.setDuration(380)
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
        # Cuando volvemos a idle, dejamos que el nivel se desvanezca solo
        if new_state == STATE_IDLE:
            self._target_level = 0.0
        self._trans_anim.stop()
        self.set_transition(0.0)
        self._trans_anim.setStartValue(0.0)
        self._trans_anim.setEndValue(1.0)
        self._trans_anim.start()

    def _on_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, level))

    def _ensure_on_top(self) -> None:
        """Reposiciona y eleva la ventana periódicamente."""
        if not self.isVisible():
            self.show()
        self._position_bottom_center()
        self.raise_()

    def _tick(self) -> None:
        self._phase += 0.06
        self._audio_level = self._audio_level * 0.6 + self._target_level * 0.4
        self.update()

    # ---- Mouse ----

    def mousePressEvent(self, event):
        # Cualquier botón abre el menú. Sólo dispara cuando estamos en idle
        # para no interrumpir grabación/conversación.
        if self._state == STATE_IDLE:
            self.sig_menu_requested.emit()
        event.accept()

    # ---- Pintado ----

    def _bg_alpha_for(self, state: str) -> int:
        return 60 if state == STATE_IDLE else 235

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        radius = rect.height() / 2

        # Fondo píldora: alpha interpolado entre estado anterior y actual
        t = self._transition
        prev_a = self._bg_alpha_for(self._prev_state)
        curr_a = self._bg_alpha_for(self._state)
        bg_alpha = int(prev_a + (curr_a - prev_a) * t)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 18, 22, bg_alpha))
        p.drawRoundedRect(rect, radius, radius)
        p.setPen(QPen(QColor(255, 255, 255, max(8, bg_alpha // 9)), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, rect.width() - 1, rect.height() - 1),
            radius - 0.5, radius - 0.5,
        )

        # Dos capas: estado anterior (fade out) + estado actual (fade in)
        if t < 1.0 and self._prev_state != self._state:
            self._draw_state(p, rect, self._prev_state, 1.0 - t)
        self._draw_state(p, rect, self._state, t if self._prev_state != self._state else 1.0)

    def _draw_state(self, p: QPainter, rect: QRectF, state: str, alpha_mul: float) -> None:
        if alpha_mul <= 0.01:
            return
        if state == STATE_IDLE:
            self._draw_idle(p, rect, alpha_mul)
        elif state == STATE_RECORDING:
            self._draw_recording(p, rect, alpha_mul)
        elif state == STATE_THINKING:
            self._draw_thinking(p, rect, alpha_mul)
        elif state == STATE_SPEAKING:
            self._draw_speaking(p, rect, alpha_mul)

    @staticmethod
    def _a(base: int, mul: float) -> int:
        return max(0, min(255, int(base * mul)))

    # --- IDLE: barrita fina centrada con un sutil shimmer ---
    def _draw_idle(self, p: QPainter, rect: QRectF, mul: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        # shimmer suave: el ancho oscila ligeramente
        w_base = 64
        w = w_base + 8 * math.sin(self._phase * 1.2)
        h = 3
        # alpha también respira un poco
        breathe = 0.5 + 0.5 * math.sin(self._phase * 0.7)
        a = int(120 + 50 * breathe)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(220, 220, 230, self._a(a, mul)))
        p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), h / 2, h / 2)

    # --- RECORDING: mic a la izquierda + barras reactivas ---
    def _draw_recording(self, p: QPainter, rect: QRectF, mul: float) -> None:
        h = rect.height()
        cx = h * 0.6
        cy = h / 2
        mic_color = QColor(255, 90, 90, self._a(255, mul))
        p.setPen(Qt.NoPen)
        p.setBrush(mic_color)
        mic_w, mic_h = 14, 22
        p.drawRoundedRect(QRectF(cx - mic_w / 2, cy - mic_h / 2 - 2, mic_w, mic_h), 7, 7)
        p.setPen(QPen(mic_color, 2))
        p.drawArc(QRectF(cx - 11, cy - 4, 22, 18), 200 * 16, 140 * 16)
        p.drawLine(int(cx), int(cy + 13), int(cx), int(cy + 19))
        p.drawLine(int(cx - 6), int(cy + 19), int(cx + 6), int(cy + 19))

        # Pulso reactivo al audio
        pulse_r = 18 + self._audio_level * 14
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 90, 90, self._a(int(40 + 60 * self._audio_level), mul)))
        p.drawEllipse(QPointF(cx, cy), pulse_r, pulse_r)

        # Barras audio-reactivas a la derecha
        p.setBrush(QColor(255, 130, 130, self._a(255, mul)))
        n = 14
        start_x = h * 1.2
        end_x = rect.width() - h * 0.4
        spacing = (end_x - start_x) / (n - 1)
        for i in range(n):
            x = start_x + i * spacing
            phase = self._phase * 4 + i * 0.55
            base = 6 + 10 * self._audio_level
            wave = max(4, base + 14 * self._audio_level * (0.5 + 0.5 * math.sin(phase)))
            p.drawRoundedRect(QRectF(x - 2, cy - wave / 2, 4, wave), 2, 2)

    # --- THINKING: 3 puntos rebotando ---
    def _draw_thinking(self, p: QPainter, rect: QRectF, mul: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        p.setPen(Qt.NoPen)
        for i in range(3):
            t = self._phase * 3 - i * 0.5
            y_off = -abs(math.sin(t)) * 10
            alpha = int(180 + 75 * abs(math.sin(t)))
            p.setBrush(QColor(255, 200, 80, self._a(alpha, mul)))
            x = cx - 26 + i * 26
            r = 6 + abs(math.sin(t)) * 1.5
            p.drawEllipse(QPointF(x, cy + y_off), r, r)

    # --- SPEAKING: onda simétrica centrada ---
    def _draw_speaking(self, p: QPainter, rect: QRectF, mul: float) -> None:
        cx = rect.width() / 2
        cy = rect.height() / 2
        p.setPen(Qt.NoPen)
        n = 22
        bar_w = 4
        spacing = 9
        start_x = cx - (n - 1) * spacing / 2
        for i in range(n):
            x = start_x + i * spacing
            d = (i - n / 2) / (n / 2)
            envelope = math.exp(-d * d * 1.8)
            phase = self._phase * 6 + i * 0.35
            wave_h = max(4, (8 + 22 * envelope) * (0.55 + 0.45 * math.sin(phase)))
            p.setBrush(QColor(120, 220, 160, self._a(240, mul)))
            p.drawRoundedRect(QRectF(x - bar_w / 2, cy - wave_h / 2, bar_w, wave_h), 2, 2)


def create_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app
