const messagesEl = document.getElementById("messages");
const form = document.getElementById("chatForm");
const input = document.getElementById("messageInput");
const resetBtn = document.getElementById("resetBtn");
const kbBtn = document.getElementById("kbBtn");
const kbPanel = document.getElementById("kbPanel");
const kbContent = document.getElementById("kbContent");
const agentBadge = document.getElementById("agentBadge");
const layout = document.querySelector(".layout");

let sessionId = localStorage.getItem("autosfera_session") || null;

function addMessage(role, text, meta = "") {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (meta) {
    const m = document.createElement("span");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  div.appendChild(document.createTextNode(text));
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setTyping(on) {
  const existing = document.getElementById("typing");
  if (existing) existing.remove();
  if (!on) return;
  const div = document.createElement("div");
  div.id = "typing";
  div.className = "msg bot typing";
  div.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage(text) {
  addMessage("user", text);
  setTyping(true);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId, channel: "web" }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem("autosfera_session", sessionId);
    agentBadge.textContent = data.agent_label;
    const meta = [
      data.agent_label,
      data.skill ? `skill: ${data.skill}` : null,
      data.escalated ? "эскалация" : null,
    ].filter(Boolean).join(" · ");
    setTyping(false);
    addMessage("bot", data.reply, meta);
  } catch (err) {
    setTyping(false);
    addMessage("bot", `Ошибка: ${err.message}`);
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

document.getElementById("quickReplies").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-q]");
  if (!btn) return;
  sendMessage(btn.dataset.q);
});

resetBtn.addEventListener("click", async () => {
  if (sessionId) {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  }
  sessionId = null;
  localStorage.removeItem("autosfera_session");
  messagesEl.innerHTML = "";
  agentBadge.textContent = "Ожидание маршрутизации";
  addMessage("bot", "Новый диалог. Я ИИ-оркестратор AutoSfera AI — опишите ваш запрос.");
});

kbBtn.addEventListener("click", async () => {
  const open = kbPanel.classList.toggle("hidden") === false;
  layout.classList.toggle("kb-open", open);
  if (!open) return;
  const res = await fetch("/api/knowledge");
  const data = await res.json();
  kbContent.replaceChildren();
  Object.entries(data.sections).forEach(([section, docs]) => {
    const wrap = document.createElement("div");
    wrap.className = "kb-section";
    const title = document.createElement("h3");
    title.textContent = section;
    wrap.appendChild(title);
    docs.forEach((doc) => {
      const item = document.createElement("div");
      item.className = "kb-doc";
      const strong = document.createElement("strong");
      strong.textContent = doc.title;
      item.appendChild(strong);
      item.appendChild(document.createTextNode(doc.content));
      wrap.appendChild(item);
    });
    kbContent.appendChild(wrap);
  });
});

addMessage("bot", "Здравствуйте! Вы общаетесь с AutoSfera AI. Опишите задачу — оркестратор подключит нужного ассистента.");
