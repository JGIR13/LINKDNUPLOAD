"""
Regresión V5 — rediseño visual de la infografía (image_infografia.py + llm.py).

Cubre las dos mejoras visuales de esta ronda:
- Lienzo oscuro derivado algorítmicamente de la paleta (sin duplicar colores
  a mano en config.py) y retrocompatibilidad con `oscuro=False` (default).
- Título con palabra clave resaltada, con validación de que sea un
  substring literal del título antes de dibujarlo en el color de acento.
"""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

import config
import image_infografia


def _datos_ejemplo(num_items=6, titulo="El peligro de any en TypeScript", resaltado="any"):
    return {
        "titulo": titulo,
        "subtitulo": "Por qué deberías evitarlo en producción",
        "titulo_resaltado": resaltado,
        "icono_principal": "warning",
        "items": [
            {"termino": f"Punto {i+1}", "descripcion": f"Descripción de ejemplo {i+1}", "icono": "idea"}
            for i in range(num_items)
        ],
    }


def _paleta():
    return config.INFOGRAFIA_PALETAS[config.INFOGRAFIA_PALETA_DEFECTO]


class TestContratoPublico:
    def test_genera_png_en_modo_claro_por_defecto(self, tmp_path, monkeypatch):
        monkeypatch.setattr(image_infografia, "GENERATED_IMG_DIR", str(tmp_path))
        ruta = image_infografia.generar_infografia(_datos_ejemplo(), _paleta())
        assert os.path.exists(ruta)
        with Image.open(ruta) as img:
            assert img.width > 0 and img.height > 0

    def test_genera_png_en_modo_oscuro(self, tmp_path, monkeypatch):
        monkeypatch.setattr(image_infografia, "GENERATED_IMG_DIR", str(tmp_path))
        ruta = image_infografia.generar_infografia(_datos_ejemplo(), _paleta(), oscuro=True)
        assert os.path.exists(ruta)

    def test_retrocompatible_sin_titulo_resaltado(self, tmp_path, monkeypatch):
        """Datos generados por una versión anterior (sin `titulo_resaltado`
        ni `icono`/`icono_principal`) no deben romper la generación."""
        monkeypatch.setattr(image_infografia, "GENERATED_IMG_DIR", str(tmp_path))
        datos = {
            "titulo": "Tema sin resaltado",
            "subtitulo": "Subtítulo",
            "items": [{"termino": "A", "descripcion": "B"}],
        }
        ruta = image_infografia.generar_infografia(datos, _paleta())
        assert os.path.exists(ruta)

    def test_con_marca_personal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(image_infografia, "GENERATED_IMG_DIR", str(tmp_path))
        marca = {"nombre": "Jesús Ibáñez", "rol": "Full Stack & AI Developer", "ruta_foto": None}
        ruta = image_infografia.generar_infografia(_datos_ejemplo(), _paleta(), marca=marca, oscuro=True)
        assert os.path.exists(ruta)


class TestPaletaOscura:
    def test_deriva_colores_desde_primario_y_acento(self):
        primario = (10, 102, 194)  # #0A66C2
        acento = (245, 180, 0)     # #F5B400
        paleta = image_infografia._paleta_oscura(primario, acento)

        assert set(paleta.keys()) >= {"fondo", "tarjeta", "texto", "texto_claro", "borde"}
        # El fondo debe ser oscuro (cerca de negro), el texto casi blanco
        r, g, b = paleta["fondo"]
        assert r < 60 and g < 60 and b < 70
        r, g, b = paleta["texto"]
        assert r > 200 and g > 200 and b > 200

    def test_paletas_distintas_dan_fondos_distintos(self):
        p1 = image_infografia._paleta_oscura((10, 102, 194), (245, 180, 0))
        p2 = image_infografia._paleta_oscura((124, 58, 237), (16, 185, 129))
        assert p1["fondo"] != p2["fondo"]


class _FakeResponse:
    def __init__(self, texto):
        self.text = texto


class TestTituloResaltado:
    def test_llm_valida_substring_literal(self, monkeypatch):
        """llm.generar_infografia_contenido debe descartar `titulo_resaltado`
        si NO es un substring literal (case-insensitive) del título que la
        propia IA devolvió, para no arriesgarse a dibujar basura."""
        import json as _json

        import llm

        respuesta_llm = {
            "titulo": "El peligro de any en TypeScript",
            "subtitulo": "Sub",
            "titulo_resaltado": "any",
            "icono_principal": "warning",
            "items": [{"termino": "X", "descripcion": "Y", "icono": "idea"}],
        }
        fake_creds = config.Credentials(
            gemini_api_key="fake-key", linkedin_client_id=None,
            linkedin_client_secret=None, linkedin_redirect_uri=None,
        )
        with monkeypatch.context() as m:
            m.setattr(llm, "get_credentials", lambda: fake_creds)
            m.setattr(llm, "_generar_con_fallback", lambda *a, **k: _FakeResponse(_json.dumps(respuesta_llm)))
            resultado = llm.generar_infografia_contenido(
                "TypeScript", {"tono": "cercano"}, [], num_items=1,
            )
        assert resultado["titulo_resaltado"].lower() == "any"

    def test_llm_descarta_resaltado_que_no_es_substring(self, monkeypatch):
        import json as _json

        import llm

        respuesta_llm = {
            "titulo": "El peligro de any en TypeScript",
            "subtitulo": "Sub",
            "titulo_resaltado": "palabra inventada",
            "icono_principal": "warning",
            "items": [{"termino": "X", "descripcion": "Y", "icono": "idea"}],
        }
        fake_creds = config.Credentials(
            gemini_api_key="fake-key", linkedin_client_id=None,
            linkedin_client_secret=None, linkedin_redirect_uri=None,
        )
        with monkeypatch.context() as m:
            m.setattr(llm, "get_credentials", lambda: fake_creds)
            m.setattr(llm, "_generar_con_fallback", lambda *a, **k: _FakeResponse(_json.dumps(respuesta_llm)))
            resultado = llm.generar_infografia_contenido(
                "TypeScript", {"tono": "cercano"}, [], num_items=1,
            )
        assert resultado["titulo_resaltado"] == ""

    def test_render_no_falla_con_resaltado_vacio_o_ausente(self, tmp_path, monkeypatch):
        monkeypatch.setattr(image_infografia, "GENERATED_IMG_DIR", str(tmp_path))
        datos = _datos_ejemplo(resaltado="")
        ruta = image_infografia.generar_infografia(datos, _paleta(), oscuro=True)
        assert os.path.exists(ruta)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
