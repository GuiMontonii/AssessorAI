# Assessor.AI - FastAPI (base Etapa 4 + controle de alucinacao da Etapa 7)

> **Etapa 7:** instrucoes e testes em [`docs/ETAPA7_GUIA.md`](docs/ETAPA7_GUIA.md).

Projeto FastAPI com a **Etapa 4 - Busca Semantica com Qdrant** integrada ao que ja existia na Etapa 3.

A Etapa 4 troca:

- busca por `$regex` do MongoDB -> busca semantica no Qdrant para memoria;
- FAISS recriado a cada pergunta -> collection persistente `faq_chunks` no Qdrant.

O MongoDB **nao foi removido**: ele continua sendo a fonte de verdade das sessoes e mensagens completas. O Qdrant e o indice semantico que aponta de volta para o `doc_id` do MongoDB.

## Arquitetura final

```text
Frontend
   |
FastAPI
   |
LangGraph / agentes
   |---------------- PostgreSQL (financeiro + agenda)
   |---------------- MongoDB local (sessoes + mensagens + resumos)
   `---------------- Qdrant Cloud
                      |-- memoria_resumos
                      `-- faq_chunks
```

## 1. Use Python 3.12

Evite Python 3.14 neste projeto, porque algumas dependencias do ecossistema LangChain ainda podem emitir avisos de compatibilidade.

No PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. MongoDB local

O projeto usa por padrao:

```text
mongodb://127.0.0.1:27017
```

Verifique no Windows:

```powershell
Get-Service MongoDB
```

Se estiver parado:

```powershell
Start-Service MongoDB
```

Nao precisa criar o banco manualmente. O projeto usa banco `assessor_ai` e collection `sessoes`.

## 3. Criar o Qdrant Cloud

A Etapa 4 exige Qdrant Cloud.

1. Acesse `https://cloud.qdrant.io`.
2. Crie uma conta.
3. Crie um cluster no tier **Free**.
4. Escolha uma regiao.
5. Dê um nome como `assessor`.
6. Copie a URL do cluster e a API Key.

Guarde a API Key. Nao coloque ela no Git.

## 4. Configurar `.env`

O arquivo deve ficar assim:

```env
GEMINI_API_KEY=SUA_CHAVE_GEMINI
DATABASE_URL=SUA_URL_POSTGRES
GROQ_API_KEY=SUA_CHAVE_GROQ
MONGODB_URI=mongodb://127.0.0.1:27017
QDRANT_URL=https://SEU_CLUSTER.REGIAO.cloud.qdrant.io:6333
QDRANT_API_KEY=SUA_CHAVE_QDRANT
```

Use a URL atual do seu PostgreSQL. Se a Aiven informar `postgres://`, o codigo converte internamente para `postgresql://`.

## 5. Criar as duas collections

O roteiro pede:

| Collection | Uso | Vetor | Distancia |
|---|---|---:|---|
| `memoria_resumos` | memoria entre sessoes, multitenancy por `user_id` | 768 | Cosine |
| `faq_chunks` | RAG do FAQ, global | 768 | Cosine |

Voce **nao precisa criar manualmente pela interface**: o projeto inclui um script que cria as duas exatamente com essas configuracoes e cria o indice de tenant em `user_id`.

Depois de preencher o `.env`:

```powershell
python -m app.setup_qdrant
```

Esperado:

```text
[qdrant] Conexao OK
[qdrant] memoria_resumos: 0 ponto(s)
[qdrant] faq_chunks: 0 ponto(s)
[qdrant] dimensao: 768
```

## 6. FAQ - indexar uma vez

A Etapa 4 separa indexacao de consulta.

O local oficial do PDF e:

```text
data/FAQ_assessor_v1.1.pdf
```

O projeto que serviu de base nao continha esse PDF, por isso `app/ingest_faq.py` foi deixado robusto:

- se o PDF existir, usa `PyPDFLoader`;
- se nao existir, usa `data/FAQ_assessor_v1.1.txt` como fallback;
- assim o comando nao quebra com `File path ... is not a valid file or url`.

Para indexar:

```powershell
python -m app.ingest_faq
```

O script:

1. carrega o FAQ;
2. quebra em chunks de 700 com overlap 150;
3. gera embeddings `gemini-embedding-2-preview` com 768 dimensoes;
4. limpa somente `faq_chunks`;
5. faz `upsert` no Qdrant.

Rode de novo apenas quando o FAQ mudar.

## 7. user_id x session_id

Na Etapa 4 os dois identificadores tem papeis diferentes:

- `session_id`: identifica a conversa atual e muda entre sessoes;
- `user_id`: identifica a pessoa de forma estavel e liga as memorias entre sessoes.

O frontend ja gera um `user_id` uma vez e guarda no `localStorage`. Agora ele tambem envia esse campo no `POST /chat`.

O request aceita:

```json
{
  "session_id": "uuid-da-conversa",
  "user_id": "usuario_teste",
  "pergunta": "fiz alguma viagem em agosto?"
}
```

## 8. Como a memoria funciona

Ao encerrar uma sessao:

```text
mensagens no MongoDB
   -> resumo
   -> embedding 768d
   -> upsert em memoria_resumos
      payload: doc_id + user_id + session_id + resumo + datas
```

Em uma nova sessao:

```text
pergunta
   -> embedding 768d
   -> query_points em memoria_resumos
   -> filtro user_id
   -> top 3 por similaridade de cosseno
   -> payload devolve doc_id
   -> se precisar de detalhe literal, MongoDB recupera as mensagens completas
```

Nao ha mais `$regex` para busca semantica.

## 9. FAQ durante o chat

`app/tools/faq.py` nao usa mais FAISS. A cada pergunta ele somente:

```text
pergunta -> embedding -> query_points(faq_chunks) -> top 6 chunks
```

Ou seja, o PDF nao e reprocessado a cada pergunta.

## 10. Rodar FastAPI

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abra:

```text
Frontend: http://127.0.0.1:8000
Swagger:  http://127.0.0.1:8000/docs
Health:   http://127.0.0.1:8000/health
```

## 11. Teste 1 - FAQ via Qdrant

Antes:

```powershell
python -m app.ingest_faq
```

Depois pergunte algo que esteja no FAQ existente, por exemplo:

```text
Onde fica a documentacao da API?
```

A resposta deve usar trechos recuperados da collection `faq_chunks`.

Se voce colocar o PDF oficial fornecido pelo professor, pode usar as perguntas especificas daquele PDF, como o teste indicado no roteiro.

## 12. Teste 2 - memoria semantica

### Sessao 1

Crie sessao:

`POST /sessions`

```json
{
  "user_id": "usuario_teste"
}
```

Converse:

`POST /chat`

```json
{
  "session_id": "SESSION_ID_1",
  "user_id": "usuario_teste",
  "pergunta": "fiz uma viagem para Joao Pessoa em agosto"
}
```

Encerre usando a rota do roteiro:

```text
POST /sessions/SESSION_ID_1/encerrar
```

Ou a rota antiga do frontend, que foi mantida:

```text
DELETE /sessions/SESSION_ID_1
```

### Sessao 2

Crie outra sessao com o **mesmo user_id** e pergunte:

```text
fiz alguma viagem em agosto?
```

Depois teste sinonimos:

```text
quando eu viajei?
qual era meu destino?
```

A busca deve encontrar a memoria de Joao Pessoa mesmo sem repetir exatamente a palavra original.

## 13. Arquivos principais da Etapa 4

```text
app/
|-- vectorstore.py       # Qdrant + embeddings + collections
|-- setup_qdrant.py      # cria/valida collections
|-- ingest_faq.py        # indexacao do FAQ
|-- memory.py            # MongoDB + memoria semantica
|-- schemas.py           # ChatRequest com user_id
|-- graph.py             # propaga user_id no config
|-- routes/
|   |-- chat.py
|   `-- sessions.py
`-- tools/
    |-- faq.py           # consulta faq_chunks
    `-- memoria.py       # tool buscar_historico
```

## 14. Checklist final

1. `qdrant-client` instalado.
2. Qdrant Cloud criado.
3. `QDRANT_URL` preenchida.
4. `QDRANT_API_KEY` preenchida.
5. MongoDB local rodando.
6. `python -m app.setup_qdrant` funcionando.
7. `memoria_resumos` criada com 768/Cosine e tenant `user_id`.
8. `faq_chunks` criada com 768/Cosine.
9. `python -m app.ingest_faq` concluido.
10. FAQ respondendo via Qdrant.
11. Uma sessao encerrada gerando resumo.
12. Segunda sessao com mesmo `user_id` recuperando o resumo.
13. Busca por sinonimo encontrando memoria relevante.
14. FastAPI subindo sem erro em `http://127.0.0.1:8000/docs`.

## Observacao sobre credenciais

O ZIP nao inclui suas chaves reais. Preencha o `.env` localmente e mantenha `.env` fora do Git.
