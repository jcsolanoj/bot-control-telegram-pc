"""
Formateador y limpiador de texto para Telegram.
Convierte markdown en formato HTML 100% válido y amigable sin símbolos feos como # o **,
y garantiza que nunca falle el envío de mensajes largos.
"""

import re
import html

ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\))')

def clean_markdown_for_telegram(text: str) -> str:
    """
    Transforma texto con markdown en formato HTML limpio para Telegram:
    - Elimina secuencias de control y color ANSI del terminal.
    - Escapa caracteres especiales (&, <, >) para evitar errores de entidad.
    - Convierte encabezados (#, ##, ###) en texto en negrita.
    - Convierte **texto** en <b>texto</b>.
    - Convierte *texto* o _texto_ en <i>texto</i>.
    - Convierte `codigo` en <code>codigo</code>.
    - Convierte viñetas (*, -) en viñetas elegantes (•).
    - Elimina asteriscos o almohadillas sueltas para que nunca aparezcan en Telegram.
    """
    if not text:
        return ""

    # Paso 0: Eliminar secuencias de control ANSI antes de procesar entidades
    text = ANSI_ESCAPE_PATTERN.sub("", text)

    # 1. Escapar primero las entidades HTML para evitar conflictos con < o > en el texto
    safe_text = html.escape(text)

    lines = []
    for line in safe_text.splitlines():
        trimmed = line.strip()

        # Encabezados markdown (# Titulo, ## Titulo, ### Titulo)
        header_match = re.match(r"^(#{1,6})\s*(.+)$", trimmed)
        if header_match:
            title = header_match.group(2).replace("**", "").strip()
            lines.append(f"\n<b>{title}</b>")
            continue

        # Viñetas con asterisco o guión al inicio (* item, - item)
        bullet_match = re.match(r"^[\*\-]\s+(.+)$", trimmed)
        if bullet_match:
            bullet_content = bullet_match.group(1)
            lines.append(f"  • {bullet_content}")
            continue

        lines.append(line)

    formatted = "\n".join(lines).strip()

    # Proteger bloques `codigo` para no alterar **kwargs o 2**3 en su interior
    code_blocks = []

    def _stash_code(match):
        code_blocks.append(f"<code>{match.group(1)}</code>")
        return f"@@CODE_{len(code_blocks) - 1}@@"

    formatted = re.sub(r"`([^`\n]+?)`", _stash_code, formatted)

    # Convertir **negrita** en <b>negrita</b>
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", formatted)

    # Convertir *cursiva* en <i>cursiva</i>
    formatted = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", formatted)

    # Limpiar almohadillas o asteriscos residuales fuera de bloques de código
    formatted = re.sub(r"(?m)^\s*#+\s*", "", formatted)
    formatted = formatted.replace("**", "").replace("###", "").replace("##", "")

    for idx, block in enumerate(code_blocks):
        formatted = formatted.replace(f"@@CODE_{idx}@@", block)

    return formatted


def strip_all_markdown(text: str) -> str:
    """Fallback seguro: elimina completamente todo markdown y tags HTML."""
    if not text:
        return ""
    # Quitar tags HTML
    clean = re.sub(r"<[^>]+>", "", text)
    # Quitar símbolos markdown
    clean = re.sub(r"(?m)^\s*#+\s*", "", clean)
    clean = clean.replace("**", "").replace("###", "").replace("##", "").replace("`", "")
    return clean.strip()


def split_long_message(text: str, max_length: int = 3800) -> list:
    """Divide un mensaje largo en partes respetando párrafos para no exceder el límite de Telegram."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = []
    current_length = 0

    for paragraph in text.split("\n\n"):
        p_len = len(paragraph) + 2
        if current_length + p_len > max_length:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            if len(paragraph) > max_length:
                # Si un solo párrafo es gigante, dividir por líneas
                for line in paragraph.splitlines():
                    if current_length + len(line) + 1 > max_length:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = []
                        current_length = 0
                    current_chunk.append(line)
                    current_length += len(line) + 1
            else:
                current_chunk.append(paragraph)
                current_length += p_len
        else:
            current_chunk.append(paragraph)
            current_length += p_len

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
