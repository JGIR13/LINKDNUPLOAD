"""
Regresión — bug del botón flotante de la barra lateral al colapsar (#53).

Motivo: "Cuando se cierra la barra horizontal izquierda se queda el boton
flotando donde se despliega no donde se guarda." Causa raíz confirmada
comparando contra un Streamlit sin CSS propio: nuestra regla de ancho fijo
(`[data-testid="stSidebar"] { width: 300px !important; ... }`, añadida para
impedir el redimensionado arrastrando el borde) se aplicaba SIEMPRE, incluso
con la barra colapsada — y como Streamlit colapsa la barra a 0px con su
propia regla !important (misma especificidad, pero la nuestra se inyecta
después y gana), nuestra regla ganaba el pulso y la barra se quedaba
visualmente a los 300px de siempre. El botón de "expandir" vive en flujo
normal justo a la derecha de la barra (no tiene posición fija/absoluta), así
que terminaba flotando a mitad de la pantalla en vez de pegado al borde
izquierdo.

Arreglo: las reglas de ancho fijo y de bloqueo del arrastre ahora solo
aplican con `[aria-expanded="true"]`, dejando que la regla nativa de
Streamlit colapse la barra a 0px sin competencia cuando está cerrada.

Dos niveles de test:
- `TestReglaCSSEscopeada`: comprobación estática y rápida (sin navegador)
  de que la regla sigue escopeada — detecta una reversión accidental del
  fix sin depender de que Playwright/Chromium estén instalados (no lo
  están en el requirements.txt de la app, así que en la instalación real
  del usuario esta suite se salta la parte de navegador y solo corre esta
  comprobación estática).
- `TestColapsoRealEnNavegador`: end-to-end con Playwright, solo si está
  disponible — reproduce exactamente el bug (o su ausencia) contra la app
  real corriendo en un puerto de prueba.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time

import pytest

BASE_DIR = os.path.dirname(__file__)
CSS_PATH = os.path.join(BASE_DIR, "static", "css", "base.css")


class TestReglaCSSEscopeada:
    def test_ancho_fijo_solo_aplica_con_barra_expandida(self):
        css = open(CSS_PATH, encoding="utf-8").read()
        # La regla de ancho fijo (300px !important) debe estar condicionada
        # a [aria-expanded="true"] — si alguien la revierte a la versión sin
        # escopear, esta comprobación falla antes de llegar a producción.
        assert '[data-testid="stSidebar"][aria-expanded="true"] {' in css, (
            "La regla de ancho fijo de la barra lateral debe estar escopeada "
            "a [aria-expanded=\"true\"]; sin el filtro, bloquea el colapso "
            "real de la barra (bug #53)."
        )
        # Confirma que NO existe la versión antigua sin escopear (que
        # aplicaría siempre, colapsada o no).
        assert not re.search(
            r'\[data-testid="stSidebar"\]\s*\{\s*\n\s*width:\s*300px\s*!important;',
            css,
        ), "La regla de ancho fijo sin escopear a aria-expanded ha vuelto — reintroduce el bug #53."

    def test_bloqueo_de_arrastre_tambien_escopeado(self):
        css = open(CSS_PATH, encoding="utf-8").read()
        assert '[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarResizeHandle"]' in css

    def test_franja_superior_usa_el_fondo_del_tema(self):
        """Con la barra colapsada (por defecto en móvil), el botón de
        expandir vive sobre `[data-testid="stHeader"]`, que Streamlit
        pinta con SU fondo claro por defecto sin importar el tema activo.
        En claro casi no se notaba (queda parecido a --bg), pero en oscuro
        se veía una franja clara a todo lo ancho, arriba del todo (#54)."""
        css = open(CSS_PATH, encoding="utf-8").read()
        assert re.search(r'\[data-testid="stHeader"\]\s*\{[^}]*background:\s*var\(--bg\)', css), (
            'Falta `[data-testid="stHeader"] { background: var(--bg) ... }` — sin ella, '
            "el tema oscuro vuelve a mostrar una franja clara arriba del todo (bug #54)."
        )


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
class TestColapsoRealEnNavegador:
    """Levanta la app real (streamlit run) en un puerto de prueba y verifica
    con un navegador de verdad que colapsar la barra lateral funciona —
    esto es lo único que puede detectar un bug puramente de CSS/layout,
    ya que streamlit.testing.v1.AppTest no renderiza CSS real."""

    @staticmethod
    @pytest.fixture(scope="class")
    def app_url(tmp_path_factory):
        # Se copia el proyecto entero a una carpeta temporal y se arranca
        # streamlit desde ahí para no tocar el código real. Desde la V5.4,
        # DB_PATH ya NO vive dentro del proyecto por defecto (se guarda en
        # la carpeta de datos de la instalación real, para sobrevivir a
        # reinstalaciones — ver config.py), así que copiar el proyecto ya
        # no basta para aislar los datos: hay que forzar explícitamente una
        # carpeta de datos vacía y propia de este test con la variable de
        # entorno LINKEDIN_AI_POSTER_DATOS (para no arrancar con cuentas ya
        # creadas de otra ejecución, ni tocar los datos reales del usuario).
        puerto = _puerto_libre()
        copia_dir = tmp_path_factory.mktemp("sidebar_css_app") / "app"
        datos_dir = tmp_path_factory.mktemp("sidebar_css_datos")
        shutil.copytree(
            BASE_DIR, copia_dir,
            ignore=shutil.ignore_patterns(
                "app.db", "logs", "__pycache__", ".pytest_cache", "*.pyc"
            ),
        )
        # El proyecto lee las credenciales del .env si existe; una copia sin
        # .env real arranca igual (pantalla de login), que es todo lo que
        # este test necesita.
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

    def test_colapsar_libera_el_espacio_y_el_boton_queda_a_la_izquierda(self, app_url):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(app_url)
            page.wait_for_timeout(2000)

            # Primera vez: crear la cuenta de administrador.
            if page.locator('input[aria-label="Tu nombre"]').count() > 0:
                page.locator('input[aria-label="Tu nombre"]').fill("Test")
                page.locator('input[aria-label="Tu email (será tu usuario para entrar)"]').fill("t@t.com")
                page.locator('input[aria-label="Contraseña"]').fill("ClaveTest123")
                page.locator('input[aria-label="Repite la contraseña"]').fill("ClaveTest123")
                page.get_by_role("button", name="Crear cuenta de administrador").click()
                page.wait_for_timeout(2500)

            main_antes = page.evaluate(
                """() => document.querySelector('[data-testid="stMain"]').getBoundingClientRect().x"""
            )
            assert main_antes == 300  # barra expandida ocupa 300px fijos

            page.evaluate(
                """() => document.querySelector('[data-testid="stSidebarCollapseButton"] button').click()"""
            )
            page.wait_for_timeout(1500)

            main_despues = page.evaluate(
                """() => document.querySelector('[data-testid="stMain"]').getBoundingClientRect().x"""
            )
            boton_expandir = page.evaluate(
                """() => {
                    const b = document.querySelector('[data-testid="stExpandSidebarButton"]');
                    return b ? b.getBoundingClientRect().x : null;
                }"""
            )

            # El contenido principal debe reclamar casi todo el ancho (no
            # quedarse a x=300 como si la barra siguiera expandida), y el
            # botón de expandir debe quedar pegado al borde izquierdo, no
            # flotando a mitad de la pantalla.
            assert main_despues is not None and main_despues < 20, (
                f"El contenido principal no reclamó el espacio de la barra colapsada "
                f"(x={main_despues}) — el bug #53 ha vuelto."
            )
            assert boton_expandir is not None and boton_expandir < 40, (
                f"El botón de expandir quedó flotando lejos del borde izquierdo "
                f"(x={boton_expandir}) — el bug #53 ha vuelto."
            )

            browser.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
