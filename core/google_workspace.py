"""
Módulo de Integración con Google Workspace (Gmail, Google Calendar, Google Drive,
Google Tasks, Google Sheets y Google Docs) para el Asistente Autónomo de Telegram.

Soporta dos modos automáticos (sin intervención del usuario):
1. Modo prioritario: CLI oficial `@googleworkspace/cli` (`gws`) si está instalado y autenticado.
2. Respaldo clásico: OAuth Desktop local con `credentials_google.json` + `token_google.json`.
"""

import os
import re
import sys
import json
import base64
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

logger = logging.getLogger("GoogleWorkspace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials_google.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token_google.json")
NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _resolve_gws_cmd() -> list:
    """Localiza `gws` y resuelve `[node.exe, run.js]` en Windows para evitar que `cmd.exe` rompa JSON."""
    exe = shutil.which("gws")
    if not exe:
        for cand in (
            r"C:\nvm4w\nodejs\gws.cmd",
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "gws.cmd"),
            r"C:\Program Files\nodejs\gws.cmd",
        ):
            if os.path.exists(cand):
                exe = cand
                break
    if not exe:
        return []

    low = exe.lower()
    if low.endswith((".cmd", ".bat", ".ps1")):
        base_dir = os.path.dirname(exe)
        run_js = os.path.join(base_dir, "node_modules", "@googleworkspace", "cli", "run.js")
        if os.path.exists(run_js):
            node_exe = os.path.join(base_dir, "node.exe")
            if not os.path.exists(node_exe):
                node_exe = shutil.which("node") or "node"
            return [node_exe, run_js]

    return [exe]


def _run_gws(args: list, timeout: int = 45) -> tuple:
    """Ejecuta `gws` con argumentos dados y devuelve (ok, parsed_json_or_text, err_text)."""
    base_cmd = _resolve_gws_cmd()
    if not base_cmd:
        return False, None, "CLI gws no encontrado"

    cmd = base_cmd + args
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW_FLAG,
        )
        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()

        if res.returncode != 0:
            return False, None, (stderr or stdout or f"Error gws código {res.returncode}")[-800:]

        # gws puede anteponer 'Using keyring backend: keyring'; extraer JSON desde el primer { o [
        idx_obj = stdout.find("{")
        idx_arr = stdout.find("[")
        starts = [i for i in (idx_obj, idx_arr) if i >= 0]
        if starts:
            candidate = stdout[min(starts):]
            try:
                return True, json.loads(candidate), ""
            except Exception:
                pass
        return True, stdout, ""
    except Exception as e:
        return False, None, str(e)


def _gws_available() -> bool:
    return bool(_resolve_gws_cmd())


def _get_google_credentials():
    """Carga o refresca credenciales OAuth2 locales clásicas (fallback si no hay gws)."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None, (
            "Faltan librerías de Google Workspace. Instala `gws` (`npm i -g @googleworkspace/cli`) "
            "o ejecuta `pip install google-api-python-client google-auth-oauthlib`."
        )

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.warning(f"Error leyendo token_google.json: {e}")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        except Exception as e:
            logger.warning(f"No se pudo refrescar token_google.json: {e}")
            creds = None

    if not creds or not creds.valid:
        return None, (
            "Google Workspace no está autenticado. "
            "Ejecuta `gws auth login` en tu PC (recomendado) o coloca `credentials_google.json` y ejecuta `python google_workspace.py --auth`."
        )

    return creds, None


def run_interactive_auth():
    """Inicia flujo OAuth interactivo clásico en navegador para generar token_google.json."""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[ERROR] No se encontró {CREDENTIALS_FILE}.")
        return False

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    print(f"[OK] Google Workspace autorizado correctamente. Token guardado en {TOKEN_FILE}")
    return True


# =============================================================================
# GOOGLE CALENDAR
# =============================================================================

def consultar_calendario(dias: int = 7) -> str:
    """Consulta los próximos eventos en Google Calendar (vía gws o API Python)."""
    dias_clean = max(1, min(int(dias or 7), 60))

    if _gws_available():
        ok, data, err = _run_gws(["calendar", "+agenda", "--days", str(dias_clean), "--format", "json"])
        if ok:
            events = data.get("events", data) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not events:
                return f"No tienes eventos agendados en Google Calendar para los próximos {dias_clean} días."
            lines = [f"📅 Eventos de Google Calendar (próximos {dias_clean} días):"]
            for ev in events[:25]:
                if not isinstance(ev, dict):
                    continue
                start = ev.get("start") or ""
                if isinstance(start, dict):
                    start = start.get("dateTime") or start.get("date") or ""
                summary = ev.get("summary") or ev.get("title") or "(Sin título)"
                loc = ev.get("location") or ""
                loc_str = f" | 📍 {loc}" if loc else ""
                lines.append(f"• {str(start)[:16].replace('T', ' ')} — {summary}{loc_str}")
            return "\n".join(lines)
        logger.warning(f"gws calendar +agenda falló ({err}); intentando respaldo OAuth...")

    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=dias_clean)
        events_result = (
            service.events()
            .list(calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
                  maxResults=20, singleEvents=True, orderBy="startTime")
            .execute()
        )
        events = events_result.get("items", [])
        if not events:
            return f"No tienes eventos agendados en Google Calendar para los próximos {dias_clean} días."
        lines = [f"📅 Eventos de Google Calendar (próximos {dias_clean} días):"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            summary = ev.get("summary", "(Sin título)")
            loc = ev.get("location", "")
            loc_str = f" | 📍 {loc}" if loc else ""
            lines.append(f"• {start[:16].replace('T', ' ')} — {summary}{loc_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR consultando Google Calendar: {e}]"


def crear_evento_calendario(
    titulo: str,
    fecha_inicio_iso: str,
    duracion_minutos: int = 60,
    descripcion: str = "",
    con_meet: bool = False,
) -> str:
    """Crea un evento en Google Calendar (soporta enlace de Google Meet vía gws)."""
    try:
        start_dt = datetime.fromisoformat(fecha_inicio_iso.strip().replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=-5)))
        end_dt = start_dt + timedelta(minutes=max(15, int(duracion_minutos or 60)))
    except Exception as e:
        return f"[ERROR: Formato de fecha inválido '{fecha_inicio_iso}'. Usa ISO 8601 (ej. 2026-11-26T10:00:00-05:00): {e}]"

    if _gws_available():
        cmd = [
            "calendar", "+insert",
            "--summary", titulo.strip(),
            "--start", start_dt.isoformat(),
            "--end", end_dt.isoformat(),
            "--format", "json",
        ]
        if descripcion and descripcion.strip():
            cmd.extend(["--description", descripcion.strip()])
        if con_meet:
            cmd.append("--meet")
        ok, data, err = _run_gws(cmd)
        if ok:
            link = data.get("htmlLink", "") if isinstance(data, dict) else ""
            meet_link = data.get("hangoutLink", "") if isinstance(data, dict) else ""
            extra = f"\n📹 Meet: {meet_link}" if meet_link else ""
            return f"✅ Evento creado en Google Calendar: '{titulo}' para {start_dt.strftime('%Y-%m-%d %H:%M')}\n🔗 {link}{extra}"
        return f"[ERROR creando evento con gws: {err}]"

    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"
    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        event_body = {
            "summary": titulo.strip(),
            "description": (descripcion or "").strip(),
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        return f"✅ Evento creado en Google Calendar: '{titulo}' para {start_dt.strftime('%Y-%m-%d %H:%M')}\n🔗 {created.get('htmlLink', '')}"
    except Exception as e:
        return f"[ERROR creando evento en Google Calendar: {e}]"


# =============================================================================
# GMAIL
# =============================================================================

def leer_correos_gmail(limite: int = 5, solo_no_leidos: bool = True, filtro: str = "") -> str:
    """Lee correos recientes de Gmail."""
    max_n = max(1, min(int(limite or 5), 15))
    query_parts = []
    if solo_no_leidos:
        query_parts.append("is:unread")
    if filtro and filtro.strip():
        query_parts.append(filtro.strip())
    q = " ".join(query_parts) or "in:inbox"

    if _gws_available():
        ok, data, err = _run_gws(["gmail", "+triage", "--max", str(max_n), "--query", q, "--format", "json"])
        if ok:
            msgs = data.get("messages", data) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not msgs:
                return "No se encontraron correos en Gmail con ese criterio."
            lines = [f"📧 Correos en Gmail ({len(msgs)}):"]
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                sender = m.get("from", "Desconocido")
                subject = m.get("subject", "(Sin asunto)")
                date_str = m.get("date", "")
                snippet = m.get("snippet", "")
                snip_line = f"\n  Resumen: {snippet[:140]}" if snippet else ""
                lines.append(f"• De: {sender}\n  Asunto: {subject} ({str(date_str)[:22]}){snip_line}")
            return "\n".join(lines)
        logger.warning(f"gws gmail +triage falló ({err}); intentando respaldo...")

    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"
    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        results = service.users().messages().list(userId="me", q=q, maxResults=max_n).execute()
        messages = results.get("messages", [])
        if not messages:
            return "No se encontraron correos en Gmail con ese criterio."
        lines = [f"📧 Correos en Gmail ({len(messages)}):"]
        for m in messages:
            msg = service.users().messages().get(userId="me", id=m["id"], format="metadata",
                                                 metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            lines.append(
                f"• De: {headers.get('From', 'Desconocido')}\n"
                f"  Asunto: {headers.get('Subject', '(Sin asunto)')}\n"
                f"  Resumen: {msg.get('snippet', '')[:140]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR leyendo Gmail: {e}]"


def enviar_correo_gmail(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    adjunto: str = "",
    borrador: bool = False,
) -> str:
    """Envía un correo (o guarda borrador) vía Gmail, con soporte de archivo adjunto."""
    if _gws_available():
        cmd = [
            "gmail", "+send",
            "--to", destinatario.strip(),
            "--subject", asunto.strip(),
            "--body", cuerpo,
            "--format", "json",
        ]
        if adjunto and os.path.isfile(adjunto.strip().strip('"')):
            cmd.extend(["-a", adjunto.strip().strip('"')])
        if borrador:
            cmd.append("--draft")
        ok, data, err = _run_gws(cmd, timeout=60)
        if ok:
            msg_id = data.get("id", "") if isinstance(data, dict) else ""
            verb = "Borrador guardado en Gmail" if borrador else "Correo enviado exitosamente por Gmail"
            return f"✅ {verb} para {destinatario} (ID: {msg_id})."
        return f"[ERROR enviando correo con gws: {err}]"

    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"
    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        message = MIMEText(cuerpo, "plain", "utf-8")
        message["to"] = destinatario.strip()
        message["subject"] = asunto.strip()
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"✅ Correo enviado exitosamente por Gmail a {destinatario} (ID: {sent.get('id')})."
    except Exception as e:
        return f"[ERROR enviando correo por Gmail: {e}]"


# =============================================================================
# GOOGLE DRIVE (Búsqueda y Descarga / Exportación a PDF)
# =============================================================================

def buscar_drive_nube(consulta: str, limite: int = 8) -> str:
    """Busca archivos directamente en la nube de Google Drive devolviendo nombre, ID y enlace."""
    max_n = max(1, min(int(limite or 8), 20))
    safe_q = (consulta or "").replace("'", "\\'").strip()
    q = f"name contains '{safe_q}' and trashed = false" if safe_q else "trashed = false"

    if _gws_available():
        params = json.dumps({
            "q": q,
            "pageSize": max_n,
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        })
        ok, data, err = _run_gws(["drive", "files", "list", "--params", params, "--format", "json"])
        if ok and isinstance(data, dict):
            files = data.get("files", [])
            if not files:
                return f"No se encontraron archivos en Google Drive que coincidan con '{consulta}'."
            lines = [f"☁️ Archivos encontrados en Google Drive ({len(files)}):"]
            for f in files:
                mod = str(f.get("modifiedTime", ""))[:10]
                lines.append(
                    f"• {f.get('name')} ({mod}) | ID: `{f.get('id')}`\n"
                    f"  Tipo: {f.get('mimeType', '')}\n"
                    f"  🔗 {f.get('webViewLink', '')}"
                )
            return "\n".join(lines)
        logger.warning(f"gws drive files list falló ({err}); intentando respaldo...")

    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        results = service.files().list(
            q=q, pageSize=max_n, fields="files(id, name, mimeType, modifiedTime, webViewLink)"
        ).execute()
        files = results.get("files", [])
        if not files:
            return f"No se encontraron archivos en la nube de Google Drive que coincidan con '{consulta}'."
        lines = [f"☁️ Archivos encontrados en Google Drive ({len(files)}):"]
        for f in files:
            lines.append(f"• {f.get('name')} ({f.get('modifiedTime', '')[:10]}) | ID: `{f.get('id')}`\n  🔗 {f.get('webViewLink', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR buscando en Google Drive: {e}]"


def descargar_archivo_drive(file_id: str, nombre_archivo: str = "", exportar_pdf: bool = False) -> tuple:
    """Descarga un archivo de Google Drive (o exporta un Google Doc/Sheet/Slide a PDF) a temp/drive/.
    Retorna (ruta_local_o_None, mensaje).
    """
    if not _gws_available():
        return None, "[ERROR: Se requiere el CLI 'gws' autenticado para descargar/exportar archivos de Drive.]"

    fid = (file_id or "").strip()
    if not fid:
        return None, "[ERROR: Debes indicar el file_id de Google Drive.]"

    ok_meta, meta, _ = _run_gws([
        "drive", "files", "get",
        "--params", json.dumps({"fileId": fid, "fields": "id,name,mimeType"}),
        "--format", "json",
    ])
    mime = meta.get("mimeType", "") if (ok_meta and isinstance(meta, dict)) else ""
    orig_name = (nombre_archivo or (meta.get("name", "") if isinstance(meta, dict) else "") or f"drive_{fid}").strip()
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", orig_name)

    out_dir = Path(BASE_DIR) / "temp" / "drive"
    out_dir.mkdir(parents=True, exist_ok=True)

    is_google_native = mime.startswith("application/vnd.google-apps.")
    if is_google_native or exportar_pdf:
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{Path(safe_name).stem}.pdf"
        out_path = out_dir / safe_name
        ok, _, err = _run_gws([
            "drive", "files", "export",
            "--params", json.dumps({"fileId": fid, "mimeType": "application/pdf"}),
            "--output", str(out_path),
        ], timeout=90)
    else:
        out_path = out_dir / safe_name
        ok, _, err = _run_gws([
            "drive", "files", "get",
            "--params", json.dumps({"fileId": fid, "alt": "media"}),
            "--output", str(out_path),
        ], timeout=90)

    if not ok or not out_path.exists():
        return None, f"[ERROR descargando archivo de Drive ({fid}): {err}]"

    return str(out_path), f"Archivo descargado desde Google Drive: {out_path.name}"


# =============================================================================
# GOOGLE TASKS
# =============================================================================

def listar_tareas_google(limite: int = 15) -> str:
    """Lista las tareas pendientes en Google Tasks (@default)."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` (`gws auth login`) para gestionar Google Tasks."

    params = json.dumps({
        "tasklist": "@default",
        "showCompleted": False,
        "maxResults": max(1, min(int(limite or 15), 50)),
    })
    ok, data, err = _run_gws(["tasks", "tasks", "list", "--params", params, "--format", "json"])
    if not ok:
        return f"[ERROR consultando Google Tasks: {err}]"

    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        return "✅ No tienes tareas pendientes en Google Tasks."

    lines = [f"☑️ Tareas pendientes en Google Tasks ({len(items)}):"]
    for t in items:
        title = t.get("title", "(Sin título)")
        due = str(t.get("due", ""))[:10]
        due_str = f" (vence: {due})" if due else ""
        notes = t.get("notes", "")
        notes_str = f"\n  Nota: {notes[:100]}" if notes else ""
        lines.append(f"• {title}{due_str}{notes_str}")
    return "\n".join(lines)


def crear_tarea_google(titulo: str, notas: str = "", fecha_limite_iso: str = "") -> str:
    """Crea una nueva tarea en Google Tasks (@default)."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` para crear tareas en Google Tasks."

    body = {"title": titulo.strip()}
    if notas and notas.strip():
        body["notes"] = notas.strip()
    if fecha_limite_iso and fecha_limite_iso.strip():
        due_raw = fecha_limite_iso.strip()
        if len(due_raw) == 10:
            due_raw += "T00:00:00Z"
        body["due"] = due_raw

    ok, _, err = _run_gws([
        "tasks", "tasks", "insert",
        "--params", json.dumps({"tasklist": "@default"}),
        "--json", json.dumps(body, ensure_ascii=False),
        "--format", "json",
    ])
    if not ok:
        return f"[ERROR creando tarea en Google Tasks: {err}]"
    return f"✅ Tarea creada en Google Tasks: '{titulo}'."


# =============================================================================
# GOOGLE SHEETS
# =============================================================================

def leer_hoja_sheets(spreadsheet_id: str, rango: str = "A1:Z30") -> str:
    """Lee celdas y valores de una hoja de Google Sheets."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` para leer Google Sheets."

    ok, data, err = _run_gws([
        "sheets", "+read",
        "--spreadsheet", spreadsheet_id.strip(),
        "--range", rango.strip(),
        "--format", "json",
    ])
    if not ok:
        return f"[ERROR leyendo Google Sheets: {err}]"

    values = data.get("values", data) if isinstance(data, dict) else data
    if not values:
        return "La hoja o rango especificado está vacío."
    if isinstance(values, list):
        lines = [f"📊 Datos de Google Sheets ({rango}):"]
        for row in values[:40]:
            if isinstance(row, list):
                lines.append(" | ".join(str(c) for c in row))
            else:
                lines.append(str(row))
        return "\n".join(lines)
    return str(values)[:3000]


def agregar_fila_sheets(spreadsheet_id: str, valores_csv: str) -> str:
    """Agrega una nueva fila al final de una hoja de Google Sheets (valores separados por comas)."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` para escribir en Google Sheets."

    ok, _, err = _run_gws([
        "sheets", "+append",
        "--spreadsheet", spreadsheet_id.strip(),
        "--values", valores_csv.strip(),
        "--format", "json",
    ])
    if not ok:
        return f"[ERROR agregando fila a Google Sheets: {err}]"
    return f"✅ Fila agregada exitosamente en Google Sheets (`{spreadsheet_id}`): {valores_csv}"


# =============================================================================
# GOOGLE DOCS
# =============================================================================

def leer_documento_docs(document_id: str) -> str:
    """Lee el texto completo de un documento de Google Docs por su ID."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` para leer Google Docs."

    ok, data, err = _run_gws([
        "docs", "documents", "get",
        "--params", json.dumps({"documentId": document_id.strip()}),
        "--format", "json",
    ])
    if not ok or not isinstance(data, dict):
        return f"[ERROR leyendo Google Docs: {err}]"

    title = data.get("title", "(Sin título)")
    body_content = data.get("body", {}).get("content", [])
    paragraphs = []
    for elem in body_content:
        para = elem.get("paragraph")
        if para:
            text_runs = [
                el.get("textRun", {}).get("content", "")
                for el in para.get("elements", [])
            ]
            line = "".join(text_runs).strip()
            if line:
                paragraphs.append(line)

    full_text = "\n".join(paragraphs)
    if len(full_text) > 3500:
        full_text = full_text[:3500] + "\n... [Documento truncado]"
    return f"📄 Google Doc: {title}\n\n{full_text or '(Documento vacío)'}"


def escribir_en_documento_docs(document_id: str, texto: str) -> str:
    """Agrega texto al final de un documento de Google Docs."""
    if not _gws_available():
        return "[INFO GOOGLE WORKSPACE] Instala y autentica `gws` para editar Google Docs."

    ok, _, err = _run_gws([
        "docs", "+write",
        "--document", document_id.strip(),
        "--text", texto,
        "--format", "json",
    ])
    if not ok:
        return f"[ERROR escribiendo en Google Docs: {err}]"
    return f"✅ Texto agregado correctamente al documento de Google Docs (`{document_id}`)."


if __name__ == "__main__":
    if "--auth" in sys.argv:
        run_interactive_auth()
    else:
        print("Cmd gws:", _resolve_gws_cmd() or "no encontrado")
