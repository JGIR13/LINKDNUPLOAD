"""
Regresión V5 — smoke test end-to-end de app.py con streamlit.testing.v1.AppTest.

No usa credenciales reales de ningún proveedor (Gemini/LinkedIn) — solo
verifica que las páginas renderizan sin excepción y que las garantías de
la V5 se cumplen a nivel de interfaz:
- Alta de la primera cuenta (queda como admin) y login normal.
- Las 6 páginas de la navegación normal, sin excepciones — y que
  "🛠️ Administración" NUNCA está entre ellas, ni siquiera para una cuenta
  admin (es una pantalla completamente aparte, ver TestPanelAdministrativoAparte).
- Una cuenta con rol 'usuario' NUNCA ve "🛠️ Administración" en su menú.
- El panel administrativo, alcanzable solo vía ?admin=1: login con cuenta
  admin, rechazo de cuentas no-admin y de credenciales incorrectas, y el
  enlace hacia él en la pantalla de login normal.
- Cambio de contraseña obligatorio al entrar con una cuenta recién creada
  por el administrador (contraseña temporal).
- Aislamiento de datos entre cuentas, verificado desde la propia UI
  (Historial de una cuenta no muestra los posts de otra).

Cada test usa su propia base de datos SQLite temporal.
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
    """Rellena el formulario de login (cuentas ya existentes: email + contraseña)
    y lo envía."""
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    return at


class TestPrimerArranqueYLogin:
    def test_sin_cuentas_muestra_alta_de_admin(self, dbtmp):
        at = AppTest.from_file(APP_PATH)
        at.run()
        assert not at.exception
        textos = [md.value for md in at.markdown] + [i.value for i in at.info]
        assert any("Inicia sesión" in t or "Crea la cuenta" in t or "Todavía no hay ninguna cuenta" in t
                   for t in textos)

    def test_alta_primera_cuenta_queda_como_admin(self, dbtmp):
        db = dbtmp
        at = AppTest.from_file(APP_PATH)
        at.run()
        assert not at.exception

        # Formulario de alta: nombre, email, contraseña, repetir contraseña
        at.text_input[0].set_value("Jesús Ibáñez")
        at.text_input[1].set_value("jesus.ibanez@exacloud.com")
        at.text_input[2].set_value("ClaveSegura123")
        at.text_input[3].set_value("ClaveSegura123")
        at.button[0].click().run()
        assert not at.exception

        cuenta = db.obtener_cuenta_por_email("jesus.ibanez@exacloud.com")
        assert cuenta is not None
        assert cuenta["rol"] == "admin"

    def test_login_con_credenciales_incorrectas_muestra_error(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveReal123")
        db.crear_cuenta("existe@test.com", h, s, rol="admin")

        at = AppTest.from_file(APP_PATH)
        at.run()

        # La pantalla de login normal (con cuentas ya existentes) enlaza al
        # panel administrativo aparte, al estilo del acceso separado de
        # wp-admin — nunca lo mezcla con la navegación de la app.
        assert any("Panel administrativo" in c.value and "?admin=1" in c.value
                   for c in at.caption)

        _login_como(at, "existe@test.com", "clave-equivocada")
        assert not at.exception
        assert any("incorrectos" in e.value for e in at.error)

    def test_alta_primera_cuenta_con_email_ya_registrado_no_revienta(self, dbtmp, monkeypatch):
        """Regresión de un caso visto en producción: un
        sqlite3.IntegrityError sin capturar tumbaba la app con una
        traceback cruda al enviar el formulario de alta de la primera
        cuenta con un email que, en el instante de insertar, ya existía
        (p. ej. un doble envío del formulario). Se simula la condición de
        carrera exacta: en el momento en que app.py comprueba que no hay
        ninguna cuenta y que ese email está libre, ambas comprobaciones
        siguen diciendo que no hay nada — pero el INSERT real choca contra
        una fila que ya está en la base de datos. El aviso amigable debe
        mostrarse y la app NUNCA debe lanzar una excepción."""
        db = dbtmp
        import config

        at = AppTest.from_file(APP_PATH)
        at.run()
        assert not at.exception  # sin cuentas todavía -> pantalla de alta

        # La cuenta ya existe de verdad en la base de datos (para que el
        # INSERT real choque), pero se simula que, en el instante exacto en
        # que app.py la comprueba, todavía "no se ve" — la condición de
        # carrera real: el chequeo y el INSERT no son atómicos.
        h, s = config.hash_password("ClaveExistente123")
        db.crear_cuenta("jesusgibanez@gmail.com", h, s, nombre="Jesús", rol="admin")
        monkeypatch.setattr(db, "listar_cuentas", lambda: [])
        monkeypatch.setattr(db, "obtener_cuenta_por_email", lambda email: None)

        at.text_input[0].set_value("Jesús Ibáñez")
        at.text_input[1].set_value("jesusgibanez@gmail.com")
        at.text_input[2].set_value("OtraClaveNueva123")
        at.text_input[3].set_value("OtraClaveNueva123")
        at.button[0].click().run()

        assert not at.exception
        assert any("Ya existe una cuenta con ese email" in e.value for e in at.error)
        # Nunca se creó una sesión con la cuenta a medio insertar.
        assert "cuenta_id" not in at.session_state


class TestNavegacionYRoles:
    def test_admin_ve_las_6_paginas_sin_excepciones_y_sin_administracion(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("admin@test.com", h, s, rol="admin", nombre="Admin")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "admin@test.com", "ClaveAdmin123")
        assert not at.exception

        etiquetas_esperadas = [
            "🚀 Generar", "📅 Generación diaria", "✨ Inspiración",
            "⚙️ Configuración", "🗂️ Historial", "🔗 LinkedIn",
        ]
        # at.segmented_control[i].options devuelve las etiquetas SIN emoji
        # (quirk conocido de AppTest) — comparamos contra la versión sin
        # emoji de lo esperado, pero set_value() exige la etiqueta ORIGINAL
        # con emoji (si no, no cambia el valor del widget y no lanza error).
        etiquetas_sin_emoji = [e.split(" ", 1)[1] for e in etiquetas_esperadas]
        opciones = at.segmented_control[0].options
        assert set(opciones) == set(etiquetas_sin_emoji)
        # "🛠️ Administración" (ni su versión sin emoji) NUNCA debe estar en
        # la navegación normal, ni siquiera para una cuenta admin — es una
        # pantalla completamente aparte (ver TestPanelAdministrativoAparte).
        assert not any("dministra" in o for o in opciones)

        # Re-obtenemos el widget de navegación en cada vuelta (no reutilizamos
        # una referencia vieja): cada `.run()` reconstruye el árbol de la
        # página, y páginas distintas montan widgets distintos (p. ej. el
        # selector de modo solo existe en "Generar") — mantener una
        # referencia stale a través de varios `.run()` puede arrastrar
        # estado de un widget que ya no está montado en la página actual.
        for etiqueta in etiquetas_esperadas:
            at.segmented_control[0].set_value(etiqueta).run()
            assert not at.exception, f"La página '{etiqueta}' lanzó una excepción: {at.exception}"

        # El enlace de la barra lateral hacia el panel administrativo aparte
        # (visible solo para cuentas admin) debe seguir montado tras navegar.
        html_sidebar = " ".join(getattr(md, "value", "") for md in at.sidebar.markdown)
        assert "Panel administrativo" in html_sidebar
        assert "?admin=1" in html_sidebar

    def test_usuario_normal_nunca_ve_administracion(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("temporal123")
        cid = db.crear_cuenta("colega@test.com", h, s, rol="usuario", nombre="Colega",
                               debe_cambiar_password=True)

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "colega@test.com", "temporal123")
        assert not at.exception

        # Primer login con contraseña temporal -> pantalla de cambio obligatorio
        assert any("Cambia tu contraseña" in md.value for md in at.markdown)

        at.text_input[0].set_value("MiClaveNueva456")
        at.text_input[1].set_value("MiClaveNueva456")
        at.button[0].click().run()
        assert not at.exception

        cuenta = db.obtener_cuenta(cid)
        assert not cuenta["debe_cambiar_password"]

        nav = at.segmented_control[0]
        assert not any("dministra" in o for o in nav.options)

        # Una cuenta 'usuario' tampoco debe ver el enlace de la barra
        # lateral hacia el panel administrativo (solo se muestra a admins).
        html_sidebar = " ".join(getattr(md, "value", "") for md in at.sidebar.markdown)
        assert "Panel administrativo" not in html_sidebar


class TestPanelAdministrativoAparte:
    """El panel de administración es una pantalla COMPLETAMENTE APARTE de la
    app normal (nunca una pestaña de su navegación) — solo se alcanza
    visitando ?admin=1, al estilo del acceso separado de wp-admin, y exige
    loguearse ahí con una cuenta propia que tenga rol='admin'."""

    @staticmethod
    def _ir_al_panel(dbtmp_or_none=None):
        at = AppTest.from_file(APP_PATH)
        at.query_params["admin"] = "1"
        at.run()
        return at

    def test_admin_1_en_la_url_muestra_login_del_panel_sin_sesion_normal(self, dbtmp):
        # Sin haber iniciado sesión en la app normal en absoluto, ?admin=1
        # debe llevar directo al login del panel (no a la app normal ni a
        # la pantalla de alta de la primera cuenta).
        at = self._ir_al_panel()
        assert not at.exception
        assert any("Panel de administración" in md.value for md in at.markdown)
        assert any("Volver al inicio de sesión normal" in c.value for c in at.caption)

    def test_cuenta_admin_puede_entrar_al_panel(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("admin@test.com", h, s, rol="admin", nombre="Admin")

        at = self._ir_al_panel()
        at.text_input[0].set_value("admin@test.com")
        at.text_input[1].set_value("ClaveAdmin123")
        at.button[0].click().run()
        assert not at.exception

        assert any("Administración" in md.value for md in at.markdown)
        assert any("Sesión de administrador: admin@test.com" in c.value for c in at.caption)

    def test_cuenta_usuario_normal_es_rechazada_en_el_panel(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveUsuario123")
        db.crear_cuenta("colega@test.com", h, s, rol="usuario", nombre="Colega")

        at = self._ir_al_panel()
        at.text_input[0].set_value("colega@test.com")
        at.text_input[1].set_value("ClaveUsuario123")
        at.button[0].click().run()
        assert not at.exception

        assert any("no tiene permisos de administrador" in e.value for e in at.error)
        # Nunca llega a renderizar el contenido del panel.
        assert not any("Sesión de administrador" in c.value for c in at.caption)

    def test_credenciales_incorrectas_son_rechazadas_en_el_panel(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("admin@test.com", h, s, rol="admin", nombre="Admin")

        at = self._ir_al_panel()
        at.text_input[0].set_value("admin@test.com")
        at.text_input[1].set_value("clave-equivocada")
        at.button[0].click().run()
        assert not at.exception

        assert any("incorrectos" in e.value for e in at.error)

    def test_cuenta_admin_desactivada_es_rechazada_en_el_panel(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveAdmin123")
        admin_id = db.crear_cuenta("admin@test.com", h, s, rol="admin", nombre="Admin")
        db.actualizar_cuenta(admin_id, activo=False)

        at = self._ir_al_panel()
        at.text_input[0].set_value("admin@test.com")
        at.text_input[1].set_value("ClaveAdmin123")
        at.button[0].click().run()
        assert not at.exception

        assert any("desactivada" in e.value for e in at.error)


class TestGeneracionDiariaControlesNuevos:
    """Comprueba que los controles nuevos de "📅 Generación diaria" (hora
    de la Automatización Total + "🚀 Subida masiva") están realmente
    montados en la página, no solo que la página no lanza excepción."""

    def test_hora_automatizacion_y_subida_masiva_estan_presentes(self, dbtmp):
        db = dbtmp
        import config
        h, s = config.hash_password("ClaveAdmin123")
        db.crear_cuenta("admin_diaria@test.com", h, s, rol="admin", nombre="Admin")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "admin_diaria@test.com", "ClaveAdmin123")
        at.segmented_control[0].set_value("📅 Generación diaria").run()
        assert not at.exception

        # Hora configurable de la Automatización Total (Task #44).
        assert len(at.time_input) >= 1

        # Checkbox de publicar-o-no de la subida masiva, tal como lo pidió
        # el usuario explícitamente ("un checkbox preguntándole... si
        # subirlos... o si requiere aprobación previa").
        etiquetas_checkbox = [c.label for c in at.checkbox]
        assert any("Publicar automáticamente en LinkedIn" in e for e in etiquetas_checkbox)

        etiquetas_numeros = [n.label for n in at.number_input]
        assert any("Infografías en esta tanda" in e for e in etiquetas_numeros)
        assert any("Solo texto en esta tanda" in e for e in etiquetas_numeros)

        etiquetas_botones = [b.label for b in at.button]
        assert any("Generar" in e and "post(s) ahora" in e for e in etiquetas_botones)


class TestAislamientoDeDatosEnLaUI:
    def test_historial_no_muestra_posts_de_otra_cuenta(self, dbtmp):
        db = dbtmp
        import config
        h1, s1 = config.hash_password("ClaveAdmin123")
        admin_id = db.crear_cuenta("admin2@test.com", h1, s1, rol="admin", nombre="Admin")
        h2, s2 = config.hash_password("ClaveColega123")
        colega_id = db.crear_cuenta("colega2@test.com", h2, s2, rol="usuario", nombre="Colega")

        db.crear_post(admin_id, "Tema exclusivo del admin", "Texto del admin", "")
        db.crear_post(colega_id, "Tema exclusivo del colega", "Texto del colega", "")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "colega2@test.com", "ClaveColega123")
        assert not at.exception

        nav = at.segmented_control[0]
        nav.set_value("🗂️ Historial").run()
        assert not at.exception

        texto_pagina = " ".join(md.value for md in at.markdown) + " ".join(c.value for c in at.caption)
        assert "Tema exclusivo del colega" in texto_pagina
        assert "Tema exclusivo del admin" not in texto_pagina


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
