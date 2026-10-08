"""
Publicación en LinkedIn vía la API oficial (ugcPosts), tal como indica
la sección 3.6 del plan técnico. Requiere que el usuario ya haya
autorizado la app (linkedin_oauth.py) y tenga un access_token válido
con el scope w_member_social.
"""

import requests

from db import obtener_cuenta

API_BASE = "https://api.linkedin.com/v2"
REST_HEADERS_BASE = {
    "X-Restli-Protocol-Version": "2.0.0",
    "Content-Type": "application/json",
}


def _headers(access_token: str) -> dict:
    return {**REST_HEADERS_BASE, "Authorization": f"Bearer {access_token}"}


def _registrar_subida_imagen(access_token: str, member_urn: str) -> dict:
    body = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": member_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ],
        }
    }
    resp = requests.post(
        f"{API_BASE}/assets?action=registerUpload",
        headers=_headers(access_token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def _subir_binario_imagen(upload_url: str, access_token: str, ruta_imagen: str):
    with open(ruta_imagen, "rb") as f:
        resp = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {access_token}"},
            data=f.read(),
            timeout=60,
        )
    resp.raise_for_status()


def _subir_imagen(access_token: str, member_urn: str, ruta_imagen: str) -> str:
    """Sube la imagen a LinkedIn y devuelve el asset URN para referenciarlo en el post."""
    registro = _registrar_subida_imagen(access_token, member_urn)
    upload_url = registro["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn = registro["asset"]
    _subir_binario_imagen(upload_url, access_token, ruta_imagen)
    return asset_urn


def publicar_post(cuenta_id: int, texto: str, ruta_imagen: str | None = None) -> str:
    """
    Publica el post en LinkedIn (con imagen opcional) usando la conexión de
    LinkedIn de `cuenta_id`, y devuelve el post_id de LinkedIn generado.
    """
    cuenta = obtener_cuenta(cuenta_id)
    if not cuenta or not cuenta.get("linkedin_access_token"):
        raise RuntimeError("No hay una cuenta de LinkedIn conectada. Conéctala primero.")

    access_token = cuenta["linkedin_access_token"]
    member_urn = cuenta["linkedin_member_urn"]

    media_category = "NONE"
    media = []

    if ruta_imagen:
        asset_urn = _subir_imagen(access_token, member_urn, ruta_imagen)
        media_category = "IMAGE"
        media = [{"status": "READY", "media": asset_urn}]

    body = {
        "author": member_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": texto},
                "shareMediaCategory": media_category,
                **({"media": media} if media else {}),
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    resp = requests.post(
        f"{API_BASE}/ugcPosts",
        headers=_headers(access_token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.headers.get("x-restli-id") or resp.json().get("id", "")
