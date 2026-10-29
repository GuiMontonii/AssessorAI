# Etapa 8 - Decisao tecnica (versao para validacao)

## 1. Problema e decisao

Na base da Etapa 7, `add_transaction`, `update_transaction` e `add_event` executavam SQL dentro de `get_conn()` e encerravam o bloco com `commit()` antes de `no_juiz`. O juiz poderia rejeitar a resposta e a escrita continuar no PostgreSQL.

**Decisao:** **ADIAR**, com **confirmacao atomica em transacao curta**. O `ToolRuntime` recebe `AgentContext` com identificador do turno. As tres tools publicas mantem seus nomes, mas, no chat, passam a registrar uma proposta em `escritas_pendentes` em vez de escrever imediatamente. O especialista e o orquestrador produzem uma resposta candidata que indica a pendencia. O juiz da Etapa 7 valida a resposta e, quando ha escritas, responde na mesma requisicao JEV uma pergunta extra (`autorizar_escritas`) sobre a coerencia das acoes. Sem aprovacao explicita nas duas avaliacoes (`>=0,70`), nenhuma escrita acontece.

**Fluxo anterior:** usuario -> especialista -> tool INSERT/UPDATE e commit -> orquestrador -> guardrail -> juiz -> chat.

**Fluxo atualizado:** usuario -> especialista -> tool prepara acao -> orquestrador -> guardrail -> juiz -> (recusa: descarte / aprovacao: uma transacao SQL com todas as acoes e registro de idempotencia) -> resposta -> MongoDB.

As duas confirmacoes financeiras e a de agenda reutilizam os helpers `_db` ja existentes, agora aceitando `conn` opcional para participar de uma unica transacao. O SQL de criacao/alteracao permanece nesses helpers. Uma falha de qualquer acao aborta a transacao inteira. O banco gera a resposta de confirmacao por dados retornados pelo `RETURNING`, e nao por uma afirmacao inventada pelo modelo.

## 2. Invariante das tres ferramentas

- Recusa, baixo escore, indisponibilidade ou erro do juiz: `escritas_pendentes` nao e confirmada.
- Aprovacao: todas as acoes sao aplicadas em uma transacao PostgreSQL; qualquer falha provoca `rollback` integral.
- `escritas_turno(turno_id PRIMARY KEY)` grava o resultado junto com as alteracoes. Nova chamada de confirmacao com **o mesmo turno_id** devolve o resultado original e nao repete a escrita.
- O fallback de modelos limpa a lista de acoes da tentativa falha antes de experimentar o proximo provedor.
- Uma chamada de ferramenta identica repetida no mesmo turno e preparada uma vez. Duas escritas intencionalmente identicas precisam ser diferenciadas por dados da operacao para nao serem confundidas com repeticao acidental.
- O controle de conflito de agenda e reexecutado sob trava transacional por usuario (`pg_advisory_xact_lock`) no momento da confirmacao.

**Limite importante:** cada novo `POST /chat` gera novo `turno_id`. A mesma frase enviada outra vez como *nova mensagem* e uma nova solicitacao, podendo gerar outra escrita. Dedupe robusta de *reenvio do mesmo HTTP request apos perda da resposta* exigiria identificador de requisicao estavel do cliente, o que alteraria o contrato atual. Nao foi adicionado para preservar a API do professor.

## 3. Alternativas descartadas

| Familia | Vantagem real | Custo e motivo para nao adotar isoladamente |
|---|---|---|
| Interceptar | Rejeita acao inadequada antes de chamar SQL. | A avaliacao da intencao nao substitui o juiz final; uma validacao previa pode aprovar e o juiz posterior recusar. Precisaria mudar profundamente o momento e o contrato da avaliacao. Foi combinada apenas uma verificacao semantica das acoes na **mesma chamada** JEV. |
| Transacionar durante o juiz | Permite `COMMIT` se aprovada e `ROLLBACK` se rejeitada. | Mantem transacao e possiveis locks do PostgreSQL abertos durante a chamada externa TypeSafe, inclusive timeout. Inadequado para SLO e concorrencia do projeto. Adotada transacao **curta depois** do juiz. |
| Compensar | Pode ser util quando o efeito externo ja aconteceu. | A recusa acontece depois do `commit`; DELETE/UPDATE inverso pode falhar ou apagar atualizacoes concorrentes. Nao garante que nenhum efeito da recusa permaneceu durante quedas de processo. |

## 4. Impacto no monitor e no SLO

- O monitor existente continua coletando turnos, status, tokens, custo e latencia sem alterar as rotas.
- **JEV:** continua com uma chamada de rede; so aumenta o numero de perguntas *dentro* da mesma chamada quando ha pendencia. Isso pode modificar ligeiramente a latencia do proprio JEV, mas nao obriga outra chamada de LLM.
- **Confirmacao SQL:** acrescenta uma curta transacao e um registro de `escritas_turno`. Podera aumentar a latencia; medir P95 contra o SLO de **8 segundos**.
- **Cambio USD/BRL:** acrescenta uma consulta HTTP de ate 5 segundos quando ha valores em USD; usa cache de 15 minutos por processo. Pode afetar o P95. Nao e custo de token.
- **Taxa de erro:** excecoes nao tratadas de banco produzem turno `erro` (SLO de ate **5%**). Rejeicoes normais do juiz produzem resposta segura sem excecao. Bloqueio do guardrail de entrada continua `bloqueado` e nao conta como excecao.
- A alternativa "transacao aberta enquanto juiz responde" ocuparia uma conexao e possivelmente locks durante toda a espera externa; a escolhida nao faz isso.
- Os custos do monitor continuam sendo estimativas de chamadas de modelos. A API de cambio e o JEV nao estao contabilizados ali como tokens dos modelos existentes.

## 5. Outras decisoes e escopo

- **`add_google_event`:** nao faz parte das ferramentas registradas no agente de agenda deste ZIP; nao foi criada integracao externa nova.
- **`salvar_mensagem`:** continua gravando a fala final no MongoDB depois do juiz e da eventual confirmacao. Como nao existe transacao distribuida Mongo + PostgreSQL, eventual falha na memoria e registrada no log; nao se mente ao usuario dizendo que o registro financeiro foi desfeito. MongoDB e historico conversacional, nao fonte de verdade dos gastos.
- **Juiz indisponivel:** *fail closed*; nao confirma operacoes pendentes e usa frase segura da Etapa 7.
- **Queda de processo:** antes do commit nao ha escrita duravel; durante a transacao PostgreSQL faz rollback; depois do commit pode haver confirmacao sem resposta HTTP. O registro por `turno_id` previne repeticao desse mesmo turno, mas nao resolve novo POST sem idempotency key do cliente.
- **MCP:** `app/mcp_server.py` nao foi alterado. O chat usa `ToolRuntime[AgentContext]` para preparar; a interface MCP independente nao faz parte do caminho `/chat` e nao recebe essa autorizacao. Nao se afirma que o MCP e um fluxo de escrita protegido pela Etapa 8.
- **Conversao cambial:** o banco mantem `valor` em BRL para saldo e passa a registrar `valor_original`, `moeda_original`, `taxa_cambio`, `data_cotacao` e `fonte_cotacao`. Para USD consulta-se a taxa de referencia mais recente do **Frankfurter v2** e multiplica-se via `Decimal`; nao ha cotacao no prompt. Trata-se de valor **aproximado**, nao necessariamente o cobrado pelo banco/cartao. Sem cotacao ou com moedas ambiguas/mistas, a tool recusa preparar a escrita. Outras moedas ainda nao sao suportadas. A taxa usada e a mais recente disponivel, nao necessariamente uma cotacao historica da data da compra.
- Para limitar a alteracao, mantiveram-se FastAPI, contratos do `/chat`, interfaces, nomes das tools, Qdrant, MongoDB e tabelas `transactions`/`events`; houve apenas migracao aditiva de colunas de moedas e uma tabela de idempotencia.

## 6. Evidencias e validacao pendentes

Os testes automatizados `python -m unittest discover -s tests -v` cobrem preparacao sem escrita, aprovacao, recusa, rollback de duas acoes, atualizacao, conflito de agenda, idempotencia por turno, falta de cotacao e aprovacao separada das escritas pelo juiz. Sao **testes isolados com banco e JEV simulados**. Nao comprovam a integracao real com os provedores e o PostgreSQL. A execucao real deve ser documentada com marcador unico, veredito `[juiz]`, status do monitor e `SELECT` antes e depois de cada operacao; instrucoes em `docs/ETAPA8_VALIDACAO.md`.

## 7. Arquivos criados

- `app/tools/pendencias.py`: preparacao e confirmacao atomica/idempotente das tres operacoes.
- `app/tools/cambio.py`: deteccao de moeda e conversao externa USD/BRL.
- `tests/test_etapa8.py`: testes isolados de integridade, juiz, agenda e cambio.
- `docs/ETAPA8_VALIDACAO.md`: plano de verificacao real no Windows/PostgreSQL.
- `decisao_tecnica.md`: esta justificativa.

## 8. Arquivos modificados

- `app/context.py`: identidade e dados de escrita do turno.
- `app/agents.py`: limpar pendencias antes do fallback de modelo.
- `app/graph.py`: transportar pendencias e executar confirmacao apenas apos juiz aprovado; resposta final de banco e registro de erro Mongo.
- `app/juiz.py`: `juiz_aprovado` explicito e validacao de acoes pendentes, na mesma chamada ao JEV.
- `app/tools/financeiro.py`: preparar `add_transaction`/`update_transaction`, preservar `_db` e habilitar conexao compartilhada e metadados de moeda.
- `app/tools/agenda.py`: preparar `add_event`, preservar `_db`, permitir transacao compartilhada e travar checagem de conflito.
- `app/tools/db.py`: migracao aditiva das colunas cambiais e tabela `escritas_turno`.
- `database.sql`: representar o mesmo schema atualizado, sem apagar dados antigos.
- `app/prompts.py`: esclarecer que status `pendente` nao representa gravacao; nenhuma taxa de cambio adicionada.

*Documento em revisao: anexar evidencias reais dos tres caminhos ao finalizar a validacao com o professor.*



## Auditoria pontual (29/10/2026)

Na revisao do ZIP da Etapa 8, foram realizados ajustes pontuais sem substituir a arquitetura: normalizacao de aliases de despesa nas ferramentas financeiras, rejeicao explicita de moedas estrangeiras nao suportadas (inclusive GBP e JPY), passagem da rota FAQ pelo guardrail de saida e adiamento da criacao do indice do perfil para o momento da gravacao do perfil. O README tambem foi atualizado para apontar para o comando existente de indexacao do FAQ.

Os testes `python -m unittest discover -s tests -v` sao unitarios/isolados e nao constituem comprovacao de funcionamento real com PostgreSQL, TypeSafe, Gemini, MongoDB e Qdrant. As evidencias SQL antes/depois, autorizacoes e recusas reais e metricas comparativas do monitor permanecem pendentes de execucao documentada em ambiente de teste. O recibo final e produzido deterministicamente com dados confirmados pelo banco, apos o julgamento da resposta candidata; ele nao e submetido a um segundo julgamento.
