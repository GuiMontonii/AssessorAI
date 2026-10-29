from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage

from app.context import AgentContext
from app.llms import fast_models, specialist_models
from app.prompts import (
    AGENDA_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    ROUTER_PROMPT_COMPLETO,
)
from app.tools.agenda import TOOLS_AGENDA
from app.tools.faq import TOOLS_FAQ
from app.tools.financeiro import TOOLS
from app.tools.memoria import TOOLS_MEMORIA
from app.tools.perfil import TOOLS_PERFIL

Route = Literal["FINANCEIRO", "AGENDA", "FAQ", "GERAL", "FORA_ESCOPO"]


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif getattr(item, "text", None):
                parts.append(str(item.text))
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_final(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    return _message_text(messages[-1])


@lru_cache(maxsize=8)
def _router_agent(model_index: int):
    models = fast_models()
    return create_agent(
        model=models[model_index],
        tools=[],
        system_prompt=ROUTER_PROMPT_COMPLETO,
    )


@lru_cache(maxsize=8)
def _orchestrator_agent(model_index: int):
    models = fast_models()
    return create_agent(
        model=models[model_index],
        tools=TOOLS_MEMORIA,
        system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
    )


@lru_cache(maxsize=8)
def _finance_agent(model_index: int):
    models = specialist_models()
    return create_agent(
        model=models[model_index],
        tools=TOOLS + TOOLS_PERFIL,
        system_prompt=FINANCEIRO_PROMPT_COMPLETO,
        context_schema=AgentContext,
    )


@lru_cache(maxsize=8)
def _agenda_agent(model_index: int):
    models = specialist_models()
    return create_agent(
        model=models[model_index],
        tools=TOOLS_AGENDA,
        system_prompt=AGENDA_PROMPT_COMPLETO,
        context_schema=AgentContext,
    )


@lru_cache(maxsize=8)
def _faq_agent(model_index: int):
    models = fast_models()
    return create_agent(
        model=models[model_index],
        tools=TOOLS_FAQ,
        system_prompt=FAQ_PROMPT_COMPLETO,
    )


def _invoke_agent_with_fallback(
    factory,
    model_count: int,
    payload: str,
    context: AgentContext | None = None,
    configurable: dict[str, Any] | None = None,
    mensagens_evidencia: list[Any] | None = None,
) -> str:
    errors: list[str] = []
    for index in range(model_count):
        if context is not None:
            context.escritas_pendentes.clear()
        try:
            agent = factory(index)
            kwargs: dict[str, Any] = {}
            if context is not None:
                kwargs["context"] = context
            if configurable:
                kwargs["config"] = {"configurable": configurable}
            result = agent.invoke(
                {"messages": [{"role": "user", "content": payload}]},
                **kwargs,
            )
            final = _extract_final(result)
            if final:
                if mensagens_evidencia is not None:
                    # Sem registrar prompts dos agentes nem outras sessoes.
                    for mensagem in result.get("messages") or []:
                        if isinstance(mensagem, ToolMessage):
                            mensagens_evidencia.append(mensagem)
                        elif isinstance(mensagem, AIMessage) and mensagem.tool_calls:
                            mensagens_evidencia.append(mensagem)
                return final
        except Exception as exc:
            if context is not None:
                context.escritas_pendentes.clear()
            errors.append(f"{type(exc).__name__}: {exc}")
    if context is not None:
        context.escritas_pendentes.clear()
    raise RuntimeError("Falha nos modelos do agente: " + " | ".join(errors))


def _keyword_route(question: str) -> Route:
    text = question.lower()
    faq_words = (
        "assessor.ai",
        "assessor ai",
        "como funciona",
        "privacidade",
        "memoria",
        "qdrant",
        "mongodb",
        "documentacao",
        "api",
        "suporte",
    )
    agenda_words = (
        "agenda",
        "compromisso",
        "evento",
        "reuniao",
        "horario",
        "amanha",
        "calendario",
        "livre",
    )
    finance_words = (
        "gastei",
        "gasto",
        "despesa",
        "comprei",
        "paguei",
        "recebi",
        "salario",
        "saldo",
        "divida",
        "orcamento",
        "transacao",
        "finance",
        "dinheiro",
        "reais",
        "r$",
    )
    if any(word in text for word in faq_words):
        return "FAQ"
    if any(word in text for word in agenda_words):
        return "AGENDA"
    if any(word in text for word in finance_words):
        return "FINANCEIRO"
    if any(word in text for word in ("oi", "ola", "bom dia", "boa tarde", "boa noite")):
        return "GERAL"
    return "FORA_ESCOPO"


def classificar_rota(question: str) -> Route:
    try:
        models = fast_models()
        raw = _invoke_agent_with_fallback(_router_agent, len(models), question)
        upper = raw.upper().replace("-", "_")
        for route in ("FINANCEIRO", "AGENDA", "FAQ", "GERAL", "FORA_ESCOPO"):
            if route in upper:
                return route  # type: ignore[return-value]
    except Exception:
        pass
    return _keyword_route(question)


def invoke_financeiro(
    question: str, memory: str, context: AgentContext,
    mensagens_evidencia: list[Any] | None = None,
) -> str:
    payload = f"MEMORIA RELEVANTE:\n{memory}\n\nMENSAGEM ATUAL:\n{question}"
    models = specialist_models()
    return _invoke_agent_with_fallback(
        _finance_agent,
        len(models),
        payload,
        context=context,
        mensagens_evidencia=mensagens_evidencia,
    )


def invoke_agenda(
    question: str, memory: str, context: AgentContext,
    mensagens_evidencia: list[Any] | None = None,
) -> str:
    payload = f"MEMORIA RELEVANTE:\n{memory}\n\nMENSAGEM ATUAL:\n{question}"
    models = specialist_models()
    return _invoke_agent_with_fallback(
        _agenda_agent,
        len(models),
        payload,
        context=context,
        mensagens_evidencia=mensagens_evidencia,
    )


def invoke_faq(
    question: str, memory: str,
    mensagens_evidencia: list[Any] | None = None,
) -> str:
    payload = f"MEMORIA RELEVANTE:\n{memory}\n\nPERGUNTA:\n{question}"
    models = fast_models()
    return _invoke_agent_with_fallback(
        _faq_agent, len(models), payload, mensagens_evidencia=mensagens_evidencia
    )


def invoke_orchestrator(
    *,
    question: str,
    route: Route,
    memory: str,
    specialist_response: str,
    user_id: str,
    session_id: str,
    mensagens_evidencia: list[Any] | None = None,
) -> str:
    payload = (
        f"ROTA: {route}\n\n"
        f"MEMORIA RELEVANTE:\n{memory}\n\n"
        f"MENSAGEM ATUAL:\n{question}\n\n"
        f"RESPOSTA DO ESPECIALISTA:\n{specialist_response or 'Nenhuma.'}"
    )
    models = fast_models()
    return _invoke_agent_with_fallback(
        _orchestrator_agent,
        len(models),
        payload,
        configurable={"thread_id": session_id, "user_id": user_id},
        mensagens_evidencia=mensagens_evidencia,
    )
