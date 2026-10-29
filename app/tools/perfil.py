from __future__ import annotations

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.context import AgentContext
from app.profile import buscar_perfil, buscar_preferencias

@tool
def consultar_perfil_financeiro(
    busca: str,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """
    Consulta o perfil financeiro cadastrado do usuário atual.

    Use quando uma recomendação depender de renda, objetivo,
    tolerância a risco ou preferências pessoais.

    O argumento busca descreve semanticamente o assunto relevante
    das preferências.
    """

    user_id = runtime.context.user_id

    perfil = buscar_perfil(user_id)

    if not perfil:
        return {
            "status": "sem_perfil",
            "mensagem": (
                "O usuário não possui perfil financeiro cadastrado. "
                "Oriente-o a usar a tela Perfil."
            ),
        }

    preferencias = buscar_preferencias(user_id, busca)

    return {
        "status": "ok",
        "renda_mensal": perfil["renda_mensal"],
        "objetivo": perfil["objetivo"],
        "tolerancia_risco": perfil["tolerancia_risco"],
        "preferencias_relevantes": preferencias,
    }

TOOLS_PERFIL = [consultar_perfil_financeiro]