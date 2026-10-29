from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.context import AgentContext
from app.tools.db import get_conn
from app.tools.pendencias import preparar_escrita


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_dict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column, value in zip(columns, row):
        result[column] = value.isoformat() if isinstance(value, datetime) else value
    return result


def add_event_db(
    user_id: str,
    titulo: str,
    inicio: datetime,
    fim: datetime,
    descricao: str = "",
    conn: Any = None,
) -> dict[str, Any]:
    if not titulo.strip():
        return {"status": "erro", "erro": "titulo e obrigatorio"}
    if fim < inicio:
        return {"status": "erro", "erro": "fim nao pode ser anterior ao inicio"}

    with (nullcontext(conn) if conn is not None else get_conn()) as conexao:
        with conexao.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"agenda:{user_id}",))
            cur.execute(
                """
                SELECT id, titulo, inicio, fim
                FROM events
                WHERE user_id = %s
                  AND inicio < %s
                  AND fim > %s
                ORDER BY inicio
                """,
                (user_id, fim, inicio),
            )
            conflitos = cur.fetchall()
            conflito_columns = [desc.name for desc in cur.description]
            if conflitos:
                return {
                    "status": "conflito",
                    "erro": "Existe compromisso no mesmo intervalo.",
                    "conflitos": [
                        _row_dict(conflito_columns, row) for row in conflitos
                    ],
                }

            cur.execute(
                """
                INSERT INTO events (user_id, titulo, descricao, inicio, fim)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, titulo, descricao, inicio, fim
                """,
                (user_id, titulo.strip(), descricao.strip(), inicio, fim),
            )
            row = cur.fetchone()
            columns = [desc.name for desc in cur.description]

    return {"status": "ok", "evento": _row_dict(columns, row)}


@tool
def add_event(
    titulo: str,
    inicio: str,
    fim: str,
    runtime: ToolRuntime[AgentContext],
    descricao: str = "",
) -> dict[str, Any]:
    """Prepara um compromisso; conflito e revisto no momento da confirmacao."""
    inicio_data = _parse_datetime(inicio)
    fim_data = _parse_datetime(fim)
    if not titulo.strip() or fim_data < inicio_data:
        return {"status": "erro", "erro": "titulo ou intervalo do evento invalido"}
    return preparar_escrita(runtime.context, "add_event", {
        "titulo": titulo.strip(), "inicio": inicio_data.isoformat(),
        "fim": fim_data.isoformat(), "descricao": descricao.strip(),
    })


TOOLS_AGENDA = [add_event]
