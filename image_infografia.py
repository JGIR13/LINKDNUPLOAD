"""
Formato "Infografía de lista" — desde V4, el ÚNICO formato de imagen de la
app (se eliminó el antiguo modo "imagen ilustrativa" vía Gemini image +
respaldo Pollinations.ai: sin una API key con cuota de imagen, ese respaldo
gratuito no daba una calidad aceptable — ver el changelog del proyecto).

Este formato NO llama a ningún proveedor de generación de imagen: el
contenido (título + N puntos, cada uno con un icono) lo estructura el LLM
de texto (que ya funciona bien en el nivel gratuito — ver
llm.generar_infografia_contenido) y el diseño completo — título, tarjetas
numeradas con icono, franja de marca personal — se compone aquí con Pillow.

Ventaja: es 100% gratuito y fiable — nunca depende de que un modelo de
imagen "dibuje" texto (que es precisamente donde fallan todos, incluido
Gemini), ni de su cuota, ni de conexión a internet en tiempo de uso: los
iconos (Twemoji, CC-BY 4.0 — ver static/icons/emoji/ATTRIBUTION.txt) y las
fuentes (Poppins, OFL) se descargaron una vez y van empaquetados con la app.

Calidad visual:
- Todo se dibuja al doble de resolución (_ESCALA=2) y se reduce al final con
  LANCZOS — el mismo truco de cualquier herramienta de diseño para que el
  texto y los bordes redondeados salgan nítidos en vez de dentados.
- Tipografía Poppins (más expresiva que una sans genérica) en varios pesos
  para dar jerarquía: Bold para el título, SemiBold para los términos,
  Regular/Medium para el resto — con DejaVu Sans como red de seguridad si
  alguna vez faltara algún archivo de fuente.
- El LLM elige un icono a color (de un set curado, siempre garantizado en
  disco) por cada punto y uno "principal" para la cabecera — igual que el
  ejemplo de referencia que compartió el usuario, sin necesitar que un
  modelo de imagen "dibuje" iconos (cosa en la que también fallan).
- Tarjetas con sombra suave y borde de color por columna (variantes de tono
  del acento de la paleta).
"""

import colorsys
import functools
import os
import time
import uuid

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import (
    FONTS_DIR,
    GENERATED_IMG_DIR,
    ICONOS_DIR,
    INFOGRAFIA_ICONO_DEFECTO,
)
from image_compose import _ajustar_fuente_titulo, _avatar_circular, _envolver_texto, _recortar_lineas_desbordadas

ANCHO = 1080  # ancho del PNG final publicado — no cambia (LinkedIn + tests ya cuentan con esto)
_ESCALA = 2   # se dibuja a esta escala y se reduce al final -> texto y bordes mucho más nítidos


def _e(valor):
    """Escala un valor 'lógico' (el de un diseño a 1080px) a píxeles del lienzo de alta resolución."""
    return int(round(valor * _ESCALA))


ANCHO_HD = _e(ANCHO)
PADDING = _e(56)
GAP_COLUMNAS = _e(32)
GAP_FILAS = _e(30)
RADIO_TARJETA = _e(18)
DIAMETRO_BADGE = _e(54)
DIAMETRO_CHIP_NUM = _e(24)
SOMBRA_DESPLAZAMIENTO = _e(5)
SOMBRA_BLUR = _e(9)
ANCHO_BARRA_TARJETA = _e(5)  # barra de color por columna en el borde izquierdo de cada tarjeta

_FUENTES_PESO = {
    "bold": ("Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"),
    "semibold": ("Poppins-SemiBold.ttf", "DejaVuSans-Bold.ttf"),
    "medium": ("Poppins-Medium.ttf", "DejaVuSans.ttf"),
    "regular": ("Poppins-Regular.ttf", "DejaVuSans.ttf"),
}


@functools.lru_cache(maxsize=None)
def _fuente_peso(peso: str, size: int) -> ImageFont.FreeTypeFont:
    """Carga una fuente Poppins por peso ("bold"/"semibold"/"medium"/"regular"),
    cayendo a DejaVu Sans si ese archivo en concreto no estuviera empaquetado
    — nunca depende de fuentes instaladas en el sistema del usuario."""
    preferida, respaldo = _FUENTES_PESO[peso]
    ruta = os.path.join(FONTS_DIR, preferida)
    if not os.path.exists(ruta):
        ruta = os.path.join(FONTS_DIR, respaldo)
    return ImageFont.truetype(ruta, max(size, 8))


@functools.lru_cache(maxsize=None)
def _cargar_icono(clave: str, tamano: int) -> Image.Image:
    """Carga un icono (PNG a color, Twemoji) del set curado y lo escala al
    tamaño pedido. Si la clave no tuviera archivo (no debería pasar — el LLM
    solo elige de la lista cerrada en config.INFOGRAFIA_ICONOS, y ésta se
    valida en llm.py — pero por robustez ante un paquete incompleto), cae al
    icono por defecto; si ni siquiera ese existe, devuelve un icono en
    blanco en vez de romper la generación de la imagen."""
    ruta = os.path.join(ICONOS_DIR, f"{clave}.png")
    if not os.path.exists(ruta):
        ruta = os.path.join(ICONOS_DIR, f"{INFOGRAFIA_ICONO_DEFECTO}.png")
    if not os.path.exists(ruta):
        return Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    icono = Image.open(ruta).convert("RGBA")
    return icono.resize((tamano, tamano), Image.LANCZOS)


def _hex_a_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mezclar(c1: tuple, c2: tuple, t: float) -> tuple:
    """Interpola entre dos colores RGB (t=0 -> c1, t=1 -> c2)."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _variantes_columna(acento_rgb: tuple, n: int) -> list:
    """Genera hasta 3 tonos emparentados del color de acento (uno por columna),
    para diferenciar visualmente cada columna de la infografía sin salirse de
    la paleta elegida — mismo espíritu que las columnas por categoría del
    ejemplo de referencia."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in acento_rgb))
    desplazamientos = [0.0, 0.035, -0.035]
    variantes = []
    for d in desplazamientos[:max(n, 1)]:
        h2 = (h + d) % 1.0
        s2 = min(max(s * (0.94 if d else 1.0), 0), 1)
        r, g, b = colorsys.hsv_to_rgb(h2, s2, v)
        variantes.append((int(r * 255), int(g * 255), int(b * 255)))
    return variantes


def _rectangulo_redondeado(draw: ImageDraw.ImageDraw, caja, radio, fill=None, outline=None, width=1):
    draw.rounded_rectangle(caja, radius=radio, fill=fill, outline=outline, width=width)


def _num_columnas(n_items: int) -> int:
    if n_items <= 6:
        return 1
    if n_items <= 14:
        return 2
    return 3


def _medir_lineas(draw, texto, fuente, max_ancho, max_lineas=None):
    lineas = _envolver_texto(draw, texto, fuente, max_ancho)
    if max_lineas and len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        ultima = lineas[-1]
        while len(ultima) > 1 and draw.textlength(ultima + "…", font=fuente) > max_ancho:
            ultima = ultima[:-1]
        lineas[-1] = ultima.rstrip() + "…"
    # Salvaguarda contra desbordamiento: un término corto suele ser UNA sola
    # "palabra" compuesta sin espacios (p. ej. "Autenticación/Autorización",
    # "CI/CD", "Seguridad(OWASP)") que _envolver_texto no puede partir entre
    # palabras — sin esto, esa línea se sale de la tarjeta aunque el número
    # de líneas esté dentro de max_lineas (ver image_compose._recortar_lineas_desbordadas).
    return _recortar_lineas_desbordadas(draw, lineas, fuente, max_ancho)


def _textura_diagonal(ancho: int, alto: int) -> Image.Image:
    """Textura decorativa muy sutil (líneas diagonales blancas, baja opacidad)
    para dar algo de vida a la cabecera sin depender de ningún asset externo."""
    if ancho <= 0 or alto <= 0:
        return Image.new("RGBA", (max(ancho, 1), max(alto, 1)), (0, 0, 0, 0))
    capa = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    draw = ImageDraw.Draw(capa)
    paso = _e(22)
    grosor = max(_e(2), 1)
    for x in range(-alto, ancho, paso):
        draw.line([(x, 0), (x + alto, alto)], fill=(255, 255, 255, 22), width=grosor)
    return capa


def _degradado_vertical(ancho: int, alto: int, color_arriba: tuple, color_abajo: tuple) -> Image.Image:
    """Rectángulo con un degradado vertical suave (color_arriba -> color_abajo)
    — le da profundidad al cuerpo de la infografía en vez de un color plano.
    Se construye como una tira de 1px de ancho (un `_mezclar` por fila) y se
    estira horizontalmente, mucho más barato que dibujar `alto` líneas."""
    if ancho <= 0 or alto <= 0:
        return Image.new("RGB", (max(ancho, 1), max(alto, 1)), color_arriba)
    tira = Image.new("RGB", (1, alto))
    for y in range(alto):
        tira.putpixel((0, y), _mezclar(color_arriba, color_abajo, y / max(alto - 1, 1)))
    return tira.resize((ancho, alto), Image.NEAREST)


def _paleta_clara(primario: tuple, acento: tuple) -> dict:
    """Deriva un set de colores 'lienzo claro' a partir de primario+acento —
    mismo espíritu que `_paleta_oscura`, pero para el modo claro: fondo con
    un tinte muy sutil del primario, tarjetas casi blancas y texto oscuro
    neutro (igual que en los presets ya existentes de config.py, que también
    usan un texto casi fijo con independencia del color primario, para
    garantizar contraste). Sirve de base para CUALQUIER paleta que no traiga
    sus propios valores de fondo/texto/tarjeta explícitos — en concreto, las
    paletas personalizadas (el usuario solo elige primario+acento)."""
    blanco = (255, 255, 255)
    return {
        "fondo": _mezclar(primario, blanco, 0.94),
        "tarjeta": _mezclar(primario, blanco, 0.985),
        "texto": (17, 24, 39),
        "texto_claro": (75, 85, 99),
        "borde": _mezclar(primario, blanco, 0.86),
    }


def _paleta_oscura(primario: tuple, acento: tuple) -> dict:
    """Deriva un set de colores 'lienzo oscuro' a partir de los dos colores
    que YA tiene cada paleta (primario + acento) — así no hace falta duplicar
    a mano cada paleta de config.py en una versión clara y otra oscura, y el
    tono oscuro siempre queda coherente con la paleta elegida. Estilo:
    fondo casi negro con un tinte del color primario, tarjetas "flotantes"
    un punto más claras que el fondo, texto casi blanco y el borde de cada
    tarjeta teñido del acento en vez de un gris neutro."""
    negro = (11, 13, 18)
    fondo = _mezclar(primario, negro, 0.86)
    tarjeta = _mezclar(primario, negro, 0.68)
    borde = _mezclar(acento, tarjeta, 0.45)
    return {
        "fondo": fondo,
        "tarjeta": tarjeta,
        "texto": (245, 247, 250),
        "texto_claro": (173, 180, 194),
        "borde": borde,
    }


def _dibujar_linea_resaltada(draw, x, y, linea: str, resaltado: str, fuente, color_normal, color_resalte):
    """Dibuja `linea` en `color_normal`, salvo el fragmento (si aparece,
    sin distinguir mayúsculas/minúsculas) que coincide con `resaltado`, que
    se dibuja en `color_resalte` — el efecto de "palabra clave a color"
    típico de una portada/infografía profesional. Si `resaltado` está vacío
    o no aparece en esta línea, la dibuja entera en `color_normal`, sin
    romper nada del comportamiento anterior."""
    if not resaltado:
        draw.text((x, y), linea, font=fuente, fill=color_normal)
        return
    idx = linea.lower().find(resaltado.lower())
    if idx == -1:
        draw.text((x, y), linea, font=fuente, fill=color_normal)
        return
    antes, medio, despues = linea[:idx], linea[idx:idx + len(resaltado)], linea[idx + len(resaltado):]
    cx = x
    if antes:
        draw.text((cx, y), antes, font=fuente, fill=color_normal)
        cx += draw.textlength(antes, font=fuente)
    draw.text((cx, y), medio, font=fuente, fill=color_resalte)
    cx += draw.textlength(medio, font=fuente)
    if despues:
        draw.text((cx, y), despues, font=fuente, fill=color_normal)


def _insignia_decorativa(diametro: int, icono_clave: str) -> Image.Image:
    """Insignia grande y semi-transparente con el icono principal del tema —
    el toque "elemento gráfico" de la cabecera, con el mismo icono que ya
    eligió el LLM para representar la infografía (coherencia contenido-diseño
    en vez de un adorno genérico)."""
    capa = Image.new("RGBA", (diametro, diametro), (0, 0, 0, 0))
    draw = ImageDraw.Draw(capa)
    draw.ellipse([0, 0, diametro, diametro], fill=(255, 255, 255, 28))
    icono = _cargar_icono(icono_clave, int(diametro * 0.52))
    pos = ((diametro - icono.width) // 2, (diametro - icono.height) // 2)
    capa.alpha_composite(icono, pos)
    return capa


def generar_infografia(datos: dict, paleta: dict, marca: dict | None = None, oscuro: bool = False) -> str:
    """
    Genera la imagen completa de la infografía a partir de:
    - datos: {"titulo", "titulo_resaltado", "subtitulo", "icono_principal",
      "items": [{"termino", "descripcion", "icono"}, ...]} — "titulo_resaltado"
      (opcional) es un fragmento exacto de "titulo" que se dibuja en el color
      de acento en vez del color de texto normal; "icono"/"icono_principal"
      son claves de config.INFOGRAFIA_ICONOS (opcionales por compatibilidad:
      si faltan, se usa el icono por defecto).
    - paleta: dict de colores hex (ver config.INFOGRAFIA_PALETAS). Solo
      "primario" y "acento" son obligatorios — si faltan "fondo"/"texto"/
      "texto_claro"/"tarjeta" (caso de una paleta PERSONALIZADA, donde el
      usuario solo elige esos dos colores), se derivan automáticamente con
      `_paleta_clara()`, con el mismo criterio que ya usan los 5 presets
      empaquetados (texto oscuro neutro, tarjeta casi blanca, fondo con un
      tinte muy sutil del primario) — así una paleta personalizada se ve
      igual de cuidada que una empaquetada, sin que el usuario tenga que
      elegir 7 colores a mano.
    - marca: {"nombre", "rol", "ruta_foto"} o None (sin franja de marca personal)
    - oscuro: si es True, el cuerpo de la infografía usa un lienzo oscuro
      derivado de la propia paleta (ver `_paleta_oscura`) en vez del fondo
      claro por defecto — mismo espíritu que los ejemplos de referencia de
      infografías técnicas con fondo oscuro. La cabecera y el pie (franja de
      marca personal) no cambian: ya usan el color primario en los dos modos.

    Devuelve la ruta del PNG generado (ya reducido a ANCHO=1080 tras
    dibujarse internamente al doble de resolución).
    """
    primario = _hex_a_rgb(paleta["primario"])
    acento = _hex_a_rgb(paleta["acento"])
    if oscuro:
        colores_cuerpo = _paleta_oscura(primario, acento)
        fondo = colores_cuerpo["fondo"]
        color_texto = colores_cuerpo["texto"]
        texto_claro = colores_cuerpo["texto_claro"]
        tarjeta_color = colores_cuerpo["tarjeta"]
        color_borde_base = colores_cuerpo["borde"]
    else:
        derivados_claro = _paleta_clara(primario, acento)
        fondo = _hex_a_rgb(paleta["fondo"]) if paleta.get("fondo") else derivados_claro["fondo"]
        color_texto = _hex_a_rgb(paleta["texto"]) if paleta.get("texto") else derivados_claro["texto"]
        texto_claro = _hex_a_rgb(paleta["texto_claro"]) if paleta.get("texto_claro") else derivados_claro["texto_claro"]
        tarjeta_color = _hex_a_rgb(paleta["tarjeta"]) if paleta.get("tarjeta") else derivados_claro["tarjeta"]
        color_borde_base = None  # en modo claro el borde ya se deriva por columna, más abajo

    items = datos.get("items") or []
    n = max(len(items), 1)
    columnas = _num_columnas(n)
    variantes_col = _variantes_columna(acento, columnas)
    icono_principal = datos.get("icono_principal") or INFOGRAFIA_ICONO_DEFECTO

    # Lienzo temporal solo para medir texto antes de saber la altura final.
    medidor = Image.new("RGB", (ANCHO_HD, 10))
    draw_medidor = ImageDraw.Draw(medidor)

    # --- Cabecera: título + subtítulo (dejamos margen a la derecha para la
    # insignia decorativa con el icono principal) ---
    diametro_insignia = int(_e(56) * 2.6)
    max_ancho_titulo = ANCHO_HD - 2 * PADDING - int(diametro_insignia * 0.55)
    fuente_titulo, lineas_titulo = _ajustar_fuente_titulo(
        draw_medidor, (datos.get("titulo") or "Infografía").strip(),
        max_ancho_titulo, max_lineas=2, tam_inicial=_e(54), tam_min=_e(34),
    )
    interlineado_titulo = int(fuente_titulo.size * 1.22)

    subtitulo = (datos.get("subtitulo") or "").strip()
    lineas_subtitulo = []
    fuente_subtitulo = _fuente_peso("medium", _e(25))
    if subtitulo:
        lineas_subtitulo = _medir_lineas(draw_medidor, subtitulo, fuente_subtitulo, max_ancho_titulo, max_lineas=2)
    interlineado_subtitulo = int(fuente_subtitulo.size * 1.35)

    alto_cabecera = (
        int(PADDING * 1.15)
        + len(lineas_titulo) * interlineado_titulo
        + (int(fuente_subtitulo.size * 0.5) + len(lineas_subtitulo) * interlineado_subtitulo if lineas_subtitulo else 0)
        + int(PADDING * 0.85)
    )
    alto_cabecera = max(alto_cabecera, int(diametro_insignia * 0.9))

    # --- Cuerpo: geometría de las tarjetas (se calcula antes de dibujar nada,
    # para poder generar primero la capa de sombra) ---
    ancho_columna = (ANCHO_HD - 2 * PADDING - (columnas - 1) * GAP_COLUMNAS) // columnas
    pad_tarjeta = _e(20)
    gap_badge_texto = _e(16)
    ancho_texto_tarjeta = ancho_columna - 2 * pad_tarjeta - DIAMETRO_BADGE - gap_badge_texto

    fuente_termino = _fuente_peso("semibold", _e(23))
    fuente_desc = _fuente_peso("regular", _e(18))
    interlineado_desc = int(fuente_desc.size * 1.32)
    fuente_num = _fuente_peso("bold", _e(13))

    filas = []
    for i in range(0, n, columnas):
        fila_items = items[i:i + columnas]
        filas_datos = []
        alto_fila = 0
        for it in fila_items:
            lineas_termino = _medir_lineas(draw_medidor, it.get("termino") or "", fuente_termino, ancho_texto_tarjeta, max_lineas=2)
            lineas_desc = _medir_lineas(draw_medidor, it.get("descripcion") or "", fuente_desc, ancho_texto_tarjeta, max_lineas=3)
            alto_contenido = max(DIAMETRO_BADGE, len(lineas_termino) * int(fuente_termino.size * 1.25))
            alto_tarjeta = pad_tarjeta * 2 + alto_contenido + (6 + len(lineas_desc) * interlineado_desc if lineas_desc else 0)
            filas_datos.append({"lineas_termino": lineas_termino, "lineas_desc": lineas_desc, "alto": alto_tarjeta})
            alto_fila = max(alto_fila, alto_tarjeta)
        filas.append((fila_items, filas_datos, alto_fila))

    alto_cuerpo = int(PADDING * 0.7) + sum(alto for _, _, alto in filas) + GAP_FILAS * max(len(filas) - 1, 0) + int(PADDING * 0.5)

    # --- Pie: marca personal (opcional) ---
    tam_avatar = _e(92)
    alto_pie = int(tam_avatar + PADDING * 1.1) if marca else 0

    alto_total = alto_cabecera + alto_cuerpo + alto_pie

    # Geometría final de cada tarjeta (posición + color de columna + icono),
    # calculada ahora que conocemos alto_cabecera — se usa primero para la
    # sombra y después para dibujar el contenido real encima.
    tarjetas_geo = []
    y_fila = alto_cabecera + int(PADDING * 0.65)
    numero_global = 1
    for fila_items, filas_datos, alto_fila in filas:
        x_col = PADDING
        for idx_col, (it, dat) in enumerate(zip(fila_items, filas_datos)):
            caja = (x_col, y_fila, x_col + ancho_columna, y_fila + alto_fila)
            tarjetas_geo.append({
                "caja": caja, "dat": dat, "numero": numero_global,
                "color": variantes_col[idx_col % len(variantes_col)],
                "icono": it.get("icono") or INFOGRAFIA_ICONO_DEFECTO,
            })
            numero_global += 1
            x_col += ancho_columna + GAP_COLUMNAS
        y_fila += alto_fila + GAP_FILAS

    # --- Lienzo base ---
    img = Image.new("RGB", (ANCHO_HD, alto_total), fondo)
    draw = ImageDraw.Draw(img)

    # El cuerpo (entre cabecera y pie) lleva un degradado vertical muy sutil
    # en vez de un color plano — un toque de profundidad que evita que el
    # fondo se vea "chato", sin afectar a la cabecera ni al pie (que siguen
    # con el color primario sólido, sin cambios).
    color_cuerpo_abajo = _mezclar(fondo, (0, 0, 0), 0.10 if oscuro else 0.035)
    degradado_cuerpo = _degradado_vertical(ANCHO_HD, alto_cuerpo, fondo, color_cuerpo_abajo)
    img.paste(degradado_cuerpo, (0, alto_cabecera))

    if oscuro:
        # Textura sutil sobre TODO el lienzo (no solo la cabecera) — el
        # rectángulo opaco de la cabecera y, si lo hay, el del pie, se
        # dibujan encima y la tapan en esas zonas, así que en la práctica
        # queda visible solo en el cuerpo — el efecto "tech" de fondo oscuro
        # de los ejemplos de referencia, sin tocar la cabecera ni el pie.
        textura_cuerpo = _textura_diagonal(ANCHO_HD, alto_total)
        img.paste(textura_cuerpo, (0, 0), textura_cuerpo)

    # Cabecera: fondo + textura decorativa + insignia con el icono principal + título
    draw.rectangle([0, 0, ANCHO_HD, alto_cabecera], fill=primario)
    zona_x0 = int(ANCHO_HD * 0.6)
    textura = _textura_diagonal(ANCHO_HD - zona_x0, alto_cabecera)
    img.paste(textura, (zona_x0, 0), textura)

    insignia = _insignia_decorativa(diametro_insignia, icono_principal)
    pos_insignia = (ANCHO_HD - int(diametro_insignia * 0.78), (alto_cabecera - diametro_insignia) // 2)
    img.paste(insignia, pos_insignia, insignia)

    barra_ancho = _e(6)
    draw.rectangle(
        [PADDING - barra_ancho - _e(10), int(PADDING * 0.55), PADDING - _e(10), alto_cabecera - int(PADDING * 0.55)],
        fill=acento,
    )
    titulo_resaltado = (datos.get("titulo_resaltado") or "").strip()
    y = int(PADDING * 0.6)
    for linea in lineas_titulo:
        _dibujar_linea_resaltada(draw, PADDING, y, linea, titulo_resaltado, fuente_titulo, (255, 255, 255), acento)
        y += interlineado_titulo
    if lineas_subtitulo:
        y += int(fuente_subtitulo.size * 0.35)
        for linea in lineas_subtitulo:
            draw.text((PADDING, y), linea, font=fuente_subtitulo, fill=(226, 232, 240))
            y += interlineado_subtitulo

    # Sombra suave de todas las tarjetas, en una sola pasada (más barato que
    # difuminar tarjeta por tarjeta) — se pega ANTES de dibujar las tarjetas
    # encima, dando el efecto de profundidad típico de una tarjeta "flotando".
    sombra = Image.new("RGBA", (ANCHO_HD, alto_total), (0, 0, 0, 0))
    draw_sombra = ImageDraw.Draw(sombra)
    color_sombra = (0, 0, 0, 130) if oscuro else (15, 23, 42, 60)
    for t in tarjetas_geo:
        x0, y0, x1, y1 = t["caja"]
        draw_sombra.rounded_rectangle(
            [x0, y0 + SOMBRA_DESPLAZAMIENTO, x1, y1 + SOMBRA_DESPLAZAMIENTO],
            radius=RADIO_TARJETA, fill=color_sombra,
        )
    sombra = sombra.filter(ImageFilter.GaussianBlur(SOMBRA_BLUR))
    img.paste(sombra, (0, 0), sombra)

    # Tarjetas: fondo + borde de color por columna (tono pastel del acento de
    # esa columna) + badge con icono a color + chip numerado + término + descripción.
    for t in tarjetas_geo:
        x0, y0, x1, y1 = t["caja"]
        dat = t["dat"]
        color_col = t["color"]
        borde_col = (
            _mezclar(color_col, color_borde_base, 0.5) if oscuro
            else _mezclar(color_col, (255, 255, 255), 0.55)
        )
        _rectangulo_redondeado(draw, t["caja"], RADIO_TARJETA, fill=tarjeta_color, outline=borde_col, width=max(_e(2), 1))

        # Barra de color por columna en el borde izquierdo — refuerza la
        # sensación de categorías agrupadas (una por columna) más allá del
        # badge, como un acento sutil que no compite con el resto de la
        # tarjeta (a diferencia de una franja superior a todo lo ancho).
        ancho_borde = max(_e(2), 1)
        inset_barra = _e(14)
        draw.rounded_rectangle(
            [x0 + ancho_borde + _e(2), y0 + inset_barra,
             x0 + ancho_borde + _e(2) + ANCHO_BARRA_TARJETA, y1 - inset_barra],
            radius=ANCHO_BARRA_TARJETA // 2, fill=color_col,
        )

        cx_badge = x0 + pad_tarjeta + DIAMETRO_BADGE // 2
        cy_badge = y0 + pad_tarjeta + DIAMETRO_BADGE // 2
        fondo_badge = _mezclar(color_col, (255, 255, 255), 0.78)
        draw.ellipse(
            [cx_badge - DIAMETRO_BADGE // 2, cy_badge - DIAMETRO_BADGE // 2,
             cx_badge + DIAMETRO_BADGE // 2, cy_badge + DIAMETRO_BADGE // 2],
            fill=fondo_badge, outline=color_col, width=max(_e(2), 1),
        )
        icono_img = _cargar_icono(t["icono"], int(DIAMETRO_BADGE * 0.6))
        pos_icono = (cx_badge - icono_img.width // 2, cy_badge - icono_img.height // 2)
        img.paste(icono_img, pos_icono, icono_img)

        # Chip numerado, superpuesto en la esquina del badge (estilo "notificación").
        chip_cx = cx_badge + int(DIAMETRO_BADGE * 0.36)
        chip_cy = cy_badge + int(DIAMETRO_BADGE * 0.36)
        r_chip = DIAMETRO_CHIP_NUM // 2
        draw.ellipse(
            [chip_cx - r_chip, chip_cy - r_chip, chip_cx + r_chip, chip_cy + r_chip],
            fill=color_col, outline=tarjeta_color, width=max(_e(2), 1),
        )
        num_texto = str(t["numero"])
        bbox = draw.textbbox((0, 0), num_texto, font=fuente_num)
        w_num, h_num = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((chip_cx - w_num / 2 - bbox[0], chip_cy - h_num / 2 - bbox[1]), num_texto, font=fuente_num, fill=(255, 255, 255))

        x_texto = x0 + pad_tarjeta + DIAMETRO_BADGE + gap_badge_texto
        y_texto = y0 + pad_tarjeta
        for linea in dat["lineas_termino"]:
            draw.text((x_texto, y_texto), linea, font=fuente_termino, fill=color_texto)
            y_texto += int(fuente_termino.size * 1.25)
        if dat["lineas_desc"]:
            y_texto += _e(6)
            for linea in dat["lineas_desc"]:
                draw.text((x_texto, y_texto), linea, font=fuente_desc, fill=texto_claro)
                y_texto += interlineado_desc

    # Pie: marca personal — rediseñado para que se vea como una credencial de
    # autor (avatar con anillo de acento + sombra, rol en una "píldora" en
    # vez de texto plano, textura y barra de acento a juego con la cabecera)
    # en vez de solo una foto con un nombre al lado.
    if marca:
        y_pie = alto_cabecera + alto_cuerpo

        # Degradado (primario -> un tono más oscuro) en vez de un color
        # plano, mismo lenguaje visual que ya usa el cuerpo — cabecera y pie
        # quedan como "bookends" coherentes del mismo diseño.
        color_pie_abajo = _mezclar(primario, (0, 0, 0), 0.28)
        degradado_pie = _degradado_vertical(ANCHO_HD, alto_pie, primario, color_pie_abajo)
        img.paste(degradado_pie, (0, y_pie))

        zona_pie_x0 = int(ANCHO_HD * 0.55)
        textura_pie = _textura_diagonal(ANCHO_HD - zona_pie_x0, alto_pie)
        img.paste(textura_pie, (zona_pie_x0, y_pie), textura_pie)

        draw.line([(0, y_pie), (ANCHO_HD, y_pie)], fill=_mezclar(primario, (255, 255, 255), 0.18), width=max(_e(1), 1))

        # Barra de acento junto al avatar — el mismo elemento que ya marca
        # el título en la cabecera, repetido aquí para dar cohesión visual
        # entre el principio y el final de la infografía.
        barra_pie_alto = int(tam_avatar * 0.7)
        draw.rectangle(
            [PADDING - barra_ancho - _e(14), y_pie + (alto_pie - barra_pie_alto) // 2,
             PADDING - _e(14), y_pie + (alto_pie + barra_pie_alto) // 2],
            fill=acento,
        )

        nombre = (marca.get("nombre") or "Tu nombre").strip()
        rol = (marca.get("rol") or "").strip()
        iniciales = "".join(p[0].upper() for p in nombre.split()[:2]) or "TU"

        pos_avatar = (PADDING, y_pie + (alto_pie - tam_avatar) // 2)
        cx_avatar = pos_avatar[0] + tam_avatar // 2
        cy_avatar = pos_avatar[1] + tam_avatar // 2

        # Sombra suave bajo el avatar (capa aparte, difuminada) + anillo de
        # acento alrededor — acabado "insignia de autor" en vez de una foto
        # suelta flotando sobre el color de fondo.
        radio_sombra = tam_avatar // 2 + _e(10)
        sombra_avatar = Image.new("RGBA", (ANCHO_HD, alto_total), (0, 0, 0, 0))
        draw_sombra_av = ImageDraw.Draw(sombra_avatar)
        draw_sombra_av.ellipse(
            [cx_avatar - radio_sombra, cy_avatar - radio_sombra + _e(4),
             cx_avatar + radio_sombra, cy_avatar + radio_sombra + _e(4)],
            fill=(0, 0, 0, 90),
        )
        sombra_avatar = sombra_avatar.filter(ImageFilter.GaussianBlur(_e(6)))
        img.paste(sombra_avatar, (0, 0), sombra_avatar)

        radio_anillo = tam_avatar // 2 + _e(6)
        draw.ellipse(
            [cx_avatar - radio_anillo, cy_avatar - radio_anillo, cx_avatar + radio_anillo, cy_avatar + radio_anillo],
            outline=acento, width=max(_e(3), 1),
        )
        avatar = _avatar_circular(tam_avatar, marca.get("ruta_foto"), iniciales, primario, acento)
        img.paste(avatar, pos_avatar, avatar)

        x_texto = pos_avatar[0] + tam_avatar + _e(28)
        max_ancho_pie = ANCHO_HD - x_texto - PADDING
        fuente_nombre = _fuente_peso("bold", _e(29))
        fuente_rol = _fuente_peso("semibold", _e(18))

        nombre_mostrar = nombre
        while len(nombre_mostrar) > 1 and draw.textlength(nombre_mostrar, font=fuente_nombre) > max_ancho_pie:
            nombre_mostrar = nombre_mostrar[:-1]
        if nombre_mostrar != nombre:
            nombre_mostrar = nombre_mostrar.rstrip() + "…"

        rol_mostrar = rol
        ancho_pill_max = max(max_ancho_pie - _e(28), _e(40))
        while len(rol_mostrar) > 1 and draw.textlength(rol_mostrar, font=fuente_rol) > ancho_pill_max:
            rol_mostrar = rol_mostrar[:-1]
        if rol_mostrar and rol_mostrar != rol:
            rol_mostrar = rol_mostrar.rstrip() + "…"

        if rol_mostrar:
            y_nombre = y_pie + alto_pie / 2 - fuente_nombre.size * 1.05
            y_pill = y_nombre + fuente_nombre.size * 1.28
        else:
            y_nombre = y_pie + alto_pie / 2 - fuente_nombre.size * 0.5
            y_pill = None

        draw.text((x_texto, y_nombre), nombre_mostrar, font=fuente_nombre, fill=(255, 255, 255))

        if y_pill is not None:
            # El rol se muestra como una "píldora" (chip) en vez de texto
            # plano suelto — más parecido a la credencial de un autor/
            # ponente en una infografía profesional que a una simple
            # etiqueta secundaria.
            pad_pill_x, pad_pill_y = _e(14), _e(7)
            ancho_texto_rol = draw.textlength(rol_mostrar, font=fuente_rol)
            caja_pill = [
                x_texto, y_pill,
                x_texto + ancho_texto_rol + pad_pill_x * 2, y_pill + fuente_rol.size + pad_pill_y * 2,
            ]
            color_pill = _mezclar(acento, primario, 0.2)
            draw.rounded_rectangle(caja_pill, radius=(fuente_rol.size + pad_pill_y * 2) // 2, fill=color_pill)
            draw.text((x_texto + pad_pill_x, y_pill + pad_pill_y), rol_mostrar, font=fuente_rol, fill=(255, 255, 255))
        else:
            # Sin cargo/rol configurado: un pequeño trazo de acento bajo el
            # nombre a modo de firma, para que el pie no se vea vacío ni
            # descompensado en vez de dejar el hueco en blanco.
            y_firma = y_nombre + fuente_nombre.size * 1.15
            draw.rounded_rectangle(
                [x_texto, y_firma, x_texto + _e(46), y_firma + _e(5)], radius=_e(3), fill=acento,
            )

    # Reducción final: de _ESCALA x a resolución de publicación -> el mismo
    # truco de antialiasing que usa cualquier herramienta de diseño (texto y
    # bordes redondeados salen nítidos en vez de dentados).
    alto_final = max(int(round(alto_total / _ESCALA)), 1)
    img = img.resize((ANCHO, alto_final), Image.LANCZOS)

    nombre_archivo = f"infografia_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
    ruta_final = os.path.join(GENERATED_IMG_DIR, nombre_archivo)
    img.save(ruta_final, "PNG")
    return ruta_final
