"""
Regresión V5 — temáticas rotativas (db.siguiente_tema_rotacion + daily._elegir_tema).

Cubre el diseño elegido explícitamente por el usuario vía AskUserQuestion
("lista de temas que rotan solos"): round-robin simple, con fallback a
tema libre cuando no hay ninguna temática activa configurada.
"""
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture()
def dbtmp(monkeypatch):
    import config
    import db

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    yield db
    if os.path.exists(path):
        os.unlink(path)


class TestRotacionRoundRobin:
    def test_sin_temas_devuelve_none(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("sin_temas@test.com", "h", "s")
        assert db.siguiente_tema_rotacion(cid) is None

    def test_rota_en_orden(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("rota@test.com", "h", "s")
        db.agregar_tema(cid, "Python")
        db.agregar_tema(cid, "Seguridad")
        db.agregar_tema(cid, "Cloud")

        secuencia = [db.siguiente_tema_rotacion(cid) for _ in range(6)]
        assert secuencia == ["Python", "Seguridad", "Cloud", "Python", "Seguridad", "Cloud"]

    def test_temas_inactivos_se_saltan(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("skip@test.com", "h", "s")
        id_python = db.agregar_tema(cid, "Python")
        db.agregar_tema(cid, "Seguridad")
        db.activar_tema(id_python, False)

        secuencia = [db.siguiente_tema_rotacion(cid) for _ in range(4)]
        assert secuencia == ["Seguridad", "Seguridad", "Seguridad", "Seguridad"]

    def test_eliminar_tema_lo_saca_de_la_rotacion(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("elim@test.com", "h", "s")
        db.agregar_tema(cid, "Python")
        id_seg = db.agregar_tema(cid, "Seguridad")
        db.eliminar_tema(id_seg)

        secuencia = [db.siguiente_tema_rotacion(cid) for _ in range(3)]
        assert secuencia == ["Python", "Python", "Python"]

    def test_no_afecta_a_otras_cuentas(self, dbtmp):
        db = dbtmp
        a = db.crear_cuenta("a3@test.com", "h", "s")
        b = db.crear_cuenta("b3@test.com", "h", "s")
        db.agregar_tema(a, "SoloDeA")
        db.agregar_tema(b, "SoloDeB")

        assert db.siguiente_tema_rotacion(a) == "SoloDeA"
        assert db.siguiente_tema_rotacion(b) == "SoloDeB"
        # confirmar que el índice de A no afectó a B
        assert db.siguiente_tema_rotacion(a) == "SoloDeA"
        assert db.siguiente_tema_rotacion(b) == "SoloDeB"


class TestElegirTemaEnDaily:
    """daily._elegir_tema debe pasar el tema rotativo como restricción al
    LLM cuando existe, y dejar que la IA proponga libremente cuando no."""

    def test_usa_tema_rotativo_si_existe(self, dbtmp):
        import daily
        db = dbtmp
        cid = db.crear_cuenta("d1@test.com", "h", "s")
        db.agregar_tema(cid, "Python")
        parametros = db.obtener_parametros(cid)

        with patch("daily.llm.sugerir_tema_automatico", return_value="Ángulo concreto de Python") as mock_llm:
            tema = daily._elegir_tema(cid, parametros)
            assert tema == "Ángulo concreto de Python"
            _, kwargs = mock_llm.call_args
            assert kwargs.get("tema_base") == "Python"

    def test_tema_libre_si_no_hay_temas_configurados(self, dbtmp):
        import daily
        db = dbtmp
        cid = db.crear_cuenta("d2@test.com", "h", "s")
        parametros = db.obtener_parametros(cid)

        with patch("daily.llm.sugerir_tema_automatico", return_value="Tema libre propuesto") as mock_llm:
            tema = daily._elegir_tema(cid, parametros)
            assert tema == "Tema libre propuesto"
            _, kwargs = mock_llm.call_args
            assert kwargs.get("tema_base") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
