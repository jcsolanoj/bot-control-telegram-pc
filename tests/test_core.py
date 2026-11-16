"""Pruebas unitarias para bot-control-telegram-pc."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

CORE_DIR = str(Path(__file__).resolve().parent.parent / "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from telegram_formatter import clean_markdown_for_telegram, split_long_message, strip_all_markdown
from memory_manager import get_default_profile
from project_manager import make_clean_slug


def test_telegram_formatter_preserves_code_and_escapes_html():
    raw = "## Título\n- item **negrita**\nCódigo: `2**3 + a < b`"
    out = clean_markdown_for_telegram(raw)
    assert "<b>Título</b>" in out
    assert "• item <b>negrita</b>" in out
    assert "<code>2**3 + a &lt; b</code>" in out
    assert strip_all_markdown("<b>Hola</b> **mundo**") == "Hola mundo"


def test_split_long_message():
    long_text = "\n\n".join(["Párrafo " + ("x" * 200) for _ in range(30)])
    chunks = split_long_message(long_text, max_length=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


def test_default_profile_has_no_personal_pii(monkeypatch):
    monkeypatch.setenv("USER_NAME", "Tester")
    profile = get_default_profile()
    assert profile["usuario"]["nombre"] == "Tester"
    assert profile["usuario"]["institucion"] == ""


def test_project_slug_generation():
    assert make_clean_slug("Mi Proyecto de Prueba") == "mi_proyecto_prueba"


def test_is_safe_attachment_path(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "12345")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")
    from agent_engine import _is_safe_attachment_path

    assert _is_safe_attachment_path(os.path.join(CORE_DIR, ".env")) is False
    assert _is_safe_attachment_path(os.path.join(CORE_DIR, "bot.py")) is False
    assert _is_safe_attachment_path(os.path.join(CORE_DIR, "temp", "captura.png")) is True
    assert _is_safe_attachment_path(os.path.expanduser("~/Documents/archivo.pdf")) is True
