"""
Cliente Qdrant e funcoes de embedding da Etapa 4.

Duas collections:
- memoria_resumos: resumos de sessoes encerradas, filtrados por user_id.
- faq_chunks: chunks do FAQ, compartilhados por todos os usuarios.

O MongoDB continua sendo a fonte das mensagens completas. O Qdrant funciona
como indice semantico e devolve o doc_id usado para voltar ao MongoDB.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient, models

from app.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    GEMINI_API_KEY,
    QDRANT_API_KEY,
    QDRANT_URL,
)

COLLECTION_MEMORIA = "memoria_resumos"
COLLECTION_FAQ = "faq_chunks"
COLLECTION_PERFIL = "perfil_preferencias"

@lru_cache(maxsize=1)
def cliente_qdrant() -> QdrantClient:
    if not QDRANT_URL or not QDRANT_API_KEY:
        raise RuntimeError(
            "Qdrant nao configurado. Preencha QDRANT_URL e QDRANT_API_KEY no .env."
        )
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)


@lru_cache(maxsize=1)
def modelo_embeddings() -> GoogleGenerativeAIEmbeddings:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY nao configurada no .env.")

    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=GEMINI_API_KEY,
        output_dimensionality=EMBEDDING_DIM,
    )


def gerar_embedding(texto: str) -> list[float]:
    """Gera um embedding de 768 dimensoes para uma consulta."""
    if not texto or not texto.strip():
        raise ValueError("Nao e possivel gerar embedding de texto vazio.")
    return modelo_embeddings().embed_query(
        texto.strip(), output_dimensionality=EMBEDDING_DIM
    )


def gerar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    """Gera embeddings de 768 dimensoes para documentos em lote."""
    if not textos:
        return []
    if any(not texto or not texto.strip() for texto in textos):
        raise ValueError("Nao e possivel gerar embedding de texto vazio.")
    return modelo_embeddings().embed_documents(
        [texto.strip() for texto in textos],
        output_dimensionality=EMBEDDING_DIM,
    )


def _criar_collection(nome: str) -> None:
    cliente_qdrant().create_collection(
        collection_name=nome,
        vectors_config=models.VectorParams(
            size=EMBEDDING_DIM,
            distance=models.Distance.COSINE,
        ),
    )


def garantir_collections() -> None:
    """
    Garante as collections usadas pela aplicacao.

    Collections:
    - memoria_resumos: memoria semantica entre sessoes
    - faq_chunks: chunks do PDF do FAQ
    - perfil_preferencias: preferencias semanticas do perfil financeiro

    As collections de memoria e perfil usam multitenancy pelo campo user_id.
    """
    client = cliente_qdrant()

    # Garante a collection de memoria
    if not client.collection_exists(COLLECTION_MEMORIA):
        _criar_collection(COLLECTION_MEMORIA)

    # Garante a collection do FAQ
    if not client.collection_exists(COLLECTION_FAQ):
        _criar_collection(COLLECTION_FAQ)

    # Garante a collection das preferencias do perfil
    if not client.collection_exists(COLLECTION_PERFIL):
        _criar_collection(COLLECTION_PERFIL)

    # Multitenancy da memoria:
    # cada usuario so deve buscar os proprios resumos.
    try:
        client.create_payload_index(
            collection_name=COLLECTION_MEMORIA,
            field_name="user_id",
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=True,
            ),
            wait=True,
        )
    except Exception as exc:
        # Criar novamente pode retornar "already exists".
        # Outros erros devem continuar aparecendo.
        if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
            raise

    # Multitenancy do perfil:
    # cada usuario so deve buscar as proprias preferencias.
    try:
        client.create_payload_index(
            collection_name=COLLECTION_PERFIL,
            field_name="user_id",
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=True,
            ),
            wait=True,
        )
    except Exception as exc:
        # Criar novamente pode retornar "already exists".
        # Outros erros devem continuar aparecendo.
        if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
            raise


def testar_qdrant() -> dict[str, object]:
    """Retorna informacoes simples para validar a conexao e as collections."""
    garantir_collections()
    client = cliente_qdrant()
    memoria = client.get_collection(COLLECTION_MEMORIA)
    faq = client.get_collection(COLLECTION_FAQ)
    return {
        "status": "ok",
        "memoria_resumos": memoria.points_count,
        "faq_chunks": faq.points_count,
        "dimensao": EMBEDDING_DIM,
    }
