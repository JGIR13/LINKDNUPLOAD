"""
Autenticación con LinkedIn vía OAuth 2.0 (Authorization Code flow).

Importante (sección 1 del plan técnico): la app NUNCA pide usuario/contraseña
de LinkedIn. El usuario autoriza la app desde la propia web de LinkedIn y
LinkedIn nos entrega un token con permisos limitados (scopes). Pedir
credenciales directas viola los ToS de LinkedIn y puede banear la cuenta.

V5 (multiusuario): cada cuenta conecta SU PROPIA cuenta de LinkedIn, pero
comparten la misma app de LinkedIn Developer (Client ID/Secret globales,
ver config.get_credentials()). El "state" que LinkedIn nos devuelve tal
cual en el redirect lleva embebido el cuenta_id de quien inició el login,
FIRMADO con HMAC (clave: config_global.app_secret, única por instalación)
para que no se pueda falsificar — necesario porque el redirect de LinkedIn
es una recarga COMPLETA de la página (una sesión nueva de Streamlit, sin
memoria de qué cuenta lo inició) y así app.py sabe a qué cuenta atribuir el
login sin tener que volver a pedir que inicie sesión en la app.
"""

import hashlib
import hmac
import secrets
import urllib.parse
from datetime import datetime, timedelta

import requests

import db
from config import get_credentials

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# openid/profile -> identificar al usuario (member URN) sin pedir su contraseña
# w_member_social -> publicar posts en su nombre
SCOPES = "openid profile w_member_social"


def _firmar(valor: str) -> str:
    secreto = db.obtener_o_crear_app_secret()
    return hmac.new(secreto.encode("utf-8"), valor.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def generar_state(cuenta_id: int) -> str:
    """Genera el "state" que se envía a LinkedIn: un token aleatorio +
    el cuenta_id de quien inicia el login + una firma HMAC de los dos,
    todo en un solo string que LinkedIn nos devuelve tal cual en el
    redirect. Ver `verificar_y_extraer_cuenta` para el lado de vuelta."""
    aleatorio = secrets.token_urlsafe(12)
    base = f"{aleatorio}.{cuenta_id}"
    firma = _firmar(base)
    return f"{base}.{firma}"


def verificar_y_extraer_cuenta(state: str) -> int | None:
    """Verifica la firma del "state" devuelto por LinkedIn y, si es válida,
    devuelve el cuenta_id que llevaba embebido. Devuelve None si el state
    no tiene el formato esperado o la firma no coincide (manipulado, o de
    una instalación distinta) — en ese caso, quien llama debe tratar el
    login como fallido, nunca asumir una cuenta por defecto."""
    partes = (state or "").rsplit(".", 2)
    if len(partes) != 3:
        return None
    aleatorio, cuenta_id_str, firma = partes
    base = f"{aleatorio}.{cuenta_id_str}"
    if not hmac.compare_digest(_firmar(base), firma):
        return None
    try:
        return int(cuenta_id_str)
    except ValueError:
        return None


def construir_url_autorizacion(state: str) -> str:
    creds = get_credentials()
    if not creds.linkedin_client_id:
        raise RuntimeError(
            "Esta instalación todavía no tiene configurada la app de LinkedIn. "
            "Pide a quien la administra que la configure desde 🛠️ Administración."
        )
    params = {
        "response_type": "code",
        "client_id": creds.linkedin_client_id,
        "redirect_uri": creds.linkedin_redirect_uri,
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def intercambiar_codigo_por_token(code: str) -> dict:
    creds = get_credentials()
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": creds.linkedin_redirect_uri,
            "client_id": creds.linkedin_client_id,
            "client_secret": creds.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def refrescar_token(refresh_token: str) -> dict:
    creds = get_credentials()
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": creds.linkedin_client_id,
            "client_secret": creds.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def obtener_userinfo(access_token: str) -> dict:
    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def completar_login(cuenta_id: int, code: str):
    """Intercambia el código por tokens, obtiene el perfil y lo guarda en
    la conexión de LinkedIn de esta cuenta."""
    token_data = intercambiar_codigo_por_token(code)
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 3600)
    refresh_token = token_data.get("refresh_token")

    userinfo = obtener_userinfo(access_token)
    member_urn = f"urn:li:person:{userinfo['sub']}"
    nombre = userinfo.get("name")

    fecha_expiracion = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    db.guardar_tokens_linkedin(cuenta_id, access_token, refresh_token, fecha_expiracion, member_urn, nombre)
    return userinfo


def token_valido(cuenta: dict) -> bool:
    if not cuenta or not cuenta.get("linkedin_access_token"):
        return False
    fecha_exp = cuenta.get("fecha_expiracion_token")
    if not fecha_exp:
        return False
    return datetime.fromisoformat(fecha_exp) > datetime.utcnow() + timedelta(minutes=2)
