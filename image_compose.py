"""
Utilidades de texto/tipografía e imagen compartidas por el renderer de la
infografía (image_infografia.py) — el único formato de imagen desde V4.

Historia: hasta V3 este módulo componía overlays (título + marca personal)
sobre una imagen de fondo generada por IA (Gemini/Pollinations). En V4 se
eliminó por completo el modo "imagen ilustrativa" (sin una API key con cuota
de imagen, el respaldo gratuito de Pollinations no daba una calidad
aceptable) — ahora el único formato con imagen es la "📊 Infografía de
lista", compuesta 100% en código con Pillow (ver image_infografia.py), así
que este módulo se redujo a los helpers de texto/tipografía/avatar que ese
renderer SÍ sigue usando: fuentes embebidas, ajuste automático de tamaño y
salto de línea (con salvaguarda anti-desbordamiento), y el avatar circular
de marca personal.
"""

import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

from config import FONTS_DIR


def _ruta_fuente(preferida: str, respaldo: str) -> str:
    """Usa la fuente preferida (Poppins, más expresiva) si está empaquetada,
    y si no cae a la de respaldo (DejaVu Sans) — nunca depende de fuentes del
    sistema, así que el texto siempre sale igual en cualquier PC."""
    ruta_preferida = os.path.join(FONTS_DIR, preferida)
    return ruta_preferida if os.path.exists(ruta_preferida) else os.path.join(FONTS_DIR, respaldo)


FUENTE_BOLD = _ruta_fuente("Poppins-Bold.ttf", "DejaVuSans-Bold.ttf")
FUENTE_REGULAR = _ruta_fuente("Poppins-Regular.ttf", "DejaVuSans.ttf")


def _fuente(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FUENTE_BOLD if bold else FUENTE_REGULAR, max(size, 8))


def _envolver_texto(draw: ImageDraw.ImageDraw, texto: str, fuente, max_ancho: int) -> list:
    palabras = texto.split()
    lineas, actual = [], ""
    for palabra in palabras:
        prueba = f"{actual} {palabra}".strip()
        if draw.textlength(prueba, font=fuente) <= max_ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _recortar_lineas_desbordadas(draw, lineas, fuente, max_ancho):
    """Salvaguarda contra desbordamiento horizontal: `_envolver_texto` solo
    corta ENTRE palabras (por espacios), así que una sola palabra/token sin
    espacios más ancho que `max_ancho` (p. ej. un término compuesto como
    "Autenticación/Autorización", o cualquier palabra larga sin espacios)
    queda como una línea de ancho arbitrario y se sale del recuadro/tarjeta.
    Aquí se recorta cualquier línea que aún exceda el ancho disponible,
    carácter a carácter, terminando en "…" — igual que ya se hacía solo para
    la ÚLTIMA línea cuando sobraban líneas, pero aplicado a TODAS las líneas,
    porque el desbordamiento puede darse aunque el texto quepa en el número
    de líneas permitido."""
    resultado = []
    for linea in lineas:
        if draw.textlength(linea, font=fuente) <= max_ancho:
            resultado.append(linea)
            continue
        recorte = linea
        while len(recorte) > 1 and draw.textlength(recorte + "…", font=fuente) > max_ancho:
            recorte = recorte[:-1]
        resultado.append(recorte.rstrip() + "…")
    return resultado


def _ajustar_fuente_titulo(draw, texto, max_ancho, max_lineas=3, tam_inicial=64, tam_min=32):
    """Prueba tamaños de fuente decrecientes hasta que el título quepa en
    max_lineas líneas — evita títulos cortados o desbordados."""
    tam = tam_inicial
    while tam >= tam_min:
        fuente = _fuente(True, tam)
        lineas = _envolver_texto(draw, texto, fuente, max_ancho)
        if len(lineas) <= max_lineas:
            return fuente, _recortar_lineas_desbordadas(draw, lineas, fuente, max_ancho)
        tam -= 4

    fuente = _fuente(True, tam_min)
    lineas = _envolver_texto(draw, texto, fuente, max_ancho)[:max_lineas]
    if lineas:
        while len(lineas[-1]) > 1 and draw.textlength(lineas[-1] + "…", font=fuente) > max_ancho:
            lineas[-1] = lineas[-1][:-1]
        lineas[-1] = lineas[-1].rstrip() + "…"
    return fuente, _recortar_lineas_desbordadas(draw, lineas, fuente, max_ancho)


def _avatar_circular(tamano: int, ruta_foto, iniciales: str, color1, color2) -> Image.Image:
    """Avatar circular: la foto real recortada en círculo si se da una ruta
    válida, o un círculo con degradado color1->color2 + iniciales si no."""
    supersample = 4
    tam_hd = tamano * supersample

    if ruta_foto and os.path.exists(ruta_foto):
        foto = Image.open(ruta_foto).convert("RGB")
        lado = min(foto.size)
        foto = foto.crop((
            (foto.width - lado) // 2, (foto.height - lado) // 2,
            (foto.width + lado) // 2, (foto.height + lado) // 2,
        )).resize((tam_hd, tam_hd), Image.LANCZOS)
        circulo = foto.convert("RGBA")
    else:
        base = Image.new("L", (1, tam_hd))
        for y in range(tam_hd):
            base.putpixel((0, y), int(255 * y / max(tam_hd - 1, 1)))
        base = base.resize((tam_hd, tam_hd), Image.LANCZOS)
        circulo = ImageOps.colorize(base, black=color1, white=color2).convert("RGBA")
        draw_ini = ImageDraw.Draw(circulo)
        fuente_ini = _fuente(True, int(tam_hd * 0.36))
        bbox = draw_ini.textbbox((0, 0), iniciales, font=fuente_ini)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw_ini.text(
            ((tam_hd - w) / 2 - bbox[0], (tam_hd - h) / 2 - bbox[1]),
            iniciales, font=fuente_ini, fill=(255, 255, 255, 255),
        )

    mascara = Image.new("L", (tam_hd, tam_hd), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, tam_hd, tam_hd), fill=255)
    circulo.putalpha(mascara)
    circulo = circulo.resize((tamano, tamano), Image.LANCZOS)

    lienzo = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    ImageDraw.Draw(lienzo).ellipse((1, 1, tamano - 2, tamano - 2), outline=(255, 255, 255, 235), width=3)
    lienzo.alpha_composite(circulo)
    return lienzo
