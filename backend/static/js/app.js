/* ============================================================
   Spike - Chat UI
   ============================================================ */

/* ---------- Elements ---------- */
const messagesEl = document.getElementById("messages");
const msgContainer = document.querySelector(".msg-container");
const formEl = document.getElementById("input-form");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const clearBtn = document.getElementById("clear-btn");
const statusEl = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const chatListEl = document.getElementById("chat-list");
const newChatBtn = document.getElementById("new-chat-btn");
const addChatBtn = document.getElementById("add-chat-btn");
const toggleSidebar = document.getElementById("toggle-sidebar");
const sidebar = document.getElementById("sidebar");
const chatTitle = document.getElementById("chat-title");
const toastEl = document.getElementById("toast");
const scrollFab = document.getElementById("scroll-fab");
const micBtn = document.getElementById("mic-btn");

/* ---------- Auth ---------- */
const authScreen = document.getElementById("auth-screen");
const authLoading = document.getElementById("auth-loading");
const authForm = document.getElementById("auth-form");
const authTitle = document.getElementById("auth-title");
const authSub = document.getElementById("auth-sub");
const authSubmit = document.getElementById("auth-submit");
const authError = document.getElementById("auth-error");
const authSwitchText = document.getElementById("auth-switch-text");
const authSwitchBtn = document.getElementById("auth-switch-btn");
const authNameField = document.getElementById("auth-name-field");
const authName = document.getElementById("auth-name");
const authEmail = document.getElementById("auth-email");
const authPassword = document.getElementById("auth-password");
const authConfirmField = document.getElementById("auth-confirm-field");
const authConfirm = document.getElementById("auth-confirm");
const authGoogle = document.getElementById("auth-google");
const authForgot = document.getElementById("auth-forgot");
const accountArea = document.getElementById("account-area");
const accountName = document.getElementById("account-name");
const accountEmail = document.getElementById("account-email");

const appEl = document.querySelector(".app");

const TOKEN_KEY = "spike_token";
const USER_KEY = "spike_user";
let authMode = "login";

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function getAuthedUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
  catch { return null; }
}
function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
/* STATE management: only one screen visible at a time */
function showAuthScreen(show) {
  if (show) {
    authScreen.classList.remove("hidden");
    appEl.classList.add("hidden");
    if (accountArea) accountArea.hidden = true;
  } else {
    authScreen.classList.add("hidden");
    appEl.classList.remove("hidden");
  }
}
function showLoading(show) {
  if (!authLoading) return;
  if (show) authLoading.classList.remove("hidden");
  else authLoading.classList.add("hidden");
}
function authHeaders(extra) {
  const t = getToken();
  return Object.assign({ "Content-Type": "application/json" }, extra || {},
    t ? { "Authorization": "Bearer " + t } : {});
}
function setAuthMode(mode) {
  authMode = mode;
  const signup = mode === "signup";
  authTitle.textContent = "Welcome to Spike";
  authSub.textContent = signup
    ? "Create your account to get started."
    : "Your AI assistant for thinking, creating, learning, and getting things done.";
  authSubmit.textContent = signup ? "Create account" : "Continue";
  authSwitchText.textContent = signup ? "Already have an account?" : "Don't have an account?";
  authSwitchBtn.textContent = signup ? "Sign in" : "Sign up";
  authNameField.classList.toggle("hidden", !signup);
  authConfirmField.classList.toggle("hidden", !signup);
  authError.textContent = "";
}


/* ---------- State ---------- */
let chats = JSON.parse(localStorage.getItem("chats") || "[]");
let activeId = localStorage.getItem("activeChat") || null;
let busy = false;
let activeController = null; // AbortController for Stop
let lastUserMsg = "";

if (!chats.length) activeId = null;
else if (!chats.some((c) => c.id === activeId)) activeId = chats[0].id;

function save() {
  localStorage.setItem("chats", JSON.stringify(chats));
  localStorage.setItem("activeChat", activeId);
}
function getActive() { return chats.find((c) => c.id === activeId) || null; }
function ensureChat() {
  let chat = getActive();
  if (!chat) { chat = { id: Date.now().toString(36), title: "New chat", messages: [] }; chats.unshift(chat); activeId = chat.id; }
  return chat;
}
function currentModel() {
  return "qwen/qwen3.8-27b";
}

/* ---------- Toast ---------- */
let toastTimer;
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1400);
}

/* ---------- Markdown ---------- */
marked.setOptions({ breaks: true, gfm: true });
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function renderMarkdown(text) {
  const codeBlocks = [];
  const cleaned = text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const id = "cb" + codeBlocks.length;
      codeBlocks.push({ id, lang: lang || "code", code });
      return `\n\n<div class="code-block" data-id="${id}"></div>\n\n`;
    })
    .replace(/`([^`]+)`/g, (m, c) => `<code>${escapeHtml(c)}</code>`);
  let html = marked.parse(cleaned);
  codeBlocks.forEach((cb) => {
    const div = `<div class="code-block"><div class="code-header"><span>${escapeHtml(cb.lang)}</span><button class="copy-btn" type="button" data-full="${escapeHtml(cb.id)}">Copy</button></div><pre><code class="language-${escapeHtml(cb.lang)}">${escapeHtml(cb.code)}</code></pre></div>`;
    html = html.replace(`<div class="code-block" data-id="${cb.id}"></div>`, div);
  });
  return html;
}

/* ---------- Rendering ---------- */
const ASSISTANT_AVATAR =
  `<div class="avatar"><img src="/static/logo.svg" alt="ai" /></div>`;

function addUserMsg(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap user";
  const inner = document.createElement("div");
  inner.className = "user-wrap-inner";
  const label = document.createElement("div");
  label.className = "you-label";
  label.innerHTML = `<span class="you-avatar">🙂</span> You`;
  const bubble = document.createElement("div");
  bubble.className = "user-bubble";
  bubble.textContent = text;
  const time = document.createElement("div");
  time.className = "time";
  time.textContent = nowTime();
  inner.appendChild(label);
  inner.appendChild(bubble);
  wrap.appendChild(inner);
  wrap.appendChild(time);

  // copy action for user message
  const actions = document.createElement("div");
  actions.className = "msg-actions user-actions";
  actions.dataset.full = text;
  actions.innerHTML = `<button class="act-btn" data-act="copy"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11z"/></svg> Copy</button>`;
  wrap.appendChild(actions);
  msgContainer.appendChild(wrap);
}

function addAssistantShell() {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap assistant";
  wrap.id = "live-assistant";
  const time = document.createElement("div");
  time.className = "time";
  time.textContent = nowTime();
  wrap.innerHTML =
    ASSISTANT_AVATAR +
    `<div class="msg-body"><div class="role-label">Spike</div>` +
    `<div class="msg-content stream-cursor"></div></div>`;
  wrap.appendChild(time);
  msgContainer.appendChild(wrap);
  return wrap;
}

function renderStored(role, text) {
  if (role === "user") {
    const wrap = document.createElement("div");
    wrap.className = "msg-wrap user";
    const inner = document.createElement("div");
    inner.className = "user-wrap-inner";
    const label = document.createElement("div");
    label.className = "you-label";
    label.innerHTML = `<span class="you-avatar">🙂</span> You`;
    const bubble = document.createElement("div");
    bubble.className = "user-bubble";
    bubble.textContent = text;
    const time = document.createElement("div");
    time.className = "time";
    time.textContent = nowTime();
    inner.appendChild(label);
    inner.appendChild(bubble);
    wrap.appendChild(inner);
    wrap.appendChild(time);
    const actions = document.createElement("div");
    actions.className = "msg-actions user-actions";
    actions.dataset.full = text;
    actions.innerHTML = `<button class="act-btn" data-act="copy"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11z"/></svg> Copy</button>`;
    wrap.appendChild(actions);
    msgContainer.appendChild(wrap);
  } else if (role === "assistant") {
    const wrap = document.createElement("div");
    wrap.className = "msg-wrap assistant";
    wrap.innerHTML =
      ASSISTANT_AVATAR +
      `<div class="msg-body"><div class="role-label">Spike</div>` +
      `<div class="msg-content">${renderMarkdown(text)}</div>` +
      `<div class="msg-actions">` +
        `<button class="act-btn" data-act="copy" title="Copy"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11z"/></svg> Copy</button>` +
        `<button class="act-btn" data-act="regenerate" title="Regenerate"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"/></svg></button>` +
        `<button class="act-btn" data-act="speak" title="Read aloud"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg></button>` +
      `</div></div>`;
    const time = document.createElement("div");
    time.className = "time";
    time.textContent = nowTime();
    wrap.appendChild(time);
    msgContainer.appendChild(wrap);
  }
}

/* ---------- Loading / typing ---------- */
const LOADING_PHRASES = [
  "Thinking…",
  "Reasoning…",
  "Crafting your answer…",
  "Synthesizing…",
  "Analyzing…",
];

function showTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap assistant";
  wrap.id = "typing";
  wrap.innerHTML =
    ASSISTANT_AVATAR +
    `<div class="msg-body"><div class="role-label">Spike</div>` +
    `<div class="typing-box"><div class="typing-dots"><span></span><span></span><span></span></div>` +
    `<span class="typing-label">Thinking…</span></div>` +
    `<button class="stop-btn" id="stop-btn" title="Stop generating"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg></button></div>`;
  msgContainer.appendChild(wrap);
  scrollBottom();
  let i = 0;
  const label = wrap.querySelector(".typing-label");
  wrap._t = setInterval(() => {
    i = (i + 1) % LOADING_PHRASES.length;
    if (label) label.textContent = LOADING_PHRASES[i];
  }, 1500);
  document.getElementById("stop-btn").addEventListener("click", stopGenerating);
  return wrap;
}

function removeTyping() {
  const el = document.getElementById("typing");
  if (el) { clearInterval(el._t); el.remove(); }
}

function stopGenerating() {
  if (activeController) {
    activeController.abort();
    activeController = null;
  }
  removeTyping();
  sendBtn.disabled = false;
  inputEl.disabled = false;
  toast("Generation stopped");
}

/* ---------- Sidebar ---------- */
function renderChatList() {
  chatListEl.innerHTML = "";
  chats.slice(0, 100).forEach((c) => {
    const item = document.createElement("div");
    item.className = "chat-item" + (c.id === activeId ? " active" : "");
    const name = document.createElement("span");
    name.className = "chat-name";
    name.textContent = c.title || "New chat";
    const del = document.createElement("button");
    del.className = "delete";
    del.innerHTML = "&#10005;";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(c.id);
    });
    item.appendChild(name);
    item.appendChild(del);
    item.addEventListener("click", () => {
      if (busy) return;
      activeId = c.id; save(); renderConversation();
      if (window.innerWidth <= 640) sidebar.classList.remove("open");
    });
    chatListEl.appendChild(item);
  });
}

function deleteChat(id) {
  chats = chats.filter((c) => c.id !== id);
  if (activeId === id) activeId = chats.length ? chats[0].id : null;
  save(); renderChatList(); renderConversation();
  toast("Chat deleted");
}

function updateChatTitle(chat, firstText) {
  const t = (firstText || "New chat").trim();
  if (!chat.title || chat.title === "New chat") {
    chat.title = t.length > 34 ? t.slice(0, 34) + "…" : t;
    save(); renderChatList();
  }
  chatTitle.textContent = chat.title;
}

/* ---------- Conversation ---------- */
function renderConversation() {
  const chat = getActive();
  msgContainer.querySelectorAll(".msg-wrap").forEach((m) => m.remove());
  chatTitle.textContent = chat ? (chat.title || "New chat") : "New chat";
  if (chat && chat.messages.length) {
    emptyState.style.display = "none";
    chat.messages.forEach((m) => renderStored(m.role, m.content));
  } else {
    emptyState.style.display = "flex";
  }
  renderChatList();
  scrollBottom();
}

function nowTime() {
  const d = new Date();
  let h = d.getHours(); const m = d.getMinutes();
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m < 10 ? "0" + m : m} ${ap}`;
}

/* ---------- Scroll ---------- */
function scrollBottom() {
  requestAnimationFrame(() => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
    updateFab();
  });
}
function updateFab() {
  const nearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;
  scrollFab.classList.toggle("show", !nearBottom);
}
messagesEl.addEventListener("scroll", updateFab);
scrollFab.addEventListener("click", () => { messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" }); });

/* ---------- Send / streaming ---------- */
function send(textOverride) {
  const text = (textOverride !== undefined ? textOverride : inputEl.value).trim();
  if (!text || busy) return;
  busy = true;

  ensureChat();
  const chat = getActive();
  emptyState.style.display = "none";
  lastUserMsg = text;

  chat.messages.push({ role: "user", content: text });
  addUserMsg(text);
  chatTitle.textContent = chat.title || "New chat";
  updateChatTitle(chat, text);

  showTyping();
  sendBtn.disabled = true;
  sendBtn.classList.add("busy");
  inputEl.value = "";
  autoResize();
  inputEl.disabled = true;

  const history = chat.messages.filter((m) => m.role !== "error");

  activeController = new AbortController();

  (async () => {
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          messages: history,
          model: currentModel(),
          conversationId: chat.backendId || null,
        }),
        signal: activeController.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Request failed");
      }

      const cid = res.headers.get("X-Conversation-Id");
      if (cid) {
        chat.backendId = cid;
        if (chat.title && chat.title !== "New chat") { /* keep */ }
        else { chat.id = "backend-" + cid; activeId = chat.id; }
        save();
      }

      removeTyping();
      const shell = addAssistantShell();
      const contentEl = shell.querySelector(".msg-content");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let full = "";
      let pending = false;
      let buffer = "";
      let stopped = false;

      const render = () => {
        pending = false;
        const html = renderMarkdown(full);
        if (contentEl.innerHTML !== html) contentEl.innerHTML = html;
        scrollBottom();
      };
      const scheduleRender = () => {
        if (pending) return;
        pending = true;
        requestAnimationFrame(render);
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let nl;
          while ((nl = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (!line) continue;
            let data;
            try { data = JSON.parse(line); } catch (e) { continue; }
            if (data.error) throw new Error(data.error);
            full += data.token || "";
          }
          scheduleRender();
        }
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim());
            if (data.error) throw new Error(data.error);
            full += data.token || "";
          } catch (e) {}
        }
      } catch (err) {
        if (err.name === "AbortError") stopped = true;
        else throw err;
      }

      contentEl.classList.remove("stream-cursor");
      if (stopped) {
        contentEl.innerHTML = renderMarkdown(full) + `<span class="stopped-note"> · stopped</span>`;
      } else {
        contentEl.innerHTML = renderMarkdown(full);
        chat.messages.push({ role: "assistant", content: full });
        addActions(shell, full);
        save();
        updateChatTitle(chat, full);
      }
      scrollBottom();
    } catch (err) {
      removeTyping();
      if (err.name === "AbortError") {
        sendBtn.disabled = false;
        sendBtn.classList.remove("busy");
        inputEl.disabled = false;
        inputEl.focus();
        return;
      }
      // Handle auth failure: clear the bad token and force re-login
      if (err.message && err.message.indexOf("Not authenticated") !== -1) {
        clearAuth();
        busy = false;
        sendBtn.disabled = false;
        sendBtn.classList.remove("busy");
        inputEl.disabled = false;
        showAuthScreen(true);
        setAuthMode("login");
        authError.textContent = "Your session expired. Please sign in again.";
        toast("Please sign in to continue");
        return;
      }
      const shell = addAssistantShell();
      const contentEl = shell.querySelector(".msg-content");
      contentEl.classList.remove("stream-cursor");
      contentEl.innerHTML = `<p style="color:#ef4444;font-weight:600">⚠️ ${escapeHtml(err.message)}</p>`;
      chat.messages.push({ role: "error", content: "Error: " + err.message });
      save();
    } finally {
      activeController = null;
      busy = false;
      sendBtn.disabled = false;
      sendBtn.classList.remove("busy");
      inputEl.disabled = false;
      inputEl.focus();
      scrollBottom();
    }
  })();
}

function addActions(shell, full) {
  const body = shell.querySelector(".msg-body");
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  actions.innerHTML =
    `<button class="act-btn" data-act="copy"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11z"/></svg> Copy</button>` +
    `<button class="act-btn" data-act="regenerate"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"/></svg> Regenerate</button>` +
    `<button class="act-btn" data-act="speak"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg> Speak</button>`;
  actions.dataset.full = full;
  body.appendChild(actions);
}

/* ---------- Regenerate ---------- */
function regenerate() {
  if (busy) return;
  const chat = getActive();
  if (!chat) return;
  // remove last user + assistant turn, then resend the user prompt
  if (chat.messages.length < 2) return;
  // find the last user message
  let lastUserIdx = -1;
  for (let i = chat.messages.length - 1; i >= 0; i--) {
    if (chat.messages[i].role === "user") { lastUserIdx = i; break; }
  }
  if (lastUserIdx === -1) return;
  const userText = chat.messages[lastUserIdx].content;
  chat.messages = chat.messages.slice(0, lastUserIdx + 1);
  save();
  renderConversation();
  send(userText);
}

/* ---------- Actions delegation ---------- */
function speakText(text) {
  if (!window.speechSynthesis) { toast("Speech not supported"); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[#*`_>\[\]]/g, " "));
  u.rate = 1; u.pitch = 1;
  window.speechSynthesis.speak(u);
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".copy-btn");
  if (btn) {
    const block = btn.closest(".code-block");
    if (block) {
      const text = block.querySelector("pre").textContent;
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast("Copied"));
      btn.textContent = "✓";
      setTimeout(() => (btn.textContent = "Copy"), 1200);
    }
    return;
  }
  const act = e.target.closest(".act-btn");
  if (!act) return;
  const actType = act.dataset.act;
  if (actType === "copy") {
    const actions = act.closest(".msg-actions");
    const full = actions.dataset.full;
    if (navigator.clipboard) navigator.clipboard.writeText(full).then(() => toast("Copied to clipboard"));
  } else if (actType === "regenerate") {
    regenerate();
  } else if (actType === "speak") {
    const actions = act.closest(".msg-actions");
    speakText(actions.dataset.full);
  }
});

/* ---------- Input ---------- */
function autoResize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
}
function newChat() {
  if (busy) return;
  const chat = { id: Date.now().toString(36), title: "New chat", messages: [] };
  chats.unshift(chat);
  activeId = chat.id;
  save(); renderConversation();
  inputEl.focus();
  if (window.innerWidth <= 640) sidebar.classList.remove("open");
}

/* ---------- Status ---------- */
function checkHealth() {
  fetch("/api/health")
    .then((r) => r.json())
    .then((d) => {
      statusEl.className = "status " + (d.status === "ok" ? "online" : "error");
      statusEl.textContent = d.status === "ok" ? "Online" : "API key missing";
    })
    .catch(() => {
      statusEl.className = "status error";
      statusEl.textContent = "Offline";
    });
}

/* ---------- Theme toggle ---------- */
const themeBtn = document.getElementById("theme-btn");
const themeIco = document.getElementById("theme-path");
const exportBtn = document.getElementById("export-btn");

const THEME_KEY = "theme";
function applyTheme(mode) {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  if (mode === "light") root.classList.add("light");
  else if (mode === "dark") root.classList.add("dark");
  // update icon
  if (themeIco) {
    if (mode === "dark") {
      themeIco.setAttribute("d", "M12 3a9 9 0 1 0 0 18zm0 2v14a7 7 0 0 1 0-14z");
    } else {
      themeIco.setAttribute("d", "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-14v2m0 14v2m7.07-12.93-1.41 1.41M6.34 17.66l-1.41 1.41m14.14-7.07-1.41-1.41M5.2 6.34 6.6 7.75M9 4a3 3 0 0 0 6 0z");
    }
  }
}
function nextTheme() {
  const root = document.documentElement;
  const cur = root.classList.contains("dark") ? "dark" : (root.classList.contains("light") ? "light" : "auto");
  const next = cur === "auto" ? "light" : cur === "light" ? "dark" : "light";
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
  const label = next === "auto" ? "System" : next === "light" ? "Light" : "Dark";
  toast("Theme: " + label);
}
themeBtn.addEventListener("click", nextTheme);

/* ---------- Export ---------- */
function exportText() {
  const chat = getActive();
  if (!chat || !chat.messages.length) { toast("Nothing to export"); return; }
  let out = "Spike - Chat Export\n" + (chat.title || "Chat") + "\n" + new Date().toLocaleString() + "\n" + "=".repeat(40) + "\n\n";
  chat.messages.forEach((m) => {
    const who = m.role === "user" ? "You" : "Spike";
    out += `[${who}]\n${m.content}\n\n`;
  });
  const blob = new Blob([out], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (chat.title || "chat").replace(/[^\w\- ]/g, "").trim() + ".txt";
  a.click();
  URL.revokeObjectURL(a.href);
  toast("Chat exported as .txt");
}

function exportPdf() {
  const chat = getActive();
  if (!chat || !chat.messages.length) { toast("Nothing to export"); return; }
  // Build a clean printable document
  const body = chat.messages.map((m) => {
    const who = m.role === "user" ? "You" : "Spike";
    const pre = m.content.replace(/```/g, "__CODE__");
    return `<div class="ex-msg ${m.role}"><p class="ex-who">${who}</p>` +
           `<p class="ex-text">${escapeHtml(pre).replace(/__CODE__/g, '```').replace(/\n/g, "<br>")}</p></div>`;
  }).join("");
  const win = window.open("", "_blank");
  if (!win) { toast("Popup blocked"); return; }
  win.document.write(`<!DOCTYPE html><html><head><title>${escapeHtml(chat.title || "Chat")}</title>
    <style>
      body{font-family:Georgia,serif;max-width:700px;margin:40px auto;padding:0 24px;color:#222;}
      h1{font-size:24px;border-bottom:1px solid #ddd;padding-bottom:12px;}
      .meta{color:#888;font-size:13px;margin-bottom:24px;}
      .ex-msg{margin:0 0 22px;}
      .ex-who{font-weight:bold;margin-bottom:6px;}
      .ex-who:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;}
      .ex-msg.user .ex-who:before{background:#6366f1;}
      .ex-msg.assistant .ex-who:before{background:#ec4899;}
      .ex-text{line-height:1.6;font-size:15px;white-space:pre-wrap;}
      code{background:#f4f4f4;padding:1px 4px;border-radius:3px;font-size:13px;}
      pre{background:#f6f6f6;padding:12px;border-radius:6px;overflow:auto;}
      @media print{body{max-width:none;}}
    </style></head><body>
    <h1>${escapeHtml(chat.title || "Chat")}</h1>
    <div class="meta">Spike &middot; ${new Date().toLocaleString()}</div>
    ${body}
    </body></html>`);
  win.document.close();
  setTimeout(() => { win.focus(); win.print(); }, 300);
  toast("Opening print — choose 'Save as PDF'");
}

exportBtn.addEventListener("click", () => {
  const chat = getActive();
  if (!chat || !chat.messages.length) { toast("Nothing to export"); return; }
  const choice = confirm("How do you want to export?  (OK = PDF via print · Cancel = .txt file)");
  if (choice) exportPdf();
  else exportText();
});

/* ---------- Mic / voice ---------- */
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let micActive = false;
if (SpeechRec) {
  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";
}
if (recognition) {
  recognition.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) inputEl.value += (inputEl.value ? " " : "") + t;
      else interim += t;
    }
    inputEl.setAttribute("placeholder", interim || "Message Spike…");
    autoResize();
  };
  recognition.onend = () => {
    micActive = false;
    micBtn.classList.remove("recording");
    inputEl.setAttribute("placeholder", "Message Spike…");
    if (inputEl.value.trim()) autoResize();
  };
  recognition.onerror = (e) => {
    micActive = false;
    micBtn.classList.remove("recording");
    toast("Mic: " + (e.error || "error"));
  };
  micBtn.addEventListener("click", () => {
    if (busy) return;
    if (micActive) { recognition.stop(); micActive = false; micBtn.classList.remove("recording"); return; }
    try {
      recognition.start();
      micActive = true;
      micBtn.classList.add("recording");
      inputEl.setAttribute("placeholder", "Listening… speak now");
    } catch (err) { toast("Mic not available"); }
  });
} else {
  micBtn.style.display = "none";
}

/* ---------- Events ---------- */
formEl.addEventListener("submit", (e) => { e.preventDefault(); send(); });
inputEl.addEventListener("input", autoResize);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
sendBtn.addEventListener("click", (e) => { e.preventDefault(); send(); });
inputEl.addEventListener("keyup", updateSendState);
inputEl.addEventListener("input", updateSendState);
function updateSendState() {
  sendBtn.classList.toggle("has-text", !!inputEl.value.trim());
}
newChatBtn.addEventListener("click", newChat);
if (addChatBtn) addChatBtn.addEventListener("click", newChat);
toggleSidebar.addEventListener("click", () => sidebar.classList.toggle("open"));
clearBtn.addEventListener("click", () => {
  if (busy) return;
  const c = getActive();
  if (c) c.messages = [];
  save(); renderConversation(); inputEl.focus();
});
document.querySelector(".suggestions").addEventListener("click", (e) => {
  const t = e.target.closest(".suggestion");
  if (t) send(t.textContent);
});

/* ---------- Auth handlers ---------- */
const logoutBtn = document.getElementById("logout-btn");
const logoutUser = document.getElementById("logout-user");

/* STATE separation: one of [loading, auth, chat] is visible at a time. */

function friendlyAuthError(err, fallback) {
  const m = (err && err.message) || fallback || "Something went wrong. Please try again.";
  if (/already exists/i.test(m)) return "An account with this email already exists. Try signing in.";
  if (/incorrect email or password/i.test(m)) return "Incorrect email or password. Please try again.";
  if (/not configured/i.test(m)) return "Google login isn't configured yet. Please use email.";
  if (/failed|bad gateway/i.test(m)) return "Google sign-in failed. Please try again or use email.";
  if (/missing authorization code/i.test(m)) return "Google sign-in was interrupted. Please try again.";
  if (/did not provide an email/i.test(m)) return "Google didn't share an email. Please use email sign-in.";
  return m;
}

function showAccount(u) {
  if (!u) return;
  if (logoutUser) logoutUser.textContent = u.name || "Account";
  if (accountName) accountName.textContent = u.name || "User";
  if (accountEmail) accountEmail.textContent = u.email || "";
  if (accountArea) accountArea.hidden = false;
}

authSwitchBtn.addEventListener("click", () => {
  setAuthMode(authMode === "login" ? "signup" : "login");
});

authGoogle.addEventListener("click", async () => {
  authError.textContent = "";
  authError.style.color = "";
  authGoogle.disabled = true;
  try {
    const res = await fetch("/api/auth/google");
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.url) throw new Error(data.detail || "Google login unavailable");
    window.location.href = data.url;
  } catch (err) {
    authError.textContent = friendlyAuthError(err, "Google login unavailable");
    authGoogle.disabled = false;
  }
});

authForgot.addEventListener("click", async () => {
  authError.textContent = "";
  authError.style.color = "";
  const email = authEmail.value.trim();
  if (!email) {
    authError.textContent = "Enter your email above, then click Forgot password.";
    return;
  }
  authForgot.disabled = true;
  try {
    const res = await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    authError.style.color = "#16a34a";
    authError.textContent = data.message || "If that email exists, a reset link was sent.";
  } catch (err) {
    authError.textContent = "Couldn't process that. Please try again.";
  } finally {
    authForgot.disabled = false;
    setTimeout(() => { authError.style.color = ""; }, 6000);
  }
});

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.textContent = "";
  authError.style.color = "";
  const email = authEmail.value.trim();
  const password = authPassword.value;
  if (!email || !password) { authError.textContent = "Please enter your email and password."; return; }
  if (authMode === "signup") {
    const name = authName.value.trim();
    if (!name) { authError.textContent = "Please enter your name."; return; }
    if (password.length < 8) { authError.textContent = "Password must be at least 8 characters."; return; }
    if (password !== authConfirm.value) { authError.textContent = "Passwords do not match."; return; }
    authSubmit.disabled = true;
    authSubmit.textContent = "Creating…";
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Registration failed");
      setAuth(data.access_token, data.user);
      afterLogin();
    } catch (err) {
      authError.textContent = friendlyAuthError(err, "Registration failed");
    } finally {
      authSubmit.disabled = false;
      authSubmit.textContent = "Create account";
    }
  } else {
    authSubmit.disabled = true;
    authSubmit.textContent = "Signing in…";
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Login failed");
      setAuth(data.access_token, data.user);
      afterLogin();
    } catch (err) {
      authError.textContent = friendlyAuthError(err, "Login failed");
    } finally {
      authSubmit.disabled = false;
      authSubmit.textContent = "Continue";
    }
  }
});

logoutBtn.addEventListener("click", () => {
  clearAuth();
  chats = [];
  activeId = null;
  save();
  renderChatList();
  renderConversation();
  if (accountArea) accountArea.hidden = true;
  if (logoutUser) logoutUser.textContent = "Sign in";
  showAuthScreen(true);
  setAuthMode("login");
  toast("Logged out");
});

function afterLogin() {
  const u = getAuthedUser();
  showAccount(u);
  showAuthScreen(false);
  loadBackendConversations();
  toast("Welcome, " + (u ? u.name : "back") + "!");
}

function loadBackendConversations() {
  const t = getToken();
  if (!t) return;
  fetch("/api/conversations", { headers: authHeaders() })
    .then((r) => r.json())
    .then((list) => {
      if (Array.isArray(list)) {
        chats = list.map((c) => ({
          id: "backend-" + c.id,
          backendId: c.id,
          title: c.title || "New chat",
          messages: [],
        }));
        activeId = chats.length ? chats[0].id : null;
        save(); renderChatList(); renderConversation();
      }
    })
    .catch(() => {});
}

/* ---------- Auth state helpers ---------- */
function tokenFromHash() {
  if (location.hash.includes("gtoken=")) {
    const m = location.hash.match(/gtoken=([^&]+)/);
    const t = m ? decodeURIComponent(m[1]) : null;
    history.replaceState(null, "", location.pathname + location.search);
    return t;
  }
  return null;
}

async function verifyAndEnter(token) {
  const res = await fetch("/api/auth/me", { headers: { Authorization: "Bearer " + token } });
  if (!res.ok) throw new Error("invalid");
  const user = await res.json();
  setAuth(token, user);
  showAccount(user);
  showLoading(false);
  showAuthScreen(false);
  loadBackendConversations();
  toast("Welcome, " + (user.name || "back") + "!");
}

/* ---------- Init (enforced login state machine) ---------- */
async function init() {
  applyTheme(localStorage.getItem(THEME_KEY) || "auto");
  renderConversation();
  checkHealth();
  setInterval(checkHealth, 30000);

  // Start in loading state: hide both chat and auth behind opaque overlay.
  showLoading(true);
  showAuthScreen(true);

  const hashToken = tokenFromHash();
  if (hashToken) {
    try { await verifyAndEnter(hashToken); return; }
    catch { clearAuth(); }
  }
  const t = getToken();
  const u = getAuthedUser();
  if (t && u) {
    try { await verifyAndEnter(t); return; }
    catch { clearAuth(); }
  }

  // Not authenticated -> STATE A: login only.
  showLoading(false);
  showAuthScreen(true);
  setAuthMode("login");
}
init();
