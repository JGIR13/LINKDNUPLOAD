"""
Configuración central de la app.

Implementa el flag `modo_claves` descrito en el plan técnico:
  - "propio"      -> las credenciales se leen del .env del propio usuario (V1).
  - "gestionado"  -> las credenciales las provee la plataforma (V2, futuro).

Todo el resto del código (llm.py, linkedin_*.py) pide sus
credenciales a través de `get_credentials()` en vez de leer os.environ
directamente. Así, cuando en el futuro exista un modo "gestionado" (multiusuario,
claves propias de la plataforma), basta con cambiar esta función para que
lea de una base de datos de usuarios en vez del .env, sin tocar el resto
de módulos.
"""

import hashlib
import hmac
import os
import secrets
import shutil
from dataclasses import dataclass

from dotenv import load_dotenv

# encoding="utf-8-sig" evita un bug silencioso muy común en Windows: PowerShell
# (Out-File -Encoding utf8) añade un BOM al inicio del archivo, lo que hace que
# python-dotenv lea la primera variable como "﻿NOMBRE_VAR" en vez de
# "NOMBRE_VAR" y esa variable se pierda sin ningún error visible.
load_dotenv(encoding="utf-8-sig")

MODO_CLAVES = os.getenv("MODO_CLAVES", "propio")

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")  # assets de la propia app (CSS, fuentes, iconos) — SÍ van con el código
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")
ICONOS_DIR = os.path.join(STATIC_DIR, "icons", "emoji")


# ---------------------------------------------------------------------------
# V5.4: los DATOS del usuario (base de datos + imágenes subidas/generadas)
# viven FUERA de BASE_DIR (la carpeta donde está instalado el código de la
# app) — antes vivían dentro (data/app.db, static/generated, etc.), lo que
# significaba que reinstalar desde cero (descomprimir una versión nueva del
# zip en una carpeta nueva, o mover la instalación a otro sitio) los perdía
# sin avisar. Ahora se guardan en la carpeta de datos de aplicación del
# usuario (%LOCALAPPDATA% en Windows), independiente de dónde esté el
# código — así sobreviven a cualquier reinstalación. La primera vez que se
# arranca esta versión, si hay datos en el sitio antiguo y todavía no se
# migraron, se copian automáticamente (nunca se borra el original, por si
# acaso). Se puede forzar la carpeta con la variable de entorno
# LINKEDIN_AI_POSTER_DATOS (útil para desarrollo/tests).
# ---------------------------------------------------------------------------
def _carpeta_datos_persistentes() -> str:
    forzada = os.getenv("LINKEDIN_AI_POSTER_DATOS")
    if forzada:
        return forzada
    base = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "LinkedInAIPoster")


def _migrar_si_hace_falta(origen: str, destino: str):
    """Copia (nunca mueve ni borra) `origen` -> `destino` la primera vez que
    exista el origen y el destino todavía no exista — migración automática
    de una sola vez desde el sitio antiguo (dentro de BASE_DIR, versiones
    <= V5.3) al nuevo. Idempotente: en cualquier arranque posterior, con el
    destino ya presente, no hace nada."""
    if os.path.exists(destino) or not os.path.exists(origen):
        return
    try:
        if os.path.isdir(origen):
            shutil.copytree(origen, destino)
        else:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(origen, destino)
    except OSError:
        pass  # mejor arrancar con datos nuevos vacíos que no arrancar


_DATOS_DIR = _carpeta_datos_persistentes()
os.makedirs(_DATOS_DIR, exist_ok=True)

_migrar_si_hace_falta(os.path.join(BASE_DIR, "data", "app.db"), os.path.join(_DATOS_DIR, "app.db"))
DB_PATH = os.path.join(_DATOS_DIR, "app.db")

_migrar_si_hace_falta(os.path.join(STATIC_DIR, "generated"), os.path.join(_DATOS_DIR, "generated"))
_migrar_si_hace_falta(os.path.join(STATIC_DIR, "inspiracion"), os.path.join(_DATOS_DIR, "inspiracion"))
_migrar_si_hace_falta(os.path.join(STATIC_DIR, "perfil"), os.path.join(_DATOS_DIR, "perfil"))
GENERATED_IMG_DIR = os.path.join(_DATOS_DIR, "generated")
INSPIRACION_IMG_DIR = os.path.join(_DATOS_DIR, "inspiracion")
PERFIL_IMG_DIR = os.path.join(_DATOS_DIR, "perfil")

os.makedirs(GENERATED_IMG_DIR, exist_ok=True)
os.makedirs(INSPIRACION_IMG_DIR, exist_ok=True)
os.makedirs(PERFIL_IMG_DIR, exist_ok=True)

# --- Modelos de Gemini ---
# El naming de los modelos de Gemini cambia con el tiempo. Para no dejar la
# app "rota" si un modelo se renombra o deja de estar disponible, cada
# funcionalidad prueba una lista de candidatos en orden y usa el primero que
# funcione (ver llm.py). Puedes fijar uno concreto en tu .env
# (GEMINI_TEXT_MODEL) y se probará ese primero.
def _lista_sin_duplicados(*modelos):
    vistos, resultado = set(), []
    for m in modelos:
        if m and m not in vistos:
            vistos.add(m)
            resultado.append(m)
    return resultado


GEMINI_TEXT_MODEL_CANDIDATOS = _lista_sin_duplicados(
    os.getenv("GEMINI_TEXT_MODEL"),
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
)

# El cupo gratuito diario de Gemini es POR MODELO (confirmado por el propio
# 429 de Google: quotaId "GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
# así que cada candidato de la lista de arriba tiene su propio cupo
# independiente — si uno se agota, los demás siguen disponibles (ver
# llm._generar_con_fallback). Google no ofrece ninguna API pública para
# consultar cuánto queda antes de que ocurra un 429 (solo un panel web en
# ai.dev/rate-limit), así que este número es una ESTIMACIÓN de partida para
# el indicador de uso de la interfaz — en cuanto un modelo se agota de
# verdad, se sustituye por el número real que Google comunica en ese
# momento (`quotaValue` del propio error), guardado en
# db.uso_gemini_diario. Puede no coincidir exactamente con el cupo real de
# cada modelo mientras no se haya agotado todavía hoy.
GEMINI_LIMITE_ESTIMADO_POR_MODELO = 20


def fingerprint_clave_gemini(api_key: str | None) -> str:
    """Huella corta y NO reversible de la clave de Gemini activa (nunca la
    propia clave). Sirve para que db.uso_gemini_diario sepa, por cada
    modelo, BAJO QUÉ CLAVE se registró cada conteo/agotamiento de hoy — así,
    cuando alguien cambia de clave desde 🛠️ Administración (p. ej. para
    probar otra de sus proyectos de Google AI Studio), la app deja de dar
    por hecho, sin comprobarlo, que la cuota sigue agotada: vuelve a
    intentarlo con la clave nueva y registra un estado propio para ella,
    en vez de heredar ciegamente el "agotado" que dejó la clave anterior.
    Cadena vacía si no hay clave configurada (nunca debe romper nada)."""
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
# Nota V4: ya no hay GEMINI_IMAGE_MODEL_CANDIDATOS — se eliminó el modo de
# imagen ilustrativa (Gemini image + respaldo Pollinations.ai). El único
# formato con imagen es la infografía de lista, compuesta 100% en código
# (image_infografia.py) a partir del texto que ya genera el modelo de arriba.

# --- Paletas para el formato "Infografía de lista" ---
# A diferencia del estilo visual libre (texto que se le pasa al modelo de
# imagen), aquí necesitamos colores hexadecimales exactos porque el diseño
# se compone 100% en código (Pillow), sin depender de ningún proveedor de
# generación de imagen — así este formato es siempre gratuito y fiable,
# sin caer nunca en la cuota de Gemini ni en el respaldo de Pollinations.
INFOGRAFIA_PALETAS = {
    "Azul corporativo": {
        "primario": "#0A66C2", "acento": "#F5B400", "fondo": "#F4F6F8",
        "texto": "#111827", "texto_claro": "#4B5563", "tarjeta": "#FFFFFF", "borde": "#E2E8F0",
    },
    "Oscuro elegante": {
        "primario": "#111827", "acento": "#D4AF37", "fondo": "#F7F7F5",
        "texto": "#111827", "texto_claro": "#52525B", "tarjeta": "#FFFFFF", "borde": "#E4E4E7",
    },
    "Verde tech": {
        "primario": "#065F46", "acento": "#10B981", "fondo": "#F1F8F5",
        "texto": "#0F172A", "texto_claro": "#3F5B54", "tarjeta": "#FFFFFF", "borde": "#DCEEE6",
    },
    "Morado creativo": {
        "primario": "#4C1D95", "acento": "#EC4899", "fondo": "#F8F5FC",
        "texto": "#1E1033", "texto_claro": "#5B4B75", "tarjeta": "#FFFFFF", "borde": "#E9DFF5",
    },
    "Minimal gris": {
        "primario": "#1F2937", "acento": "#F97316", "fondo": "#F5F5F5",
        "texto": "#111111", "texto_claro": "#525252", "tarjeta": "#FFFFFF", "borde": "#E5E5E5",
    },
}
INFOGRAFIA_PALETA_DEFECTO = "Azul corporativo"

# --- Iconos para la "Infografía de lista" ---
# Set curado de iconos (Twemoji, descargados una vez y empaquetados en
# static/icons/emoji/ — ver ese directorio y su ATTRIBUTION.txt) que el LLM
# elige por clave exacta (nunca genera un emoji libre: evita problemas de
# codificación/variantes y garantiza que el archivo siempre existe).
INFOGRAFIA_ICONOS = [
    "laptop", "desktop", "mobile", "plug", "gear", "wrench", "tools", "lock", "unlock", "shield",
    "globe", "cloud", "satellite", "link", "puzzle", "chart_bar", "chart_up", "chart_down", "brain",
    "idea", "rocket", "target", "check", "cycle", "bolt", "cabinet", "package", "abacus", "search",
    "calendar", "stopwatch", "alarm", "memo", "books", "graduation", "handshake", "people", "chat",
    "megaphone", "trophy", "seedling", "recycle", "money", "card", "compass", "map", "mouse", "keyboard",
    "key", "toolbox", "ruler", "testtube", "microscope", "construction", "office", "phone", "mail",
    "paperclip", "stethoscope", "heart", "clover", "sparkle_star", "star", "fire", "running", "palette",
    "music", "cart", "label", "camera", "clapper", "pen", "pencil", "scale", "receipt", "hospital",
    "car", "plane", "house",
]
INFOGRAFIA_ICONO_DEFECTO = "idea"


@dataclass
class Credentials:
    gemini_api_key: str | None
    linkedin_client_id: str | None
    linkedin_client_secret: str | None
    linkedin_redirect_uri: str | None


def get_credentials() -> Credentials:
    """
    Punto único de lectura de credenciales de la INSTALACIÓN completa:
    Client ID/Secret de la app de LinkedIn Developer, redirect URI y clave
    de API de Gemini. Son GLOBALES — las comparten todas las cuentas de
    usuario (ver db.py, tabla `cuentas`); no confundir con la conexión
    personal de LinkedIn de cada cuenta (esa vive en `cuentas` y se lee con
    db.obtener_cuenta(cuenta_id), no aquí.

    En modo "propio" (uso local), se lee del .env, PERO cualquier
    credencial que se haya guardado desde 🛠️ Administración (tabla
    `config_global`) tiene prioridad sobre el .env — no hace falta editar
    el .env a mano, aunque seguir usándolo sigue funcionando igual si se
    prefiere y no se ha guardado nada desde el panel.

    En un futuro modo "gestionado", esta función leería las claves de la
    plataforma en vez de las de esta instalación, sin que llm.py /
    linkedin_*.py cambien una sola línea.
    """
    if MODO_CLAVES == "propio":
        linkedin_client_id = os.getenv("LINKEDIN_CLIENT_ID") or None
        linkedin_client_secret = os.getenv("LINKEDIN_CLIENT_SECRET") or None
        linkedin_redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI") or "http://localhost:8501"
        gemini_api_key = os.getenv("GEMINI_API_KEY") or None

        # Import diferido (no al nivel de módulo) porque db.py importa
        # DB_PATH/hash_password de este mismo módulo — importar db arriba
        # crearía un ciclo. Para cuando get_credentials() se llama de
        # verdad en tiempo de ejecución, db ya está completamente cargado.
        try:
            import db
            global_cfg = db.obtener_config_global()
        except Exception:
            global_cfg = {}
        if global_cfg:
            linkedin_client_id = global_cfg.get("linkedin_client_id") or linkedin_client_id
            linkedin_client_secret = global_cfg.get("linkedin_client_secret") or linkedin_client_secret
            linkedin_redirect_uri = global_cfg.get("linkedin_redirect_uri") or linkedin_redirect_uri
            gemini_api_key = global_cfg.get("gemini_api_key") or gemini_api_key

        return Credentials(
            gemini_api_key=gemini_api_key,
            linkedin_client_id=linkedin_client_id,
            linkedin_client_secret=linkedin_client_secret,
            linkedin_redirect_uri=linkedin_redirect_uri,
        )

    # modo "gestionado" -> reservado para un futuro hosting compartido con claves de la plataforma
    raise NotImplementedError(
        "El modo 'gestionado' no está implementado todavía. De momento usa MODO_CLAVES=propio en tu .env."
    )


# ---------------------------------------------------------------------------
# Contraseñas de cuenta (V5, multiusuario): cada persona tiene su propia
# cuenta con email + contraseña (tabla `cuentas` en db.py) — reemplaza el
# candado de una sola contraseña de administrador de versiones anteriores.
# Estas dos funciones son utilidades genéricas de hashing que usa el resto
# del código (login, alta de cuentas, cambio de contraseña) — no dependen
# de qué cuenta es. El hash usa PBKDF2-HMAC-SHA256 con sal aleatoria por
# contraseña (sin depender de bcrypt/passlib, que no están en
# requirements.txt); la comparación usa hmac.compare_digest para evitar
# timing attacks triviales. Pensado para uso de un equipo pequeño y
# conocido (no para exponer la instalación a desconocidos en internet).
# ---------------------------------------------------------------------------

_PBKDF2_ITERACIONES = 200_000


def hash_password(password: str) -> tuple[str, str]:
    """Devuelve (hash_hex, salt_hex) para una contraseña nueva."""
    salt = secrets.token_hex(16)
    hash_hex = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERACIONES
    ).hex()
    return hash_hex, salt


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    if not hash_hex or not salt_hex:
        return False
    intento = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERACIONES
    ).hex()
    return hmac.compare_digest(intento, hash_hex)
