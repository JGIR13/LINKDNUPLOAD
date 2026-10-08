"""
Regresión — los datos del usuario sobreviven a una reinstalación (V5.4).

Motivo (pedido explícito del usuario): "quisiera que... la información [no
cambie] al cambiar de versión" — antes, la base de datos (data/app.db) y las
imágenes subidas/generadas (static/generated, static/inspiracion,
static/perfil) vivían DENTRO de la propia carpeta de instalación de la app
(config.BASE_DIR). Reinstalar desde cero — descomprimir una versión nueva
del zip en una carpeta nueva, o mover la instalación a otro sitio — las
perdía sin avisar (de hecho, el propio zip que se entrega EXCLUYE
deliberadamente data/app.db para no enviar datos de prueba).

Ahora esos datos viven en la carpeta de datos de aplicación del usuario
(%LOCALAPPDATA% en Windows, ~/.local/share en otros sistemas — o donde
apunte LINKEDIN_AI_POSTER_DATOS), independiente de dónde esté el código, y
la primera vez que arranca esta versión se migran automáticamente desde el
sitio antiguo si los encuentra ahí (sin borrar nunca el original).

Cubre las dos funciones de config.py que implementan esto:
- `_carpeta_datos_persistentes`: resuelve la carpeta (con
  LINKEDIN_AI_POSTER_DATOS como escape hatch para tests/desarrollo).
- `_migrar_si_hace_falta`: copia (nunca mueve) origen -> destino solo la
  primera vez, y es inofensiva si no hay nada que migrar o si el destino
  ya existe (no pisa datos nuevos con datos viejos en arranques
  posteriores).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))


class TestCarpetaDatosPersistentes:
    def test_respeta_la_variable_de_entorno(self, monkeypatch, tmp_path):
        import config

        destino = str(tmp_path / "datos_forzados")
        monkeypatch.setenv("LINKEDIN_AI_POSTER_DATOS", destino)
        assert config._carpeta_datos_persistentes() == destino

    def test_sin_variable_de_entorno_usa_localappdata_o_home(self, monkeypatch):
        import config

        monkeypatch.delenv("LINKEDIN_AI_POSTER_DATOS", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\alguien\\AppData\\Local")
        assert config._carpeta_datos_persistentes() == os.path.join(
            "C:\\Users\\alguien\\AppData\\Local", "LinkedInAIPoster"
        )

        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        carpeta = config._carpeta_datos_persistentes()
        assert carpeta == os.path.join(os.path.expanduser("~"), ".local", "share", "LinkedInAIPoster")


class TestMigrarSiHaceFalta:
    def test_copia_un_archivo_si_el_destino_no_existe(self, tmp_path):
        import config

        origen = tmp_path / "vieja" / "app.db"
        origen.parent.mkdir()
        origen.write_text("datos reales del usuario")
        destino = tmp_path / "nueva" / "app.db"

        config._migrar_si_hace_falta(str(origen), str(destino))

        assert destino.read_text() == "datos reales del usuario"
        assert origen.exists()  # el original NUNCA se borra

    def test_no_pisa_un_destino_que_ya_existe(self, tmp_path):
        """Crítico: en cada arranque se vuelve a llamar — si el destino ya
        existe (instalación ya migrada, con datos nuevos desde entonces),
        NO debe sobrescribirlo con la copia vieja."""
        import config

        origen = tmp_path / "vieja" / "app.db"
        origen.parent.mkdir()
        origen.write_text("dato viejo")
        destino = tmp_path / "nueva" / "app.db"
        destino.parent.mkdir()
        destino.write_text("dato nuevo, ya migrado antes")

        config._migrar_si_hace_falta(str(origen), str(destino))

        assert destino.read_text() == "dato nuevo, ya migrado antes"

    def test_no_hace_nada_si_no_hay_origen(self, tmp_path):
        import config

        origen = tmp_path / "no_existe" / "app.db"
        destino = tmp_path / "nueva" / "app.db"

        config._migrar_si_hace_falta(str(origen), str(destino))

        assert not destino.exists()

    def test_copia_un_arbol_de_carpetas_completo(self, tmp_path):
        import config

        origen = tmp_path / "vieja" / "generated"
        origen.mkdir(parents=True)
        (origen / "post1.png").write_bytes(b"contenido binario 1")
        sub = origen / "subcarpeta"
        sub.mkdir()
        (sub / "post2.png").write_bytes(b"contenido binario 2")
        destino = tmp_path / "nueva" / "generated"

        config._migrar_si_hace_falta(str(origen), str(destino))

        assert (destino / "post1.png").read_bytes() == b"contenido binario 1"
        assert (destino / "subcarpeta" / "post2.png").read_bytes() == b"contenido binario 2"

    def test_es_inofensivo_llamarla_repetidamente(self, tmp_path):
        """Se llama en CADA arranque de la app (no solo el primero) — debe
        ser barata y segura de repetir indefinidamente."""
        import config

        origen = tmp_path / "vieja" / "app.db"
        origen.parent.mkdir()
        origen.write_text("dato")
        destino = tmp_path / "nueva" / "app.db"

        for _ in range(5):
            config._migrar_si_hace_falta(str(origen), str(destino))

        assert destino.read_text() == "dato"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
