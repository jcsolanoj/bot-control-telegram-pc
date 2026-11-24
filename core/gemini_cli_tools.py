"""
Integración con `gemini-api` CLI para dotar al bot de Telegram de:
1. Respuestas en audio hablado (Text-to-Speech via `gemini-api tts` + conversión opcional a OGG voz).
2. Transcripción profesional de archivos de audio y video (`gemini-api transcribe` a md/text/srt).
3. Investigación profunda con fuentes primarias (`gemini-api agent run --agent deep-research-preview-04-2026`).
"""

import os
import re
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("GeminiCliTools")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _find_gemini_api_exe() -> str:
    exe = shutil.which("gemini-api")
    if exe:
        return exe
    candidates = [
        os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "bin", "gemini-api.exe"),
        os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "bin", "gemini-api.cmd"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "gemini-api", "gemini-api.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def _run_cli(cmd: list, timeout: int = 120) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        creationflags=NO_WINDOW_FLAG,
    )


def generar_audio_tts(
    texto: str,
    voz: str = "Kore",
    estilo: str = "",
    idioma: str = "es-419",
) -> tuple:
    """Genera un archivo de audio hablado (.ogg si ffmpeg está disponible, sino .wav) usando `gemini-api tts`.
    Retorna (ruta_archivo_o_None, mensaje_estado).
    """
    exe = _find_gemini_api_exe()
    if not exe:
        return None, "[ERROR: No se encontró el CLI 'gemini-api' en esta PC.]"

    clean_text = (texto or "").strip()
    if not clean_text:
        return None, "[ERROR: El texto para generar audio está vacío.]"

    out_dir = Path(BASE_DIR) / "temp" / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    wav_path = out_dir / f"respuesta_voz_{ts}.wav"

    cmd = [
        exe, "tts", clean_text,
        "--voice", (voz or "Kore").strip(),
        "--language", (idioma or "es-419").strip(),
        "--out", str(wav_path),
    ]
    if estilo and estilo.strip():
        cmd.extend(["--style", estilo.strip()])

    try:
        res = _run_cli(cmd, timeout=90)
        if res.returncode != 0:
            err_msg = (res.stderr or res.stdout or "").strip()
            return None, f"[ERROR generando audio TTS (Código {res.returncode})]: {err_msg[-600:]}"

        actual_wav = wav_path
        if not actual_wav.exists() and res.stdout:
            cand = Path(res.stdout.strip().splitlines()[-1].strip())
            if cand.exists():
                actual_wav = cand

        if not actual_wav.exists():
            return None, "[ERROR: gemini-api tts terminó sin generar el archivo de audio.]"

        # Convertir a .ogg OPUS para que Telegram lo muestre como nota de voz nativa si ffmpeg está instalado
        ffmpeg_exe = shutil.which("ffmpeg")
        if ffmpeg_exe:
            ogg_path = actual_wav.with_suffix(".ogg")
            conv = _run_cli(
                [ffmpeg_exe, "-y", "-i", str(actual_wav), "-c:a", "libopus", "-b:a", "48k", str(ogg_path)],
                timeout=30,
            )
            if conv.returncode == 0 and ogg_path.exists():
                try:
                    actual_wav.unlink()
                except Exception:
                    pass
                return str(ogg_path), "Audio generado con éxito."

        return str(actual_wav), "Audio generado con éxito."
    except Exception as e:
        return None, f"[ERROR ejecutando gemini-api tts: {e}]"


def transcribir_archivo_multimedia(
    ruta_archivo: str,
    formato: str = "md",
    incluir_hablantes: bool = True,
) -> tuple:
    """Transcribe un archivo de audio o video usando `gemini-api transcribe` (sube primero si >14 MB).
    Retorna (ruta_transcripcion_o_None, texto_o_error).
    """
    exe = _find_gemini_api_exe()
    if not exe:
        return None, "[ERROR: No se encontró el CLI 'gemini-api' en esta PC.]"

    src = Path((ruta_archivo or "").strip().strip('"'))
    if not src.is_file():
        return None, f"[ERROR: No se encontró el archivo multimedia en '{src}'.]"

    fmt = (formato or "md").strip().lower()
    if fmt not in {"md", "text", "json", "srt"}:
        fmt = "md"

    out_dir = Path(BASE_DIR) / "temp" / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "txt" if fmt == "text" else fmt
    out_file = out_dir / f"{src.stem}_transcripcion_{int(time.time())}.{ext}"

    try:
        input_ref = str(src)
        size_mb = src.stat().st_size / (1024 * 1024)
        if size_mb > 13.5:
            logger.info(f"Archivo de {size_mb:.1f} MB; subiendo primero via gemini-api files upload...")
            up_res = _run_cli([exe, "files", "upload", str(src), "--wait"], timeout=300)
            if up_res.returncode != 0:
                return None, f"[ERROR subiendo archivo grande: {(up_res.stderr or up_res.stdout)[-500:]}]"
            uri_match = re.search(r"(files/[A-Za-z0-9_-]+)", up_res.stdout or "")
            if not uri_match:
                return None, f"[ERROR: No se obtuvo URI files/<id> tras subir {src.name}.]"
            input_ref = uri_match.group(1)

        cmd = [exe, "transcribe", "-i", input_ref, "--format", fmt, "--out", str(out_file)]
        if not incluir_hablantes:
            cmd.append("--no-speakers")

        res = _run_cli(cmd, timeout=300)
        if res.returncode != 0:
            err_msg = (res.stderr or res.stdout or "").strip()
            return None, f"[ERROR transcribiendo (Código {res.returncode})]: {err_msg[-800:]}"

        actual_out = out_file
        if not actual_out.exists() and res.stdout:
            cand = Path(res.stdout.strip().splitlines()[-1].strip())
            if cand.exists():
                actual_out = cand

        if not actual_out.exists():
            return None, "[ERROR: gemini-api transcribe finalizó sin generar archivo de salida.]"

        preview = actual_out.read_text(encoding="utf-8", errors="replace")[:1800]
        return str(actual_out), preview
    except Exception as e:
        return None, f"[ERROR ejecutando gemini-api transcribe: {e}]"


def ejecutar_investigacion_profunda(tema: str, timeout_segundos: int = 480) -> tuple:
    """Lanza Deep Research (`deep-research-preview-04-2026`) en segundo plano y espera el informe final.
    Retorna (ruta_informe_md_o_None, texto_resumen_o_error).
    """
    exe = _find_gemini_api_exe()
    if not exe:
        return None, "[ERROR: No se encontró el CLI 'gemini-api' en esta PC.]"

    prompt = (tema or "").strip()
    if not prompt:
        return None, "[ERROR: Indica el tema o pregunta para la investigación profunda.]"

    try:
        start_cmd = [
            exe, "agent", "run", prompt,
            "--agent", "deep-research-preview-04-2026",
            "--background",
            "-o", "json",
        ]
        res = _run_cli(start_cmd, timeout=45)
        if res.returncode != 0:
            return None, f"[ERROR iniciando Deep Research: {(res.stderr or res.stdout)[-600:]}]"

        run_id = None
        try:
            payload = json.loads(res.stdout)
            run_id = payload.get("id")
        except Exception:
            m = re.search(r'"id"\s*:\s*"([^"]+)"', res.stdout or "")
            if m:
                run_id = m.group(1)

        if not run_id:
            return None, f"[ERROR: No se pudo obtener el ID de ejecución de Deep Research. Salida: {res.stdout[:400]}]"

        deadline = time.time() + max(60, int(timeout_segundos))
        final_data = None
        last_status = "unknown"

        while time.time() < deadline:
            time.sleep(10)
            st_res = _run_cli([exe, "agent", "status", run_id, "-o", "json"], timeout=30)
            if st_res.returncode != 0:
                continue
            try:
                st_json = json.loads(st_res.stdout)
                last_status = st_json.get("status", "unknown")
                if last_status == "completed":
                    final_data = st_json
                    break
                if last_status in {"failed", "cancelled", "incomplete", "budget_exceeded"}:
                    return None, f"[ERROR: Deep Research terminó con estado '{last_status}'.]"
            except Exception:
                continue

        if not final_data:
            return None, f"[TIEMPO AGOTADO: Deep Research ({run_id}) sigue en estado '{last_status}' tras {timeout_segundos}s.]"

        chunks = []
        for step in final_data.get("steps", []):
            if step.get("type") == "model_output":
                for item in step.get("content", []):
                    if item.get("type") == "text" and item.get("text"):
                        chunks.append(item["text"])
        full_report = "\n".join(chunks).strip()
        if not full_report:
            full_report = json.dumps(final_data, indent=2, ensure_ascii=False)

        out_dir = Path(BASE_DIR) / "temp" / "research"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", prompt[:40]).strip("_") or "informe"
        md_path = out_dir / f"deep_research_{slug}_{int(time.time())}.md"
        md_path.write_text(f"# Investigación Profunda: {prompt}\n\n{full_report}", encoding="utf-8")

        return str(md_path), full_report
    except Exception as e:
        return None, f"[ERROR ejecutando Deep Research: {e}]"
