"""
Motor de Agente Autónomo (Antigravity Core) para Telegram.
Implementa un bucle de agente completo (ReAct) con Automatic Function Calling (AFC)
utilizando el SDK oficial de Google GenAI (Gemini) y herramientas universales de sistema.
"""

import os
import sys
import time
import psutil
import ctypes
import datetime
import subprocess
import pyotp
import logging
from PIL import Image, ImageGrab
from dotenv import load_dotenv

from memory_manager import (
    formatear_contexto_memoria,
    registrar_turno,
    agregar_nota_perfil,
    actualizar_memoria_estructurada,
    olvidar_dato_memoria,
    resumir_memoria_personal,
    limpiar_historial_conversacion,
    obtener_actividad_reciente_antigravity
)
import google_workspace
import usage_tracker
import gemini_cli_tools

from google import genai
from google.genai import types

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(WORKSPACE_DIR, ".env"))
logger = logging.getLogger("AgentEngine")
NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
USER_HOME = os.path.expanduser("~")
CHROME_BOT_PROFILE = os.path.join(USER_HOME, ".gemini", "chrome_bot_profile")
CUSTOM_WORKSPACE = os.path.expanduser(os.environ.get("WORKSPACE_DIR", r"~\Documents"))

SEARCH_ROOTS = [
    os.path.join(USER_HOME, "Desktop"),
    os.path.join(USER_HOME, "Documents"),
    os.path.join(USER_HOME, "Downloads"),
]
if os.path.exists(CUSTOM_WORKSPACE) and CUSTOM_WORKSPACE not in SEARCH_ROOTS:
    SEARCH_ROOTS.append(CUSTOM_WORKSPACE)

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_EXE):
    CHROME_EXE = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_EXE):
    CHROME_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
if not os.path.exists(CHROME_EXE):
    CHROME_EXE = "chrome"

PORTALS_MAP = {
    "outlook": "https://outlook.office.com/mail/",
    "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "drive": "https://drive.google.com",
}

# Lista por turno para rastrear archivos adjuntos (capturas, descargas)
CURRENT_RUN_FILES = []
PENDING_CONFIRMATIONS = {}
CURRENT_PENDING_CONFIRMATION = None


def registrar_confirmacion_sensible(titulo: str, resumen: str, func, kwargs: dict) -> str:
    """Registra una acción sensible para pedir confirmación explícita al usuario en Telegram."""
    import uuid
    global CURRENT_PENDING_CONFIRMATION
    action_id = uuid.uuid4().hex[:8]
    entry = {
        "id": action_id,
        "titulo": titulo,
        "resumen": resumen,
        "func": func,
        "kwargs": kwargs,
    }
    PENDING_CONFIRMATIONS[action_id] = entry
    CURRENT_PENDING_CONFIRMATION = entry
    return (
        f"[CONFIRMACION_REQUERIDA:{action_id}] Esta acción requiere tu confirmación explícita: {resumen}. "
        f"Detente aquí y pide confirmación al usuario."
    )


def ejecutar_accion_confirmada(action_id: str) -> str:
    """Ejecuta una acción sensible previamente aprobada por el usuario."""
    entry = PENDING_CONFIRMATIONS.pop(action_id, None)
    if not entry:
        return "[ERROR: La confirmación expiró o ya fue procesada.]"
    kwargs = dict(entry["kwargs"])
    kwargs["confirmado"] = True
    return str(entry["func"](**kwargs))


def _is_safe_attachment_path(file_path: str) -> bool:
    """Bloquea el envío de secretos (.env, claves, sesiones) o código fuente interno del bot."""
    abs_path = os.path.abspath(file_path)
    low_name = os.path.basename(abs_path).lower()
    blocked_names = {
        ".env", "user_profile.json", "chat_history.json", "project_sessions.json",
        "credentials_google.json", "token_google.json",
    }
    blocked_exts = {".p12", ".pfx", ".pem", ".key"}
    if low_name in blocked_names or low_name.startswith(".env."):
        return False
    if os.path.splitext(low_name)[1] in blocked_exts:
        return False
    core_dir = os.path.abspath(WORKSPACE_DIR)
    allowed_core_subdirs = (
        os.path.abspath(os.path.join(WORKSPACE_DIR, "temp")) + os.sep,
        os.path.abspath(os.path.join(WORKSPACE_DIR, "descargas")) + os.sep,
    )
    if abs_path.startswith(core_dir + os.sep) and not abs_path.startswith(allowed_core_subdirs):
        return False
    return True


# =============================================================================
# HERRAMIENTAS UNIVERSALES DEL AGENTE (Tools expuestas a Gemini)
# =============================================================================

def navegar_y_extraer_web(url_o_portal: str) -> str:
    """
    Navega a cualquier página web o sitio usando Playwright con perfil persistente.
    Lee y extrae los títulos y textos principales, y genera una captura de pantalla para Telegram.

    Args:
        url_o_portal: Nombre corto (ej: 'github', 'drive') o URL web completa a visitar.
    """
    global CURRENT_RUN_FILES
    target_clean = url_o_portal.lower().strip()

    url = PORTALS_MAP.get(target_clean)
    if not url:
        for k, v in PORTALS_MAP.items():
            if k in target_clean or target_clean in k:
                url = v
                break
    if not url:
        if target_clean.startswith("http://") or target_clean.startswith("https://"):
            url = target_clean
        elif "." in target_clean and " " not in target_clean:
            url = f"https://{target_clean}"
        else:
            url = f"https://www.google.com/search?q={url_o_portal}"

    screenshot_path = os.path.join(WORKSPACE_DIR, "captura_navegacion.png")

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=CHROME_BOT_PROFILE,
                headless=True,
                channel="chrome",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.new_page()
            page.goto(url, timeout=40000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            title = page.title()

            # Tomar captura de pantalla de la página
            try:
                page.screenshot(path=screenshot_path)
                if os.path.exists(screenshot_path) and screenshot_path not in CURRENT_RUN_FILES:
                    CURRENT_RUN_FILES.append(screenshot_path)
            except Exception:
                pass

            body_text = page.inner_text("body")
            browser.close()

            # Limpiar texto
            lines = [l.strip() for l in body_text.splitlines() if l.strip()]
            snippet = "\n".join(lines[:60])
            if len(snippet) > 2500:
                snippet = snippet[:2500] + "... (contenido truncado)"

            return f"Navegación exitosa a {url}.\nTítulo de la página: '{title}'\n\nContenido extraído:\n{snippet}"
    except Exception as e:
        return f"Error navegando a {url}: {e}"


def interactuar_en_pagina_web(url_o_portal: str, selector_o_texto: str, accion: str = "click", texto_a_escribir: str = "") -> str:
    """
    Interactúa físicamente (hace clic en botones/enlaces o rellena formularios) en una página o portal institucional
    dentro de la sesión persistente, verificando el resultado con una captura de pantalla que se envía a Telegram.
    Usa esta herramienta cuando el usuario te pida hacer clic en botones como 'Iniciar Sesión', 'Consultar', etc.
    """
    global CURRENT_RUN_FILES
    try:
        from institutional_navigator import interactuar_en_portal
        res = interactuar_en_portal(url_o_portal, selector_o_texto, accion, texto_a_escribir)
        if res.get("screenshot") and res["screenshot"] not in CURRENT_RUN_FILES:
            CURRENT_RUN_FILES.append(res["screenshot"])
        if res.get("success"):
            return f"Acción realizada: {res.get('mensaje')}"
        else:
            return f"Aviso: {res.get('error')}"
    except Exception as e:
        return f"Error al interactuar con la página web: {e}"


def interactuar_y_descargar_web(url_o_portal: str, selector_o_texto_click: str) -> str:
    """
    Navega a un portal institucional o página web, hace clic en un botón o enlace específico
    y descarga el archivo generado (reporte, PDF, Excel), preparándolo para enviarlo a Telegram.
    """
    target_clean = url_o_portal.lower().strip()
    url = PORTALS_MAP.get(target_clean, url_o_portal)
    download_dir = os.path.join(WORKSPACE_DIR, "descargas")
    os.makedirs(download_dir, exist_ok=True)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=CHROME_BOT_PROFILE,
                headless=True,
                channel="chrome",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.new_page()
            page.goto(url, timeout=40000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            # Esperar descarga al hacer clic
            with page.expect_download(timeout=30000) as download_info:
                if selector_o_texto_click.startswith("//") or "[" in selector_o_texto_click:
                    page.click(selector_o_texto_click)
                else:
                    page.click(f"text='{selector_o_texto_click}'")

            download = download_info.value
            safe_filename = os.path.basename(download.suggested_filename) or f"descarga_{int(time.time())}"
            saved_path = os.path.abspath(os.path.join(download_dir, safe_filename))
            if not saved_path.startswith(os.path.abspath(download_dir) + os.sep):
                raise ValueError("Nombre de archivo de descarga inválido.")
            download.save_as(saved_path)
            if os.path.exists(saved_path) and saved_path not in CURRENT_RUN_FILES:
                CURRENT_RUN_FILES.append(saved_path)
            browser.close()

            return f"Descarga exitosa: '{safe_filename}' guardado en {saved_path}\nENVIAR_ARCHIVO: {saved_path}"
    except Exception as e:
        return f"Error al interactuar y descargar: {e}"


def abrir_en_chrome(url_o_portal: str) -> str:
    """
    Abre una pestaña en la pantalla física del monitor de la PC del usuario
    (usar SOLO si el usuario pide expresamente abrir una ventana para verla físicamente en su monitor).
    """
    target_clean = url_o_portal.lower().strip()
    url = PORTALS_MAP.get(target_clean)
    if not url:
        for k, v in PORTALS_MAP.items():
            if k in target_clean or target_clean in k:
                url = v
                break
    if not url:
        if target_clean.startswith("http://") or target_clean.startswith("https://"):
            url = target_clean
        elif "." in target_clean and " " not in target_clean:
            url = f"https://{target_clean}"
        else:
            url = f"https://www.google.com/search?q={url_o_portal}"

    try:
        subprocess.Popen([CHROME_EXE, url])
        try:
            bring_to_front_script = (
                "$wshell = New-Object -ComObject wscript.shell; "
                "$wshell.AppActivate('Google Chrome')"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", bring_to_front_script],
                timeout=5,
                creationflags=NO_WINDOW_FLAG
            )
        except Exception:
            pass

        return f"Pestaña abierta en el monitor de tu PC: {url}"
    except Exception as e:
        return f"Error abriendo Chrome: {e}"


def buscar_archivos(palabras_clave: str, extension: str = None) -> str:
    """
    Busca archivos en Google Drive, OneDrive y carpetas personales del usuario.
    Ordena los resultados por fecha (los más recientes primero) y devuelve las rutas completas.

    Args:
        palabras_clave: Términos o nombres a buscar en el título del archivo (ej: 'silabo', 'rubrica', 'cv', 'informe').
        extension: Extensión opcional del archivo sin punto (ej: 'pdf', 'xlsx', 'docx', 'py').
    """
    keywords = palabras_clave.lower().replace("_", " ").replace("-", " ").split()
    stop_words = {"el", "la", "los", "las", "un", "una", "de", "del", "en", "para", "mi", "mis", "último", "ultimo", "archivo", "formato"}
    keywords = [w for w in keywords if w not in stop_words]

    if "cv" in keywords or "curriculum" in keywords:
        keywords.extend(["hoja", "vida"])
    if "vida" in keywords:
        keywords.append("cv")

    matches = []
    for root_dir in SEARCH_ROOTS:
        if not os.path.exists(root_dir):
            continue
        for root, dirs, files in os.walk(root_dir):
            for f in files:
                f_lower = f.lower()
                if extension and not f_lower.endswith(extension.lower()):
                    continue
                matched_kws = sum(1 for kw in keywords if kw in f_lower)
                if matched_kws > 0:
                    score = matched_kws / max(1, len(keywords))
                    full_p = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(full_p)
                        dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                        matches.append((mtime, full_p, dt, score))
                    except Exception:
                        pass

    matches.sort(key=lambda x: (x[3], x[0]), reverse=True)
    if not matches:
        return f"No se encontraron archivos para '{palabras_clave}'."

    top_results = matches[:8]
    lines = [f"- {p} (Modificado: {dt})" for _, p, dt, _ in top_results]
    return "Archivos encontrados (ordenados por fecha más reciente):\n" + "\n".join(lines)


def adjuntar_archivo_a_telegram(ruta_archivo: str) -> str:
    """
    Marca un archivo de la computadora (PDF, Word, Excel, imagen, ZIP, etc.)
    para que sea enviado como documento adjunto directamente al chat de Telegram.
    """
    clean_path = ruta_archivo.strip().strip("[]'\"`*")
    if not os.path.exists(clean_path):
        return f"No se encontró ningún archivo en la ruta: {clean_path}"
    if not _is_safe_attachment_path(clean_path):
        return "Acceso denegado: por seguridad no se permite enviar archivos de configuración o credenciales."
    if clean_path not in CURRENT_RUN_FILES:
        CURRENT_RUN_FILES.append(clean_path)
    return f"Archivo '{os.path.basename(clean_path)}' preparado y encolado para enviarse adjunto a Telegram."


def ejecutar_codigo_python(codigo: str) -> str:
    """
    Ejecuta un script de Python de forma local en la computadora y devuelve su salida (stdout o stderr).
    Útil para cálculos matemáticos, transformaciones de archivos, análisis de datos con pandas o scripts rápidos.

    Args:
        codigo: Código fuente en Python a ejecutar.
    """
    temp_script = os.path.join(os.environ.get("TEMP", "."), f"agent_script_{int(time.time())}.py")
    python_exe = sys.executable
    if python_exe.lower().endswith("pythonw.exe"):
        candidate_exe = python_exe[:-5] + ".exe"
        if os.path.exists(candidate_exe):
            python_exe = candidate_exe
    try:
        with open(temp_script, "w", encoding="utf-8") as f:
            f.write(codigo)
        res = subprocess.run(
            [python_exe, temp_script],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW_FLAG
        )
        out = res.stdout.strip()
        err = res.stderr.strip()
        if res.returncode != 0:
            return f"[ERROR EN SCRIPT PYTHON (Código {res.returncode})]:\n{err or out}\nACCIÓN: Prohibido reportar éxito. Informa el error exacto al usuario."
        return out or err or "Código Python ejecutado con éxito sin salida por consola."
    except Exception as e:
        return f"[ERROR EN EJECUCIÓN PYTHON]: {e}"
    finally:
        if os.path.exists(temp_script):
            try:
                os.remove(temp_script)
            except Exception:
                pass


def ejecutar_comando_powershell(comando: str) -> str:
    """
    Ejecuta cualquier comando o script en PowerShell de Windows y devuelve la salida.
    Útil para tareas de sistema, gestión de procesos, Git, inspección de rutas y utilidades de Windows.

    Args:
        comando: Comando o script de PowerShell a ejecutar.
    """
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", comando],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW_FLAG
        )
        out = res.stdout.strip()
        err = res.stderr.strip()
        if res.returncode != 0:
            return f"[ERROR EN POWERSHELL (Código {res.returncode})]:\n{err or out}\nACCIÓN: Prohibido reportar éxito. Informa con precisión el error devuelto al usuario."
        if out and err:
            return f"SALIDA:\n{out}\n\nAVISOS:\n{err}"
        return out or err or "Comando ejecutado exitosamente sin salida."
    except Exception as e:
        return f"[ERROR EJECUTANDO POWERSHELL]: {e}"


def obtener_codigo_2fa() -> str:
    """Calcula el código TOTP de 6 dígitos actual para la autenticación de dos pasos institucional."""
    secret = os.getenv("INSTITUTIONAL_2FA_SECRET", "").strip().replace(" ", "").upper()
    if not secret:
        return "No hay clave 2FA configurada en el archivo .env (INSTITUTIONAL_2FA_SECRET)."
    try:
        totp = pyotp.TOTP(secret)
        code = totp.now()
        secs = 30 - (int(time.time()) % 30)
        return f"Código 2FA: {code} (Válido por {secs} segundos más)."
    except Exception as e:
        return f"Error calculando 2FA: {e}"


def obtener_estado_pc() -> str:
    """
    Obtiene un diagnóstico completo de salud y rendimiento de la computadora del usuario:
    - Uso de CPU y memoria RAM (usada, libre y porcentaje).
    - Espacio libre y total en todas las unidades de disco fijas (C:, D:, etc.).
    - Estado de batería y cargador.
    - Top 5 de procesos que más memoria RAM están consumiendo actualmente.
    """
    try:
        # 1. CPU y RAM
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        ram_str = f"{round(ram.used/(1024**3), 2)}GB / {round(ram.total/(1024**3), 2)}GB ({ram.percent}%)"

        # 2. Discos fijos
        disks_info = []
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or not part.fstype:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks_info.append(f"{part.device} ({round(usage.free/(1024**3), 1)}GB libres de {round(usage.total/(1024**3), 1)}GB)")
            except (PermissionError, OSError):
                continue
        disks_str = " | ".join(disks_info) if disks_info else "No disponible"

        # 3. Batería
        battery = psutil.sensors_battery()
        if battery:
            bat_str = f"{battery.percent}% ({'Conectado al cargador' if battery.power_plugged else 'Usando batería'})"
        else:
            bat_str = "PC de escritorio / Sin batería"

        # 4. Top 5 Procesos por RAM
        procs = []
        for p in psutil.process_iter(['name', 'memory_info']):
            try:
                mem = p.info['memory_info'].rss
                pname = p.info['name']
                if mem and pname:
                    procs.append((pname, mem))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x[1], reverse=True)
        top_5 = [f"{name} ({round(mem/(1024**2), 1)}MB)" for name, mem in procs[:5]]
        top_str = ", ".join(top_5)

        return (
            f"Diagnóstico en vivo de la PC:\n"
            f"• CPU: {cpu}%\n"
            f"• RAM: {ram_str}\n"
            f"• Discos: {disks_str}\n"
            f"• Batería: {bat_str}\n"
            f"• Top 5 Procesos en RAM: {top_str}"
        )
    except Exception as e:
        return f"Error obteniendo estado del PC: {e}"


def recordar_preferencia_o_habito(detalle: str) -> str:
    """
    Guarda en la memoria a largo plazo un nuevo hábito, preferencia, materia,
    horario o dato personal importante que el usuario te indique para que nunca lo olvides.
    """
    return agregar_nota_perfil(detalle)


def guardar_dato_sobre_usuario(categoria: str, dato: str) -> str:
    """Guarda información personal estructurada sobre el usuario en su memoria a largo plazo.

    Args:
        categoria: Categoría exacta ('identidad', 'trabajo_y_proyectos', 'rutinas_y_horarios', 'contactos_frecuentes', 'preferencias_y_notas').
        dato: Información clara y concisa a recordar permanentemente.
    """
    return actualizar_memoria_estructurada(categoria, dato)


def consultar_memoria_sobre_usuario() -> str:
    """Devuelve todo lo que el asistente recuerda a largo plazo sobre el usuario."""
    return resumir_memoria_personal()


def olvidar_dato_usuario(texto_a_olvidar: str) -> str:
    """Elimina un dato específico de la memoria a largo plazo si el usuario pide olvidarlo.

    Args:
        texto_a_olvidar: Palabra clave o frase del recuerdo a eliminar.
    """
    return olvidar_dato_memoria(texto_a_olvidar)


def olvidar_conversacion_reciente() -> str:
    """
    Limpia la memoria de mensajes recientes si el usuario te pide expresamente
    'olvida lo que hablamos', 'comencemos de cero' o 'borra la memoria reciente'.
    """
    return limpiar_historial_conversacion()


def consultar_actividad_antigravity() -> str:
    """
    Consulta detalladamente las últimas conversaciones, proyectos, tareas y avances
    realizados por el usuario dentro de Antigravity IDE en la computadora.
    """
    actividades = obtener_actividad_reciente_antigravity(limite=8)
    if not actividades:
        return "No se encontraron sesiones registradas en Antigravity IDE."
    lineas = ["Sesiones y proyectos recientes en Antigravity IDE:"]
    for a in actividades:
        lineas.append(f"• [{a['fecha']}] {a['titulo']}: {a['resumen']}")
    return "\n".join(lineas)


def apagar_pc(segundos: int = 60, confirmado: bool = False) -> str:
    """Programa el apagado de la computadora en la cantidad de segundos indicada (requiere confirmación del usuario).

    Args:
        segundos: Segundos antes de apagar (por defecto 60).
        confirmado: Debe ser False en la solicitud inicial para pedir confirmación.
    """
    if not confirmado:
        return registrar_confirmacion_sensible(
            titulo="Apagar computadora",
            resumen=f"Apagar la computadora en {segundos} segundos.",
            func=apagar_pc,
            kwargs={"segundos": segundos},
        )
    try:
        subprocess.run(["shutdown", "/s", "/t", str(segundos)], check=True, creationflags=NO_WINDOW_FLAG)
        return f"La computadora se apagará en {segundos} segundos. Si cambias de opinión, pídeme 'cancelar apagado'."
    except Exception as e:
        return f"Error al programar el apagado: {e}"


def cancelar_apagado() -> str:
    """Cancela un apagado o reinicio que haya sido programado previamente."""
    try:
        subprocess.run(["shutdown", "/a"], check=True, creationflags=NO_WINDOW_FLAG)
        return "Apagado cancelado con éxito. Tu computadora continuará encendida normalmente."
    except Exception as e:
        return f"No había ningún apagado pendiente o error: {e}"


def reiniciar_pc(segundos: int = 60, confirmado: bool = False) -> str:
    """Programa el reinicio de la computadora en la cantidad de segundos indicada (requiere confirmación del usuario).

    Args:
        segundos: Segundos antes de reiniciar (por defecto 60).
        confirmado: Debe ser False inicialmente para pedir confirmación.
    """
    if not confirmado:
        return registrar_confirmacion_sensible(
            titulo="Reiniciar computadora",
            resumen=f"Reiniciar la computadora en {segundos} segundos.",
            func=reiniciar_pc,
            kwargs={"segundos": segundos},
        )
    try:
        subprocess.run(["shutdown", "/r", "/t", str(segundos)], check=True, creationflags=NO_WINDOW_FLAG)
        return f"La computadora se reiniciará en {segundos} segundos."
    except Exception as e:
        return f"Error al programar reinicio: {e}"


def suspender_pc() -> str:
    """Pone la computadora en suspensión para ahorrar energía. (Aviso: mientras esté suspendida no responderá Telegram hasta que se presione el botón de encendido)."""
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"],
            creationflags=NO_WINDOW_FLAG
        )
        return "Comando de suspensión enviado. La PC entrará en reposo."
    except Exception as e:
        return f"Error suspendiendo la PC: {e}"


def bloquear_pc() -> str:
    """Bloquea la sesión de Windows (Win + L) para proteger tu pantalla. El bot sigue 100% activo en segundo plano."""
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Pantalla bloqueada con éxito (sesión de Windows asegurada). Sigo escuchando tus órdenes en segundo plano."
    except Exception as e:
        return f"Error al bloquear la pantalla: {e}"


def cerrar_aplicaciones_abiertas(aplicacion_especifica: str = "", confirmado: bool = False) -> str:
    """
    Cierra de forma real y efectiva las aplicaciones y programas de usuario abiertos en Windows
    (como Google Chrome, WhatsApp, Word, Excel, PowerPoint, Acrobat, Bloc de notas, VLC, Edge, etc.).
    Requiere confirmación previa del usuario antes de cerrar procesos.

    Args:
        aplicacion_especifica: Nombre opcional de una aplicación concreta a cerrar (ej: 'chrome', 'whatsapp', 'word'). Si está vacío o es 'todas', cierra todos los programas de usuario abiertos.
        confirmado: Debe ser False inicialmente para solicitar confirmación al usuario.
    """
    if not confirmado:
        objetivo_txt = (
            f"cerrar la aplicación '{aplicacion_especifica}'"
            if aplicacion_especifica and aplicacion_especifica.strip().lower() not in ("todas", "todos", "all", "")
            else "cerrar TODAS las aplicaciones y ventanas abiertas en tu PC (excepto el sistema y el bot)"
        )
        return registrar_confirmacion_sensible(
            titulo="Cerrar aplicaciones",
            resumen=f"Confirmar {objetivo_txt}.",
            func=cerrar_aplicaciones_abiertas,
            kwargs={"aplicacion_especifica": aplicacion_especifica},
        )
    import psutil

    # Protección estricta de PIDs: NUNCA auto-terminar el bot ni sus procesos hijos
    current_pid = os.getpid()
    parent_pid = os.getppid()
    bot_pids = {current_pid, parent_pid}
    try:
        for c in psutil.Process(current_pid).children(recursive=True):
            bot_pids.add(c.pid)
    except Exception:
        pass

    # Procesos protegidos que NUNCA deben cerrarse
    PROTECTED = {
        "python", "pythonw", "antigravity", "explorer", "onedrive", "googledrivefs",
        "conhost", "cmd", "powershell", "taskhostw", "sihost", "dwm", "csrss",
        "winlogon", "runtimebroker", "searchhost", "shellexperiencehost",
        "startmenuexperiencehost", "textinputhost", "systemsettings",
        "securityhealthsystray", "code"
    }

    # Familias de aplicaciones de usuario comunes
    USER_TARGETS = {
        "chrome": "Google Chrome",
        "whatsapp.root": "WhatsApp",
        "whatsapp": "WhatsApp",
        "msedge": "Microsoft Edge",
        "notepad": "Bloc de notas",
        "notepad++": "Notepad++",
        "winword": "Microsoft Word",
        "excel": "Microsoft Excel",
        "powerpnt": "Microsoft PowerPoint",
        "outlook": "Microsoft Outlook",
        "acrobat": "Adobe Acrobat",
        "acrord32": "Adobe Reader",
        "vlc": "VLC Media Player",
        "spotify": "Spotify",
        "discord": "Discord",
        "telegram": "Telegram Desktop",
        "slack": "Slack",
        "teams": "Microsoft Teams",
        "calculator": "Calculadora",
        "calc": "Calculadora"
    }

    filtro = aplicacion_especifica.lower().strip() if aplicacion_especifica else ""
    if filtro in ("todas", "todos", "todo", "los programas", "las aplicaciones"):
        filtro = ""

    cerrados = []
    pids_terminados = 0

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pid = proc.info.get('pid')
            if pid in bot_pids:
                continue

            pname = (proc.info.get('name') or '').lower().replace('.exe', '')

            # Respetar protecciones críticas
            if pname in PROTECTED or pname.startswith("asus") or pname.startswith("intel"):
                continue

            es_objetivo = False
            label = pname
            for target_key, target_label in USER_TARGETS.items():
                if target_key in pname:
                    if not filtro or filtro in target_key or filtro in target_label.lower():
                        es_objetivo = True
                        label = target_label
                        break

            if not es_objetivo and filtro and (filtro in pname):
                es_objetivo = True
                label = pname

            if es_objetivo:
                try:
                    proc.kill()
                    pids_terminados += 1
                    if label not in cerrados:
                        cerrados.append(label)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if cerrados:
        return f"Se cerraron exitosamente las siguientes aplicaciones abiertas: {', '.join(cerrados)} (Total {pids_terminados} procesos finalizados)."
    else:
        if filtro:
            return f"No se encontró la aplicación '{filtro}' abierta en tu computadora."
        return "No se encontraron aplicaciones o ventanas de usuario abiertas para cerrar (o ya estaban cerradas)."


def capturar_pantalla_pc_fisica() -> str:
    """
    Captura una imagen instantánea en vivo de lo que se está mostrando físicamente
    en la pantalla o monitor de la computadora del usuario y la adjunta a Telegram.
    Úsala cuando el usuario pida 'captura de pantalla', 'pantallazo', 'qué hay en mi pantalla',
    'ver escritorio', 'muéstrame la pantalla' o quiera supervisar visualmente su PC desde el teléfono.
    """
    global CURRENT_RUN_FILES
    temp_dir = os.path.join(WORKSPACE_DIR, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    screenshot_file = os.path.join(temp_dir, f"pantalla_pc_{int(time.time())}.png")

    # 1. Intentar con PIL.ImageGrab
    try:
        img = ImageGrab.grab(all_screens=True)
        img.save(screenshot_file, format="PNG")
        if os.path.exists(screenshot_file) and screenshot_file not in CURRENT_RUN_FILES:
            CURRENT_RUN_FILES.append(screenshot_file)
        return f"Captura del monitor físico tomada con éxito ({img.width}x{img.height} px).\nENVIAR_ARCHIVO: {screenshot_file}"
    except Exception as e_pil:
        logger.warning(f"ImageGrab falló ({e_pil}), intentando vía PowerShell .NET...")

    # 2. Respaldo vía .NET Graphics (funciona cuando GDI directo tiene restricciones)
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        f"$bmp.Save('{screenshot_file}', [System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose();"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, timeout=10, creationflags=NO_WINDOW_FLAG)
        if os.path.exists(screenshot_file) and os.path.getsize(screenshot_file) > 1000:
            if screenshot_file not in CURRENT_RUN_FILES:
                CURRENT_RUN_FILES.append(screenshot_file)
            return f"Captura del monitor físico tomada con éxito vía .NET.\nENVIAR_ARCHIVO: {screenshot_file}"
    except Exception as e_ps:
        logger.error(f"Falla en captura .NET: {e_ps}")

    return "No se pudo tomar la captura de pantalla física. Es posible que la sesión de Windows esté bloqueada (Win+L / suspensión), en cuyo caso Windows deshabilita la emisión del framebuffer por seguridad."


# =============================================================================
# DETECCIÓN DINÁMICA DE PROYECTOS DE ANTIGRAVITY IDE
# =============================================================================

def obtener_proyectos_antigravity_dinamicos() -> dict:
    """
    Lee en tiempo real la base de datos de Antigravity IDE (conversation_summaries.db)
    para detectar automáticamente cualquier proyecto nuevo que el usuario cree en el futuro.
    """
    import sqlite3
    import json
    import urllib.parse

    projects = {
        "workspace": CUSTOM_WORKSPACE,
    }

    db_path = os.path.join(USER_HOME, ".gemini", "antigravity", "conversation_summaries.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT title, workspace_uris FROM conversation_summaries WHERE length(title) > 0 ORDER BY last_modified_time DESC")
            for title, uris_json in c.fetchall():
                if not uris_json:
                    continue
                try:
                    uris = json.loads(uris_json)
                    for u in uris:
                        clean_path = urllib.parse.unquote(u.replace("file:///", "").replace("file://", ""))
                        if clean_path.startswith("/") and len(clean_path) > 2 and clean_path[2] == ":":
                            clean_path = clean_path[1:]
                        clean_path = clean_path.replace("/", "\\")
                        if os.path.exists(clean_path):
                            folder_name = os.path.basename(clean_path.rstrip("\\")).lower()
                            if folder_name and folder_name not in projects:
                                projects[folder_name] = clean_path
                            title_clean = title.lower().strip()
                            if title_clean and title_clean not in projects:
                                projects[title_clean] = clean_path
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass

    return projects


def listar_proyectos_antigravity() -> str:
    """Lista dinámicamente todos los proyectos y espacios de trabajo activos de tu Antigravity IDE."""
    projects = obtener_proyectos_antigravity_dinamicos()
    # Filtrar carpetas únicas y significativas
    unique_folders = {}
    for name, path in projects.items():
        base = os.path.basename(path.rstrip("\\"))
        if base and base.lower() not in unique_folders:
            unique_folders[base.lower()] = (base, path)

    lines = ["📁 Proyectos detectados en tu Antigravity IDE (actualizados en tiempo real):"]
    for base, path in sorted(unique_folders.values(), key=lambda x: x[0].lower()):
        lines.append(f"• <b>{base}</b>")
    
    return "\n".join(lines[:15])


def ejecutar_tarea_con_antigravity_cli(tarea: str) -> str:
    """
    Ejecuta tareas de programación, desarrollo, análisis de código, modificación o creación de archivos
    utilizando el motor autónomo oficial de Antigravity CLI (agy.exe) con modelo gemini-3.8-flash-low y memoria persistente.
    Usa esta herramienta cuando el usuario pida crear scripts, refactorizar código, procesar documentos
    o realizar trabajos autónomos profundos en su computadora.
    """
    try:
        from agent_executor import execute_autonomous_task
        res = execute_autonomous_task(tarea, return_dict=True)
        if isinstance(res, dict):
            for f in res.get("files", []):
                if f not in CURRENT_RUN_FILES:
                    CURRENT_RUN_FILES.append(f)
            return res.get("text", "Tarea completada.")
        return str(res)
    except Exception as e:
        return f"Error ejecutando tarea en Antigravity CLI: {e}"


def trabajar_en_proyecto_antigravity(nombre_proyecto: str, instruccion_o_tarea: str) -> str:
    """
    Ejecuta tareas de desarrollo, modificación de código, procesamiento de documentos o creación de archivos
    en cualquiera de tus proyectos de Antigravity (detectados dinámicamente desde Antigravity IDE).
    """
    try:
        from agent_executor import execute_autonomous_task
        import project_manager

        # 1. Intentar resolver mediante project_manager
        all_projs = project_manager.list_projects()
        target_dir = None
        key_clean = nombre_proyecto.lower().strip()

        for p in all_projs:
            if p["key"] in key_clean or key_clean in p["key"] or p["name"].lower() in key_clean:
                target_dir = p["directory"]
                break

        # 2. Respaldo en proyectos dinámicos de Antigravity IDE
        if not target_dir:
            dyn_projs = obtener_proyectos_antigravity_dinamicos()
            for k, path in dyn_projs.items():
                if k in key_clean or key_clean in k:
                    target_dir = path
                    break

        # 3. Respaldo en WORKSPACE_DIR configurado
        if not target_dir or not os.path.exists(target_dir):
            candidate = os.path.join(CUSTOM_WORKSPACE, nombre_proyecto)
            if os.path.exists(candidate):
                target_dir = candidate

        if not target_dir or not os.path.exists(target_dir):
            return f"No se encontró el proyecto '{nombre_proyecto}'. Usa `listar_proyectos_antigravity` para ver los nombres disponibles."

        res = execute_autonomous_task(instruccion_o_tarea, work_dir=target_dir, return_dict=True)
        if isinstance(res, dict):
            for f in res.get("files", []):
                if f not in CURRENT_RUN_FILES:
                    CURRENT_RUN_FILES.append(f)
            out_text = res.get("text", "Tarea completada.")
        else:
            out_text = str(res)

        return f"Resultado del trabajo en '{os.path.basename(target_dir)}':\n{out_text}"
    except Exception as e:
        return f"Error trabajando en el proyecto '{nombre_proyecto}': {e}"


def _resolve_firmar_pdf_command() -> list:
    """Resuelve el ejecutable o módulo local de firmar-pdf si está instalado."""
    import shutil
    exe_in_path = shutil.which("firmar-pdf")
    if exe_in_path:
        return [exe_in_path]

    candidates = [
        os.path.join(os.path.dirname(sys.executable), "Scripts", "firmar-pdf.exe"),
        os.path.join(USER_HOME, ".gemini", "antigravity", "bin", "firmar-pdf.cmd"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return [c]
    return [sys.executable, "-m", "firma_pdf.cli"]


def firmar_documento_pdf(
    ruta_pdf: str,
    pin: str,
    texto_busqueda: str = "",
    posicion: str = "bottom-right",
    pagina: str = "last",
    offset: str = "",
    coordenadas: str = ""
) -> str:
    """Firma electrónicamente un documento PDF usando el motor local firmar-pdf (si está instalado) y lo adjunta a Telegram.

    Args:
        ruta_pdf: Ruta absoluta al archivo PDF a firmar.
        pin: PIN numérico de 4 dígitos para autorizar la firma electrónica.
        texto_busqueda: Texto opcional dentro del PDF sobre el cual estampar la firma.
        posicion: Posición predefinida si no hay texto_busqueda ('bottom-right', 'bottom-left', 'bottom-center', 'top-right', 'top-left', 'center').
        pagina: Página donde firmar ('last', 'first', 'all', o número de página).
        offset: Desplazamiento fino opcional 'dx,dy'.
        coordenadas: Coordenadas manuales opcionales 'x,y'.
    """
    try:
        from pathlib import Path
        pdf_path = Path(ruta_pdf.strip().strip('"'))
        if not pdf_path.is_file():
            return f"[ERROR: No se encontró el archivo PDF en '{pdf_path}']"
        if pdf_path.suffix.lower() != ".pdf":
            return f"[ERROR: El archivo '{pdf_path.name}' no es un PDF válido.]"

        pin_clean = str(pin or "").strip()
        if not pin_clean:
            return "[ERROR: Se requiere el PIN de 4 dígitos para firmar electrónicamente el documento.]"

        base_cmd = _resolve_firmar_pdf_command()
        out_dir = Path(WORKSPACE_DIR) / "temp" / "signed"
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = base_cmd + [
            "-i", str(pdf_path),
            "-o", str(out_dir),
            "--pin", pin_clean,
            "--page", str(pagina or "last").strip()
        ]
        if coordenadas and coordenadas.strip():
            cmd.extend(["--coords", coordenadas.strip()])
        elif texto_busqueda and texto_busqueda.strip():
            cmd.extend(["--search-text", texto_busqueda.strip()])
        else:
            valid_pos = {"bottom-right", "bottom-left", "bottom-center", "top-right", "top-left", "center"}
            pos_clean = posicion if posicion in valid_pos else "bottom-right"
            cmd.extend(["--pos", pos_clean])
        if offset and offset.strip():
            cmd.extend(["--offset", offset.strip()])

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=NO_WINDOW_FLAG
        )
        combined_output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        if res.returncode != 0:
            return f"[ERROR AL FIRMAR PDF (Código {res.returncode})]:\n{combined_output[-1500:]}"

        signed_path = None
        for line in combined_output.splitlines():
            if "Ruta:" in line:
                candidate = line.split("Ruta:", 1)[1].strip()
                if os.path.exists(candidate):
                    signed_path = candidate
                    break
        if not signed_path:
            expected = out_dir / f"{pdf_path.stem}-signed.pdf"
            if expected.is_file():
                signed_path = str(expected)
            else:
                matches = sorted(out_dir.glob(f"{pdf_path.stem}*-signed*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
                if matches:
                    signed_path = str(matches[0])

        if not signed_path or not os.path.exists(signed_path):
            return f"[ERROR: firmar-pdf terminó pero no se encontró el archivo -signed.pdf en {out_dir}.]"

        if signed_path not in CURRENT_RUN_FILES:
            CURRENT_RUN_FILES.append(signed_path)
        return f"Documento firmado electrónicamente con éxito: {os.path.basename(signed_path)}\nENVIAR_ARCHIVO: {signed_path}"
    except Exception as e:
        return f"[ERROR ejecutando firmar-pdf: {e}]"


def consultar_calendario_google(dias: int = 7) -> str:
    """Consulta los próximos eventos y reuniones en Google Calendar."""
    return google_workspace.consultar_calendario(dias=dias)


def crear_evento_calendario_google(
    titulo: str,
    fecha_inicio_iso: str,
    duracion_minutos: int = 60,
    descripcion: str = ""
) -> str:
    """Crea un nuevo evento o recordatorio en Google Calendar."""
    return google_workspace.crear_evento_calendario(
        titulo=titulo,
        fecha_inicio_iso=fecha_inicio_iso,
        duracion_minutos=duracion_minutos,
        descripcion=descripcion
    )


def leer_correos_gmail(limite: int = 5, solo_no_leidos: bool = True, filtro: str = "") -> str:
    """Lee correos electrónicos recientes de Gmail."""
    return google_workspace.leer_correos_gmail(
        limite=limite,
        solo_no_leidos=solo_no_leidos,
        filtro=filtro
    )


def enviar_correo_gmail(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    confirmado: bool = False
) -> str:
    """Envía un correo electrónico por Gmail (requiere confirmación explícita del usuario)."""
    if not confirmado:
        return registrar_confirmacion_sensible(
            titulo="Enviar correo por Gmail",
            resumen=f"Enviar correo a '{destinatario}' con asunto '{asunto}'.",
            func=enviar_correo_gmail,
            kwargs={"destinatario": destinatario, "asunto": asunto, "cuerpo": cuerpo},
        )
    return google_workspace.enviar_correo_gmail(
        destinatario=destinatario,
        asunto=asunto,
        cuerpo=cuerpo
    )


def buscar_google_drive_nube(consulta: str, limite: int = 8) -> str:
    """Busca archivos directamente en la nube de Google Drive."""
    return google_workspace.buscar_drive_nube(consulta=consulta, limite=limite)


def consultar_consumo_api() -> str:
    """Consulta el consumo de tokens y costo estimado de la API de Gemini (hoy, última consulta y total)."""
    return usage_tracker.obtener_resumen_consumo()


def responder_con_audio(texto_a_hablar: str, voz: str = "Kore", estilo: str = "") -> str:
    """Convierte texto a voz hablada (TTS) y lo adjunta como nota de voz/audio en Telegram."""
    global CURRENT_RUN_FILES
    audio_path, status_msg = gemini_cli_tools.generar_audio_tts(
        texto=texto_a_hablar, voz=voz, estilo=estilo, idioma="es-419"
    )
    if not audio_path:
        return status_msg
    if audio_path not in CURRENT_RUN_FILES:
        CURRENT_RUN_FILES.append(audio_path)
    return f"Audio generado y adjuntado para Telegram.\nENVIAR_ARCHIVO: {audio_path}"


def transcribir_archivo_multimedia(ruta_archivo: str, formato: str = "md", incluir_hablantes: bool = True) -> str:
    """Transcribe un archivo de audio o video a texto, Markdown o subtítulos SRT."""
    global CURRENT_RUN_FILES
    out_path, preview_or_err = gemini_cli_tools.transcribir_archivo_multimedia(
        ruta_archivo=ruta_archivo, formato=formato, incluir_hablantes=incluir_hablantes
    )
    if not out_path:
        return preview_or_err
    if out_path not in CURRENT_RUN_FILES:
        CURRENT_RUN_FILES.append(out_path)
    return f"Transcripción completada: {os.path.basename(out_path)}\nENVIAR_ARCHIVO: {out_path}\n\nVista previa:\n{preview_or_err}"


def investigacion_profunda(tema: str) -> str:
    """Ejecuta una investigación profunda (Deep Research) con fuentes primarias y devuelve el informe en Markdown."""
    global CURRENT_RUN_FILES
    md_path, report_or_err = gemini_cli_tools.ejecutar_investigacion_profunda(tema=tema)
    if not md_path:
        return report_or_err
    if md_path not in CURRENT_RUN_FILES:
        CURRENT_RUN_FILES.append(md_path)
    resumen = report_or_err[:2500] + ("\n\n... [Informe completo adjunto en el archivo .md]" if len(report_or_err) > 2500 else "")
    return f"Investigación profunda completada.\nENVIAR_ARCHIVO: {md_path}\n\n{resumen}"


# =============================================================================
# MOTOR DEL AGENTE (Loop ReAct)
# =============================================================================

AGENT_SYSTEM_PROMPT = """
Eres un Asistente Autónomo de Inteligencia Artificial conectado a la computadora del usuario.
Te comunicas exclusivamente a través de su chat privado de Telegram (mensajes de texto y notas de voz).

PAUTAS CRUCIALES DE INTERACCIÓN:
1. COMUNICACIÓN DESDE DISPOSITIVO MÓVIL:
   - El usuario se comunica desde Telegram y no está viendo la pantalla de su PC.
   - Si pide información de la web, extrae y resume los datos con `navegar_y_extraer_web` en lugar de limitarte a abrir una ventana.
   - Usa `abrir_en_chrome` únicamente si pide explícitamente abrir una pestaña en el monitor de su PC.

2. ENVÍO DE DOCUMENTOS Y ARCHIVOS:
   - Si pide un archivo, búscalo con `buscar_archivos` y adjúntalo con `adjuntar_archivo_a_telegram(ruta_archivo)`.

3. PROYECTOS Y DESARROLLO:
   - Si pide ver qué proyectos tiene, usa `listar_proyectos_antigravity`.
   - Si pide trabajar en un proyecto o ejecutar tareas de desarrollo, usa `trabajar_en_proyecto_antigravity` o `ejecutar_tarea_con_antigravity_cli`.

4. CONTROL DE ENERGÍA, PANTALLA Y HARDWARE:
   - Usa `bloquear_pc`, `apagar_pc`, `reiniciar_pc`, `suspender_pc`, `capturar_pantalla_pc_fisica`, `obtener_estado_pc` y `cerrar_aplicaciones_abiertas` según corresponda.

5. MEMORIA PERSISTENTE ESTRUCTURADA Y ESTILO:
   - Si el usuario comparte datos personales, horarios, proyectos, contactos o preferencias, guárdalos automáticamente con `guardar_dato_sobre_usuario`.
   - Si pregunta qué sabes o recuerdas de él/ella, usa `consultar_memoria_sobre_usuario`.
   - Responde de forma concisa, directa y profesional, sin encabezados `#` ni markdown roto.

6. GOOGLE WORKSPACE Y FIRMA DE PDFs:
   - Usa `consultar_calendario_google`, `crear_evento_calendario_google`, `leer_correos_gmail`, `enviar_correo_gmail` y `buscar_google_drive_nube` cuando solicite datos de Google Workspace.
   - Si envía un PDF o pide firmar uno con su PIN, usa `firmar_documento_pdf`.

7. CONFIRMACIÓN OBLIGATORIA DE ACCIONES SENSIBLES:
   - Las herramientas `apagar_pc`, `reiniciar_pc`, `cerrar_aplicaciones_abiertas` y `enviar_correo_gmail` requieren confirmación explícita del usuario. Invócalas con `confirmado=False` y detente cuando devuelvan `[CONFIRMACION_REQUERIDA:...]`.

REGLA DE ORO ANTI-ALUCINACIÓN:
Nunca afirmes haber ejecutado una acción en la computadora o en la web si no ejecutaste exitosamente la herramienta correspondiente en este turno.
"""

class AgentEngine:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client = genai.Client(api_key=self.api_key)
        env_model = os.getenv("GEMINI_MODEL", "").strip()
        candidates = [
            "gemini-4-hydrogen",
            env_model,
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
        ]

        self.models_to_try = []
        for m in candidates:
            if m and m not in self.models_to_try:
                self.models_to_try.append(m)
        self.tools = [
            navegar_y_extraer_web,
            interactuar_en_pagina_web,
            interactuar_y_descargar_web,
            abrir_en_chrome,
            buscar_archivos,
            adjuntar_archivo_a_telegram,
            consultar_calendario_google,
            crear_evento_calendario_google,
            leer_correos_gmail,
            enviar_correo_gmail,
            buscar_google_drive_nube,
            consultar_consumo_api,
            responder_con_audio,
            transcribir_archivo_multimedia,
            investigacion_profunda,
            recordar_preferencia_o_habito,
            guardar_dato_sobre_usuario,
            consultar_memoria_sobre_usuario,
            olvidar_dato_usuario,
            olvidar_conversacion_reciente,
            consultar_actividad_antigravity,
            capturar_pantalla_pc_fisica,
            ejecutar_codigo_python,
            ejecutar_comando_powershell,
            obtener_codigo_2fa,
            obtener_estado_pc,
            apagar_pc,
            cancelar_apagado,
            reiniciar_pc,
            suspender_pc,
            bloquear_pc,
            cerrar_aplicaciones_abiertas,
            firmar_documento_pdf,
            listar_proyectos_antigravity,
            trabajar_en_proyecto_antigravity,
            ejecutar_tarea_con_antigravity_cli
        ]

    def run_task(self, user_prompt: str) -> dict:
        """
        Ejecuta el bucle de agente autónomo con memoria persistente (corto y largo plazo)
        y tolerancia a fallos, priorizando Gemini 4 Hydrogen.
        """
        global CURRENT_RUN_FILES, CURRENT_PENDING_CONFIRMATION
        CURRENT_RUN_FILES = []
        CURRENT_PENDING_CONFIRMATION = None
        last_error = None

        contexto_memoria = formatear_contexto_memoria()
        system_instruction_completa = f"{AGENT_SYSTEM_PROMPT}\n\n{contexto_memoria}"

        for m in self.models_to_try:
            try:
                logger.info(f"Procesando orden con modelo: {m}")
                config_kwargs = {
                    "system_instruction": system_instruction_completa,
                    "tools": self.tools,
                    "temperature": 0.2
                }
                if "gemini-4-" in m.lower():
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
                elif "gemini-3.5-flash-lite" in m.lower():
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")

                config = types.GenerateContentConfig(**config_kwargs)
                chat = self.client.chats.create(
                    model=m,
                    config=config
                )
                response = chat.send_message(user_prompt)
                try:
                    usage_tracker.registrar_consumo(m, getattr(response, "usage_metadata", None))
                except Exception:
                    pass
                final_text = response.text or ""
                
                # Detectar archivos marcados para enviar
                files_to_send = []
                cleaned_lines = []
                for line in final_text.splitlines():
                    if "ENVIAR_ARCHIVO:" in line:
                        path = line.split("ENVIAR_ARCHIVO:")[1].strip().strip("[]'\"`*")
                        if os.path.exists(path) and path not in files_to_send:
                            files_to_send.append(path)
                    else:
                        cleaned_lines.append(line)
                        
                # Añadir archivos generados durante las herramientas (capturas, descargas, adjuntar_archivo)
                for f in CURRENT_RUN_FILES:
                    if os.path.exists(f) and f not in files_to_send:
                        files_to_send.append(f)

                cleaned_reply = "\n".join(cleaned_lines).strip()
                if not cleaned_reply and files_to_send:
                    cleaned_reply = "Aquí tienes el archivo solicitado."
                elif not cleaned_reply:
                    cleaned_reply = "Orden ejecutada correctamente."

                # Registrar el turno en el historial de conversación para continuidad
                registrar_turno(user_prompt, cleaned_reply)

                logger.info(f"Orden completada exitosamente con {m}. Archivos adjuntos: {len(files_to_send)}")
                return {
                    "success": True,
                    "text": cleaned_reply,
                    "files": files_to_send,
                    "model_used": m,
                    "pending_confirmation": CURRENT_PENDING_CONFIRMATION,
                }
            except Exception as e:
                last_error = e
                logger.warning(f"Falla con modelo {m} ({e}), intentando siguiente modelo...")
                if "503" in str(e) or "UNAVAILABLE" in str(e) or "demand" in str(e).lower():
                    time.sleep(2.0)
                continue

        logger.error(f"Todos los modelos fallaron. Último error: {last_error}")
        return {
            "success": False,
            "text": f"⚠️ No pude completar la consulta en este momento debido a saturación temporal de los servidores de IA ({last_error}). Por favor, intenta nuevamente en unos segundos.",
            "files": []
        }

    def process_voice_and_run(self, audio_bytes: bytes, mime_type: str = "audio/ogg", extra_context: str = "") -> dict:
        """Transcribe la nota de voz usando modelos Flash Lite y ejecuta el bucle de agente."""
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        voice_models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"] + self.models_to_try
        transcription = None
        last_err = None

        for vm in voice_models:
            try:
                trans_res = self.client.models.generate_content(
                    model=vm,
                    contents=[audio_part, "Por favor transcribe exactamente lo que dice este audio en español. Solo devuelve la transcripción."]
                )
                if trans_res and trans_res.text:
                    try:
                        usage_tracker.registrar_consumo(vm, getattr(trans_res, "usage_metadata", None))
                    except Exception:
                        pass
                    transcription = trans_res.text.strip()
                    break
                elif trans_res and getattr(trans_res, "candidates", None):
                    parts = trans_res.candidates[0].content.parts
                    collected = []
                    for p in parts:
                        if getattr(p, "text", None):
                            collected.append(p.text)
                        elif getattr(p, "audio_transcription", None):
                            collected.append(str(p.audio_transcription))
                    if collected:
                        transcription = " ".join(collected).strip()
                        break
            except Exception as e:
                last_err = e
                logger.warning(f"Falla transcribiendo audio con {vm}: {e}")
                continue

        if not transcription:
            return {
                "success": False,
                "transcription": "(Error de audio)",
                "text": f"No se pudo transcribir la nota de voz: {last_err}",
                "files": []
            }

        prompt_to_run = f"{extra_context}\n\nInstrucción del usuario: {transcription}" if extra_context else transcription
        result = self.run_task(prompt_to_run)
        result["transcription"] = transcription
        return result
