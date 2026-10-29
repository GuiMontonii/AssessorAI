from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_FAST_MODEL,
    GROQ_SPECIALIST_MODEL,
)


class LLMConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def llm_gemini() -> BaseChatModel:
    if not GEMINI_API_KEY:
        raise LLMConfigurationError("GEMINI_API_KEY nao configurada.")
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=0.7,
        top_p=0.95,
        google_api_key=GEMINI_API_KEY,
    )


@lru_cache(maxsize=1)
def llm_groq_especialista() -> BaseChatModel:
    if not GROQ_API_KEY:
        raise LLMConfigurationError("GROQ_API_KEY nao configurada.")
    return ChatGroq(
        model=GROQ_SPECIALIST_MODEL,
        temperature=0.7,
        api_key=GROQ_API_KEY,
    )


@lru_cache(maxsize=1)
def llm_groq_rapido() -> BaseChatModel:
    if not GROQ_API_KEY:
        raise LLMConfigurationError("GROQ_API_KEY nao configurada.")
    return ChatGroq(
        model=GROQ_FAST_MODEL,
        temperature=0.0,
        api_key=GROQ_API_KEY,
    )


def specialist_models() -> list[BaseChatModel]:
    modelos: list[BaseChatModel] = []
    for factory in (llm_gemini, llm_groq_especialista):
        try:
            modelos.append(factory())
        except LLMConfigurationError:
            continue
    if not modelos:
        raise LLMConfigurationError(
            "Configure GEMINI_API_KEY ou GROQ_API_KEY para usar os agentes."
        )
    return modelos


def fast_models() -> list[BaseChatModel]:
    modelos: list[BaseChatModel] = []
    for factory in (llm_groq_rapido, llm_gemini):
        try:
            modelos.append(factory())
        except LLMConfigurationError:
            continue
    if not modelos:
        raise LLMConfigurationError(
            "Configure GROQ_API_KEY ou GEMINI_API_KEY para usar os agentes."
        )
    return modelos


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes: list[str] = []
        for item in content:
            if isinstance(item, str):
                partes.append(item)
            elif isinstance(item, dict):
                texto = item.get("text")
                if texto:
                    partes.append(str(texto))
            else:
                texto = getattr(item, "text", None)
                if texto:
                    partes.append(str(texto))
        return "\n".join(partes)
    return str(content)


def invoke_with_fallback(
    models: Iterable[BaseChatModel],
    messages: list[dict[str, str]],
) -> str:
    errors: list[str] = []
    for model in models:
        try:
            response = model.invoke(messages)
            return _content_to_text(response.content).strip()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    raise RuntimeError("Todos os provedores de LLM falharam: " + " | ".join(errors))


def invoke_fast(system_prompt: str, user_prompt: str) -> str:
    return invoke_with_fallback(
        fast_models(),
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
