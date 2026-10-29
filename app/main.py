from __future__ import annotations

from app.routes import chat, sessions, monitor, perfil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import APP_NAME, APP_VERSION, CORS_ORIGINS, FRONTEND_DIR, validar_configuracao

# A Etapa 4 considera QDRANT_URL e QDRANT_API_KEY obrigatorias.
validar_configuracao()

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Assessor pessoal com agentes de financas e agenda, MongoDB para sessoes "
        "e memoria semantica/FAQ no Qdrant Cloud (Etapa 4)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(perfil.router)
app.include_router(monitor.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "etapa": "4",
    }


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
