from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.graph import gerar_resumo_e_encerrar
from app.memory import exigir_sessao, iniciar_sessao, recuperar_historico
from app.schemas import HistoryItem, HistoryResponse, SessionCreateRequest, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_response(doc) -> SessionResponse:
    return SessionResponse(
        session_id=str(doc["session_id"]),
        user_id=str(doc["user_id"]),
        status="encerrada" if doc.get("encerrada_em") else "ativa",
        resumo=doc.get("resumo") or None,
        iniciada_em=doc.get("iniciada_em"),
        encerrada_em=doc.get("encerrada_em"),
    )


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(payload: SessionCreateRequest) -> SessionResponse:
    try:
        doc = await run_in_threadpool(iniciar_sessao, payload.user_id)
        return _session_response(doc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Nao foi possivel iniciar a sessao no MongoDB: {exc}",
        ) from exc


async def _close(session_id: str) -> SessionResponse:
    try:
        doc = await run_in_threadpool(gerar_resumo_e_encerrar, session_id)
        return _session_response(doc)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Nao foi possivel encerrar a sessao e indexar a memoria. "
                "Confira MongoDB, Gemini e Qdrant no terminal."
            ),
        ) from exc


# Mantem a rota que o frontend atual ja usa.
@router.delete("/{session_id}", response_model=SessionResponse)
async def close_session_delete(session_id: str) -> SessionResponse:
    return await _close(session_id)


# Alias pedido explicitamente nos testes da Etapa 4.
@router.post("/{session_id}/encerrar", response_model=SessionResponse)
async def close_session_post(session_id: str) -> SessionResponse:
    return await _close(session_id)


@router.get("/{session_id}/historico", response_model=HistoryResponse)
async def get_history(
    session_id: str,
    busca: str = Query(default="", max_length=1000),
    limite: int = Query(default=3, ge=1, le=20),
) -> HistoryResponse:
    try:
        sessao = await run_in_threadpool(exigir_sessao, session_id)
        user_id = str(sessao["user_id"])
        items = await run_in_threadpool(
            recuperar_historico,
            user_id,
            busca,
            limite,
        )
        return HistoryResponse(
            identifier=user_id,
            itens=[HistoryItem(**item) for item in items],
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
