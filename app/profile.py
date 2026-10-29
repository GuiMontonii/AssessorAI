from __future__ import annotations

import uuid
from typing import Any

from pymongo import MongoClient
from qdrant_client import models

from app.config import MONGODB_DB, MONGODB_URI
from app.vectorstore import (
    COLLECTION_PERFIL,
    cliente_qdrant,
    garantir_collections,
    gerar_embedding,
)

_mongo = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=4000,
)

_db = _mongo[MONGODB_DB]
_perfis = _db["perfis"]

def _garantir_indice_perfis() -> None:
    _perfis.create_index("user_id", unique=True)


def _qdrant_point_id(user_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"assessor-ai:perfil:{user_id}",
        )
    )

def salvar_perfil(
    *,
    user_id: str,
    renda_mensal: float,
    objetivo: str,
    tolerancia_risco: str,
    preferencias: str,
) -> dict[str, Any]:
    user_id = user_id.strip()
    objetivo = objetivo.strip()
    tolerancia_risco = tolerancia_risco.strip()
    preferencias = preferencias.strip()

    documento = {
        "user_id": user_id,
        "renda_mensal": renda_mensal,
        "objetivo": objetivo,
        "tolerancia_risco": tolerancia_risco,
        "preferencias": preferencias,
    }

    vetor = gerar_embedding(preferencias)

    _garantir_indice_perfis()
    _perfis.update_one(
        {"user_id": user_id},
        {"$set": documento},
        upsert=True,
    )

    garantir_collections()

    cliente_qdrant().upsert(
        collection_name=COLLECTION_PERFIL,
        points=[
            models.PointStruct(
                id=_qdrant_point_id(user_id),
                vector=vetor,
                payload={
                    "user_id": user_id,
                    "preferencias": preferencias,
                },
            )
        ],
        wait=True,
    )

    return documento

def buscar_perfil(user_id: str) -> dict[str, Any] | None:
    user_id = user_id.strip()

    if not user_id:
        return None

    perfil = _perfis.find_one(
        {"user_id": user_id},
        {"_id": 0},
    )

    if not perfil:
        return None

    return dict(perfil)

def buscar_preferencias(
    user_id: str,
    busca: str,
    limite: int = 1,
) -> list[dict[str, Any]]:
    user_id = user_id.strip()
    busca = busca.strip()

    if not user_id or not busca or limite <= 0:
        return []

    garantir_collections()
    
    vetor = gerar_embedding(busca)

    resultados = cliente_qdrant().query_points(
        collection_name=COLLECTION_PERFIL,
        query=vetor,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(
                        value=user_id,
                    ),
                )
            ]
        ),
        limit=limite,
        with_payload=True,
    )

    preferencias = []

    for ponto in resultados.points:
        payload = dict(ponto.payload or {})

        if not payload.get("preferencias"):
            continue

        preferencias.append(
            {
                "preferencias": payload["preferencias"],
                "score": ponto.score,
            }
        )

    return preferencias