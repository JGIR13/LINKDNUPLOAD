"""
Regresión — "🚀 Subida masiva" (daily.generar_lote) y paletas personalizadas
de la infografía (db.py: tabla paletas_personalizadas + resolver_paleta_infografia).

Cubre lo añadido en esta ronda:
- CRUD de paletas personalizadas, aisladas por cuenta.
- `db.resolver_paleta_infografia` traduce un preset o un valor
  'custom:<id>' al diccionario de colores esperado por
  `image_infografia.generar_infografia` — con fallback seguro al preset
  por defecto ante cualquier valor irreconocible o de otra cuenta.
- `daily.generar_lote` genera una tanda "de golpe" de la mezcla de tipos
  pedida, SIN tocar la tabla `generacion_diaria` (no debe interferir con
  el plan automático del día ni con la Automatización Total).
- El checkbox de publicar-o-no de la subida masiva (mandado explícitamente
  por el usuario): `publicar=False` dejr los posts como borrador,
  `publicar=True` los publica pieza a pieza si hay LinkedIn conectado, y no
  falla si no lo hay (igual que la cola diaria).
- Un error en una pieza de la tanda no tumba el resto.
- La paleta/estilo pedidos para la tanda se aplican a TODAS sus infografías.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(__file__))


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


class TestPaletasPersonalizadas:
    def test_crear_listar_eliminar(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("paleta@test.com", "h", "s")
        pid = db.crear_paleta_personalizada(cid, "Mi marca", "#7C3AED", "#F59E0B")

        paletas = db.listar_paletas_personalizadas(cid)
        assert len(paletas) == 1
        assert paletas[0]["nombre"] == "Mi marca"
        assert paletas[0]["primario"] == "#7C3AED"
        assert paletas[0]["acento"] == "#F59E0B"

        db.eliminar_paleta_personalizada(pid)
        assert db.listar_paletas_personalizadas(cid) == []

    def test_aisladas_por_cuenta(self, dbtmp):
        db = dbtmp
        a = db.crear_cuenta("pa@test.com", "h", "s")
        b = db.crear_cuenta("pb@test.com", "h", "s")
        db.crear_paleta_personalizada(a, "De A", "#111111", "#222222")

        assert len(db.listar_paletas_personalizadas(a)) == 1
        assert db.listar_paletas_personalizadas(b) == []

    def test_resolver_preset_devuelve_la_paleta_completa(self, dbtmp):
        import config

        db = dbtmp
        paleta = db.resolver_paleta_infografia(999, "Azul corporativo")
        assert paleta == config.INFOGRAFIA_PALETAS["Azul corporativo"]

    def test_resolver_custom_devuelve_solo_primario_y_acento(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("resolver@test.com", "h", "s")
        pid = db.crear_paleta_personalizada(cid, "Mi marca", "#7C3AED", "#F59E0B")

        valor = db.valor_selector_paleta(pid)
        assert valor == f"custom:{pid}"
        paleta = db.resolver_paleta_infografia(cid, valor)
        assert paleta == {"primario": "#7C3AED", "acento": "#F59E0B"}

    def test_resolver_custom_de_otra_cuenta_cae_al_defecto(self, dbtmp):
        import config

        db = dbtmp
        a = db.crear_cuenta("owner@test.com", "h", "s")
        b = db.crear_cuenta("otro@test.com", "h", "s")
        pid = db.crear_paleta_personalizada(a, "De A", "#111111", "#222222")

        paleta = db.resolver_paleta_infografia(b, db.valor_selector_paleta(pid))
        assert paleta == config.INFOGRAFIA_PALETAS[config.INFOGRAFIA_PALETA_DEFECTO]

    def test_resolver_valor_desconocido_o_ausente_cae_al_defecto(self, dbtmp):
        import config

        db = dbtmp
        defecto = config.INFOGRAFIA_PALETAS[config.INFOGRAFIA_PALETA_DEFECTO]
        assert db.resolver_paleta_infografia(1, "no-existe") == defecto
        assert db.resolver_paleta_infografia(1, None) == defecto
        assert db.resolver_paleta_infografia(1, "custom:9999") == defecto
        assert db.resolver_paleta_infografia(1, "custom:no-es-numero") == defecto


def _mocks_generacion_basica(monkeypatch, daily):
    monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema de prueba")
    monkeypatch.setattr(daily.llm, "generar_variantes_texto", lambda *a, **k: ["Texto variante 1", "Texto variante 2"])
    monkeypatch.setattr(daily.llm, "generar_infografia_contenido", lambda *a, **k: {"titulo": "T", "items": []})
    monkeypatch.setattr(daily.image_infografia, "generar_infografia", lambda *a, **k: "/tmp/fake_infografia.png")


class TestGenerarLote:
    def test_genera_la_mezcla_de_tipos_pedida_en_orden(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote1@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)

        resultados = daily.generar_lote(cid, ["infografia", "infografia", "texto"], publicar=False)

        assert [r["tipo"] for r in resultados] == ["infografia", "infografia", "texto"]
        assert all(r["estado"] == "generado" for r in resultados)
        assert len(db.listar_posts(cid)) == 3

    def test_no_toca_la_tabla_generacion_diaria(self, dbtmp, monkeypatch):
        """La subida masiva no debe crear ni modificar filas del plan diario
        — debe poder lanzarse el mismo día sin interferir con
        asegurar_plan_del_dia ni con la Automatización Total."""
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote2@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)

        fecha_hoy = daily.hoy()
        plan_antes = db.listar_plan_dia(cid, fecha_hoy)
        daily.generar_lote(cid, ["texto", "texto"], publicar=False)
        plan_despues = db.listar_plan_dia(cid, fecha_hoy)

        assert plan_antes == plan_despues == []

    def test_sin_marcar_publicar_deja_como_borrador(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote3@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)

        resultados = daily.generar_lote(cid, ["texto"], publicar=False)
        assert resultados[0]["estado"] == "generado"
        post = db.obtener_post(resultados[0]["post_id"])
        assert post["estado"] == "borrador"

    def test_publicar_true_sin_linkedin_conectado_no_falla_y_queda_borrador(self, dbtmp, monkeypatch):
        """Coherente con daily._publicar_si_procede: pedir publicar=True sin
        tener LinkedIn conectado no debe lanzar, solo deja el post como
        borrador listo para publicar a mano."""
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote4@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)

        resultados = daily.generar_lote(cid, ["texto"], publicar=True)
        assert resultados[0]["estado"] == "generado"

    def test_publicar_true_con_linkedin_conectado_publica_cada_pieza(self, dbtmp, monkeypatch):
        """Con textos DISTINTOS entre piezas, cada una se publica en
        LinkedIn. (Si el texto generado fuera idéntico entre piezas, la red
        de seguridad anti-duplicado entraría en juego — ver
        TestNoPublicarElMismoTextoDosVeces — así que aquí forzamos textos
        distintos para probar el camino normal de "publicar cada pieza".)"""
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote5@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)
        textos = iter(["Texto pieza 1", "Texto pieza 2"])
        monkeypatch.setattr(daily.llm, "generar_variantes_texto", lambda *a, **k: [next(textos)])
        fecha_exp_futura = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.guardar_tokens_linkedin(cid, "fake-access", "fake-refresh", fecha_exp_futura)

        monkeypatch.setattr(daily.linkedin_publish, "publicar_post", lambda *a, **k: "urn:li:share:fake")
        monkeypatch.setattr(daily.time, "sleep", lambda *a, **k: None)  # no ralentizar el test

        resultados = daily.generar_lote(cid, ["texto", "texto"], publicar=True)

        assert all(r["estado"] == "publicado" for r in resultados)
        for r in resultados:
            post = db.obtener_post(r["post_id"])
            assert post["estado"] == "publicado"
            assert post["post_id_linkedin"] == "urn:li:share:fake"

    def test_un_error_en_una_pieza_no_tumba_el_resto_de_la_tanda(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote6@test.com", "h", "s")
        monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema de prueba")

        llamadas = {"n": 0}

        def variantes_con_fallo(*a, **k):
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                raise RuntimeError("fallo simulado de la IA")
            return ["Texto ok"]

        monkeypatch.setattr(daily.llm, "generar_variantes_texto", variantes_con_fallo)

        resultados = daily.generar_lote(cid, ["texto", "texto", "texto"], publicar=False)

        assert [r["estado"] for r in resultados] == ["generado", "error", "generado"]
        assert "fallo simulado" in resultados[1]["error"]

    def test_respeta_la_paleta_y_estilo_pedidos_para_toda_la_tanda(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote7@test.com", "h", "s")
        monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema de prueba")
        monkeypatch.setattr(daily.llm, "generar_variantes_texto", lambda *a, **k: ["Texto"])
        monkeypatch.setattr(daily.llm, "generar_infografia_contenido", lambda *a, **k: {"titulo": "T", "items": []})

        llamadas_render = []

        def render_fake(datos, paleta, marca=None, oscuro=None):
            llamadas_render.append((paleta, oscuro))
            return "/tmp/fake_infografia.png"

        monkeypatch.setattr(daily.image_infografia, "generar_infografia", render_fake)

        pid = db.crear_paleta_personalizada(cid, "Marca", "#123456", "#abcdef")
        valor_custom = db.valor_selector_paleta(pid)

        daily.generar_lote(cid, ["infografia", "infografia"], publicar=False, paleta_valor=valor_custom, oscuro=True)

        assert len(llamadas_render) == 2
        for paleta_usada, oscuro_usado in llamadas_render:
            assert paleta_usada == {"primario": "#123456", "acento": "#abcdef"}
            assert oscuro_usado is True

    def test_lote_vacio_no_genera_nada(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("lote8@test.com", "h", "s")
        _mocks_generacion_basica(monkeypatch, daily)

        assert daily.generar_lote(cid, [], publicar=False) == []
        assert db.listar_posts(cid) == []


class TestNoPublicarElMismoTextoDosVeces:
    """Red de seguridad ante el bug reportado: 'se subió el mismo post 2
    veces' en LinkedIn. Sea cual sea la causa real (una IA que devuelve
    texto casi idéntico, una re-ejecución de Streamlit, una doble
    pulsación), publicar dos posts con el MISMO texto en poco tiempo para
    la misma cuenta nunca debe llegar dos veces a LinkedIn."""

    def _preparar_cuenta_con_linkedin(self, db, email):
        cid = db.crear_cuenta(email, "h", "s")
        fecha_exp_futura = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.guardar_tokens_linkedin(cid, "fake-access", "fake-refresh", fecha_exp_futura)
        return cid

    def test_existe_publicado_reciente_detecta_texto_exacto(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("dup1@test.com", "h", "s")
        post_id = db.crear_post(cid, "tema", "Texto exacto del post", "")
        db.marcar_publicado(post_id, "urn:li:share:1")

        assert db.existe_publicado_reciente(cid, "Texto exacto del post") is True
        assert db.existe_publicado_reciente(cid, "Texto completamente distinto") is False

    def test_existe_publicado_reciente_ignora_borradores_y_otras_cuentas(self, dbtmp):
        db = dbtmp
        cid = db.crear_cuenta("dup2@test.com", "h", "s")
        otro = db.crear_cuenta("dup2b@test.com", "h", "s")

        # Borrador (nunca publicado) con el mismo texto: no cuenta.
        db.crear_post(cid, "tema", "Texto en borrador", "")
        assert db.existe_publicado_reciente(cid, "Texto en borrador") is False

        # Publicado, pero en OTRA cuenta: no debe filtrar entre cuentas.
        post_otro = db.crear_post(otro, "tema", "Texto de otra cuenta", "")
        db.marcar_publicado(post_otro, "urn:li:share:2")
        assert db.existe_publicado_reciente(cid, "Texto de otra cuenta") is False

    def test_existe_publicado_reciente_respeta_la_ventana_de_horas(self, dbtmp):
        import sqlite3

        db = dbtmp
        cid = db.crear_cuenta("dup3@test.com", "h", "s")
        post_id = db.crear_post(cid, "tema", "Texto de hace tiempo", "")
        db.marcar_publicado(post_id, "urn:li:share:3")

        # Forzar la fecha de publicación a hace más de 24h.
        fecha_vieja = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE posts_generados SET fecha_publicacion=? WHERE id=?", (fecha_vieja, post_id)
            )

        assert db.existe_publicado_reciente(cid, "Texto de hace tiempo") is False

    def test_publicar_si_procede_omite_el_duplicado_y_no_llama_a_linkedin(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = self._preparar_cuenta_con_linkedin(db, "dup4@test.com")

        llamadas = {"n": 0}

        def publicar_fake(*a, **k):
            llamadas["n"] += 1
            return f"urn:li:share:{llamadas['n']}"

        monkeypatch.setattr(daily.linkedin_publish, "publicar_post", publicar_fake)

        post_id_1 = db.crear_post(cid, "tema", "Mismo texto repetido", "")
        estado_1 = daily._publicar_si_procede(cid, post_id_1, "Mismo texto repetido", "")
        assert estado_1 == "publicado"

        post_id_2 = db.crear_post(cid, "tema", "Mismo texto repetido", "")
        estado_2 = daily._publicar_si_procede(cid, post_id_2, "Mismo texto repetido", "")
        assert estado_2 == "duplicado_omitido"

        # linkedin_publish.publicar_post solo se llamó UNA vez, no dos.
        assert llamadas["n"] == 1
        assert db.obtener_post(post_id_2)["estado"] != "publicado"

    def test_generar_lote_no_publica_dos_veces_el_mismo_texto_generado(self, dbtmp, monkeypatch):
        """Reproduce el escenario real: la IA (mockeada aquí, pero podría
        pasar con una IA real que devuelve contenido casi idéntico) genera
        el mismo texto para dos piezas de la misma tanda con publicar=True
        — solo la primera debe llegar a LinkedIn."""
        import daily

        db = dbtmp
        cid = self._preparar_cuenta_con_linkedin(db, "dup5@test.com")
        _mocks_generacion_basica(monkeypatch, daily)  # siempre devuelve el mismo texto
        monkeypatch.setattr(daily.time, "sleep", lambda *a, **k: None)

        llamadas = {"n": 0}
        monkeypatch.setattr(
            daily.linkedin_publish, "publicar_post",
            lambda *a, **k: (llamadas.__setitem__("n", llamadas["n"] + 1), "urn:li:share:x")[1],
        )

        resultados = daily.generar_lote(cid, ["texto", "texto"], publicar=True)

        assert [r["estado"] for r in resultados] == ["publicado", "duplicado_omitido"]
        assert llamadas["n"] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
