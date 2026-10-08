"""
Regresión — "Plan de hoy" se resincroniza al cambiar el reparto diario (#50).

Motivo (pedido explícito del usuario): "cuando se diseñe un plan diario y
se actualice se tiene que actualizar el plan diario en su totalidad." Antes
de esta ronda, `daily.asegurar_plan_del_dia` era estrictamente idempotente
— una vez creado el plan de un día, guardar un reparto distinto no tenía
ningún efecto sobre lo que ya se había planificado ese día; "Plan de hoy"
seguía mostrando el reparto viejo hasta el día siguiente.

`daily.resincronizar_plan_hoy` (llamada por app.py justo después de
`db.guardar_reparto_diario`) ajusta el plan YA EXISTENTE de hoy para que
coincida con el nuevo reparto:
- añade items 'pendiente' si el nuevo reparto pide más que los que hay;
- quita items 'pendiente' sobrantes (los más recientes primero) si el
  nuevo reparto pide menos;
- NUNCA toca un item ya 'generado'/'publicado'/'error' — si ya hay más
  contenido generado que lo que el nuevo reparto pide, ese contenido se
  queda tal cual (no se puede "des-generar" un post).
"""
import os
import sys
import tempfile

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


@pytest.fixture()
def cuenta(dbtmp):
    import config

    h, s = config.hash_password("Secreta123")
    return dbtmp.crear_cuenta("resync@test.com", h, s, nombre="Test", rol="usuario")


FECHA = "2026-09-27"


class TestResincronizarPlanHoy:
    def test_crea_el_plan_si_todavia_no_existe(self, dbtmp, cuenta):
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 2, 1)
        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan) == 3
        assert resumen["añadidos"] == {"infografia": 2, "texto": 1}

    def test_amplia_un_plan_existente_anadiendo_pendientes(self, dbtmp, cuenta):
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 1, 1)
        daily.resincronizar_plan_hoy(cuenta, FECHA)
        assert len(dbtmp.listar_plan_dia(cuenta, FECHA)) == 2

        # El usuario amplía el reparto — el plan de hoy debe crecer en el acto.
        dbtmp.guardar_reparto_diario(cuenta, 3, 2)
        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan) == 5
        assert len([i for i in plan if i["tipo"] == "infografia"]) == 3
        assert len([i for i in plan if i["tipo"] == "texto"]) == 2
        assert resumen["añadidos"] == {"infografia": 2, "texto": 1}

    def test_reduce_un_plan_existente_quitando_pendientes_sobrantes(self, dbtmp, cuenta):
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 3, 3)
        daily.resincronizar_plan_hoy(cuenta, FECHA)
        assert len(dbtmp.listar_plan_dia(cuenta, FECHA)) == 6

        dbtmp.guardar_reparto_diario(cuenta, 1, 0)
        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan) == 1
        assert plan[0]["tipo"] == "infografia"
        assert resumen["quitados"] == {"infografia": 2, "texto": 3}
        assert all(i["estado"] == "pendiente" for i in plan)

    def test_nunca_toca_items_ya_generados_o_publicados(self, dbtmp, cuenta):
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 3, 0)
        daily.resincronizar_plan_hoy(cuenta, FECHA)
        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan) == 3

        # Se genera y publica uno de los tres.
        item_generado = plan[0]
        pid = dbtmp.crear_post(cuenta, "tema", "texto", "")
        dbtmp.actualizar_item_plan_dia(item_generado["id"], estado="publicado", post_id=pid)

        # El usuario reduce el reparto a 1 infografía — quedan 3 items
        # totales (1 publicado + 2 pendientes), sobran 2 para llegar a 1.
        # Se pueden quitar los 2 pendientes (nunca el publicado), así que
        # el plan queda solo con el publicado, aunque el objetivo pedía 1.
        dbtmp.guardar_reparto_diario(cuenta, 1, 0)
        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        plan_tras = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan_tras) == 1
        assert plan_tras[0]["estado"] == "publicado"
        assert plan_tras[0]["id"] == item_generado["id"]
        assert plan_tras[0]["post_id"] == pid
        assert resumen["quitados"] == {"infografia": 2}

    def test_reduccion_parcial_cuando_solo_algunos_estan_pendientes(self, dbtmp, cuenta):
        """Caso límite: el nuevo objetivo es MENOR que lo ya generado —
        no debe intentar quitar de más ni fallar."""
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 2, 0)
        daily.resincronizar_plan_hoy(cuenta, FECHA)
        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        for item in plan:
            pid = dbtmp.crear_post(cuenta, "tema", "texto", "")
            dbtmp.actualizar_item_plan_dia(item["id"], estado="generado", post_id=pid)

        # Reparto baja a 0 — pero ya hay 2 generados, ninguno pendiente.
        dbtmp.guardar_reparto_diario(cuenta, 0, 0)
        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        plan_tras = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan_tras) == 2
        assert all(i["estado"] == "generado" for i in plan_tras)
        # No había pendientes que quitar, así que no se registra nada.
        assert resumen["quitados"] == {}

    def test_no_cambia_nada_si_el_reparto_es_igual(self, dbtmp, cuenta):
        import daily

        dbtmp.guardar_reparto_diario(cuenta, 2, 1)
        daily.resincronizar_plan_hoy(cuenta, FECHA)
        ids_antes = {i["id"] for i in dbtmp.listar_plan_dia(cuenta, FECHA)}

        resumen = daily.resincronizar_plan_hoy(cuenta, FECHA)

        ids_despues = {i["id"] for i in dbtmp.listar_plan_dia(cuenta, FECHA)}
        assert ids_antes == ids_despues
        assert resumen == {"añadidos": {}, "quitados": {}}


class TestEliminarItemsPlanDia:
    def test_borra_solo_los_ids_indicados(self, dbtmp, cuenta):
        dbtmp.crear_items_plan_dia(cuenta, FECHA, "texto", 3)
        plan = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(plan) == 3

        dbtmp.eliminar_items_plan_dia([plan[0]["id"], plan[1]["id"]])

        restante = dbtmp.listar_plan_dia(cuenta, FECHA)
        assert len(restante) == 1
        assert restante[0]["id"] == plan[2]["id"]

    def test_lista_vacia_no_hace_nada(self, dbtmp, cuenta):
        dbtmp.crear_items_plan_dia(cuenta, FECHA, "texto", 2)
        dbtmp.eliminar_items_plan_dia([])
        assert len(dbtmp.listar_plan_dia(cuenta, FECHA)) == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
