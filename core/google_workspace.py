"""
Módulo de Integración con Google Workspace (Gmail, Google Calendar, Google Drive)
para el Asistente Autónomo de Telegram.

Requisitos de configuración (una sola vez por usuario):
1. Descargar el archivo OAuth Desktop `credentials_google.json` desde Google Cloud Console
   (APIs habilitadas: Gmail API, Google Calendar API, Google Drive API).
2. Colocar `credentials_google.json` en la carpeta del bot (`core/` o raíz del bot).
3. Ejecutar `python google_workspace.py --auth` para autorizar en el navegador y generar `token_google.json`.
"""

import os
import sys
import base64
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

logger = logging.getLogger("GoogleWorkspace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials_google.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token_google.json")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_google_credentials():
    """Carga o refresca credenciales OAuth2 locales de Google Workspace."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None, (
            "Faltan librerías de Google Workspace. Ejecuta: "
            "pip install google-api-python-client google-auth-oauthlib"
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
        if not os.path.exists(CREDENTIALS_FILE):
            return None, (
                "Google Workspace aún no está vinculado en esta PC. "
                "Para activarlo: coloca tu archivo OAuth `credentials_google.json` en la carpeta del bot "
                "y ejecuta `python google_workspace.py --auth` una sola vez en tu PC."
            )
        return None, (
            "Tu sesión de Google Workspace expiró o falta autorizarla. "
            "Ejecuta `python google_workspace.py --auth` en tu PC para generar `token_google.json`."
        )

    return creds, None


def run_interactive_auth():
    """Inicia flujo OAuth interactivo en navegador para generar token_google.json."""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[ERROR] No se encontró {CREDENTIALS_FILE}.")
        print("Descarga tus credenciales OAuth 2.0 (Aplicación de escritorio) desde Google Cloud Console")
        print("y guárdalas con el nombre 'credentials_google.json' en esta carpeta.")
        return False

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    print(f"[OK] Google Workspace autorizado correctamente. Token guardado en {TOKEN_FILE}")
    return True


def consultar_calendario(dias: int = 7) -> str:
    """Consulta los próximos eventos en Google Calendar."""
    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=max(1, min(int(dias), 60)))

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        if not events:
            return f"No tienes eventos agendados en Google Calendar para los próximos {dias} días."

        lines = [f"📅 Eventos de Google Calendar (próximos {dias} días):"]
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
    descripcion: str = ""
) -> str:
    """Crea un evento en Google Calendar."""
    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        start_dt = datetime.fromisoformat(fecha_inicio_iso.strip().replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            # Asumir hora local de Ecuador/UTC-5 si no viene zona horaria
            start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=-5)))
        end_dt = start_dt + timedelta(minutes=max(15, int(duracion_minutos)))

        event_body = {
            "summary": titulo.strip(),
            "description": descripcion.strip(),
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        link = created.get("htmlLink", "")
        return f"✅ Evento creado en Google Calendar: '{titulo}' para {start_dt.strftime('%Y-%m-%d %H:%M')}\n🔗 {link}"
    except Exception as e:
        return f"[ERROR creando evento en Google Calendar: {e}]"


def leer_correos_gmail(limite: int = 5, solo_no_leidos: bool = True, filtro: str = "") -> str:
    """Lee mensajes recientes de Gmail."""
    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"

    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        query_parts = []
        if solo_no_leidos:
            query_parts.append("is:unread")
        if filtro and filtro.strip():
            query_parts.append(filtro.strip())
        q = " ".join(query_parts)

        results = (
            service.users()
            .messages()
            .list(userId="me", q=q, maxResults=max(1, min(int(limite), 15)))
            .execute()
        )
        messages = results.get("messages", [])
        if not messages:
            return "No se encontraron correos en Gmail con ese criterio."

        lines = [f"📧 Correos en Gmail ({len(messages)}):"]
        for m in messages:
            msg = service.users().messages().get(userId="me", id=m["id"], format="metadata",
                                                 metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "Desconocido")
            subject = headers.get("Subject", "(Sin asunto)")
            snippet = msg.get("snippet", "")[:140]
            lines.append(f"• De: {sender}\n  Asunto: {subject}\n  Resumen: {snippet}")
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR leyendo Gmail: {e}]"


def enviar_correo_gmail(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Envía un correo electrónico usando Gmail API."""
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


def buscar_drive_nube(consulta: str, limite: int = 8) -> str:
    """Busca archivos directamente en Google Drive (nube)."""
    creds, err = _get_google_credentials()
    if err:
        return f"[INFO GOOGLE WORKSPACE] {err}"

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        safe_q = consulta.replace("'", "\\'")
        q = f"name contains '{safe_q}' and trashed = false"
        results = (
            service.files()
            .list(q=q, pageSize=max(1, min(int(limite), 20)),
                  fields="files(id, name, mimeType, modifiedTime, webViewLink)")
            .execute()
        )
        files = results.get("files", [])
        if not files:
            return f"No se encontraron archivos en la nube de Google Drive que coincidan con '{consulta}'."

        lines = [f"☁️ Archivos encontrados en Google Drive ({len(files)}):"]
        for f in files:
            mod = f.get("modifiedTime", "")[:10]
            link = f.get("webViewLink", "")
            lines.append(f"• {f.get('name')} ({mod})\n  🔗 {link}")
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR buscando en Google Drive: {e}]"


if __name__ == "__main__":
    if "--auth" in sys.argv:
        run_interactive_auth()
    else:
        print("Uso: python google_workspace.py --auth")
