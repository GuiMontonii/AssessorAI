from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.context import AgentContext
from app.tools.db import get_conn
from app.tools.cambio import normalizar_valor
from app.tools.pendencias import preparar_escrita


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_to_dict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: _iso(value) for column, value in zip(columns, row)}


def add_transaction_db(
    user_id: str,
    tipo: str,
    valor: float,
    descricao: str,
    categoria: str = "geral",
    data_transacao: datetime | None = None,
    moeda_original: str = "BRL",
    valor_original: Decimal | None = None,
    taxa_cambio: Decimal | None = None,
    data_cotacao: date | None = None,
    fonte_cotacao: str | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    tipo = tipo.lower().strip()
    if tipo not in {"entrada", "saida"}:
        return {"status": "erro", "erro": "tipo deve ser entrada ou saida"}
    if valor <= 0:
        return {"status": "erro", "erro": "valor deve ser maior que zero"}
    if not descricao.strip():
        return {"status": "erro", "erro": "descricao e obrigatoria"}

    momento = data_transacao or datetime.now(timezone.utc)
    with (nullcontext(conn) if conn is not None else get_conn()) as conexao:
        with conexao.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transactions
                    (user_id, tipo, valor, descricao, categoria, data_transacao,
                     moeda_original, valor_original, taxa_cambio, data_cotacao, fonte_cotacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, tipo, valor, descricao, categoria, data_transacao,
                          moeda_original, valor_original, taxa_cambio, data_cotacao, fonte_cotacao
                """,
                (user_id, tipo, valor, descricao.strip(), categoria.strip() or "geral", momento,
                 moeda_original, valor_original if valor_original is not None else valor,
                 taxa_cambio, data_cotacao, fonte_cotacao),
            )
            row = cur.fetchone()
            columns = [desc.name for desc in cur.description]
    return {"status": "ok", "transacao": _row_to_dict(columns, row)}


def query_transactions_db(
    user_id: str,
    inicio: date | None = None,
    fim: date | None = None,
    tipo: str | None = None,
    categoria: str | None = None,
    limite: int = 50,
) -> dict[str, Any]:
    limite = min(max(limite, 1), 200)
    where = ["user_id = %s"]
    params: list[Any] = [user_id]

    if inicio:
        where.append("data_transacao >= %s")
        params.append(inicio)
    if fim:
        where.append("data_transacao < (%s::date + interval '1 day')")
        params.append(fim)
    if tipo:
        where.append("tipo = %s")
        params.append(tipo.lower().strip())
    if categoria:
        where.append("LOWER(categoria) = LOWER(%s)")
        params.append(categoria.strip())

    params.append(limite)
    sql = f"""
        SELECT id, tipo, valor, descricao, categoria, data_transacao,
               moeda_original, valor_original, taxa_cambio, data_cotacao, fonte_cotacao
        FROM transactions
        WHERE {' AND '.join(where)}
        ORDER BY data_transacao DESC, id DESC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            columns = [desc.name for desc in cur.description]
    return {
        "status": "ok",
        "quantidade": len(rows),
        "transacoes": [_row_to_dict(columns, row) for row in rows],
    }


def total_balance_db(user_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0)
                FROM transactions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            entradas, saidas = cur.fetchone()
    saldo = Decimal(entradas) - Decimal(saidas)
    return {
        "status": "ok",
        "entradas": float(entradas),
        "saidas": float(saidas),
        "saldo": float(saldo),
    }


def daily_balance_db(user_id: str, dia: date) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0)
                FROM transactions
                WHERE user_id = %s AND data_transacao::date = %s
                """,
                (user_id, dia),
            )
            entradas, saidas = cur.fetchone()
    return {
        "status": "ok",
        "data": dia.isoformat(),
        "entradas": float(entradas),
        "saidas": float(saidas),
        "saldo": float(Decimal(entradas) - Decimal(saidas)),
    }


def update_transaction_db(
    user_id: str,
    transaction_id: int,
    valor: float | None = None,
    descricao: str | None = None,
    categoria: str | None = None,
    tipo: str | None = None,
    moeda_original: str = "BRL",
    valor_original: Decimal | None = None,
    taxa_cambio: Decimal | None = None,
    data_cotacao: date | None = None,
    fonte_cotacao: str | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    updates: list[str] = []
    params: list[Any] = []

    if valor is not None:
        if valor <= 0:
            return {"status": "erro", "erro": "valor deve ser maior que zero"}
        updates.append("valor = %s")
        params.append(valor)
        updates.extend([
            "moeda_original = %s", "valor_original = %s", "taxa_cambio = %s",
            "data_cotacao = %s", "fonte_cotacao = %s",
        ])
        params.extend([
            moeda_original, valor_original if valor_original is not None else valor,
            taxa_cambio, data_cotacao, fonte_cotacao,
        ])
    if descricao is not None:
        updates.append("descricao = %s")
        params.append(descricao.strip())
    if categoria is not None:
        updates.append("categoria = %s")
        params.append(categoria.strip() or "geral")
    if tipo is not None:
        tipo = tipo.lower().strip()
        if tipo not in {"entrada", "saida"}:
            return {"status": "erro", "erro": "tipo deve ser entrada ou saida"}
        updates.append("tipo = %s")
        params.append(tipo)

    if not updates:
        return {"status": "erro", "erro": "nenhum campo para atualizar"}

    params.extend([transaction_id, user_id])
    sql = f"""
        UPDATE transactions
        SET {', '.join(updates)}
        WHERE id = %s AND user_id = %s
        RETURNING id, tipo, valor, descricao, categoria, data_transacao,
                  moeda_original, valor_original, taxa_cambio, data_cotacao, fonte_cotacao
    """
    with (nullcontext(conn) if conn is not None else get_conn()) as conexao:
        with conexao.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            if not row:
                return {"status": "erro", "erro": "transacao nao encontrada"}
            columns = [desc.name for desc in cur.description]
    return {"status": "ok", "transacao": _row_to_dict(columns, row)}


@tool
def add_transaction(
    tipo: str,
    valor: float,
    descricao: str,
    runtime: ToolRuntime[AgentContext],
    categoria: str = "geral",
    moeda: str = "BRL",
) -> dict[str, Any]:
    """Prepara uma transacao (BRL ou USD) sem gravar ate o juiz aprovar."""
    tipo = tipo.lower().strip()
    if tipo not in {"entrada", "saida"} or not descricao.strip():
        return {"status": "erro", "erro": "tipo ou descricao invalida"}
    conversao = normalizar_valor(valor, moeda, runtime.context.moeda_informada)
    if conversao["status"] != "ok":
        return conversao
    return preparar_escrita(runtime.context, "add_transaction", {
        "tipo": tipo, "valor": conversao["valor"], "descricao": descricao.strip(),
        "categoria": categoria.strip() or "geral",
        "moeda_original": conversao["moeda_original"],
        "valor_original": conversao["valor_original"],
        "taxa_cambio": conversao["taxa_cambio"],
        "data_cotacao": conversao["data_cotacao"],
        "fonte_cotacao": conversao["fonte_cotacao"],
    })


@tool
def query_transactions(
    runtime: ToolRuntime[AgentContext],
    inicio: str | None = None,
    fim: str | None = None,
    tipo: str | None = None,
    categoria: str | None = None,
    limite: int = 50,
) -> dict[str, Any]:
    """Lista transacoes financeiras persistidas do usuario atual com filtros opcionais."""
    inicio_date = date.fromisoformat(inicio) if inicio else None
    fim_date = date.fromisoformat(fim) if fim else None
    return query_transactions_db(
        runtime.context.user_id,
        inicio=inicio_date,
        fim=fim_date,
        tipo=tipo,
        categoria=categoria,
        limite=limite,
    )


@tool
def total_balance(runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
    """Calcula entradas, saidas e saldo total do usuario atual."""
    return total_balance_db(runtime.context.user_id)


@tool
def daily_balance(dia: str, runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
    """Calcula entradas, saidas e saldo de um dia no formato YYYY-MM-DD."""
    return daily_balance_db(runtime.context.user_id, date.fromisoformat(dia))


@tool
def update_transaction(
    transaction_id: int,
    runtime: ToolRuntime[AgentContext],
    valor: float | None = None,
    descricao: str | None = None,
    categoria: str | None = None,
    tipo: str | None = None,
    moeda: str = "BRL",
) -> dict[str, Any]:
    """Prepara alteracao de uma transacao; gravacao depende do juiz."""
    if valor is None and descricao is None and categoria is None and tipo is None:
        return {"status": "erro", "erro": "nenhum campo para atualizar"}
    if tipo is not None and tipo.lower().strip() not in {"entrada", "saida"}:
        return {"status": "erro", "erro": "tipo deve ser entrada ou saida"}
    dados: dict[str, Any] = {
        "transaction_id": transaction_id, "valor": None,
        "moeda_explicita": runtime.context.moeda_informada is not None,
        "descricao": descricao, "categoria": categoria,
        "tipo": tipo.lower().strip() if tipo is not None else None,
    }
    if valor is not None:
        conversao = normalizar_valor(valor, moeda, runtime.context.moeda_informada)
        if conversao["status"] != "ok":
            return conversao
        dados.update(conversao)
        dados.pop("status", None)
    return preparar_escrita(runtime.context, "update_transaction", dados)


TOOLS = [
    add_transaction,
    query_transactions,
    total_balance,
    daily_balance,
    update_transaction,
]
