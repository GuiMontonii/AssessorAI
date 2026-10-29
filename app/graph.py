from __future__ import annotations

from typing import Any
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from app.observabilidade import abrir_turno, fechar_turno, status_do_estado

from app.agents import (
    classificar_rota,
    invoke_agenda,
    invoke_faq,
    invoke_financeiro,
    invoke_orchestrator,
)
from app.context import AgentContext
from app.guardrail import anonimizar_entrada, guardrail_entrada, guardrail_saida
from app.juiz import no_juiz
from app.llms import invoke_fast
from app.memory import (
    construir_contexto_memoria,
    encerrar_sessao,
    exigir_sessao,
    listar_mensagens,
    salvar_mensagem,
)
from app.prompts import SUMMARY_PROMPT
from app.tools.cambio import moeda_da_mensagem
from app.tools.pendencias import ConfirmacaoRecusada, confirmar_escritas, resposta_confirmada

logger = logging.getLogger(__name__)


class Estado(MessagesState):
    session_id: str
    user_id: str
    pergunta: str
    mapa_pii: dict[str, str]
    bloqueado: bool
    motivo_bloqueio: str
    memoria_contexto: str
    rota: str
    resposta_especialista: str
    resposta: str
    agentes_chamados: list[str]
    turno_id: str
    moeda_informada: str | None
    escritas_pendentes: list[dict[str, Any]]
    juiz_aprovado: bool


def no_guardrail_entrada(state: Estado) -> dict[str, Any]:
    decisao = guardrail_entrada(state["pergunta"])
    return {
        "bloqueado": not decisao.permitido,
        "motivo_bloqueio": decisao.motivo,
        "agentes_chamados": ["guardrail_entrada"],
    }


def decidir_pos_guardrail_entrada(state: Estado) -> str:
    return "bloqueado" if state.get("bloqueado") else "continuar"


def no_memoria(state: Estado) -> dict[str, Any]:
    contexto = construir_contexto_memoria(
        state["session_id"],
        state["user_id"],
        state["pergunta"],
    )
    return {
        "memoria_contexto": contexto,
        "agentes_chamados": state.get("agentes_chamados", []) + ["memoria"],
    }


def no_roteador(state: Estado) -> dict[str, Any]:
    rota = classificar_rota(state["pergunta"])
    return {
        "rota": rota,
        "agentes_chamados": state.get("agentes_chamados", []) + ["roteador"],
    }


def decidir_especialista(state: Estado) -> str:
    rota = str(state.get("rota", "FORA_ESCOPO"))
    if rota in {"FINANCEIRO", "AGENDA", "FAQ"}:
        return rota.lower()
    return "orquestrador"


def no_financeiro(state: Estado) -> dict[str, Any]:
    evidencias = []
    contexto = AgentContext(
        user_id=state["user_id"], session_id=state["session_id"],
        turno_id=state["turno_id"], moeda_informada=state.get("moeda_informada"),
    )
    resposta = invoke_financeiro(
        state["pergunta"], state.get("memoria_contexto", ""),
        contexto, mensagens_evidencia=evidencias,
    )
    return {
        "resposta_especialista": resposta,
        "escritas_pendentes": list(contexto.escritas_pendentes),
        "messages": evidencias,
        "agentes_chamados": state.get("agentes_chamados", []) + ["financeiro"],
    }


def no_agenda(state: Estado) -> dict[str, Any]:
    evidencias = []
    contexto = AgentContext(
        user_id=state["user_id"], session_id=state["session_id"],
        turno_id=state["turno_id"], moeda_informada=state.get("moeda_informada"),
    )
    resposta = invoke_agenda(
        state["pergunta"], state.get("memoria_contexto", ""),
        contexto, mensagens_evidencia=evidencias,
    )
    return {
        "resposta_especialista": resposta,
        "escritas_pendentes": list(contexto.escritas_pendentes),
        "messages": evidencias,
        "agentes_chamados": state.get("agentes_chamados", []) + ["agenda"],
    }


def no_faq(state: Estado) -> dict[str, Any]:
    evidencias = []
    resposta = invoke_faq(
        state["pergunta"], state.get("memoria_contexto", ""),
        mensagens_evidencia=evidencias,
    )
    return {
        "resposta_especialista": resposta,
        "resposta": resposta,
        "messages": [*evidencias, AIMessage(content=resposta)],
        "agentes_chamados": state.get("agentes_chamados", []) + ["faq"],
    }


def no_orquestrador(state: Estado) -> dict[str, Any]:
    evidencias = []
    resposta = invoke_orchestrator(
        question=state["pergunta"],
        route=state.get("rota", "FORA_ESCOPO"),  # type: ignore[arg-type]
        memory=state.get("memoria_contexto", ""),
        specialist_response=state.get("resposta_especialista", ""),
        user_id=state["user_id"],
        session_id=state["session_id"],
        mensagens_evidencia=evidencias,
    )
    return {
        "resposta": resposta,
        "messages": [*evidencias, AIMessage(content=resposta)],
        "agentes_chamados": state.get("agentes_chamados", []) + ["orquestrador"],
    }


def no_guardrail_saida(state: Estado) -> dict[str, Any]:
    if state.get("bloqueado"):
        resposta = state.get("motivo_bloqueio") or "Mensagem bloqueada pelo guardrail."
    else:
        resposta = state.get("resposta") or state.get("resposta_especialista") or ""

    resposta = guardrail_saida(resposta, state.get("mapa_pii", {}))
    return {
        "resposta": resposta,
        "messages": [AIMessage(content=resposta)],
        "agentes_chamados": state.get("agentes_chamados", []) + ["guardrail_saida"],
    }




def no_confirmar_escritas(state: Estado) -> dict[str, Any]:
    pendentes = state.get("escritas_pendentes") or []
    if not pendentes:
        return {"escritas_pendentes": []}
    if not state.get("juiz_aprovado"):
        return {"escritas_pendentes": []}
    erro_confirmacao = False
    try:
        resultados = confirmar_escritas(
            state["turno_id"], state["session_id"], state["user_id"], pendentes,
        )
    except ConfirmacaoRecusada as exc:
        texto = f"Nao foi possivel confirmar a operacao: {exc}. Nenhuma escrita deste turno foi aplicada."
    except Exception:
        logger.exception("Falha ao confirmar escritas no PostgreSQL")
        texto = (
            "Nao foi possivel confirmar se a operacao foi registrada. "
            "Consulte seus registros antes de tentar novamente."
        )
        erro_confirmacao = True
    else:
        texto = resposta_confirmada(resultados)
    texto = guardrail_saida(texto, state.get("mapa_pii", {}))
    agentes = state.get("agentes_chamados", []) + ["confirmar_escritas"]
    if erro_confirmacao:
        agentes.append("confirmar_escritas:erro")
    return {
        "resposta": texto,
        "messages": [AIMessage(content=texto)],
        "escritas_pendentes": [],
        "agentes_chamados": agentes,
    }


_builder = StateGraph(Estado)
_builder.add_node("guardrail_entrada", no_guardrail_entrada)
_builder.add_node("memoria", no_memoria)
_builder.add_node("roteador", no_roteador)
_builder.add_node("financeiro", no_financeiro)
_builder.add_node("agenda", no_agenda)
_builder.add_node("faq", no_faq)
_builder.add_node("orquestrador", no_orquestrador)
_builder.add_node("guardrail_saida", no_guardrail_saida)
_builder.add_node("juiz", no_juiz)
_builder.add_node("confirmar_escritas", no_confirmar_escritas)

_builder.add_edge(START, "guardrail_entrada")
_builder.add_conditional_edges(
    "guardrail_entrada",
    decidir_pos_guardrail_entrada,
    {"bloqueado": "guardrail_saida", "continuar": "memoria"},
)
_builder.add_edge("memoria", "roteador")
_builder.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda": "agenda",
        "faq": "faq",
        "orquestrador": "orquestrador",
    },
)
_builder.add_edge("financeiro", "orquestrador")
_builder.add_edge("agenda", "orquestrador")
_builder.add_edge("faq", "juiz")
_builder.add_edge("orquestrador", "guardrail_saida")
# Mensagem bloqueada na entrada termina no compliance, sem chamar a API do juiz.
_builder.add_conditional_edges(
    "guardrail_saida",
    decidir_pos_guardrail_entrada,
    {"bloqueado": END, "continuar": "juiz"},
)
_builder.add_edge("juiz", "confirmar_escritas")
_builder.add_edge("confirmar_escritas", END)

checkpointer = MemorySaver()
fluxo_agentes = _builder.compile(checkpointer=checkpointer)


def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> str:
    # Verificar a sessao ANTES das tools evita registrar transacoes de outra pessoa.
    sessao = exigir_sessao(session_id, ativa=True)
    if str(sessao.get("user_id")) != user_id:
        raise ValueError("O user_id informado nao pertence a esta sessao.")

    pergunta_usuario_anonimizado, mapa_pii = anonimizar_entrada(pergunta_usuario)
    turno_id = abrir_turno()
    estado_inicial = {
        "messages": [HumanMessage(content=pergunta_usuario_anonimizado)],
        "agentes_chamados": [],
        "rota": "",
        "resposta": "",
        "resposta_especialista": "",
        "bloqueado": False,
        "motivo_bloqueio": "",
        "memoria_contexto": "",
        "mapa_pii": mapa_pii,
        "pergunta": pergunta_usuario_anonimizado,
        "session_id": session_id,
        "user_id": user_id,
        "turno_id": turno_id,
        "moeda_informada": moeda_da_mensagem(pergunta_usuario),
        "escritas_pendentes": [],
        "juiz_aprovado": False,
    }

    status = "erro"
    rota = ""
    try:
        estado_final = fluxo_agentes.invoke(
            estado_inicial,
            config={"configurable": {"thread_id": session_id, "user_id": user_id}},
        )
        resposta = str(estado_final.get("resposta") or "").strip()
        if not resposta:
            raise RuntimeError("O fluxo terminou sem produzir uma resposta.")

        # A role 'ai' e permitida pelo schema de memoria existente.
        try:
            salvar_mensagem(session_id, "human", pergunta_usuario_anonimizado, user_id=user_id)
            salvar_mensagem(session_id, "ai", resposta, user_id=user_id)
        except Exception:
            logger.exception("Falha ao salvar historico no MongoDB; resposta do turno preservada")

        status = status_do_estado(estado_final)
        rota = estado_final.get("rota") or ""
        return resposta
    finally:
        fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)


def executar_fluxo(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> dict[str, Any]:
    """Compatibilidade com POST /chat, sem alterar executar_fluxo_assessor."""
    resposta = executar_fluxo_assessor(pergunta_usuario, session_id, user_id)
    estado = fluxo_agentes.get_state(
        config={"configurable": {"thread_id": session_id, "user_id": user_id}}
    ).values
    return {
        "session_id": session_id,
        "resposta": resposta,
        "agentes_chamados": estado.get("agentes_chamados", []),
        "rota": estado.get("rota") or None,
    }


def _fallback_summary(messages: list[dict[str, Any]]) -> str:
    human_parts: list[str] = []
    for message in messages:
        if message.get("role") in {"human", "usuario"}:
            safe, _ = anonimizar_entrada(str(message.get("content", "")))
            if safe.strip():
                human_parts.append(safe.strip())
    if not human_parts:
        return "Sessao encerrada sem conteudo relevante para memoria."

    compact = " | ".join(human_parts[-6:])
    return f"- Principais assuntos informados pelo usuario: {compact[:1800]}"


def gerar_resumo_e_encerrar(session_id: str) -> dict[str, Any]:
    sessao = exigir_sessao(session_id)
    if sessao.get("encerrada_em") is not None:
        return sessao

    messages = listar_mensagens(session_id)
    if not messages:
        resumo = "Sessao encerrada sem mensagens."
    else:
        safe_lines: list[str] = []
        for message in messages:
            safe, _ = anonimizar_entrada(str(message.get("content", "")))
            safe_lines.append(f"{message.get('role', 'unknown')}: {safe}")
        transcript = "\n".join(safe_lines[-40:])
        try:
            resumo = invoke_fast(SUMMARY_PROMPT, transcript)
        except Exception:
            resumo = _fallback_summary(messages)

    return encerrar_sessao(session_id, guardrail_saida(resumo))
