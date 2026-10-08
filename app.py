"""
UI local con Streamlit — V5 del proyecto (multiusuario real).

Páginas (una vez autenticado):
- Generar Post (texto + imagen, revisión/edición, vista previa estilo LinkedIn, publicación)
- Generación diaria (reparto fijo, temáticas rotativas, Automatización Total)
- Inspiración (ejemplos de texto e imagen, few-shot, con análisis de estilo por IA)
- Configuración (perfil por defecto, mi cuenta)
- Historial
- Conectar LinkedIn (OAuth, nunca pide usuario/contraseña de LinkedIn)
- Administración (solo cuentas con rol='admin'): credenciales de la instalación + gestión de cuentas

Cada persona tiene su propia cuenta (email + contraseña) — ver db.py, tabla
`cuentas`. Todo lo que genera y publica queda scoped a su cuenta_id; las
credenciales de la instalación (app de LinkedIn Developer, clave de Gemini)
son globales y las gestiona quien tenga rol de administrador.
"""

import base64
import html as html_lib
import mimetypes
import os
import re
import sqlite3
import sys
import traceback
import uuid
from datetime import datetime, timedelta

import streamlit as st

import config
import daily
import db
import image_infografia
import linkedin_oauth
import linkedin_publish
import llm

LOGO_PATH = os.path.join(config.STATIC_DIR, "img", "lp-logo-png_seeklogo-85938.png")


def _icono_pagina():
    """Favicon de la pestaña del navegador: el logo real de la app si está
    disponible, con el emoji de siempre como respaldo — una instalación a
    la que le falte el archivo (o una copia parcial) nunca debe impedir
    que la app arranque por esto."""
    try:
        from PIL import Image
        return Image.open(LOGO_PATH)
    except Exception:
        return "💼"


st.set_page_config(page_title="LinkedIn Poster", page_icon=_icono_pagina(), layout="centered")
db.init_db()

# El tema (☀️ claro / 🌙 oscuro) se decide aquí, ANTES de inyectar el CSS y el
# banner. Antes de iniciar sesión no hay ninguna cuenta de la que leer una
# preferencia guardada, así que se usa "claro" — en cuanto se establece la
# sesión (más abajo) se sincroniza con la preferencia real de esa cuenta.
st.session_state.setdefault("tema_ui", "claro")

# =============================================================================
# Estilos — dos temas completos, solo el interfaz de la app (nunca las
# paletas de la infografía, que cada persona elige por separado). Streamlit
# no soporta dos temas a la vez vía config.toml, así que esto se inyecta
# como CSS propio sobre el tema base (config.toml queda en modo claro como
# red de seguridad si el CSS no carga).
#
# El CSS y el HTML de las piezas de marca (banner, tarjetas...) viven en
# archivos de verdad bajo static/css/ y static/html/ (no en f-strings de
# Python), para que se pueda editar el aspecto de la app sin tocar código
# Python. Se leen del disco en cada ejecución del script, así que un cambio
# guardado en cualquiera de esos archivos se aplica en la siguiente
# interacción con la app (clic, recarga...), sin reiniciar el servidor.
# =============================================================================

CSS_DIR = os.path.join(config.STATIC_DIR, "css")
HTML_DIR = os.path.join(config.STATIC_DIR, "html")


def _leer_css(nombre: str) -> str:
    ruta = os.path.join(CSS_DIR, nombre)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return f"/* no se pudo leer {nombre} */"


def _leer_html(nombre_archivo: str) -> str:
    """Lee una plantilla HTML de static/html/. Igual que _leer_css, se lee
    del disco en cada llamada (no se cachea), así que un cambio en el
    archivo se ve solo con recargar la página — sin tocar Python."""
    ruta = os.path.join(HTML_DIR, nombre_archivo)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return f"<!-- no se pudo leer {nombre_archivo} -->"


def _render_html(nombre_archivo: str, **valores: str) -> str:
    """Rellena los huecos `{{clave}}` de una plantilla HTML con los valores
    dados (ya deben venir escapados por el llamador si contienen texto del
    usuario). No usa str.format() a propósito: así el HTML de la plantilla
    puede tener llaves normales (estilos, JSON de ejemplo...) sin que
    rompan el reemplazo. El parámetro del archivo se llama distinto a
    cualquier clave de plantilla real para que nunca choquen entre sí."""
    contenido = _leer_html(nombre_archivo)
    for clave, valor in valores.items():
        contenido = contenido.replace("{{" + clave + "}}", valor)
    return contenido


def _logo_html(alt: str, css_class: str) -> str:
    """`<img>` del logo embebido en base64 (funciona igual con
    `enableStaticServing = false` — no depende de que Streamlit sirva
    static/ por HTTP), con el emoji 💼 de siempre como respaldo si el
    archivo no está disponible. Usado en la cabecera de la barra lateral y
    en el banner de bienvenida."""
    try:
        with open(LOGO_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f'<img class="{css_class}" src="data:image/png;base64,{b64}" alt="{alt}">'
    except OSError:
        return "💼"


def _inject_css(tema: str):
    archivo_tema = "theme_oscuro.css" if tema == "oscuro" else "theme_claro.css"
    css = _leer_css(archivo_tema) + "\n" + _leer_css("base.css")
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)


_inject_css(st.session_state.tema_ui)

# =============================================================================
# Helpers de presentación
# =============================================================================

def _texto_a_html_linkedin(texto: str) -> str:
    escapado = html_lib.escape(texto or "")
    con_hashtags = re.sub(r"#(\w+)", r'<span class="li-hashtag">#\1</span>', escapado)
    return con_hashtags.replace("\n", "<br>")


def _imagen_a_data_uri(path) -> str | None:
    if not path or not os.path.exists(path):
        return None
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def render_preview_linkedin(nombre: str, headline: str, texto: str, imagen_path=None):
    iniciales = "".join(p[0].upper() for p in (nombre or "Tu Nombre").split()[:2]) or "TU"
    img_uri = _imagen_a_data_uri(imagen_path)
    img_html = f'<img src="{img_uri}" class="li-preview-img" />' if img_uri else ""
    st.markdown(
        _render_html(
            "li_preview.html",
            iniciales=html_lib.escape(iniciales),
            nombre=html_lib.escape(nombre or "Tu nombre"),
            headline=html_lib.escape(headline or ""),
            texto_html=_texto_a_html_linkedin(texto),
            img_html=img_html,
        ),
        unsafe_allow_html=True,
    )


def _guardar_imagen_subida(uploaded_file) -> str:
    ext = os.path.splitext(uploaded_file.name)[1].lower() or ".png"
    nombre = f"insp_{uuid.uuid4().hex[:10]}{ext}"
    ruta = os.path.join(config.INSPIRACION_IMG_DIR, nombre)
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return ruta


def _guardar_foto_perfil(uploaded_file) -> str:
    ext = os.path.splitext(uploaded_file.name)[1].lower() or ".png"
    nombre = f"perfil_{uuid.uuid4().hex[:10]}{ext}"
    ruta = os.path.join(config.PERFIL_IMG_DIR, nombre)
    with open(ruta, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return ruta


def _reportar_error(prefijo: str, e: Exception):
    """Muestra el error en la interfaz Y ADEMÁS imprime el traceback completo
    en la consola (la ventana/terminal donde corre `streamlit run app.py`),
    para poder diagnosticar un fallo sin depender de una captura de pantalla
    del mensaje resumido que se ve en la web.

    Caso especial: cuando Gemini se queda sin cuota gratuita
    (`llm.CuotaGeminiAgotada`), el mensaje ya es humano y claro por sí
    mismo — se muestra como aviso (⏳), no como un error rojo con el JSON
    crudo de la API detrás, que no aporta nada a quien usa la app."""
    if isinstance(e, llm.CuotaGeminiAgotada):
        st.warning(f"⏳ {e}")
    else:
        st.error(f"{prefijo}: {e}")
    print(f"\n{'=' * 70}\n[LinkedIn Poster] {prefijo}\n{'=' * 70}", file=sys.stderr)
    traceback.print_exc()
    print("=" * 70 + "\n", file=sys.stderr)


def _opciones_paleta(cuenta_id: int) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Construye las opciones de un selector de paleta de infografía: las
    predefinidas (config.INFOGRAFIA_PALETAS, etiqueta = su propio nombre) +
    las personalizadas de esta cuenta (etiqueta con 🎨, valor 'custom:<id>'
    — ver db.resolver_paleta_infografia). Devuelve (etiquetas,
    etiqueta_a_valor, valor_a_etiqueta) para no repetir esta construcción
    en cada sitio donde se elige paleta (asistente, modo rápido,
    configuración, subida masiva)."""
    etiquetas = list(config.INFOGRAFIA_PALETAS.keys())
    etiqueta_a_valor = {n: n for n in etiquetas}
    for pp in db.listar_paletas_personalizadas(cuenta_id):
        etiqueta = f"🎨 {pp['nombre']} (personalizada)"
        etiquetas.append(etiqueta)
        etiqueta_a_valor[etiqueta] = db.valor_selector_paleta(pp["id"])
    valor_a_etiqueta = {v: k for k, v in etiqueta_a_valor.items()}
    return etiquetas, etiqueta_a_valor, valor_a_etiqueta


def _etiqueta_paleta(cuenta_id: int, valor: str | None) -> str:
    """Nombre legible de un valor de paleta guardado ('Azul corporativo', o
    'custom:7' -> '🎨 Nombre (personalizada)') — para mostrar en resúmenes
    sin exponer el valor técnico interno."""
    if valor and valor.startswith("custom:"):
        try:
            paleta_id = int(valor.split(":", 1)[1])
        except ValueError:
            paleta_id = None
        fila = db.obtener_paleta_personalizada(paleta_id) if paleta_id else None
        if fila and fila["cuenta_id"] == cuenta_id:
            return f"🎨 {fila['nombre']} (personalizada)"
        return config.INFOGRAFIA_PALETA_DEFECTO
    return valor or config.INFOGRAFIA_PALETA_DEFECTO


def _swatch_html(colores: dict, tam_px: int = 15) -> str:
    """HTML de una fila de círculos de color para las claves con hueco
    visual (primario/acento/fondo/tarjeta) presentes en `colores` — bloque
    puramente decorativo (sin widgets), seguro de usar dentro de un
    st.form."""
    puntos = "".join(
        f'<span style="display:inline-block;width:{tam_px}px;height:{tam_px}px;border-radius:50%;'
        f'background:{colores[k]};margin-right:4px;border:1px solid rgba(0,0,0,.18);vertical-align:middle"></span>'
        for k in ("primario", "acento", "fondo", "tarjeta") if colores.get(k)
    )
    return f'<span style="white-space:nowrap">{puntos}</span>'


def _render_galeria_paletas(cuenta_id: int):
    """Cuadrícula informativa con los colores de cada paleta disponible
    (predefinidas + personalizadas de esta cuenta) — para que se vea de un
    vistazo qué colores usa cada preset antes de elegirlo. Puramente
    visual, sin ningún widget interactivo."""
    entradas = [(nombre, colores) for nombre, colores in config.INFOGRAFIA_PALETAS.items()]
    personalizadas = db.listar_paletas_personalizadas(cuenta_id)
    entradas += [
        (f"🎨 {pp['nombre']}", {"primario": pp["primario"], "acento": pp["acento"]}) for pp in personalizadas
    ]
    columnas = st.columns(3)
    for i, (nombre, colores) in enumerate(entradas):
        with columnas[i % 3]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:0.85rem">'
                f'{_swatch_html(colores)}<span>{html_lib.escape(nombre)}</span></div>',
                unsafe_allow_html=True,
            )


def _gestor_paletas_personalizadas(cuenta_id: int, key_prefix: str):
    """UI para crear/eliminar paletas personalizadas de esta cuenta (dos
    selectores de color + nombre + guardar). Debe usarse SIEMPRE fuera de
    un st.form (necesita su propio botón con rerun inmediato, algo que un
    formulario no permite hasta que se envía por completo)."""
    personalizadas = db.listar_paletas_personalizadas(cuenta_id)
    if personalizadas:
        for pp in personalizadas:
            cpp1, cpp2 = st.columns([5, 1])
            cpp1.markdown(
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'{_swatch_html({"primario": pp["primario"], "acento": pp["acento"]})}'
                f'<span>{html_lib.escape(pp["nombre"])}</span></div>',
                unsafe_allow_html=True,
            )
            if cpp2.button("🗑️", key=f"{key_prefix}_del_paleta_{pp['id']}"):
                db.eliminar_paleta_personalizada(pp["id"])
                st.rerun()

    with st.expander("➕ Crear paleta personalizada"):
        st.caption(
            "Elige solo dos colores (primario y acento) — el resto (fondo, tarjetas, texto...) se calcula "
            "automáticamente para que siempre haya buen contraste, tanto en modo claro como oscuro."
        )
        cnp1, cnp2, cnp3 = st.columns([2, 1, 1])
        nombre_nueva_paleta = cnp1.text_input("Nombre", placeholder="Ej: Colores de mi marca", key=f"{key_prefix}_nombre_paleta")
        color_primario_nuevo = cnp2.color_picker("Primario", value="#0A66C2", key=f"{key_prefix}_color_primario")
        color_acento_nuevo = cnp3.color_picker("Acento", value="#F5B400", key=f"{key_prefix}_color_acento")
        st.markdown(
            _swatch_html({"primario": color_primario_nuevo, "acento": color_acento_nuevo}, tam_px=22),
            unsafe_allow_html=True,
        )
        if st.button("💾 Guardar paleta", key=f"{key_prefix}_guardar_paleta"):
            if nombre_nueva_paleta.strip():
                db.crear_paleta_personalizada(cuenta_id, nombre_nueva_paleta.strip(), color_primario_nuevo, color_acento_nuevo)
                st.toast("Paleta personalizada guardada.", icon="✅")
                st.rerun()
            else:
                st.toast("Ponle un nombre a la paleta antes de guardarla.", icon="⚠️")


def _lanzar_generacion_variantes(
    tema, parametros_texto, inspiracion, overlay_marca, formato_post="infografia", infografia_config=None,
):
    """Punto único de entrada para generar variantes de texto, usado tanto por el
    asistente completo como por el modo rápido. Guarda en session_state todo lo
    necesario para el paso siguiente (generar la imagen, si el formato la lleva).

    `formato_post` es "infografia" (imagen compuesta 100% en código — ver
    image_infografia.py) o "texto" (publicación sin ninguna imagen).
    `infografia_config` (dict con "paleta_nombre" y "num_items") solo se usa
    cuando formato_post="infografia"."""
    with st.status("Generando variantes de texto con IA...", expanded=False) as status:
        try:
            variantes = llm.generar_variantes_texto(tema, parametros_texto, inspiracion)
            st.session_state.variantes = variantes
            st.session_state.tema_actual = tema
            st.session_state.inspiracion_relevante = inspiracion
            st.session_state.imagen_path = None
            st.session_state.imagen_proveedor = None
            st.session_state.post_id_actual = None
            st.session_state.variante_idx = 0
            st.session_state.ronda = st.session_state.get("ronda", 0) + 1
            st.session_state.overlay_marca_actual = overlay_marca
            st.session_state.formato_post_actual = formato_post
            st.session_state.infografia_config_actual = infografia_config
            status.update(label="¡Variantes listas!", state="complete")
        except Exception as e:
            status.update(label="Error generando texto", state="error")
            _reportar_error("Error generando variantes de texto", e)


# =============================================================================
# Autenticación — cada persona tiene su propia cuenta (tabla `cuentas`).
# Sin cuentas todavía en la instalación -> primer arranque, se crea la
# cuenta de administrador. Con cuentas ya creadas -> login con email +
# contraseña. La sesión (st.session_state.cuenta_id) dura mientras el
# navegador mantenga la pestaña/sesión de Streamlit abierta — una pestaña
# nueva pide iniciar sesión de nuevo, igual que cualquier app web normal.
# =============================================================================

def _pantalla_login():
    st.markdown(
        _render_html("hero_banner.html", logo_html=_logo_html("LinkedIn Poster", "hero-logo-img")),
        unsafe_allow_html=True,
    )

    error_previo = st.session_state.pop("login_error", None)
    if error_previo:
        st.error(f"No se pudo completar la conexión con LinkedIn: {error_previo}")

    st.markdown("### 👋 Inicia sesión")
    cuentas_existentes = db.listar_cuentas()

    if not cuentas_existentes:
        st.info(
            "Todavía no hay ninguna cuenta en esta instalación. Crea la cuenta de "
            "administrador para empezar — con ella podrás crear después una cuenta para "
            "cada colega que vaya a usar la app, desde el panel administrativo."
        )
        with st.form("form_primera_cuenta"):
            nombre_in = st.text_input("Tu nombre")
            email_in = st.text_input("Tu email (será tu usuario para entrar)")
            col_p1, col_p2 = st.columns(2)
            pw1 = col_p1.text_input("Contraseña", type="password")
            pw2 = col_p2.text_input("Repite la contraseña", type="password")
            crear = st.form_submit_button("Crear cuenta de administrador", type="primary", width="stretch")
        if crear:
            if not email_in.strip() or "@" not in email_in:
                st.error("Introduce un email válido.")
            elif not pw1 or len(pw1) < 6:
                st.error("Usa una contraseña de al menos 6 caracteres.")
            elif pw1 != pw2:
                st.error("Las dos contraseñas no coinciden.")
            elif db.obtener_cuenta_por_email(email_in):
                # Ya existe una cuenta con ese email (p. ej. una doble pulsación
                # del botón, o esta misma cuenta creada en un intento anterior) —
                # nunca se llega a esto en el primer envío real, así que si ocurre
                # es que la cuenta ya está lista para usarse.
                st.error(
                    "Ya existe una cuenta con ese email en esta instalación. "
                    "Recarga la página e inicia sesión con tu contraseña."
                )
            else:
                pw_hash, pw_salt = config.hash_password(pw1)
                try:
                    nueva_id = db.crear_cuenta(email_in, pw_hash, pw_salt, nombre_in, rol="admin")
                except sqlite3.IntegrityError:
                    st.error(
                        "Ya existe una cuenta con ese email en esta instalación. "
                        "Recarga la página e inicia sesión con tu contraseña."
                    )
                else:
                    st.session_state.cuenta_id = nueva_id
                    st.rerun()
    else:
        with st.form("form_login"):
            email_in = st.text_input("Email")
            pw_in = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Iniciar sesión", type="primary", width="stretch")
        if entrar:
            cuenta = db.obtener_cuenta_por_email(email_in)
            if not cuenta or not config.verify_password(pw_in, cuenta["password_hash"], cuenta["password_salt"]):
                st.error("Email o contraseña incorrectos.")
            elif not cuenta.get("activo"):
                st.error("Esta cuenta está desactivada. Contacta con quien administra la instalación.")
            else:
                st.session_state.cuenta_id = cuenta["id"]
                st.rerun()

    st.divider()
    st.caption("¿Eres administrador de esta instalación? [🛠️ Panel administrativo](?admin=1)")


def _pantalla_cambiar_password_obligatorio(cuenta_id: int):
    st.markdown(
        _render_html(
            "page_header.html",
            icono=_logo_html("LinkedIn Poster", "page-header-logo-img"),
            titulo="Cambia tu contraseña",
            descripcion="Por seguridad, hazlo antes de continuar.",
        ),
        unsafe_allow_html=True,
    )
    st.warning("Tu contraseña actual es temporal — elige una nueva para seguir.")
    with st.form("form_cambiar_pw_obligatorio"):
        pw1 = st.text_input("Nueva contraseña", type="password")
        pw2 = st.text_input("Repite la nueva contraseña", type="password")
        cambiar = st.form_submit_button("Cambiar contraseña y continuar", type="primary", width="stretch")
    if cambiar:
        if not pw1 or len(pw1) < 6:
            st.error("Usa al menos 6 caracteres.")
        elif pw1 != pw2:
            st.error("Las dos contraseñas no coinciden.")
        else:
            pw_hash, pw_salt = config.hash_password(pw1)
            db.cambiar_password_cuenta(cuenta_id, pw_hash, pw_salt, debe_cambiar_password=False)
            st.rerun()


# =============================================================================
# Panel de administración — pantalla COMPLETAMENTE APARTE de la app normal,
# nunca una pestaña de su navegación (un usuario normal no debe verla ni
# tener forma de llegar a ella). Se accede por el enlace "Panel
# administrativo" de la pantalla de inicio de sesión, al estilo del acceso
# separado de wp-admin en WordPress — exige loguearse con una cuenta que
# tenga rol='admin'; cualquier otra cuenta (o credenciales incorrectas) se
# rechaza aquí mismo, sin llegar nunca al panel.
# =============================================================================
def _pagina_admin(cuenta_id):
    cfg_global = db.obtener_config_global()
    creds_linkedin = config.get_credentials()

    with st.container(border=True):
        st.markdown("**Credenciales de la app de LinkedIn**")
        st.caption("Compartidas por todas las cuentas de esta instalación.")
        credenciales_listas = bool(creds_linkedin.linkedin_client_id and creds_linkedin.linkedin_client_secret)
        creds_desde_bd = bool(cfg_global.get("linkedin_client_id") and cfg_global.get("linkedin_client_secret"))
        if credenciales_listas:
            origen = "guardadas aquí en la app" if creds_desde_bd else "leídas de tu archivo .env"
            st.badge(f"Configuradas ({origen})", color="green", icon="✅")
        else:
            st.badge("Todavía no configuradas", color="gray", icon="⚪")

        st.markdown(
            _render_html("creds_hint.html", redirect_uri=html_lib.escape(creds_linkedin.linkedin_redirect_uri or "")),
            unsafe_allow_html=True,
        )

        with st.form("form_credenciales_linkedin", border=False):
            col_cid, col_curi = st.columns(2)
            client_id_in = col_cid.text_input(
                "Client ID", value=cfg_global.get("linkedin_client_id") or "", placeholder="86xxxxxxxxxxxx",
            )
            redirect_uri_in = col_curi.text_input(
                "Redirect URI", value=creds_linkedin.linkedin_redirect_uri or "http://localhost:8501",
            )
            client_secret_in = st.text_input(
                "Client Secret", value=cfg_global.get("linkedin_client_secret") or "",
                type="password", placeholder="••••••••••••",
            )
            col_guardar, col_borrar = st.columns(2)
            guardar_creds = col_guardar.form_submit_button("💾 Guardar credenciales", type="primary", width="stretch")
            borrar_creds = col_borrar.form_submit_button("🗑️ Quitar credenciales guardadas", width="stretch")

        if guardar_creds:
            if not client_id_in.strip() or not client_secret_in.strip():
                st.toast("Rellena al menos el Client ID y el Client Secret.", icon="⚠️")
            else:
                db.guardar_credenciales_linkedin_global(client_id_in, client_secret_in, redirect_uri_in)
                st.toast("Credenciales guardadas.", icon="✅")
                st.rerun()
        if borrar_creds:
            db.eliminar_credenciales_linkedin_global()
            st.toast("Credenciales eliminadas (si tienes las variables en tu .env, se seguirán usando esas).", icon="✅")
            st.rerun()

    with st.container(border=True):
        st.markdown("**Clave de API de Gemini (IA)**")
        st.caption(
            "Necesaria para generar texto e infografías. Consíguela gratis en aistudio.google.com/apikey. "
            "Compartida por todas las cuentas."
        )
        gemini_lista = bool(creds_linkedin.gemini_api_key)
        gemini_desde_bd = bool(cfg_global.get("gemini_api_key"))
        if gemini_lista:
            origen_gemini = "guardada aquí en la app" if gemini_desde_bd else "leída de tu archivo .env"
            st.badge(f"Configurada ({origen_gemini})", color="green", icon="✅")
            st.caption(
                f"Huella de la clave activa: `{config.fingerprint_clave_gemini(creds_linkedin.gemini_api_key)}` "
                "— cambia después de guardar una clave distinta, así puedes comprobar que el cambio se aplicó."
            )
        else:
            st.badge("Todavía no configurada", color="gray", icon="⚪")

        with st.form("form_gemini_api_key", border=False):
            gemini_key_in = st.text_input(
                "Clave de API", value=cfg_global.get("gemini_api_key") or "",
                type="password", placeholder="••••••••••••",
            )
            col_guardar_g, col_borrar_g = st.columns(2)
            guardar_gemini = col_guardar_g.form_submit_button("💾 Guardar clave", type="primary", width="stretch")
            borrar_gemini = col_borrar_g.form_submit_button("🗑️ Quitar clave guardada", width="stretch")

        if guardar_gemini:
            if not gemini_key_in.strip():
                st.toast("Introduce una clave antes de guardar.", icon="⚠️")
            else:
                db.guardar_gemini_api_key_global(gemini_key_in)
                st.toast("Clave guardada.", icon="✅")
                st.rerun()
        if borrar_gemini:
            db.eliminar_gemini_api_key_global()
            st.toast("Clave eliminada (si tienes la variable en tu .env, se seguirá usando esa).", icon="✅")
            st.rerun()

        st.divider()
        st.markdown("**📊 Cuota de Gemini — hoy**")
        st.caption(
            "El nivel gratuito de Gemini limita las peticiones por día POR MODELO — así que cuando uno "
            "se agota, la app pasa sola al siguiente de la lista de abajo en vez de bloquearse. Google no "
            "ofrece ninguna forma de consultar el cupo de antemano: el número exacto de cada modelo se "
            "conoce la primera vez que se agota HOY — hasta entonces se muestra una estimación, que puede "
            "quedarse corta si hubo reintentos por límite de peticiones POR MINUTO antes de llegar al tope "
            "diario. Cada infografía gasta 2 llamadas (texto + contenido de la infografía); un post de "
            "solo texto gasta 1."
        )
        with st.expander("¿Cambiar de clave de API me da más cupo?"):
            st.markdown(
                "**No, si la clave nueva es del mismo proyecto de Google Cloud.** El cupo gratuito de "
                "Gemini lo controla Google por *proyecto*, no por clave — varias claves del mismo "
                "proyecto (lo ves en la columna \"Proyecto\" de aistudio.google.com/apikey) comparten "
                "un único cupo diario. Cambiar entre ellas no libera peticiones nuevas.\n\n"
                "Para tener cupo adicional de verdad necesitas una clave de **otro** proyecto de Google "
                "Cloud (o activar facturación en uno existente). Usa la huella de la clave, arriba, para "
                "confirmar que la que has guardado es la que crees que es."
            )
        _estado_cuota_admin = llm.estado_cuota_gemini_hoy()
        for _m in _estado_cuota_admin["modelos"]:
            _pct_m = min(1.0, _m["usados"] / _m["limite"]) if _m["limite"] else 0.0
            if _m["limite_es_real"]:
                _texto_barra_m = f"{_m['usados']}/{_m['limite']}"
            elif _m["usados"] > _m["limite"]:
                # La estimación se quedó corta frente a los intentos reales de
                # hoy (cada intento cuenta, aunque falle por límite POR MINUTO
                # en vez de por cupo diario) — mostrar la fracción tal cual
                # daría un ">100%" que parece un error y no lo es.
                _texto_barra_m = f"{_m['usados']} intentos hoy (estimación de {_m['limite']} superada)"
            else:
                _texto_barra_m = f"{_m['usados']}/{_m['limite']} (estimado)"
            # Fila en dos líneas (nombre+badge arriba, barra abajo a todo el
            # ancho) en vez de tres columnas estrechas — con la clave del
            # límite en texto largo ("(estimación de 20 superada)") una
            # columna angosta para el badge se recortaba con "...".
            _cm1, _cm3 = st.columns([3, 1.6])
            _cm1.markdown(f"`{_m['modelo']}`")
            if _m["agotado"]:
                _cm3.badge("Agotado hoy", color="red", icon="🔴")
            elif _pct_m >= 0.7:
                _cm3.badge("Cerca del límite", color="orange", icon="🟠")
            else:
                _cm3.badge("Disponible", color="green", icon="🟢")
            st.progress(_pct_m, text=_texto_barra_m)
        if _estado_cuota_admin["todos_agotados"]:
            st.warning("⏳ Todos los modelos candidatos están agotados hoy — la generación con IA se reanudará mañana.")

        st.divider()
        st.caption(
            "Límite propio adicional (opcional): frena cada modelo ANTES de que Google devuelva el "
            "429, si prefieres quedarte por debajo del cupo real con margen de seguridad. Se aplica "
            "por modelo, igual que el cupo de Google. Ponlo en 0 para no autolimitarte y dejar que la "
            "app llegue hasta el cupo real de cada modelo."
        )
        limite_actual_g = db.obtener_limite_diario_gemini()
        with st.form("form_limite_gemini", border=False):
            limite_nuevo_g = st.number_input(
                "Límite propio de generaciones/día por modelo (0 = sin límite)",
                min_value=0, max_value=200, value=limite_actual_g, step=1,
            )
            if st.form_submit_button("💾 Guardar límite diario", type="primary", width="stretch"):
                db.guardar_limite_diario_gemini(int(limite_nuevo_g))
                st.toast("Límite diario guardado.", icon="✅")
                st.rerun()

    st.divider()
    st.markdown("**👥 Cuentas de esta instalación**")
    st.caption(
        "Crea una cuenta por cada colega que vaya a usar la app. Comparte con esa persona su "
        "email y la contraseña temporal por el canal que uses habitualmente — se le pedirá "
        "cambiarla la primera vez que inicie sesión."
    )

    with st.expander("➕ Crear cuenta nueva"):
        with st.form("form_crear_cuenta", clear_on_submit=True):
            col_n, col_e = st.columns(2)
            nombre_nueva = col_n.text_input("Nombre")
            email_nueva = col_e.text_input("Email")
            col_r, col_p = st.columns(2)
            rol_nueva = col_r.selectbox("Rol", ["usuario", "admin"])
            pw_nueva = col_p.text_input("Contraseña temporal", type="password")
            crear_cuenta_btn = st.form_submit_button("Crear cuenta", type="primary", width="stretch")
        if crear_cuenta_btn:
            if not email_nueva.strip() or "@" not in email_nueva:
                st.toast("Introduce un email válido.", icon="⚠️")
            elif db.obtener_cuenta_por_email(email_nueva):
                st.toast("Ya existe una cuenta con ese email.", icon="⚠️")
            elif not pw_nueva or len(pw_nueva) < 6:
                st.toast("Usa una contraseña temporal de al menos 6 caracteres.", icon="⚠️")
            else:
                pw_hash, pw_salt = config.hash_password(pw_nueva)
                try:
                    db.crear_cuenta(email_nueva, pw_hash, pw_salt, nombre_nueva, rol=rol_nueva,
                                     debe_cambiar_password=True)
                except sqlite3.IntegrityError:
                    st.toast("Ya existe una cuenta con ese email.", icon="⚠️")
                else:
                    st.toast(f"Cuenta creada para {email_nueva}. Comparte con esa persona su email y contraseña temporal.", icon="✅")
                    st.rerun()

    for cta in db.listar_cuentas():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 2])
            etiqueta_rol = "🛠️ Administrador" if cta["rol"] == "admin" else "👤 Usuario"
            c1.markdown(f"**{html_lib.escape(cta.get('nombre') or cta['email'])}**")
            c1.caption(cta["email"] + f" · {etiqueta_rol}")
            c2.badge("Activa" if cta["activo"] else "Desactivada", color="green" if cta["activo"] else "gray")

            if cta["id"] == cuenta_id:
                c3.caption("Tu propia cuenta — cámbiate la contraseña desde ⚙️ Configuración.")
                continue

            with c3.popover("Gestionar", width="stretch"):
                nuevo_rol = st.selectbox(
                    "Rol", ["usuario", "admin"], index=(0 if cta["rol"] == "usuario" else 1),
                    key=f"rol_{cta['id']}",
                )
                if nuevo_rol != cta["rol"] and st.button("Guardar rol", key=f"guardar_rol_{cta['id']}", width="stretch"):
                    db.actualizar_cuenta(cta["id"], rol=nuevo_rol)
                    st.rerun()

                etiqueta_toggle = "⏸️ Desactivar cuenta" if cta["activo"] else "▶️ Reactivar cuenta"
                if st.button(etiqueta_toggle, key=f"toggle_{cta['id']}", width="stretch"):
                    db.actualizar_cuenta(cta["id"], activo=not cta["activo"])
                    st.rerun()

                st.divider()
                with st.form(f"form_reset_pw_{cta['id']}", border=False):
                    nueva_pw = st.text_input("Nueva contraseña temporal", type="password", key=f"pw_{cta['id']}")
                    resetear = st.form_submit_button("Resetear contraseña", width="stretch")
                if resetear:
                    if not nueva_pw or len(nueva_pw) < 6:
                        st.toast("Usa al menos 6 caracteres.", icon="⚠️")
                    else:
                        pw_hash, pw_salt = config.hash_password(nueva_pw)
                        db.cambiar_password_cuenta(cta["id"], pw_hash, pw_salt, debe_cambiar_password=True)
                        st.toast("Contraseña reseteada. Compártesela a esa persona.", icon="✅")
                        st.rerun()

                st.divider()
                confirmar_borrado = st.checkbox(
                    "Confirmo que quiero borrar esta cuenta y TODOS sus datos", key=f"confirmar_del_{cta['id']}",
                )
                if st.button(
                    "🗑️ Borrar cuenta definitivamente", key=f"del_{cta['id']}",
                    disabled=not confirmar_borrado, width="stretch",
                ):
                    db.eliminar_cuenta_y_datos(cta["id"])
                    st.toast("Cuenta eliminada.", icon="✅")
                    st.rerun()




def _pantalla_admin_login():
    st.caption("Acceso restringido a cuentas con permisos de administrador.")
    with st.form("form_admin_login"):
        email_in = st.text_input("Email")
        pw_in = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", width="stretch")
    if entrar:
        cuenta = db.obtener_cuenta_por_email(email_in)
        if not cuenta or not config.verify_password(pw_in, cuenta["password_hash"], cuenta["password_salt"]):
            st.error("Email o contraseña incorrectos.")
        elif not cuenta.get("activo"):
            st.error("Esta cuenta está desactivada.")
        elif cuenta.get("rol") != "admin":
            st.error("Esta cuenta no tiene permisos de administrador.")
        else:
            st.session_state.admin_cuenta_id = cuenta["id"]
            st.rerun()
    st.divider()
    st.caption("[← Volver al inicio de sesión normal](?)")


def _panel_admin_standalone():
    st.markdown(
        _render_html(
            "page_header.html",
            icono=_logo_html("LinkedIn Poster", "page-header-logo-img"),
            titulo="Panel de administración",
            descripcion="Credenciales de la instalación, cuota de Gemini y gestión de cuentas.",
        ),
        unsafe_allow_html=True,
    )
    admin_id = st.session_state.get("admin_cuenta_id")
    admin_cuenta = db.obtener_cuenta(admin_id) if admin_id else None
    if not admin_cuenta or admin_cuenta.get("rol") != "admin" or not admin_cuenta.get("activo"):
        st.session_state.pop("admin_cuenta_id", None)
        _pantalla_admin_login()
        return
    col_ses1, col_ses2 = st.columns([5, 1])
    col_ses1.caption(f"Sesión de administrador: {admin_cuenta['email']}")
    if col_ses2.button("Cerrar sesión", key="cerrar_sesion_admin"):
        st.session_state.pop("admin_cuenta_id", None)
        st.rerun()
    _pagina_admin(admin_cuenta["id"])


# =============================================================================
# Callback OAuth de LinkedIn — GLOBAL, antes del gate de login
# =============================================================================
# LinkedIn redirige de vuelta a esta URL con ?code=...&state=... (éxito) o
# ?error=...&error_description=... (rechazo) tras la autorización. Eso es una
# recarga COMPLETA de la página — una sesión nueva de Streamlit, sin memoria
# de qué cuenta iba conectando su LinkedIn — así que el "state" que se envió
# a LinkedIn lleva el cuenta_id embebido y firmado (ver
# linkedin_oauth.generar_state/verificar_y_extraer_cuenta): al volver, se
# verifica la firma y se usa ese cuenta_id para completar el login Y para
# re-autenticar esta sesión nueva como esa cuenta (si no, habría que volver
# a iniciar sesión justo después de conectar LinkedIn, mala experiencia).
_qp = st.query_params
_nav_forzada = None
if ("code" in _qp or "error" in _qp) and not st.session_state.get("login_procesado"):
    st.session_state.login_procesado = True
    _cuenta_desde_state = linkedin_oauth.verificar_y_extraer_cuenta(_qp.get("state") or "")

    if "error" in _qp:
        _codigo_error = _qp.get("error") or ""
        _detalle = _qp.get("error_description") or _codigo_error
        _mensaje_error = f"LinkedIn rechazó la autorización: {_detalle}"
        if "scope" in _codigo_error.lower() or "scope" in (_detalle or "").lower():
            _mensaje_error += (
                " — revisa en la app de LinkedIn (developers.linkedin.com › tu app › pestaña "
                "\"Products\") que estén añadidos \"Sign In with LinkedIn using OpenID Connect\" "
                "y \"Share on LinkedIn\"."
            )
        st.session_state.login_error = _mensaje_error
    elif _cuenta_desde_state is None:
        st.session_state.login_error = "No se pudo verificar la solicitud de conexión (caducada o inválida). Inténtalo de nuevo."
    else:
        try:
            _userinfo = linkedin_oauth.completar_login(_cuenta_desde_state, _qp["code"])
            st.session_state.login_ok_nombre = _userinfo.get("name", "usuario")
        except Exception as e:
            st.session_state.login_error = str(e)

    if _cuenta_desde_state is not None:
        # Re-autentica esta sesión nueva como la cuenta que inició el login,
        # tanto si la conexión con LinkedIn tuvo éxito como si no — para que
        # la persona no tenga que volver a escribir su email/contraseña
        # justo después de intentar conectar LinkedIn.
        st.session_state.cuenta_id = _cuenta_desde_state

    st.query_params.clear()
    _nav_forzada = "🔗 LinkedIn"

# =============================================================================
# Gate del panel de administración — corre ANTES del login normal para que
# sea alcanzable sin tener ya una sesión abierta en la app (igual que
# wp-admin no depende de estar logueado en el sitio normal).
# =============================================================================
if _qp.get("admin") == "1":
    _panel_admin_standalone()
    st.stop()


if not st.session_state.get("cuenta_id"):
    _pantalla_login()
    st.stop()

cuenta_actual = db.obtener_cuenta(st.session_state.cuenta_id)
if not cuenta_actual or not cuenta_actual.get("activo"):
    for _k in ("cuenta_id", "login_procesado"):
        st.session_state.pop(_k, None)
    st.warning("Tu sesión ya no es válida (la cuenta fue desactivada o eliminada). Inicia sesión de nuevo.")
    st.stop()

cuenta_id = cuenta_actual["id"]
es_admin = cuenta_actual.get("rol") == "admin"

if not st.session_state.get("_tema_sincronizado"):
    _parametros_tema = db.obtener_parametros(cuenta_id) or {}
    st.session_state.tema_ui = _parametros_tema.get("tema_ui_defecto") or "claro"
    st.session_state._tema_sincronizado = True

if cuenta_actual.get("debe_cambiar_password"):
    _pantalla_cambiar_password_obligatorio(cuenta_id)
    st.stop()


# =============================================================================
# Navegación
# =============================================================================

PAGINAS = {
    "🚀 Generar": "generar",
    "📅 Generación diaria": "diaria",
    "✨ Inspiración": "inspiracion",
    "⚙️ Configuración": "config",
    "🗂️ Historial": "historial",
    "🔗 LinkedIn": "linkedin",
}
# La Administración NUNCA es una opción de esta navegación, ni siquiera para
# una cuenta admin — es una pantalla completamente aparte (ver "Panel de
# administración" más arriba, alcanzable por el enlace de la pantalla de
# login o desde el propio enlace de la barra lateral, no desde aquí).

seleccion = st.segmented_control(
    "Navegación", list(PAGINAS.keys()), default=_nav_forzada or list(PAGINAS.keys())[0],
    key="nav_principal", required=True, width="stretch",
)
pagina = PAGINAS.get(seleccion, "generar")

with st.sidebar:
    st.markdown(
        _render_html("sidebar_brand.html", logo_html=_logo_html("LinkedIn Poster", "sidebar-logo-img")),
        unsafe_allow_html=True,
    )

    st.markdown("#### Tu sesión")
    st.markdown(f"**{html_lib.escape(cuenta_actual.get('nombre') or cuenta_actual['email'])}**")
    st.caption(cuenta_actual["email"] + (" · Administrador" if es_admin else ""))
    if st.button("Cerrar sesión", width="stretch"):
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        st.rerun()
    if es_admin:
        st.markdown(
            '<a class="admin-link" href="?admin=1" target="_blank">🛠️ Panel administrativo ↗</a>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("#### Estado")
    conectado_sb = bool(cuenta_actual.get("linkedin_access_token"))
    if conectado_sb:
        st.badge(f"{cuenta_actual.get('linkedin_nombre') or 'LinkedIn'}", color="green", icon="✅")
    else:
        st.badge("LinkedIn no conectado", color="gray", icon="⚪")

    todos_los_posts = db.listar_posts(cuenta_id, limit=1000)
    publicados_n = sum(1 for p in todos_los_posts if p["estado"] == "publicado")
    borradores_n = len(todos_los_posts) - publicados_n
    c1, c2 = st.columns(2)
    c1.metric("Publicados", publicados_n)
    c2.metric("Borradores", borradores_n)

    _estado_cuota_sb = llm.estado_cuota_gemini_hoy()
    _activo_sb = _estado_cuota_sb["activo"]
    if _estado_cuota_sb["todos_agotados"]:
        st.badge("Cuota IA agotada hoy", color="red", icon="🔴")
    elif _activo_sb and _activo_sb["usados"] > 0:
        _pct_sb = _activo_sb["usados"] / _activo_sb["limite"] if _activo_sb["limite"] else 0
        _color_sb = "red" if _pct_sb >= 1 else ("orange" if _pct_sb >= 0.7 else "gray")
        st.badge(f"IA hoy: {_activo_sb['usados']}/{_activo_sb['limite']}", color=_color_sb, icon="🧠")

    st.divider()
    opciones_tema = ["☀️ Claro", "🌙 Oscuro"]
    tema_sel = st.segmented_control(
        "Tema", opciones_tema,
        default=opciones_tema[1] if st.session_state.tema_ui == "oscuro" else opciones_tema[0],
        key="tema_ui_control", label_visibility="collapsed",
    )
    tema_nuevo = "oscuro" if tema_sel == opciones_tema[1] else "claro"
    if tema_nuevo != st.session_state.tema_ui:
        st.session_state.tema_ui = tema_nuevo
        db.guardar_tema_ui(cuenta_id, tema_nuevo)
        st.rerun()


# Cabecera compacta de la página actual — sustituye al hero grande (que
# desde la V5.6 solo se ve en la pantalla de login) por algo que se
# identifica con lo que se hace EN ESTA página en concreto. La marca de la
# app ya vive de forma permanente en la barra lateral, así que aquí no
# hace falta repetir el logo.
PAGINA_HEADERS = {
    "generar": ("🚀", "Generar publicación", "Texto y, si quieres, infografía — revisa y edita antes de publicar."),
    "diaria": ("📅", "Generación diaria", "Reparto automático por hora, temáticas rotativas y subida masiva."),
    "inspiracion": ("✨", "Inspiración", "Ejemplos de texto e imagen para que la IA aprenda tu estilo."),
    "config": ("⚙️", "Configuración", "Tono, formato por defecto, marca personal y ajustes de tu cuenta."),
    "historial": ("🗂️", "Historial", "Todo lo generado y publicado hasta ahora, con su estado."),
    "linkedin": ("🔗", "Conectar LinkedIn", "Vincula tu cuenta para poder publicar directamente desde aquí."),
}
_icono_pg, _titulo_pg, _desc_pg = PAGINA_HEADERS.get(pagina, ("💼", "LinkedIn Poster", ""))
st.markdown(
    _render_html("page_header.html", icono=_icono_pg, titulo=_titulo_pg, descripcion=_desc_pg),
    unsafe_allow_html=True,
)


# =============================================================================
# Generar Post
# =============================================================================

if pagina == "generar":
    parametros_default = db.obtener_parametros(cuenta_id)
    inspiracion_disponible = db.listar_inspiracion(cuenta_id)

    modo_gen = st.segmented_control(
        "Modo de generación", ["🧙 Asistente completo", "⚡ Modo rápido"],
        default="🧙 Asistente completo", key="modo_generacion_top", required=True,
    )
    es_asistente = modo_gen != "⚡ Modo rápido"
    st.divider()

    boton_generar = False

    if es_asistente:
        st.markdown("##### 1️⃣ &nbsp; Origen del tema", unsafe_allow_html=True)
        origen = st.segmented_control(
            "Origen del tema", ["📝 Tema nuevo", "✨ Desde inspiración guardada"],
            default="📝 Tema nuevo", key="wizard_origen", required=True, label_visibility="collapsed",
        )
        descripcion_wizard = ""
        entrada_seed = None
        tema_listo = False
        if origen == "📝 Tema nuevo":
            descripcion_wizard = st.text_area(
                "Descripción / idea a desarrollar", key="wizard_descripcion", height=110,
                placeholder="Cuéntame qué pasó, qué aprendiste o qué quieres transmitir... "
                             "La IA lo toma como idea de partida — nunca lo copia literal.",
            )
            tema_listo = bool(descripcion_wizard.strip())
        else:
            entradas_con_texto = [i for i in inspiracion_disponible if i.get("texto_original")]
            if not entradas_con_texto:
                st.warning(
                    "Todavía no tienes ejemplos de texto guardados en ✨ Inspiración. "
                    "Añade alguno ahí, o usa '📝 Tema nuevo'."
                )
            else:
                opciones_insp = {}
                for i in entradas_con_texto:
                    txt = i["texto_original"]
                    etiqueta = f"#{i['id']} — " + (txt[:70] + "…" if len(txt) > 70 else txt)
                    opciones_insp[etiqueta] = i["id"]
                etiqueta_insp = st.selectbox(
                    "Elige un ejemplo guardado como punto de partida",
                    list(opciones_insp.keys()), key="wizard_insp_select",
                )
                id_seed = opciones_insp[etiqueta_insp]
                entrada_seed = next(i for i in entradas_con_texto if i["id"] == id_seed)
                tema_listo = True

        st.markdown("##### 2️⃣ &nbsp; Título / gancho (opcional)", unsafe_allow_html=True)
        titulo_wizard = st.text_input(
            "Título", key="wizard_titulo", label_visibility="collapsed",
            placeholder="Ej: 3 lecciones tras migrar Oracle Forms a la v12c",
        )
        st.caption(
            "El texto que escribas aquí y en la descripción nunca se copia literal en la imagen ni en la "
            "publicación — la IA solo lo usa como idea, tema e instrucciones. Si eliges infografía, también "
            "se usa como sugerencia para su titular."
        )

        st.markdown("##### 3️⃣ &nbsp; Formato del post", unsafe_allow_html=True)
        opciones_formato = ["📊 Infografía de lista", "📝 Solo texto"]
        idx_formato_defecto = 0 if (parametros_default.get("formato_post_defecto") or "infografia") == "infografia" else 1
        formato_sel = st.segmented_control(
            "Formato del post", opciones_formato, default=opciones_formato[idx_formato_defecto],
            key="wizard_formato_post", required=True,
        )
        formato_post_wizard = "infografia" if formato_sel == opciones_formato[0] else "texto"

        infografia_config_wizard = None

        if formato_post_wizard == "infografia":
            st.caption(
                "📊 Se genera una infografía de lista sobre el tema (título con una palabra clave "
                "resaltada, puntos numerados con icono y descripción), compuesta enteramente en código "
                "— no depende de ningún proveedor de generación de imagen, así que siempre es gratis y "
                "no falla por cuota."
            )
            col_i1, col_i2 = st.columns(2)
            etiquetas_paleta_wiz, etiqueta_a_valor_wiz, valor_a_etiqueta_wiz = _opciones_paleta(cuenta_id)
            paleta_defecto = parametros_default.get("infografia_paleta_defecto") or config.INFOGRAFIA_PALETA_DEFECTO
            etiqueta_defecto_wiz = valor_a_etiqueta_wiz.get(paleta_defecto, etiquetas_paleta_wiz[0])
            etiqueta_paleta_wizard = col_i1.selectbox(
                "Paleta de colores", etiquetas_paleta_wiz,
                index=etiquetas_paleta_wiz.index(etiqueta_defecto_wiz),
                key="wizard_infografia_paleta",
            )
            paleta_infografia_wizard = etiqueta_a_valor_wiz[etiqueta_paleta_wizard]
            num_items_wizard = col_i2.number_input(
                "Número de puntos", min_value=3, max_value=20,
                value=int(parametros_default.get("infografia_num_items_defecto") or 8), step=1,
                key="wizard_infografia_num_items",
            )
            with st.expander("🎨 Ver colores de cada paleta / crear una personalizada"):
                _render_galeria_paletas(cuenta_id)
                st.divider()
                _gestor_paletas_personalizadas(cuenta_id, key_prefix="wizard")
            opciones_estilo_infografia = ["🌙 Lienzo oscuro", "☀️ Lienzo claro"]
            estilo_defecto_idx = 0 if (parametros_default.get("infografia_estilo_defecto") or "oscuro") == "oscuro" else 1
            estilo_sel_wizard = st.segmented_control(
                "Estilo de la infografía", opciones_estilo_infografia,
                default=opciones_estilo_infografia[estilo_defecto_idx], key="wizard_infografia_estilo", required=True,
            )
            infografia_config_wizard = {
                "paleta_nombre": paleta_infografia_wizard,
                "num_items": int(num_items_wizard),
                "oscuro": estilo_sel_wizard == opciones_estilo_infografia[0],
            }
        else:
            st.caption("📝 Publicación de solo texto, sin ninguna imagen.")

        nombre_marca_wizard, rol_marca_wizard, modo_marca_wizard = "", "", "foto"
        incluir_marca_wizard = False
        if formato_post_wizard == "infografia":
            st.markdown("##### 4️⃣ &nbsp; Marca personal en la imagen", unsafe_allow_html=True)
            incluir_marca_wizard = st.toggle(
                "Añadir una referencia a tu perfil en la imagen (foto o iniciales + nombre + cargo)",
                value=bool(parametros_default.get("incluir_marca_personal_default")), key="wizard_incluir_marca",
            )
            if incluir_marca_wizard:
                foto_config = parametros_default.get("foto_perfil_path")
                tiene_foto = bool(foto_config and os.path.exists(foto_config))
                opciones_modo = ["📷 Con foto de perfil", "🔤 Solo iniciales"]
                modo_default_idx = 0 if (parametros_default.get("marca_personal_modo_default") or "foto") == "foto" else 1
                modo_sel_wizard = st.segmented_control(
                    "Formato", opciones_modo, default=opciones_modo[modo_default_idx],
                    key="wizard_modo_marca", required=True,
                )
                modo_marca_wizard = "foto" if modo_sel_wizard == opciones_modo[0] else "texto"
                if modo_marca_wizard == "foto" and not tiene_foto:
                    if foto_config:
                        st.caption(
                            f"⚠️ Tienes una foto guardada en la base de datos pero no se encuentra en disco "
                            f"(`{foto_config}`) — vuelve a subirla en ⚙️ Configuración. Mientras tanto se usarán tus iniciales."
                        )
                    else:
                        st.caption(
                            "⚠️ No tienes foto de perfil guardada (pestaña ⚙️ Configuración) — se usarán tus iniciales."
                        )
                col_n1, col_n2 = st.columns(2)
                nombre_marca_wizard = col_n1.text_input(
                    "Nombre a mostrar",
                    value=cuenta_actual.get("linkedin_nombre") or cuenta_actual.get("nombre") or "",
                    key="wizard_nombre_marca",
                )
                rol_marca_wizard = col_n2.text_input(
                    "Cargo / rol a mostrar", value=parametros_default.get("sector") or "", key="wizard_rol_marca",
                )

        st.divider()
        boton_generar = st.button(
            "✨ Generar variantes", type="primary", disabled=not tema_listo, width="stretch",
            key="btn_generar_asistente",
        )
        if boton_generar:
            partes_tema = []
            if titulo_wizard.strip():
                partes_tema.append(f"Título/gancho de referencia (idea, no copiar literal): {titulo_wizard.strip()}")
            if origen == "📝 Tema nuevo":
                partes_tema.append(descripcion_wizard.strip())
            elif entrada_seed:
                partes_tema.append(
                    "Basado en este ejemplo guardado por el usuario, como idea de partida "
                    f"(no copiar literal, solo tomar tema y estructura): {entrada_seed['texto_original'][:1500]}"
                )
            tema_final = "\n".join(parte for parte in partes_tema if parte)

            inspiracion_relevante = [i for i in inspiracion_disponible if i["favorito"]] or inspiracion_disponible

            overlay_marca = None
            if incluir_marca_wizard:
                foto_config = parametros_default.get("foto_perfil_path")
                ruta_foto_marca = (
                    foto_config if (modo_marca_wizard == "foto" and foto_config and os.path.exists(foto_config))
                    else None
                )
                overlay_marca = {
                    "nombre": nombre_marca_wizard.strip() or "Tu nombre",
                    "rol": rol_marca_wizard.strip(),
                    "ruta_foto": ruta_foto_marca,
                }

            if infografia_config_wizard:
                infografia_config_wizard = dict(infografia_config_wizard)
                infografia_config_wizard["titulo_sugerido"] = titulo_wizard.strip() or None

            _lanzar_generacion_variantes(
                tema_final, parametros_default, inspiracion_relevante, overlay_marca,
                formato_post=formato_post_wizard, infografia_config=infografia_config_wizard,
            )

    else:
        tema_rapido = st.text_area(
            "Tema", placeholder="Ej: acabamos de terminar la migración de Oracle Forms a la v12c...",
            height=100, label_visibility="collapsed", key="tema_rapido",
        )
        if inspiracion_disponible:
            n_fav = sum(1 for i in inspiracion_disponible if i["favorito"])
            if n_fav:
                st.caption(f"💡 Se usarán tus {n_fav} ejemplo(s) de inspiración favoritos.")
            else:
                st.caption(f"💡 Se usarán tus {len(inspiracion_disponible)} ejemplo(s) de inspiración disponibles.")
        formato_rapido = parametros_default.get("formato_post_defecto") or "infografia"
        etiqueta_formato_rapido = "📊 infografía de lista" if formato_rapido == "infografia" else "📝 solo texto"
        st.caption(
            f"Se generará en formato {etiqueta_formato_rapido} (tu formato por defecto, cambialo en "
            "⚙️ Configuración) con tu preferencia de marca personal guardada, sin preguntas adicionales. "
            "Usa el 🧙 Asistente completo para elegir el formato en cada publicación."
        )

        boton_generar = st.button(
            "✨ Generar variantes", type="primary", disabled=not tema_rapido.strip(), width="stretch",
            key="btn_generar_rapido",
        )
        if boton_generar:
            inspiracion_relevante = [i for i in inspiracion_disponible if i["favorito"]] or inspiracion_disponible

            overlay_marca = None
            if bool(parametros_default.get("incluir_marca_personal_default")):
                foto_config = parametros_default.get("foto_perfil_path")
                modo_def = parametros_default.get("marca_personal_modo_default") or "foto"
                ruta_foto_marca = foto_config if (modo_def == "foto" and foto_config and os.path.exists(foto_config)) else None
                overlay_marca = {
                    "nombre": cuenta_actual.get("linkedin_nombre") or cuenta_actual.get("nombre") or "Tu nombre",
                    "rol": parametros_default.get("sector") or "",
                    "ruta_foto": ruta_foto_marca,
                }

            infografia_config_rapido = None
            if formato_rapido == "infografia":
                infografia_config_rapido = {
                    "paleta_nombre": parametros_default.get("infografia_paleta_defecto") or config.INFOGRAFIA_PALETA_DEFECTO,
                    "num_items": int(parametros_default.get("infografia_num_items_defecto") or 8),
                    "oscuro": (parametros_default.get("infografia_estilo_defecto") or "oscuro") == "oscuro",
                }

            _lanzar_generacion_variantes(
                tema_rapido.strip(), parametros_default, inspiracion_relevante, overlay_marca,
                formato_post=formato_rapido, infografia_config=infografia_config_rapido,
            )

    if st.session_state.get("variantes"):
        ronda = st.session_state.get("ronda", 0)
        variantes = st.session_state.variantes

        st.divider()
        st.markdown("#### 1. Elige una variante")
        cols = st.columns(len(variantes))
        for i, col in enumerate(cols):
            activa = st.session_state.get("variante_idx", 0) == i
            with col:
                with st.container(border=True, height=210):
                    st.caption(f"Variante {i + 1}" + (" ✅" if activa else ""))
                    st.text(variantes[i])
                if st.button(
                    "Elegida ✓" if activa else "Elegir esta", key=f"elegir_{ronda}_{i}",
                    width="stretch", type=("primary" if activa else "secondary"), disabled=activa,
                ):
                    st.session_state.variante_idx = i
                    st.rerun()

        idx = st.session_state.get("variante_idx", 0)

        st.markdown("#### 2. Edita el texto final")
        texto_editable = st.text_area(
            "Texto final", value=variantes[idx], height=220,
            key=f"texto_editable_{ronda}_{idx}", label_visibility="collapsed",
        )

        overlay_marca_actual = st.session_state.get("overlay_marca_actual")
        formato_post_actual = st.session_state.get("formato_post_actual") or "infografia"
        infografia_config_actual = st.session_state.get("infografia_config_actual") or {}
        es_infografia = formato_post_actual == "infografia"

        if es_infografia:
            st.markdown("#### 3. Imagen")
            etiqueta_estilo_actual = "🌙 oscuro" if infografia_config_actual.get("oscuro", True) else "☀️ claro"
            resumen_bits = [
                f"📊 infografía de {infografia_config_actual.get('num_items', 8)} puntos · "
                f"paleta {_etiqueta_paleta(cuenta_id, infografia_config_actual.get('paleta_nombre'))} · "
                f"estilo {etiqueta_estilo_actual}"
            ]
            if overlay_marca_actual:
                nombre_m = overlay_marca_actual.get("nombre") or "Tu nombre"
                rol_m = overlay_marca_actual.get("rol")
                resumen_bits.append(f"🪪 marca personal: {nombre_m}" + (f" · {rol_m}" if rol_m else ""))
            st.caption(" &nbsp;·&nbsp; ".join(resumen_bits), unsafe_allow_html=True)

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🎨 Generar imagen", width="stretch"):
                    with st.status("Generando infografía...", expanded=False) as status:
                        try:
                            datos_infografia = llm.generar_infografia_contenido(
                                st.session_state.tema_actual, db.obtener_parametros(cuenta_id),
                                st.session_state.get("inspiracion_relevante"),
                                num_items=infografia_config_actual.get("num_items", 8),
                                titulo_sugerido=infografia_config_actual.get("titulo_sugerido"),
                            )
                            paleta_nombre = infografia_config_actual.get("paleta_nombre", config.INFOGRAFIA_PALETA_DEFECTO)
                            paleta_hex = db.resolver_paleta_infografia(cuenta_id, paleta_nombre)
                            st.session_state.imagen_path = image_infografia.generar_infografia(
                                datos_infografia, paleta_hex, marca=overlay_marca_actual,
                                oscuro=infografia_config_actual.get("oscuro", True),
                            )
                            st.session_state.imagen_proveedor = "infografia"
                            status.update(label="¡Infografía lista!", state="complete")
                        except Exception as e:
                            status.update(label="Error generando la infografía", state="error")
                            _reportar_error("Error generando la infografía", e)
            with col_b:
                if st.session_state.get("imagen_path"):
                    if st.button("🗑️ Quitar imagen", width="stretch"):
                        st.session_state.imagen_path = None
                        st.session_state.imagen_proveedor = None
                        st.rerun()
        else:
            st.caption("📝 Publicación de solo texto — sin ninguna imagen.")

        st.markdown("#### 4. Vista previa y publicación")
        nombre_preview = cuenta_actual.get("linkedin_nombre") or cuenta_actual.get("nombre") or "Tu nombre"
        parametros_preview = db.obtener_parametros(cuenta_id)
        render_preview_linkedin(
            nombre_preview, parametros_preview.get("sector") or "", texto_editable,
            st.session_state.get("imagen_path"),
        )

        col1, col2 = st.columns(2)
        if col1.button("💾 Guardar como borrador", width="stretch"):
            post_id = db.crear_post(cuenta_id, st.session_state.tema_actual, texto_editable, st.session_state.get("imagen_path") or "")
            st.session_state.post_id_actual = post_id
            st.toast(f"Guardado como borrador (#{post_id}).", icon="✅")
            st.rerun()

        conectado = bool(cuenta_actual.get("linkedin_access_token"))
        if col2.button("📤 Publicar en LinkedIn", type="primary", disabled=not conectado, width="stretch"):
            with st.status("Publicando en LinkedIn...", expanded=False) as status:
                try:
                    post_id_local = st.session_state.get("post_id_actual") or db.crear_post(
                        cuenta_id, st.session_state.tema_actual, texto_editable, st.session_state.get("imagen_path") or ""
                    )
                    post_id_linkedin = linkedin_publish.publicar_post(cuenta_id, texto_editable, st.session_state.get("imagen_path"))
                    db.marcar_publicado(post_id_local, post_id_linkedin)
                    status.update(label="¡Publicado!", state="complete")
                    st.toast("¡Publicado en LinkedIn! 🎉", icon="✅")
                    for k in [
                        "variantes", "tema_actual", "imagen_path", "imagen_proveedor", "post_id_actual",
                        "variante_idx", "inspiracion_relevante", "overlay_marca_actual",
                        "formato_post_actual", "infografia_config_actual",
                    ]:
                        st.session_state.pop(k, None)
                    st.rerun()
                except Exception as e:
                    status.update(label="Error al publicar", state="error")
                    _reportar_error("Error al publicar en LinkedIn", e)
        if not conectado:
            st.caption("Conecta tu cuenta de LinkedIn (pestaña 🔗 LinkedIn arriba) para poder publicar directamente.")


# =============================================================================
# Generación diaria
# =============================================================================

elif pagina == "diaria":
    st.caption(
        "Planifica cuántos posts quieres generar cada día (reparto fijo entre infografía y solo texto). "
        "Por defecto tú decides cuándo pulsar 'generar' (cola manual, sin publicar nada sin que lo revises) "
        "— la 🤖 Automatización Total de más abajo es opcional y explícita."
    )

    parametros_diaria = db.obtener_parametros(cuenta_id)

    with st.container(border=True):
        st.markdown("**Reparto diario**")
        st.caption(
            "No hay un límite técnico real: el nivel gratuito de Gemini permite cientos de peticiones al día. "
            "Este reparto es solo tu propia decisión de cuántos posts quieres generar cada día."
        )
        col_r1, col_r2 = st.columns(2)
        n_infografia_actual = col_r1.number_input(
            "📊 Infografías / día", min_value=0, max_value=20,
            value=int(parametros_diaria.get("reparto_diario_infografia") or 0), step=1, key="reparto_infografia",
        )
        n_texto_actual = col_r2.number_input(
            "📝 Solo texto / día", min_value=0, max_value=20,
            value=int(parametros_diaria.get("reparto_diario_texto") or 0), step=1, key="reparto_texto",
        )
        if st.button("💾 Guardar reparto", key="btn_guardar_reparto"):
            db.guardar_reparto_diario(cuenta_id, n_infografia_actual, n_texto_actual)
            cambios = daily.resincronizar_plan_hoy(cuenta_id)
            añadidos = cambios.get("añadidos") or {}
            quitados = cambios.get("quitados") or {}
            if añadidos or quitados:
                partes = []
                if añadidos:
                    partes.append("añadidos: " + ", ".join(f"{n} {t}" for t, n in añadidos.items()))
                if quitados:
                    partes.append("quitados: " + ", ".join(f"{n} {t}" for t, n in quitados.items()))
                st.success(f"Reparto diario guardado — plan de hoy actualizado ({'; '.join(partes)}).")
            else:
                st.success("Reparto diario guardado.")
            st.rerun()

    with st.container(border=True):
        st.markdown("**🎯 Temáticas para la generación automática**")
        st.caption(
            "Configura una lista de temas y la generación automática (aquí y en la 🤖 Automatización Total) "
            "irá rotando entre ellos en vez de improvisar un tema libre cada vez — por ejemplo Python, "
            "Seguridad, Cloud: un día le toca a uno, el siguiente al otro (la IA sigue eligiendo un ángulo "
            "concreto dentro de cada tema, no repite lo mismo). Si no añades ninguno, la IA sigue proponiendo "
            "un tema libre por su cuenta, como hasta ahora."
        )
        temas_actuales = db.listar_temas(cuenta_id)
        if temas_actuales:
            for t in temas_actuales:
                ct1, ct2, ct3 = st.columns([3, 1, 1])
                ct1.markdown(("✅ " if t["activo"] else "⏸️ ") + html_lib.escape(t["nombre"]))
                etiqueta_act = "Desactivar" if t["activo"] else "Activar"
                if ct2.button(etiqueta_act, key=f"tema_toggle_{t['id']}", width="stretch"):
                    db.activar_tema(t["id"], not t["activo"])
                    st.rerun()
                if ct3.button("🗑️", key=f"tema_del_{t['id']}", width="stretch"):
                    db.eliminar_tema(t["id"])
                    st.rerun()
        else:
            st.caption("Todavía no has añadido ninguna temática — la IA elige el tema libremente.")

        with st.form("form_nuevo_tema", clear_on_submit=True, border=False):
            col_t1, col_t2 = st.columns([3, 1])
            nuevo_tema = col_t1.text_input(
                "Nueva temática", placeholder="Ej: Python, Seguridad, Cloud, Oracle...", label_visibility="collapsed",
            )
            agregar_tema_btn = col_t2.form_submit_button("➕ Añadir", width="stretch")
        if agregar_tema_btn:
            if nuevo_tema.strip():
                db.agregar_tema(cuenta_id, nuevo_tema.strip())
                st.toast("Temática añadida.", icon="✅")
                st.rerun()
            else:
                st.toast("Escribe un nombre antes de añadir.", icon="⚠️")

    st.divider()

    fecha_hoy = daily.hoy()
    plan_hoy = daily.asegurar_plan_del_dia(cuenta_id, fecha_hoy)

    st.markdown(f"**Plan de hoy** ({fecha_hoy})")
    if not plan_hoy:
        st.info("El reparto diario está en 0/0 — no hay nada planificado para hoy. Ajusta el reparto arriba.")
    else:
        iconos_tipo = {"infografia": "📊", "texto": "📝"}
        color_estado_plan = {"pendiente": "gray", "generado": "blue", "publicado": "green", "error": "red"}
        for item in plan_hoy:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.markdown(f"{iconos_tipo.get(item['tipo'], '•')} **{item['tipo'].capitalize()}**")
                c2.badge(item["estado"].capitalize(), color=color_estado_plan.get(item["estado"], "gray"))
                if item["estado"] == "pendiente":
                    if c3.button("▶️ Generar", key=f"gen_item_{item['id']}", width="stretch"):
                        with st.spinner("Generando..."):
                            resultado = daily.generar_item(cuenta_id, item, publicar=False)
                        if resultado.get("estado") == "cuota_agotada":
                            st.warning(f"⏳ {resultado.get('error')}")
                        elif resultado.get("estado") == "error":
                            st.error(f"Error: {resultado.get('error')}")
                        else:
                            st.toast(f"Generado como borrador (post #{resultado.get('post_id')}).", icon="✅")
                            st.rerun()
                elif item["estado"] == "error":
                    st.caption(f"⚠️ {item.get('error') or 'Error desconocido'}")
                elif item.get("post_id"):
                    st.caption(f"Post #{item['post_id']} — revísalo y publícalo en 🗂️ Historial.")

        pendientes_hoy = [i for i in plan_hoy if i["estado"] == "pendiente"]
        if pendientes_hoy and st.button(
            f"▶️ Generar todo lo pendiente de hoy ({len(pendientes_hoy)})", type="primary", width="stretch",
        ):
            with st.spinner(f"Generando {len(pendientes_hoy)} post(s)..."):
                resultados = daily.generar_pendientes_del_dia(cuenta_id, fecha_hoy, publicar=False)
            errores = [r for r in resultados if r.get("estado") == "error"]
            cuota_agotada = [r for r in resultados if r.get("estado") == "cuota_agotada"]
            if cuota_agotada:
                generados = len(resultados) - len(cuota_agotada)
                st.warning(
                    f"⏳ Se generaron {generados} de {len(pendientes_hoy)} — se agotó la cuota gratuita de "
                    "Gemini. Los que faltan siguen pendientes y se generarán en el próximo intento."
                )
            elif errores:
                st.warning(f"Generado con {len(errores)} error(es) — revisa los detalles arriba.")
            else:
                st.success("¡Todo el plan de hoy generado como borrador! Revísalo en 🗂️ Historial.")
            st.rerun()

    st.divider()

    with st.expander("🤖 Automatización Total (avanzado)"):
        st.warning(
            "Esto permite que un script aparte (`generar_diario.py`, disparado por el Programador de "
            "tareas de Windows) genere — y, si lo activas, PUBLIQUE — posts sin que nadie los revise. "
            "Actívalo solo si confías en el resultado sin supervisión.",
            icon="⚠️",
        )
        activa_actual = bool(parametros_diaria.get("automatizacion_total_activa"))
        auto_publicar_actual = bool(parametros_diaria.get("automatizacion_auto_publicar"))
        hora_actual_str = parametros_diaria.get("automatizacion_hora") or "09:00"
        try:
            hora_actual_obj = datetime.strptime(hora_actual_str, "%H:%M").time()
        except ValueError:
            hora_actual_obj = datetime.strptime("09:00", "%H:%M").time()

        activa_nueva = st.toggle(
            "Activar Automatización Total", value=activa_actual, key="auto_total_activa",
        )
        hora_nueva = st.time_input(
            "Hora de generación / publicación",
            value=hora_actual_obj, key="auto_total_hora", step=900, disabled=not activa_nueva,
            help="A partir de esta hora, la próxima vez que el latido programado se ejecute generará "
                 "(y, si lo activaste, publicará) el plan de hoy. No hace falta que coincida al minuto: "
                 "basta con que el latido pase con la frecuencia indicada más abajo.",
        )
        auto_publicar_nuevo = st.toggle(
            "Publicar directo en LinkedIn sin revisión manual (si se desactiva, se generan como borrador)",
            value=auto_publicar_actual, key="auto_total_publicar", disabled=not activa_nueva,
        )
        if st.button("💾 Guardar automatización", key="btn_guardar_auto"):
            db.guardar_automatizacion(cuenta_id, activa_nueva, auto_publicar_nuevo, hora_nueva.strftime("%H:%M"))
            st.toast("Configuración de automatización guardada.", icon="✅")
            st.rerun()

        if activa_nueva:
            st.markdown(
                f"**Se generará a partir de las {hora_nueva.strftime('%H:%M')}**, la primera vez que el "
                "latido programado se ejecute ese día. Para eso, la tarea programada debe dispararse con "
                "frecuencia (cada 15-30 min), no una sola vez al día — el propio script comprueba la hora "
                "de cada cuenta y no hace nada hasta que le toca, y nunca duplica ni repite lo ya generado "
                "ese día aunque se dispare muchas veces."
            )
            st.markdown("**Cómo programarlo en Windows (una sola vez, sirve para todas las cuentas):**")
            st.code(
                'schtasks /create /tn "LinkedIn AI Poster - Generacion diaria" '
                f'/tr "\\"{os.path.join(config.BASE_DIR, "generar_diario.bat")}\\"" '
                '/sc minute /mo 15',
                language="text",
            )
            st.caption(
                "Pega ese comando en una consola (cmd, como administrador) para crear la tarea programada "
                "— se ejecutará cada 15 minutos (el propio script decide si a cada cuenta le toca ya o no, "
                "según su hora configurada) y comprobará TODAS las cuentas que tengan la Automatización "
                "Total activada, no solo la tuya. También puedes crearla a mano desde el Programador de "
                f"tareas de Windows apuntando a `{os.path.join(config.BASE_DIR, 'generar_diario.bat')}`. "
                "El script no hace nada para las cuentas que no hayan activado esto, ni antes de su hora "
                "— puedes dejar la tarea programada creada sin riesgo.\n\n"
                "**¿Ya tenías la tarea programada antigua creada (una vez al día)?** Bórrala primero con "
                "`schtasks /delete /tn \"LinkedIn AI Poster - Generacion diaria\" /f` y vuelve a crearla "
                "con el comando de arriba para que pase a comprobar cada 15 minutos en vez de una sola vez."
            )

    with st.expander("🚀 Subida masiva — generar varios posts de golpe"):
        st.caption(
            "Genera ya mismo una tanda de posts (no repartidos por hora, todos de una vez), totalmente "
            "configurable — usa las mismas 🎯 temáticas rotativas de arriba si las tienes configuradas, "
            "sin interferir con el plan automático del día ni con la 🤖 Automatización Total."
        )
        _estado_cuota_lote = llm.estado_cuota_gemini_hoy()
        if _estado_cuota_lote["todos_agotados"]:
            st.warning("⏳ La cuota de Gemini está agotada hoy en todos los modelos disponibles — espera a mañana.")
        else:
            _capacidad_restante_lote = sum(
                max(0, m["limite"] - m["usados"]) for m in _estado_cuota_lote["modelos"] if not m["agotado"]
            )
            st.caption(
                f"📊 Capacidad de Gemini restante hoy: ≈{_capacidad_restante_lote} llamadas (sumando los "
                f"{len(_estado_cuota_lote['modelos'])} modelos de respaldo) — recuerda que cada infografía gasta 2."
            )
        colm1, colm2 = st.columns(2)
        n_infografia_lote = colm1.number_input(
            "📊 Infografías en esta tanda", min_value=0, max_value=12, value=2, step=1, key="lote_n_infografia",
        )
        n_texto_lote = colm2.number_input(
            "📝 Solo texto en esta tanda", min_value=0, max_value=12, value=0, step=1, key="lote_n_texto",
        )
        total_lote = int(n_infografia_lote) + int(n_texto_lote)

        etiquetas_paleta_lote, etiqueta_a_valor_lote, valor_a_etiqueta_lote = _opciones_paleta(cuenta_id)
        paleta_defecto_lote = parametros_diaria.get("infografia_paleta_defecto") or config.INFOGRAFIA_PALETA_DEFECTO
        etiqueta_defecto_lote = valor_a_etiqueta_lote.get(paleta_defecto_lote, etiquetas_paleta_lote[0])
        colm3, colm4 = st.columns(2)
        etiqueta_paleta_lote_sel = colm3.selectbox(
            "Paleta de la infografía", etiquetas_paleta_lote,
            index=etiquetas_paleta_lote.index(etiqueta_defecto_lote), key="lote_paleta",
            disabled=int(n_infografia_lote) == 0,
        )
        opciones_estilo_lote = ["🌙 Lienzo oscuro", "☀️ Lienzo claro"]
        idx_estilo_lote = 0 if (parametros_diaria.get("infografia_estilo_defecto") or "oscuro") == "oscuro" else 1
        estilo_lote_sel = colm4.segmented_control(
            "Estilo de la infografía", opciones_estilo_lote, default=opciones_estilo_lote[idx_estilo_lote],
            key="lote_estilo", disabled=int(n_infografia_lote) == 0,
        )
        with st.expander("🎨 Ver colores de cada paleta / crear una personalizada"):
            _render_galeria_paletas(cuenta_id)
            st.divider()
            _gestor_paletas_personalizadas(cuenta_id, key_prefix="lote")

        conectado_lote = bool(cuenta_actual.get("linkedin_access_token"))
        publicar_lote = st.checkbox(
            "Publicar automáticamente en LinkedIn en cuanto se generen (si lo dejas sin marcar, se generan "
            "como borrador y tú decides cuándo publicarlos desde 🗂️ Historial)",
            value=False, key="lote_publicar", disabled=not conectado_lote,
        )
        if not conectado_lote:
            st.caption("Conecta tu cuenta de LinkedIn (pestaña 🔗 LinkedIn) para poder publicar directo desde aquí.")

        if st.button(
            f"🚀 Generar {total_lote} post(s) ahora", type="primary", width="stretch",
            disabled=total_lote == 0, key="btn_generar_lote",
        ):
            tipos_lote = ["infografia"] * int(n_infografia_lote) + ["texto"] * int(n_texto_lote)
            etiqueta_tiempo = "publicando" if publicar_lote else "generando como borrador"
            with st.spinner(f"{etiqueta_tiempo.capitalize()} {total_lote} post(s) — puede tardar varios minutos..."):
                st.session_state.bulk_resultados = daily.generar_lote(
                    cuenta_id, tipos_lote, publicar=publicar_lote,
                    paleta_valor=etiqueta_a_valor_lote[etiqueta_paleta_lote_sel],
                    oscuro=(estilo_lote_sel == opciones_estilo_lote[0]),
                )

        resultados_lote = st.session_state.get("bulk_resultados")
        if resultados_lote:
            iconos_tipo_lote = {"infografia": "📊", "texto": "📝"}
            color_estado_lote = {
                "generado": "blue", "publicado": "green", "error": "red", "cuota_agotada": "orange",
                "duplicado_omitido": "orange",
            }
            etiqueta_estado_lote = {
                "generado": "Generado", "publicado": "Publicado", "error": "Error",
                "cuota_agotada": "Cuota agotada", "duplicado_omitido": "Duplicado",
            }
            errores_lote = [r for r in resultados_lote if r.get("estado") == "error"]
            cuota_agotada_lote = [r for r in resultados_lote if r.get("estado") == "cuota_agotada"]
            duplicados_lote = [r for r in resultados_lote if r.get("estado") == "duplicado_omitido"]
            if cuota_agotada_lote:
                generados_lote = len(resultados_lote) - len(cuota_agotada_lote)
                st.warning(
                    f"⏳ Se generaron {generados_lote} de {total_lote} — se agotó la cuota gratuita de "
                    "Gemini. Vuelve a intentarlo en unos minutos para el resto."
                )
            elif duplicados_lote:
                st.warning(
                    f"⚠️ {len(duplicados_lote)} pieza(s) salieron con el mismo texto que un post ya "
                    "publicado hace poco — no se han vuelto a publicar (se quedaron como borrador, "
                    "revísalas en 🗂️ Historial)."
                )
            elif errores_lote:
                st.warning(f"Tanda completada con {len(errores_lote)} error(es) — detalle abajo.")
            else:
                st.success("¡Tanda generada! Revísala en 🗂️ Historial.")
            for r in resultados_lote:
                with st.container(border=True):
                    cr1, cr2 = st.columns([3, 1])
                    etiqueta_r = (r.get("tema") or r.get("error") or "").strip()[:80]
                    cr1.markdown(f"{iconos_tipo_lote.get(r.get('tipo'), '•')} **{etiqueta_r}**")
                    _estado_r = r.get("estado", "error")
                    cr2.badge(
                        etiqueta_estado_lote.get(_estado_r, _estado_r.capitalize()),
                        color=color_estado_lote.get(_estado_r, "red"),
                    )
            if st.button("🧹 Limpiar resultados", key="btn_limpiar_bulk_resultados"):
                del st.session_state["bulk_resultados"]
                st.rerun()

    with st.expander("Historial reciente de la generación diaria"):
        historial_plan = db.listar_plan_reciente(cuenta_id)
        if not historial_plan:
            st.caption("Todavía no hay historial.")
        else:
            iconos_tipo_hist = {"infografia": "📊", "texto": "📝"}
            for item in historial_plan:
                st.caption(
                    f"{item['fecha']} — {iconos_tipo_hist.get(item['tipo'], '•')} {item['tipo']} — **{item['estado']}**"
                    + (f" (post #{item['post_id']})" if item.get("post_id") else "")
                    + (f" — {item['error']}" if item.get("error") else "")
                )


# =============================================================================
# Inspiración
# =============================================================================

elif pagina == "inspiracion":
    st.caption(
        "Guarda publicaciones que te gusten (texto) e imágenes de referencia visual. "
        "Se usan solo como guía de estructura, ritmo, tono y estilo — nunca se copian literalmente."
    )

    with st.container(border=True):
        st.markdown("**➕ Añadir un ejemplo nuevo**")
        with st.form("form_inspiracion", clear_on_submit=True, border=False):
            texto_insp = st.text_area(
                "Texto de una publicación que te guste (opcional)", height=120,
                placeholder="Pega aquí el texto de un post que te inspire...",
            )
            imagenes_insp = st.file_uploader(
                "Imágenes de referencia visual (opcional, puedes subir varias)",
                type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True,
            )
            notas_insp = st.text_input(
                "¿Qué te gusta de este ejemplo? (opcional — si subes una imagen y lo dejas vacío, "
                "la IA describirá el estilo visual por ti)"
            )
            enviado = st.form_submit_button("➕ Añadir a inspiración", type="primary", width="stretch")

    if enviado:
        if not texto_insp.strip() and not imagenes_insp:
            st.toast("Añade al menos un texto o una imagen antes de guardar.", icon="⚠️")
        else:
            if texto_insp.strip():
                db.agregar_inspiracion(cuenta_id, texto_original=texto_insp.strip(), notas=notas_insp.strip())
            for img in (imagenes_insp or []):
                ruta = _guardar_imagen_subida(img)
                notas_finales = notas_insp.strip()
                if not notas_finales:
                    with st.spinner("Analizando estilo visual de la imagen con IA..."):
                        notas_finales = llm.analizar_estilo_imagen(ruta)
                db.agregar_inspiracion(cuenta_id, texto_original="", notas=notas_finales, imagen_path=ruta)
            st.toast("Inspiración añadida.", icon="✅")
            st.rerun()

    st.divider()
    ejemplos = db.listar_inspiracion(cuenta_id)
    st.markdown(f"**🗂️ Tus ejemplos guardados** ({len(ejemplos)})" if ejemplos else "**🗂️ Tus ejemplos guardados**")
    if not ejemplos:
        st.info(
            "Todavía no has añadido ningún ejemplo. Cuantos más añadas (sobre todo marcados "
            "como favoritos ⭐), mejor se ajustará la IA a lo que realmente quieres."
        )
    else:
        filtro = st.segmented_control(
            "Filtrar", ["Todos", "⭐ Favoritos", "🖼️ Imágenes", "📝 Texto"],
            default="Todos", key="filtro_insp",
        )
        if filtro == "⭐ Favoritos":
            ejemplos = [e for e in ejemplos if e["favorito"]]
        elif filtro == "🖼️ Imágenes":
            ejemplos = [e for e in ejemplos if e["imagen_path"]]
        elif filtro == "📝 Texto":
            ejemplos = [e for e in ejemplos if e["texto_original"]]

        if not ejemplos:
            st.caption("No hay ejemplos que coincidan con este filtro.")

        cols = st.columns(3)
        for i, ej in enumerate(ejemplos):
            with cols[i % 3]:
                with st.container(border=True):
                    if ej["imagen_path"] and os.path.exists(ej["imagen_path"]):
                        st.image(ej["imagen_path"], width="stretch")
                    if ej["texto_original"]:
                        recorte = ej["texto_original"][:160]
                        if len(ej["texto_original"]) > 160:
                            recorte += "…"
                        st.text(recorte)
                    if ej["notas"]:
                        st.caption(f"💬 {ej['notas']}")
                    st.caption(f"Añadido: {ej['fecha_agregado'][:10]}")
                    cb1, cb2 = st.columns(2)
                    etiqueta_fav = "★ Favorito" if ej["favorito"] else "☆ Marcar"
                    if cb1.button(etiqueta_fav, key=f"fav_{ej['id']}", width="stretch"):
                        db.marcar_favorito_inspiracion(ej["id"], not ej["favorito"])
                        st.rerun()
                    if cb2.button("🗑️ Eliminar", key=f"del_{ej['id']}", width="stretch"):
                        db.eliminar_inspiracion(ej["id"])
                        st.rerun()


# =============================================================================
# Configuración
# =============================================================================

elif pagina == "config":
    st.caption("Cuanto más contexto des aquí, más se parecerá el resultado a lo que realmente quieres publicar.")

    with st.container(border=True):
        st.markdown("**🔑 Mi cuenta**")
        col_mc1, col_mc2 = st.columns(2)
        col_mc1.text_input("Email", value=cuenta_actual["email"], disabled=True)
        with st.form("form_mi_nombre", border=False):
            nuevo_nombre_cuenta = col_mc2.text_input("Tu nombre", value=cuenta_actual.get("nombre") or "")
            guardar_nombre_btn = st.form_submit_button("💾 Guardar nombre")
        if guardar_nombre_btn:
            db.actualizar_cuenta(cuenta_id, nombre=nuevo_nombre_cuenta)
            st.toast("Nombre actualizado.", icon="✅")
            st.rerun()

        with st.expander("Cambiar mi contraseña"):
            with st.form("form_cambiar_mi_pw"):
                pw_actual_in = st.text_input("Contraseña actual", type="password")
                pw_nueva1_in = st.text_input("Nueva contraseña", type="password")
                pw_nueva2_in = st.text_input("Repite la nueva contraseña", type="password")
                cambiar_pw_btn = st.form_submit_button("Cambiar contraseña")
            if cambiar_pw_btn:
                if not config.verify_password(pw_actual_in, cuenta_actual["password_hash"], cuenta_actual["password_salt"]):
                    st.toast("La contraseña actual no es correcta.", icon="⚠️")
                elif not pw_nueva1_in or len(pw_nueva1_in) < 6:
                    st.toast("Usa al menos 6 caracteres.", icon="⚠️")
                elif pw_nueva1_in != pw_nueva2_in:
                    st.toast("Las dos contraseñas nuevas no coinciden.", icon="⚠️")
                else:
                    pw_hash, pw_salt = config.hash_password(pw_nueva1_in)
                    db.cambiar_password_cuenta(cuenta_id, pw_hash, pw_salt, debe_cambiar_password=False)
                    st.toast("Contraseña actualizada.", icon="✅")
                    st.rerun()

    p = db.obtener_parametros(cuenta_id)

    with st.container(border=True):
        st.markdown("**🪪 Marca personal en las imágenes**")
        st.caption(
            "Referencia opcional (foto o iniciales + nombre + cargo) que se puede añadir sobre las imágenes "
            "generadas, como en un sello de autor. La activas o no en cada publicación — aquí solo defines "
            "tu foto y la preferencia por defecto."
        )
        col_foto1, col_foto2 = st.columns([1, 2])
        foto_actual = p.get("foto_perfil_path")
        with col_foto1:
            if foto_actual and os.path.exists(foto_actual):
                st.image(foto_actual, width=110)
            else:
                st.caption("Sin foto de perfil todavía.")
        with col_foto2:
            with st.form("form_foto_perfil", clear_on_submit=True, border=False):
                nueva_foto = st.file_uploader(
                    "Foto de perfil (se recorta en círculo automáticamente)",
                    type=["png", "jpg", "jpeg", "webp"],
                )
                subir_foto = st.form_submit_button("💾 Guardar foto", width="stretch")
            if subir_foto:
                if nueva_foto:
                    ruta_nueva = _guardar_foto_perfil(nueva_foto)
                    db.guardar_foto_perfil(cuenta_id, ruta_nueva)
                    st.toast("Foto de perfil actualizada.", icon="✅")
                    st.rerun()
                else:
                    st.toast("Elige primero una imagen.", icon="⚠️")
            if foto_actual and st.button("🗑️ Quitar foto de perfil"):
                db.eliminar_foto_perfil(cuenta_id)
                st.toast("Foto de perfil eliminada.", icon="✅")
                st.rerun()

    OBJETIVOS = [
        "Marca personal / posicionamiento",
        "Generar leads o clientes",
        "Atraer talento (reclutamiento)",
        "Compartir conocimiento (thought leadership)",
        "Networking y visibilidad",
        "Otro / personalizado",
    ]

    with st.container(border=True):
        st.markdown("**🎨 Paletas de color de la infografía**")
        st.caption(
            "Estos son los colores que usa cada paleta disponible — la que elijas como 'por defecto' más "
            "abajo, en 📊 Formato de post, se usa automáticamente en ⚡ Modo rápido, 📅 Generación diaria y "
            "🚀 Subida masiva. Puedes crear tu propia paleta a partir de solo dos colores."
        )
        _render_galeria_paletas(cuenta_id)
        st.divider()
        _gestor_paletas_personalizadas(cuenta_id, key_prefix="config")

    with st.form("form_config"):
        with st.container(border=True):
            st.markdown("**🎯 Identidad y objetivo**")
            tono = st.text_input("Tono", value=p["tono"])
            sector = st.text_input(
                "Sector / rubro", value=p["sector"],
                placeholder="Ej: desarrollo de software, migraciones Oracle, marketing digital...",
            )
            objetivo_actual = p.get("objetivo") or ""
            idx_objetivo = OBJETIVOS.index(objetivo_actual) if objetivo_actual in OBJETIVOS else len(OBJETIVOS) - 1
            objetivo_sel = st.selectbox("Objetivo principal de tus publicaciones", OBJETIVOS, index=idx_objetivo)
            objetivo_custom = st.text_input(
                "Objetivo personalizado (opcional — sobreescribe la opción de arriba si lo rellenas)",
                value=(objetivo_actual if objetivo_actual not in OBJETIVOS else ""),
            )
            audiencia_objetivo = st.text_input(
                "Audiencia objetivo", value=p.get("audiencia_objetivo") or "",
                placeholder="Ej: reclutadores tech, founders de startups, clientes del sector retail...",
            )
            temas_habituales = st.text_area(
                "Temas sobre los que sueles publicar", value=p.get("temas_habituales") or "",
                placeholder="Ej: migraciones legacy, IA aplicada a desarrollo, liderazgo técnico...", height=80,
            )

        with st.container(border=True):
            st.markdown("**✍️ Formato del texto**")
            longitud = st.selectbox(
                "Longitud preferida", ["corta", "media", "larga"],
                index=["corta", "media", "larga"].index(p["longitud_preferida"])
                if p["longitud_preferida"] in ["corta", "media", "larga"] else 1,
            )
            colf1, colf2 = st.columns(2)
            usa_emojis = colf1.toggle("Usar emojis", value=bool(p["usa_emojis"]))
            usa_hashtags = colf2.toggle("Usar hashtags", value=bool(p["usa_hashtags"]))
            palabras_clave = st.text_input(
                "Palabras clave a incluir cuando encajen (separadas por comas)",
                value=p.get("palabras_clave") or "",
            )
            palabras_evitar = st.text_input(
                "Palabras o temas a evitar siempre (separadas por comas)",
                value=p.get("palabras_evitar") or "",
            )
            cta_habitual = st.text_input(
                "CTA habitual", value=p["cta_habitual"],
                placeholder="Ej: 'Cuéntame tu experiencia en comentarios'",
            )
            firma = st.text_input(
                "Firma / cierre habitual", value=p.get("firma") or "",
                placeholder="Ej: Jesús · Full Stack & AI Developer",
            )

        with st.container(border=True):
            st.markdown("**📊 Formato de post por defecto**")
            st.caption(
                "Usado por ⚡ Modo rápido y por 📅 Generación diaria, sin preguntar cada vez. "
                "En el 🧙 Asistente completo puedes elegir el formato en cada publicación."
            )
            opciones_formato_defecto = ["📊 Infografía de lista", "📝 Solo texto"]
            idx_formato_cfg = 0 if (p.get("formato_post_defecto") or "infografia") == "infografia" else 1
            formato_defecto_sel = st.segmented_control(
                "Formato por defecto", opciones_formato_defecto,
                default=opciones_formato_defecto[idx_formato_cfg], key="formato_post_defecto_config",
            )
            colf3, colf4 = st.columns(2)
            etiquetas_paleta_cfg, etiqueta_a_valor_cfg, valor_a_etiqueta_cfg = _opciones_paleta(cuenta_id)
            paleta_actual_cfg = p.get("infografia_paleta_defecto") or config.INFOGRAFIA_PALETA_DEFECTO
            etiqueta_actual_cfg = valor_a_etiqueta_cfg.get(paleta_actual_cfg, etiquetas_paleta_cfg[0])
            etiqueta_paleta_cfg_sel = colf3.selectbox(
                "Paleta de la infografía por defecto", etiquetas_paleta_cfg,
                index=etiquetas_paleta_cfg.index(etiqueta_actual_cfg),
            )
            infografia_paleta_defecto = etiqueta_a_valor_cfg[etiqueta_paleta_cfg_sel]
            infografia_num_items_defecto = colf4.number_input(
                "Nº de puntos por defecto", min_value=3, max_value=20,
                value=int(p.get("infografia_num_items_defecto") or 8), step=1,
            )
            opciones_estilo_cfg = ["🌙 Lienzo oscuro", "☀️ Lienzo claro"]
            idx_estilo_cfg = 0 if (p.get("infografia_estilo_defecto") or "oscuro") == "oscuro" else 1
            estilo_infografia_sel = st.segmented_control(
                "Estilo de la infografía por defecto", opciones_estilo_cfg,
                default=opciones_estilo_cfg[idx_estilo_cfg], key="infografia_estilo_defecto_config",
            )

        with st.container(border=True):
            st.markdown("**🪪 Preferencia por defecto de marca personal**")
            incluir_marca_personal_default = st.toggle(
                "Incluir marca personal por defecto en publicaciones nuevas",
                value=bool(p.get("incluir_marca_personal_default")),
                help="Podrás activarlo o desactivarlo para cada publicación individualmente al generarla.",
            )
            modo_marca_sel = st.segmented_control(
                "Formato por defecto",
                ["📷 Con foto de perfil", "🔤 Solo iniciales"],
                default=(
                    "📷 Con foto de perfil"
                    if (p.get("marca_personal_modo_default") or "foto") == "foto"
                    else "🔤 Solo iniciales"
                ),
                key="modo_marca_default_config",
            )

        guardado = st.form_submit_button("💾 Guardar configuración", type="primary", width="stretch")

    if guardado:
        objetivo_final = objetivo_custom.strip() or objetivo_sel
        marca_personal_modo_final = "foto" if modo_marca_sel == "📷 Con foto de perfil" else "texto"
        formato_post_defecto_final = "infografia" if formato_defecto_sel == opciones_formato_defecto[0] else "texto"
        estilo_infografia_final = "oscuro" if estilo_infografia_sel == opciones_estilo_cfg[0] else "claro"
        db.guardar_parametros(
            cuenta_id, tono, sector, longitud, usa_emojis, usa_hashtags, p["estilo_visual"], p["paleta_colores"],
            cta_habitual, objetivo_final, temas_habituales, audiencia_objetivo,
            palabras_clave, palabras_evitar, firma,
            incluir_marca_personal_default, marca_personal_modo_final,
            formato_post_defecto_final, infografia_paleta_defecto, int(infografia_num_items_defecto),
            estilo_infografia_final,
        )
        st.toast("Parámetros guardados.", icon="✅")
        st.rerun()


# =============================================================================
# Historial
# =============================================================================

elif pagina == "historial":
    posts = db.listar_posts(cuenta_id)

    if not posts:
        st.info("Todavía no has generado ninguna publicación.")
    else:
        color_estado = {"borrador": "gray", "editado": "orange", "publicado": "green"}
        filtro_h = st.segmented_control(
            "Filtrar", ["Todos", "Publicados", "Borradores"], default="Todos", key="filtro_hist",
        )
        if filtro_h == "Publicados":
            posts = [p for p in posts if p["estado"] == "publicado"]
        elif filtro_h == "Borradores":
            posts = [p for p in posts if p["estado"] != "publicado"]

        nombre_h = cuenta_actual.get("linkedin_nombre") or cuenta_actual.get("nombre") or "Tu nombre"
        conectado_h = bool(cuenta_actual.get("linkedin_access_token"))

        borradores_visibles = [p for p in posts if p["estado"] != "publicado"]
        ids_visibles = {p["id"] for p in borradores_visibles}
        if "hist_seleccion" not in st.session_state:
            st.session_state["hist_seleccion"] = set()
        # Nunca dejar seleccionado un id que ya no está en pantalla (filtrado, publicado o borrado).
        st.session_state["hist_seleccion"] &= ids_visibles

        if borradores_visibles:
            with st.container(border=True):
                st.markdown(f"**📝 Gestión de borradores** — {len(borradores_visibles)} esperando revisión")

                colsel1, colsel2 = st.columns(2)
                # Botones de una sola acción (no checkboxes con estado propio): así se puede
                # "preseeder" el estado de cada checkbox individual ANTES de crearlo más abajo,
                # sin pelear con el estado que Streamlit ya recuerda para cada uno por su key.
                if colsel1.button("☑️ Seleccionar todos", key="hist_btn_sel_todos", width="stretch"):
                    for pid in ids_visibles:
                        st.session_state[f"hist_sel_{pid}"] = True
                    st.session_state["hist_seleccion"] = set(ids_visibles)
                    st.rerun()
                if colsel2.button("⬜ Deseleccionar todos", key="hist_btn_desel_todos", width="stretch"):
                    for pid in ids_visibles:
                        st.session_state[f"hist_sel_{pid}"] = False
                    st.session_state["hist_seleccion"] = set()
                    st.rerun()

                n_sel = len(st.session_state["hist_seleccion"])
                colb1, colb2 = st.columns(2)
                if colb1.button(
                    f"📤 Publicar seleccionados ({n_sel})", type="primary", width="stretch",
                    disabled=not conectado_h or n_sel == 0, key="hist_publicar_sel",
                ):
                    ok, fallidos = 0, 0
                    for pid in list(st.session_state["hist_seleccion"]):
                        p_sel = db.obtener_post(pid)
                        if not p_sel or p_sel["estado"] == "publicado":
                            continue
                        try:
                            post_id_linkedin = linkedin_publish.publicar_post(
                                cuenta_id, p_sel["texto_generado"] or "", p_sel["imagen_url_o_path"] or None,
                            )
                            db.marcar_publicado(pid, post_id_linkedin)
                            ok += 1
                        except Exception:
                            fallidos += 1
                    st.session_state["hist_seleccion"] = set()
                    if fallidos:
                        st.warning(f"Publicados {ok} de {ok + fallidos} — {fallidos} con error (revísalos individualmente).")
                    else:
                        st.toast(f"¡{ok} borrador(es) publicado(s) en LinkedIn! 🎉", icon="✅")
                    st.rerun()

                confirmar_borrar_sel = colb2.checkbox(
                    f"Confirmo borrar los {n_sel} seleccionados", key="hist_confirmar_borrar_sel",
                    disabled=n_sel == 0,
                )
                if colb2.button(
                    f"🗑️ Borrar seleccionados ({n_sel})", width="stretch",
                    disabled=n_sel == 0 or not confirmar_borrar_sel, key="hist_borrar_sel",
                ):
                    for pid in list(st.session_state["hist_seleccion"]):
                        db.eliminar_post(pid)
                        st.session_state.pop(f"hist_sel_{pid}", None)
                    st.session_state["hist_seleccion"] = set()
                    st.session_state["hist_confirmar_borrar_sel"] = False
                    st.toast(f"{n_sel} borrador(es) eliminado(s).", icon="✅")
                    st.rerun()

                if not conectado_h:
                    st.caption("Conecta tu cuenta de LinkedIn (pestaña 🔗 LinkedIn) para poder publicar borradores.")

        if not posts:
            st.info(f"No hay publicaciones en «{filtro_h}».")

        for p in posts:
            with st.container(border=True):
                es_borrador = p["estado"] != "publicado"
                if es_borrador:
                    ccheck, cb, ct = st.columns([0.4, 1, 2.6])
                    seleccionado = ccheck.checkbox(
                        "Seleccionar", key=f"hist_sel_{p['id']}", label_visibility="collapsed",
                    )
                    if seleccionado:
                        st.session_state["hist_seleccion"].add(p["id"])
                    else:
                        st.session_state["hist_seleccion"].discard(p["id"])
                else:
                    cb, ct = st.columns([1, 3])
                cb.badge(p["estado"].capitalize(), color=color_estado.get(p["estado"], "gray"))
                ct.caption(p["fecha_creacion"][:16].replace("T", " "))
                st.markdown(f"**{html_lib.escape(p['tema'])}**")
                with st.expander("Ver publicación completa"):
                    render_preview_linkedin(nombre_h, "", p["texto_generado"] or "", p["imagen_url_o_path"])
                    if p["estado"] == "publicado":
                        st.caption(
                            f"Publicado el {p['fecha_publicacion'][:16].replace('T', ' ')} · "
                            f"LinkedIn ID: {p['post_id_linkedin']}"
                        )
                    else:
                        # Cubre los borradores creados fuera del flujo interactivo habitual
                        # (p. ej. por 📅 Generación diaria) — sin esto no había forma de
                        # publicarlos salvo desde la sesión de generación original.
                        cap, cad = st.columns(2)
                        if cap.button(
                            "✅ Aprobar y publicar", key=f"publicar_hist_{p['id']}",
                            disabled=not conectado_h, width="stretch",
                        ):
                            try:
                                post_id_linkedin = linkedin_publish.publicar_post(
                                    cuenta_id, p["texto_generado"] or "", p["imagen_url_o_path"] or None,
                                )
                                db.marcar_publicado(p["id"], post_id_linkedin)
                                st.toast("¡Publicado en LinkedIn! 🎉", icon="✅")
                                st.rerun()
                            except Exception as e:
                                _reportar_error("Error al publicar en LinkedIn", e)
                        key_confirmar_del = f"hist_confirmar_del_{p['id']}"
                        if st.session_state.get(key_confirmar_del):
                            if cad.button("⚠️ Confirmar borrado", key=f"hist_del_si_{p['id']}", width="stretch"):
                                db.eliminar_post(p["id"])
                                st.session_state["hist_seleccion"].discard(p["id"])
                                st.session_state.pop(f"hist_sel_{p['id']}", None)
                                st.session_state.pop(key_confirmar_del, None)
                                st.toast("Borrador descartado.", icon="✅")
                                st.rerun()
                        else:
                            if cad.button("❌ Denegar (borrar)", key=f"hist_del_{p['id']}", width="stretch"):
                                st.session_state[key_confirmar_del] = True
                                st.rerun()
                        if not conectado_h:
                            st.caption("Conecta tu cuenta de LinkedIn (pestaña 🔗 LinkedIn) para poder publicar.")


# =============================================================================
# Conectar LinkedIn
# =============================================================================

elif pagina == "linkedin":
    # Página pensada para USO NORMAL: solo conectar/desconectar la cuenta de
    # LinkedIn propia. Las credenciales de la app de LinkedIn (Client
    # ID/Secret) las configura quien administra esta instalación, en
    # 🛠️ Administración (solo visible con rol='admin') — aquí no se piden
    # ni se muestran.
    st.caption(
        "Usamos OAuth 2.0 oficial de LinkedIn. Nunca te pedimos tu usuario ni contraseña: "
        "autorizas la app desde la propia web de LinkedIn."
    )

    # El resultado de la autorización (éxito o error) lo dejó calculado el
    # bloque global de arriba, antes del gate de login (ver el comentario
    # ahí sobre por qué tiene que vivir fuera de esta página). Se muestra
    # una sola vez y se limpia, para que no reaparezca en cada rerun.
    if "login_ok_nombre" in st.session_state:
        st.toast(f"¡Conectado como {st.session_state.pop('login_ok_nombre')}!", icon="✅")
    if "login_error" in st.session_state:
        st.error(f"No se pudo completar la conexión con LinkedIn: {st.session_state.pop('login_error')}")

    conectado = bool(cuenta_actual.get("linkedin_access_token"))
    creds_linkedin = config.get_credentials()
    credenciales_listas = bool(creds_linkedin.linkedin_client_id and creds_linkedin.linkedin_client_secret)

    with st.container(border=True):
        if conectado:
            st.badge(f"Conectado como {cuenta_actual.get('linkedin_nombre') or 'LinkedIn'}", color="green", icon="✅")
            if not linkedin_oauth.token_valido(cuenta_actual):
                st.warning("El token ha expirado o está por expirar.")
                if cuenta_actual.get("linkedin_refresh_token") and st.button("🔄 Refrescar token"):
                    try:
                        data = linkedin_oauth.refrescar_token(cuenta_actual["linkedin_refresh_token"])
                        fecha_exp = (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
                        db.guardar_tokens_linkedin(
                            cuenta_id, data["access_token"],
                            data.get("refresh_token", cuenta_actual["linkedin_refresh_token"]), fecha_exp,
                        )
                        st.toast("Token refrescado.", icon="✅")
                        st.rerun()
                    except Exception as e:
                        _reportar_error("No se pudo refrescar el token de LinkedIn", e)
            if st.button("Desconectar cuenta"):
                db.desconectar_linkedin(cuenta_id)
                st.rerun()
        else:
            st.badge("No hay ninguna cuenta conectada", color="gray", icon="⚪")
            if not credenciales_listas:
                st.info(
                    "Esta app todavía no está lista para conectar LinkedIn. Pide a quien "
                    "administra esta instalación que termine de configurarla."
                )
            else:
                try:
                    state = linkedin_oauth.generar_state(cuenta_id)
                    url = linkedin_oauth.construir_url_autorizacion(state)
                    st.link_button("Conectar con LinkedIn →", url, type="primary", width="stretch")
                    st.caption(
                        "Se abrirá LinkedIn. Tras autorizar, LinkedIn te redirige de vuelta aquí "
                        "automáticamente y quedarás conectado."
                    )
                except Exception as e:
                    _reportar_error("No se pudo preparar la conexión con LinkedIn", e)
