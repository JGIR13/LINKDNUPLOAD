"""
Regresión V5 — arquitectura multiusuario (db.py + config.py + linkedin_oauth.py).

Cubre las garantías que motivaron el rediseño de esta ronda:
- Cuentas reales (alta, login, cambio de contraseña, roles).
- AISLAMIENTO DE DATOS entre cuentas (la garantía arquitectónica central).
- Config global (LinkedIn/Gemini) compartida por todas las cuentas.
- Firma HMAC del `state` OAuth por cuenta (sobrevive al full-page-reload).

Uso: cada test usa su propia base de datos SQLite temporal (nunca la real
de desarrollo), fijando `config.DB_PATH`/`db.DB_PATH` antes de `db.init_db()`.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture()
def dbtmp(monkeypatch):
    """Aísla cada test en su propia BD SQLite temporal."""
    import config
    import db

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # que init_db la cree de cero

    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    yield db
    if os.path.exists(path):
        os.unlink(path)


def _crear_cuenta(db, config, email, password, rol="usuario", nombre="Test"):
    h, s = config.hash_password(password)
    return db.crear_cuenta(email, h, s, nombre=nombre, rol=rol)


class TestCuentas:
    def test_alta_y_login(self, dbtmp):
        import config
        db = dbtmp
        cid = _crear_cuenta(db, config, "admin@test.com", "Secreta123", rol="admin")
        cuenta = db.obtener_cuenta_por_email("admin@test.com")
        assert cuenta is not None
        assert cuenta["id"] == cid
        assert cuenta["rol"] == "admin"
        assert config.verify_password("Secreta123", cuenta["password_hash"], cuenta["password_salt"])
        assert not config.verify_password("otra-clave", cuenta["password_hash"], cuenta["password_salt"])

    def test_email_unico(self, dbtmp):
        import config
        db = dbtmp
        _crear_cuenta(db, config, "dup@test.com", "clave1")
        # Tipo de excepción exacto, no un `Exception` genérico: app.py depende
        # de capturar justo `sqlite3.IntegrityError` para convertir un email
        # duplicado en un aviso claro en vez de una traceback cruda (ver
        # `_pantalla_login` y "➕ Crear cuenta nueva" en 🛠️ Administración).
        with pytest.raises(sqlite3.IntegrityError):
            _crear_cuenta(db, config, "dup@test.com", "clave2")

    def test_cambiar_password(self, dbtmp):
        import config
        db = dbtmp
        cid = _crear_cuenta(db, config, "u@test.com", "vieja123")
        h2, s2 = config.hash_password("nueva456")
        db.cambiar_password_cuenta(cid, h2, s2, debe_cambiar_password=False)
        cuenta = db.obtener_cuenta(cid)
        assert config.verify_password("nueva456", cuenta["password_hash"], cuenta["password_salt"])
        assert not config.verify_password("vieja123", cuenta["password_hash"], cuenta["password_salt"])
        assert not cuenta["debe_cambiar_password"]

    def test_debe_cambiar_password_flag(self, dbtmp):
        import config
        db = dbtmp
        cid = _crear_cuenta(db, config, "temp@test.com", "temporal1")
        cuenta = db.obtener_cuenta(cid)
        assert not cuenta["debe_cambiar_password"]  # default False al crear directo

        h, s = config.hash_password("otra")
        cid2 = db.crear_cuenta("temp2@test.com", h, s, rol="usuario", debe_cambiar_password=True)
        cuenta2 = db.obtener_cuenta(cid2)
        assert cuenta2["debe_cambiar_password"]

    def test_roles_admin_vs_usuario(self, dbtmp):
        import config
        db = dbtmp
        admin_id = _crear_cuenta(db, config, "a@test.com", "x", rol="admin")
        user_id = _crear_cuenta(db, config, "b@test.com", "x", rol="usuario")
        assert db.obtener_cuenta(admin_id)["rol"] == "admin"
        assert db.obtener_cuenta(user_id)["rol"] == "usuario"

        db.actualizar_cuenta(user_id, rol="admin")
        assert db.obtener_cuenta(user_id)["rol"] == "admin"

    def test_activar_desactivar_cuenta(self, dbtmp):
        import config
        db = dbtmp
        cid = _crear_cuenta(db, config, "c@test.com", "x")
        assert db.obtener_cuenta(cid)["activo"]
        db.actualizar_cuenta(cid, activo=False)
        assert not db.obtener_cuenta(cid)["activo"]
        db.actualizar_cuenta(cid, activo=True)
        assert db.obtener_cuenta(cid)["activo"]

    def test_eliminar_cuenta_borra_sus_datos(self, dbtmp):
        import config
        db = dbtmp
        cid = _crear_cuenta(db, config, "borrar@test.com", "x")
        db.crear_post(cid, "tema de prueba", "texto", "")
        assert len(db.listar_posts(cid)) == 1

        db.eliminar_cuenta_y_datos(cid)
        assert db.obtener_cuenta(cid) is None
        # listar_posts sobre una cuenta borrada no debe reventar ni devolver nada
        assert db.listar_posts(cid) == []


class TestAislamientoDeDatos:
    """La garantía arquitectónica central de la V5: los datos de una cuenta
    nunca deben ser visibles ni alcanzables desde otra."""

    def test_posts_aislados_por_cuenta(self, dbtmp):
        import config
        db = dbtmp
        admin_id = _crear_cuenta(db, config, "admin@x.com", "x", rol="admin")
        colega_id = _crear_cuenta(db, config, "colega@x.com", "x", rol="usuario")

        db.crear_post(admin_id, "tema del admin", "texto admin", "")
        db.crear_post(colega_id, "tema del colega", "texto colega", "")

        posts_admin = db.listar_posts(admin_id)
        posts_colega = db.listar_posts(colega_id)

        assert len(posts_admin) == 1 and posts_admin[0]["tema"] == "tema del admin"
        assert len(posts_colega) == 1 and posts_colega[0]["tema"] == "tema del colega"
        # Ningún post de una cuenta aparece en el listado de la otra
        assert all(p["tema"] != "tema del colega" for p in posts_admin)
        assert all(p["tema"] != "tema del admin" for p in posts_colega)

    def test_parametros_aislados_por_cuenta(self, dbtmp):
        import config
        db = dbtmp
        a = _crear_cuenta(db, config, "a@x.com", "x")
        b = _crear_cuenta(db, config, "b@x.com", "x")

        db.guardar_parametros(a, "cercano", "tech", "media", True, True, "", "", "",
                               infografia_estilo_defecto="oscuro")
        db.guardar_parametros(b, "formal", "finanzas", "corta", False, False, "", "", "",
                               infografia_estilo_defecto="claro")

        pa = db.obtener_parametros(a)
        pb = db.obtener_parametros(b)
        assert pa["sector"] == "tech" and pa["infografia_estilo_defecto"] == "oscuro"
        assert pb["sector"] == "finanzas" and pb["infografia_estilo_defecto"] == "claro"

    def test_temas_rotativos_aislados_por_cuenta(self, dbtmp):
        import config
        db = dbtmp
        a = _crear_cuenta(db, config, "a2@x.com", "x")
        b = _crear_cuenta(db, config, "b2@x.com", "x")

        db.agregar_tema(a, "Python")
        db.agregar_tema(b, "Marketing")

        temas_a = [t["nombre"] for t in db.listar_temas(a)]
        temas_b = [t["nombre"] for t in db.listar_temas(b)]
        assert temas_a == ["Python"]
        assert temas_b == ["Marketing"]

    def test_linkedin_token_no_se_comparte(self, dbtmp):
        import config
        db = dbtmp
        a = _crear_cuenta(db, config, "li_a@x.com", "x")
        b = _crear_cuenta(db, config, "li_b@x.com", "x")

        db.guardar_tokens_linkedin(a, "token-de-a", "refresh-a", "2030-01-01T00:00:00",
                                    member_urn="urn:a", nombre="Cuenta A")
        cuenta_a = db.obtener_cuenta(a)
        cuenta_b = db.obtener_cuenta(b)
        assert cuenta_a["linkedin_access_token"] == "token-de-a"
        assert not cuenta_b.get("linkedin_access_token")


class TestConfigGlobal:
    """LinkedIn Client ID/Secret y la clave de Gemini SÍ son compartidos por
    toda la instalación (a diferencia de los datos por cuenta)."""

    def test_credenciales_linkedin_globales_visibles_a_cualquier_cuenta(self, dbtmp):
        db = dbtmp
        db.guardar_credenciales_linkedin_global("client123", "secret456", "http://localhost:8501")
        cfg = db.obtener_config_global()
        assert cfg["linkedin_client_id"] == "client123"
        assert cfg["linkedin_client_secret"] == "secret456"

    def test_gemini_key_global(self, dbtmp):
        db = dbtmp
        db.guardar_gemini_api_key_global("AIza-fake-key")
        cfg = db.obtener_config_global()
        assert cfg["gemini_api_key"] == "AIza-fake-key"

    def test_app_secret_estable(self, dbtmp):
        db = dbtmp
        s1 = db.obtener_o_crear_app_secret()
        s2 = db.obtener_o_crear_app_secret()
        assert s1 == s2
        assert len(s1) >= 32


class TestOAuthStatePorCuenta:
    """El `state` OAuth debe sobrevivir al full-page-reload de LinkedIn y
    recuperar la cuenta correcta, firmado para que no se pueda falsificar."""

    def test_state_firmado_recupera_la_cuenta(self, dbtmp):
        import linkedin_oauth
        db = dbtmp
        cid = db.crear_cuenta("oauth@test.com", "h", "s", rol="usuario")

        state = linkedin_oauth.generar_state(cid)
        recuperado = linkedin_oauth.verificar_y_extraer_cuenta(state)
        assert recuperado == cid

    def test_state_manipulado_se_rechaza(self, dbtmp):
        import linkedin_oauth
        db = dbtmp
        cid = db.crear_cuenta("oauth2@test.com", "h", "s", rol="usuario")

        state = linkedin_oauth.generar_state(cid)
        # Manipular el cuenta_id embebido sin volver a firmar
        manipulado = state.replace(str(cid), str(cid + 999), 1)
        resultado = linkedin_oauth.verificar_y_extraer_cuenta(manipulado)
        assert resultado != cid  # o None, o falla — nunca debe validar como si fuera cid


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
