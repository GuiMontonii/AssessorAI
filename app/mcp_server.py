import sys
from pathlib import Path
from typing import Annotated, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.financeiro import (
    add_transaction as _add_transaction,
    daily_balance as _daily_balance,
    query_transactions as _query_transactions,
    total_balance as _total_balance,
    update_transaction as _update_transaction,
)


mcp = MCPServer(
    name="assessor-financeiro",
    version="1.0.0",
    instructions="Ferramentas financeiras do Assessor.AI para registrar, consultar e atualizar transações e consultar saldos.",
)


LEITURA = ToolAnnotations(
    readOnlyHint=True
)

ESCRITA = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False
)


@mcp.tool(
    name="total_balance",
    title="Saldo total",
    description="Saldo de todo o histórico: entradas menos saídas.",
    annotations=LEITURA,
)
def total_balance() -> dict[str, Any]:
    return _total_balance.invoke({})


@mcp.tool(
    name="add_transaction",
    title="Registrar transação",
    description="Registra uma entrada ou saída financeira na tabela transactions.",
    annotations=ESCRITA,
)
def add_transaction(
    tipo: Annotated[
        str,
        Field(
            description="Tipo da transação: entrada ou saida."
        ),
    ],
    valor: Annotated[
        float,
        Field(
            description="Valor da transação, sempre maior que zero."
        ),
    ],
    descricao: Annotated[
        str,
        Field(
            description="Descrição da transação financeira."
        ),
    ],
    categoria: Annotated[
        Optional[str],
        Field(
            description="Categoria da transação, por exemplo: alimentação, transporte, salário ou geral."
        ),
    ] = "geral",
) -> dict[str, Any]:
    return _add_transaction.invoke({
        "tipo": tipo,
        "valor": valor,
        "descricao": descricao,
        "categoria": categoria,
    })


@mcp.tool(
    name="query_transactions",
    title="Consultar transações",
    description="Lista as transações financeiras do usuário com filtros opcionais.",
    annotations=LEITURA,
)
def query_transactions(
    inicio: Annotated[
        Optional[str],
        Field(
            description="Data inicial da consulta no formato YYYY-MM-DD."
        ),
    ] = None,
    fim: Annotated[
        Optional[str],
        Field(
            description="Data final da consulta no formato YYYY-MM-DD."
        ),
    ] = None,
    tipo: Annotated[
        Optional[str],
        Field(
            description="Filtra pelo tipo da transação: entrada ou saida."
        ),
    ] = None,
    categoria: Annotated[
        Optional[str],
        Field(
            description="Filtra pela categoria da transação."
        ),
    ] = None,
    limite: Annotated[
        int,
        Field(
            description="Quantidade máxima de transações retornadas. Máximo de 200."
        ),
    ] = 50,
) -> dict[str, Any]:
    return _query_transactions.invoke({
        "inicio": inicio,
        "fim": fim,
        "tipo": tipo,
        "categoria": categoria,
        "limite": limite,
    })


@mcp.tool(
    name="daily_balance",
    title="Saldo diário",
    description="Calcula entradas, saídas e saldo de um dia específico.",
    annotations=LEITURA,
)
def daily_balance(
    dia: Annotated[
        str,
        Field(
            description="Data que será consultada no formato YYYY-MM-DD."
        ),
    ],
) -> dict[str, Any]:
    return _daily_balance.invoke({
        "dia": dia,
    })


@mcp.tool(
    name="update_transaction",
    title="Atualizar transação",
    description="Atualiza uma transação existente na tabela transactions.",
    annotations=ESCRITA,
)
def update_transaction(
    transaction_id: Annotated[
        int,
        Field(
            description="ID da transação que será atualizada."
        ),
    ],
    valor: Annotated[
        Optional[float],
        Field(
            description="Novo valor da transação. Deve ser maior que zero."
        ),
    ] = None,
    descricao: Annotated[
        Optional[str],
        Field(
            description="Nova descrição da transação."
        ),
    ] = None,
    categoria: Annotated[
        Optional[str],
        Field(
            description="Nova categoria da transação."
        ),
    ] = None,
    tipo: Annotated[
        Optional[str],
        Field(
            description="Novo tipo da transação: entrada ou saida."
        ),
    ] = None,
) -> dict[str, Any]:
    return _update_transaction.invoke({
        "transaction_id": transaction_id,
        "valor": valor,
        "descricao": descricao,
        "categoria": categoria,
        "tipo": tipo,
    })


if __name__ == "__main__":
    from app.config import DATABASE_URL

    if not DATABASE_URL:
        print(
            "[assessor-financeiro] DATABASE_URL ausente no .env",
            file=sys.stderr,
        )

    mcp.run(transport="stdio")