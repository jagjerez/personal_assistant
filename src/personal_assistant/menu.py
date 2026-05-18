"""Diálogo de configuración: idioma + selección de voz con demo."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .voices import (
    DEMO_TEXTS,
    Voice,
    download_voice,
    is_downloaded,
    voices_for_language,
)

log = logging.getLogger(__name__)


_LANG_LABELS = {
    "es": "Español",
    "en": "English",
}


class _VoiceJob(QObject):
    """Worker para descargar + demo en background sin congelar la UI."""
    finished = Signal(str, bool, str)  # voice_id, success, message

    def __init__(self, voice: Voice, demo_text: str, play_func: Callable):
        super().__init__()
        self.voice = voice
        self.demo_text = demo_text
        self.play_func = play_func

    @Slot()
    def run(self) -> None:
        try:
            if not is_downloaded(self.voice):
                download_voice(self.voice)
            self.play_func(self.demo_text, self.voice.id)
            self.finished.emit(self.voice.id, True, "")
        except Exception as e:
            log.exception("Error en demo de voz")
            self.finished.emit(self.voice.id, False, str(e))


class SettingsDialog(QDialog):
    """Diálogo de selección de idioma y voz."""

    def __init__(
        self,
        current_language: str,
        current_voice_id: str,
        play_demo: Callable[[str, str], None],
        on_save: Callable[[str, str], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Asistente — Idioma y voz")
        self.setMinimumSize(520, 460)
        self.play_demo = play_demo
        self.on_save = on_save
        self._current_lang = current_language
        self._current_voice_id = current_voice_id
        self._jobs: list[QThread] = []

        # Layout principal
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("Configuración del asistente")
        f = title.font(); f.setPointSize(14); f.setBold(True); title.setFont(f)
        root.addWidget(title)

        # Selector idioma
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Idioma de respuesta:"))
        self.lang_combo = QComboBox()
        for code, label in _LANG_LABELS.items():
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(
            max(0, list(_LANG_LABELS.keys()).index(current_language))
            if current_language in _LANG_LABELS else 0
        )
        self.lang_combo.currentIndexChanged.connect(self._refresh_voices)
        lang_row.addWidget(self.lang_combo, 1)
        root.addLayout(lang_row)

        # Línea separadora
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444")
        root.addWidget(sep)

        # Lista de voces
        root.addWidget(QLabel("Voces disponibles (clic en ▶ para escuchar demo):"))
        self.voice_list = QListWidget()
        self.voice_list.setSpacing(2)
        self.voice_list.setStyleSheet(
            "QListWidget::item { padding: 8px; } "
            "QListWidget::item:selected { background-color: #2c5282; }"
        )
        root.addWidget(self.voice_list, 1)

        # Status / mensaje
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-style: italic")
        root.addWidget(self.status_label)

        # Botones
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Guardar")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        self._refresh_voices()

    def _refresh_voices(self) -> None:
        lang = self.lang_combo.currentData()
        self.voice_list.clear()
        for v in voices_for_language(lang):
            self._add_voice_row(v)

    def _add_voice_row(self, voice: Voice) -> None:
        item = QListWidgetItem(self.voice_list)
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)

        gender_emoji = "♀" if voice.gender == "F" else "♂"
        downloaded = "✓" if is_downloaded(voice) else "↓"
        label = QLabel(f"{gender_emoji}  {voice.name}   [{downloaded}]")
        f = label.font(); f.setPointSize(10); label.setFont(f)
        row.addWidget(label, 1)

        demo_btn = QPushButton("▶")
        demo_btn.setFixedWidth(40)
        demo_btn.clicked.connect(lambda _, v=voice, b=demo_btn, l=label: self._play(v, b, l))
        row.addWidget(demo_btn)

        select_btn = QPushButton("Usar")
        select_btn.setFixedWidth(70)
        is_current = voice.id == self._current_voice_id
        if is_current:
            select_btn.setText("Actual")
            select_btn.setEnabled(False)
        select_btn.clicked.connect(lambda _, v=voice: self._select(v))
        row.addWidget(select_btn)

        item.setSizeHint(widget.sizeHint())
        self.voice_list.setItemWidget(item, widget)

    def _select(self, voice: Voice) -> None:
        self._current_voice_id = voice.id
        self.status_label.setText(f"Seleccionada: {voice.name}. Pulsa Guardar para aplicar.")
        self._refresh_voices()

    def _play(self, voice: Voice, btn: QPushButton, label: QLabel) -> None:
        btn.setEnabled(False)
        btn.setText("…")
        self.status_label.setText(
            f"Descargando {voice.name}..." if not is_downloaded(voice)
            else f"Sintetizando demo en {voice.name}..."
        )
        lang = self.lang_combo.currentData()
        demo_text = DEMO_TEXTS.get(lang, DEMO_TEXTS["en"])

        thread = QThread(self)
        worker = _VoiceJob(voice, demo_text, self.play_demo)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda vid, ok, msg: self._on_demo_done(btn, label, ok, msg))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._jobs.append(thread)

    def _on_demo_done(self, btn: QPushButton, label: QLabel, ok: bool, msg: str) -> None:
        btn.setEnabled(True)
        btn.setText("▶")
        if not ok:
            self.status_label.setText(f"Error: {msg[:80]}")
        else:
            self.status_label.setText("")
            self._refresh_voices()  # actualiza el ✓ si se acaba de descargar

    def _save(self) -> None:
        lang = self.lang_combo.currentData()
        try:
            self.on_save(lang, self._current_voice_id)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error guardando", str(e))
