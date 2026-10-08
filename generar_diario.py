"""
Script standalone (SIN Streamlit) para la "🤖 Automatización Total".

Pensado para dispararse solo, sin que nadie abra la app, vía el Programador
de tareas de Windows (ver generar_diario.bat y las instrucciones en la
página "📅 Generación diaria" de la app / README) — como un LATIDO
frecuente (cada 15-30 minutos), no como un disparo único al día. Recorre
TODAS las cuentas de la instalación y, para cada una que tenga la
Automatización Total activada, comprueba si ya ha llegado su hora
configurada (`automatizacion_hora`, por defecto 09:00); si aún no ha
llegado, no hace nada y lo comprueba de nuevo en la siguiente ejecución
del latido. En cuanto llega la hora, genera lo que falte de su plan del
día (según su propio reparto configurado) y, si además activó
explícitamente "auto-publicar", publica directo en LinkedIn sin revisión
manual — si no, deja los posts como borrador para que esa persona los
revise y publique a mano.

Es seguro ejecutarlo cada pocos minutos, varias veces al día o varios días
seguidos sin supervisión: nunca duplica el plan de un día ya creado, ni
repite un item ya generado/publicado (ver daily.asegurar_plan_del_dia) ni
antes de su hora configurada, y un fallo en la cuenta de una persona no
afecta a las demás.

Uso:
    python generar_diario.py

Salida: un resumen por consola Y por archivo (logs/generar_diario.log, con
rotación — ver `_configurar_logging()`), ya que al dispararse vía el
Programador de tareas de Windows no hay ninguna ventana de consola visible
donde leer el resultado. Código de salida 1 si algún item de alguna cuenta
terminó en error, para que el Programador de tareas lo pueda marcar como
fallido.
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

import daily
import db
from config import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "generar_diario.log")


def _configurar_logging() -> logging.Logger:
    """Registra en consola (por si se ejecuta a mano) Y en un archivo con
    rotación (logs/generar_diario.log, hasta 1 MB x 5 archivos ≈ historial
    de varios meses de ejecuciones diarias) — así, cuando el Programador de
    tareas de Windows lo dispara sin supervisión, queda un registro
    consultable sin depender de una ventana de consola que nadie ve."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("generar_diario")
    logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    handler_archivo = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler_archivo.setFormatter(formato)
    logger.addHandler(handler_archivo)

    handler_consola = logging.StreamHandler(sys.stdout)
    handler_consola.setFormatter(formato)
    logger.addHandler(handler_consola)

    return logger


def _procesar_cuenta(log: logging.Logger, cuenta: dict) -> bool:
    """Genera el plan del día de UNA cuenta si tiene la Automatización
    Total activada. Devuelve True si hubo algún error en alguno de sus
    items (para el código de salida del script)."""
    etiqueta = cuenta.get("email") or f"cuenta #{cuenta['id']}"

    if not cuenta.get("activo"):
        return False  # cuenta desactivada por un administrador: se ignora en silencio

    parametros = db.obtener_parametros(cuenta["id"])
    if not parametros or not bool(parametros.get("automatizacion_total_activa")):
        return False  # esta cuenta no activó la Automatización Total: nada que hacer

    hora_configurada = (parametros.get("automatizacion_hora") or "09:00").strip()
    if datetime.now().strftime("%H:%M") < hora_configurada:
        return False  # aún no ha llegado su hora programada — se comprobará de nuevo en el próximo latido

    resultados = daily.generar_pendientes_del_dia(cuenta["id"])
    if not resultados:
        log.info(f"[{etiqueta}] El reparto diario es 0/0 — no hay nada que generar hoy.")
        return False

    hubo_error = False
    log.info(f"[{etiqueta}] Plan de hoy: {len(resultados)} item(s).")
    for item in resultados:
        estado = item.get("estado")
        tipo = item.get("tipo")
        if estado == "error":
            hubo_error = True
            log.info(f"  ✗ [{etiqueta}] {tipo}: ERROR — {item.get('error')}")
        elif estado == "cuota_agotada":
            # No se cuenta como error: es un límite temporal de Gemini, no un
            # fallo de esta cuenta — el item queda 'pendiente' y se reintenta
            # solo en el próximo latido, sin marcar el script como fallido.
            log.info(f"  ⏳ [{etiqueta}] {tipo}: cuota de Gemini agotada por ahora — se reintentará en el próximo latido.")
        elif estado == "publicado":
            log.info(f"  ✓ [{etiqueta}] {tipo}: publicado en LinkedIn (post #{item.get('post_id')})")
        elif estado == "generado":
            log.info(f"  ✓ [{etiqueta}] {tipo}: generado como borrador (post #{item.get('post_id')}) — pendiente de publicar")
        else:
            log.info(f"  · [{etiqueta}] {tipo}: {estado}")
    return hubo_error


def main() -> int:
    log = _configurar_logging()
    db.init_db()

    cuentas = db.listar_cuentas()
    if not cuentas:
        log.info("[generar_diario] Todavía no hay ninguna cuenta creada en esta instalación — no hay nada que hacer.")
        return 0

    hubo_algun_error = False
    alguna_activa = False
    for cuenta in cuentas:
        parametros = db.obtener_parametros(cuenta["id"])
        if cuenta.get("activo") and parametros and bool(parametros.get("automatizacion_total_activa")):
            alguna_activa = True
        if _procesar_cuenta(log, cuenta):
            hubo_algun_error = True

    if not alguna_activa:
        log.info(
            "[generar_diario] Ninguna cuenta tiene la Automatización Total activada en "
            "📅 Generación diaria — no se generó nada."
        )

    return 1 if hubo_algun_error else 0


if __name__ == "__main__":
    sys.exit(main())
