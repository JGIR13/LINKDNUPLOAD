"""
Regresión — hora configurable de la "🤖 Automatización Total" (db.py +
generar_diario.py).

Cubre lo añadido en esta ronda:
- `db.guardar_automatizacion` persiste la hora junto con los dos
  interruptores existentes, con '09:00' como valor por defecto para
  cuentas que nunca la configuraron explícitamente.
- `generar_diario._procesar_cuenta` NO genera nada si la hora local
  actual es anterior a la hora configurada de la cuenta (el "latido"
  programado puede dispararse mucho antes de que toque).
- En cuanto la hora local actual alcanza (o supera) la hora configurada,
  SÍ procede a generar — sin que haga falta que coincidan al minuto.
- Cada cuenta se evalúa con su propia hora, de forma independiente.

La comprobación de hora no depende del reloj real de la máquina que
ejecuta los tests (evita tests intermitentes): se sustituye
`generar_diario.datetime` por un doble de prueba con una hora fija.
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


def _crear_cuenta_activa(db, config, email, hora=None, auto_publicar=False):
    h, s = config.hash_password("Secreta123")
    cid = db.crear_cuenta(email, h, s, nombre="Test", rol="usuario")
    db.guardar_automatizacion(cid, True, auto_publicar, hora or "09:00")
    return cid


class _HoraFija:
    """Doble de prueba para `datetime` dentro de generar_diario: sustituye
    solo `.now().strftime(...)`, que es lo único que usa el gate de hora."""

    def __init__(self, hhmm: str):
        self._hhmm = hhmm

    def now(self):
        return self

    def strftime(self, _fmt):
        return self._hhmm


class TestPersistenciaHora:
    def test_hora_por_defecto_es_09_00(self, dbtmp):
        import config

        db = dbtmp
        h, s = config.hash_password("Secreta123")
        cid = db.crear_cuenta("nueva@test.com", h, s, nombre="Test")
        parametros = db.obtener_parametros(cid)
        assert parametros["automatizacion_hora"] == "09:00"

    def test_guardar_automatizacion_persiste_la_hora_elegida(self, dbtmp):
        import config

        db = dbtmp
        h, s = config.hash_password("Secreta123")
        cid = db.crear_cuenta("horario@test.com", h, s, nombre="Test")

        db.guardar_automatizacion(cid, True, False, "18:30")
        parametros = db.obtener_parametros(cid)
        assert parametros["automatizacion_hora"] == "18:30"
        assert bool(parametros["automatizacion_total_activa"]) is True

    def test_guardar_automatizacion_sin_hora_usa_defecto(self, dbtmp):
        """Llamar a guardar_automatizacion sin el nuevo parámetro (código
        antiguo, o una llamada que no pasa `hora`) no debe romper nada."""
        import config

        db = dbtmp
        h, s = config.hash_password("Secreta123")
        cid = db.crear_cuenta("sinhora@test.com", h, s, nombre="Test")

        db.guardar_automatizacion(cid, True, False)
        parametros = db.obtener_parametros(cid)
        assert parametros["automatizacion_hora"] == "09:00"


class TestGateDeHoraEnElLatido:
    def test_no_genera_nada_antes_de_la_hora_configurada(self, dbtmp, monkeypatch):
        import config
        import generar_diario

        db = dbtmp
        cid = _crear_cuenta_activa(db, config, "temprano@test.com", hora="09:00")
        cuenta = db.obtener_cuenta(cid)

        llamado = {"veces": 0}
        monkeypatch.setattr(
            generar_diario.daily, "generar_pendientes_del_dia",
            lambda *a, **k: llamado.__setitem__("veces", llamado["veces"] + 1) or [],
        )
        monkeypatch.setattr(generar_diario, "datetime", _HoraFija("08:45"))

        log = generar_diario._configurar_logging()
        hubo_error = generar_diario._procesar_cuenta(log, cuenta)

        assert hubo_error is False
        assert llamado["veces"] == 0  # ni siquiera se llegó a intentar generar

    def test_genera_en_cuanto_llega_la_hora_configurada(self, dbtmp, monkeypatch):
        import config
        import generar_diario

        db = dbtmp
        cid = _crear_cuenta_activa(db, config, "puntual@test.com", hora="09:00")
        cuenta = db.obtener_cuenta(cid)

        llamado = {"veces": 0}
        monkeypatch.setattr(
            generar_diario.daily, "generar_pendientes_del_dia",
            lambda *a, **k: llamado.__setitem__("veces", llamado["veces"] + 1) or [
                {"estado": "generado", "tipo": "texto", "post_id": 1}
            ],
        )
        monkeypatch.setattr(generar_diario, "datetime", _HoraFija("09:00"))

        log = generar_diario._configurar_logging()
        generar_diario._procesar_cuenta(log, cuenta)

        assert llamado["veces"] == 1

    def test_sigue_generando_horas_despues_de_la_hora_configurada(self, dbtmp, monkeypatch):
        """El latido se dispara cada 15 min todo el día — una vez pasada la
        hora, cualquier disparo posterior debe seguir intentándolo (es
        `daily.generar_pendientes_del_dia`, con su propia idempotencia por
        item, quien evita repetir lo ya generado ese día)."""
        import config
        import generar_diario

        db = dbtmp
        cid = _crear_cuenta_activa(db, config, "tarde@test.com", hora="09:00")
        cuenta = db.obtener_cuenta(cid)

        monkeypatch.setattr(generar_diario.daily, "generar_pendientes_del_dia", lambda *a, **k: [])
        monkeypatch.setattr(generar_diario, "datetime", _HoraFija("14:37"))

        log = generar_diario._configurar_logging()
        hubo_error = generar_diario._procesar_cuenta(log, cuenta)
        assert hubo_error is False

    def test_cada_cuenta_se_evalua_con_su_propia_hora(self, dbtmp, monkeypatch):
        import config
        import generar_diario

        db = dbtmp
        cid_temprana = _crear_cuenta_activa(db, config, "cuenta_a@test.com", hora="08:00")
        cid_tardia = _crear_cuenta_activa(db, config, "cuenta_b@test.com", hora="20:00")

        llamadas = []
        monkeypatch.setattr(
            generar_diario.daily, "generar_pendientes_del_dia",
            lambda cuenta_id, *a, **k: llamadas.append(cuenta_id) or [],
        )
        monkeypatch.setattr(generar_diario, "datetime", _HoraFija("12:00"))

        log = generar_diario._configurar_logging()
        for cuenta in (db.obtener_cuenta(cid_temprana), db.obtener_cuenta(cid_tardia)):
            generar_diario._procesar_cuenta(log, cuenta)

        # A las 12:00, a la cuenta de las 08:00 ya le toca; a la de las 20:00, no.
        assert llamadas == [cid_temprana]

    def test_no_genera_si_automatizacion_total_no_esta_activa(self, dbtmp, monkeypatch):
        """El gate de hora no debe activarse (ni consultarse) para una
        cuenta que ni siquiera encendió la Automatización Total."""
        import config
        import generar_diario

        db = dbtmp
        h, s = config.hash_password("Secreta123")
        cid = db.crear_cuenta("inactiva@test.com", h, s, nombre="Test")
        cuenta = db.obtener_cuenta(cid)

        llamado = {"veces": 0}
        monkeypatch.setattr(
            generar_diario.daily, "generar_pendientes_del_dia",
            lambda *a, **k: llamado.__setitem__("veces", llamado["veces"] + 1) or [],
        )
        monkeypatch.setattr(generar_diario, "datetime", _HoraFija("23:59"))

        log = generar_diario._configurar_logging()
        hubo_error = generar_diario._procesar_cuenta(log, cuenta)

        assert hubo_error is False
        assert llamado["veces"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
