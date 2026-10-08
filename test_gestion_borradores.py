"""
Regresión — gestión de borradores en 🗂️ Historial (esta ronda).

Motivo: los 12 borradores pendientes de aprobación no tenían forma de
denegarse (borrarse) ni de actuar sobre varios a la vez — solo existía
"Publicar en LinkedIn" uno a uno. Cubre lo nuevo en db.py:

- `db.eliminar_post`: borra el post y, si venía del plan diario
  (`generacion_diaria.post_id` apuntaba a él), limpia esa referencia para
  no dejar un post_id colgando hacia una fila ya borrada.
"""
import os
import sys
import tempfile

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(__file__))
APP_PATH = os.path.join(os.path.dirname(__file__), "app.py")


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


def _login_como(at, email, password):
    """Rellena el formulario de login (cuentas ya existentes: email +
    contraseña) y lo envía — mismo patrón que test_app_smoke.py."""
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    return at


class TestEliminarPost:
    def test_borra_el_post(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("borra1@test.com", "h", "s")
        pid = db.crear_post(cid, "tema", "texto", "")
        assert db.obtener_post(pid) is not None

        db.eliminar_post(pid)
        assert db.obtener_post(pid) is None
        assert db.listar_posts(cid) == []

    def test_no_afecta_a_otros_posts_de_la_cuenta(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("borra2@test.com", "h", "s")
        p1 = db.crear_post(cid, "tema 1", "t1", "")
        p2 = db.crear_post(cid, "tema 2", "t2", "")

        db.eliminar_post(p1)

        restantes = db.listar_posts(cid)
        assert len(restantes) == 1
        assert restantes[0]["id"] == p2

    def test_limpia_la_referencia_en_el_plan_diario(self, dbtmp):
        """Un post generado desde 📅 Generación diaria queda enlazado desde
        `generacion_diaria.post_id`. Borrarlo desde Historial no debe dejar
        ese puntero colgando hacia una fila que ya no existe."""
        db = dbtmp
        cid = db.crear_cuenta("borra3@test.com", "h", "s")
        fecha = "2026-09-27"
        db.crear_items_plan_dia(cid, fecha, "texto", 1)
        item = db.listar_plan_dia(cid, fecha)[0]

        pid = db.crear_post(cid, "tema del plan", "texto", "")
        db.actualizar_item_plan_dia(item["id"], estado="generado", post_id=pid)
        assert db.listar_plan_dia(cid, fecha)[0]["post_id"] == pid

        db.eliminar_post(pid)

        item_tras_borrado = db.listar_plan_dia(cid, fecha)[0]
        assert item_tras_borrado["post_id"] is None
        # El estado del item no se toca — solo se limpia el puntero muerto.
        assert item_tras_borrado["estado"] == "generado"


class TestInterfazDeAprobacionEnHistorial:
    """Prueba end-to-end (streamlit.testing.v1.AppTest) de la nueva interfaz
    de gestión de borradores: "Denegar (borrar)" con confirmación en dos
    pasos, y "Seleccionar todos" — este último cubre específicamente un bug
    real de Streamlit (el checkbox de cada item ignora un `value=`
    recalculado una vez que ya tiene una key en session_state) que se
    solucionó pre-sembrando `st.session_state[f"hist_sel_{id}"]` antes de
    instanciar cada checkbox, en vez de pasarle `value=`."""

    def test_denegar_borrador_lo_elimina_tras_confirmar(self, dbtmp):
        db = dbtmp
        import config

        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("hist_deny@test.com", h, s, rol="admin", nombre="Admin")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "hist_deny@test.com", "ClaveAdmin123")
        assert not at.exception

        cuenta_id = at.session_state["cuenta_id"]
        pid = db.crear_post(cuenta_id, "Post a denegar", "texto", "")

        nav = at.segmented_control[0]
        nav.set_value("🗂️ Historial").run()
        assert not at.exception

        # Aún no está borrado con un solo clic — primero pide confirmación.
        at.button(key=f"hist_del_{pid}").click().run()
        assert not at.exception
        assert db.obtener_post(pid) is not None

        at.button(key=f"hist_del_si_{pid}").click().run()
        assert not at.exception
        assert db.obtener_post(pid) is None

    def test_seleccionar_todos_marca_cada_checkbox_individual(self, dbtmp):
        """Reproduce el bug encontrado: sin la pre-siembra de session_state,
        el botón "Seleccionar todos" quedaba anulado en el mismo run por
        los checkboxes individuales (que ignoran el `value=` recalculado y
        conservan su estado previo sin marcar)."""
        db = dbtmp
        import config

        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("hist_selall@test.com", h, s, rol="admin", nombre="Admin")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "hist_selall@test.com", "ClaveAdmin123")
        cuenta_id = at.session_state["cuenta_id"]

        db.crear_post(cuenta_id, "Borrador 1", "t1", "")
        db.crear_post(cuenta_id, "Borrador 2", "t2", "")

        nav = at.segmented_control[0]
        nav.set_value("🗂️ Historial").run()
        assert not at.exception

        at.button(key="hist_btn_sel_todos").click().run()
        assert not at.exception

        assert len(at.session_state["hist_seleccion"]) == 2
        assert all(c.value is True for c in at.checkbox if (c.key or "").startswith("hist_sel_"))

        # El botón de publicar seleccionados ya no está deshabilitado (LinkedIn
        # no está conectado en el test, pero el de borrar sí lo comprobamos).
        boton_borrar_sel = at.button(key="hist_borrar_sel")
        assert "2" in boton_borrar_sel.label


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
