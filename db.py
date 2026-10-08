"""
Capa de datos — SQLite local.

V5: modelo MULTIUSUARIO real. Cada persona tiene su propia cuenta (email +
contraseña), su propia conexión de LinkedIn, sus propios parámetros por
defecto, posts, inspiración, plan diario y temáticas automáticas. Las
credenciales de la INSTALACIÓN completa (Client ID/Secret de la app de
LinkedIn Developer, clave de API de Gemini) siguen siendo globales — las
comparten todas las cuentas, las configura quien administra la instalación
desde 🛠️ Administración, y viven en `config_global` (una sola fila).

Migración: si la base de datos viene de una versión anterior a V5 (una
sola tabla `usuarios` con una fila, uso personal — ver
`_migrar_a_multiusuario`), la primera vez que arranca esta versión se crea
automáticamente la primera cuenta (administrador), conservando su
contraseña y su conexión de LinkedIn ya existentes, y se le reasigna todo
lo que ya hubiera guardado (parámetros, posts, inspiración, plan diario).
Nunca se pierden datos ya guardados al actualizar la app.
"""

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from config import DB_PATH, INFOGRAFIA_PALETA_DEFECTO, INFOGRAFIA_PALETAS, hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    nombre TEXT NOT NULL DEFAULT '',
    rol TEXT NOT NULL DEFAULT 'usuario',        -- 'admin' / 'usuario'
    activo INTEGER NOT NULL DEFAULT 1,
    debe_cambiar_password INTEGER NOT NULL DEFAULT 0,
    fecha_creacion TEXT NOT NULL,
    -- conexión de LinkedIn propia de esta cuenta (cada persona conecta la suya)
    linkedin_access_token TEXT,
    linkedin_refresh_token TEXT,
    fecha_expiracion_token TEXT,
    linkedin_member_urn TEXT,
    linkedin_nombre TEXT
);

-- Credenciales de la INSTALACIÓN completa, compartidas por todas las
-- cuentas: la app de LinkedIn Developer (Client ID/Secret/Redirect URI) y
-- la clave de Gemini. Las configura quien administra la instalación, una
-- sola vez, desde 🛠️ Administración — nunca se piden por cuenta.
-- app_secret: token aleatorio generado la primera vez, usado para firmar
-- el "state" del login de LinkedIn (ver linkedin_oauth.py) y así saber a
-- qué cuenta pertenece un login sin depender de la sesión del navegador
-- (LinkedIn redirige de vuelta con una recarga completa de la página).
-- limite_diario_gemini: tope de generaciones/día POR MODELO que la propia
-- app se autoimpone para no arriesgarse a chocar con la cuota GRATUITA de
-- Gemini (que es de la instalación entera, no por cuenta, porque la clave
-- es compartida) — 0 significa "sin límite propio" (se apoya solo en los
-- 429 reales que devuelve Google, ver uso_gemini_diario más abajo).
-- uso_gemini_fecha/uso_gemini_contador: contador GLOBAL heredado de antes
-- de la V5.4 (cuando se asumía —incorrectamente— que la cuota gratuita de
-- Gemini era de todo el proyecto, no por modelo). Ya no se usan para nada
-- (ver uso_gemini_diario), se dejan solo para no romper una BD existente.
CREATE TABLE IF NOT EXISTS config_global (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    linkedin_client_id TEXT,
    linkedin_client_secret TEXT,
    linkedin_redirect_uri TEXT,
    gemini_api_key TEXT,
    app_secret TEXT,
    limite_diario_gemini INTEGER DEFAULT 0,
    uso_gemini_fecha TEXT,
    uso_gemini_contador INTEGER DEFAULT 0
);

-- V5.4: la cuota gratuita de Gemini es, en realidad, POR MODELO (el propio
-- error 429 de Google lo confirma: quotaId
-- "GenerateRequestsPerDayPerProjectPerModel-FreeTier", con el modelo como
-- una de las dimensiones) — no un cupo compartido de toda la instalación,
-- como se asumía hasta la V5.3. Esta tabla registra, por cada día y cada
-- modelo candidato (ver config.GEMINI_TEXT_MODEL_CANDIDATOS), cuántas
-- llamadas reales se han hecho y si Google ya devolvió un 429 de cuota
-- DIARIA para ese modelo hoy (columna `agotado`) — así, cuando un modelo se
-- agota, la app pasa automáticamente al siguiente candidato en vez de
-- rendirse (y no vuelve a intentar el que ya sabe agotado, ahorrando la
-- espera de un 429 innecesario). `limite_conocido` guarda el número real
-- que Google haya comunicado la última vez (el `quotaValue` del propio
-- error 429) — cuando no se conoce todavía, la interfaz usa una estimación
-- (ver config.GEMINI_LIMITE_ESTIMADO_POR_MODELO).
-- `clave_fingerprint` (huella corta de config.fingerprint_clave_gemini,
-- NUNCA la clave real) recuerda bajo qué clave de Gemini se registró el
-- conteo/agotamiento de esta fila. Si la clave activa cambia (🛠️
-- Administración), la fila queda "obsoleta para la clave nueva": se trata
-- como si hoy no se hubiera usado nada todavía con ella (vuelve a
-- intentarse de verdad, en vez de arrastrar un "agotado" que pertenecía a
-- la clave anterior) — ver db.uso_gemini_hoy_por_modelo.
CREATE TABLE IF NOT EXISTS uso_gemini_diario (
    fecha TEXT NOT NULL,
    modelo TEXT NOT NULL,
    contador INTEGER NOT NULL DEFAULT 0,
    agotado INTEGER NOT NULL DEFAULT 0,
    limite_conocido INTEGER,
    clave_fingerprint TEXT,
    PRIMARY KEY (fecha, modelo)
);

CREATE TABLE IF NOT EXISTS parametros_default (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER UNIQUE,
    tono TEXT DEFAULT 'profesional y cercano',
    sector TEXT DEFAULT '',
    longitud_preferida TEXT DEFAULT 'media',
    usa_emojis INTEGER DEFAULT 1,
    usa_hashtags INTEGER DEFAULT 1,
    estilo_visual TEXT DEFAULT 'ilustración digital minimalista',
    paleta_colores TEXT DEFAULT '',
    cta_habitual TEXT DEFAULT '',
    objetivo TEXT DEFAULT '',
    temas_habituales TEXT DEFAULT '',
    audiencia_objetivo TEXT DEFAULT '',
    palabras_clave TEXT DEFAULT '',
    palabras_evitar TEXT DEFAULT '',
    firma TEXT DEFAULT '',
    foto_perfil_path TEXT,
    incluir_marca_personal_default INTEGER DEFAULT 0,
    marca_personal_modo_default TEXT DEFAULT 'foto',
    formato_post_defecto TEXT DEFAULT 'infografia',
    infografia_paleta_defecto TEXT DEFAULT 'Azul corporativo',
    infografia_num_items_defecto INTEGER DEFAULT 8,
    infografia_estilo_defecto TEXT DEFAULT 'oscuro',
    reparto_diario_infografia INTEGER DEFAULT 1,
    reparto_diario_texto INTEGER DEFAULT 2,
    automatizacion_total_activa INTEGER DEFAULT 0,
    automatizacion_auto_publicar INTEGER DEFAULT 0,
    automatizacion_hora TEXT DEFAULT '09:00',
    tema_ui_defecto TEXT DEFAULT 'claro',
    tema_rotacion_indice INTEGER DEFAULT 0
);

-- Lista de temáticas que rotan solas en la generación automática (📅
-- Generación diaria / 🤖 Automatización Total) — ver db.siguiente_tema_rotacion.
-- Si una cuenta no tiene ninguna temática activa, la generación automática
-- sigue dejando que la IA proponga un tema libre, como siempre.
CREATE TABLE IF NOT EXISTS temas_automaticos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);

-- Paletas de color personalizadas para la infografía, creadas por el
-- usuario a partir de solo dos colores (primario + acento) — el resto de
-- tonos (fondo, tarjeta, texto...) se derivan automáticamente, igual que
-- en las paletas predefinidas de config.INFOGRAFIA_PALETAS (ver
-- image_infografia._paleta_clara / _paleta_oscura). Se seleccionan en la UI
-- junto con las predefinidas, distinguibles por el valor 'custom:<id>'
-- (ver db.resolver_paleta_infografia).
CREATE TABLE IF NOT EXISTS paletas_personalizadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    primario TEXT NOT NULL,
    acento TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generacion_diaria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER,
    fecha TEXT NOT NULL,              -- 'YYYY-MM-DD'
    tipo TEXT NOT NULL,               -- 'infografia' / 'texto'
    estado TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente / generado / publicado / error
    post_id INTEGER,
    error TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);

CREATE TABLE IF NOT EXISTS inspiracion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER,
    texto_original TEXT NOT NULL DEFAULT '',
    notas TEXT,
    imagen_path TEXT,
    favorito INTEGER DEFAULT 0,
    fecha_agregado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts_generados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER,
    tema TEXT NOT NULL,
    texto_generado TEXT,
    imagen_url_o_path TEXT,
    estado TEXT DEFAULT 'borrador',  -- borrador / editado / publicado
    fecha_creacion TEXT NOT NULL,
    fecha_publicacion TEXT,
    post_id_linkedin TEXT
);
"""

# Columnas que pueden faltar en una BD creada por una versión anterior de la
# app. Cada entrada es (tabla, columna, fragmento_ddl_para_ALTER_TABLE).
# Nota: parametros_default llega aquí ya reconstruida sin la restricción
# CHECK(id=1) vieja (ver _quitar_check_singleton), así que en la práctica
# ya trae cuenta_id — estas dos entradas son solo una red de seguridad.
COLUMNAS_NUEVAS = [
    ("parametros_default", "cuenta_id", "INTEGER"),
    ("parametros_default", "tema_rotacion_indice", "INTEGER DEFAULT 0"),
    ("parametros_default", "infografia_estilo_defecto", "TEXT DEFAULT 'oscuro'"),
    ("parametros_default", "automatizacion_hora", "TEXT DEFAULT '09:00'"),
    ("generacion_diaria", "cuenta_id", "INTEGER"),
    ("inspiracion", "cuenta_id", "INTEGER"),
    ("posts_generados", "cuenta_id", "INTEGER"),
    ("config_global", "app_secret", "TEXT"),
    ("config_global", "limite_diario_gemini", "INTEGER DEFAULT 0"),
    ("config_global", "uso_gemini_fecha", "TEXT"),
    ("config_global", "uso_gemini_contador", "INTEGER DEFAULT 0"),
    ("uso_gemini_diario", "clave_fingerprint", "TEXT"),
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _tabla_existe(conn, nombre: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
    ).fetchone() is not None


def _migrar_columnas_nuevas(conn):
    for tabla, columna, ddl in COLUMNAS_NUEVAS:
        if not _tabla_existe(conn, tabla):
            continue
        existentes = {fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})")}
        if columna not in existentes:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")


def _quitar_check_singleton(conn, tabla: str):
    """Reconstruye `tabla` sin la restricción CHECK(id=1) heredada de
    versiones anteriores a V5 (donde solo existía una fila, uso personal) —
    necesario para parametros_default, que en el modelo multiusuario pasa a
    tener una fila POR CUENTA. No hace nada si la tabla ya tiene el esquema
    nuevo (instalación nueva, o ya migrada antes): lo detecta mirando si el
    SQL con el que se creó la tabla contiene "CHECK"."""
    fila_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
    ).fetchone()
    if not fila_sql or not fila_sql[0] or "CHECK" not in fila_sql[0].upper():
        return

    columnas_viejas = [f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")]
    conn.execute(f"ALTER TABLE {tabla} RENAME TO {tabla}_viejo_v1")
    conn.executescript(SCHEMA)  # recrea `tabla` con el esquema nuevo (sin CHECK, con cuenta_id)
    columnas_str = ", ".join(columnas_viejas)
    conn.execute(f"INSERT INTO {tabla} ({columnas_str}) SELECT {columnas_str} FROM {tabla}_viejo_v1")
    conn.execute(f"DROP TABLE {tabla}_viejo_v1")


def _migrar_a_multiusuario(conn):
    """Migra una base de datos de antes de V5 (usuario único, fila id=1 en
    `usuarios`) al modelo multiusuario: crea la primera cuenta
    (administrador) conservando su contraseña y su conexión de LinkedIn ya
    existentes, mueve las credenciales de la instalación a `config_global`,
    y reasigna a esa cuenta todo lo que ya hubiera guardado (parámetros,
    posts, inspiración, plan diario). Se ejecuta como mucho una vez por
    instalación — hecho esto, `usuarios` se renombra y deja de usarse (no
    se borra: es una red de seguridad, nunca se destruyen datos)."""
    if not _tabla_existe(conn, "usuarios"):
        return  # instalación nueva, o ya migrada antes: nada que hacer

    fila = conn.execute("SELECT * FROM usuarios WHERE id=1").fetchone()
    fila = dict(fila) if fila else {}

    conn.execute(
        """INSERT OR IGNORE INTO config_global (id, linkedin_client_id, linkedin_client_secret,
           linkedin_redirect_uri, gemini_api_key) VALUES (1, ?, ?, ?, ?)""",
        (fila.get("linkedin_client_id"), fila.get("linkedin_client_secret"),
         fila.get("linkedin_redirect_uri"), fila.get("gemini_api_key")),
    )

    if fila.get("admin_password_hash") and fila.get("admin_password_salt"):
        pw_hash, pw_salt, debe_cambiar = fila["admin_password_hash"], fila["admin_password_salt"], 0
    else:
        # Instalación anterior que nunca llegó a tener una contraseña de
        # administrador configurada (solo se usó vía variables de entorno).
        # Se crea la cuenta igualmente, con una contraseña temporal
        # conocida, para no dejar huérfanos los posts/inspiración que ya
        # hubiera guardados — se fuerza a cambiarla en el primer login.
        pw_hash, pw_salt = hash_password("cambiar123")
        debe_cambiar = 1

    ahora = datetime.utcnow().isoformat()
    cur = conn.execute(
        """INSERT INTO cuentas (email, password_hash, password_salt, nombre, rol, activo,
           debe_cambiar_password, fecha_creacion, linkedin_access_token, linkedin_refresh_token,
           fecha_expiracion_token, linkedin_member_urn, linkedin_nombre)
           VALUES (?, ?, ?, ?, 'admin', 1, ?, ?, ?, ?, ?, ?, ?)""",
        ("admin@local", pw_hash, pw_salt, fila.get("linkedin_nombre") or "Administrador", debe_cambiar,
         ahora, fila.get("linkedin_access_token"), fila.get("linkedin_refresh_token"),
         fila.get("fecha_expiracion_token"), fila.get("linkedin_member_urn"), fila.get("linkedin_nombre")),
    )
    cuenta_id = cur.lastrowid
    for tabla in ("parametros_default", "posts_generados", "generacion_diaria", "inspiracion"):
        conn.execute(f"UPDATE {tabla} SET cuenta_id=? WHERE cuenta_id IS NULL", (cuenta_id,))

    conn.execute("ALTER TABLE usuarios RENAME TO usuarios_legado_v1")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _quitar_check_singleton(conn, "parametros_default")
        _migrar_columnas_nuevas(conn)
        _migrar_a_multiusuario(conn)
        conn.execute("INSERT OR IGNORE INTO config_global (id) VALUES (1)")


# ---------- cuentas ----------

def crear_cuenta(email: str, password_hash: str, password_salt: str, nombre: str = "",
                  rol: str = "usuario", debe_cambiar_password: bool = False) -> int:
    """Crea una cuenta nueva y, en la misma operación, su fila de
    parámetros por defecto (toda cuenta tiene siempre una, lista para
    usarse sin pasos adicionales)."""
    ahora = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO cuentas (email, password_hash, password_salt, nombre, rol, activo,
               debe_cambiar_password, fecha_creacion) VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (email.strip().lower(), password_hash, password_salt, (nombre or "").strip(), rol,
             int(debe_cambiar_password), ahora),
        )
        cuenta_id = cur.lastrowid
        conn.execute("INSERT INTO parametros_default (cuenta_id) VALUES (?)", (cuenta_id,))
        return cuenta_id


def obtener_cuenta(cuenta_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
        return dict(row) if row else None


def obtener_cuenta_por_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cuentas WHERE email=?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def listar_cuentas() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cuentas ORDER BY fecha_creacion").fetchall()
        return [dict(r) for r in rows]


def actualizar_cuenta(cuenta_id: int, nombre=None, rol=None, activo=None):
    campos, valores = [], []
    if nombre is not None:
        campos.append("nombre=?")
        valores.append(nombre.strip())
    if rol is not None:
        campos.append("rol=?")
        valores.append(rol)
    if activo is not None:
        campos.append("activo=?")
        valores.append(int(activo))
    if not campos:
        return
    valores.append(cuenta_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE cuentas SET {', '.join(campos)} WHERE id=?", valores)


def cambiar_password_cuenta(cuenta_id: int, password_hash: str, password_salt: str,
                             debe_cambiar_password: bool = False):
    with get_conn() as conn:
        conn.execute(
            "UPDATE cuentas SET password_hash=?, password_salt=?, debe_cambiar_password=? WHERE id=?",
            (password_hash, password_salt, int(debe_cambiar_password), cuenta_id),
        )


def eliminar_cuenta_y_datos(cuenta_id: int):
    """Borra la cuenta y TODOS sus datos (parámetros, posts, plan diario,
    inspiración, temáticas). Sin confirmación aquí — la confirma quien
    llama (🛠️ Administración) antes de invocar esta función; no hay forma
    de deshacerlo."""
    with get_conn() as conn:
        for tabla in ("parametros_default", "posts_generados", "generacion_diaria", "inspiracion", "temas_automaticos"):
            conn.execute(f"DELETE FROM {tabla} WHERE cuenta_id=?", (cuenta_id,))
        conn.execute("DELETE FROM cuentas WHERE id=?", (cuenta_id,))


# ---------- LinkedIn (por cuenta) ----------

def guardar_tokens_linkedin(cuenta_id: int, access_token, refresh_token, fecha_expiracion,
                             member_urn=None, nombre=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE cuentas SET linkedin_access_token=?, linkedin_refresh_token=?,
               fecha_expiracion_token=?, linkedin_member_urn=COALESCE(?, linkedin_member_urn),
               linkedin_nombre=COALESCE(?, linkedin_nombre) WHERE id=?""",
            (access_token, refresh_token, fecha_expiracion, member_urn, nombre, cuenta_id),
        )


def desconectar_linkedin(cuenta_id: int):
    with get_conn() as conn:
        conn.execute(
            """UPDATE cuentas SET linkedin_access_token=NULL, linkedin_refresh_token=NULL,
               fecha_expiracion_token=NULL, linkedin_member_urn=NULL, linkedin_nombre=NULL WHERE id=?""",
            (cuenta_id,),
        )


# ---------- config_global (credenciales de la instalación) ----------

def obtener_config_global() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM config_global WHERE id=1").fetchone()
        return dict(row) if row else {}


def guardar_credenciales_linkedin_global(client_id: str, client_secret: str, redirect_uri: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE config_global SET linkedin_client_id=?, linkedin_client_secret=?,
               linkedin_redirect_uri=? WHERE id=1""",
            (client_id.strip() or None, client_secret.strip() or None, redirect_uri.strip() or None),
        )


def eliminar_credenciales_linkedin_global():
    with get_conn() as conn:
        conn.execute(
            """UPDATE config_global SET linkedin_client_id=NULL, linkedin_client_secret=NULL,
               linkedin_redirect_uri=NULL WHERE id=1"""
        )


def guardar_gemini_api_key_global(clave: str):
    with get_conn() as conn:
        conn.execute("UPDATE config_global SET gemini_api_key=? WHERE id=1", (clave.strip() or None,))


def eliminar_gemini_api_key_global():
    with get_conn() as conn:
        conn.execute("UPDATE config_global SET gemini_api_key=NULL WHERE id=1")


def obtener_limite_diario_gemini() -> int:
    """Tope de generaciones/día POR MODELO que la propia app se autoimpone
    (0 = sin límite propio, solo se frena con los 429 reales de Google —
    ver `uso_gemini_hoy_por_modelo`). Es de la INSTALACIÓN entera, no por
    cuenta, porque la clave de Gemini es compartida por todas las cuentas."""
    with get_conn() as conn:
        row = conn.execute("SELECT limite_diario_gemini FROM config_global WHERE id=1").fetchone()
        return int(row["limite_diario_gemini"] or 0) if row else 0


def guardar_limite_diario_gemini(limite: int):
    with get_conn() as conn:
        conn.execute("UPDATE config_global SET limite_diario_gemini=? WHERE id=1", (max(0, int(limite)),))


def _fila_pertenece_a_la_clave_activa(fila_fingerprint, clave_fingerprint: str) -> bool:
    """True si el estado guardado en esta fila de `uso_gemini_diario` sigue
    siendo válido para la clave de Gemini ACTUALMENTE activa. Una fila sin
    huella guardada (BD de antes de esta función, o `clave_fingerprint=""`
    porque no había ninguna clave configurada cuando se registró) siempre
    se trata como válida — nunca se descarta un dato real por no poder
    comparar. Solo se considera "de otra clave" cuando AMBAS huellas están
    presentes y son distintas."""
    fila_fingerprint = fila_fingerprint or ""
    if not fila_fingerprint or not clave_fingerprint:
        return True
    return fila_fingerprint == clave_fingerprint


def uso_gemini_hoy_por_modelo(clave_fingerprint: str = "") -> dict[str, dict]:
    """{modelo: {"usados": int, "agotado": bool, "limite_conocido": int|None}}
    de HOY, para los modelos que ya se hayan usado o marcado agotados hoy
    (un modelo todavía no usado hoy simplemente no aparece en el dict —
    quien llama lo trata como 0 usos / no agotado).

    `clave_fingerprint` (ver config.fingerprint_clave_gemini) es la huella
    de la clave de Gemini ACTUALMENTE activa. Una fila registrada bajo una
    clave distinta a la actual se omite del resultado a propósito — así,
    si alguien cambia de clave desde 🛠️ Administración, esos modelos vuelven
    a aparecer como "sin usar hoy" para la clave nueva, en vez de arrastrar
    un "agotado" que en realidad pertenece a la clave anterior."""
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        filas = conn.execute(
            "SELECT modelo, contador, agotado, limite_conocido, clave_fingerprint "
            "FROM uso_gemini_diario WHERE fecha=?",
            (hoy_str,),
        ).fetchall()
        return {
            f["modelo"]: {
                "usados": int(f["contador"] or 0),
                "agotado": bool(f["agotado"]),
                "limite_conocido": int(f["limite_conocido"]) if f["limite_conocido"] else None,
            }
            for f in filas
            if _fila_pertenece_a_la_clave_activa(f["clave_fingerprint"], clave_fingerprint)
        }


def registrar_uso_gemini(modelo: str, clave_fingerprint: str = "") -> int:
    """Registra UNA llamada real a la API de Gemini hecha en este instante
    para `modelo` (se cuente como éxito o como fallo — ambas gastan cuota
    igual). Devuelve el contador de HOY para ese modelo ya actualizado.

    Si la fila de hoy para este modelo pertenece a una clave distinta a
    `clave_fingerprint` (ver `_fila_pertenece_a_la_clave_activa`), el
    contador arranca de cero para la clave nueva en vez de seguir sumando
    sobre el conteo de la clave anterior — cada clave lleva su propia
    cuenta, aunque compartan fila en la tabla."""
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        fila = conn.execute(
            "SELECT contador, clave_fingerprint FROM uso_gemini_diario WHERE fecha=? AND modelo=?",
            (hoy_str, modelo),
        ).fetchone()
        if fila is not None and not _fila_pertenece_a_la_clave_activa(fila["clave_fingerprint"], clave_fingerprint):
            conn.execute(
                """UPDATE uso_gemini_diario SET contador=1, agotado=0, limite_conocido=NULL,
                   clave_fingerprint=? WHERE fecha=? AND modelo=?""",
                (clave_fingerprint, hoy_str, modelo),
            )
            return 1
        conn.execute(
            """INSERT INTO uso_gemini_diario (fecha, modelo, contador, agotado, clave_fingerprint)
               VALUES (?, ?, 1, 0, ?)
               ON CONFLICT(fecha, modelo) DO UPDATE SET
                   contador = contador + 1,
                   clave_fingerprint = COALESCE(NULLIF(excluded.clave_fingerprint, ''), uso_gemini_diario.clave_fingerprint)""",
            (hoy_str, modelo, clave_fingerprint),
        )
        row = conn.execute(
            "SELECT contador FROM uso_gemini_diario WHERE fecha=? AND modelo=?", (hoy_str, modelo)
        ).fetchone()
        return int(row["contador"]) if row else 1


def marcar_gemini_agotado(modelo: str, limite_real: int | None = None, clave_fingerprint: str = ""):
    """Marca `modelo` como agotado HOY (Google ya devolvió un 429 de cuota
    DIARIA para él) — para que la app deje de intentarlo el resto del día y
    pase directa al siguiente candidato. Si Google comunicó el cupo real
    en el propio error (`limite_real`), se guarda para mostrarlo en la
    interfaz en vez de una estimación. Guarda también `clave_fingerprint`:
    este agotamiento es válido para ESA clave, no para cualquier otra que
    se configure después."""
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO uso_gemini_diario (fecha, modelo, contador, agotado, limite_conocido, clave_fingerprint)
               VALUES (?, ?, 0, 1, ?, ?)
               ON CONFLICT(fecha, modelo) DO UPDATE SET
                   agotado = 1,
                   limite_conocido = COALESCE(excluded.limite_conocido, uso_gemini_diario.limite_conocido),
                   clave_fingerprint = excluded.clave_fingerprint""",
            (hoy_str, modelo, limite_real, clave_fingerprint),
        )


def modelo_gemini_agotado_hoy(modelo: str, clave_fingerprint: str = "") -> bool:
    """Consulta rápida (sin registrar nada) usada ANTES de intentar un
    modelo — si ya sabemos que se agotó hoy CON ESTA CLAVE, ni se llama a
    la API."""
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT agotado, clave_fingerprint FROM uso_gemini_diario WHERE fecha=? AND modelo=?",
            (hoy_str, modelo),
        ).fetchone()
        if not row or not _fila_pertenece_a_la_clave_activa(row["clave_fingerprint"], clave_fingerprint):
            return False
        return bool(row["agotado"])


def obtener_o_crear_app_secret() -> str:
    """Token aleatorio de la instalación, generado una sola vez, usado para
    firmar (HMAC) el "state" del login de LinkedIn — ver linkedin_oauth.py."""
    with get_conn() as conn:
        row = conn.execute("SELECT app_secret FROM config_global WHERE id=1").fetchone()
        if row and row["app_secret"]:
            return row["app_secret"]
        nuevo = secrets.token_hex(32)
        conn.execute("UPDATE config_global SET app_secret=? WHERE id=1", (nuevo,))
        return nuevo


# ---------- parametros_default (por cuenta) ----------

def obtener_parametros(cuenta_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM parametros_default WHERE cuenta_id=?", (cuenta_id,)).fetchone()
        return dict(row) if row else None


def guardar_parametros(cuenta_id, tono, sector, longitud_preferida, usa_emojis, usa_hashtags,
                        estilo_visual, paleta_colores, cta_habitual, objetivo="",
                        temas_habituales="", audiencia_objetivo="", palabras_clave="",
                        palabras_evitar="", firma="", incluir_marca_personal_default=False,
                        marca_personal_modo_default="foto", formato_post_defecto="infografia",
                        infografia_paleta_defecto="Azul corporativo", infografia_num_items_defecto=8,
                        infografia_estilo_defecto="oscuro"):
    with get_conn() as conn:
        conn.execute(
            """UPDATE parametros_default SET tono=?, sector=?, longitud_preferida=?,
               usa_emojis=?, usa_hashtags=?, estilo_visual=?, paleta_colores=?, cta_habitual=?,
               objetivo=?, temas_habituales=?, audiencia_objetivo=?, palabras_clave=?,
               palabras_evitar=?, firma=?, incluir_marca_personal_default=?, marca_personal_modo_default=?,
               formato_post_defecto=?, infografia_paleta_defecto=?, infografia_num_items_defecto=?,
               infografia_estilo_defecto=?
               WHERE cuenta_id=?""",
            (tono, sector, longitud_preferida, int(usa_emojis), int(usa_hashtags),
             estilo_visual, paleta_colores, cta_habitual, objetivo, temas_habituales,
             audiencia_objetivo, palabras_clave, palabras_evitar, firma,
             int(incluir_marca_personal_default), marca_personal_modo_default,
             formato_post_defecto, infografia_paleta_defecto, int(infografia_num_items_defecto),
             infografia_estilo_defecto, cuenta_id),
        )


def guardar_reparto_diario(cuenta_id: int, n_infografia: int, n_texto: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE parametros_default SET reparto_diario_infografia=?, reparto_diario_texto=? WHERE cuenta_id=?",
            (int(n_infografia), int(n_texto), cuenta_id),
        )


def guardar_automatizacion(cuenta_id: int, activa: bool, auto_publicar: bool, hora: str = "09:00"):
    with get_conn() as conn:
        conn.execute(
            """UPDATE parametros_default SET automatizacion_total_activa=?, automatizacion_auto_publicar=?,
               automatizacion_hora=? WHERE cuenta_id=?""",
            (int(activa), int(auto_publicar), (hora or "09:00").strip(), cuenta_id),
        )


def guardar_tema_ui(cuenta_id: int, valor: str):
    with get_conn() as conn:
        conn.execute("UPDATE parametros_default SET tema_ui_defecto=? WHERE cuenta_id=?", (valor, cuenta_id))


def guardar_foto_perfil(cuenta_id: int, ruta: str):
    with get_conn() as conn:
        conn.execute("UPDATE parametros_default SET foto_perfil_path=? WHERE cuenta_id=?", (ruta, cuenta_id))


def eliminar_foto_perfil(cuenta_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE parametros_default SET foto_perfil_path=NULL WHERE cuenta_id=?", (cuenta_id,))


# ---------- temas_automaticos (temáticas rotativas, por cuenta) ----------

def listar_temas(cuenta_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM temas_automaticos WHERE cuenta_id=? ORDER BY orden, id", (cuenta_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def agregar_tema(cuenta_id: int, nombre: str) -> int:
    with get_conn() as conn:
        siguiente_orden = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 FROM temas_automaticos WHERE cuenta_id=?", (cuenta_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO temas_automaticos (cuenta_id, nombre, activo, orden, creado_en) VALUES (?, ?, 1, ?, ?)",
            (cuenta_id, nombre.strip(), siguiente_orden, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def eliminar_tema(id_: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM temas_automaticos WHERE id=?", (id_,))


def activar_tema(id_: int, activo: bool):
    with get_conn() as conn:
        conn.execute("UPDATE temas_automaticos SET activo=? WHERE id=?", (int(activo), id_))


def siguiente_tema_rotacion(cuenta_id: int) -> str | None:
    """Devuelve la siguiente temática activa de la cuenta, rotando en orden
    (round-robin) y avanzando el índice guardado en parametros_default —
    así "día 1 -> Python, día 2 -> Seguridad, día 3 -> Cloud" no depende
    del día de la semana ni de cuántos posts se generen cada día, solo de
    cuántas veces se ha llamado ya. Devuelve None si la cuenta no tiene
    ninguna temática activa configurada — en ese caso, quien llama
    (daily.py) debe seguir dejando que la IA proponga un tema libre, como
    hacía siempre por defecto."""
    with get_conn() as conn:
        temas = conn.execute(
            "SELECT nombre FROM temas_automaticos WHERE cuenta_id=? AND activo=1 ORDER BY orden, id",
            (cuenta_id,),
        ).fetchall()
        if not temas:
            return None
        nombres = [t["nombre"] for t in temas]
        fila = conn.execute(
            "SELECT tema_rotacion_indice FROM parametros_default WHERE cuenta_id=?", (cuenta_id,)
        ).fetchone()
        indice = (fila["tema_rotacion_indice"] if fila else 0) or 0
        tema = nombres[indice % len(nombres)]
        conn.execute(
            "UPDATE parametros_default SET tema_rotacion_indice=? WHERE cuenta_id=?", (indice + 1, cuenta_id)
        )
        return tema


# ---------- paletas personalizadas de la infografía (por cuenta) ----------

def listar_paletas_personalizadas(cuenta_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM paletas_personalizadas WHERE cuenta_id=? ORDER BY id", (cuenta_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def obtener_paleta_personalizada(id_: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM paletas_personalizadas WHERE id=?", (id_,)).fetchone()
        return dict(row) if row else None


def crear_paleta_personalizada(cuenta_id: int, nombre: str, primario: str, acento: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO paletas_personalizadas (cuenta_id, nombre, primario, acento, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (cuenta_id, nombre.strip() or "Mi paleta", primario, acento, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def eliminar_paleta_personalizada(id_: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM paletas_personalizadas WHERE id=?", (id_,))


def valor_selector_paleta(paleta_personalizada_id: int) -> str:
    """Valor único usado en los selectores de paleta de la UI para distinguir
    una paleta personalizada ('custom:<id>') de una predefinida (que se
    identifica por su propio nombre, p. ej. 'Azul corporativo')."""
    return f"custom:{paleta_personalizada_id}"


def resolver_paleta_infografia(cuenta_id: int, valor: str | None) -> dict:
    """Traduce el valor elegido en un selector de paleta (nombre de preset,
    o 'custom:<id>' de una paleta personalizada) al diccionario de colores
    que espera `image_infografia.generar_infografia`. Si `valor` no es
    reconocible (paleta personalizada borrada, o de otra cuenta) cae de
    vuelta a la paleta predefinida por defecto — nunca lanza."""
    if valor and valor.startswith("custom:"):
        try:
            paleta_id = int(valor.split(":", 1)[1])
        except ValueError:
            paleta_id = None
        fila = obtener_paleta_personalizada(paleta_id) if paleta_id else None
        if fila and fila["cuenta_id"] == cuenta_id:
            return {"primario": fila["primario"], "acento": fila["acento"]}
        return INFOGRAFIA_PALETAS[INFOGRAFIA_PALETA_DEFECTO]
    return INFOGRAFIA_PALETAS.get(valor, INFOGRAFIA_PALETAS[INFOGRAFIA_PALETA_DEFECTO])


# ---------- inspiracion (por cuenta) ----------
#
# Nota de confianza: las operaciones por id (notas/favorito/eliminar) no
# comprueban explícitamente que el id pertenezca a la cuenta que llama —
# como el listado SIEMPRE se filtra por cuenta_id, en la práctica nadie ve
# ni puede pulsar un botón sobre un id que no sea suyo. Nivel de confianza
# razonable para un equipo pequeño de colegas, no para un SaaS expuesto a
# desconocidos.

def agregar_inspiracion(cuenta_id: int, texto_original="", notas="", imagen_path=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO inspiracion (cuenta_id, texto_original, notas, imagen_path, fecha_agregado)
               VALUES (?, ?, ?, ?, ?)""",
            (cuenta_id, texto_original or "", notas or "", imagen_path, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def actualizar_notas_inspiracion(id_, notas):
    with get_conn() as conn:
        conn.execute("UPDATE inspiracion SET notas=? WHERE id=?", (notas, id_))


def listar_inspiracion(cuenta_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inspiracion WHERE cuenta_id=? ORDER BY favorito DESC, fecha_agregado DESC",
            (cuenta_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def marcar_favorito_inspiracion(id_, favorito: bool):
    with get_conn() as conn:
        conn.execute("UPDATE inspiracion SET favorito=? WHERE id=?", (int(favorito), id_))


def eliminar_inspiracion(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM inspiracion WHERE id=?", (id_,))


# ---------- posts_generados (por cuenta) ----------

def crear_post(cuenta_id: int, tema, texto_generado="", imagen_url_o_path=""):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO posts_generados (cuenta_id, tema, texto_generado, imagen_url_o_path, estado, fecha_creacion)
               VALUES (?, ?, ?, ?, 'borrador', ?)""",
            (cuenta_id, tema, texto_generado, imagen_url_o_path, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def actualizar_post(id_, texto_generado=None, imagen_url_o_path=None, estado=None):
    campos, valores = [], []
    if texto_generado is not None:
        campos.append("texto_generado=?")
        valores.append(texto_generado)
    if imagen_url_o_path is not None:
        campos.append("imagen_url_o_path=?")
        valores.append(imagen_url_o_path)
    if estado is not None:
        campos.append("estado=?")
        valores.append(estado)
    if not campos:
        return
    valores.append(id_)
    with get_conn() as conn:
        conn.execute(f"UPDATE posts_generados SET {', '.join(campos)} WHERE id=?", valores)


def marcar_publicado(id_, post_id_linkedin):
    with get_conn() as conn:
        conn.execute(
            """UPDATE posts_generados SET estado='publicado', post_id_linkedin=?,
               fecha_publicacion=? WHERE id=?""",
            (post_id_linkedin, datetime.utcnow().isoformat(), id_),
        )


def existe_publicado_reciente(cuenta_id: int, texto: str, horas: int = 24) -> bool:
    """True si esta cuenta YA tiene un post PUBLICADO con este mismo texto
    (comparación exacta) en las últimas `horas` — red de seguridad para
    nunca publicar el mismo contenido dos veces en LinkedIn, sea cual sea
    la causa (p. ej. un reintento tras un fallo de red que en realidad sí
    llegó a publicarse, o una generación duplicada). Comparar por texto
    exacto es deliberado: dos posts DISTINTOS pueden compartir tema sin
    compartir ni una palabra, así que solo el texto es una señal fiable de
    que es literalmente el mismo contenido, no solo el mismo asunto."""
    if not (texto or "").strip():
        return False
    limite = (datetime.utcnow() - timedelta(hours=horas)).isoformat()
    with get_conn() as conn:
        fila = conn.execute(
            """SELECT 1 FROM posts_generados
               WHERE cuenta_id=? AND estado='publicado' AND texto_generado=? AND fecha_publicacion >= ?
               LIMIT 1""",
            (cuenta_id, texto, limite),
        ).fetchone()
        return fila is not None


def listar_posts(cuenta_id: int, limit=50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts_generados WHERE cuenta_id=? ORDER BY fecha_creacion DESC LIMIT ?",
            (cuenta_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def obtener_post(id_):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM posts_generados WHERE id=?", (id_,)).fetchone()
        return dict(row) if row else None


def eliminar_post(id_):
    """Borra un post (normalmente un borrador que se deniega/descarta desde
    🗂️ Historial). También limpia la referencia en `generacion_diaria` si
    ese post venía del plan diario, para no dejar un post_id colgando
    apuntando a una fila ya borrada."""
    with get_conn() as conn:
        conn.execute("UPDATE generacion_diaria SET post_id=NULL WHERE post_id=?", (id_,))
        conn.execute("DELETE FROM posts_generados WHERE id=?", (id_,))


# ---------- generación diaria (plan + automatización, por cuenta) ----------

def listar_plan_dia(cuenta_id: int, fecha: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generacion_diaria WHERE cuenta_id=? AND fecha=? ORDER BY id", (cuenta_id, fecha)
        ).fetchall()
        return [dict(r) for r in rows]


def crear_items_plan_dia(cuenta_id: int, fecha: str, tipo: str, cantidad: int):
    """Añade `cantidad` items 'pendiente' de `tipo` ('infografia'/'texto') al
    plan de `fecha` de esta cuenta. No comprueba duplicados — quien llama
    (`daily.py`) debe asegurarse antes de no crear un plan dos veces para
    el mismo día."""
    ahora = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO generacion_diaria (cuenta_id, fecha, tipo, estado, creado_en)
               VALUES (?, ?, ?, 'pendiente', ?)""",
            [(cuenta_id, fecha, tipo, ahora) for _ in range(max(int(cantidad), 0))],
        )


def eliminar_items_plan_dia(ids: list[int]):
    """Quita items concretos del plan diario (por id). Usado solo al
    resincronizar el plan de hoy tras cambiar el reparto — el llamador
    (`daily.resincronizar_plan_hoy`) ya se asegura de pasar únicamente ids
    de items en estado 'pendiente', nunca de items ya generados/publicados/
    con error."""
    if not ids:
        return
    with get_conn() as conn:
        marcadores = ", ".join("?" for _ in ids)
        conn.execute(f"DELETE FROM generacion_diaria WHERE id IN ({marcadores})", ids)


def actualizar_item_plan_dia(id_, estado=None, post_id=None, error=None):
    campos, valores = [], []
    if estado is not None:
        campos.append("estado=?")
        valores.append(estado)
    if post_id is not None:
        campos.append("post_id=?")
        valores.append(post_id)
    if error is not None:
        campos.append("error=?")
        valores.append(error)
    if not campos:
        return
    campos.append("actualizado_en=?")
    valores.append(datetime.utcnow().isoformat())
    valores.append(id_)
    with get_conn() as conn:
        conn.execute(f"UPDATE generacion_diaria SET {', '.join(campos)} WHERE id=?", valores)


def listar_plan_reciente(cuenta_id: int, dias: int = 14) -> list[dict]:
    """Historial reciente del plan diario de esta cuenta (todas las fechas,
    más nuevo primero) — útil para revisar qué hizo la automatización total
    sin supervisión."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generacion_diaria WHERE cuenta_id=? ORDER BY fecha DESC, id DESC LIMIT ?",
            (cuenta_id, dias * 10),
        ).fetchall()
        return [dict(r) for r in rows]
