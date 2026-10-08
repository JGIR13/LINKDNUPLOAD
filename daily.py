"""
"Generación diaria" — planifica y genera automáticamente los posts del día
de UNA cuenta según un reparto fijo configurable (nº de infografías + nº de
posts de solo texto por día, en 📅 Generación diaria).

Este módulo es el núcleo compartido por tres caminos:
- La página "📅 Generación diaria" de la app (cola MANUAL, por defecto): la
  persona decide cuándo generar cada item pendiente, revisa el resultado y
  publica ella misma — igual que siempre.
- `generar_diario.py` (script standalone, sin Streamlit): pensado para
  dispararse solo, vía el Programador de tareas de Windows, para CADA
  cuenta que tenga activada la "🤖 Automatización Total" — puede además
  publicar directo en LinkedIn sin revisión manual si así se configura
  explícitamente.
- La "🚀 Subida masiva" de la propia página "📅 Generación diaria": genera
  una tanda de N posts de golpe (no repartidos por hora), totalmente
  configurable (mezcla de formatos, paleta, modo claro/oscuro) e
  independiente del plan diario — ver `generar_lote`.

El plan de un día es idempotente: `asegurar_plan_del_dia()` solo crea items
la primera vez que se llama para una fecha (y una cuenta) — llamarlo varias
veces el mismo día nunca duplica items ni vuelve a generar lo ya hecho.

Temáticas rotativas: si la cuenta configuró una lista de temas (ver
db.siguiente_tema_rotacion), cada item generado automáticamente usa el
siguiente tema de la lista en vez de dejar que la IA proponga un tema
completamente libre — pero la IA sigue eligiendo un ángulo concreto dentro
de esa temática, no repite la misma frase genérica cada vez.

No hay ningún límite técnico real que obligue a un tope diario — en el
nivel gratuito de Gemini el límite es de cientos de peticiones/día (ver
README) — el reparto diario es una decisión de producto de cada usuario,
no una barrera de la API.
"""

import os
import time
from datetime import date, datetime, timedelta

import config
import db
import image_infografia
import linkedin_oauth
import linkedin_publish
import llm


def hoy() -> str:
    return date.today().isoformat()


def asegurar_plan_del_dia(cuenta_id: int, fecha: str | None = None) -> list[dict]:
    """Crea (solo si no existe ya) el plan del día de esta cuenta según el
    reparto configurado, y devuelve el plan completo de esa fecha."""
    fecha = fecha or hoy()
    plan_existente = db.listar_plan_dia(cuenta_id, fecha)
    if plan_existente:
        return plan_existente

    parametros = db.obtener_parametros(cuenta_id)
    n_infografia = int(parametros.get("reparto_diario_infografia") or 0)
    n_texto = int(parametros.get("reparto_diario_texto") or 0)
    if n_infografia:
        db.crear_items_plan_dia(cuenta_id, fecha, "infografia", n_infografia)
    if n_texto:
        db.crear_items_plan_dia(cuenta_id, fecha, "texto", n_texto)
    return db.listar_plan_dia(cuenta_id, fecha)


def resincronizar_plan_hoy(cuenta_id: int, fecha: str | None = None) -> dict:
    """A diferencia de `asegurar_plan_del_dia` (que solo crea el plan la
    PRIMERA vez y luego nunca lo vuelve a tocar), esta función AJUSTA el
    plan ya existente de `fecha` para que coincida con el reparto que
    acaba de guardarse — se llama justo después de
    `db.guardar_reparto_diario()`, para que "Plan de hoy" no se quede
    mostrando un reparto anterior.

    Por cada tipo ('infografia'/'texto'):
    - Si el plan tiene MENOS items de los que pide el nuevo reparto, se
      añaden 'pendiente' los que falten (igual que si el plan se acabara
      de crear).
    - Si el plan tiene MÁS, se quitan del plan los 'pendiente' sobrantes
      (los más recientes primero) — nunca se toca un item ya
      'generado'/'publicado'/'error': si ya se generó contenido, ese
      contenido no desaparece solo porque se reduzca el reparto. Si no
      hay suficientes 'pendiente' para llegar al nuevo objetivo (porque
      ya se generó más de lo que el nuevo reparto pide), el plan
      simplemente se queda con lo ya generado, sin añadir ni quitar nada
      más de ese tipo.

    Si el plan de hoy todavía no existe (nadie ha visitado "📅 Generación
    diaria" hoy), esto lo crea directamente con el reparto ya actualizado
    — mismo resultado que si se hubiera llamado a `asegurar_plan_del_dia`
    después de guardar.

    Devuelve un resumen {"añadidos": {...}, "quitados": {...}} por tipo,
    útil para informar en pantalla qué cambió.
    """
    fecha = fecha or hoy()
    parametros = db.obtener_parametros(cuenta_id)
    objetivo = {
        "infografia": int(parametros.get("reparto_diario_infografia") or 0),
        "texto": int(parametros.get("reparto_diario_texto") or 0),
    }
    plan_actual = db.listar_plan_dia(cuenta_id, fecha)
    resumen = {"añadidos": {}, "quitados": {}}

    for tipo, n_objetivo in objetivo.items():
        items_tipo = [it for it in plan_actual if it["tipo"] == tipo]
        actuales = len(items_tipo)
        if actuales < n_objetivo:
            faltan = n_objetivo - actuales
            db.crear_items_plan_dia(cuenta_id, fecha, tipo, faltan)
            resumen["añadidos"][tipo] = faltan
        elif actuales > n_objetivo:
            sobran = actuales - n_objetivo
            pendientes = sorted(
                (it for it in items_tipo if it["estado"] == "pendiente"),
                key=lambda it: it["id"], reverse=True,
            )
            a_quitar = pendientes[:sobran]
            if a_quitar:
                db.eliminar_items_plan_dia([it["id"] for it in a_quitar])
                resumen["quitados"][tipo] = len(a_quitar)

    return resumen


def _temas_recientes(cuenta_id: int, limite: int = 15) -> list[str]:
    posts = db.listar_posts(cuenta_id, limit=limite)
    return [p["tema"] for p in posts if p.get("tema")]


def _elegir_tema(cuenta_id: int, parametros: dict) -> str:
    """Elige el tema de un item generado automáticamente: si la cuenta
    configuró temáticas rotativas, usa la siguiente de la lista (pidiendo a
    la IA un ángulo concreto dentro de ella); si no, deja que la IA
    proponga un tema completamente libre, como siempre."""
    tema_base = db.siguiente_tema_rotacion(cuenta_id)
    return llm.sugerir_tema_automatico(parametros, evitar=_temas_recientes(cuenta_id), tema_base=tema_base)


def _construir_marca(cuenta_id: int, parametros: dict) -> dict | None:
    if not parametros.get("incluir_marca_personal_default"):
        return None
    cuenta = db.obtener_cuenta(cuenta_id)
    foto = parametros.get("foto_perfil_path")
    modo = parametros.get("marca_personal_modo_default") or "foto"
    ruta_foto = foto if (modo == "foto" and foto and os.path.exists(foto)) else None
    return {
        "nombre": (cuenta and cuenta.get("linkedin_nombre")) or (cuenta and cuenta.get("nombre")) or "Tu nombre",
        "rol": parametros.get("sector") or "",
        "ruta_foto": ruta_foto,
    }


def _publicar_si_procede(cuenta_id: int, post_id: int, texto: str, imagen_path: str) -> str:
    """Intenta publicar en LinkedIn (refrescando el token si hiciera falta).
    Devuelve el estado final: 'publicado', 'generado' si no hay cuenta de
    LinkedIn conectada (el post se queda como borrador listo para publicar
    a mano), o 'duplicado_omitido' si este mismo texto YA se publicó hace
    poco para esta cuenta — red de seguridad para nunca publicar el mismo
    contenido dos veces en LinkedIn, sea cual sea la causa (una generación
    repetida, un reintento, una doble pulsación de un botón)."""
    cuenta = db.obtener_cuenta(cuenta_id)
    if not (cuenta and cuenta.get("linkedin_access_token")):
        return "generado"

    if db.existe_publicado_reciente(cuenta_id, texto):
        return "duplicado_omitido"

    if not linkedin_oauth.token_valido(cuenta) and cuenta.get("linkedin_refresh_token"):
        datos_token = linkedin_oauth.refrescar_token(cuenta["linkedin_refresh_token"])
        fecha_exp = (
            datetime.utcnow() + timedelta(seconds=datos_token.get("expires_in", 3600))
        ).isoformat()
        db.guardar_tokens_linkedin(
            cuenta_id,
            datos_token["access_token"],
            datos_token.get("refresh_token", cuenta["linkedin_refresh_token"]),
            fecha_exp,
        )

    post_id_linkedin = linkedin_publish.publicar_post(cuenta_id, texto, imagen_path or None)
    db.marcar_publicado(post_id, post_id_linkedin)
    return "publicado"


def _generar_pieza(
    cuenta_id: int, tipo: str, parametros: dict,
    paleta_valor: str | None = None, oscuro: bool | None = None,
) -> tuple[str, str, str]:
    """
    Genera el contenido de UNA pieza (tema + texto, y su imagen si
    `tipo == 'infografia'`) SIN guardarla como post ni tocar ninguna tabla
    de planificación — es el núcleo compartido por `generar_item` (plan
    diario / cola manual) y `generar_lote` (subida masiva), para no
    duplicar la lógica de generación entre los dos caminos.

    `paleta_valor` y `oscuro` permiten sobrescribir, solo para esta pieza,
    la paleta/estilo por defecto de la cuenta (usado por la subida masiva,
    que es completamente configurable por tanda) — si se omiten, se usan
    los valores por defecto guardados en `parametros`, igual que siempre.
    """
    inspiracion = db.listar_inspiracion(cuenta_id)
    inspiracion_relevante = [i for i in inspiracion if i["favorito"]] or inspiracion

    tema = _elegir_tema(cuenta_id, parametros)
    variantes = llm.generar_variantes_texto(tema, parametros, inspiracion_relevante)
    texto = variantes[0]

    imagen_path = ""
    if tipo == "infografia":
        datos_infografia = llm.generar_infografia_contenido(
            tema, parametros, inspiracion_relevante,
            num_items=int(parametros.get("infografia_num_items_defecto") or 8),
        )
        paleta_hex = db.resolver_paleta_infografia(
            cuenta_id, paleta_valor or parametros.get("infografia_paleta_defecto") or config.INFOGRAFIA_PALETA_DEFECTO,
        )
        es_oscuro = (
            (parametros.get("infografia_estilo_defecto") or "oscuro") == "oscuro" if oscuro is None else oscuro
        )
        imagen_path = image_infografia.generar_infografia(
            datos_infografia, paleta_hex, marca=_construir_marca(cuenta_id, parametros), oscuro=es_oscuro,
        )
    return tema, texto, imagen_path


def generar_item(cuenta_id: int, item: dict, publicar: bool = False) -> dict:
    """
    Genera el contenido de UN item pendiente del plan de `cuenta_id` (tema
    automático + texto, y su imagen si es infografía), lo guarda como post,
    y opcionalmente lo publica en LinkedIn directo (solo si `publicar=True`).

    Nunca lanza: cualquier error queda registrado en el propio item
    ('estado': 'error', 'error': mensaje) para que la interfaz o el log del
    script lo muestren, sin tumbar el resto del plan del día.

    Excepción: si Gemini responde que se agotó la cuota gratuita
    (`llm.CuotaGeminiAgotada`), el item NO se marca como 'error' — se deja
    en 'pendiente' tal cual estaba, para que un intento posterior (cuando la
    cuota se recupere) pueda generarlo sin necesitar intervención manual. El
    resultado devuelto se marca con 'estado': 'cuota_agotada' para que el
    llamador (la interfaz, o `generar_pendientes_del_dia`) lo distinga de un
    fallo normal y pueda cortar el resto de la tanda en vez de seguir
    insistiendo contra una API saturada.
    """
    try:
        parametros = db.obtener_parametros(cuenta_id)
        tema, texto, imagen_path = _generar_pieza(cuenta_id, item["tipo"], parametros)

        post_id = db.crear_post(cuenta_id, tema, texto, imagen_path)
        estado = _publicar_si_procede(cuenta_id, post_id, texto, imagen_path) if publicar else "generado"

        db.actualizar_item_plan_dia(item["id"], estado=estado, post_id=post_id)
        return {**item, "estado": estado, "post_id": post_id}
    except llm.CuotaGeminiAgotada as e:
        return {**item, "estado": "cuota_agotada", "error": str(e)}
    except Exception as e:
        db.actualizar_item_plan_dia(item["id"], estado="error", error=str(e))
        return {**item, "estado": "error", "error": str(e)}


def generar_lote(
    cuenta_id: int, tipos: list[str], publicar: bool = False,
    paleta_valor: str | None = None, oscuro: bool | None = None,
) -> list[dict]:
    """
    Subida masiva: genera una TANDA de posts "de golpe", uno por cada
    elemento de `tipos` (p. ej. ``['infografia', 'infografia', 'texto']``
    para 2 infografías + 1 de solo texto, en ese orden) — a diferencia del
    plan diario, no crea ni toca ninguna fila de `generacion_diaria`, así
    que puede lanzarse cualquier día sin interferir con el plan automático
    de ese mismo día ni con la cola manual.

    `paleta_valor`/`oscuro` se aplican a TODAS las infografías de la tanda
    (la subida masiva es una configuración de un solo uso, independiente de
    los valores por defecto guardados de la cuenta). Si `publicar=True`, se
    publica cada pieza directo en LinkedIn a medida que se genera, con una
    pequeña pausa entre publicaciones consecutivas — no por ningún límite
    real de la API, sino para no volcar varios posts en el feed de la
    persona en cuestión de segundos.

    Nunca lanza: cada pieza que falle queda registrada en su propio
    resultado ('estado': 'error') sin tumbar el resto de la tanda.

    Excepción: si Gemini agota la cuota gratuita a mitad de la tanda
    (`llm.CuotaGeminiAgotada`), se añade UN solo resultado con
    'estado': 'cuota_agotada' y se corta la tanda ahí mismo — seguir
    probando el resto de piezas contra una cuota ya agotada solo produce
    más fallos idénticos sin ninguna posibilidad de éxito.
    """
    parametros = db.obtener_parametros(cuenta_id)
    resultados = []
    for i, tipo in enumerate(tipos):
        try:
            tema, texto, imagen_path = _generar_pieza(
                cuenta_id, tipo, parametros, paleta_valor=paleta_valor, oscuro=oscuro,
            )
            post_id = db.crear_post(cuenta_id, tema, texto, imagen_path)
            if publicar:
                if i > 0:
                    time.sleep(2)
                estado = _publicar_si_procede(cuenta_id, post_id, texto, imagen_path)
            else:
                estado = "generado"
            resultados.append({"tipo": tipo, "estado": estado, "post_id": post_id, "tema": tema})
        except llm.CuotaGeminiAgotada as e:
            resultados.append({"tipo": tipo, "estado": "cuota_agotada", "error": str(e)})
            break
        except Exception as e:
            resultados.append({"tipo": tipo, "estado": "error", "error": str(e)})
    return resultados


def generar_pendientes_del_dia(cuenta_id: int, fecha: str | None = None, publicar: bool | None = None) -> list[dict]:
    """
    Genera TODOS los items 'pendiente' del plan del día de esta cuenta
    (creándolo antes si hace falta). Si `publicar` es None, se usa la
    preferencia guardada de esta cuenta (solo publica si su Automatización
    Total está activa Y "auto-publicar" está encendido) — pásalo en
    True/False explícitamente para forzar un comportamiento (p. ej. la cola
    manual de la app siempre llama con `publicar=False`, para no publicar
    nada sin que la persona lo revise primero).

    Si en algún punto Gemini responde que se agotó la cuota gratuita, se
    corta el resto del bucle inmediatamente (el item que falló queda
    'pendiente' en la base de datos, listo para el próximo intento) en vez
    de seguir insistiendo, uno a uno, contra una API ya saturada — así se
    evita la tanda de errores idénticos y la espera inútil.
    """
    fecha = fecha or hoy()
    plan = asegurar_plan_del_dia(cuenta_id, fecha)

    if publicar is None:
        parametros = db.obtener_parametros(cuenta_id)
        publicar = bool(parametros.get("automatizacion_total_activa")) and bool(
            parametros.get("automatizacion_auto_publicar")
        )

    resultados = []
    for item in plan:
        if item["estado"] != "pendiente":
            resultados.append(item)
            continue
        resultado = generar_item(cuenta_id, item, publicar=publicar)
        resultados.append(resultado)
        if resultado.get("estado") == "cuota_agotada":
            break
    return resultados
