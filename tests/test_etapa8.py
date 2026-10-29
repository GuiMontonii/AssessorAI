"""Testes isolados da Etapa 8; nao acessam APIs externas nem banco real."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
import types
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Apenas para poder rodar os testes de regras em ambientes sem as dependencias completas.
# Em Windows, com requirements.txt instalado, importam-se as classes reais.
if importlib.util.find_spec("langchain") is None:
    langchain = types.ModuleType("langchain")
    langchain.__path__ = []
    langchain_tools = types.ModuleType("langchain.tools")

    class ToolRuntime:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

    langchain_tools.ToolRuntime = ToolRuntime
    langchain.tools = langchain_tools
    sys.modules["langchain"] = langchain
    sys.modules["langchain.tools"] = langchain_tools

if importlib.util.find_spec("langchain_core") is None:
    core = types.ModuleType("langchain_core")
    core.__path__ = []
    core_tools = types.ModuleType("langchain_core.tools")
    core_tools.tool = lambda func: func
    core.tools = core_tools
    sys.modules["langchain_core"] = core
    sys.modules["langchain_core.tools"] = core_tools

if importlib.util.find_spec("psycopg2") is None:
    psycopg = types.ModuleType("psycopg2")
    ext = types.ModuleType("psycopg2.extensions")
    ext.connection = object
    psycopg.extensions = ext
    sys.modules["psycopg2"] = psycopg
    sys.modules["psycopg2.extensions"] = ext

from app.context import AgentContext
from app.tools import cambio, pendencias
from app.tools import agenda, financeiro
from app import juiz


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        q = " ".join(sql.lower().split())
        if q.startswith("insert into escritas_turno"):
            turno, sessao, usuario = params
            if turno in self.database["ledger"]:
                self.result = None
            else:
                self.database["ledger"][turno] = [sessao, usuario, []]
                self.result = (turno,)
        elif q.startswith("select session_id, user_id, resultados from escritas_turno"):
            self.result = self.database["ledger"].get(params[0])
        elif q.startswith("update escritas_turno set resultados"):
            resultados, turno = params
            self.database["ledger"][turno][2] = json.loads(resultados)
            self.result = None
        elif q.startswith("select moeda_original from transactions"):
            transacao = self.database["transactions"].get(params[0])
            self.result = ((transacao["moeda_original"],) if transacao and transacao["user_id"] == params[1] else None)
        else:
            raise AssertionError(f"SQL inesperado no teste: {q}")

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, store):
        self.store = store
        self.dados = copy.deepcopy(store)

    def cursor(self):
        return FakeCursor(self.dados)


class BaseTests(unittest.TestCase):
    def setUp(self):
        self.store = {"ledger": {}, "transactions": {}, "events": {}}
        self.usuarios = []

    @contextmanager
    def get_conn(self):
        conn = FakeConnection(self.store)
        try:
            yield conn
        except Exception:
            raise
        else:
            self.store.clear()
            self.store.update(copy.deepcopy(conn.dados))

    @staticmethod
    def fake_add_transaction(user_id, tipo, valor, descricao, categoria="geral", conn=None, **kwargs):
        ids = list(conn.dados["transactions"].keys())
        proximo = max(ids, default=0) + 1
        record = {
            "id": proximo, "user_id": user_id, "tipo": tipo,
            "valor": str(valor), "descricao": descricao, "categoria": categoria,
            "moeda_original": kwargs.get("moeda_original", "BRL"),
            "valor_original": str(kwargs.get("valor_original", valor)),
            "taxa_cambio": str(kwargs["taxa_cambio"]) if kwargs.get("taxa_cambio") else None,
            "data_cotacao": kwargs["data_cotacao"].isoformat() if kwargs.get("data_cotacao") else None,
            "fonte_cotacao": kwargs.get("fonte_cotacao"),
        }
        conn.dados["transactions"][proximo] = record
        return {"status": "ok", "transacao": record}

    @staticmethod
    def fake_update_transaction(user_id, transaction_id, conn=None, **kwargs):
        if kwargs.get("descricao") == "FALHAR":
            return {"status": "erro", "erro": "erro simulado apos a primeira acao"}
        transacao = conn.dados["transactions"].get(transaction_id)
        if not transacao or transacao["user_id"] != user_id:
            return {"status": "erro", "erro": "transacao nao encontrada"}
        for chave in ("valor", "descricao", "categoria", "tipo"):
            if kwargs.get(chave) is not None:
                transacao[chave] = str(kwargs[chave]) if chave == "valor" else kwargs[chave]
        return {"status": "ok", "transacao": transacao.copy()}

    @staticmethod
    def fake_add_event(user_id, titulo, inicio, fim, descricao="", conn=None):
        if inicio > fim:
            return {"status": "erro", "erro": "intervalo invalido"}
        for evento in conn.dados["events"].values():
            if evento["user_id"] == user_id and inicio < evento["fim"] and fim > evento["inicio"]:
                return {"status": "conflito", "erro": "conflito de agenda"}
        proximo = max(conn.dados["events"].keys(), default=0) + 1
        record = {"id": proximo, "user_id": user_id, "titulo": titulo,
                  "inicio": inicio, "fim": fim, "descricao": descricao}
        conn.dados["events"][proximo] = record
        return {"status": "ok", "evento": {**record, "inicio": inicio.isoformat(), "fim": fim.isoformat()}}

    def confirmar(self, pendentes, turno="turno1"):
        with patch("app.tools.db.get_conn", self.get_conn), \
             patch("app.tools.financeiro.add_transaction_db", self.fake_add_transaction), \
             patch("app.tools.financeiro.update_transaction_db", self.fake_update_transaction), \
             patch("app.tools.agenda.add_event_db", self.fake_add_event):
            return pendencias.confirmar_escritas(turno, "sessao1", "usuario1", pendentes)

    def contexto(self, turno="turno1", moeda=None):
        return AgentContext("usuario1", "sessao1", turno, moeda)

    def nova_acao(self, contexto, descricao="ET8-novo", valor="10.00"):
        return pendencias.preparar_escrita(contexto, "add_transaction", {
            "tipo": "saida", "valor": valor, "descricao": descricao,
            "categoria": "geral", "moeda_original": "BRL", "valor_original": valor,
            "taxa_cambio": None, "data_cotacao": None, "fonte_cotacao": None,
        })

    def test_preparar_nao_grava_e_contextos_nao_compartilham_listas(self):
        c1, c2 = self.contexto(), self.contexto("turno2")
        resposta = self.nova_acao(c1)
        self.assertEqual(resposta["status"], "pendente")
        self.assertEqual(len(c1.escritas_pendentes), 1)
        self.assertEqual(c2.escritas_pendentes, [])
        self.assertEqual(self.store["transactions"], {})

    def test_same_tool_called_twice_in_one_turn_does_not_duplicate(self):
        c = self.contexto()
        self.nova_acao(c)
        self.nova_acao(c)
        self.assertEqual(len(c.escritas_pendentes), 1)
        self.confirmar(c.escritas_pendentes)
        self.assertEqual(len(self.store["transactions"]), 1)

    def test_add_approved_once_and_replay_same_turn(self):
        c = self.contexto()
        self.nova_acao(c)
        resultado = self.confirmar(c.escritas_pendentes)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(len(self.store["transactions"]), 1)
        self.assertEqual(self.confirmar(c.escritas_pendentes), resultado)
        self.assertEqual(len(self.store["transactions"]), 1)

    def test_atomic_rollback_when_second_action_fails(self):
        c = self.contexto()
        self.nova_acao(c)
        pendencias.preparar_escrita(c, "update_transaction", {
            "transaction_id": 999, "descricao": "FALHAR", "valor": None,
        })
        with self.assertRaises(pendencias.ConfirmacaoRecusada):
            self.confirmar(c.escritas_pendentes)
        self.assertEqual(self.store["transactions"], {})
        self.assertEqual(self.store["ledger"], {})

    def test_update_success(self):
        self.store["transactions"][7] = {
            "id": 7, "user_id": "usuario1", "tipo": "saida", "valor": "20.00",
            "descricao": "antiga", "moeda_original": "BRL",
        }
        c = self.contexto()
        pendencias.preparar_escrita(c, "update_transaction", {
            "transaction_id": 7, "valor": None, "descricao": "nova",
            "tipo": None, "categoria": None,
        })
        self.confirmar(c.escritas_pendentes)
        self.assertEqual(self.store["transactions"][7]["descricao"], "nova")

    def test_event_success_and_conflict_rollback(self):
        c = self.contexto()
        dados = {"titulo": "ET8-agenda", "inicio": "2026-11-03T10:00:00+00:00",
                 "fim": "2026-11-03T11:00:00+00:00", "descricao": ""}
        pendencias.preparar_escrita(c, "add_event", dados)
        self.confirmar(c.escritas_pendentes)
        self.assertEqual(len(self.store["events"]), 1)
        c2 = self.contexto("turno2")
        self.nova_acao(c2, descricao="nao pode persistir")
        pendencias.preparar_escrita(c2, "add_event", dados)
        with self.assertRaises(pendencias.ConfirmacaoRecusada):
            self.confirmar(c2.escritas_pendentes, turno="turno2")
        self.assertEqual(len(self.store["events"]), 1)
        self.assertEqual(len(self.store["transactions"]), 0)

    def test_turn_mismatch_rejected_before_opening_db(self):
        c = self.contexto("outra_tentativa")
        self.nova_acao(c)
        with self.assertRaises(ValueError):
            self.confirmar(c.escritas_pendentes)

    def test_update_usd_requires_explicit_currency(self):
        self.store["transactions"][7] = {"id": 7, "user_id": "usuario1", "tipo": "saida",
                                          "valor": "35.00", "moeda_original": "USD"}
        c = self.contexto()
        pendencias.preparar_escrita(c, "update_transaction", {
            "transaction_id": 7, "valor": "40.00", "valor_original": "8.00",
            "moeda_explicita": False, "moeda_original": "BRL",
        })
        with self.assertRaises(pendencias.ConfirmacaoRecusada):
            self.confirmar(c.escritas_pendentes)
        self.assertEqual(self.store["transactions"][7]["valor"], "35.00")


class ToolBoundaryTests(unittest.TestCase):
    @staticmethod
    def get_callable(tool):
        return getattr(tool, "func", tool)

    def test_finance_tool_prepares_without_db_write(self):
        contexto = AgentContext("usuario1", "sessao1", "turno1", "USD")
        runtime = types.SimpleNamespace(context=contexto)
        with patch("app.tools.cambio._cotacao_usd_brl", return_value=(Decimal("5.25"), date(2026,10,29))):
            resultado = self.get_callable(financeiro.add_transaction)(
                tipo="saida", valor=5, descricao="ET8-USD-001", runtime=runtime,
            )
        self.assertEqual(resultado["status"], "pendente")
        self.assertEqual(contexto.escritas_pendentes[0]["dados"]["valor"], "26.25")
        self.assertEqual(contexto.escritas_pendentes[0]["dados"]["moeda_original"], "USD")

    def test_financeiro_accepts_common_expense_terms(self):
        runtime = types.SimpleNamespace(context=AgentContext("usuario1", "sessao1", "turno-alias", "BRL"))
        ferramenta = self.get_callable(financeiro.add_transaction)
        for tipo in ("saida", "saída", "despesa", "gasto", "compra"):
            resultado = ferramenta(tipo=tipo, valor=100, descricao="camiseta da Zara", runtime=runtime)
            self.assertEqual(resultado["status"], "pendente")
            self.assertEqual(resultado["dados"]["tipo"], "saida")
        self.assertEqual(len(runtime.context.escritas_pendentes), 1)

    def test_financeiro_does_not_accept_unknown_type(self):
        runtime = types.SimpleNamespace(context=AgentContext("usuario1", "sessao1", "turno-invalido", "BRL"))
        ferramenta = self.get_callable(financeiro.add_transaction)
        resultado = ferramenta(tipo="outro", valor=100, descricao="camiseta", runtime=runtime)
        self.assertEqual(resultado["status"], "erro")
        self.assertEqual(runtime.context.escritas_pendentes, [])

    def test_update_accepts_expense_alias(self):
        runtime = types.SimpleNamespace(context=AgentContext("usuario1", "sessao1", "turno-update", "BRL"))
        ferramenta = self.get_callable(financeiro.update_transaction)
        resultado = ferramenta(transaction_id=8, runtime=runtime, tipo="despesa")
        self.assertEqual(resultado["status"], "pendente")
        self.assertEqual(resultado["dados"]["tipo"], "saida")

    def test_agenda_tool_prepares_without_db_write(self):
        contexto = AgentContext("usuario1", "sessao1", "turno2")
        runtime = types.SimpleNamespace(context=contexto)
        resultado = self.get_callable(agenda.add_event)(
            "ET8-evento", "2026-11-03T10:00:00-03:00",
            "2026-11-03T11:00:00-03:00", runtime,
        )
        self.assertEqual(resultado["status"], "pendente")
        self.assertEqual(len(contexto.escritas_pendentes), 1)

    def test_update_tool_prepares_without_db_write(self):
        contexto = AgentContext("usuario1", "sessao1", "turno3", "BRL")
        runtime = types.SimpleNamespace(context=contexto)
        resultado = self.get_callable(financeiro.update_transaction)(
            transaction_id=8, runtime=runtime, valor=20,
        )
        self.assertEqual(resultado["status"], "pendente")
        self.assertEqual(contexto.escritas_pendentes[0]["operacao"], "update_transaction")


class CurrencyTests(unittest.TestCase):
    def test_detect_usd_and_brl_and_mixed(self):
        self.assertEqual(cambio.moeda_da_mensagem("comprei por US$ 5"), "USD")
        self.assertEqual(cambio.moeda_da_mensagem("gastei 5 dólares"), "USD")
        self.assertEqual(cambio.moeda_da_mensagem("R$ 5 reais"), "BRL")
        self.assertEqual(cambio.moeda_da_mensagem("5 dolares e 10 reais"), "MISTO")

    def test_converts_using_external_rate_not_prompt(self):
        with patch("app.tools.cambio._cotacao_usd_brl", return_value=(Decimal("5.25"), date(2026,10,29))):
            result = cambio.normalizar_valor(5, "BRL", "USD")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["valor"], "26.25")
        self.assertEqual(result["valor_original"], "5.00")
        self.assertEqual(result["moeda_original"], "USD")
        self.assertEqual(result["data_cotacao"], "2026-10-29")

    def test_cambio_unavailable_does_not_turn_usd_into_brl(self):
        with patch("app.tools.cambio._cotacao_usd_brl", side_effect=TimeoutError):
            result = cambio.normalizar_valor(5, "BRL", "USD")
        self.assertEqual(result["status"], "erro")
        self.assertNotIn("valor", result)

    def test_brl_no_conversion_and_mixed_rejected(self):
        self.assertEqual(cambio.normalizar_valor(5, "BRL", "BRL")["valor"], "5.00")
        self.assertEqual(cambio.normalizar_valor(5, "BRL", "MISTO")["status"], "erro")


class JudgeTests(unittest.TestCase):
    def fake_jev(self, autorizado=0.9, supported=0.9, choice="apoiada"):
        data = {"answers": {"veredito": {"choice": choice}, "apoiada": {"noul": supported},
                            "autorizar_escritas": {"noul": autorizado}}}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(data).encode()
        return Response()

    def test_no_key_fails_closed(self):
        with patch.object(juiz, "TYPESAFE_API_KEY", ""):
            outcome = juiz._julgar_jev("oi", "olá", "evidencia")
        self.assertFalse(outcome["juiz_aprovado"])

    def test_approves_only_if_both_answer_and_write_are_approved(self):
        with patch.object(juiz, "TYPESAFE_API_KEY", "teste"), \
             patch("app.juiz.urllib.request.urlopen", return_value=self.fake_jev()):
            resultado = juiz._julgar_jev("gastei 5", "preparado", "tool pendente", [{"operacao":"add_transaction"}])
        self.assertTrue(resultado["juiz_aprovado"])

    def test_rejects_write_even_if_answer_supported(self):
        with patch.object(juiz, "TYPESAFE_API_KEY", "teste"), \
             patch("app.juiz.urllib.request.urlopen", return_value=self.fake_jev(autorizado=0.1)):
            resultado = juiz._julgar_jev("gastei 5", "preparado", "tool pendente", [{"operacao":"add_transaction"}])
        self.assertFalse(resultado["juiz_aprovado"])
        self.assertEqual(resultado["messages"][-1]["content"], juiz.FRASE_SEGURA)


class GraphBoundaryTests(unittest.TestCase):
    def setUp(self):
        node = next(n for n in ast.parse((ROOT / "app/graph.py").read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "no_confirmar_escritas")
        module = ast.Module(body=[node], type_ignores=[])
        ns = {
            "Estado": dict, "Any": object,
            "ConfirmacaoRecusada": pendencias.ConfirmacaoRecusada,
            "guardrail_saida": lambda txt, mapa: txt,
            "AIMessage": lambda content: {"content": content},
            "resposta_confirmada": lambda r: "confirmado!",
            "logger": types.SimpleNamespace(exception=lambda *args: None),
        }
        exec(compile(module, "graph.py", "exec"), ns)
        self.func = ns["no_confirmar_escritas"]
        self.ns = ns

    def test_judge_rejection_cannot_call_db(self):
        self.ns["confirmar_escritas"] = lambda *args: self.fail("DB nao pode ser chamada")
        result = self.func({"escritas_pendentes": [{"operacao": "add_transaction"}], "juiz_aprovado": False})
        self.assertEqual(result["escritas_pendentes"], [])

    def test_judge_approval_calls_commit(self):
        chamadas = []
        self.ns["confirmar_escritas"] = lambda *args: chamadas.append(args) or [{"operacao":"add_transaction"}]
        state = {"escritas_pendentes": [{"operacao":"add_transaction"}], "juiz_aprovado": True,
                 "turno_id": "t1", "session_id": "s1", "user_id": "u1", "agentes_chamados": []}
        resultado = self.func(state)
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(resultado["resposta"], "confirmado!")
        self.assertNotIn("confirmar_escritas:erro", resultado["agentes_chamados"])

    def test_db_failure_returns_safe_message_without_leaking_details(self):
        def falhar(*args):
            raise ConnectionError("senha=SEGREDO")

        self.ns["confirmar_escritas"] = falhar
        state = {"escritas_pendentes": [{"operacao": "add_transaction"}], "juiz_aprovado": True,
                 "turno_id": "t1", "session_id": "s1", "user_id": "u1", "agentes_chamados": []}
        resultado = self.func(state)
        self.assertIn("Nao foi possivel confirmar", resultado["resposta"])
        self.assertNotIn("SEGREDO", resultado["resposta"])
        self.assertIn("confirmar_escritas:erro", resultado["agentes_chamados"])
        self.assertEqual(resultado["escritas_pendentes"], [])

    def test_business_rejection_keeps_existing_behavior(self):
        def recusar(*args):
            raise pendencias.ConfirmacaoRecusada("conflito de agenda")

        self.ns["confirmar_escritas"] = recusar
        state = {"escritas_pendentes": [{"operacao": "add_event"}], "juiz_aprovado": True,
                 "turno_id": "t1", "session_id": "s1", "user_id": "u1", "agentes_chamados": []}
        resultado = self.func(state)
        self.assertIn("conflito de agenda", resultado["resposta"])
        self.assertNotIn("confirmar_escritas:erro", resultado["agentes_chamados"])

    def test_monitor_marks_db_failure_as_error(self):
        node = next(n for n in ast.parse((ROOT / "app/observabilidade.py").read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "status_do_estado")
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "observabilidade.py", "exec"), ns)
        status = ns["status_do_estado"]
        self.assertEqual(status({"agentes_chamados": ["confirmar_escritas:erro"]}), "erro")
        self.assertEqual(status({"agentes_chamados": ["confirmar_escritas"]}), "ok")
        self.assertEqual(status({"bloqueado": True}), "bloqueado")


if __name__ == "__main__":
    unittest.main()
