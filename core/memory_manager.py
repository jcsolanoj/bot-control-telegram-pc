"""
Sistema de Memoria Persistente para el Asistente Telegram:
1. Memoria a corto plazo (buffer de conversación multi-turno).
2. Memoria a largo plazo (perfil del usuario, hábitos, proyectos y preferencias).
3. Sincronización opcional con sesiones recientes de Antigravity IDE si está instalado.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger("AgentMemory")

MEMORY_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_FILE = os.path.join(MEMORY_DIR, "user_profile.json")
HISTORY_FILE = os.path.join(MEMORY_DIR, "chat_history.json")
USER_HOME = os.path.expanduser("~")
ANTIGRAVITY_DB = os.path.join(USER_HOME, ".gemini", "antigravity", "conversation_summaries.db")


def get_default_profile() -> dict:
    user_name = os.environ.get("USER_NAME", "Usuario").strip() or "Usuario"
    return {
        "usuario": {
            "nombre": user_name,
            "trato": user_name,
            "rol": "Usuario de escritorio y desarrollo con IA",
            "institucion": "",
            "plataformas_clave": [],
        },
        "habitos_y_preferencias": {
            "estilo_respuestas": "Conciso, resolutivo, directo y profesional",
            "dispositivo_principal": "Teléfono móvil (Telegram) mientras la PC trabaja en segundo plano",
            "accion_web_favorita": "Extraer y resumir en Telegram antes que abrir pestañas en el monitor, salvo que lo pida expresamente",
            "proyectos_principales": [],
            "notas_y_recordatorios_aprendidos": [
                "Priorizar modelos rápidos/lite cuando no se requiera razonamiento pesado"
            ],
        },
    }


def cargar_perfil() -> dict:
    """Carga el perfil persistente de largo plazo del usuario."""
    default_profile = get_default_profile()
    if not os.path.exists(PROFILE_FILE):
        guardar_perfil(default_profile)
        return default_profile
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando perfil: {e}")
        return default_profile


def guardar_perfil(perfil: dict):
    """Guarda el perfil de largo plazo en disco."""
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(perfil, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando perfil: {e}")


VALID_MEMORY_CATEGORIES = {
    "identidad": "Identidad y Perfil Personal",
    "trabajo_y_proyectos": "Trabajo, Clases y Proyectos",
    "rutinas_y_horarios": "Rutinas y Horarios",
    "contactos_frecuentes": "Contactos Frecuentes",
    "preferencias_y_notas": "Preferencias y Notas Aprendidas",
}


def agregar_nota_perfil(nueva_nota: str) -> str:
    """Permite al agente registrar un nuevo hábito, preferencia o dato relevante del usuario."""
    return actualizar_memoria_estructurada("preferencias_y_notas", nueva_nota)


def actualizar_memoria_estructurada(categoria: str, dato: str) -> str:
    """Guarda un dato personal estructurado en memoria a largo plazo."""
    perfil = cargar_perfil()
    cat_key = (categoria or "preferencias_y_notas").strip().lower()
    if cat_key not in VALID_MEMORY_CATEGORIES:
        cat_key = "preferencias_y_notas"

    limpia = (dato or "").strip()
    if not limpia:
        return "El dato a guardar no puede estar vacío."

    if cat_key == "preferencias_y_notas":
        lista = perfil.setdefault("habitos_y_preferencias", {}).setdefault("notas_y_recordatorios_aprendidos", [])
    else:
        mem_struct = perfil.setdefault("memoria_estructurada", {})
        lista = mem_struct.setdefault(cat_key, [])

    if limpia not in lista:
        lista.append(limpia)
        if len(lista) > 30:
            del lista[:-30]
        guardar_perfil(perfil)
        return f"Guardado en memoria ({VALID_MEMORY_CATEGORIES[cat_key]}): '{limpia}'"
    return f"Ese dato ya estaba en tu memoria ({VALID_MEMORY_CATEGORIES[cat_key]})."


def olvidar_dato_memoria(texto_a_olvidar: str) -> str:
    """Elimina cualquier nota o dato de memoria a largo plazo que coincida con el texto indicado."""
    perfil = cargar_perfil()
    objetivo = (texto_a_olvidar or "").strip().lower()
    if not objetivo:
        return "Indica qué dato deseas olvidar."

    eliminados = 0
    notas = perfil.get("habitos_y_preferencias", {}).get("notas_y_recordatorios_aprendidos", [])
    nuevas_notas = [n for n in notas if objetivo not in n.lower()]
    eliminados += len(notas) - len(nuevas_notas)
    if "habitos_y_preferencias" in perfil:
        perfil["habitos_y_preferencias"]["notas_y_recordatorios_aprendidos"] = nuevas_notas

    mem_struct = perfil.get("memoria_estructurada", {})
    for cat_key, lista in list(mem_struct.items()):
        if isinstance(lista, list):
            nueva_lista = [item for item in lista if objetivo not in str(item).lower()]
            eliminados += len(lista) - len(nueva_lista)
            mem_struct[cat_key] = nueva_lista

    if eliminados > 0:
        guardar_perfil(perfil)
        return f"Se eliminaron {eliminados} registro(s) relacionados con '{texto_a_olvidar}' de tu memoria."
    return f"No se encontró ningún dato en memoria que contenga '{texto_a_olvidar}'."


def resumir_memoria_personal() -> str:
    """Devuelve un resumen legible de todo lo que el bot sabe sobre el usuario."""
    perfil = cargar_perfil()
    u = perfil.get("usuario", {})
    h = perfil.get("habitos_y_preferencias", {})
    mem_struct = perfil.get("memoria_estructurada", {})

    lines = [
        "🧠 <b>Memoria Personal a Largo Plazo:</b>",
        f"• <b>Nombre:</b> {u.get('nombre', 'Usuario')} ({u.get('rol', '')})",
    ]
    if u.get("institucion"):
        lines.append(f"• <b>Institución:</b> {u.get('institucion')}")
    if h.get("proyectos_principales"):
        lines.append(f"• <b>Proyectos clave:</b> {', '.join(h['proyectos_principales'])}")

    for cat_key, cat_label in VALID_MEMORY_CATEGORIES.items():
        if cat_key == "preferencias_y_notas":
            items = h.get("notas_y_recordatorios_aprendidos", [])
        else:
            items = mem_struct.get(cat_key, [])
        if items:
            lines.append(f"\n📌 <b>{cat_label}:</b>")
            for item in items:
                lines.append(f"  • {item}")

    return "\n".join(lines)


def cargar_historial(max_turnos: int = 10) -> list:
    """Carga los turnos recientes de conversación."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            hist = json.load(f)
            return hist[-max_turnos:]
    except Exception as e:
        logger.error(f"Error leyendo historial: {e}")
        return []


def registrar_turno(usuario: str, asistente: str):
    """Agrega un turno (pregunta/respuesta) al historial de conversación de corto plazo."""
    try:
        historial = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                historial = json.load(f)

        historial.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "usuario": usuario.strip(),
            "asistente": asistente.strip(),
        })

        historial = historial[-25:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(historial, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error registrando turno en historial: {e}")


def limpiar_historial_conversacion() -> str:
    """Borra el buffer de conversación a corto plazo (para empezar una charla limpia)."""
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        return "Memoria de conversación reciente reiniciada. Empezamos una sesión limpia."
    except Exception as e:
        return f"Error reiniciando memoria reciente: {e}"


def obtener_actividad_reciente_antigravity(limite: int = 6) -> list:
    """Lee las conversaciones recientes de Antigravity IDE si existe la base de datos local."""
    if not os.path.exists(ANTIGRAVITY_DB):
        return []
    try:
        conn = sqlite3.connect(ANTIGRAVITY_DB)
        c = conn.cursor()
        c.execute(
            """
            SELECT title, preview, last_modified_time
            FROM conversation_summaries
            WHERE length(title) > 0
            ORDER BY last_modified_time DESC
            LIMIT ?
            """,
            (limite,),
        )
        filas = c.fetchall()
        conn.close()

        actividades = []
        for t, prev, dt in filas:
            resumen = prev.strip() if prev else t.strip()
            fecha_str = dt.split()[0] if " " in str(dt) else str(dt)[:10]
            actividades.append({
                "titulo": t.strip(),
                "resumen": resumen[:120],
                "fecha": fecha_str,
            })
        return actividades
    except Exception as e:
        logger.error(f"Error leyendo actividad reciente de Antigravity IDE: {e}")
        return []


def formatear_contexto_memoria() -> str:
    """Genera el bloque textual de contexto que se inyecta en el prompt del agente."""
    perfil = cargar_perfil()
    historial = cargar_historial(max_turnos=8)
    actividad_ide = obtener_actividad_reciente_antigravity(limite=5)

    u = perfil.get("usuario", {})
    h = perfil.get("habitos_y_preferencias", {})
    trato = u.get("trato") or u.get("nombre") or "Usuario"

    lineas = [
        f"PERFIL Y HÁBITOS DE {trato.upper()} (Memoria a Largo Plazo):",
        f"- Usuario: {u.get('nombre', trato)} ({u.get('rol', '')})",
        f"- Estilo preferido: {h.get('estilo_respuestas', '')}",
    ]
    if u.get("institucion"):
        lineas.append(f"- Organización: {u['institucion']}")
    if h.get("proyectos_principales"):
        lineas.append(f"- Proyectos habituales: {', '.join(h['proyectos_principales'])}")

    notas = h.get("notas_y_recordatorios_aprendidos", [])
    if notas:
        lineas.append("- Preferencias y notas aprendidas:")
        for n in notas[-8:]:
            lineas.append(f"  • {n}")

    mem_struct = perfil.get("memoria_estructurada", {})
    for cat_key, cat_label in VALID_MEMORY_CATEGORIES.items():
        if cat_key == "preferencias_y_notas":
            continue
        items = mem_struct.get(cat_key, [])
        if items:
            lineas.append(f"- {cat_label}:")
            for item in items[-8:]:
                lineas.append(f"  • {item}")

    if actividad_ide:
        lineas.append("\nACTIVIDAD Y TRABAJO RECIENTE EN ANTIGRAVITY IDE (En tu PC):")
        for act in actividad_ide:
            lineas.append(f"  • [{act['fecha']}] {act['titulo']}")

    if historial:
        lineas.append("\nMEMORIA DE CONVERSACIÓN RECIENTE (Últimos mensajes de Telegram):")
        for t in historial:
            lineas.append(f"{trato}: {t.get('usuario')}")
            resp_corta = t.get("asistente", "").replace("\n", " ")
            if len(resp_corta) > 140:
                resp_corta = resp_corta[:140] + "..."
            lineas.append(f"Tú (Asistente): {resp_corta}")

    return "\n".join(lineas)
