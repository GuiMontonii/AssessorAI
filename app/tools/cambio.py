"""Normalizacao monetaria: a cotacao e consultada em uma fonte externa, nunca no prompt."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache

CENTAVO = Decimal("0.01")
FONTE_CAMBIO = "Frankfurter (referencia de mercado)"


def moeda_da_mensagem(texto: str) -> str | None:
    moedas = set()
    if re.search(r"US\s*\$|\bUSD\b|\bd[oó]lar(?:es)?\b", texto, re.I):
        moedas.add("USD")
    if re.search(r"R\s*\$|\bBRL\b|\breais\b|\breal\b", texto, re.I):
        moedas.add("BRL")
    if re.search(r"€|\bEUR\b|\beuros?\b", texto, re.I):
        moedas.add("EUR")
    if len(moedas) > 1:
        return "MISTO"
    return next(iter(moedas), None)


@lru_cache(maxsize=32)
def _cotacao_usd_brl(janela: int) -> tuple[Decimal, date]:
    del janela
    url = "https://api.frankfurter.dev/v2/rate/USD/BRL"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resposta:
        dados = json.load(resposta)

    if dados.get("base", "").upper() != "USD" or dados.get("quote", "").upper() != "BRL":
        raise ValueError("A fonte retornou um par de moedas inesperado.")
    cotacao = Decimal(str(dados["rate"]))
    data_taxa = date.fromisoformat(dados["date"])
    hoje = datetime.now(timezone.utc).date()
    if not cotacao.is_finite() or cotacao <= 0:
        raise ValueError("Cotacao invalida.")
    if data_taxa > hoje or hoje - data_taxa > timedelta(days=10):
        raise ValueError("A cotacao retornada nao esta atualizada.")
    return cotacao, data_taxa


def normalizar_valor(valor: float, moeda: str, moeda_informada: str | None) -> dict:
    """Converte USD para BRL; rejeita ambiguidades em vez de registrar moeda errada."""
    try:
        original = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return {"status": "erro", "erro": "Valor financeiro invalido."}
    if not original.is_finite() or original <= 0:
        return {"status": "erro", "erro": "O valor deve ser maior que zero."}

    moeda = (moeda or "BRL").strip().upper()
    if moeda_informada == "MISTO":
        return {"status": "erro", "erro": "Ha mais de uma moeda na mensagem. Informe cada lancamento separadamente."}
    if moeda_informada == "EUR":
        return {"status": "erro", "erro": "Moeda EUR ainda nao suportada. Nenhum valor foi registrado."}
    if moeda_informada == "USD":
        moeda = "USD" if moeda == "BRL" else moeda
    elif moeda_informada == "BRL" and moeda != "BRL":
        return {"status": "erro", "erro": "A moeda escolhida nao corresponde ao pedido em reais."}
    elif moeda_informada is None and moeda != "BRL":
        return {"status": "erro", "erro": "O usuario nao informou moeda estrangeira. Confirme a moeda antes de registrar."}
    if moeda not in {"BRL", "USD"}:
        return {"status": "erro", "erro": "Moeda nao suportada. Nenhum valor foi registrado."}
    if original.quantize(CENTAVO, rounding=ROUND_HALF_UP) <= 0:
        return {"status": "erro", "erro": "Valor arredondado deve ser maior que zero."}
    if moeda == "BRL":
        return {
            "status": "ok", "valor": str(original.quantize(CENTAVO, rounding=ROUND_HALF_UP)),
            "valor_original": str(original.quantize(CENTAVO, rounding=ROUND_HALF_UP)),
            "moeda_original": "BRL", "taxa_cambio": None,
            "data_cotacao": None, "fonte_cotacao": None,
        }

    try:
        taxa, data_taxa = _cotacao_usd_brl(int(time.time() // 900))
    except Exception:
        return {
            "status": "erro",
            "erro": "Nao foi possivel obter a cotacao USD/BRL agora. Nenhum valor foi registrado.",
        }
    convertido = (original * taxa).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    if convertido <= 0:
        return {"status": "erro", "erro": "Valor convertido deve ser maior que zero."}
    return {
        "status": "ok",
        "valor": str(convertido),
        "valor_original": str(original.quantize(CENTAVO, rounding=ROUND_HALF_UP)),
        "moeda_original": "USD", "taxa_cambio": str(taxa),
        "data_cotacao": data_taxa.isoformat(), "fonte_cotacao": FONTE_CAMBIO,
    }
