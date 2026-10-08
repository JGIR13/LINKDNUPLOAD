"""
Motor de generación de texto (sección 5 del plan técnico).

Combina parámetros por defecto (tono, objetivo, temática, audiencia...) +
ejemplos de inspiración (texto e imágenes) + tema del usuario en un prompt
para Gemini, y devuelve 2-3 variantes de texto para LinkedIn.
"""

import json
import mimetypes
import re

from google import genai
from google.genai import types

import db
from config import (
    GEMINI_LIMITE_ESTIMADO_POR_MODELO,
    GEMINI_TEXT_MODEL_CANDIDATOS,
    INFOGRAFIA_ICONO_DEFECTO,
    INFOGRAFIA_ICONOS,
    fingerprint_clave_gemini,
    get_credentials,
)


def _prompt_infografia(num_items: int) -> str:
    lista_iconos = ", ".join(INFOGRAFIA_ICONOS)
    return f"""Eres un experto en contenido educativo para infografías de LinkedIn en español.

Tu tarea es estructurar un tema en una lista numerada de puntos breves, al estilo
de una infografía profesional tipo "N cosas que debes saber sobre X" — cada punto
es un término/concepto corto (1-4 palabras) con una descripción de una frase y un
icono que lo represente visualmente.

Reglas estrictas:
- Devuelve EXACTAMENTE el número de puntos pedido, ni más ni menos.
- Cada "termino" debe ser muy corto (1-4 palabras, como una etiqueta o título de concepto).
- Cada "descripcion" debe ser una frase clara y concisa (máximo ~90 caracteres), sin cortarse a medias.
- Para cada punto y para "icono_principal", elige la clave que mejor lo represente de esta
  lista CERRADA (usa EXACTAMENTE una de estas claves tal cual, en minúsculas, sin inventar
  otras ni traducirlas): {lista_iconos}
- No repitas conceptos ni los reordenes de forma redundante.
- No inventes datos, cifras ni logros que el usuario no haya mencionado en el tema.
- Usa los ejemplos de inspiración SOLO como referencia de tono — nunca copies frases literales.
- Respeta el tono, sector y audiencia indicados.
- Además del título, elige "titulo_resaltado": la palabra o frase corta (1-3 palabras) MÁS
  llamativa dentro de ese título — para resaltarla visualmente en un color distinto, al estilo
  de una portada profesional (p. ej. si el título es "El peligro de any en TypeScript",
  "titulo_resaltado" podría ser "any"). Debe ser EXACTAMENTE un fragmento textual que aparezca
  dentro de "titulo" (mismas mayúsculas/minúsculas), nunca una palabra distinta ni parafraseada.
  Si ninguna palabra destaca especialmente, devuelve una cadena vacía.
- Devuelve SIEMPRE el resultado como JSON válido con este formato exacto, sin texto adicional fuera del JSON:
{{"titulo": "Título corto y llamativo de la infografía", "titulo_resaltado": "fragmento exacto de titulo, o cadena vacía", "subtitulo": "Subtítulo breve opcional (o cadena vacía)", "icono_principal": "clave_de_la_lista", "items": [{{"termino": "Término 1", "descripcion": "Descripción breve del término 1", "icono": "clave_de_la_lista"}}]}}
"""

SYSTEM_PROMPT = """Eres un redactor experto en publicaciones de LinkedIn en español.

Reglas estrictas:
- Escribe publicaciones que suenen humanas, naturales, nunca genéricas ni con "gancho" de IA barato.
- Respeta el tono, sector, objetivo, audiencia y demás preferencias indicadas por el usuario.
- Usa los ejemplos de inspiración SOLO como referencia de estructura, ritmo y tono — nunca copies frases literales de ellos.
- No inventes datos, cifras ni logros que el usuario no haya mencionado en el tema.
- No menciones marcas ajenas ni personas reales identificables salvo que el usuario las nombre explícitamente en el tema.
- Si se indican palabras clave a incluir, intégralas de forma natural, sin forzarlas.
- Si se indican palabras o temas a evitar, no los uses bajo ninguna circunstancia.
- Termina con la llamada a la acción (CTA) y/o firma indicada, si se proporciona, integrada de forma natural.
- Devuelve SIEMPRE el resultado como JSON válido con este formato exacto, sin texto adicional fuera del JSON:
{"variantes": ["texto variante 1", "texto variante 2", "texto variante 3"]}
"""


class CuotaGeminiAgotada(RuntimeError):
    """Se agotó la cuota/límite de peticiones gratuitas de Gemini (HTTP 429 /
    RESOURCE_EXHAUSTED). A diferencia de un fallo puntual, reintentar en el
    acto no sirve de nada — el llamador (daily.py) usa este tipo distinto
    para cortar el resto de un lote en vez de seguir fallando uno a uno."""


def _es_error_de_cuota(error: Exception) -> bool:
    """Detecta un 429/RESOURCE_EXHAUSTED de forma robusta: primero por los
    atributos estructurados que expone google-genai (`code`/`status`), y
    solo como respaldo por el texto del error (por si llega envuelto de
    otra forma)."""
    codigo = getattr(error, "code", None)
    if codigo == 429:
        return True
    status = (getattr(error, "status", "") or "").upper()
    if "RESOURCE_EXHAUSTED" in status:
        return True
    texto = str(error).upper()
    return "429" in texto or "RESOURCE_EXHAUSTED" in texto or "QUOTA" in texto


def _es_error_de_cuota_diaria(error: Exception) -> bool:
    """Distingue el caso concreto de la cuota GRATUITA DIARIA de Gemini
    (quotaId tipo 'GenerateRequestsPerDayPerProjectPerModel-FreeTier') de un
    límite de ráfaga por minuto — el mensaje al usuario debe ser distinto:
    un límite diario no se recupera "en unos minutos", solo al resetearse
    la cuota (Google la resetea a medianoche, hora del Pacífico de EE.UU.)."""
    return "PERDAY" in str(error).upper().replace(" ", "").replace("_", "")


def _info_cuota_desde_error(error: Exception) -> dict:
    """Extrae, cuando están disponibles, el modelo y el cupo REAL
    (`quotaValue`) del detalle estructurado que devuelve la API de Gemini en
    un 429 (`error.details`, ver google.genai.errors.APIError) — Google no
    ofrece ninguna API separada para consultar el cupo de antemano, pero SÍ
    lo comunica dentro del propio error cuando se agota, y así evitamos
    tener que adivinarlo a mano."""
    detalles = getattr(error, "details", None)
    if not isinstance(detalles, dict):
        return {}
    cuerpo_error = detalles.get("error", detalles) if isinstance(detalles.get("error"), dict) else detalles
    for item in cuerpo_error.get("details", []) or []:
        for violacion in item.get("violations", []) or []:
            valor = violacion.get("quotaValue")
            modelo = (violacion.get("quotaDimensions") or {}).get("model")
            if valor:
                try:
                    return {"modelo": modelo, "limite": int(valor)}
                except (TypeError, ValueError):
                    return {"modelo": modelo}
    return {}


def _mensaje_cuota_agotada_todos(candidatos: list[str]) -> str:
    return (
        "Se alcanzó el límite DIARIO gratuito de Gemini en todos los modelos disponibles de esta "
        f"instalación ({', '.join(candidatos)}). No se recupera en minutos: la cuota se restablece a "
        "lo largo del día (normalmente en la madrugada, hora de EE.UU.) — vuelve a intentarlo más "
        "tarde o mañana."
    )


def _generar_con_fallback(client, contents, config, candidatos: list[str]):
    """
    Prueba cada modelo candidato en orden y devuelve la primera respuesta que
    funcione. Los nombres de modelo de Gemini cambian con el tiempo; esto
    evita que la app se rompa entera si uno de ellos deja de existir.

    La cuota gratuita DIARIA de Gemini es, en realidad, POR MODELO (lo
    confirma el propio 429 de Google: quotaId
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier") — así que si un
    candidato se agota, sí tiene sentido seguir probando el resto, cada uno
    tiene su propio cupo independiente. Solo se rinde (`CuotaGeminiAgotada`)
    cuando TODOS los candidatos están agotados hoy. Un modelo ya marcado
    como agotado hoy (en un intento anterior) ni se reintenta — se salta
    directo al siguiente, para no perder tiempo esperando un 429 que ya
    sabemos que va a llegar.

    Antes de intentar nada, respeta también el límite propio (por modelo)
    que la instalación se haya configurado (🛠️ Administración) — si un
    candidato ya lo alcanzó hoy, se salta igual que si Google lo hubiera
    agotado de verdad.

    El "agotado" de hoy se lleva POR CLAVE de Gemini (ver
    config.fingerprint_clave_gemini / db.uso_gemini_diario): si desde que
    se agotó un modelo alguien ha cambiado la clave activa (🛠️
    Administración → Clave de API), ese agotamiento ya no cuenta para la
    clave nueva — se vuelve a intentar de verdad, en vez de rendirse sin
    siquiera llamar a la API. Cuidado: el cupo gratuito de Gemini es POR
    PROYECTO de Google Cloud, no por clave — si la clave nueva pertenece al
    MISMO proyecto que la agotada, es muy probable que el intento falle
    igual, pero ahora sí es un fallo real y actualizado, no uno heredado.
    """
    clave_activa = fingerprint_clave_gemini(get_credentials().gemini_api_key)
    limite_propio = db.obtener_limite_diario_gemini()
    uso_hoy = db.uso_gemini_hoy_por_modelo(clave_activa)

    candidatos_disponibles = []
    for modelo in candidatos:
        info = uso_hoy.get(modelo, {})
        if info.get("agotado"):
            continue
        if limite_propio and info.get("usados", 0) >= limite_propio:
            continue
        candidatos_disponibles.append(modelo)

    if not candidatos_disponibles:
        raise CuotaGeminiAgotada(_mensaje_cuota_agotada_todos(candidatos))

    ultimo_error = None
    hubo_agotamiento_diario = False
    hubo_limite_por_minuto = False
    for modelo in candidatos_disponibles:
        db.registrar_uso_gemini(modelo, clave_activa)
        try:
            return client.models.generate_content(model=modelo, contents=contents, config=config)
        except Exception as e:
            if _es_error_de_cuota(e):
                if _es_error_de_cuota_diaria(e):
                    info_cuota = _info_cuota_desde_error(e)
                    db.marcar_gemini_agotado(modelo, limite_real=info_cuota.get("limite"), clave_fingerprint=clave_activa)
                    hubo_agotamiento_diario = True
                else:
                    hubo_limite_por_minuto = True
                ultimo_error = e
                continue
            ultimo_error = e
            continue

    if hubo_agotamiento_diario:
        raise CuotaGeminiAgotada(_mensaje_cuota_agotada_todos(candidatos)) from ultimo_error
    if hubo_limite_por_minuto:
        raise CuotaGeminiAgotada(
            "Se alcanzó el límite de peticiones por minuto de Gemini en todos los modelos "
            "disponibles. Espera un momento y vuelve a intentarlo."
        ) from ultimo_error
    raise RuntimeError(
        f"Ningún modelo de Gemini disponible respondió ({', '.join(candidatos)}). "
        f"Último error: {ultimo_error}"
    )


def estado_cuota_gemini_hoy() -> dict:
    """Resumen del consumo de cuota de Gemini HOY, listo para mostrar en la
    interfaz: el estado de cada modelo candidato (en el orden en que se
    intentan) y cuál es el "activo" ahora mismo — el primero que todavía no
    está agotado (o None si ya lo están todos). Cada entrada incluye
    "limite" (el real, si Google ya lo comunicó hoy; si no, la estimación
    de config.GEMINI_LIMITE_ESTIMADO_POR_MODELO) y si ese límite es
    "real" o solo estimado, para poder rotularlo distinto en la interfaz."""
    clave_activa = fingerprint_clave_gemini(get_credentials().gemini_api_key)
    uso_hoy = db.uso_gemini_hoy_por_modelo(clave_activa)
    limite_propio = db.obtener_limite_diario_gemini()
    modelos = []
    activo = None
    for modelo in GEMINI_TEXT_MODEL_CANDIDATOS:
        info = uso_hoy.get(modelo, {})
        usados = info.get("usados", 0)
        limite_conocido = info.get("limite_conocido")
        agotado = bool(info.get("agotado")) or bool(limite_propio and usados >= limite_propio)
        entrada = {
            "modelo": modelo,
            "usados": usados,
            "agotado": agotado,
            "limite": limite_conocido or limite_propio or GEMINI_LIMITE_ESTIMADO_POR_MODELO,
            "limite_es_real": limite_conocido is not None,
        }
        modelos.append(entrada)
        if activo is None and not agotado:
            activo = entrada
    return {"modelos": modelos, "activo": activo, "todos_agotados": activo is None}


def _construir_prompt_usuario(tema: str, parametros: dict, inspiracion: list[dict]) -> str:
    partes = [f"TEMA DEL POST: {tema}\n"]

    partes.append("PARÁMETROS POR DEFECTO DEL USUARIO:")
    partes.append(f"- Tono: {parametros.get('tono') or 'profesional y cercano'}")
    if parametros.get("sector"):
        partes.append(f"- Sector/rol: {parametros['sector']}")
    if parametros.get("objetivo"):
        partes.append(f"- Objetivo de la publicación: {parametros['objetivo']}")
    if parametros.get("audiencia_objetivo"):
        partes.append(f"- Audiencia objetivo: {parametros['audiencia_objetivo']}")
    if parametros.get("temas_habituales"):
        partes.append(f"- Temática habitual del usuario (contexto de su marca personal): {parametros['temas_habituales']}")
    partes.append(f"- Longitud preferida: {parametros.get('longitud_preferida') or 'media'}")
    partes.append(f"- Usar emojis: {'sí' if parametros.get('usa_emojis') else 'no'}")
    partes.append(f"- Usar hashtags: {'sí' if parametros.get('usa_hashtags') else 'no'}")
    if parametros.get("palabras_clave"):
        partes.append(f"- Palabras clave a incluir si encajan de forma natural: {parametros['palabras_clave']}")
    if parametros.get("palabras_evitar"):
        partes.append(f"- Palabras/temas a EVITAR por completo: {parametros['palabras_evitar']}")
    if parametros.get("cta_habitual"):
        partes.append(f"- CTA habitual a integrar: {parametros['cta_habitual']}")
    if parametros.get("firma"):
        partes.append(f"- Firma/cierre habitual a integrar de forma natural al final: {parametros['firma']}")

    inspiracion_texto = [i for i in inspiracion if i.get("texto_original")]
    if inspiracion_texto:
        partes.append("\nEJEMPLOS DE INSPIRACIÓN (solo como referencia de estilo, NO copiar literalmente):")
        for i, ejemplo in enumerate(inspiracion_texto[:3], 1):
            partes.append(f"--- Ejemplo {i} ---")
            partes.append(ejemplo["texto_original"][:1500])
            if ejemplo.get("notas"):
                partes.append(f"(Qué le gusta al usuario de este ejemplo: {ejemplo['notas']})")

    partes.append("\nGenera 3 variantes de publicación de LinkedIn siguiendo todas las reglas e instrucciones del sistema.")
    return "\n".join(partes)


def _extraer_json(texto: str) -> dict:
    """Interpreta la respuesta del LLM como JSON, tolerando que a veces (pese a
    pedir response_mime_type="application/json") el modelo envuelva el JSON en
    un bloque de código markdown o añada texto alrededor. Usado tanto para las
    variantes de texto como para el contenido estructurado de la infografía."""
    texto = (texto or "").strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```[a-zA-Z]*\n?", "", texto)
        texto = re.sub(r"\n?```$", "", texto).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        coincidencia = re.search(r"\{.*\}", texto, re.DOTALL)
        if coincidencia:
            return json.loads(coincidencia.group(0))
        raise


# Alias retrocompatible (nombre usado por versiones anteriores/tests).
_parsear_json_variantes = _extraer_json


def generar_variantes_texto(tema: str, parametros: dict, inspiracion: list[dict]) -> list[str]:
    """Devuelve una lista de 2-3 variantes de texto generadas por el LLM."""
    creds = get_credentials()
    if not creds.gemini_api_key:
        raise RuntimeError(
            "La generación con IA no está disponible: esta instalación todavía no tiene "
            "una clave de API activada. Contacta con quien la administra."
        )

    client = genai.Client(api_key=creds.gemini_api_key)
    prompt_usuario = _construir_prompt_usuario(tema, parametros, inspiracion)

    response = _generar_con_fallback(
        client,
        contents=prompt_usuario,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.9,
        ),
        candidatos=GEMINI_TEXT_MODEL_CANDIDATOS,
    )

    texto_respuesta = getattr(response, "text", None)
    if not texto_respuesta:
        motivo = ""
        try:
            candidato = response.candidates[0]
            motivo = f" (finish_reason: {candidato.finish_reason})"
        except Exception:
            pass
        raise RuntimeError(
            "Gemini no devolvió texto en la respuesta — puede que se haya bloqueado por "
            f"seguridad o se haya cortado{motivo}. Prueba a reformular el tema o inténtalo de nuevo."
        )

    try:
        data = _parsear_json_variantes(texto_respuesta)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "El LLM devolvió una respuesta que no se pudo interpretar como JSON. Prueba a generar "
            f"de nuevo. (detalle técnico: {e}; inicio de la respuesta: {texto_respuesta[:200]!r})"
        ) from e

    variantes = data.get("variantes", [])
    if not variantes:
        raise RuntimeError("El LLM no devolvió ninguna variante de texto. Inténtalo de nuevo.")
    return variantes


def sugerir_tema_automatico(parametros: dict, evitar: list[str] | None = None, tema_base: str | None = None) -> str:
    """
    Propone UN tema/idea de post cuando no hay ninguno indicado directamente
    — usado por la "Generación diaria" (modo cola manual sin tema elegido, y
    sobre todo por la Automatización Total, que corre sin nadie delante).
    Se apoya en el perfil guardado (sector, temas habituales, audiencia,
    objetivo) y evita repetir temas usados recientemente.

    `tema_base` (opcional): cuando la cuenta configuró una lista de
    temáticas rotativas (ver db.siguiente_tema_rotacion), aquí llega la que
    le toca hoy (p. ej. "Python") — en ese caso no se le pide a la IA un
    tema libre, sino un ÁNGULO CONCRETO dentro de esa temática, para que
    cada vez que rote a "Python" el post no sea siempre el mismo.
    """
    creds = get_credentials()
    if not creds.gemini_api_key:
        raise RuntimeError(
            "La generación con IA no está disponible: esta instalación todavía no tiene "
            "una clave de API activada. Contacta con quien la administra."
        )

    client = genai.Client(api_key=creds.gemini_api_key)

    partes = ["Perfil del autor:"]
    partes.append(f"- Sector/rol: {parametros.get('sector') or 'profesional en tecnología'}")
    if parametros.get("objetivo"):
        partes.append(f"- Objetivo de sus publicaciones: {parametros['objetivo']}")
    if parametros.get("audiencia_objetivo"):
        partes.append(f"- Audiencia objetivo: {parametros['audiencia_objetivo']}")
    if parametros.get("temas_habituales"):
        partes.append(f"- Temas sobre los que suele publicar: {parametros['temas_habituales']}")
    if evitar:
        partes.append(
            "- Temas usados en publicaciones recientes, NO los repitas ni propongas algo "
            "casi idéntico: " + "; ".join(evitar[:10])
        )
    if tema_base:
        partes.append(
            f"\nEl post de HOY debe tratar específicamente sobre esta temática: \"{tema_base}\". "
            "Propón UN ángulo concreto y específico dentro de esa temática (no la repitas tal cual "
            "de forma genérica — encuentra un aspecto, error común, comparación o caso práctico "
            "concreto). Responde EXCLUSIVAMENTE con ese ángulo convertido en un tema de una frase, "
            "sin comillas, sin explicaciones ni texto adicional."
        )
    else:
        partes.append(
            "\nPropón UN solo tema concreto y específico (no genérico) para una publicación de "
            "LinkedIn nueva, coherente con este perfil. Responde EXCLUSIVAMENTE con el tema en una "
            "frase, sin comillas, sin explicaciones ni texto adicional."
        )

    response = _generar_con_fallback(
        client,
        contents="\n".join(partes),
        config=types.GenerateContentConfig(temperature=1.0),
        candidatos=GEMINI_TEXT_MODEL_CANDIDATOS,
    )
    tema = (getattr(response, "text", None) or "").strip().strip('"').strip()
    if not tema:
        raise RuntimeError("El LLM no propuso ningún tema. Inténtalo de nuevo.")
    return tema


def analizar_estilo_imagen(ruta_imagen: str) -> str:
    """
    Usa Gemini (visión) para describir en 1-2 frases el estilo visual de una
    imagen de inspiración subida por el usuario (composición, colores, mood).
    Se usa para autorrellenar las "notas" cuando el usuario no escribe nada,
    y así aprovechar la imagen como contexto para el generador de imágenes.
    """
    creds = get_credentials()
    if not creds.gemini_api_key:
        return ""

    mime_type = mimetypes.guess_type(ruta_imagen)[0] or "image/png"
    with open(ruta_imagen, "rb") as f:
        datos = f.read()

    try:
        client = genai.Client(api_key=creds.gemini_api_key)
        response = _generar_con_fallback(
            client,
            contents=[
                types.Part.from_bytes(data=datos, mime_type=mime_type),
                "Describe en una frase corta (máx. 25 palabras), en español, el estilo visual de esta "
                "imagen para poder pedir imágenes similares en el futuro: composición, colores, "
                "iluminación y mood. No describas el contenido literal, solo el estilo.",
            ],
            config=types.GenerateContentConfig(temperature=0.4),
            candidatos=GEMINI_TEXT_MODEL_CANDIDATOS,
        )
        return (response.text or "").strip()
    except Exception:
        return ""


def generar_infografia_contenido(
    tema: str, parametros: dict, inspiracion: list[dict], num_items: int = 8,
    titulo_sugerido: str | None = None,
) -> dict:
    """
    Estructura el tema en contenido para una infografía de lista (formato
    "N cosas sobre X"): título, subtítulo opcional y `num_items` puntos
    (término + descripción breve). A diferencia de la imagen ilustrativa,
    este contenido se renderiza 100% en código (ver image_infografia.py) —
    no depende de ningún modelo de generación de imagen, así que nunca cae
    en la cuota de Gemini ni necesita el respaldo de Pollinations.ai.
    """
    creds = get_credentials()
    if not creds.gemini_api_key:
        raise RuntimeError(
            "La generación con IA no está disponible: esta instalación todavía no tiene "
            "una clave de API activada. Contacta con quien la administra."
        )

    client = genai.Client(api_key=creds.gemini_api_key)

    partes = [f"TEMA: {tema}\n", f"Número exacto de puntos a generar: {num_items}"]
    if titulo_sugerido:
        partes.append(f"Título sugerido por el usuario (adáptalo si hace falta, no lo copies literal si no encaja): {titulo_sugerido}")
    partes.append(f"- Tono: {parametros.get('tono') or 'profesional y cercano'}")
    if parametros.get("sector"):
        partes.append(f"- Sector/rol: {parametros['sector']}")
    if parametros.get("audiencia_objetivo"):
        partes.append(f"- Audiencia objetivo: {parametros['audiencia_objetivo']}")

    inspiracion_texto = [i for i in (inspiracion or []) if i.get("texto_original")]
    if inspiracion_texto:
        partes.append("\nEJEMPLOS DE INSPIRACIÓN (solo como referencia de tono, NO copiar literalmente):")
        for i, ejemplo in enumerate(inspiracion_texto[:2], 1):
            partes.append(f"--- Ejemplo {i} ---")
            partes.append(ejemplo["texto_original"][:800])

    prompt_usuario = "\n".join(partes)

    response = _generar_con_fallback(
        client,
        contents=prompt_usuario,
        config=types.GenerateContentConfig(
            system_instruction=_prompt_infografia(num_items),
            response_mime_type="application/json",
            temperature=0.8,
        ),
        candidatos=GEMINI_TEXT_MODEL_CANDIDATOS,
    )

    texto_respuesta = getattr(response, "text", None)
    if not texto_respuesta:
        raise RuntimeError(
            "Gemini no devolvió texto para la infografía — puede que se haya bloqueado por "
            "seguridad o se haya cortado. Prueba a reformular el tema o inténtalo de nuevo."
        )

    try:
        data = _extraer_json(texto_respuesta)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "El LLM devolvió una respuesta que no se pudo interpretar como JSON para la "
            f"infografía. Prueba a generar de nuevo. (detalle técnico: {e}; inicio de la "
            f"respuesta: {texto_respuesta[:200]!r})"
        ) from e

    items = data.get("items") or []
    if not items:
        raise RuntimeError("El LLM no devolvió ningún punto para la infografía. Inténtalo de nuevo.")

    # Si el modelo devuelve de más o de menos, ajustamos al número pedido en
    # vez de fallar — más robusto que exigir una coincidencia exacta.
    items = items[:num_items]

    def _icono_valido(valor) -> str:
        # El modelo debe elegir de una lista cerrada (INFOGRAFIA_ICONOS), pero
        # nunca confiamos ciegamente en la salida del LLM: si devuelve algo
        # fuera de la lista (o nada), usamos el icono por defecto en vez de
        # fallar o intentar cargar un archivo que no existe.
        valor = (valor or "").strip().lower()
        return valor if valor in INFOGRAFIA_ICONOS else INFOGRAFIA_ICONO_DEFECTO

    titulo_final = (data.get("titulo") or titulo_sugerido or tema[:60]).strip()
    resaltado = (data.get("titulo_resaltado") or "").strip()
    if resaltado and resaltado.lower() not in titulo_final.lower():
        # El LLM debe resaltar un fragmento EXACTO del título — si devuelve
        # algo que no aparece literalmente (parafraseado, inventado...), se
        # descarta en vez de arriesgarse a que image_infografia.py no lo
        # encuentre y el resaltado simplemente no se dibuje.
        resaltado = ""

    return {
        "titulo": titulo_final,
        "titulo_resaltado": resaltado,
        "subtitulo": (data.get("subtitulo") or "").strip(),
        "icono_principal": _icono_valido(data.get("icono_principal")),
        "items": [
            {
                "termino": (it.get("termino") or "").strip(),
                "descripcion": (it.get("descripcion") or "").strip(),
                "icono": _icono_valido(it.get("icono")),
            }
            for it in items if (it.get("termino") or "").strip()
        ],
    }
