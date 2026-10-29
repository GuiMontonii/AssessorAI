"""
Memoria de longo prazo do Assessor.AI.

Etapa 4:
- MongoDB continua guardando sessoes, mensagens completas e resumos.
- Qdrant Cloud guarda embeddings dos resumos para busca semantica.
- session_id identifica uma conversa.
- user_id identifica o mesmo usuario entre varias conversas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from qdrant_client import models

from app.config import MONGODB_COLLECTION, MONGODB_DB, MONGODB_URI
from app.guardrail import anonimizar_entrada
from app.vectorstore import (
    COLLECTION_MEMORIA,
    cliente_qdrant,
    garantir_collections,
    gerar_embedding,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(MONGODB_URI, serverSelectionTimeoutMS=4000)


@lru_cache(maxsize=1)
def get_sessions_collection() -> Collection:
    collection = get_mongo_client()[MONGODB_DB][MONGODB_COLLECTION]
    collection.create_index([("session_id", ASCENDING)], unique=True)
    collection.create_index([("user_id", ASCENDING), ("iniciada_em", DESCENDING)])
    collection.create_index([("user_id", ASCENDING), ("encerrada_em", DESCENDING)])
    return collection


def iniciar_sessao(user_id: str, session_id: str | None = None) -> dict[str, Any]:
    """Cria uma nova conversa no MongoDB para um user_id estavel."""
    user_id = user_id.strip()
    if not user_id:
        raise ValueError("user_id nao pode ser vazio.")

    sid = session_id or str(uuid.uuid4())
    agora = _utcnow()
    doc: dict[str, Any] = {
        # UUID em string: pode ser reutilizado como identificador do point no Qdrant.
        "_id": str(uuid.uuid4()),
        "session_id": sid,
        "user_id": user_id,
        "iniciada_em": agora,
        "atualizada_em": agora,
        "encerrada_em": None,
        "resumo": "",
        "mensagens": [],
    }
    get_sessions_collection().insert_one(doc)
    return doc


def obter_sessao(session_id: str) -> dict[str, Any] | None:
    return get_sessions_collection().find_one({"session_id": session_id})


def exigir_sessao(session_id: str, ativa: bool | None = None) -> dict[str, Any]:
    doc = obter_sessao(session_id)
    if not doc:
        raise LookupError("Sessao nao encontrada.")
    if ativa is True and doc.get("encerrada_em") is not None:
        raise LookupError("A sessao ja foi encerrada.")
    if ativa is False and doc.get("encerrada_em") is None:
        raise LookupError("A sessao ainda esta ativa.")
    return doc


def salvar_mensagem(
    session_id: str,
    role: str,
    content: str,
    user_id: str | None = None,
) -> None:
    """Adiciona uma mensagem a sessao atual, opcionalmente validando o user_id."""
    if role not in {"human", "ai", "system", "usuario", "assistente"}:
        raise ValueError("role de mensagem invalida.")

    sessao = exigir_sessao(session_id, ativa=True)
    if user_id and str(sessao.get("user_id")) != str(user_id):
        raise ValueError("O user_id informado nao pertence a esta sessao.")

    result = get_sessions_collection().update_one(
        {"session_id": session_id, "encerrada_em": None},
        {
            "$push": {
                "mensagens": {
                    "role": role,
                    "content": content,
                    "timestamp": _utcnow(),
                }
            },
            "$set": {"atualizada_em": _utcnow()},
        },
    )
    if result.modified_count != 1:
        raise RuntimeError("Nao foi possivel salvar a mensagem na sessao.")


def listar_mensagens(session_id: str, limite: int | None = None) -> list[dict[str, Any]]:
    doc = exigir_sessao(session_id)
    mensagens = list(doc.get("mensagens", []))
    if limite is not None and limite > 0:
        return mensagens[-limite:]
    return mensagens


def _qdrant_point_id(doc_id: str) -> str:
    """Usa o doc_id diretamente quando for UUID; gera UUID estavel para legado."""
    try:
        return str(uuid.UUID(doc_id))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"assessor-ai:{doc_id}"))


def encerrar_sessao(session_id: str, resumo: str) -> dict[str, Any]:
    """Persiste o resumo no MongoDB e o indexa semanticamente no Qdrant."""
    doc = exigir_sessao(session_id)
    if doc.get("encerrada_em") is not None:
        return doc

    resumo = resumo.strip()
    encerrada_em = _utcnow()
    get_sessions_collection().update_one(
        {"session_id": session_id, "encerrada_em": None},
        {
            "$set": {
                "encerrada_em": encerrada_em,
                "atualizada_em": encerrada_em,
                "resumo": resumo,
            }
        },
    )
    atualizado = exigir_sessao(session_id)

    if resumo:
        resumo_anonimo, _ = anonimizar_entrada(resumo)
        vetor = gerar_embedding(resumo_anonimo)
        garantir_collections()
        doc_id = str(atualizado["_id"])

        cliente_qdrant().upsert(
            collection_name=COLLECTION_MEMORIA,
            points=[
                models.PointStruct(
                    id=_qdrant_point_id(doc_id),
                    vector=vetor,
                    payload={
                        "doc_id": doc_id,
                        "user_id": str(atualizado["user_id"]),
                        "session_id": str(atualizado["session_id"]),
                        "resumo": resumo_anonimo,
                        "iniciada_em": (
                            atualizado["iniciada_em"].isoformat()
                            if atualizado.get("iniciada_em")
                            else ""
                        ),
                        "encerrada_em": encerrada_em.isoformat(),
                    },
                )
            ],
            wait=True,
        )

    return atualizado


def _historico_recente_mongo(user_id: str, limite: int) -> list[dict[str, Any]]:
    docs = (
        get_sessions_collection()
        .find(
            {"user_id": user_id, "resumo": {"$nin": ["", None]}},
            {
                "session_id": 1,
                "resumo": 1,
                "iniciada_em": 1,
                "encerrada_em": 1,
            },
        )
        .sort("iniciada_em", DESCENDING)
        .limit(limite)
    )
    return [
        {
            "doc_id": str(doc["_id"]),
            "session_id": doc.get("session_id"),
            "iniciada_em": doc.get("iniciada_em"),
            "encerrada_em": doc.get("encerrada_em"),
            "resumo": doc.get("resumo", ""),
            "score": None,
        }
        for doc in docs
    ]


def recuperar_historico(
    user_id: str,
    busca: str = "",
    limite: int = 3,
) -> list[dict[str, Any]]:
    """
    Recupera resumos de sessoes ANTERIORES do usuario.

    Com busca: usa Qdrant e similaridade semantica, filtrando pelo user_id.
    Sem busca: devolve as sessoes encerradas mais recentes pelo MongoDB.
    """
    user_id = user_id.strip()
    if not user_id or limite <= 0:
        return []

    busca = busca.strip()
    if busca:
        busca_anonima, _ = anonimizar_entrada(busca)
        vetor = gerar_embedding(busca_anonima)
        garantir_collections()
        resultados = cliente_qdrant().query_points(
            collection_name=COLLECTION_MEMORIA,
            query=vetor,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="user_id",
                        match=models.MatchValue(value=user_id),
                    )
                ]
            ),
            limit=limite,
            with_payload=True,
        )

        if resultados.points:
            itens: list[dict[str, Any]] = []
            for ponto in resultados.points:
                payload = dict(ponto.payload or {})
                if not payload.get("doc_id") or not payload.get("resumo"):
                    continue
                itens.append(
                    {
                        "doc_id": str(payload["doc_id"]),
                        "session_id": payload.get("session_id"),
                        "iniciada_em": payload.get("iniciada_em", ""),
                        "encerrada_em": payload.get("encerrada_em", ""),
                        "resumo": str(payload["resumo"]),
                        "score": float(ponto.score),
                    }
                )
            if itens:
                return itens

    return _historico_recente_mongo(user_id, limite)


def recuperar_mensagens(doc_id: str) -> list[dict[str, Any]]:
    """Busca as mensagens completas no MongoDB pelo doc_id devolvido pelo Qdrant."""
    collection = get_sessions_collection()
    doc = collection.find_one({"_id": doc_id}, {"mensagens": 1})

    # Compatibilidade com sessoes antigas criadas com ObjectId.
    if doc is None and ObjectId.is_valid(doc_id):
        doc = collection.find_one({"_id": ObjectId(doc_id)}, {"mensagens": 1})

    if doc is None:
        # Conveniencia para chamadas manuais com session_id.
        doc = collection.find_one({"session_id": doc_id}, {"mensagens": 1})

    return list(doc.get("mensagens", [])) if doc else []


def precisa_detalhe_literal(pergunta: str) -> bool:
    texto = pergunta.lower()
    termos = (
        "exatamente",
        "quanto",
        "qual valor",
        "que valor",
        "quando",
        "que dia",
        "o que eu disse",
        "o que falei",
        "detalhe",
        "literal",
        "nome",
    )
    return any(termo in texto for termo in termos)


def construir_contexto_memoria(
    session_id: str,
    user_id: str,
    pergunta: str,
    limite_atual: int = 8,
    limite_passado: int = 3,
) -> str:
    """Monta contexto curto da conversa atual e da memoria semantica passada."""
    blocos: list[str] = []

    atuais = listar_mensagens(session_id, limite=limite_atual)
    if atuais:
        linhas: list[str] = []
        for mensagem in atuais:
            conteudo, _ = anonimizar_entrada(str(mensagem.get("content", "")))
            linhas.append(f"{mensagem.get('role', 'unknown')}: {conteudo}")
        blocos.append("CONVERSA ATUAL RECENTE:\n" + "\n".join(linhas))

    try:
        historico = recuperar_historico(user_id, busca=pergunta, limite=limite_passado)
    except Exception:
        # Se o Qdrant estiver temporariamente indisponivel, nao derruba o chat.
        # O fallback aqui e apenas por recencia no MongoDB, sem voltar ao regex.
        historico = _historico_recente_mongo(user_id, limite_passado)

    if historico:
        linhas = []
        for item in historico:
            resumo, _ = anonimizar_entrada(str(item.get("resumo", "")))
            score = item.get("score")
            sufixo = f" (score={score:.3f})" if isinstance(score, float) else ""
            linhas.append(f"- {resumo}{sufixo}")
        blocos.append("MEMORIA DE SESSOES ANTERIORES:\n" + "\n".join(linhas))

        if precisa_detalhe_literal(pergunta):
            top_doc_id = str(historico[0].get("doc_id", ""))
            if top_doc_id:
                detalhes = recuperar_mensagens(top_doc_id)
                linhas_detalhe: list[str] = []
                for mensagem in detalhes[-10:]:
                    conteudo, _ = anonimizar_entrada(str(mensagem.get("content", "")))
                    linhas_detalhe.append(
                        f"{mensagem.get('role', 'unknown')}: {conteudo}"
                    )
                if linhas_detalhe:
                    blocos.append(
                        "DETALHE DA SESSAO HISTORICA MAIS RELEVANTE:\n"
                        + "\n".join(linhas_detalhe)
                    )

    return "\n\n".join(blocos) if blocos else "Sem memoria adicional relevante."
