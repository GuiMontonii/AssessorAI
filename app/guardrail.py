from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailDecision:
    permitido: bool
    motivo: str = ""


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "CPF",
        re.compile(r"(?<!\d)(?:\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[-.\s]?\d{2})(?!\d)"),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[-\s]?\d{4}(?!\d)"),
    ),
    (
        "CARD",
        re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)"),
    ),
]

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_ -]?key|token|senha|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*"),
]

_BLOCK_PATTERNS = [
    re.compile(r"(?i)\bignore\s+as\s+instru[cç][oõ]es\b"),
    re.compile(r"(?i)\bqual\s+a[cç][aã]o\s+de\s+empresa\b.{0,100}\bcompro\b"),
    re.compile(r"(?i)ignore\s+(all|previous|above)\s+(instructions|rules)"),
    re.compile(r"(?i)revele?\s+(o\s+)?(system prompt|prompt do sistema|segredos?)"),
    re.compile(r"(?i)mostre?\s+(suas?|as)\s+(chaves?|api keys?|tokens?)"),
]


def anonimizar_entrada(texto: str) -> tuple[str, dict[str, str]]:
    resultado = texto
    mapa: dict[str, str] = {}
    contadores: dict[str, int] = {}

    for nome, pattern in _PATTERNS:
        def substituir(match: re.Match[str], nome: str = nome) -> str:
            valor = match.group(0)
            contadores[nome] = contadores.get(nome, 0) + 1
            token = f"<PII_{nome}_{contadores[nome]}>"
            mapa[token] = valor
            return token

        resultado = pattern.sub(substituir, resultado)

    for pattern in _SECRET_PATTERNS:
        def substituir_segredo(match: re.Match[str]) -> str:
            contadores["SECRET"] = contadores.get("SECRET", 0) + 1
            token = f"<PII_SECRET_{contadores['SECRET']}>"
            mapa[token] = match.group(0)
            return token

        resultado = pattern.sub(substituir_segredo, resultado)

    return resultado, mapa


def guardrail_entrada(texto: str) -> GuardrailDecision:
    if not texto or not texto.strip():
        return GuardrailDecision(False, "Mensagem vazia.")
    if len(texto) > 8000:
        return GuardrailDecision(False, "Mensagem acima do limite permitido.")
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(texto):
            return GuardrailDecision(
                False,
                "Nao posso expor instrucoes internas, credenciais ou segredos do sistema.",
            )
    return GuardrailDecision(True)


def _remover_pii_detectavel(texto: str) -> str:
    resultado = texto
    for nome, pattern in _PATTERNS:
        resultado = pattern.sub(f"<PII_{nome}_REMOVIDO>", resultado)
    for pattern in _SECRET_PATTERNS:
        resultado = pattern.sub("<PII_SECRET_REMOVIDO>", resultado)
    return resultado


def guardrail_saida(resposta: str, mapa_pii: dict[str, str] | None = None) -> str:
    limpa = resposta or ""
    mapa_pii = mapa_pii or {}

    for token, valor in mapa_pii.items():
        if valor:
            limpa = limpa.replace(valor, token)

    limpa = _remover_pii_detectavel(limpa)
    return limpa.strip()


def anonimizar_textos(textos: list[str]) -> list[str]:
    return [anonimizar_entrada(texto)[0] for texto in textos]
