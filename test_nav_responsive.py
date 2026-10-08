"""
Regresión — barra de Navegación desigual al envolver en varias filas (#54).

Motivo: con 7 opciones (8 para un admin) la barra de Navegación no cabe en
una sola fila y envuelve — por defecto (flex normal, igual que el resto de
`st.segmented_control` de la app) cada fila se estira para rellenar el
ancho disponible, así que la última fila (con menos botones) queda con
esos botones mucho más anchos que los de arriba: en escritorio, "LinkedIn"
y "🛠️ Administración" solos en la fila 2, estirados a la mitad del ancho
cada uno; en móvil, hasta 4 filas de 1-2 botones cada vez más anchos.

Arreglo: la barra de Navegación (identificada por su propio aria-label,
"Navegación" — el label del widget — para no afectar a los demás
segmented_control de la app, que sí deben seguir estirándose al tener
solo 2-3 opciones) pasa a usar CSS grid con columnas de ancho fijo
(`repeat(auto-fill, minmax(...))`): todas las filas usan el mismo número
de columnas del mismo ancho, y una fila incompleta deja hueco en vez de
estirar sus botones.

Dos niveles de test, mismo patrón que test_sidebar_css.py:
- `TestReglaCSSEscopeada`: comprobación estática y rápida (sin navegador).
- `TestFilaIncompletaNoSeEstira`: end-to-end con Playwright, solo si está
  disponible — reproduce el caso real (7 opciones en un ancho que solo
  deja 2 completas en la última fila) y comprueba que el botón solitario
  no se estira para rellenar el ancho de su fila.
"""
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

BASE_DIR = os.path.dirname(__file__)
CSS_PATH = os.path.join(BASE_DIR, "static", "css", "base.css")


class TestReglaCSSEscopeada:
    def test_grid_escopeado_al_aria_label_de_navegacion(self):
        css = open(CSS_PATH, encoding="utf-8").read()
        assert '[role="radiogroup"][aria-label="Navegación"]' in css, (
            "La regla de grid de la barra de Navegación debe seguir escopeada a su "
            "propio aria-label, para no afectar a los demás segmented_control de la "
            "app (bug #54)."
        )
        assert "display: grid !important;" in css

    def test_otros_segmented_control_siguen_con_flex_normal(self):
        """La regla general (compartida por Tema, Modo de generación, Formato...)
        no debe convertirse en grid — solo la de Navegación, más abajo, la
        sobreescribe para su propio aria-label."""
        css = open(CSS_PATH, encoding="utf-8").read()
        seccion_general = css.split('/* ---------- Segmented control')[1].split(
            '[role="radiogroup"][aria-label="Navegación"]'
        )[0]
        assert "display: grid" not in seccion_general


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium_disponible() -> bool:
    return os.path.exists("/opt/pw-browsers/chromium") or os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")


playwright = pytest.importorskip(
    "playwright.sync_api", reason="Playwright no está instalado — se salta el test end-to-end de navegador."
)


@pytest.mark.skipif(not _chromium_disponible(), reason="Chromium no disponible en esta máquina.")
class TestFilaIncompletaNoSeEstira:
    @staticmethod
    @pytest.fixture(scope="class")
    def app_url(tmp_path_factory):
        # Ver el comentario equivalente en test_sidebar_css.py: desde la
        # V5.4, DB_PATH ya no vive dentro del proyecto por defecto, así que
        # hay que forzar una carpeta de datos propia y vacía para este test.
        puerto = _puerto_libre()
        copia_dir = tmp_path_factory.mktemp("nav_css_app") / "app"
        datos_dir = tmp_path_factory.mktemp("nav_css_datos")
        shutil.copytree(
            BASE_DIR, copia_dir,
            ignore=shutil.ignore_patterns(
                "app.db", "logs", "__pycache__", ".pytest_cache", "*.pyc"
            ),
        )
        env = {**os.environ, "LINKEDIN_AI_POSTER_DATOS": str(datos_dir)}
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", os.path.join(copia_dir, "app.py"),
                "--server.headless", "true", "--server.port", str(puerto),
            ],
            cwd=copia_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        url = f"http://localhost:{puerto}"
        try:
            for _ in range(40):
                try:
                    with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.5)
            time.sleep(2)
            yield url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_boton_solitario_de_la_ultima_fila_no_se_estira(self, app_url):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            # Ancho elegido para que la barra (7-8 opciones) envuelva dejando
            # una última fila con un solo botón — el caso que se rompía.
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(app_url)
            page.wait_for_timeout(2000)

            if page.locator('input[aria-label="Tu nombre"]').count() > 0:
                page.locator('input[aria-label="Tu nombre"]').fill("Test")
                page.locator('input[aria-label="Tu email (será tu usuario para entrar)"]').fill("t@t.com")
                page.locator('input[aria-label="Contraseña"]').fill("ClaveTest123")
                page.locator('input[aria-label="Repite la contraseña"]').fill("ClaveTest123")
                page.get_by_role("button", name="Crear cuenta de administrador").click()
                page.wait_for_timeout(2500)

            anchos = page.evaluate(
                """() => {
                    const nav = document.querySelector('[role="radiogroup"][aria-label="Navegación"]');
                    const botones = [...nav.querySelectorAll('button')];
                    return botones.map(b => Math.round(b.getBoundingClientRect().width));
                }"""
            )
            assert len(anchos) >= 6, f"Se esperaban al menos 6 opciones de navegación, hay {len(anchos)}."

            # Todos los botones deben compartir (aprox.) el mismo ancho de
            # columna — incluido el último si su fila queda incompleta.
            # Sin el fix, el último botón de una fila incompleta se estira
            # y puede llegar a doblar el ancho de los demás.
            ancho_min, ancho_max = min(anchos), max(anchos)
            assert ancho_max <= ancho_min * 1.4, (
                f"Los anchos de los botones de Navegación no son uniformes ({anchos}) — "
                "una fila incompleta se está estirando otra vez (bug #54)."
            )

            browser.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
