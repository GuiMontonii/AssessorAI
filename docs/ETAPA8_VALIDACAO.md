# Etapa 8 - como validar no computador (nao usar com dados reais)

## Antes de comecar

1. Preserve o ZIP da Etapa 7 ja salvo. **Nao apague o projeto anterior.**
2. Extraia o ZIP da Etapa 8 em outra pasta. O ZIP nao traz `.env`.
3. Copie seu `.env` **localmente**, sem publicar ou enviar credenciais.
4. Certifique-se de que sua `DATABASE_URL` aponta para um ambiente de TESTE ou base que voce possa usar com marcadores ficticios. O script de inicializacao cria colunas em `transactions` e a tabela `escritas_turno` automaticamente, sem apagar lancamentos existentes.
5. Execute `python -m pip install -r requirements.txt`, `python -m unittest discover -s tests -v` e `python -m uvicorn app.main:app --reload`.
6. Abra `http://127.0.0.1:8000/` e `/monitor.html`.

## Verificacao antes de criar dados

Confirme que as tabelas existem apos o primeiro acesso ao PostgreSQL:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'transactions'
ORDER BY ordinal_position;

SELECT table_name FROM information_schema.tables
WHERE table_name = 'escritas_turno';
```

Use **um identificador exclusivo** por tentativa, por exemplo `ET8-CRIA-001`, `ET8-UPDATE-001`, `ET8-AGENDA-001`, para nao confundir com outras conversas. O fluxo de registro precisa seguir `... -> juiz:apoiada ... -> confirmar_escritas` para considerar a escrita confirmada.

### Caso A - Criacao financeira aprovada

Pergunta: `Registre uma despesa de R$ 42,50 com descricao ET8-CRIA-001.`

```sql
SELECT id, user_id, descricao, valor, moeda_original, valor_original
FROM transactions WHERE descricao = 'ET8-CRIA-001';
```

Resultado esperado: antes zero linha; depois, **exatamente uma** linha com valor 42,50 em BRL. O juiz pode recusar mesmo uma instrucao valida (ele e probabilistico); se recusar, a consulta deve continuar sem linha.

### Caso B - Atualizacao

Crie primeiro uma despesa ficticia com descricao `ET8-UPDATE-001`. Anote o ID.

```sql
SELECT id, valor, descricao, categoria, tipo FROM transactions
WHERE descricao = 'ET8-UPDATE-001';
```

Pergunte: `Altere a transacao ID <ID_REAL> para R$ 32,00.` Apos `juiz:apoiada` e confirmacao, o valor do **mesmo ID** deve mudar uma vez. Se o juiz recusar, o valor original deve permanecer. Teste somente com registro criado por voce e nesse banco de testes.

### Caso C - Agenda

Pergunta: `Crie um compromisso ET8-AGENDA-001 em 03/11/2026 das 10h as 11h, horario de Brasilia.`

```sql
SELECT id, titulo, inicio, fim FROM events
WHERE titulo = 'ET8-AGENDA-001';
```

Resultado esperado: exatamente um evento se o juiz aprovar; nenhum na recusa. A aplicacao mantem a interpretacao original de datas ISO da ferramenta; confira o fuso exibido.

### Caso D - USD sem cotacao fixa no prompt

Pergunta: `Comprei um jogo de 5 dolares, registre como despesa ET8-USD-001.`

```sql
SELECT descricao, valor AS valor_brl, moeda_original,
       valor_original, taxa_cambio, data_cotacao, fonte_cotacao
FROM transactions WHERE descricao = 'ET8-USD-001';
```

Se aprovada, a coluna `valor` deve conter a conversao BRL estimada da fonte externa. `valor_original=5.00` e `moeda_original='USD'`. **Nao ha taxa de cambio fixada no codigo ou prompt.** Se a API de cambio nao estiver acessivel, nenhuma escrita deve ser feita; o assistente devera comunicar a indisponibilidade.

### Caso E - juiz recusa / falha

Os testes controlados em `tests/test_etapa8.py` simulam `juiz_aprovado=False`, rejeicao de escrita e sem chave. Neles o confirmador nao e chamado. Para uma evidencia real com SQL, a recusa precisa ocorrer em uma mensagem de teste com marcador. Registre a resposta `juiz:*` do terminal e compare `SELECT` antes e depois. Nao force a recusa desativando o juiz em producao.

### Caso F - duas acoes, uma falha

Os testes isolados simulam uma insercao seguida de atualizacao falha e demonstram que nem a insercao nem a tabela de idempotencia persistem. A prova final deve ser feita no banco de testes, nao com dados pessoais.

### Caso G - repeticao de confirmacao

Os testes isolados chamam o confirmador duas vezes com o mesmo `turno_id` e confirmam uma so aplicacao. Repetir a mesma frase pelo chat cria novo turno e **pode gerar outro registro**. Esta e uma limitacao documentada da API atual sem idempotency key do cliente.

## Sobre o dashboard

Acompanhamento de `p95 <= 8 s`, erro `<= 5%`, tokens e custo continua. `juiz:sem_chave`, `erro http`, e `escritas_recusadas` nao confirmam escrita. Compare a latencia da Etapa 7 com a da Etapa 8; a consulta cambial pode aumentar o tempo de um registro em USD.

## Se algo falhar

Copie **a mensagem do terminal sem credenciais** e envie para revisao. Nao altere o juiz para aprovar sempre, nao force `commit()` antes do veredito e nao apague linhas manualmente como parte de um teste de rollback.
