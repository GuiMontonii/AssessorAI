from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    status: str
    resumo: str | None = None
    iniciada_em: datetime | None = None
    encerrada_em: datetime | None = None


class ChatRequest(BaseModel):
    """O que o navegador envia no POST /chat."""

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Identifica a conversa atual.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_id: str = Field(
        default="usuario_teste",
        min_length=1,
        max_length=120,
        description=(
            "Identifica o usuario de forma estavel entre sessoes. "
            "E o que permite a memoria de longo prazo funcionar."
        ),
        examples=["usuario_teste"],
    )
    pergunta: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="Mensagem do usuario.",
        examples=["gastei 50 reais no mercado hoje"],
    )


class ChatResponse(BaseModel):
    session_id: str
    resposta: str
    agentes_chamados: list[str] = Field(default_factory=list)
    rota: str | None = None


class HistoryItem(BaseModel):
    doc_id: str
    session_id: str | None = None
    iniciada_em: datetime | str | None = None
    encerrada_em: datetime | str | None = None
    resumo: str
    score: float | None = None


class HistoryResponse(BaseModel):
    identifier: str
    itens: list[HistoryItem]

class PerfilRequest(BaseModel):
    user_id: str = Field(...,
        min_length=1,
        max_length=120,
    )

    renda_mensal: float = Field(...,
        gt=0,
    )

    objetivo: str = Field(...,
        min_length=1,
        max_length=120,
    )

    tolerancia_risco: Literal["baixa", "media", "alta"]

    preferencias: str = Field(...,
        min_length=1,
    )