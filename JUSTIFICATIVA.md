# JUSTIFICATIVA

## 1. Quais arquivos você criou ou modificou?

Criados:
- app/profile.py
- app/routes/perfil.py
- app/tools/perfil.py

Modificados:
- app/schemas.py
- app/vectorstore.py
- app/main.py
- app/agents.py
- app/prompts.py
- frontend/perfil.js

Também foram adicionados ao diretório frontend/ os arquivos perfil.html e perfil.css fornecidos na atividade. O arquivo frontend/perfil.js foi ajustado para reutilizar o mesmo user_id estável utilizado pelo chat, armazenado no localStorage pela chave assessor_user_id.

## 2. Por onde o perfil entra, e onde cada parte dele é gravada?

O perfil entra pela rota POST /perfil. O cadastro completo é persistido na collection perfis do MongoDB e o campo preferencias também é transformado em embedding e armazenado na collection perfil_preferencias do Qdrant. Quando o mesmo user_id salva o formulário novamente, o documento do MongoDB é atualizado e o mesmo Point do Qdrant é sobrescrito, evitando perfis e preferências duplicadas.

## 3. Como as preferencias são guardadas e consultadas, e por que não é busca por palavra?

As preferencias são convertidas em um embedding de 768 dimensões e armazenadas no Qdrant. A consulta utiliza similaridade de cosseno, permitindo encontrar informações semanticamente relacionadas mesmo quando a pergunta não possui as mesmas palavras do texto cadastrado. Por exemplo, uma pergunta sobre criptomoedas pode recuperar uma preferência como "não quero investimento agressivo", mesmo sem a palavra "cripto" aparecer no cadastro.

## 4. Você criou uma tool ou duas? Por quê?

Foi criada uma única tool, consultar_perfil_financeiro. Ela reúne os dados estruturados do MongoDB e as preferências semanticamente relevantes do Qdrant, pois todas essas informações fazem parte do mesmo perfil financeiro utilizado pelo especialista. A tool é somente de consulta; não existe tool para criar ou alterar o perfil.

## 5. O que garante que o perfil de um usuário não apareceria para outro, se houvesse mais de um?

Todas as consultas ao MongoDB utilizam o user_id do usuário atual e as consultas ao Qdrant possuem filtro obrigatório pelo mesmo user_id. A collection perfil_preferencias também utiliza user_id como campo de tenant. O user_id não é escolhido pelo modelo: ele vem do contexto da requisição. A tela Perfil e o chat compartilham o mesmo identificador estável salvo no localStorage como assessor_user_id.

## 6. Sua tool consulta o banco diretamente ou faz uma chamada HTTP na própria API? Por quê?

A tool consulta diretamente a camada de persistência em Python, acessando MongoDB e Qdrant pelas funções internas da aplicação. Fazer uma requisição HTTP para a própria API adicionaria complexidade e latência sem necessidade.

## 7. Por que não existe um agente "perfil"?

O perfil não é um novo domínio do sistema. Ele é um dado de apoio utilizado pelo especialista financeiro para personalizar suas recomendações, portanto não foi criado um agente separado para perfil.

## 8. Por que o chat não altera o cadastro?

O especialista financeiro possui apenas uma tool de leitura do perfil. A função de escrita é chamada exclusivamente pela rota POST /perfil, portanto alterações de renda, objetivo, tolerância a risco e preferências só podem ser feitas pela tela Perfil. Se o usuário pedir uma alteração pelo chat, o assessor apenas orienta que a mudança seja feita pela tela Perfil.