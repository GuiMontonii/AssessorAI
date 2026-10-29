"""
Script de ingestao do FAQ no Qdrant Cloud.

Le o PDF oficial, divide em chunks, gera embeddings de 768 dimensoes e insere
na collection "faq_chunks". Deve ser executado uma vez ou sempre que o FAQ mudar:

    python -m app.ingest_faq

Se o PDF oficial ainda nao estiver em data/, o projeto usa o TXT existente como
fallback para que a Etapa 4 possa ser validada sem o erro de caminho do PyPDFLoader.
"""

from __future__ import annotations

import uuid

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from app.config import FAQ_PDF_PATH, FAQ_TEXT_PATH
from app.vectorstore import (
    COLLECTION_FAQ,
    cliente_qdrant,
    garantir_collections,
    gerar_embeddings_batch,
)

CHUNK_SIZE = 700
CHUNK_OVERLAP = 150
BATCH_SIZE = 50


def _carregar_documentos() -> list[Document]:
    if FAQ_PDF_PATH.exists():
        print(f"[ingest] Carregando PDF: {FAQ_PDF_PATH}")
        docs = PyPDFLoader(str(FAQ_PDF_PATH)).load()
        print(f"[ingest] {len(docs)} pagina(s) carregada(s)")
        return docs

    if FAQ_TEXT_PATH.exists():
        print(f"[ingest] PDF nao encontrado: {FAQ_PDF_PATH.name}")
        print(f"[ingest] Usando fallback TXT: {FAQ_TEXT_PATH}")
        texto = FAQ_TEXT_PATH.read_text(encoding="utf-8")
        if not texto.strip():
            raise RuntimeError("O arquivo de FAQ TXT esta vazio.")
        return [
            Document(
                page_content=texto,
                metadata={"source": str(FAQ_TEXT_PATH), "page": 0},
            )
        ]

    raise FileNotFoundError(
        "Nenhum FAQ encontrado. Coloque data/FAQ_assessor_v1.1.pdf no projeto."
    )


def ingerir_faq() -> int:
    """Indexa o FAQ no Qdrant e retorna o numero de chunks inseridos."""
    docs = _carregar_documentos()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    print(f"[ingest] {len(chunks)} chunk(s) gerado(s)")

    client = cliente_qdrant()

    # Reindexacao limpa: somente faq_chunks e recriada; memoria_resumos e mantida.
    if client.collection_exists(COLLECTION_FAQ):
        info = client.get_collection(COLLECTION_FAQ)
        print(f"[ingest] Limpando {info.points_count or 0} ponto(s) existente(s)...")
        client.delete_collection(COLLECTION_FAQ)

    garantir_collections()

    textos = [chunk.page_content for chunk in chunks]
    for i in range(0, len(textos), BATCH_SIZE):
        lote_textos = textos[i : i + BATCH_SIZE]
        lote_chunks = chunks[i : i + BATCH_SIZE]

        print(
            f"[ingest] Gerando embeddings para chunk "
            f"{i + 1}-{i + len(lote_textos)}..."
        )
        vetores = gerar_embeddings_batch(lote_textos)

        pontos = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vetor,
                payload={
                    "page_content": chunk.page_content,
                    "page_number": chunk.metadata.get("page", 0),
                    "source": str(chunk.metadata.get("source", "")),
                },
            )
            for vetor, chunk in zip(vetores, lote_chunks)
        ]

        client.upsert(
            collection_name=COLLECTION_FAQ,
            points=pontos,
            wait=True,
        )

    print(f"[ingest] Concluido! {len(chunks)} chunk(s) indexado(s) no Qdrant.")
    return len(chunks)


if __name__ == "__main__":
    ingerir_faq()
