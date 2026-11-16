"""
Gestor de sesiones y proyectos para Antigravity CLI (AgyBridge).
Sincroniza directamente con los proyectos reales de Antigravity IDE (~/.gemini/config/projects),
ordena por actividad reciente desde conversation_summaries.db y mantiene memoria persistente por proyecto.
"""

import os
import glob
import json
import uuid
import datetime
import logging
import sqlite3
import re
import unicodedata
from urllib.parse import unquote
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_FILE = os.path.join(BASE_DIR, "project_sessions.json")
DEFAULT_DIR = os.path.expanduser(os.environ.get("WORKSPACE_DIR", r"~\Documents"))
GEMINI_PROJECTS_DIR = os.path.expanduser(r"~\.gemini\config\projects")
SUMMARIES_DB = os.path.expanduser(r"~\.gemini\antigravity\conversation_summaries.db")


def normalize_text(text: str) -> str:
    """Normaliza texto eliminando acentos y caracteres especiales."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def make_clean_slug(name: str) -> str:
    """Genera un slug corto y nemotécnico para usar como comando de Telegram."""
    clean = normalize_text(name)
    clean = re.sub(r"[^a-z0-9]+", "_", clean).strip("_")
    stop_words = {"y", "de", "la", "el", "los", "las", "un", "una", "en", "para", "del", "al"}
    words = [w for w in clean.split("_") if w and w not in stop_words]
    if words:
        return "_".join(words[:3])
    return clean[:20] or "proyecto"


def discover_antigravity_projects() -> Dict[str, Dict[str, Any]]:
    """
    Descubre automáticamente todos los proyectos reales creados en Antigravity IDE,
    leyendo las configuraciones de ~/.gemini/config/projects/*.json y ordenando por fecha de actividad.
    """
    discovered: Dict[str, Dict[str, Any]] = {}

    # 1. Escanear definiciones de proyectos de Antigravity
    if os.path.exists(GEMINI_PROJECTS_DIR):
        for f in glob.glob(os.path.join(GEMINI_PROJECTS_DIR, "*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                    pid = d.get("id")
                    name = d.get("name", "").strip()
                    if not pid or not name or name.startswith("android-cli-plugin") or pid in ["outside-of-project", "default-cli-project"]:
                        continue

                    res = d.get("projectResources", {}).get("resources", [])
                    folder = ""
                    if res and "folderUri" in res[0]:
                        u = res[0]["folderUri"]
                        if u.startswith("file:///"):
                            folder = unquote(u.replace("file:///", "")).replace("/", "\\")

                    # Si el folder existe en el disco, lo consideramos proyecto válido
                    if folder and os.path.exists(folder):
                        slug = make_clean_slug(name)
                        discovered[slug] = {
                            "antigravity_id": pid,
                            "name": name,
                            "directory": os.path.abspath(folder),
                            "last_active": ""
                        }
            except Exception as e:
                logger.debug(f"Error procesando proyecto {f}: {e}")

    # 2. Consultar actividad reciente desde conversation_summaries.db
    if os.path.exists(SUMMARIES_DB):
        try:
            conn = sqlite3.connect(SUMMARIES_DB)
            c = conn.cursor()
            c.execute("SELECT project_id, MAX(last_modified_time) FROM conversation_summaries GROUP BY project_id")
            activity_map = {pid: mtime for pid, mtime in c.fetchall()}
            conn.close()

            for slug, info in discovered.items():
                ag_id = info.get("antigravity_id")
                if ag_id in activity_map:
                    info["last_active"] = activity_map[ag_id] or ""
        except Exception as e:
            logger.warning(f"No se pudo consultar conversation_summaries.db: {e}")

    return discovered


def load_sessions() -> dict:
    """
    Carga y sincroniza las sesiones de proyectos.
    Garantiza que los proyectos reales de Antigravity estén disponibles.
    """
    data = {"active_project": "general", "projects": {}}
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "projects" in loaded:
                    data = loaded
        except Exception as e:
            logger.warning(f"Error leyendo {SESSIONS_FILE}: {e}")

    # Modo Libre General siempre presente
    if "general" not in data["projects"]:
        data["projects"]["general"] = {
            "name": "General (Modo Libre)",
            "directory": DEFAULT_DIR if os.path.exists(DEFAULT_DIR) else os.path.expanduser("~"),
            "conversation_id": str(uuid.uuid4()),
            "turns_count": 0,
            "last_active": datetime.datetime.now().isoformat(),
            "last_updated": datetime.datetime.now().isoformat()
        }

    # Sincronizar con los proyectos reales de Antigravity IDE
    real_projects = discover_antigravity_projects()
    for slug, info in real_projects.items():
        if slug not in data["projects"]:
            data["projects"][slug] = {
                "name": info["name"],
                "directory": info["directory"],
                "antigravity_id": info.get("antigravity_id", ""),
                "conversation_id": str(uuid.uuid4()),
                "turns_count": 0,
                "last_active": info.get("last_active", ""),
                "last_updated": datetime.datetime.now().isoformat()
            }
        else:
            # Actualizar metadatos si cambiaron
            data["projects"][slug]["name"] = info["name"]
            data["projects"][slug]["directory"] = info["directory"]
            if info.get("last_active"):
                data["projects"][slug]["last_active"] = info["last_active"]

    save_sessions(data)
    return data


def save_sessions(data: dict):
    """Guarda el estado de sesiones en JSON."""
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando {SESSIONS_FILE}: {e}")


def get_active_project() -> dict:
    """Retorna la información del proyecto actualmente activo."""
    data = load_sessions()
    active_key = data.get("active_project", "general")
    proj = data.get("projects", {}).get(active_key)
    if not proj:
        active_key = "general"
        proj = data.get("projects", {}).get("general", {
            "name": "General (Modo Libre)",
            "directory": DEFAULT_DIR,
            "conversation_id": str(uuid.uuid4()),
            "turns_count": 0,
            "last_updated": datetime.datetime.now().isoformat()
        })
    proj["key"] = active_key
    return proj


def set_active_project(query: str) -> bool:
    """
    Fija el proyecto activo por su clave (slug) o por coincidencia de nombre.
    Soporta 'libre', 'reset', 'general' para volver a modo sin proyecto.
    """
    data = load_sessions()
    q_norm = normalize_text(query.strip())
    if not q_norm:
        return False

    if q_norm in ["reset", "libre", "ninguno", "general", "default", "desactivar", "modo libre"]:
        data["active_project"] = "general"
        save_sessions(data)
        return True

    # 1. Búsqueda exacta por clave/slug
    if q_norm in data.get("projects", {}):
        data["active_project"] = q_norm
        save_sessions(data)
        return True

    # 2. Búsqueda por coincidencia en slug o nombre
    for p_key, info in data.get("projects", {}).items():
        name_norm = normalize_text(info.get("name", ""))
        key_norm = normalize_text(p_key)
        if q_norm == key_norm or q_norm in key_norm or q_norm in name_norm:
            data["active_project"] = p_key
            save_sessions(data)
            return True

    return False


def list_projects(limit: int = 8, show_all: bool = False) -> List[Dict[str, Any]]:
    """
    Retorna la lista de proyectos registrados, ordenados por actividad reciente.
    """
    data = load_sessions()
    active = data.get("active_project", "general")
    projects_list = []

    for key, info in data.get("projects", {}).items():
        if key == "general":
            continue
        projects_list.append({
            "key": key,
            "name": info.get("name", key),
            "directory": info.get("directory", ""),
            "turns_count": info.get("turns_count", 0),
            "last_active": info.get("last_active", ""),
            "is_active": (key == active)
        })

    # Ordenar por fecha de última actividad descendente
    projects_list.sort(key=lambda x: x.get("last_active") or "", reverse=True)

    if not show_all and limit:
        return projects_list[:limit]
    return projects_list


def resolve_project_session(user_prompt: str) -> Tuple[str, str, str]:
    """
    Resuelve el proyecto para una orden:
    Retorna: (project_key, target_directory, conversation_id)
    """
    data = load_sessions()
    p_norm = normalize_text(user_prompt)

    # 1. Chequeo de escape explícito a modo libre
    if any(k in p_norm for k in ["modo libre", "sin proyecto", "tarea libre", "fuera de proyecto", "no project"]):
        gen = data["projects"].get("general", {})
        return "general", gen.get("directory", DEFAULT_DIR), gen.get("conversation_id", str(uuid.uuid4()))

    # 2. Detección por nombre o slug de proyecto en el texto
    for key, info in data.get("projects", {}).items():
        if key == "general":
            continue
        name_norm = normalize_text(info.get("name", ""))
        key_norm = normalize_text(key)
        if (len(key_norm) >= 3 and key_norm in p_norm) or (len(name_norm) >= 4 and name_norm in p_norm):
            conv_id = increment_and_rotate_session(key)
            return key, info.get("directory", DEFAULT_DIR), conv_id

    # 3. Proyecto activo por defecto
    active = get_active_project()
    key = active.get("key", "general")
    conv_id = increment_and_rotate_session(key)
    return key, active.get("directory", DEFAULT_DIR), conv_id


def increment_and_rotate_session(project_key: str, max_turns: int = 20) -> str:
    """
    Incrementa el contador de turnos de la sesión.
    Si supera max_turns o no tiene conversation_id, genera uno nuevo y reinicia el contador.
    """
    data = load_sessions()
    proj = data.get("projects", {}).get(project_key)
    if not proj:
        return str(uuid.uuid4())

    conv_id = proj.get("conversation_id")
    turns = proj.get("turns_count", 0) + 1

    if not conv_id or turns > max_turns:
        conv_id = str(uuid.uuid4())
        turns = 1
        logger.info(f"Sesión rotada para proyecto '{project_key}'. Nuevo conversation_id: {conv_id}")

    proj["conversation_id"] = conv_id
    proj["turns_count"] = turns
    proj["last_updated"] = datetime.datetime.now().isoformat()
    save_sessions(data)
    return conv_id
