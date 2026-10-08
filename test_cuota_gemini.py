"""
Regresión — manejo del límite de cuota gratuita de Gemini.

V5.4: se corrigió una suposición equivocada de la V5.2/V5.3 — el 429 real
que devuelve Google (quotaId "GenerateRequestsPerDayPerProjectPerModel-
FreeTier") deja claro que la cuota gratuita DIARIA es POR MODELO, no del
proyecto/clave entera. Antes, `_generar_con_fallback` se rendía en cuanto
CUALQUIER candidato devolvía un 429, sin probar los demás — desperdiciando
la cuota independiente de los otros modelos de la lista de respaldo
(`config.GEMINI_TEXT_MODEL_CANDIDATOS`). Ahora prueba cada candidato no
agotado hasta que uno funcione, recuerda (por día) qué modelos ya se
agotaron para no reintentarlos, y solo lanza `CuotaGeminiAgotada` cuando
TODOS están agotados. Cubre:

- `llm._es_error_de_cuota` / `_es_error_de_cuota_diaria`: detección
  robusta (atributos estructurados `.code`/`.status` de la API, con
  respaldo por texto) y distinción entre límite diario vs. de ráfaga.
- `llm._info_cuota_desde_error`: extrae el modelo y el cupo real
  (`quotaValue`) del detalle estructurado del 429, cuando está disponible.
- `llm._generar_con_fallback`: al agotarse un candidato SÍ prueba el
  resto (cada uno tiene su propio cupo); un modelo ya marcado agotado hoy
  se salta sin intentarlo; solo se rinde cuando todos lo están.
- `db.uso_gemini_diario` (contador/agotado/límite conocido POR MODELO) y
  `llm.estado_cuota_gemini_hoy` (resumen para la interfaz).
- El límite diario propio configurable (`db.limite_diario_gemini`), ahora
  aplicado POR MODELO, corta ANTES de tocar la API cuando un modelo
  concreto ya lo alcanzó — sin bloquear a los demás.
- `daily.generar_item` / `generar_lote` / `generar_pendientes_del_dia`:
  al toparse con `CuotaGeminiAgotada`, el item afectado NO se marca
  'error' en la base de datos (queda 'pendiente' para reintentarlo más
  tarde) y se corta el resto de la tanda/plan en vez de seguir fallando
  uno a uno contra una API ya saturada.
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


class _ErrorConAtributos(Exception):
    """Simula google.genai.errors.APIError: expone .code (int) y .status
    (str) como atributos estructurados, además del texto habitual."""

    def __init__(self, mensaje, code=None, status=None, details=None):
        super().__init__(mensaje)
        self.code = code
        self.status = status
        self.details = details


def _error_cuota_real(modelo: str, quota_value: str = "20", diaria: bool = True) -> _ErrorConAtributos:
    """Construye un error lo más fiel posible al 429 real que devuelve
    google-genai (mismo `.details` estructurado, y el mensaje incluye ese
    dict igual que hace `APIError.__init__` de verdad — así los tests
    ejercitan la detección por texto exactamente como en producción)."""
    quota_id = (
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if diaria
        else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    )
    details = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaId": quota_id,
                            "quotaDimensions": {"location": "global", "model": modelo},
                            "quotaValue": quota_value,
                        }
                    ],
                },
            ],
        }
    }
    return _ErrorConAtributos(f"429 RESOURCE_EXHAUSTED. {details}", code=429, status="RESOURCE_EXHAUSTED", details=details)


class _FakeModels:
    def __init__(self, respuestas: dict):
        self.respuestas = respuestas  # modelo -> valor de retorno o excepción a lanzar
        self.llamadas = []

    def generate_content(self, model, contents, config):
        self.llamadas.append(model)
        r = self.respuestas[model]
        if isinstance(r, Exception):
            raise r
        return r


class _FakeClient:
    def __init__(self, respuestas: dict):
        self.models = _FakeModels(respuestas)


class TestDeteccionDeCuota:
    def test_detecta_por_codigo_429_estructurado(self, dbtmp):
        import llm

        assert llm._es_error_de_cuota(_ErrorConAtributos("da igual el texto", code=429)) is True

    def test_detecta_por_status_resource_exhausted(self, dbtmp):
        import llm

        assert llm._es_error_de_cuota(_ErrorConAtributos("x", status="RESOURCE_EXHAUSTED")) is True

    def test_detecta_por_texto_como_respaldo(self, dbtmp):
        import llm

        assert llm._es_error_de_cuota(RuntimeError("429 RESOURCE_EXHAUSTED: quota...")) is True

    def test_error_normal_no_se_confunde_con_cuota(self, dbtmp):
        import llm

        assert llm._es_error_de_cuota(RuntimeError("modelo no encontrado (404)")) is False

    def test_distingue_limite_diario_de_limite_por_minuto(self, dbtmp):
        import llm

        diario = RuntimeError(
            "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 20"
        )
        minuto = RuntimeError("quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier limit: 15")
        assert llm._es_error_de_cuota_diaria(diario) is True
        assert llm._es_error_de_cuota_diaria(minuto) is False


class TestGenerarConFallback:
    def test_cuota_agotada_en_el_primero_SI_prueba_el_siguiente_candidato(self, dbtmp):
        """El bug central que motivó esta ronda: la cuota es por modelo, así
        que agotar el primer candidato no debe impedir probar el segundo."""
        import llm

        class _Respuesta:
            text = "ok desde modelo-b"

        respuestas = {
            "modelo-a": _error_cuota_real("modelo-a"),
            "modelo-b": _Respuesta(),
        }
        client = _FakeClient(respuestas)

        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])

        assert resultado.text == "ok desde modelo-b"
        assert client.models.llamadas == ["modelo-a", "modelo-b"]
        # El modelo agotado queda recordado para el resto del día.
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-a") is True
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-b") is False

    def test_todos_agotados_por_cuota_diaria_lanza_cuotageminiagotada(self, dbtmp):
        import llm

        respuestas = {
            "modelo-a": _error_cuota_real("modelo-a"),
            "modelo-b": _error_cuota_real("modelo-b"),
        }
        client = _FakeClient(respuestas)

        with pytest.raises(llm.CuotaGeminiAgotada):
            llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])

        assert client.models.llamadas == ["modelo-a", "modelo-b"]
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-a") is True
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-b") is True

    def test_un_modelo_ya_agotado_hoy_se_salta_sin_intentarlo(self, dbtmp):
        """Si una llamada ANTERIOR ya agotó modelo-a hoy, una llamada nueva
        ni se molesta en reintentarlo — va directa a modelo-b."""
        import llm

        class _Respuesta:
            text = "ok"

        dbtmp.marcar_gemini_agotado("modelo-a", limite_real=20)
        client = _FakeClient({"modelo-b": _Respuesta()})

        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])

        assert resultado.text == "ok"
        assert client.models.llamadas == ["modelo-b"]  # modelo-a nunca se llamó

    def test_limite_por_minuto_tambien_prueba_el_siguiente_candidato(self, dbtmp):
        import llm

        class _Respuesta:
            text = "ok"

        respuestas = {
            "modelo-a": _error_cuota_real("modelo-a", diaria=False),
            "modelo-b": _Respuesta(),
        }
        client = _FakeClient(respuestas)

        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])
        assert resultado.text == "ok"
        # Un límite por minuto NO se recuerda como agotado (se recupera solo, a diferencia del diario).
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-a") is False

    def test_todos_agotados_por_limite_de_minuto_lanza_cuotageminiagotada_con_mensaje_distinto(self, dbtmp):
        import llm

        respuestas = {"modelo-a": _error_cuota_real("modelo-a", diaria=False)}
        client = _FakeClient(respuestas)

        with pytest.raises(llm.CuotaGeminiAgotada) as exc_info:
            llm._generar_con_fallback(client, "contenido", None, ["modelo-a"])
        assert "por minuto" in str(exc_info.value)

    def test_error_no_relacionado_con_cuota_sigue_probando_el_resto(self, dbtmp):
        import llm

        class _Respuesta:
            text = "ok"

        respuestas = {
            "modelo-a": RuntimeError("modelo retirado"),
            "modelo-b": _Respuesta(),
        }
        client = _FakeClient(respuestas)

        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])

        assert resultado.text == "ok"
        assert client.models.llamadas == ["modelo-a", "modelo-b"]

    def test_todos_los_candidatos_fallan_sin_ser_cuota_da_runtimeerror_generico(self, dbtmp):
        import llm

        respuestas = {"modelo-a": RuntimeError("fallo a"), "modelo-b": RuntimeError("fallo b")}
        client = _FakeClient(respuestas)

        with pytest.raises(RuntimeError) as exc_info:
            llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])
        assert not isinstance(exc_info.value, llm.CuotaGeminiAgotada)

    def test_registra_uso_por_cada_llamada_real_a_la_api(self, dbtmp):
        import llm

        class _Respuesta:
            text = "ok"

        client = _FakeClient({"modelo-a": _Respuesta()})
        assert dbtmp.uso_gemini_hoy_por_modelo() == {}

        llm._generar_con_fallback(client, "contenido", None, ["modelo-a"])

        assert dbtmp.uso_gemini_hoy_por_modelo()["modelo-a"]["usados"] == 1

    def test_limite_diario_propio_corta_solo_el_modelo_que_lo_alcanzo(self, dbtmp):
        """El límite propio ahora es POR MODELO: agotar modelo-a con él no
        debe impedir que modelo-b (que no lo ha alcanzado) se intente."""
        import llm

        class _Respuesta:
            text = "ok desde b"

        dbtmp.guardar_limite_diario_gemini(2)
        dbtmp.registrar_uso_gemini("modelo-a")
        dbtmp.registrar_uso_gemini("modelo-a")  # modelo-a ya va 2/2

        client = _FakeClient({"modelo-a": "no debería usarse", "modelo-b": _Respuesta()})

        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a", "modelo-b"])

        assert resultado.text == "ok desde b"
        assert client.models.llamadas == ["modelo-b"]  # modelo-a se saltó, ni se intentó

    def test_limite_diario_propio_en_todos_los_candidatos_corta_sin_llamar_a_la_api(self, dbtmp):
        import llm

        dbtmp.guardar_limite_diario_gemini(2)
        dbtmp.registrar_uso_gemini("modelo-a")
        dbtmp.registrar_uso_gemini("modelo-a")

        client = _FakeClient({"modelo-a": "no debería usarse"})

        with pytest.raises(llm.CuotaGeminiAgotada):
            llm._generar_con_fallback(client, "contenido", None, ["modelo-a"])

        assert client.models.llamadas == []  # ni se intentó

    def test_limite_diario_en_cero_significa_sin_limite(self, dbtmp):
        import llm

        class _Respuesta:
            text = "ok"

        dbtmp.guardar_limite_diario_gemini(0)
        for _ in range(30):
            dbtmp.registrar_uso_gemini("modelo-a")

        client = _FakeClient({"modelo-a": _Respuesta()})
        resultado = llm._generar_con_fallback(client, "contenido", None, ["modelo-a"])
        assert resultado.text == "ok"


class TestCuotaPorClaveDeGemini:
    """V5.6: se corrigió un segundo bug de la misma familia — el "agotado"
    de `uso_gemini_diario` se guardaba solo por (fecha, modelo), sin saber
    NADA de qué clave de Gemini estaba activa cuando se registró. Reportado
    por el usuario: cambió la clave de API desde 🛠️ Administración tras
    agotar la cuota y, al volver a generar, la app se rindió igual — sin
    siquiera intentarlo con la clave nueva, porque el "agotado" de la
    clave anterior seguía ahí. Ahora cada fila lleva la huella
    (`config.fingerprint_clave_gemini`) de la clave bajo la que se
    registró, y un "agotado" de una clave distinta a la activa se trata
    como si hoy no se hubiera intentado nada todavía con la clave nueva."""

    def test_fingerprint_es_estable_y_no_reversible(self, dbtmp):
        import config

        a = config.fingerprint_clave_gemini("AIzaClaveDeEjemplo1")
        b = config.fingerprint_clave_gemini("AIzaClaveDeEjemplo1")
        c = config.fingerprint_clave_gemini("AIzaClaveDeEjemplo2")
        assert a == b
        assert a != c
        assert "AIzaClaveDeEjemplo1" not in a
        assert config.fingerprint_clave_gemini(None) == ""
        assert config.fingerprint_clave_gemini("") == ""

    def test_agotado_de_una_clave_no_cuenta_para_otra_clave(self, dbtmp):
        db = dbtmp
        db.registrar_uso_gemini("modelo-a", clave_fingerprint="clave-vieja")
        db.marcar_gemini_agotado("modelo-a", limite_real=20, clave_fingerprint="clave-vieja")

        # Con la clave que lo agotó, sigue agotado.
        assert db.modelo_gemini_agotado_hoy("modelo-a", clave_fingerprint="clave-vieja") is True
        assert db.uso_gemini_hoy_por_modelo("clave-vieja")["modelo-a"]["agotado"] is True

        # Con una clave DISTINTA, ese agotamiento no aplica — como si hoy
        # no se hubiera tocado ese modelo todavía con la clave nueva.
        assert db.modelo_gemini_agotado_hoy("modelo-a", clave_fingerprint="clave-nueva") is False
        assert db.uso_gemini_hoy_por_modelo("clave-nueva") == {}

    def test_registrar_uso_con_clave_nueva_arranca_el_contador_de_cero(self, dbtmp):
        db = dbtmp
        db.registrar_uso_gemini("modelo-a", clave_fingerprint="clave-vieja")
        db.registrar_uso_gemini("modelo-a", clave_fingerprint="clave-vieja")
        assert db.uso_gemini_hoy_por_modelo("clave-vieja")["modelo-a"]["usados"] == 2

        # La clave nueva empieza su propio conteo, no hereda el 2 anterior.
        n = db.registrar_uso_gemini("modelo-a", clave_fingerprint="clave-nueva")
        assert n == 1
        assert db.uso_gemini_hoy_por_modelo("clave-nueva")["modelo-a"]["usados"] == 1
        # Y para la clave vieja, esa misma fila ya no es "suya" (la pisó la
        # nueva) — coherente con que ahora solo existe una fila por
        # (fecha, modelo): se prioriza reflejar la clave ACTIVA.
        assert db.uso_gemini_hoy_por_modelo("clave-vieja") == {}

    def test_una_fila_sin_fingerprint_guardado_nunca_se_descarta(self, dbtmp):
        """BD de antes de esta función (o clave_fingerprint='' porque no
        había ninguna clave configurada al registrarla): debe seguir
        contando como válida para cualquier clave, en vez de perder datos
        reales por no poder comparar."""
        db = dbtmp
        db.registrar_uso_gemini("modelo-a")  # sin fingerprint -> ""
        assert db.uso_gemini_hoy_por_modelo("clave-cualquiera")["modelo-a"]["usados"] == 1
        assert db.modelo_gemini_agotado_hoy("modelo-a", clave_fingerprint="clave-cualquiera") is False

    def test_generar_con_fallback_reintenta_tras_cambiar_de_clave(self, dbtmp, monkeypatch):
        """Reproduce el escenario reportado end-to-end: se agota modelo-a
        con la clave 1, el usuario cambia a la clave 2 desde 🛠️
        Administración, y la siguiente generación SÍ vuelve a intentar
        modelo-a de verdad (no se rinde arrastrando el agotado viejo)."""
        import llm

        db = dbtmp
        db.guardar_gemini_api_key_global("clave-uno-AIzaFake1111111111")

        respuestas_1 = {"modelo-a": _error_cuota_real("modelo-a")}
        client1 = _FakeClient(respuestas_1)
        with pytest.raises(llm.CuotaGeminiAgotada):
            llm._generar_con_fallback(client1, "contenido", None, ["modelo-a"])
        assert client1.models.llamadas == ["modelo-a"]

        # Cambia de clave desde el panel de administración.
        db.guardar_gemini_api_key_global("clave-dos-AIzaFake2222222222")

        class _Respuesta:
            text = "ok con la clave nueva"

        client2 = _FakeClient({"modelo-a": _Respuesta()})
        resultado = llm._generar_con_fallback(client2, "contenido", None, ["modelo-a"])

        assert resultado.text == "ok con la clave nueva"
        # La prueba central: SÍ se volvió a llamar a la API con modelo-a,
        # en vez de rendirse sin intentarlo por el agotado de la clave 1.
        assert client2.models.llamadas == ["modelo-a"]

    def test_generar_con_fallback_si_la_clave_nueva_tambien_se_agota_lo_refleja_por_separado(self, dbtmp):
        """Si la clave nueva pertenece al mismo proyecto de Google Cloud
        (caso frecuente: varias claves del mismo "Default Gemini Project"
        en AI Studio), es esperable que también se agote — pero debe
        quedar registrado como un agotamiento PROPIO de la clave nueva,
        no confundido con el de la clave anterior."""
        import llm

        db = dbtmp
        db.guardar_gemini_api_key_global("clave-uno-AIzaFake1111111111")
        client1 = _FakeClient({"modelo-a": _error_cuota_real("modelo-a")})
        with pytest.raises(llm.CuotaGeminiAgotada):
            llm._generar_con_fallback(client1, "contenido", None, ["modelo-a"])

        db.guardar_gemini_api_key_global("clave-dos-AIzaFake2222222222")
        client2 = _FakeClient({"modelo-a": _error_cuota_real("modelo-a")})
        with pytest.raises(llm.CuotaGeminiAgotada):
            llm._generar_con_fallback(client2, "contenido", None, ["modelo-a"])

        # Ambos clientes SÍ intentaron la llamada real — ninguno se rindió
        # de antemano por el estado de la otra clave.
        assert client1.models.llamadas == ["modelo-a"]
        assert client2.models.llamadas == ["modelo-a"]


class TestInfoCuotaDesdeError:
    def test_extrae_modelo_y_cupo_real_del_detalle_estructurado(self, dbtmp):
        import llm

        error = _error_cuota_real("gemini-3.8-flash", quota_value="20")
        info = llm._info_cuota_desde_error(error)
        assert info == {"modelo": "gemini-3.8-flash", "limite": 20}

    def test_error_sin_detalles_estructurados_devuelve_vacio(self, dbtmp):
        import llm

        assert llm._info_cuota_desde_error(RuntimeError("429 quota")) == {}


class TestEstadoCuotaGeminiHoy:
    def test_sin_uso_todos_disponibles_y_activo_es_el_primero(self, dbtmp, monkeypatch):
        import config
        import llm

        monkeypatch.setattr(config, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a", "modelo-b"])
        monkeypatch.setattr(llm, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a", "modelo-b"])

        estado = llm.estado_cuota_gemini_hoy()
        assert estado["todos_agotados"] is False
        assert estado["activo"]["modelo"] == "modelo-a"
        assert all(not m["agotado"] for m in estado["modelos"])

    def test_primer_modelo_agotado_el_activo_pasa_al_segundo(self, dbtmp, monkeypatch):
        import config
        import llm

        monkeypatch.setattr(config, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a", "modelo-b"])
        monkeypatch.setattr(llm, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a", "modelo-b"])
        dbtmp.marcar_gemini_agotado("modelo-a", limite_real=20)

        estado = llm.estado_cuota_gemini_hoy()
        assert estado["todos_agotados"] is False
        assert estado["activo"]["modelo"] == "modelo-b"
        modelo_a = next(m for m in estado["modelos"] if m["modelo"] == "modelo-a")
        assert modelo_a["agotado"] is True
        assert modelo_a["limite"] == 20
        assert modelo_a["limite_es_real"] is True

    def test_todos_agotados(self, dbtmp, monkeypatch):
        import config
        import llm

        monkeypatch.setattr(config, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a"])
        monkeypatch.setattr(llm, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a"])
        dbtmp.marcar_gemini_agotado("modelo-a")

        estado = llm.estado_cuota_gemini_hoy()
        assert estado["todos_agotados"] is True
        assert estado["activo"] is None

    def test_modelo_sin_cupo_conocido_usa_la_estimacion(self, dbtmp, monkeypatch):
        import config
        import llm

        monkeypatch.setattr(config, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a"])
        monkeypatch.setattr(llm, "GEMINI_TEXT_MODEL_CANDIDATOS", ["modelo-a"])
        dbtmp.registrar_uso_gemini("modelo-a")

        estado = llm.estado_cuota_gemini_hoy()
        modelo_a = estado["modelos"][0]
        assert modelo_a["usados"] == 1
        assert modelo_a["limite"] == config.GEMINI_LIMITE_ESTIMADO_POR_MODELO
        assert modelo_a["limite_es_real"] is False


class TestUsoGeminiEnBaseDeDatos:
    def test_sin_uso_diccionario_vacio(self, dbtmp):
        assert dbtmp.uso_gemini_hoy_por_modelo() == {}

    def test_registrar_uso_incrementa_por_modelo_de_forma_independiente(self, dbtmp):
        assert dbtmp.registrar_uso_gemini("modelo-a") == 1
        assert dbtmp.registrar_uso_gemini("modelo-a") == 2
        assert dbtmp.registrar_uso_gemini("modelo-b") == 1  # independiente de modelo-a

        uso = dbtmp.uso_gemini_hoy_por_modelo()
        assert uso["modelo-a"]["usados"] == 2
        assert uso["modelo-b"]["usados"] == 1

    def test_guardar_y_obtener_limite(self, dbtmp):
        dbtmp.guardar_limite_diario_gemini(15)
        assert dbtmp.obtener_limite_diario_gemini() == 15

    def test_marcar_agotado_y_consultarlo(self, dbtmp):
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-a") is False
        dbtmp.marcar_gemini_agotado("modelo-a", limite_real=20)
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-a") is True
        assert dbtmp.uso_gemini_hoy_por_modelo()["modelo-a"]["limite_conocido"] == 20
        # Un modelo distinto no se ve afectado.
        assert dbtmp.modelo_gemini_agotado_hoy("modelo-b") is False

    def test_marcar_agotado_tras_uso_previo_conserva_el_contador(self, dbtmp):
        dbtmp.registrar_uso_gemini("modelo-a")
        dbtmp.registrar_uso_gemini("modelo-a")
        dbtmp.marcar_gemini_agotado("modelo-a", limite_real=20)

        uso = dbtmp.uso_gemini_hoy_por_modelo()["modelo-a"]
        assert uso["usados"] == 2
        assert uso["agotado"] is True
        assert uso["limite_conocido"] == 20

    def test_contador_se_reinicia_al_cambiar_de_dia(self, dbtmp):
        dbtmp.registrar_uso_gemini("modelo-a")
        dbtmp.registrar_uso_gemini("modelo-a")
        assert dbtmp.uso_gemini_hoy_por_modelo()["modelo-a"]["usados"] == 2

        # Simula que la última llamada registrada fue "ayer".
        with dbtmp.get_conn() as conn:
            conn.execute("UPDATE uso_gemini_diario SET fecha='2000-01-01' WHERE modelo='modelo-a'")

        assert dbtmp.uso_gemini_hoy_por_modelo() == {}  # ya no cuenta el registro de "ayer"
        assert dbtmp.registrar_uso_gemini("modelo-a") == 1  # arranca de nuevo, no sigue en 3


def _crear_item_pendiente(db, cuenta_id, fecha, tipo="texto"):
    db.crear_items_plan_dia(cuenta_id, fecha, tipo, 1)
    return db.listar_plan_dia(cuenta_id, fecha)[-1]


class TestDailyAntesLaCuotaAgotada:
    def test_generar_item_no_marca_error_y_deja_pendiente(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("cuota_item@test.com", "h", "s")
        fecha = daily.hoy()
        item = _crear_item_pendiente(db, cid, fecha)

        monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema")
        monkeypatch.setattr(
            daily.llm, "generar_variantes_texto",
            lambda *a, **k: (_ for _ in ()).throw(daily.llm.CuotaGeminiAgotada("límite diario alcanzado")),
        )

        resultado = daily.generar_item(cid, item, publicar=False)

        assert resultado["estado"] == "cuota_agotada"
        assert "límite diario" in resultado["error"]
        item_en_bd = db.listar_plan_dia(cid, fecha)[0]
        assert item_en_bd["estado"] == "pendiente"  # NO quedó marcado como 'error'
        assert item_en_bd["error"] is None

    def test_generar_lote_corta_la_tanda_al_agotarse_la_cuota(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("cuota_lote@test.com", "h", "s")
        monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema")

        llamadas = {"n": 0}

        def variantes(*a, **k):
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                raise daily.llm.CuotaGeminiAgotada("cuota agotada")
            return ["Texto ok"]

        monkeypatch.setattr(daily.llm, "generar_variantes_texto", variantes)

        resultados = daily.generar_lote(cid, ["texto", "texto", "texto"], publicar=False)

        assert [r["estado"] for r in resultados] == ["generado", "cuota_agotada"]
        assert llamadas["n"] == 2  # el tercero nunca se intentó

    def test_generar_pendientes_del_dia_corta_y_deja_el_resto_intacto(self, dbtmp, monkeypatch):
        import daily

        db = dbtmp
        cid = db.crear_cuenta("cuota_dia@test.com", "h", "s")
        fecha = daily.hoy()
        db.crear_items_plan_dia(cid, fecha, "texto", 3)

        monkeypatch.setattr(daily.llm, "sugerir_tema_automatico", lambda *a, **k: "Tema")

        llamadas = {"n": 0}

        def variantes(*a, **k):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise daily.llm.CuotaGeminiAgotada("cuota agotada")
            return ["Texto ok"]

        monkeypatch.setattr(daily.llm, "generar_variantes_texto", variantes)

        resultados = daily.generar_pendientes_del_dia(cid, fecha, publicar=False)

        assert len(resultados) == 1
        assert resultados[0]["estado"] == "cuota_agotada"
        plan_final = db.listar_plan_dia(cid, fecha)
        estados = sorted(i["estado"] for i in plan_final)
        assert estados == ["pendiente", "pendiente", "pendiente"]  # ninguno se tocó ni marcó error


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
