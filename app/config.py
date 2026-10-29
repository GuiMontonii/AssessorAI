from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# Etapa 7: opcional para inicializar o servidor, exigida para o juiz aprovar respostas.
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# O MongoDB continua local por padrao, como na Etapa 3. Se quiser usar outro
# servidor, basta sobrescrever MONGODB_URI no .env.
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "assessor_ai").strip()
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "sessoes").strip()

# Etapa 4: Qdrant Cloud.
QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()

# A URL antiga do PostgreSQL da Aiven pode vir no formato postgres://.
# O psycopg2 aceita postgresql:// de forma consistente, entao normalizamos.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

GEMINI_MODEL = "gemini-2.5-flash"

GROQ_SPECIALIST_MODEL = "openai/gpt-oss-120b"
GROQ_FAST_MODEL = "openai/gpt-oss-120b"

# Modelo e dimensionalidade exigidos no roteiro da Etapa 4.
EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIM = 768

APP_NAME = "Assessor.AI"
APP_VERSION = "4.0.0"
CORS_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
FAQ_PDF_PATH = DATA_DIR / "FAQ_assessor_v1.1.pdf"
FAQ_TEXT_PATH = DATA_DIR / "FAQ_assessor_v1.1.txt"


OBRIGATORIAS = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GROQ_API_KEY": GROQ_API_KEY,
    "DATABASE_URL": DATABASE_URL,
    "MONGODB_URI": MONGODB_URI,
    "QDRANT_URL": QDRANT_URL,
    "QDRANT_API_KEY": QDRANT_API_KEY,
}


def configuracoes_ausentes() -> list[str]:
    """Retorna as variaveis obrigatorias que ainda estao vazias."""
    return [nome for nome, valor in OBRIGATORIAS.items() if not str(valor).strip()]


def validar_configuracao() -> None:
    """Falha com uma mensagem curta quando uma configuracao obrigatoria falta."""
    ausentes = configuracoes_ausentes()
    if ausentes:
        raise RuntimeError(
            "Configuracao incompleta. Preencha no .env: " + ", ".join(ausentes)
        )
