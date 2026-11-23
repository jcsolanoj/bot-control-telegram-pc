"""
Rastreador persistente de consumo de tokens y costo estimado (USD) por modelo Gemini.
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("UsageTracker")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USAGE_FILE = os.path.join(BASE_DIR, "usage_stats.json")

# Tarifas oficiales estimadas por 1M tokens (USD) en Paid Tier Standard
# (En Free Tier de AI Studio el cobro real es $0.00, pero se muestra el equivalente estimado)
MODEL_PRICING_PER_1M = {
    "gemini-4-hydrogen": (1.50, 7.50),
    "gemini-4-neon": (3.00, 15.00),
    "gemini-4-carbon": (2.00, 10.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-flash-lite-latest": (0.30, 2.50),
    "gemini-3.5-flash": (0.50, 3.00),
    "gemini-flash-latest": (0.50, 3.00),
}


def _get_rates(model_name: str) -> tuple:
    low = (model_name or "").lower()
    for key, rates in MODEL_PRICING_PER_1M.items():
        if key in low:
            return rates
    return (0.30, 2.50)


def _load_stats() -> dict:
    if not os.path.exists(USAGE_FILE):
        return {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "by_day": {},
            "by_model": {},
            "last_request": None,
        }
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "by_day": {},
            "by_model": {},
            "last_request": None,
        }


def _save_stats(data: dict):
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"No se pudo guardar usage_stats.json: {e}")


def registrar_consumo(model_name: str, usage_metadata) -> dict:
    """Registra el consumo de tokens de una llamada a Gemini."""
    if not usage_metadata:
        return {}

    in_tok = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
    cand_tok = int(getattr(usage_metadata, "candidates_token_count", 0) or 0)
    think_tok = int(getattr(usage_metadata, "thoughts_token_count", 0) or 0)
    out_tok = cand_tok + think_tok

    in_rate, out_rate = _get_rates(model_name)
    cost_usd = (in_tok / 1_000_000.0) * in_rate + (out_tok / 1_000_000.0) * out_rate

    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_stats()
    data["total_requests"] = int(data.get("total_requests", 0)) + 1
    data["total_input_tokens"] = int(data.get("total_input_tokens", 0)) + in_tok
    data["total_output_tokens"] = int(data.get("total_output_tokens", 0)) + out_tok
    data["total_cost_usd"] = float(data.get("total_cost_usd", 0.0)) + cost_usd

    day_rec = data.setdefault("by_day", {}).setdefault(
        today, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    day_rec["requests"] += 1
    day_rec["input_tokens"] += in_tok
    day_rec["output_tokens"] += out_tok
    day_rec["cost_usd"] += cost_usd

    # Mantener máximo últimos 30 días
    if len(data["by_day"]) > 30:
        for old_day in sorted(data["by_day"].keys())[:-30]:
            data["by_day"].pop(old_day, None)

    mod_rec = data.setdefault("by_model", {}).setdefault(
        model_name, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    mod_rec["requests"] += 1
    mod_rec["input_tokens"] += in_tok
    mod_rec["output_tokens"] += out_tok
    mod_rec["cost_usd"] += cost_usd

    last_rec = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model_name,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": cost_usd,
    }
    data["last_request"] = last_rec
    _save_stats(data)
    return last_rec


def obtener_resumen_consumo() -> str:
    """Devuelve un resumen limpio en HTML para Telegram con el consumo de hoy y acumulado."""
    data = _load_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    d = data.get("by_day", {}).get(
        today, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )

    lines = ["📊 <b>Consumo de API Gemini</b>\n"]
    lines.append(f"📅 <b>Hoy ({today}):</b>")
    lines.append(f"• Consultas: <b>{d['requests']}</b>")
    lines.append(f"• Tokens: <code>{d['input_tokens']:,}</code> entrada / <code>{d['output_tokens']:,}</code> salida")
    lines.append(f"• Costo est.: <b>${d['cost_usd']:.5f} USD</b>")

    last = data.get("last_request")
    if last:
        lines.append("\n⚡ <b>Última consulta:</b>")
        lines.append(f"• Modelo: <code>{last['model']}</code>")
        lines.append(
            f"• Tokens: <code>{last['input_tokens']:,}</code> in / <code>{last['output_tokens']:,}</code> out "
            f"(<b>${last['cost_usd']:.5f}</b>)"
        )

    lines.append("\n📈 <b>Acumulado histórico:</b>")
    lines.append(f"• Consultas totales: <b>{data.get('total_requests', 0)}</b>")
    lines.append(
        f"• Tokens totales: <code>{data.get('total_input_tokens', 0):,}</code> in / "
        f"<code>{data.get('total_output_tokens', 0):,}</code> out"
    )
    lines.append(f"• Costo est. acumulado: <b>${data.get('total_cost_usd', 0.0):.4f} USD</b>")
    lines.append("\n<i>Nota: Si usas el nivel gratuito de AI Studio, tu facturación real es $0.00.</i>")
    return "\n".join(lines)
