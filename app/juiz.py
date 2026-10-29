"""
Juiz de fidelidade - Etapa 7 (JEV/TypeSafe).

Segue o contrato e a rubrica do roteiro do professor:
choice == 'apoiada' e noul >= 0.70 deixam a frase intacta;
os outros vereditos ou falhas devolvem a frase segura.

Adaptacao minima: atualiza tambem o campo 'resposta' usado pelo /chat
e preserva a trilha de agentes do grafo existente.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import TYPESAFE_API_KEY

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODELO = "jev-latest"
LIMIAR = 0.70
FRASE_SEGURA = "Não tenho evidência para afirmar isso."

REGRAS = (
    "A pergunta do usuário também é evidência do que ele disse que fez. "
    "Somas, contagens, datas convertidas para o horário de Brasília e "
    "reformatação de valores tirados da evidência contam como apoiada. "
    "Esclarecimento, saudação, oferta de ajuda, sugestão de próximo passo "
    "e ausência de registro contam como apoiada. "
    "Opinião do usuário pode ser citada como fala dele. "
    "A moeda de cada valor é a que aparece no source_text ou na fala do usuário. "
    "Moeda trocada, valores de moedas diferentes somados num total só, "
    "opinião dita como fato do sistema, número, data, telefone ou regra "
    "que não saiam da evidência contam como sem_apoio."
)


def _texto(mensagem) -> str:
    conteudo = getattr(mensagem, "content", "")
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        pedacos = []
        for parte in conteudo:
            if isinstance(parte, str):
                pedacos.append(parte)
            elif isinstance(parte, dict):
                pedacos.append(str(parte.get("text") or ""))
        return "\n".join(p for p in pedacos if p)
    return str(conteudo or "")


def _coleta(estado):
    pergunta = ""
    resposta = ""
    evidencias = []
    for mensagem in estado["messages"]:
        tipo = getattr(mensagem, "type", "")
        texto = _texto(mensagem).strip()
        if tipo == "human" and texto:
            pergunta = texto
            evidencias = []
            resposta = ""  # Somente a resposta do turno corrente.
        elif tipo == "tool" and texto:
            nome = getattr(mensagem, "name", "") or "tool"
            evidencias.append(f"[{nome}]\n{texto}")
        elif tipo == "ai":
            for chamada in getattr(mensagem, "tool_calls", None) or []:
                argumentos = json.dumps(chamada.get("args", {}), ensure_ascii=False)
                evidencias.append(f"[chamada {chamada.get('name')}]\n{argumentos}")
            if texto:
                resposta = texto

    # O grafo deste ZIP tambem monta memoria no no 'memoria', sem invocar uma
    # tool. Quando existe contexto do Mongo/Qdrant, ele e evidencia recuperada.
    memoria = (estado.get("memoria_contexto") or "").strip()
    if memoria and memoria != "Sem memoria adicional relevante.":
        evidencias.append(f"[memoria_recuperada]\n{memoria}")

    evidencia = "\n\n".join(evidencias).strip()
    if not evidencia:
        evidencia = "(nenhuma tool devolveu conteúdo neste turno)"
    return pergunta, resposta, evidencia[-6000:]


def _publicar(texto, rotulo, resposta_original, aprovado=False):
    print(f"[juiz] {rotulo}")
    if texto.strip() == (resposta_original or "").strip():
        return {"agentes_chamados": [f"juiz:{rotulo}"], "juiz_aprovado": aprovado}
    return {
        "messages": [{"role": "assistant", "content": texto.strip()}],
        "agentes_chamados": [f"juiz:{rotulo}"],
        "juiz_aprovado": aprovado,
    }


def _julgar_jev(pergunta, resposta, evidencia, acoes_pendentes=None):
    if not TYPESAFE_API_KEY:
        return _publicar(FRASE_SEGURA, "sem_chave", resposta)
    acoes_pendentes = acoes_pendentes or []
    perguntas = {
        "veredito": {
            "type": "choice",
            "instructions": "Seguindo as regras, a resposta so afirma o que a evidencia sustenta?",
            "criteria": {
                "apoiada": "toda afirmacao factual aparece na evidencia",
                "parcial": "parte aparece e parte nao",
                "sem_apoio": "ha fato, numero, regra ou opiniao sem evidencia",
            },
        },
        "apoiada": {
            "type": "noul",
            "instructions": (
                "Seguindo as regras, a resposta e fiel a evidencia: todo valor, moeda, "
                "data e fato dela sai da evidencia, da fala do usuario ou de contas sobre elas?"
            ),
        },
    }
    if acoes_pendentes:
        perguntas["autorizar_escritas"] = {
            "type": "noul",
            "instructions": (
                "As acoes pendentes foram explicitamente solicitadas pelo usuario, com "
                "tipo, valor, moeda, descricao e horario coerentes com a fala e a evidencia? "
                "A resposta deve descrever uma preparacao a ser confirmada, sem anunciar "
                "gravacao ja realizada nem negar que a operacao sera executada. "
                "Gastos, compras e despesas correspondem a tipo saida; receitas e "
                "recebimentos, a entrada. Reais e R$ correspondem a BRL. "
                "Campos padrao da ferramenta nao exigem mencao literal se nao "
                "contradizem o pedido. Na menor duvida, responda nao."
            ),
        }
    corpo = json.dumps({
        "model": JEV_MODELO,
        "state": {
            "pergunta": pergunta,
            "resposta": resposta,
            "evidencia": evidencia,
            "regras": REGRAS,
            "acoes_pendentes": acoes_pendentes,
        },
        "questions": perguntas,
    }).encode()
    pedido = urllib.request.Request(
        JEV_URL,
        data=corpo,
        headers={
            "Authorization": f"Bearer {TYPESAFE_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resp:
            dados = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return _publicar(FRASE_SEGURA, f"erro http {exc.code}", resposta)

    respostas = dados["answers"]
    choice = respostas["veredito"]["choice"]
    noul = float(respostas["apoiada"]["noul"])
    nota_escritas = float(respostas["autorizar_escritas"]["noul"]) if acoes_pendentes else None
    escritas_ok = nota_escritas is None or nota_escritas >= LIMIAR
    notas = f"noul={noul:.2f}"
    if nota_escritas is not None:
        notas += f" autorizacao_escritas={nota_escritas:.2f}"
    if choice == "apoiada" and noul >= LIMIAR and escritas_ok:
        return _publicar(resposta, f"apoiada {notas}", resposta, aprovado=True)
    rotulo = "apoiada:abaixo_do_limiar" if choice == "apoiada" else choice
    if not escritas_ok:
        rotulo = "escritas_recusadas"
    return _publicar(FRASE_SEGURA, f"{rotulo} {notas}", resposta)


def no_juiz(estado: dict) -> dict:
    pergunta, resposta, evidencia = _coleta(estado)
    if not resposta:
        return {
            "juiz_aprovado": False,
            "agentes_chamados": estado.get("agentes_chamados", []) + ["juiz:sem_resposta"],
        }
    try:
        resultado = _julgar_jev(pergunta, resposta, evidencia, estado.get("escritas_pendentes"))
    except Exception as exc:
        print(f"[juiz] erro {exc}")
        resultado = _publicar(FRASE_SEGURA, "erro", resposta)

    # O roteiro adiciona a mensagem ao estado; esta API tambem usa o campo
    # 'resposta'. Sem essa adaptacao, o usuario veria a frase NAO aprovada.
    if resultado.get("messages"):
        resultado["resposta"] = resultado["messages"][-1]["content"]
    else:
        resultado["resposta"] = resposta

    # LangGraph substitui listas sem reducer; nao descartar a trilha anterior.
    resultado["agentes_chamados"] = (
        estado.get("agentes_chamados", []) + resultado.get("agentes_chamados", [])
    )
    return resultado
