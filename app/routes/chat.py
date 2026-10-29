from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.graph import executar_fluxo
from app.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    try:
        result = await run_in_threadpool(
            executar_fluxo,
            payload.pergunta,
            payload.session_id,
            payload.user_id,
        )
        return ChatResponse(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao processar conversa")
        raise HTTPException(
            status_code=500,
            detail=(
                "Nao foi possivel processar a conversa. "
                "Confira os servicos e as configuracoes no terminal do FastAPI."
            ),
        ) from exc
