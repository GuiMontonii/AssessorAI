"""Etapa 8: preparar sem efeitos, confirmar todas as escritas somente apos o juiz."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from app.context import AgentContext

OPERACOES = frozenset({"add_transaction", "update_transaction", "add_event"})


class ConfirmacaoRecusada(Exception):
    """Uma regra de negocio impediu a gravacao de todo o turno."""


def preparar_escrita(contexto: AgentContext, operacao: str, dados: dict[str, Any]) -> dict[str, Any]:
    if operacao not in OPERACOES:
        raise ValueError("Operacao de escrita nao permitida.")
    if not contexto.user_id or not contexto.session_id or not contexto.turno_id:
        raise ValueError("Contexto de usuario/sessao/turno incompleto.")
    acao = {
        "turno_id": contexto.turno_id,
        "user_id": contexto.user_id,
        "operacao": operacao,
        "dados": dict(dados),
    }
    if acao not in contexto.escritas_pendentes:
        contexto.escritas_pendentes.append(acao)
    return {
        "status": "pendente", "operacao": operacao, "dados": dict(dados),
        "mensagem": "Acao preparada; ainda nao foi gravada. Aguarda aprovacao do juiz.",
    }


def confirmar_escritas(
    turno_id: str, session_id: str, user_id: str, pendentes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not pendentes:
        return []
    if not all(
        item.get("turno_id") == turno_id and item.get("user_id") == user_id
        and item.get("operacao") in OPERACOES
        for item in pendentes
    ):
        raise ValueError("As acoes pendentes nao pertencem ao turno atual.")

    from app.tools.db import get_conn
    from app.tools.financeiro import add_transaction_db, update_transaction_db
    from app.tools.agenda import add_event_db, _parse_datetime

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO escritas_turno (turno_id, session_id, user_id, resultados)
                VALUES (%s, %s, %s, '[]'::jsonb)
                ON CONFLICT (turno_id) DO NOTHING
                RETURNING turno_id
                """,
                (turno_id, session_id, user_id),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "SELECT session_id, user_id, resultados FROM escritas_turno WHERE turno_id = %s",
                    (turno_id,),
                )
                anterior = cur.fetchone()
                if not anterior or anterior[0] != session_id or anterior[1] != user_id:
                    raise ValueError("O turno ja existe para outra sessao ou usuario.")
                return anterior[2] if isinstance(anterior[2], list) else json.loads(anterior[2])

        resultados = []
        for acao in pendentes:
            dados = acao["dados"]
            if acao["operacao"] == "add_transaction":
                resultado = add_transaction_db(
                    user_id, tipo=dados["tipo"], valor=Decimal(dados["valor"]),
                    descricao=dados["descricao"], categoria=dados["categoria"],
                    moeda_original=dados["moeda_original"],
                    valor_original=Decimal(dados["valor_original"]),
                    taxa_cambio=(Decimal(dados["taxa_cambio"]) if dados["taxa_cambio"] else None),
                    data_cotacao=(date.fromisoformat(dados["data_cotacao"]) if dados["data_cotacao"] else None),
                    fonte_cotacao=dados["fonte_cotacao"], conn=conn,
                )
            elif acao["operacao"] == "update_transaction":
                if dados.get("valor") is not None and not dados.get("moeda_explicita"):
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT moeda_original FROM transactions WHERE id = %s AND user_id = %s FOR UPDATE",
                            (int(dados["transaction_id"]), user_id),
                        )
                        existente = cur.fetchone()
                        if existente and existente[0] != "BRL":
                            raise ConfirmacaoRecusada(
                                "Informe a moeda ao alterar o valor de uma transacao internacional"
                            )
                resultado = update_transaction_db(
                    user_id, transaction_id=int(dados["transaction_id"]),
                    valor=(Decimal(dados["valor"]) if dados.get("valor") is not None else None),
                    descricao=dados.get("descricao"), categoria=dados.get("categoria"),
                    tipo=dados.get("tipo"),
                    moeda_original=dados.get("moeda_original", "BRL"),
                    valor_original=(Decimal(dados["valor_original"]) if dados.get("valor_original") is not None else None),
                    taxa_cambio=(Decimal(dados["taxa_cambio"]) if dados.get("taxa_cambio") else None),
                    data_cotacao=(date.fromisoformat(dados["data_cotacao"]) if dados.get("data_cotacao") else None),
                    fonte_cotacao=dados.get("fonte_cotacao"), conn=conn,
                )
            else:
                resultado = add_event_db(
                    user_id, titulo=dados["titulo"],
                    inicio=_parse_datetime(dados["inicio"]),
                    fim=_parse_datetime(dados["fim"]),
                    descricao=dados["descricao"], conn=conn,
                )
            if resultado.get("status") != "ok":
                raise ConfirmacaoRecusada(resultado.get("erro", "Operacao nao autorizada."))
            resultados.append({"operacao": acao["operacao"], "resultado": resultado})

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE escritas_turno SET resultados = %s::jsonb WHERE turno_id = %s",
                (json.dumps(resultados, ensure_ascii=False), turno_id),
            )
    return resultados


def resposta_confirmada(resultados: list[dict[str, Any]]) -> str:
    linhas = []
    for item in resultados:
        operacao = item["operacao"]
        resultado = item["resultado"]
        if operacao in {"add_transaction", "update_transaction"}:
            transacao = resultado["transacao"]
            descricao = transacao.get("descricao", "")
            valor = Decimal(str(transacao["valor"]))
            linha = (
                f"Transacao {'registrada' if operacao == 'add_transaction' else 'atualizada'}: "
                f"{descricao} - R$ {valor:.2f} (ID {transacao['id']})."
            )
            if transacao.get("moeda_original") == "USD":
                linha += (
                    f" Valor original: US$ {Decimal(str(transacao['valor_original'])):.2f}; "
                    f"cotacao de referencia {transacao['taxa_cambio']} de "
                    f"{transacao['data_cotacao']} ({transacao['fonte_cotacao']}). "
                    "O valor cobrado no cartao pode ser diferente."
                )
            linhas.append(linha)
        else:
            evento = resultado["evento"]
            linhas.append(
                f"Compromisso registrado: {evento['titulo']}, de {evento['inicio']} "
                f"ate {evento['fim']} (ID {evento['id']})."
            )
    return "\n".join(linhas)
