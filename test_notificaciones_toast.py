"""
Regresión — notificaciones "toast" en las acciones de guardado (V5.4).

Motivo (pedido explícito del usuario): "que al utilizar un botón salten
sutiles mensajes de guardado, hecho con éxito o error si da error... para
que se sienta más viva". Antes, cada acción de guardado dejaba un
`st.success`/`st.warning`/`st.error` FIJO en pantalla (que solo desaparecía
en la siguiente interacción) — ahora las confirmaciones simples de
guardar/eliminar/actualizar usan `st.toast()`, que aparece y se desvanece
solo, sin quitarle protagonismo al resto de la pantalla.

Se comprobó primero, de forma aislada (no aquí, ver notas de la ronda), que
`st.toast()` llamado justo antes de `st.rerun()` SOBREVIVE ese rerun
(comportamiento documentado de Streamlit — el toast se conserva un rerun
para permitir justo este patrón "guardar -> aviso -> refrescar pantalla").

Deliberadamente se dejaron como `st.success`/`st.warning` PERSISTENTES (no
toast) los mensajes que son resúmenes de una operación por lotes con
información que conviene poder leer con calma (qué se generó, qué falló,
a dónde ir después) — ver `MENSAJES_QUE_DEBEN_SEGUIR_PERSISTENTES`.

Dos niveles de test:
- `TestMensajesConvertidosATooast`: comprobación estática de que una
  muestra representativa de confirmaciones de guardado usa `st.toast(`
  (no `st.success`/`st.warning`/`st.error`) — detecta una reversión
  accidental.
- `TestMensajesQueSiguenSiendoPersistentes`: lo contrario, para los
  resúmenes de lote que se dejaron a propósito sin convertir.
- `TestToastSuenaDeVerdad`: comportamiento real con AppTest — confirma que
  un guardado concreto deja un toast en cola (y que sobrevive al rerun
  disparado por el propio botón).
"""
import os
import re
import sys
import tempfile

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(__file__))
APP_PATH = os.path.join(os.path.dirname(__file__), "app.py")


def _login_como(at, email, password):
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    return at


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


@pytest.fixture(scope="module")
def codigo():
    with open(APP_PATH, encoding="utf-8") as f:
        return f.read()


class TestMensajesConvertidosAToast:
    """Confirmaciones simples de guardar/eliminar/actualizar — deben usar
    st.toast(), no un st.success/st.warning/st.error fijo en pantalla."""

    MENSAJES = [
        "Paleta personalizada guardada.",
        "Credenciales guardadas.",
        "Clave guardada.",
        "Límite diario guardado.",
        "Cuenta creada para {email_nueva}.",
        "Contraseña reseteada. Compártesela a esa persona.",
        "Cuenta eliminada.",
        "Guardado como borrador (#{post_id}).",
        "¡Publicado en LinkedIn! 🎉",
        "Generado como borrador (post #{resultado.get('post_id')}).",
        "Configuración de automatización guardada.",
        "Inspiración añadida.",
        "Nombre actualizado.",
        "Contraseña actualizada.",
        "Foto de perfil actualizada.",
        "Parámetros guardados.",
        "borrador(es) eliminado(s).",
        "Borrador descartado.",
        "Token refrescado.",
        "Temática añadida.",
    ]

    @pytest.mark.parametrize("mensaje", MENSAJES)
    def test_mensaje_usa_st_toast(self, codigo, mensaje):
        fragmento = re.escape(mensaje.split("{")[0])
        m = re.search(rf'st\.(toast|success|warning|error)\([^\n]*{fragmento}', codigo)
        assert m, f"No se encontró ninguna llamada st.* con el mensaje '{mensaje}' — ¿cambió el texto?"
        assert m.group(1) == "toast", (
            f"'{mensaje}' se muestra con st.{m.group(1)}(...), no con st.toast(...) — se esperaba que "
            "esta confirmación de guardado fuera un toast subtil (V5.4)."
        )


class TestMensajesQueSiguenSiendoPersistentes:
    """Resúmenes de operaciones por lotes: se dejaron a propósito como
    st.success (no toast) porque llevan información que conviene poder
    leer con calma, no que se desvanezca a los 4 segundos."""

    MENSAJES = [
        "Reparto diario guardado.",
        "¡Todo el plan de hoy generado como borrador! Revísalo en 🗂️ Historial.",
        "¡Tanda generada! Revísala en 🗂️ Historial.",
    ]

    @pytest.mark.parametrize("mensaje", MENSAJES)
    def test_mensaje_sigue_siendo_st_success(self, codigo, mensaje):
        fragmento = re.escape(mensaje.split("{")[0])
        m = re.search(rf'st\.(toast|success|warning|error)\([^\n]*{fragmento}', codigo)
        assert m, f"No se encontró ninguna llamada st.* con el mensaje '{mensaje}' — ¿cambió el texto?"
        assert m.group(1) == "success", (
            f"'{mensaje}' pasó a st.{m.group(1)}(...) — este resumen de lote se dejó deliberadamente "
            "persistente (no toast) para que se pueda leer con calma qué pasó y a dónde ir después."
        )


class TestToastSuenaDeVerdad:
    def test_guardar_nombre_deja_un_toast_en_cola_tras_el_rerun(self, dbtmp):
        import config

        h, s = config.hash_password("ClaveAdmin123")
        dbtmp.crear_cuenta("toast@test.com", h, s, rol="admin", nombre="Antes")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "toast@test.com", "ClaveAdmin123")
        assert not at.exception

        # Ir a ⚙️ Configuración (mismo patrón que el resto de la suite: el
        # control de Navegación es siempre el primer segmented_control de la página).
        at.segmented_control[0].set_value("⚙️ Configuración").run()
        assert not at.exception

        campo_nombre = next(ti for ti in at.text_input if ti.label == "Tu nombre")
        campo_nombre.set_value("Después")

        boton = next(b for b in at.button if b.label == "💾 Guardar nombre")
        boton.click().run()
        assert not at.exception

        assert any("Nombre actualizado" in (t.value or "") for t in at.toast), (
            "Tras guardar el nombre no quedó ningún st.toast() en cola — el toast no sobrevivió al "
            "st.rerun() disparado por el propio botón de guardar."
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
