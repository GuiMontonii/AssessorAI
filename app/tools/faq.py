from __future__ import annotations

from langchain_core.tools import tool

from app.vectorstore import (
    COLLECTION_FAQ,
    cliente_qdrant,
    garantir_collections,
    gerar_embedding,
)


@tool
def faq_retriever(question: str) -> str:
    """Busca no FAQ oficial os trechos mais relevantes para responder a pergunta."""
    vetor = gerar_embedding(question)
    garantir_collections()

    resultados = cliente_qdrant().query_points(
        collection_name=COLLECTION_FAQ,
        query=vetor,
        limit=6,
        with_payload=True,
    )

    if not resultados.points:
        return (
            "Nenhum trecho foi encontrado no FAQ. "
            "Execute primeiro: python -m app.ingest_faq"
        )

    trechos = [
        str((ponto.payload or {}).get("page_content", "")).strip()
        for ponto in resultados.points
    ]
    trechos = [trecho for trecho in trechos if trecho]

    if not trechos:
        return "Nenhum trecho relevante encontrado no FAQ."

    return "\n\n".join(trechos)


TOOLS_FAQ = [faq_retriever]
