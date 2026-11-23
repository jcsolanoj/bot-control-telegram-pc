"""
Bot de Telegram conectado al Agente General Autónomo (Antigravity Core).
Permite delegar tareas reales en la computadora desde Telegram:
- Manipulación, edición y envío de documentos (Google Drive, OneDrive, etc.)
- Navegación web en Google Chrome con sesiones activas
- Formato limpio sin símbolos feos de markdown (#, **)
- Búsqueda y envío de archivos a Telegram
- Ejecución de código y comandos del sistema
- Notas de voz y lenguaje natural fluido
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    os.chdir(BASE_DIR)
except Exception:
    pass

import re
import asyncio
import datetime
import ctypes

# Asegurar soporte de caracteres y streams válidos en pythonw / sin consola
try:
    if sys.stdout is None:
        sys.stdout = open(os.path.join(BASE_DIR, "bot_stdout.log"), "a", encoding="utf-8", buffering=1)
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if sys.stderr is None:
        sys.stderr = open(os.path.join(BASE_DIR, "bot_stderr.log"), "a", encoding="utf-8", buffering=1)
    elif hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if sys.stdin is None:
        import io
        sys.stdin = io.StringIO()
except Exception:
    pass

import logging
from io import BytesIO
from dotenv import load_dotenv

load_dotenv(os.path.join(BASE_DIR, ".env"))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from agent_engine import AgentEngine, firmar_documento_pdf, ejecutar_accion_confirmada, PENDING_CONFIRMATIONS
from agent_executor import cancel_running_tasks
from memory_manager import resumir_memoria_personal
from telegram_formatter import clean_markdown_for_telegram, split_long_message, strip_all_markdown

# Configurar logs tanto en consola (si existe) como en archivo persistente
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
handlers = [logging.FileHandler(log_file, encoding="utf-8", mode="a")]
if sys.stdout is not None:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=handlers,
    force=True
)
logger = logging.getLogger("AntigravityTelegramBot")

# Cargar variables de entorno desde la ruta absoluta de la carpeta del script
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=dotenv_path)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID_RAW = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()

if not BOT_TOKEN:
    logger.critical("Error: TELEGRAM_BOT_TOKEN no configurado en .env")
    sys.exit(1)

ALLOWED_USER_ID = int(ALLOWED_USER_ID_RAW) if ALLOWED_USER_ID_RAW.isdigit() else None
if ALLOWED_USER_ID is None:
    logger.critical("Error de seguridad: TELEGRAM_ALLOWED_USER_ID no configurado en .env o inválido. Abortando arranque.")
    sys.exit(1)

agent = AgentEngine()

# Rastreo de la tarea en curso para permitir abortar / cancelar
CURRENT_RUNNING_TASK = None
# Rastreo de PDFs pendientes de PIN por usuario {user_id: pdf_path}
PENDING_PDFS = {}
# Rastreo de confirmaciones de acciones sensibles pendientes por usuario {user_id: action_id}
PENDING_USER_CONFIRM = {}


def is_authorized(user_id: int) -> bool:
    """Verifica si el usuario que escribe es el dueño autorizado (fail-closed)."""
    if ALLOWED_USER_ID is None:
        return False
    return user_id == ALLOWED_USER_ID


async def send_clean_message(update: Update, text: str):
    """Envía mensajes formateados en HTML limpio sin símbolos de markdown rotos."""
    formatted = clean_markdown_for_telegram(text)
    chunks = split_long_message(formatted)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"Error parseando HTML en Telegram ({e}), enviando texto limpio...")
            # Fallback seguro sin etiquetas ni markdown suelto
            plain = strip_all_markdown(chunk)
            await update.message.reply_text(plain)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start para saludar e informar de las capacidades del agente."""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("⛔ Acceso no autorizado.")
        return

    welcome_msg = (
        "👋 <b>¡Hola! Tu Agente Autónomo Antigravity está listo.</b>\n\n"
        "Opero con <b>Gemini 4 Hydrogen</b>, herramientas locales y Antigravity CLI en tu computadora:\n\n"
        "  • 🚀 <b>Antigravity CLI (agy):</b> Desarrollo, refactorización, scripts y edición con memoria persistente.\n"
        "  • 📌 <b>Gestión de Proyectos:</b> Soporte para proyectos aislados o modo libre general.\n"
        "  • 🌐 <b>Navegación Web:</b> Consulta portales, extrae datos y toma capturas en segundo plano.\n"
        "  • 📄 <b>Archivos y Firma PDF:</b> Búsqueda en Drive/OneDrive y firma electrónica criptográfica.\n"
        "  • ⚡ <b>Control del Sistema:</b> Estado de batería, CPU, RAM, capturas y confirmación de acciones críticas.\n\n"
        "<b>Comandos útiles:</b>\n"
        "  • /memoria: Ver todo lo que el asistente recuerda sobre ti.\n"
        "  • /proyecto: Ver o cambiar el proyecto activo de trabajo.\n"
        "  • /cancelar o /stop: Aborta cualquier tarea en curso al instante.\n\n"
        "Puedes escribirme, enviar PDFs o enviarme notas de voz 🎙️ libremente."
    )
    await update.message.reply_text(welcome_msg, parse_mode=ParseMode.HTML)


async def proyecto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite ver, fijar o cambiar el proyecto activo de Antigravity."""
    user = update.effective_user
    if not is_authorized(user.id):
        return

    import project_manager
    args = context.args

    if not args:
        active = project_manager.get_active_project()
        recent_projs = project_manager.list_projects(limit=8)

        active_status = "🟢 <b>Proyecto Activo:</b> "
        if active.get("key") == "general":
            active_status += "<b>Modo Libre (Sin proyecto fijo)</b>\n"
        else:
            active_status += f"<b>{active.get('name')}</b> (<code>{active.get('key')}</code>)\n"
        active_status += f"📁 <i>{active.get('directory', '')}</i>\n"
        active_status += f"🔄 <i>Turnos acumulados:</i> {active.get('turns_count', 0)}/20"

        lines = [
            active_status,
            "\n📌 <b>Tus Proyectos Reales de Antigravity (Más Recientes):</b>"
        ]

        for p in recent_projs:
            date_part = f" <i>({p['last_active'][:10]})</i>" if p.get("last_active") else ""
            mark = "👉 " if p.get("is_active") else "• "
            lines.append(f"{mark}<b>{p['name']}</b>{date_part}\n   Seleccionar: <code>/proyecto {p['key']}</code>")

        lines.append("\n💡 <b>Comandos Rápidos:</b>")
        lines.append("  • <code>/proyecto &lt;nombre&gt;</code> (ej. <code>/proyecto rubricas</code> o <code>/proyecto eerssa</code>)")
        lines.append("  • <code>/proyecto libre</code> para volver al Modo Libre general.")
        lines.append("  • <code>/proyectos todos</code> para ver la lista completa de proyectos registrados.")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    first_arg = args[0].strip().lower()
    if first_arg == "todos":
        all_projs = project_manager.list_projects(limit=0, show_all=True)
        lines = ["📚 <b>Todos tus Proyectos de Antigravity en esta PC:</b>\n"]
        for p in all_projs:
            date_part = f" <i>({p['last_active'][:10]})</i>" if p.get("last_active") else ""
            lines.append(f"• <b>{p['name']}</b>{date_part} → <code>/proyecto {p['key']}</code>")
        lines.append("\n💡 Usa <code>/proyecto &lt;clave&gt;</code> para activar cualquiera de ellos.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    target = " ".join(args).strip().lower()
    success = project_manager.set_active_project(target)
    if success:
        active = project_manager.get_active_project()
        if active.get("key") == "general":
            await update.message.reply_text(
                "🌐 <b>Modo Libre Activado.</b>\nLas siguientes órdenes se ejecutarán de forma general en tu sistema sin vincularse a un proyecto específico.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"✅ <b>Proyecto seleccionado:</b> <b>{active.get('name')}</b>\n"
                f"📁 <i>{active.get('directory')}</i>\n\n"
                f"Antigravity CLI (agy) operará en este directorio con memoria persistente propia para este proyecto.",
                parse_mode=ParseMode.HTML
            )
    else:
        await update.message.reply_text(
            f"❌ No se encontró ningún proyecto con el nombre o clave '<code>{target}</code>'.\n"
            f"Escribe <code>/proyecto</code> para ver tus proyectos más recientes.",
            parse_mode=ParseMode.HTML
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /cancelar o /stop para abortar cualquier tarea pesada en ejecución inmediatamente."""
    user = update.effective_user
    if not is_authorized(user.id):
        return

    global CURRENT_RUNNING_TASK
    cancel_running_tasks()
    
    if CURRENT_RUNNING_TASK and not CURRENT_RUNNING_TASK.done():
        CURRENT_RUNNING_TASK.cancel()
        CURRENT_RUNNING_TASK = None
        await update.message.reply_text("🛑 <b>Misión abortada con éxito.</b> He detenido todos los procesos y el agente está listo para tu siguiente orden.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("ℹ️ No había ninguna tarea activa ejecutándose. El asistente está libre y escuchando.")


async def run_with_typing(update: Update, func, *args):
    """
    Ejecuta el motor del agente en un hilo secundario (thread pool) para:
    1. No bloquear el bucle de eventos asyncio de Telegram.
    2. Permitir que Playwright Sync API funcione sin conflicto con asyncio.
    3. Mantener vivo el indicador 'Escribiendo...' cada 4 segundos mientras piensa/ejecuta.
    """
    stop_event = asyncio.Event()

    async def keep_typing():
        while not stop_event.is_set():
            try:
                await update.message.reply_chat_action(ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    typing_task = asyncio.create_task(keep_typing())
    try:
        prevent_sleep()
        return await asyncio.to_thread(func, *args)
    finally:
        stop_event.set()
        try:
            await typing_task
        except Exception:
            pass


async def send_attached_files(update: Update, files_to_send: list):
    """Envía archivos adjuntos generados o localizados por el agente con vista previa visual para imágenes."""
    for file_path in files_to_send:
        if os.path.exists(file_path):
            file_name = os.path.basename(file_path)
            is_image = file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            try:
                if is_image and size_mb < 10:
                    try:
                        await update.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
                    except Exception:
                        pass
                    with open(file_path, "rb") as photo_doc:
                        await update.message.reply_photo(
                            photo=photo_doc,
                            caption=f"📷 <code>{file_name}</code>",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    try:
                        await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
                    except Exception:
                        pass
                    with open(file_path, "rb") as doc:
                        await update.message.reply_document(
                            document=doc,
                            filename=file_name,
                            caption=f"📎 <code>{file_name}</code>",
                            parse_mode=ParseMode.HTML
                        )
            except Exception as e:
                logger.error(f"Error enviando archivo {file_name}: {e}")
                await update.message.reply_text(f"⚠️ Error enviando {file_name}: {e}")


async def memoria_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /memoria para consultar todo lo que el bot recuerda sobre el usuario."""
    user = update.effective_user
    if not is_authorized(user.id):
        return
    await update.message.reply_text(resumir_memoria_personal(), parse_mode=ParseMode.HTML)


async def send_confirmation_prompt(update: Update, user_id: int, pending_conf: dict):
    """Envía botones de confirmación para una acción sensible."""
    if not pending_conf:
        return
    action_id = pending_conf["id"]
    PENDING_USER_CONFIRM[user_id] = action_id
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sí, confirmar", callback_data=f"confirm:{action_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel_conf:{action_id}"),
        ]
    ])
    await update.message.reply_text(
        f"⚠️ <b>Confirmación requerida:</b> {pending_conf['titulo']}\n"
        f"• {pending_conf['resumen']}\n\n"
        f"<i>Pulsa un botón o responde \"sí\" / \"no\".</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa clics en botones de confirmación de acciones sensibles."""
    query = update.callback_query
    if not query or not query.from_user or not is_authorized(query.from_user.id):
        return
    await query.answer()

    data = query.data or ""
    user_id = query.from_user.id
    if data.startswith("confirm:"):
        action_id = data.split(":", 1)[1]
        PENDING_USER_CONFIRM.pop(user_id, None)
        res = await asyncio.to_thread(ejecutar_accion_confirmada, action_id)
        await query.edit_message_text(f"✅ <b>Acción confirmada:</b>\n{res}", parse_mode=ParseMode.HTML)
    elif data.startswith("cancel_conf:"):
        action_id = data.split(":", 1)[1]
        PENDING_CONFIRMATIONS.pop(action_id, None)
        PENDING_USER_CONFIRM.pop(user_id, None)
        await query.edit_message_text("❎ <b>Acción cancelada.</b> No se realizó ningún cambio.", parse_mode=ParseMode.HTML)


def _parse_pin_and_search(text: str):
    """Extrae un PIN de 4 dígitos y un texto de búsqueda opcional de un mensaje o caption."""
    if not text:
        return None, ""
    match = re.search(r"\b(\d{4})\b", text)
    if not match:
        return None, text.strip()
    pin = match.group(1)
    remainder = (text[:match.start()] + " " + text[match.end():]).strip()
    remainder = re.sub(
        r"^(?:(?:pin|firma|firmar|fírmalo|firmalo|con|el|la|en|sobre|texto|buscar|por|favor|pf|pls)\b[\s:,-]*)+",
        "",
        remainder,
        flags=re.IGNORECASE,
    ).strip()
    return pin, remainder


async def _sign_and_deliver_pdf(update: Update, pdf_path: str, pin: str, search_text: str = "") -> bool:
    """Ejecuta firmar-pdf localmente y envía el archivo -signed.pdf al chat de Telegram."""
    try:
        await update.message.reply_text("✍️ Firmando electrónicamente tu documento...")
    except Exception:
        pass

    result_msg = await run_with_typing(
        update,
        firmar_documento_pdf,
        pdf_path,
        pin,
        search_text,
        "bottom-right",
        "last"
    )

    if "ENVIAR_ARCHIVO:" in result_msg:
        signed_files = []
        clean_lines = []
        for line in result_msg.splitlines():
            if line.startswith("ENVIAR_ARCHIVO:"):
                path_cand = line.split("ENVIAR_ARCHIVO:", 1)[1].strip()
                if os.path.exists(path_cand):
                    signed_files.append(path_cand)
            else:
                clean_lines.append(line)
        summary = "\n".join(clean_lines).strip() or "✅ Documento firmado electrónicamente."
        await update.message.reply_text(f"✅ <b>{summary}</b>", parse_mode=ParseMode.HTML)
        await send_attached_files(update, signed_files)
        return True

    await update.message.reply_text(f"❌ No se pudo firmar el PDF:\n<code>{result_msg}</code>", parse_mode=ParseMode.HTML)
    return False


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe archivos enviados desde Telegram (PDFs para firma inmediata o documentos generales)."""
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    if not is_authorized(user.id):
        return

    doc = update.message.document
    if not doc:
        return

    orig_name = doc.file_name or f"documento_{int(datetime.datetime.now().timestamp())}"
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", orig_name)
    inbox_dir = os.path.join(BASE_DIR, "temp", "inbox")
    os.makedirs(inbox_dir, exist_ok=True)
    local_path = os.path.join(inbox_dir, safe_name)

    try:
        tg_file = await context.bot.get_file(doc.file_id, read_timeout=60, connect_timeout=30)
        await tg_file.download_to_drive(custom_path=local_path, read_timeout=60, connect_timeout=30)
    except Exception as e:
        logger.error(f"Error descargando documento {orig_name}: {e}")
        await update.message.reply_text(f"⚠️ No pude descargar el archivo <code>{orig_name}</code>: {e}", parse_mode=ParseMode.HTML)
        return

    caption = (update.message.caption or "").strip()
    is_pdf = safe_name.lower().endswith(".pdf") or (doc.mime_type == "application/pdf")

    if is_pdf:
        pin, remainder = _parse_pin_and_search(caption)
        if pin and not remainder:
            PENDING_PDFS.pop(user.id, None)
            await _sign_and_deliver_pdf(update, local_path, pin, "")
        elif pin and remainder:
            PENDING_PDFS.pop(user.id, None)
            prompt = (
                f"El usuario acaba de enviar el PDF '{local_path}' con la instrucción: '{caption}'. "
                f"Fírmalo inmediatamente usando firmar_documento_pdf respetando el PIN, página, posición o texto de búsqueda indicados."
            )
            result = await run_with_typing(update, agent.run_task, prompt)
            await send_clean_message(update, result.get("text", "Documento procesado."))
            await send_attached_files(update, result.get("files", []))
        else:
            PENDING_PDFS[user.id] = local_path
            await update.message.reply_text(
                f"📄 PDF recibido: <code>{safe_name}</code>\n"
                f"🔐 Envíame tu <b>PIN de 4 dígitos</b> por texto o audio para firmarlo (ej. <code>1234</code>).\n"
                f"<i>También puedes decirme dónde colocarla, ej: \"1234 en la página 1 arriba a la izquierda\" o \"1234 sobre Firma\".</i>",
                parse_mode=ParseMode.HTML
            )
        return

    # Otros archivos (Word, Excel, etc.): pasarlos al agente autónomo
    prompt = f"El usuario envió el archivo '{local_path}' con la instrucción: '{caption or 'Analiza o confirma recepción de este archivo.'}'."
    try:
        result = await run_with_typing(update, agent.run_task, prompt)
        await send_clean_message(update, result.get("text", "Archivo recibido."))
        await send_attached_files(update, result.get("files", []))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error procesando archivo: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja mensajes de texto ejecutando el agente autónomo con soporte para abortar."""
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    if not is_authorized(user.id):
        return

    text = update.message.text
    if not text:
        return

    # Si el usuario escribe palabras clave de abortar en lenguaje natural
    trigger_abort = text.strip().lower() in ["cancelar", "cancela", "stop", "para", "detener", "detén", "deten", "abortar", "aborta", "alto"]
    if trigger_abort:
        PENDING_PDFS.pop(user.id, None)
        await cancel_command(update, context)
        return

    # Si hay una acción sensible esperando confirmación por texto ("sí" / "no")
    if user.id in PENDING_USER_CONFIRM:
        low_txt = text.strip().lower()
        action_id = PENDING_USER_CONFIRM.get(user.id)
        if low_txt in ("si", "sí", "confirma", "confirmar", "dale", "ok", "hazlo", "procede", "yes"):
            PENDING_USER_CONFIRM.pop(user.id, None)
            res = await asyncio.to_thread(ejecutar_accion_confirmada, action_id)
            await update.message.reply_text(f"✅ <b>Acción confirmada:</b>\n{res}", parse_mode=ParseMode.HTML)
            return
        elif low_txt in ("no", "cancelar", "cancela", "abortar"):
            PENDING_CONFIRMATIONS.pop(action_id, None)
            PENDING_USER_CONFIRM.pop(user.id, None)
            await update.message.reply_text("❎ <b>Acción cancelada.</b> No se realizó ningún cambio.", parse_mode=ParseMode.HTML)
            return

    # Si hay un PDF pendiente esperando su PIN de firma
    if user.id in PENDING_PDFS and os.path.exists(PENDING_PDFS[user.id]):
        pin, remainder = _parse_pin_and_search(text)
        pending_path = PENDING_PDFS[user.id]
        if pin and not remainder:
            signed_ok = await _sign_and_deliver_pdf(update, pending_path, pin, "")
            if signed_ok:
                PENDING_PDFS.pop(user.id, None)
            return
        elif pin and remainder:
            prompt = (
                f"El usuario tiene el PDF pendiente '{pending_path}' y ahora dio la instrucción: '{text}'. "
                f"Fírmalo inmediatamente usando firmar_documento_pdf respetando exactamente el PIN, página, posición o texto de búsqueda."
            )
            result = await run_with_typing(update, agent.run_task, prompt)
            await send_clean_message(update, result.get("text", "Documento procesado."))
            files_out = result.get("files", [])
            await send_attached_files(update, files_out)
            if any(f.lower().endswith("-signed.pdf") for f in files_out):
                PENDING_PDFS.pop(user.id, None)
            return

    global CURRENT_RUNNING_TASK
    logger.info(f"Orden recibida de {user.id}: {text[:80]}")
    try:
        CURRENT_RUNNING_TASK = asyncio.current_task()
        result = await run_with_typing(update, agent.run_task, text)
        reply_text = result.get("text", "Tarea procesada.")
        pending_conf = result.get("pending_confirmation")
        if pending_conf:
            await send_confirmation_prompt(update, user.id, pending_conf)
        else:
            await send_clean_message(update, reply_text)
        await send_attached_files(update, result.get("files", []))
    except asyncio.CancelledError:
        logger.info("Tarea cancelada explícitamente por el usuario.")
    except Exception as e:
        logger.exception(f"Error inesperado procesando mensaje de texto: {e}")
        await update.message.reply_text(
            f"⚠️ Ocurrió un error procesando tu orden: {e}\nPor favor intenta de nuevo."
        )
    finally:
        CURRENT_RUNNING_TASK = None


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja notas de voz transcribiéndolas y ejecutando el agente autónomo."""
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    if not is_authorized(user.id):
        return

    voice = update.message.voice
    if not voice:
        return

    logger.info(f"Nota de voz recibida de {user.id}")
    try:
        try:
            await update.message.reply_chat_action(ChatAction.RECORD_VOICE)
        except Exception:
            pass

        audio_bytes = None
        last_dl_err = None
        for attempt in range(3):
            try:
                file = await context.bot.get_file(voice.file_id, read_timeout=60, connect_timeout=30)
                audio_buffer = BytesIO()
                await file.download_to_memory(audio_buffer, read_timeout=60, connect_timeout=30)
                audio_bytes = audio_buffer.getvalue()
                if audio_bytes:
                    break
            except Exception as dl_e:
                last_dl_err = dl_e
                logger.warning(f"Reintento {attempt + 1}/3 descargando nota de voz de Telegram ({dl_e})...")
                await asyncio.sleep(1.5)

        if not audio_bytes:
            raise RuntimeError(f"No se pudo descargar el audio desde los servidores de Telegram ({last_dl_err})")

        CURRENT_RUNNING_TASK = asyncio.current_task()
        extra_ctx = ""
        if user.id in PENDING_PDFS and os.path.exists(PENDING_PDFS[user.id]):
            extra_ctx = (
                f"CONTEXTO ACTIVO: El usuario envió previamente el PDF '{PENDING_PDFS[user.id]}' y espera que lo firmes "
                f"con firmar_documento_pdf usando el PIN, página, posición o texto de búsqueda que indique en este audio."
            )
        result = await run_with_typing(update, agent.process_voice_and_run, audio_bytes, "audio/ogg", extra_ctx)
        transcription = result.get("transcription", "")

        if transcription and transcription != "(Error de audio)":
            await update.message.reply_text(f"🎙️ <i>\"{transcription}\"</i>", parse_mode=ParseMode.HTML)

        reply_text = result.get("text", "Tarea procesada.")
        pending_conf = result.get("pending_confirmation")
        if pending_conf:
            await send_confirmation_prompt(update, user.id, pending_conf)
        else:
            await send_clean_message(update, reply_text)
        files_out = result.get("files", [])
        await send_attached_files(update, files_out)
        if any(f.lower().endswith("-signed.pdf") for f in files_out):
            PENDING_PDFS.pop(user.id, None)
    except asyncio.CancelledError:
        logger.info("Tarea de voz cancelada explícitamente por el usuario.")
    except Exception as e:
        logger.exception(f"Error inesperado procesando nota de voz: {e}")
        await update.message.reply_text(
            f"⚠️ Ocurrió un error procesando tu nota de voz: {e}\nPor favor intenta de nuevo."
        )
    finally:
        CURRENT_RUNNING_TASK = None


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Manejador global de errores de python-telegram-bot."""
    logger.error("Excepción capturada en el manejador global de Telegram:", exc_info=context.error)


def log_print(*args, **kwargs):
    """Imprime en consola solo si hay consola disponible (python.exe)."""
    if sys.stdout is not None:
        try:
            print(*args, **kwargs)
        except Exception:
            pass


def prevent_sleep():
    """
    Indica a Windows que mantenga la CPU y la red activas en segundo plano (Away Mode / S0 Low Power Idle),
    incluso si la pantalla se apaga, la PC se bloquea o entra en suspensión Modern Standby.
    A ojos de cualquier persona externa, la laptop parece 100% apagada/dormida, pero el bot sigue escuchando.
    """
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        )
        logger.info("Modo continuo en suspensión (Away Mode / S0) activado en Windows.")
    except Exception as e:
        logger.warning(f"No se pudo establecer SetThreadExecutionState: {e}")


def main():
    """Inicia el bot de Telegram."""
    prevent_sleep()
    log_print("=" * 60)
    log_print("🚀 Iniciando Agente Autónomo Antigravity para Telegram...")
    log_print(f"🔒 Usuario autorizado: {ALLOWED_USER_ID}")
    log_print("=" * 60)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .pool_timeout(30.0)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("memoria", memoria_command))
    app.add_handler(CommandHandler("proyecto", proyecto_command))
    app.add_handler(CommandHandler("proyectos", proyecto_command))
    app.add_handler(CommandHandler("cancelar", cancel_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("stop", cancel_command))
    app.add_handler(CommandHandler("detener", cancel_command))
    app.add_handler(CommandHandler("abortar", cancel_command))
    app.add_handler(CallbackQueryHandler(handle_confirmation_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(global_error_handler)

    log_print("✅ Agente Autónomo en línea. Escuchando órdenes desde Telegram.")
    app.run_polling()


if __name__ == "__main__":
    while True:
        try:
            main()
        except KeyboardInterrupt:
            logger.info("Bot detenido manualmente por el usuario.")
            break
        except Exception as e:
            import traceback
            import time
            crash_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")
            try:
                with open(crash_file, "a", encoding="utf-8") as f:
                    f.write(f"\n--- ERROR TEMPORAL {datetime.datetime.now()} ---\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            logger.error(f"Error o desconexión en bot ({e}). Reintentando conexión en 10 segundos...")
            time.sleep(10)
