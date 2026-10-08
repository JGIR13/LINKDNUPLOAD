"""
Regresión — auditoría de refresco tras guardar (#52).

Motivo (pedido explícito del usuario): "cuando se hagan modificaciones en
el sistema y esa configuración anterior sale en algún apartado debe
actualizarse el dato" — varias acciones de guardado escribían en la base
de datos pero NO llamaban a `st.rerun()` después, así que lo que ya se
había renderizado en ESE MISMO run (p. ej. los contadores "Publicados" /
"Borradores" de la barra lateral, que se calculan ANTES del contenido de
cada página) se quedaba mostrando el dato viejo hasta la siguiente
interacción del usuario.

Encontrados y corregidos en esta ronda (todos en app.py):
- "💾 Guardar configuración" (página ⚙️ Configuración) — el más directo
  con la queja del usuario: guardaba los parámetros pero no refrescaba.
- "💾 Guardar como borrador" y "📤 Publicar en LinkedIn" (página 🚀 Generar)
  — dejaban desactualizados los contadores de la barra lateral.
- "Cambiar contraseña" (⚙️ Configuración, cuenta propia) y "Resetear
  contraseña" (🛠️ Administración, otra cuenta) — dejaban el formulario con
  la contraseña ya tecleada visible en pantalla en vez de limpiarlo.

Dos niveles de test:
- `TestRerunSiguIendoAlExito`: comprobación estática (sin navegador ni
  AppTest) de que cada `st.success(...)` de estos handlers va seguido de
  `st.rerun()` en las líneas inmediatamente posteriores — detecta una
  reversión accidental de cualquiera de los 5 arreglos sin depender del
  comportamiento (a veces difícil de reproducir con AppTest) de cada uno.
- `TestContadoresBarraLateralSeActualizanEnElActo`: end-to-end con
  streamlit.testing.v1.AppTest, reproduce el caso más claro (el contador
  "Borradores" de la barra lateral tras "💾 Guardar como borrador") como
  prueba de comportamiento real, no solo de forma del código.
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


class TestRerunSigueAlExito:
    """Cada uno de estos 5 mensajes de éxito debe ir seguido de
    `st.rerun()` a menos de 3 líneas de distancia — si alguien lo quita,
    esta prueba falla antes de llegar a producción."""

    MENSAJES = [
        "Parámetros guardados.",
        "Guardado como borrador (#{post_id}).",
        "¡Publicado en LinkedIn! 🎉",
        "Contraseña actualizada.",
        "Contraseña reseteada. Compártesela a esa persona.",
    ]

    @staticmethod
    @pytest.fixture(scope="class")
    def codigo():
        with open(os.path.join(os.path.dirname(__file__), "app.py"), encoding="utf-8") as f:
            return f.readlines()

    @pytest.mark.parametrize("mensaje", MENSAJES)
    def test_mensaje_va_seguido_de_rerun(self, codigo, mensaje):
        fragmento_buscado = re.escape(mensaje.split("{")[0])  # recorta el f-string si lo tiene
        for i, linea in enumerate(codigo):
            if fragmento_buscado and re.search(fragmento_buscado, linea):
                # Ventana generosa: algunos handlers limpian varias claves de
                # session_state (en un bucle de varias líneas) entre el
                # mensaje de éxito y el st.rerun() final.
                siguientes = "".join(codigo[i + 1:i + 10])
                assert "st.rerun()" in siguientes, (
                    f"'{mensaje}' (línea {i + 1}) ya no va seguido de st.rerun() en las "
                    "siguientes líneas — la pantalla se quedará con datos desactualizados "
                    "tras esta acción de guardado (#52)."
                )
                return
        pytest.fail(f"No se encontró el mensaje '{mensaje}' en app.py — ¿cambió el texto?")


class TestContadoresBarraLateralSeActualizanEnElActo:
    def test_guardar_como_borrador_actualiza_el_contador_al_instante(self, dbtmp):
        import config

        h, s = config.hash_password("ClaveAdmin123")
        dbtmp.crear_cuenta("refresco@test.com", h, s, rol="admin", nombre="Admin")

        at = AppTest.from_file(APP_PATH)
        at.run()
        _login_como(at, "refresco@test.com", "ClaveAdmin123")
        assert not at.exception

        metrica_borradores = next(m for m in at.metric if m.label == "Borradores")
        assert int(metrica_borradores.value) == 0

        # Simula que ya se generaron variantes (sin llamar a la IA real) —
        # es lo que deja visible el botón "💾 Guardar como borrador".
        at.session_state["variantes"] = ["Texto de prueba para el borrador."]
        at.session_state["tema_actual"] = "Tema de prueba"
        at.session_state["ronda"] = 0
        at.session_state["variante_idx"] = 0
        at.run()
        assert not at.exception

        boton_guardar = next(b for b in at.button if b.label == "💾 Guardar como borrador")
        boton_guardar.click().run()
        assert not at.exception

        # Sin el fix (#52), este contador se quedaba en 0 hasta la siguiente
        # interacción del usuario, porque la barra lateral ya se había
        # renderizado ANTES de que este mismo run creara el borrador.
        metrica_borradores_tras = next(m for m in at.metric if m.label == "Borradores")
        assert int(metrica_borradores_tras.value) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
