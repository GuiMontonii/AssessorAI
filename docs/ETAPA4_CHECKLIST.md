# Etapa 4 - checklist

- [x] `qdrant-client` no `requirements.txt`
- [ ] `QDRANT_URL` preenchida no `.env`
- [ ] `QDRANT_API_KEY` preenchida no `.env`
- [ ] Cluster gratuito criado no Qdrant Cloud
- [x] `app/vectorstore.py` criado
- [x] `app/config.py` atualizado
- [x] `app/schemas.py` com `user_id`
- [x] `app/routes/chat.py` propagando `user_id`
- [x] `app/graph.py` propagando `user_id` no `configurable`
- [x] `app/memory.py` usando Qdrant + MongoDB
- [x] `app/tools/faq.py` sem FAISS
- [x] `app/tools/memoria.py` criado
- [x] `app/ingest_faq.py` criado
- [x] `app/setup_qdrant.py` cria as duas collections automaticamente
- [ ] `python -m app.setup_qdrant` executado com suas credenciais
- [ ] `python -m app.ingest_faq` executado
- [ ] FAQ validado via Qdrant
- [ ] Memoria entre duas sessoes validada com sinonimos
