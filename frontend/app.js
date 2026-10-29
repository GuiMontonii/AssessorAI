const state = {
  userId: localStorage.getItem("assessor_user_id") || "",
  sessionId: "",
  busy: false,
};

const els = {
  form: document.getElementById("chatForm"),
  question: document.getElementById("question"),
  send: document.getElementById("sendButton"),
  messages: document.getElementById("messages"),
  status: document.getElementById("sessionStatus"),
  statusDot: document.getElementById("statusDot"),
  sessionId: document.getElementById("sessionId"),
  close: document.getElementById("closeSessionButton"),
  fresh: document.getElementById("newSessionButton"),
  agentTrace: document.getElementById("agentTrace"),
  dialog: document.getElementById("summaryDialog"),
  summary: document.getElementById("summaryText"),
  dialogNew: document.getElementById("dialogNewSession"),
  dialogClose: document.getElementById("dialogClose"),
};

function ensureUserId() {
  if (!state.userId) {
    state.userId = crypto.randomUUID
      ? crypto.randomUUID()
      : `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem("assessor_user_id", state.userId);
  }
}

function setStatus(kind, text, detail = "") {
  els.status.textContent = text;
  els.sessionId.textContent = detail;
  els.statusDot.className = `status-dot ${kind || ""}`;
}

function setBusy(value) {
  state.busy = value;
  els.send.disabled = value || !state.sessionId;
  els.question.disabled = value || !state.sessionId;
  els.close.disabled = value || !state.sessionId;
}

function addMessage(role, text, isError = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${isError ? " error" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "EU" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  bubble.appendChild(paragraph);
  article.append(avatar, bubble);
  els.messages.appendChild(article);
  els.messages.scrollTop = els.messages.scrollHeight;
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

async function createSession() {
  ensureUserId();
  setBusy(true);
  setStatus("", "Criando sessao...", "Conectando ao MongoDB");

  try {
    const data = await jsonRequest("/sessions", {
      method: "POST",
      body: JSON.stringify({ user_id: state.userId }),
    });
    state.sessionId = data.session_id;
    setStatus("ok", "Sessao ativa", state.sessionId);
    els.agentTrace.hidden = true;
    els.question.focus();
  } catch (error) {
    state.sessionId = "";
    setStatus("error", "Falha ao iniciar", error.message);
    addMessage("assistant", `Nao consegui iniciar a sessao: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

async function sendMessage(text) {
  if (!state.sessionId || state.busy) return;

  addMessage("user", text);
  setBusy(true);
  els.agentTrace.hidden = true;

  try {
    const data = await jsonRequest("/chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        user_id: state.userId,
        pergunta: text,
      }),
    });
    addMessage("assistant", data.resposta);

    const agents = data.agentes_chamados || [];
    els.agentTrace.textContent = `Rota: ${data.rota || "-"} | Fluxo: ${agents.join(" -> ")}`;
    els.agentTrace.hidden = false;
  } catch (error) {
    addMessage("assistant", `Erro: ${error.message}`, true);
  } finally {
    setBusy(false);
    els.question.focus();
  }
}

async function closeSession() {
  if (!state.sessionId || state.busy) return;

  setBusy(true);
  try {
    const data = await jsonRequest(`/sessions/${encodeURIComponent(state.sessionId)}`, {
      method: "DELETE",
    });
    els.summary.textContent = data.resumo || "Sessao encerrada sem resumo.";
    state.sessionId = "";
    setStatus("", "Sessao encerrada", "Crie uma nova sessao para continuar");
    els.dialog.showModal();
  } catch (error) {
    addMessage("assistant", `Nao consegui encerrar a sessao: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.question.value.trim();
  if (!text) return;

  els.question.value = "";
  els.question.style.height = "auto";
  await sendMessage(text);
});

els.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.form.requestSubmit();
  }
});

els.question.addEventListener("input", () => {
  els.question.style.height = "auto";
  els.question.style.height = `${Math.min(els.question.scrollHeight, 180)}px`;
});

els.close.addEventListener("click", closeSession);
els.fresh.addEventListener("click", async () => {
  if (state.sessionId && !confirm("A sessao atual ainda esta aberta. Criar outra mesmo assim?")) {
    return;
  }
  await createSession();
});
els.dialogClose.addEventListener("click", () => els.dialog.close());
els.dialogNew.addEventListener("click", async () => {
  els.dialog.close();
  await createSession();
});

ensureUserId();
createSession();
