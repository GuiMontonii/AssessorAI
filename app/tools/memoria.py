from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.memory import recuperar_historico


@tool
def buscar_historico(busca: str, config: RunnableConfig) -> str:
    """Consulta conversas ANTERIORES do usuario (sessoes ja encerradas).

    Use SOMENTE quando a resposta depende de algo dito numa conversa passada
    - preferencias, decisoes ou planos que o usuario mencionou antes.
    NAO use para dados estruturados do banco (gastos, saldos, eventos).

    Args:
        busca: assunto a procurar semanticamente nos resumos anteriores.
    """
    configuravel = (config or {}).get("configurable", {})
    user_id = configuravel.get("user_id") or configuravel.get("thread_id")

    if not user_id:
        return "Nao foi possivel identificar o usuario para buscar o historico."

    historico = recuperar_historico(str(user_id), busca=busca, limite=3)
    if not historico:
        return "Nenhuma conversa anterior relevante encontrada."

    linhas: list[str] = []
    for item in historico:
        data = item.get("iniciada_em", "")
        if hasattr(data, "strftime"):
            data_fmt = data.strftime("%d/%m/%Y")
        else:
            data_fmt = str(data)[:10]
        linhas.append(f"[{data_fmt}] {item.get('resumo', '')}")

    return "\n\n".join(linhas)


TOOLS_MEMORIA = [buscar_historico]
