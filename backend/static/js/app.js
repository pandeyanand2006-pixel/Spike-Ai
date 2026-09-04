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

/* ---------- Composer tools (image / ppt / attach) ---------- */
const plusBtn = document.getElementById("plus-btn");
const toolsPopover = document.getElementById("tools-popover");
const popAttach = document.getElementById("pop-attach");
const popImage = document.getElementById("pop-image");
const popPpt = document.getElementById("pop-ppt");
const imgInput = document.getElementById("img-input");
const TOOL_PREFIX = "__TOOL__::";
let attachedImage = null;   // base64 data URL of an uploaded image
let composerMode = "chat";  // "chat" | "image" | "ppt"
let isGuest = false;        // true when using the app without an account
const newChatBtn = document.getElementById("new-chat-btn");
const addChatBtn = document.getElementById("add-chat-btn");
const toggleSidebar = document.getElementById("toggle-sidebar");
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const chatTitle = document.getElementById("chat-title");
const toastEl = document.getElementById("toast");
const scrollFab = document.getElementById("scroll-fab");
const micBtn = document.getElementById("mic-btn");
const voiceAssistBtn = document.getElementById("voice-assist-btn");

/* ---------- Auth ---------- */
const authScreen = document.getElementById("auth-screen");
const authClose = document.getElementById("auth-close");
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
const authDivider = document.querySelector(".auth-divider");
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

function addUserMsg(text, image) {
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
  if (image) {
    const img = document.createElement("img");
    img.className = "user-img";
    img.src = image;
    img.alt = "attachment";
    bubble.appendChild(img);
  }
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

/* ---------- Tool result cards (image / ppt) ---------- */
function renderToolCard(tool) {
  const card = document.createElement("div");
  card.className = "tool-card" + (tool.type === "ppt" ? " ppt-card" : "");
  if (tool.type === "image") {
    const img = document.createElement("img");
    img.className = "tool-img";
    img.src = tool.url;
    img.alt = tool.prompt || "generated image";
    card.appendChild(img);
    const actions = document.createElement("div");
    actions.className = "tool-actions";
    actions.appendChild(makeDlBtn(tool.url, "⬇ Download image"));
    card.appendChild(actions);
  } else if (tool.type === "ppt") {
    const ico = document.createElement("div");
    ico.className = "ppt-icon";
    ico.textContent = "📊";
    const info = document.createElement("div");
    info.className = "ppt-info";
    const title = document.createElement("div");
    title.className = "ppt-title";
    title.textContent = tool.title || "Presentation";
    const sub = document.createElement("div");
    sub.className = "ppt-sub";
    sub.textContent = (tool.slides || 0) + " slides";
    info.appendChild(title);
    info.appendChild(sub);
    const actions = document.createElement("div");
    actions.className = "tool-actions";
    actions.appendChild(makeDlBtn(tool.pptx, "⬇ PPT"));
    if (tool.pdf) actions.appendChild(makeDlBtn(tool.pdf, "⬇ PDF"));
    card.appendChild(ico);
    card.appendChild(info);
    card.appendChild(actions);
  }
  return card;
}

function makeDlBtn(href, label) {
  const a = document.createElement("a");
  a.className = "dl-btn";
  a.href = href;
  a.textContent = label;
  a.setAttribute("download", "");
  a.target = "_blank";
  return a;
}

function addToolMessage(tool) {
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap assistant";
  const time = document.createElement("div");
  time.className = "time";
  time.textContent = nowTime();
  wrap.innerHTML =
    ASSISTANT_AVATAR +
    `<div class="msg-body"><div class="role-label">Spike</div><div class="msg-content"></div></div>`;
  wrap.querySelector(".msg-content").appendChild(renderToolCard(tool));
  wrap.appendChild(time);
  msgContainer.appendChild(wrap);
  scrollBottom();
  return wrap;
}

function renderStoredMessage(m) {
  const role = m.role;
  const text = m.content || "";
  if (role === "user") {
    addUserMsg(text, m.image || null);
    return;
  }
  if (role === "assistant" && text.startsWith(TOOL_PREFIX)) {
    try {
      const tool = JSON.parse(text.slice(TOOL_PREFIX.length));
      addToolMessage(tool);
      return;
    } catch (e) { /* fall through to normal render */ }
  }
  renderStored(role, text);
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
    `<button class="stop-btn" id="stop-btn" title="Tap to stop"><span class="stop-dots"><i></i><i></i><i></i></span><span class="stop-text">Stop</span></button></div>`;
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

    const actions = document.createElement("div");
    actions.className = "chat-item-actions";
    const ren = document.createElement("button");
    ren.className = "rename";
    ren.innerHTML = "&#9998;";
    ren.title = "Rename";
    ren.addEventListener("click", (e) => {
      e.stopPropagation();
      startRename(c, item, name);
    });
    const del = document.createElement("button");
    del.className = "delete";
    del.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14"/></svg>';
    del.title = "Delete";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(c.id);
    });
    actions.appendChild(ren);
    actions.appendChild(del);

    item.appendChild(name);
    item.appendChild(actions);
    item.addEventListener("click", () => {
      if (busy) return;
      activeId = c.id; save(); renderConversation();
      if (window.innerWidth <= 860) {
        sidebar.classList.remove("open");
        if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
      }
      loadFullConversation(c);
    });
    chatListEl.appendChild(item);
  });
}

function startRename(chat, item, nameEl) {
  if (item.querySelector(".rename-input")) return;
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = chat.title || "New chat";
  input.maxLength = 120;
  nameEl.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const commit = async () => {
    if (done) return;
    done = true;
    const v = input.value.trim();
    if (v && v !== chat.title) {
      chat.title = v;
      save();
      if (chat.backendId) {
        try {
          await fetch("/api/conversations/" + chat.backendId, {
            method: "PATCH",
            headers: authHeaders(),
            body: JSON.stringify({ title: v }),
          });
        } catch (e) { /* ignore */ }
      }
    }
    renderChatList();
    renderConversation();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { done = true; renderChatList(); }
  });
  input.addEventListener("blur", commit);
  input.addEventListener("click", (e) => e.stopPropagation());
}

function deleteChat(id) {
  const chat = chats.find((c) => c.id === id);
  chats = chats.filter((c) => c.id !== id);
  if (activeId === id) activeId = chats.length ? chats[0].id : null;
  save(); renderChatList(); renderConversation();
  if (chat && chat.backendId) {
    fetch("/api/conversations/" + chat.backendId, { method: "DELETE", headers: authHeaders() })
      .catch(() => {});
  }
  toast("Chat deleted");
}

async function loadFullConversation(chat) {
  if (!chat || !chat.backendId || chat.messages.length) return;
  try {
    const res = await fetch("/api/conversations/" + chat.backendId, { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    chat.messages = (data.messages || []).map((m) => ({ role: m.role, content: m.content }));
    save();
    if (chat.id === activeId) renderConversation();
  } catch (e) { /* ignore */ }
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
    chat.messages.forEach((m) => renderStoredMessage(m));
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
  addUserMsg(text, attachedImage);
  chatTitle.textContent = chat.title || "New chat";
  updateChatTitle(chat, text);

  showTyping();
  sendBtn.disabled = true;
  sendBtn.classList.add("busy");
  inputEl.value = "";
  autoResize();
  inputEl.disabled = true;

  // Build request payload with optional image attachment / tool mode
  const payload = {
    messages: chat.messages.filter((m) => m.role !== "error"),
    model: currentModel(),
    conversationId: chat.backendId || null,
  };
  if (attachedImage) payload.image = attachedImage;
  if (composerMode === "image" || composerMode === "ppt") payload.mode = composerMode;

  // Reset composer state for the next message
  clearComposerState();

  activeController = new AbortController();

  (async () => {
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
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
      let shell = null;
      let contentEl = null;
      let toolHandled = false;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let full = "";
      let pending = false;
      let buffer = "";
      let stopped = false;

      const render = () => {
        pending = false;
        const html = renderMarkdown(full);
        if (contentEl && contentEl.innerHTML !== html) contentEl.innerHTML = html;
        scrollBottom();
      };
      const scheduleRender = () => {
        if (pending || !contentEl) return;
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
            if (data.tool) {
              toolHandled = true;
              addToolMessage(data.tool);
              chat.messages.push({
                role: "assistant",
                content: TOOL_PREFIX + JSON.stringify(data.tool),
              });
              save();
              if (voiceMode) {
                voiceBusy = false;
                setOrbState("speaking");
                speakText("Here's what you asked for.", () => { if (voiceMode) resumeListening(); });
              }
              continue;
            }
            if (!shell) { shell = addAssistantShell(); contentEl = shell.querySelector(".msg-content"); }
            full += data.token || "";
            if (voiceMode) feedSpeech(data.token || "");
          }
          scheduleRender();
        }
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim());
            if (data.error) throw new Error(data.error);
            if (data.tool) {
              toolHandled = true;
              addToolMessage(data.tool);
              chat.messages.push({
                role: "assistant",
                content: TOOL_PREFIX + JSON.stringify(data.tool),
              });
              save();
            } else if (!shell) {
              shell = addAssistantShell(); contentEl = shell.querySelector(".msg-content");
              full += data.token || "";
            }
          } catch (e) {}
        }
      } catch (err) {
        if (err.name === "AbortError") stopped = true;
        else throw err;
      }

      if (shell && contentEl) {
        contentEl.classList.remove("stream-cursor");
        if (stopped) {
          contentEl.innerHTML = renderMarkdown(full) + `<span class="stopped-note"> · stopped</span>`;
        } else {
          contentEl.innerHTML = renderMarkdown(full);
          chat.messages.push({ role: "assistant", content: full });
          addActions(shell, full);
          save();
          updateChatTitle(chat, full);
          if (voiceMode) {
            if (speechBuffer.trim()) speakText(speechBuffer);
            speechBuffer = "";
          }
        }
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
let cachedVoices = [];
let ttsPlaying = false;
let speechQueue = [];
let speakingNow = false;
let speechBuffer = "";
let voiceSpeakTimer = null;
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
function pickFemaleVoice() {
  if (!cachedVoices.length && window.speechSynthesis) cachedVoices = window.speechSynthesis.getVoices() || [];
  if (!cachedVoices.length) return null;
  const prefer = cachedVoices.find((v) =>
    /female|samantha|zira|jenny|aria|google us english|tessa|victoria|karen|moira|anna|libby|natural|susan|hazel|emma|ruby|scarlett|allison|ava/i.test(v.name)
  );
  if (prefer) return prefer;
  const en = cachedVoices.find((v) => /^en(-|_)/i.test(v.lang));
  return en || cachedVoices[0];
}
function clearSpeech() {
  if (voiceSpeakTimer) { clearTimeout(voiceSpeakTimer); voiceSpeakTimer = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  speechQueue = []; speechBuffer = ""; speakingNow = false; ttsPlaying = false;
}
/* iOS can't reliably queue multiple utterances, so speak the whole reply at once.
   Other browsers stream sentence-by-sentence for a real-time, Gemini-Live feel. */
function speakText(text) {
  const t = (text || "").replace(/[#*`_>\[\]]/g, " ").trim();
  if (!t) return;
  if (isIOS) speakOnce(t);
  else enqueueSpeech(t);
}
function enqueueSpeech(text) {
  const t = (text || "").replace(/^[#*`_>\[\]\-]+/, "").replace(/[#*`_>\[\]]/g, " ").trim();
  if (!t) return;
  speechQueue.push(t);
  pumpSpeech();
}
function pumpSpeech() {
  if (speakingNow || !speechQueue.length) return;
  if (!window.speechSynthesis) { speechQueue = []; ttsPlaying = false; if (voiceMode) resumeListening(); return; }
  speakingNow = true; ttsPlaying = true;
  if (voiceMode) setOrbState("speaking");
  const text = speechQueue.shift();
  speakUtterance(text, () => {
    speakingNow = false;
    if (speechQueue.length) pumpSpeech();
    else { ttsPlaying = false; if (voiceMode) resumeListening(); }
  });
}
function speakOnce(text) {
  if (!window.speechSynthesis) { if (voiceMode) resumeListening(); return; }
  ttsPlaying = true;
  if (voiceMode) setOrbState("speaking");
  speakUtterance(text, () => { ttsPlaying = false; if (voiceMode) resumeListening(); });
}
function speakUtterance(text, onDone) {
  if (voiceSpeakTimer) { clearTimeout(voiceSpeakTimer); voiceSpeakTimer = null; }
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05; u.pitch = 1.05;
  const v = pickFemaleVoice();
  if (v) u.voice = v;
  u.onend = () => { if (voiceSpeakTimer) { clearTimeout(voiceSpeakTimer); voiceSpeakTimer = null; } if (onDone) onDone(); };
  u.onerror = () => { if (voiceSpeakTimer) { clearTimeout(voiceSpeakTimer); voiceSpeakTimer = null; } speakingNow = false; ttsPlaying = false; speechQueue = []; };
  try { window.speechSynthesis.speak(u); } catch (e) {}
  /* Safety net: some mobile browsers don't fire onend reliably, so force-advance. */
  const dur = Math.max(2000, text.length * 70);
  voiceSpeakTimer = setTimeout(() => {
    voiceSpeakTimer = null;
    try { window.speechSynthesis.cancel(); } catch (e) {}
    if (onDone) onDone();
  }, dur);
}
function feedSpeech(chunk) {
  speechBuffer += chunk || "";
  const boundaries = /[.!?\n]/g;
  let last = -1, m;
  while ((m = boundaries.exec(speechBuffer)) !== null) last = m.index;
  if (last >= 0) {
    const part = speechBuffer.slice(0, last + 1);
    speechBuffer = speechBuffer.slice(last + 1);
    part.split(/[.!?\n]/).forEach((s) => { const t = s.replace(/[#*`_>\[\]]/g, " ").trim(); if (t) enqueueSpeech(t); });
  }
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
  if (window.innerWidth <= 860) {
    sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
  }
}

/* ---------- Status ---------- */
function checkHealth() {
  fetch("/api/health")
    .then((r) => r.json())
    .then((d) => {
      statusEl.className = "status " + (d.status === "ok" ? "online" : "error");
      statusEl.textContent = "";
    })
    .catch(() => {
      statusEl.className = "status error";
      statusEl.textContent = "";
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
if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => { cachedVoices = window.speechSynthesis.getVoices() || []; };
  cachedVoices = window.speechSynthesis.getVoices() || [];
}
let listening = false;   // true while a recognition instance is actively recording
let listenTimer = null;  // debounced restart timer (prevents tight listen/speak flicker)

/* Re-arm listening after a short cooldown so the browser can clean up the previous
   instance (avoids the "listening -> speaking -> listening" flicker and frozen tabs). */
function scheduleListen() {
  if (!voiceMode || busy || voiceBusy) return;
  if (listenTimer) return;
  listenTimer = setTimeout(() => {
    listenTimer = null;
    startListening();
  }, 350);
}

function buildRecognition() {
  if (!SpeechRec) return null;
  const r = new SpeechRec();
  r.continuous = false;
  r.interimResults = true;
  r.lang = "en-US";
  r.onresult = (e) => {
    let interim = "";
    let finalText = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      const t = res[0].transcript;
      if (res.isFinal) finalText += (finalText ? " " : "") + t;
      else interim += t;
    }
    if (!voiceMode) {
      if (finalText) inputEl.value += (inputEl.value ? " " : "") + finalText;
      inputEl.setAttribute("placeholder", interim || "Message Spike…");
      autoResize();
      return;
    }
    if (interim && voiceOrbCaption) voiceOrbCaption.textContent = interim;
    if (finalText) {
      const clean = finalText.trim();
      // Ignore empty / punctuation-only captures (real speech is longer).
      if (clean.length < 2) {
        try { r.stop(); } catch (e2) {} // drop this capture; onend will re-arm
        return;
      }
      clearSpeech(); // barge-in: stop any current reply immediately
      voiceBusy = true;
      try { r.stop(); } catch (e2) {} // stop this instance so it can't double-capture
      setOrbState("thinking");
      stopViz(); startSpeakViz();
      send(clean);
    }
  };
  r.onend = () => {
    listening = false;
    if (!voiceMode) {
      micActive = false;
      micBtn.classList.remove("recording");
      inputEl.setAttribute("placeholder", "Message Spike…");
      if (inputEl.value.trim()) autoResize();
      return;
    }
    if (ttsPlaying || voiceBusy) return; // a later step will re-arm listening
    scheduleListen();
  };
  r.onerror = (e) => {
    listening = false;
    if (!voiceMode) {
      micActive = false;
      micBtn.classList.remove("recording");
      toast("Mic: " + (e.error || "error"));
    } else if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      toast("Microphone permission denied");
      closeVoiceMode();
    } else if (!voiceBusy) {
      scheduleListen(); // transient error (no-speech/network) -> re-arm after cooldown
    }
  };
  return r;
}
recognition = buildRecognition();
if (SpeechRec) {
  micBtn.addEventListener("click", () => {
    if (voiceMode) return; // the orb owns the mic in voice mode
    if (busy) return;
    if (micActive) { recognition.stop(); micActive = false; micBtn.classList.remove("recording"); return; }
    recognition = buildRecognition();
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

/* ---------- AI Voice Assistant (Gemini-style voice orb) ---------- */
const voiceOrb = document.getElementById("voice-orb");
const voiceOrbCircle = document.getElementById("voice-orb-circle");
const voiceOrbCore = document.getElementById("voice-orb-core");
const voiceOrbCaption = document.getElementById("voice-orb-caption");
const voiceOrbClose = document.getElementById("voice-orb-close");
const voiceOrbBackdrop = document.getElementById("voice-orb-backdrop");

let voiceMode = false;   // true while the voice orb is open
let voiceBusy = false;   // true while Spike is thinking/speaking

const hasWebSpeech = !!SpeechRec;  // false on iOS Safari -> use cloud STT
const isTouch = ("ontouchstart" in window) || (navigator.maxTouchPoints > 0);
// On touch devices using Web Speech, the mic is exclusive: don't grab it for the
// visualizer (that would block the recognizer). Desktop and cloud-STT devices are fine.
const micForViz = !hasWebSpeech || !isTouch;
let cloudRecorder = null, cloudChunks = [], cloudListenActive = false, cloudWatchRaf = null, cloudSilentSince = 0;

function setOrbState(state) {
  if (!voiceOrbCircle) return;
  voiceOrbCircle.classList.remove("listening", "thinking", "speaking");
  if (state === "listening" || state === "thinking") voiceOrbCircle.classList.add(state);
  else if (state === "speaking") voiceOrbCircle.classList.add("speaking");
  if (voiceOrbCaption) {
    voiceOrbCaption.textContent =
      state === "listening" ? "Listening…" :
      state === "thinking" ? "Spike is thinking…" :
      state === "speaking" ? "Spike is speaking…" : "Tap to talk";
  }
}

/* Mic amplitude visualizer (drives the orb core while you talk) */
let voiceMicStream = null, voiceAudioCtx = null, voiceAnalyser = null;
let voiceRafMic = null, voiceRafSpk = null;
function startMicViz() {
  if (!voiceAnalyser || !voiceOrbCore) return;
  const data = new Uint8Array(voiceAnalyser.frequencyBinCount);
  const tick = () => {
    voiceAnalyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / data.length);
    const scale = 1 + Math.min(1.4, rms * 5);
    voiceOrbCore.style.transform = "scale(" + scale.toFixed(3) + ")";
    voiceRafMic = requestAnimationFrame(tick);
  };
  tick();
}
function startSpeakViz() {
  if (!voiceOrbCore) return;
  let t = 0;
  const tick = () => {
    t += 0.18;
    const s = 1 + 0.55 * (0.5 + 0.5 * Math.sin(t));
    voiceOrbCore.style.transform = "scale(" + s.toFixed(3) + ")";
    voiceRafSpk = requestAnimationFrame(tick);
  };
  tick();
}
function stopViz() {
  if (voiceRafMic) cancelAnimationFrame(voiceRafMic);
  if (voiceRafSpk) cancelAnimationFrame(voiceRafSpk);
  voiceRafMic = voiceRafSpk = null;
  if (voiceOrbCore) voiceOrbCore.style.transform = "";
}

async function openVoiceMode() {
  if (!window.speechSynthesis && !hasWebSpeech && typeof MediaRecorder === "undefined") {
    toast("Voice not supported on this browser"); return;
  }
  voiceMode = true;
  if (voiceAssistBtn) voiceAssistBtn.classList.add("active");
  if (voiceOrb) voiceOrb.hidden = false;
  // Speak the greeting while we still have the user-gesture context (iOS needs this)
  stopViz(); startSpeakViz();
  setOrbState("speaking");
  speakText("Hey, I'm Spike. How can I help you?");
  // Create + resume the AudioContext INSIDE the tap gesture (iOS keeps it suspended otherwise,
  // which would make the amplitude analyser read silence and break cloud STT).
  try {
    voiceAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (voiceAudioCtx.state === "suspended") await voiceAudioCtx.resume();
  } catch (e) { voiceAudioCtx = null; }
  // Grab the mic ONLY when needed for the visualizer/cloud STT. On touch devices that
  // use Web Speech, capturing the mic here would block the recognizer, so we skip it.
  if (micForViz) {
    try {
      voiceMicStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (voiceAudioCtx) {
        const src = voiceAudioCtx.createMediaStreamSource(voiceMicStream);
        voiceAnalyser = voiceAudioCtx.createAnalyser();
        voiceAnalyser.fftSize = 256;
        src.connect(voiceAnalyser);
        if (voiceAudioCtx.state === "suspended") voiceAudioCtx.resume();
      }
    } catch (e) { voiceMicStream = null; voiceAnalyser = null; }
  }
  startMicViz();
  // Begin listening once the mic is ready (greeting may still be speaking)
  if (voiceMode && !ttsPlaying && !hasWebSpeech) startVoiceListening();
}
function closeVoiceMode() {
  voiceMode = false;
  voiceBusy = false;
  listening = false;
  if (listenTimer) { clearTimeout(listenTimer); listenTimer = null; }
  if (voiceAssistBtn) voiceAssistBtn.classList.remove("active");
  if (voiceOrb) voiceOrb.hidden = true;
  stopViz();
  if (recognition) { try { recognition.stop(); } catch (e) {} }
  stopCloudListening();
  clearSpeech();
  if (voiceMicStream) voiceMicStream.getTracks().forEach((t) => t.stop());
  if (voiceAudioCtx) { try { voiceAudioCtx.close(); } catch (e) {} }
  voiceMicStream = null; voiceAudioCtx = null; voiceAnalyser = null;
}
/* Unified entry point: Web Speech on Android/desktop, cloud STT on iOS */
function startVoiceListening() {
  if (hasWebSpeech) startListening();
  else startCloudListening();
}
function startListening() {
  if (!voiceMode || !SpeechRec || busy || voiceBusy) return;
  if (listening) return; // already recording (guard against double-start)
  if (recognition) { try { recognition.stop(); } catch (e) {} } // stop any lingering instance
  listening = true;
  recognition = buildRecognition(); // fresh instance avoids Android Web Speech degradation
  if (!recognition) { listening = false; return; }
  setOrbState("listening");
  stopViz(); startMicViz();
  try { recognition.start(); }
  catch (e) { listening = false; scheduleListen(); } // retry after cooldown
}
function resumeListening() {
  if (!voiceMode) return;
  voiceBusy = false;
  startVoiceListening();
}

/* ---- Cloud STT fallback (iOS Safari etc.) ---- */
function startCloudListening() {
  if (!voiceMode || !voiceMicStream || cloudListenActive) return;
  if (typeof MediaRecorder === "undefined") { toast("Recording not supported on this device"); return; }
  if (voiceAudioCtx && voiceAudioCtx.state === "suspended") voiceAudioCtx.resume();
  cloudListenActive = true;
  cloudChunks = [];
  try { cloudRecorder = new MediaRecorder(voiceMicStream); }
  catch (e) { cloudListenActive = false; toast("Recording not supported on this device"); return; }
  cloudRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size && !ttsPlaying && !speakingNow) cloudChunks.push(e.data);
  };
  cloudRecorder.onstop = () => { cloudListenActive = false; };
  try { cloudRecorder.start(250); } catch (e) { cloudListenActive = false; return; }
  setOrbState("listening");
  stopViz(); startMicViz();
  if (voiceAnalyser) startCloudWatch();
  else startCloudTimedCapture(); // fallback if amplitude analyser unavailable
}
/* If we can't read mic amplitude (e.g. audio context suspended), record a fixed window. */
function startCloudTimedCapture() {
  const dur = 4500;
  let elapsed = 0;
  const id = setInterval(() => {
    elapsed += 250;
    if (!cloudListenActive) { clearInterval(id); return; }
    if (elapsed >= dur) {
      clearInterval(id);
      const chunks = cloudChunks; cloudChunks = [];
      if (cloudRecorder && cloudRecorder.state !== "inactive") { try { cloudRecorder.stop(); } catch (e) {} }
      const blob = new Blob(chunks, { type: (cloudRecorder && cloudRecorder.mimeType) || "audio/webm" });
      if (blob.size > 800) processCloudAudio(blob);
      else startCloudListening();
    }
  }, 250);
}
function stopCloudListening() {
  cloudListenActive = false;
  if (cloudWatchRaf) cancelAnimationFrame(cloudWatchRaf);
  cloudWatchRaf = null;
  if (cloudRecorder && cloudRecorder.state !== "inactive") { try { cloudRecorder.stop(); } catch (e) {} }
  cloudRecorder = null;
}
function startCloudWatch() {
  if (!voiceAnalyser) return;
  const data = new Uint8Array(voiceAnalyser.frequencyBinCount);
  cloudSilentSince = 0;
  const tick = () => {
    if (!cloudListenActive) return;
    voiceAnalyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / data.length);
    const now = Date.now();
    if (ttsPlaying || speakingNow) {
      cloudSilentSince = 0; // assistant is talking; ignore audio
    } else if (rms < 0.02) {
      if (cloudSilentSince === 0) cloudSilentSince = now;
      else if (now - cloudSilentSince > 1200) {
        const chunks = cloudChunks; cloudChunks = [];
        cloudSilentSince = 0;
        if (chunks.length) {
          const blob = new Blob(chunks, { type: (cloudRecorder && cloudRecorder.mimeType) || "audio/webm" });
          if (blob.size > 800) { processCloudAudio(blob); return; }
        }
      }
    } else {
      cloudSilentSince = 0;
    }
    cloudWatchRaf = requestAnimationFrame(tick);
  };
  tick();
}
async function processCloudAudio(blob) {
  stopCloudListening(); // pause capture while we transcribe + answer
  setOrbState("thinking");
  stopViz(); startSpeakViz();
  try {
    const headers = { "Content-Type": blob.type || "audio/webm" };
    const tk = getToken();
    if (tk) headers["Authorization"] = "Bearer " + tk;
    const r = await fetch("/api/voice/transcribe", { method: "POST", body: blob, headers });
    const j = await r.json().catch(() => ({}));
    const text = (j.text || "").trim();
    if (text) { voiceBusy = true; send(text); }
    else { setOrbState("listening"); startCloudListening(); }
  } catch (e) {
    toast("Transcription failed");
    setOrbState("listening");
    startCloudListening();
  }
}

/* Tap the orb to stop the current reply and listen to the user immediately */
function bargeIn() {
  if (!voiceMode) return;
  clearSpeech();
  voiceBusy = false;
  ttsPlaying = false;
  if (recognition) { try { recognition.stop(); } catch (e) {} }
  listening = false;
  if (listenTimer) { clearTimeout(listenTimer); listenTimer = null; }
  setOrbState("listening");
  scheduleListen();
}

if (voiceAssistBtn) {
  voiceAssistBtn.addEventListener("click", () => {
    if (voiceMode) closeVoiceMode();
    else openVoiceMode();
  });
}
if (voiceOrbClose) voiceOrbClose.addEventListener("click", closeVoiceMode);
if (voiceOrbBackdrop) voiceOrbBackdrop.addEventListener("click", closeVoiceMode);
if (voiceOrbCircle) voiceOrbCircle.addEventListener("click", bargeIn);

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

/* ---------- Composer tools wiring (single + popover) ---------- */
function clearComposerState() {
  attachedImage = null;
  composerMode = "chat";
  plusBtn.classList.remove("active");
  closePopover();
}

function setMode(mode) {
  composerMode = mode;
  plusBtn.classList.toggle("active", mode !== "chat");
  inputEl.focus();
}

function openPopover() {
  toolsPopover.hidden = false;
  plusBtn.classList.add("active");
}
function closePopover() {
  toolsPopover.hidden = true;
  if (composerMode === "chat") plusBtn.classList.remove("active");
}

plusBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (toolsPopover.hidden) openPopover(); else closePopover();
});
document.addEventListener("click", (e) => {
  if (!toolsPopover.hidden && !toolsPopover.contains(e.target) && e.target !== plusBtn) {
    closePopover();
  }
});

popAttach.addEventListener("click", () => {
  closePopover();
  if (attachedImage) {
    // toggle off: clear the attached image
    attachedImage = null;
    setMode("chat");
  } else {
    imgInput.click();
  }
});
popImage.addEventListener("click", () => {
  closePopover();
  setMode(composerMode === "image" ? "chat" : "image");
});
popPpt.addEventListener("click", () => {
  closePopover();
  setMode(composerMode === "ppt" ? "chat" : "ppt");
});

imgInput.addEventListener("change", () => {
  const file = imgInput.files && imgInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    attachedImage = reader.result;
    setMode("chat"); // attached image = vision chat (not generation)
  };
  reader.readAsDataURL(file);
  imgInput.value = "";
});

newChatBtn.addEventListener("click", newChat);
if (addChatBtn) addChatBtn.addEventListener("click", newChat);
toggleSidebar.addEventListener("click", () => {
  if (window.innerWidth <= 860) {
    const willOpen = !sidebar.classList.contains("open");
    sidebar.classList.toggle("open", willOpen);
    if (sidebarBackdrop) sidebarBackdrop.classList.toggle("show", willOpen);
  } else {
    sidebar.classList.toggle("closed");
  }
});
if (sidebarBackdrop) {
  sidebarBackdrop.addEventListener("click", () => {
    sidebar.classList.remove("open");
    sidebarBackdrop.classList.remove("show");
  });
}
window.addEventListener("resize", () => {
  if (window.innerWidth > 860) {
    sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
  }
});
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
  if (accountArea) accountArea.hidden = false;
  isGuest = false;
  refreshAccountUI();
}

function refreshAccountUI() {
  const u = getAuthedUser();
  if (accountArea) accountArea.hidden = false;
  if (!isGuest && u) {
    if (accountName) accountName.textContent = u.name || "User";
    if (accountEmail) accountEmail.textContent = u.email || "";
    if (logoutUser) logoutUser.textContent = "Log out";
    if (logoutBtn) logoutBtn.title = "Log out";
  } else {
    if (accountName) accountName.textContent = "Guest";
    if (accountEmail) accountEmail.textContent = "Sign in to save chats";
    if (logoutUser) logoutUser.textContent = "Sign in";
    if (logoutBtn) logoutBtn.title = "Sign in to save your chats";
  }
}

authSwitchBtn.addEventListener("click", () => {
  setAuthMode(authMode === "login" ? "signup" : "login");
});

if (authClose) {
  authClose.addEventListener("click", () => showAuthScreen(false));
}

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
  if (isGuest) {
    showAuthScreen(true);
    setAuthMode("login");
    return;
  }
  clearAuth();
  chats = [];
  activeId = null;
  save();
  renderChatList();
  renderConversation();
  isGuest = true;
  refreshAccountUI();
  showAuthScreen(false);
  setAuthMode("login");
  toast("Logged out — continuing as a guest");
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
        const active = chats.find((x) => x.id === activeId);
        if (active) loadFullConversation(active);
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
  applyTheme(localStorage.getItem(THEME_KEY) || "light");
  renderConversation();
  checkHealth();
  setInterval(checkHealth, 30000);
  refreshAuthConfig();

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

  // Not authenticated -> enter as a GUEST (no login required).
  enterGuest();
}

function enterGuest() {
  isGuest = true;
  showLoading(false);
  refreshAccountUI();
  showAuthScreen(false);
  toast("You're using Spike as a guest — sign in anytime to save your chats.");
}

async function refreshAuthConfig() {
  try {
    const res = await fetch("/api/auth/status");
    const data = await res.json().catch(() => ({}));
    const showGoogle = !!(data && data.google);
    if (authGoogle) authGoogle.style.display = showGoogle ? "" : "none";
    if (authDivider) authDivider.style.display = showGoogle ? "" : "none";
    const showImage = !!(data && data.image);
    if (popImage) popImage.style.display = showImage ? "" : "none";
    const sgImage = document.getElementById("sg-image");
    if (sgImage) sgImage.style.display = showImage ? "" : "none";
  } catch (e) { /* leave defaults */ }
}

/* ============================================================
   Spike Agent — AI software engineer (Plan / Build)
   ============================================================ */
const agentBtn = document.getElementById("agent-btn");
const chatView = document.getElementById("chat-view");
const agentView = document.getElementById("agent-view");
const agentMessages = document.getElementById("agent-messages");
const agentEmpty = document.getElementById("agent-empty");
const agentForm = document.getElementById("agent-form");
const agentInput = document.getElementById("agent-input");
const agentSend = document.getElementById("agent-send");
const agentStatus = document.getElementById("agent-status");
const agentModeEl = document.getElementById("agent-mode");
const agentStopBtn = document.getElementById("agent-stop");
const agentList = document.getElementById("agent-list");
const agentSessionsWrap = document.getElementById("agent-sessions");

let agentMode = localStorage.getItem("spike_agent_mode") || "build";
let agentSessionId = localStorage.getItem("spike_agent_session") || null;
let agentBusy = false;
let agentController = null;

function setAgentMode(m) {
  agentMode = m === "plan" ? "plan" : "build";
  localStorage.setItem("spike_agent_mode", agentMode);
  if (agentModeEl) {
    agentModeEl.querySelectorAll(".agent-mode-btn").forEach((b) => {
      const on = b.dataset.mode === agentMode;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
}
function setAgentStatus(state) {
  if (!agentStatus) return;
  const dot = agentStatus.querySelector(".agent-dot");
  agentStatus.classList.remove("working", "error");
  if (state === "working") {
    agentStatus.classList.add("working");
    agentStatus.innerHTML = '<span class="agent-dot"></span> Working';
  } else if (state === "thinking") {
    agentStatus.classList.add("working");
    agentStatus.innerHTML = '<span class="agent-dot"></span> Thinking';
  } else if (state === "error") {
    agentStatus.classList.add("error");
    agentStatus.innerHTML = '<span class="agent-dot"></span> Error';
  } else if (state === "completed") {
    agentStatus.innerHTML = '<span class="agent-dot"></span> Completed';
  } else {
    agentStatus.innerHTML = '<span class="agent-dot"></span> Ready';
  }
}
function showChatView() {
  if (chatView) chatView.hidden = false;
  if (agentView) agentView.hidden = true;
  if (agentBtn) agentBtn.classList.remove("active");
  document.getElementById("chat-header")?.classList.remove("hidden");
  if (window.innerWidth <= 860) {
    sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
  }
}
function showAgentView() {
  if (chatView) chatView.hidden = true;
  if (agentView) agentView.hidden = false;
  if (agentBtn) agentBtn.classList.add("active");
  // deselect chat active state visually
  chatListEl.querySelectorAll(".chat-item.active").forEach((el) => el.classList.remove("active"));
  if (window.innerWidth <= 860) {
    sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
  }
  setTimeout(() => { if (agentInput) agentInput.focus(); }, 80);
  loadAgentSessions();
}

function scrollAgentBottom() {
  if (!agentMessages) return;
  requestAnimationFrame(() => { agentMessages.scrollTop = agentMessages.scrollHeight; });
}
function hideAgentEmpty() {
  if (agentEmpty) agentEmpty.style.display = "none";
}
function appendAgentBubble(role, html) {
  hideAgentEmpty();
  const wrap = document.createElement("div");
  wrap.className = "agent-msg " + role;
  const lbl = document.createElement("div");
  lbl.className = "agent-role";
  lbl.textContent = role === "user" ? "You" : "Spike Agent";
  const bubble = document.createElement("div");
  bubble.className = "agent-bubble";
  if (typeof html === "string" && html.startsWith("<")) bubble.innerHTML = html;
  else bubble.textContent = html;
  wrap.appendChild(lbl);
  wrap.appendChild(bubble);
  agentMessages.appendChild(wrap);
  scrollAgentBottom();
  return bubble;
}
function appendAgentTool(tool, input, status) {
  hideAgentEmpty();
  const wrap = document.createElement("div");
  wrap.className = "agent-tool";
  wrap.dataset.tool = tool;
  const head = document.createElement("div");
  head.className = "agent-tool-head";
  const name = document.createElement("span");
  name.className = "tool-name";
  const icons = { read_file:"📄", write_file:"✏️", edit_file:"🔧", delete_file:"🗑️", list_directory:"📁", search_files:"🔍", get_file_info:"ℹ️", inspect_project:"🧭", run_command:"💻" };
  name.textContent = (icons[tool]||"⚡")+" "+tool;
  const badge = document.createElement("span");
  badge.className = "tool-status " + (status||"running");
  badge.textContent = status==="ok" ? "✓ done" : status==="err" ? "✗ failed" : "… running";
  head.appendChild(name); head.appendChild(badge);
  const body = document.createElement("div");
  body.className = "agent-tool-body";
  body.textContent = JSON.stringify(input, null, 2);
  head.addEventListener("click", () => body.classList.toggle("collapsed"));
  wrap.appendChild(head); wrap.appendChild(body);
  agentMessages.appendChild(wrap);
  scrollAgentBottom();
  return { wrap, body, badge, head };
}
function appendAgentTerminal(cmd, output, success) {
  hideAgentEmpty();
  const wrap = document.createElement("div");
  wrap.className = "agent-tool";
  const head = document.createElement("div");
  head.className = "agent-tool-head";
  head.innerHTML = '<span class="tool-name">💻 run_command</span><span class="tool-status '+(success?"ok":"err")+'">'+(success?"✓ done":"✗ failed")+'</span>';
  const body = document.createElement("div");
  body.className = "terminal-block";
  body.textContent = "$ "+cmd+"\n"+(output||"(no output)");
  head.addEventListener("click", () => body.classList.toggle("collapsed"));
  wrap.appendChild(head); wrap.appendChild(body);
  agentMessages.appendChild(wrap);
  scrollAgentBottom();
}
function appendAgentApproval(tool, input, reason) {
  hideAgentEmpty();
  const wrap = document.createElement("div");
  wrap.className = "agent-approval";
  wrap.innerHTML = '<p><strong>⚠ Approval required</strong></p><p>'+escapeHtml(reason||"This action needs confirmation.")+'</p><p><code>'+escapeHtml(tool)+' '+escapeHtml(JSON.stringify(input))+'</code></p>';
  const actions = document.createElement("div");
  actions.className = "agent-approval-actions";
  const allow = document.createElement("button"); allow.className="approval-btn allow"; allow.textContent="Allow";
  const cancel = document.createElement("button"); cancel.className="approval-btn cancel"; cancel.textContent="Cancel";
  allow.addEventListener("click", () => { wrap.remove(); toast("Approved — retry the task or send 'allow'"); });
  cancel.addEventListener("click", () => { wrap.remove(); toast("Cancelled"); });
  actions.appendChild(allow); actions.appendChild(cancel);
  wrap.appendChild(actions);
  agentMessages.appendChild(wrap);
  scrollAgentBottom();
}
function appendAgentFileChange(path) {
  hideAgentEmpty();
  const el = document.createElement("div");
  el.className = "agent-file-change";
  el.textContent = "✓ "+ path + " updated";
  agentMessages.appendChild(el);
  scrollAgentBottom();
}

function agentAutoResize() {
  if (!agentInput) return;
  agentInput.style.height = "auto";
  agentInput.style.height = Math.min(agentInput.scrollHeight, 160) + "px";
}

async function loadAgentSessions() {
  if (!agentList) return;
  try {
    const pid = selectedProject ? selectedProject.id : null;
    const url = "/api/agent/sessions" + (pid ? "?projectId="+encodeURIComponent(pid) : "");
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) return;
    const items = await res.json();
    agentList.innerHTML = "";
    if (!items.length) {
      if (agentSessionsWrap) agentSessionsWrap.hidden = true;
      return;
    }
    if (agentSessionsWrap) agentSessionsWrap.hidden = false;
    items.slice(0, 20).forEach((s) => {
      const el = document.createElement("div");
      el.className = "chat-item" + (s.id === agentSessionId ? " active" : "");
      el.innerHTML = '<span class="chat-name">'+escapeHtml(s.title||"Agent Session")+'</span>';
      el.addEventListener("click", async () => {
        agentSessionId = s.id;
        localStorage.setItem("spike_agent_session", agentSessionId);
        showAgentView();
        // load full history
        try {
          const r = await fetch("/api/agent/sessions/"+s.id, { headers: authHeaders() });
          if (!r.ok) return;
          const d = await r.json();
          agentMessages.querySelectorAll(".agent-msg, .agent-tool, .agent-approval, .agent-file-change, .terminal-block").forEach((x)=>x.remove());
          if (agentEmpty) agentEmpty.style.display = "";
          (d.messages||[]).forEach((m)=>{
            if (m.role==="user") appendAgentBubble("user", escapeHtml(m.content));
            else if (m.role==="assistant") {
              const div=document.createElement("div"); div.className="agent-msg assistant";
              const lbl=document.createElement("div"); lbl.className="agent-role"; lbl.textContent="Spike Agent";
              const bub=document.createElement("div"); bub.className="agent-bubble";
              bub.innerHTML = renderMarkdown(m.content);
              div.appendChild(lbl); div.appendChild(bub); agentMessages.appendChild(div);
            }
          });
          (d.toolEvents||[]).forEach((ev)=>{
            if (ev.type==="tool_start") appendAgentTool(ev.tool, ev.input, "running");
          });
          hideAgentEmpty();
        } catch(e){}
      });
      agentList.appendChild(el);
    });
  } catch(e){}
}

async function sendAgent(text) {
  const msg = (text || agentInput.value || "").trim();
  if (!msg || agentBusy) return;
  agentBusy = true;
  if (agentSend) agentSend.disabled = true;
  if (agentStopBtn) agentStopBtn.hidden = false;
  setAgentStatus("working");
  appendAgentBubble("user", escapeHtml(msg));
  if (agentInput) { agentInput.value=""; agentAutoResize(); }

  agentController = new AbortController();
  const payload = { message: msg, mode: agentMode, sessionId: agentSessionId || undefined };
  const pendingTools = new Map(); // tool -> element

  try {
    const res = await fetch("/api/agent/stream", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
      signal: agentController.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>({detail:"Request failed"}));
      throw new Error(err.detail || "Agent request failed");
    }
    const sid = res.headers.get("X-Agent-Session-Id");
    if (sid) { agentSessionId = sid; localStorage.setItem("spike_agent_session", sid); }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalContent = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl+1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch(e){ continue; }
        if (ev.type === "session_started") {
          if (ev.sessionId) { agentSessionId = ev.sessionId; localStorage.setItem("spike_agent_session", ev.sessionId); }
          loadAgentSessions();
        } else if (ev.type === "thinking") {
          setAgentStatus("thinking");
        } else if (ev.type === "tool_start") {
          setAgentStatus("working");
          const el = appendAgentTool(ev.tool, ev.input, "running");
          pendingTools.set(ev.tool + JSON.stringify(ev.input), el);
        } else if (ev.type === "tool_result") {
          // update last matching tool
          const key = ev.tool + JSON.stringify(ev.input || {});
          let el = pendingTools.get(key);
          // fallback: find last running tool with same name
          if (!el) {
            const tools = agentMessages.querySelectorAll('.agent-tool');
            for (let i=tools.length-1;i>=0;i--) if (tools[i].dataset.tool===ev.tool) { el = { wrap: tools[i], body: tools[i].querySelector(".agent-tool-body"), badge: tools[i].querySelector(".tool-status") }; break; }
          }
          if (el && el.badge) {
            el.badge.textContent = ev.success ? "✓ done" : "✗ failed";
            el.badge.className = "tool-status " + (ev.success ? "ok" : "err");
          }
          if (el && el.body) {
            el.body.textContent = (ev.output || "").slice(0, 6000);
            el.body.classList.remove("collapsed");
          }
        } else if (ev.type === "command_started") {
          setAgentStatus("working");
        } else if (ev.type === "command_result") {
          appendAgentTerminal(ev.command || "", ev.output || "", !!ev.success);
        } else if (ev.type === "file_changed") {
          appendAgentFileChange(ev.path);
        } else if (ev.type === "approval_required") {
          appendAgentApproval(ev.tool, ev.input, ev.reason);
        } else if (ev.type === "completed") {
          finalContent = ev.content || "";
          const html = renderMarkdown(finalContent);
          appendAgentBubble("assistant", html);
          setAgentStatus("completed");
          setTimeout(()=>setAgentStatus("ready"), 1800);
        } else if (ev.type === "error") {
          appendAgentBubble("assistant", '<p style="color:#ef4444">⚠️ '+escapeHtml(ev.message||"Agent error")+'</p>');
          setAgentStatus("error");
        } else if (ev.type === "session_ended") {
          loadAgentSessions();
        }
      }
    }
    if (buffer.trim()) {
      try {
        const ev = JSON.parse(buffer.trim());
        if (ev.type==="completed" && ev.content) {
          appendAgentBubble("assistant", renderMarkdown(ev.content));
        }
      } catch(e){}
    }
  } catch (err) {
    if (err.name === "AbortError") {
      appendAgentBubble("assistant", '<p style="color:var(--muted)"><em>Stopped by user.</em></p>');
      setAgentStatus("ready");
    } else {
      appendAgentBubble("assistant", '<p style="color:#ef4444">⚠️ '+escapeHtml(err.message||"Agent failed")+'</p>');
      setAgentStatus("error");
    }
  } finally {
    agentBusy = false;
    if (agentSend) agentSend.disabled = false;
    if (agentStopBtn) agentStopBtn.hidden = true;
    agentController = null;
    if (agentStatus && agentStatus.textContent.includes("Thinking")) setAgentStatus("ready");
    scrollAgentBottom();
  }
}

// Wiring
if (agentBtn) agentBtn.addEventListener("click", showAgentView);
if (agentModeEl) agentModeEl.addEventListener("click", (e)=>{
  const b=e.target.closest(".agent-mode-btn");
  if (!b) return;
  setAgentMode(b.dataset.mode);
});
if (agentStopBtn) agentStopBtn.addEventListener("click", ()=>{
  if (agentController) agentController.abort();
});
if (agentForm) agentForm.addEventListener("submit", (e)=>{ e.preventDefault(); sendAgent(); });
if (agentInput) {
  agentInput.addEventListener("input", agentAutoResize);
  agentInput.addEventListener("keydown", (e)=>{
    if (e.key==="Enter" && !e.shiftKey) { e.preventDefault(); sendAgent(); }
  });
}
document.querySelectorAll(".agent-sg").forEach((b)=>{
  b.addEventListener("click", ()=> sendAgent(b.dataset.prompt));
});

/* ============================================================
   Projects / Workspace — real per-project isolation
   ============================================================ */
const addPopover = document.getElementById("add-popover");
const addProjectBtn = document.getElementById("add-project-btn");
const projectSelector = document.getElementById("project-selector");
const projectSelectorClose = document.getElementById("project-selector-close");
const projectSelectorBackdrop = document.getElementById("project-selector-backdrop");
const projectSearch = document.getElementById("project-search");
const projectListEl = document.getElementById("project-list");
const createProjectOpen = document.getElementById("create-project-open");
const createProjectModal = document.getElementById("create-project-modal");
const createProjectClose = document.getElementById("create-project-close");
const createProjectBackdrop = document.getElementById("create-project-backdrop");
const createProjectForm = document.getElementById("create-project-form");
const cpName = document.getElementById("cp-name");
const cpDesc = document.getElementById("cp-desc");
const templateGrid = document.getElementById("template-grid");
const projectBar = document.getElementById("project-bar");
const projectBarMain = document.getElementById("project-bar-main");
const projectBarName = document.getElementById("project-bar-name");
const projectBarStack = document.getElementById("project-bar-stack");
const projectChangeBtn = document.getElementById("project-change");
const explorerToggle = document.getElementById("explorer-toggle");
const fileExplorer = document.getElementById("file-explorer");
const explorerTree = document.getElementById("explorer-tree");
const explorerRefresh = document.getElementById("explorer-refresh");
const sidebarProject = document.getElementById("sidebar-project");
const sidebarProjectBtn = document.getElementById("sidebar-project-btn");
const sidebarProjectName = document.getElementById("sidebar-project-name");
const sidebarProjectStack = document.getElementById("sidebar-project-stack");

let selectedProject = null;
let selectedTemplate = "other";
let projectsCache = [];
function setAgentSessionId(sid) {
  if (!sid) return;
  agentSessionId = sid;
  localStorage.setItem("spike_agent_session", sid);
  if (selectedProject && selectedProject.id) {
    try { localStorage.setItem("spike_agent_session_" + selectedProject.id, sid); } catch(e) {}
  }
}
function getAgentSessionIdForProject(pid) {
  if (pid) {
    try { const v = localStorage.getItem("spike_agent_session_" + pid); if (v) return v; } catch(e) {}
  }
  return localStorage.getItem("spike_agent_session");
}

function getSelectedProjectId() { return localStorage.getItem("spike_project_id"); }
function setSelectedProjectId(id) { if (id) localStorage.setItem("spike_project_id", id); else localStorage.removeItem("spike_project_id"); }

function openProjectSelector() {
  if (projectSelector) projectSelector.hidden = false;
  if (projectSearch) { projectSearch.value = ""; projectSearch.focus(); }
  loadProjects();
}
function closeProjectSelector() { if (projectSelector) projectSelector.hidden = true; }
function openCreateModal() {
  closeProjectSelector();
  if (createProjectModal) createProjectModal.hidden = false;
  if (cpName) setTimeout(()=>cpName.focus(), 80);
}
function closeCreateModal() { if (createProjectModal) createProjectModal.hidden = true; }

async function loadProjects(search="") {
  if (!projectListEl) return;
  projectListEl.innerHTML = '<div style="padding:12px;color:var(--text-2);font-size:13px">Loading…</div>';
  try {
    const url = "/api/projects" + (search ? "?search="+encodeURIComponent(search) : "");
    const res = await fetch(url, { headers: authHeaders() });
    if (res.status === 401) {
      projectListEl.innerHTML = '<div style="padding:12px;color:var(--text-2);font-size:13px">Sign in to manage projects.</div>';
      return;
    }
    if (!res.ok) throw new Error("Failed to load");
    const items = await res.json();
    projectsCache = items;
    renderProjectList(items);
  } catch (e) {
    projectListEl.innerHTML = '<div style="padding:12px;color:#ef4444;font-size:13px">'+escapeHtml(e.message)+'</div>';
  }
}
function projectAvatarColor(name) {
  const colors = ["#4f46e5","#f59e0b","#06b6d4","#10b981","#ef4444","#8b5cf6","#ec4899","#6366f1","#14b8a6","#f97316"];
  let h=0; for(let i=0;i<name.length;i++) h=(h*31+name.charCodeAt(i))>>>0;
  return colors[h % colors.length];
}
function renderProjectList(items) {
  if (!projectListEl) return;
  if (!items.length) {
    projectListEl.innerHTML = '<div style="padding:12px;color:var(--text-2);font-size:13px">No projects yet. Create one to start.</div>';
    return;
  }
  projectListEl.innerHTML = "";
  items.forEach((p) => {
    const el = document.createElement("button");
    el.className = "project-item" + (selectedProject && selectedProject.id===p.id ? " active" : "");
    const initial = (p.name||"P").trim().charAt(0).toUpperCase();
    const bg = projectAvatarColor(p.name||"P");
    const time = p.lastOpenedAt ? new Date(p.lastOpenedAt).toLocaleDateString() : "";
    const isActive = selectedProject && selectedProject.id===p.id;
    el.innerHTML = '<span class="project-item-avatar" style="background:'+bg+'">'+escapeHtml(initial)+'</span><span class="project-item-info"><span class="project-item-name">'+escapeHtml(p.name)+'</span><span class="project-item-meta">'+escapeHtml(p.stack||p.template||"")+'</span></span><span class="project-item-time">'+escapeHtml(time)+'</span>'+(isActive ? '<span class="project-item-check">✓</span>' : '');
    el.addEventListener("click", ()=> selectProject(p));
    projectListEl.appendChild(el);
  });
}
async function selectProject(p) {
  selectedProject = p;
  setSelectedProjectId(p.id);
  updateProjectUI();
  closeProjectSelector();
  closeCreateModal();
  showAgentView();
  // Refresh explorer and agent sessions for this project
  await refreshExplorer();
  loadAgentSessions();
  toast("Project: "+p.name);
}
function updateProjectUI() {
  const name = selectedProject ? selectedProject.name : "Select a project";
  const stack = selectedProject ? (selectedProject.stack || selectedProject.template || "") : "Choose a workspace for Spike Agent";
  if (projectBarName) projectBarName.textContent = name;
  if (projectBarStack) projectBarStack.textContent = stack;
  if (sidebarProjectName) sidebarProjectName.textContent = name;
  if (sidebarProjectStack) sidebarProjectStack.textContent = stack;
  if (sidebarProject) sidebarProject.hidden = !selectedProject;
  if (projectBar) projectBar.hidden = false;
  if (explorerToggle) explorerToggle.hidden = !selectedProject;
  if (selectedProject) {
    agentEmpty.querySelector(".agent-empty-sub").textContent = 'Working in "'+selectedProject.name+'" — ask me to build, fix, analyze, or refactor.';
  }
}
async function fetchSelectedProject() {
  const pid = getSelectedProjectId();
  if (!pid) { updateProjectUI(); return; }
  try {
    const res = await fetch("/api/projects/"+pid, { headers: authHeaders() });
    if (!res.ok) throw new Error();
    const p = await res.json();
    selectedProject = p;
    updateProjectUI();
    await refreshExplorer();
    await restoreLastAgentSession();
  } catch (e) {
    // stale id
    setSelectedProjectId(null);
    selectedProject = null;
    updateProjectUI();
  }
}
async function restoreLastAgentSession() {
  // Try per-project session first, then global
  let sid = null;
  if (selectedProject) sid = localStorage.getItem("spike_agent_session_" + selectedProject.id);
  if (!sid) sid = localStorage.getItem("spike_agent_session");
  if (!sid || sid.startsWith("guest-")) return;
  try {
    const r = await fetch("/api/agent/sessions/" + sid, { headers: authHeaders() });
    if (!r.ok) return;
    const data = await r.json();
    // Only restore if it belongs to current project (or no project filter)
    if (selectedProject && data.projectId && data.projectId !== selectedProject.id) return;
    if (!data.messages || !data.messages.length) return;
    // Clear current and render
    agentMessages.querySelectorAll(".agent-msg, .agent-tool, .agent-approval, .agent-file-change, .terminal-block").forEach(el => el.remove());
    hideAgentEmpty();
    if (agentEmpty) agentEmpty.style.display = "none";
    data.messages.forEach(m => {
      if (m.role === "user") {
        appendAgentBubble("user", escapeHtml(m.content));
      } else if (m.role === "assistant") {
        const div = document.createElement("div");
        div.className = "agent-msg assistant";
        const lbl = document.createElement("div");
        lbl.className = "agent-role";
        lbl.textContent = "Spike Agent";
        const bub = document.createElement("div");
        bub.className = "agent-bubble";
        bub.innerHTML = renderMarkdown(m.content);
        div.appendChild(lbl);
        div.appendChild(bub);
        agentMessages.appendChild(div);
      }
    });
    // Render tool events as history (file changes etc.)
    (data.toolEvents || []).forEach(ev => {
      if (ev.type === "file_changed" && ev.path) appendAgentFileChange(ev.path);
    });
    scrollAgentBottom();
    // Also update todo to completed if session was completed
    if (data.status === "completed" && todoItems.length && todoItems.some(t=>t.status!=="done")) {
      completeAllTodos();
    }
  } catch (e) {}
}
async function refreshExplorer() {
  if (!selectedProject || !explorerTree) return;
  explorerTree.innerHTML = '<div style="padding:8px;color:var(--text-2);font-size:12px">Loading…</div>';
  try {
    const res = await fetch("/api/projects/"+selectedProject.id+"/tree", { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed");
    const data = await res.json();
    renderTree(data.tree || [], explorerTree, "");
  } catch (e) {
    explorerTree.innerHTML = '<div style="padding:8px;color:#ef4444;font-size:12px">'+escapeHtml(e.message)+'</div>';
  }
}
function renderTree(nodes, container, prefix) {
  if (!container) return;
  container.innerHTML = "";
  if (!nodes.length) { container.innerHTML = '<div style="padding:8px;color:var(--text-2);font-size:12px">Empty project</div>'; return; }
  function addNodes(list, parent) {
    list.forEach((n)=>{
      const row = document.createElement("div");
      row.className = "explorer-item " + n.type;
      row.textContent = (n.type==="dir" ? "📁 " : "📄 ") + n.name;
      row.title = n.path;
      if (n.type==="file") {
        row.addEventListener("click", async ()=>{
          try {
            const r = await fetch("/api/projects/"+selectedProject.id+"/file?path="+encodeURIComponent(n.path), { headers: authHeaders() });
            if (!r.ok) throw new Error("Failed");
            const d = await r.json();
            // Show file content as a tool card in agent messages
            hideAgentEmpty();
            const wrap = document.createElement("div");
            wrap.className = "agent-tool";
            wrap.innerHTML = '<div class="agent-tool-head"><span class="tool-name">📄 '+escapeHtml(n.path)+'</span><span class="tool-status ok">'+d.size+' bytes</span></div><div class="agent-tool-body">'+escapeHtml(d.content.slice(0,8000))+'</div>';
            agentMessages.appendChild(wrap);
            scrollAgentBottom();
          } catch(e){ toast(e.message); }
        });
      }
      parent.appendChild(row);
      if (n.children && n.children.length) {
        const sub = document.createElement("div");
        sub.style.paddingLeft = "14px";
        addNodes(n.children, sub);
        parent.appendChild(sub);
      }
    });
  }
  addNodes(nodes, container);
}

// --- Todo system (like the assistant's own todos) ---
let todoItems = [];
function initTodo(message) {
  const lower = (message||"").toLowerCase();
  let todos = [];
  if (lower.includes("tshirt") || lower.includes("chax") || lower.includes("t-shirt")) {
    todos = [
      {id:1, text:"Setup project structure (package.json, Vite, index.html)", status:"pending"},
      {id:2, text:"Design CHAX brand & styling", status:"pending"},
      {id:3, text:"Create homepage with hero & featured products", status:"pending"},
      {id:4, text:"Build product catalog & customizer", status:"pending"},
      {id:5, text:"Add cart, checkout & responsive polish", status:"pending"},
    ];
  } else if (lower.includes("website") || lower.includes("build")) {
    todos = [
      {id:1, text:"Analyze project & create plan", status:"pending"},
      {id:2, text:"Setup scaffold & dependencies", status:"pending"},
      {id:3, text:"Implement core pages / features", status:"pending"},
      {id:4, text:"Add styling & interactivity", status:"pending"},
      {id:5, text:"Test & validate build", status:"pending"},
    ];
  } else {
    todos = [
      {id:1, text:"Understand request & inspect project", status:"pending"},
      {id:2, text:"Implement changes", status:"pending"},
      {id:3, text:"Validate & report", status:"pending"},
    ];
  }
  todoItems = todos;
  // Mark first as active
  if (todoItems[0]) todoItems[0].status = "active";
  renderTodo();
  const el = document.getElementById("agent-todo");
  if (el) el.hidden = false;
}
function renderTodo() {
  const list = document.getElementById("todo-list");
  const prog = document.getElementById("todo-progress");
  if (!list) return;
  list.innerHTML = "";
  let done = 0;
  todoItems.forEach((t)=>{
    const div = document.createElement("div");
    div.className = "todo-item " + t.status;
    const icon = t.status==="done" ? "✓" : t.status==="active" ? "●" : "○";
    div.innerHTML = '<span class="todo-check">'+icon+'</span><span>'+escapeHtml(t.text)+'</span>';
    list.appendChild(div);
    if (t.status==="done") done++;
  });
  if (prog) prog.textContent = done + "/" + todoItems.length;
}
function updateTodoForFile(path) {
  if (!todoItems.length) return;
  // Mark active as done, next as active
  let activeIdx = todoItems.findIndex(t=>t.status==="active");
  if (activeIdx !== -1) {
    todoItems[activeIdx].status = "done";
    let nxt = todoItems.findIndex(t=>t.status==="pending");
    if (nxt !== -1) todoItems[nxt].status = "active";
  } else {
    let nxt = todoItems.findIndex(t=>t.status==="pending");
    if (nxt !== -1) todoItems[nxt].status = "active";
  }
  renderTodo();
}
function markTodoActive() {
  if (!todoItems.length) return;
  if (!todoItems.some(t=>t.status==="active")) {
    let nxt = todoItems.findIndex(t=>t.status==="pending");
    if (nxt !== -1) { todoItems[nxt].status = "active"; renderTodo(); }
  }
}
function completeAllTodos() {
  todoItems.forEach(t=> t.status="done");
  renderTodo();
  setTimeout(()=>{ const el=document.getElementById("agent-todo"); if(el) el.hidden=true; }, 2500);
}

// Patch sendAgent to include projectId and guard
const _origSendAgent = sendAgent;
sendAgent = async function(text) {
  const msg = (text || agentInput.value || "").trim();
  if (!msg) return;
  if (!selectedProject) {
    toast("Select a project first");
    openProjectSelector();
    return;
  }
  // delegate to original but with project context — we override fetch inside _orig
  // Instead call the original logic with projectId via closure: set a temp
  const prev = agentSessionId;
  // The original sendAgent reads selectedProject via closure if we patch its fetch?
  // We'll just call a wrapper that injects projectId
  // Re-implement quick: call original but intercept its payload creation
  // Easiest: directly implement here similar to original but with projectId
  if (agentBusy) return;
  agentBusy = true;
  if (agentSend) agentSend.disabled = true;
  if (agentStopBtn) agentStopBtn.hidden = false;
  setAgentStatus("working");
  appendAgentBubble("user", escapeHtml(msg));
  initTodo(msg);
  if (agentInput) { agentInput.value=""; agentAutoResize(); }
  agentController = new AbortController();
  const payload = { message: msg, mode: agentMode, sessionId: agentSessionId || undefined, projectId: selectedProject.id };
  const pendingTools = new Map();
  try {
    const res = await fetch("/api/agent/stream", { method:"POST", headers: authHeaders(), body: JSON.stringify(payload), signal: agentController.signal });
    if (!res.ok) { const err=await res.json().catch(()=>({detail:"Request failed"})); throw new Error(err.detail||"Agent request failed"); }
    const sid=res.headers.get("X-Agent-Session-Id");
    if (sid) { agentSessionId=sid; localStorage.setItem("spike_agent_session", sid); }
    const reader=res.body.getReader(); const decoder=new TextDecoder(); let buffer="";
    while(true){ const{value,done}=await reader.read(); if(done) break; buffer+=decoder.decode(value,{stream:true}); let nl; while((nl=buffer.indexOf("\n"))!==-1){ const line=buffer.slice(0,nl).trim(); buffer=buffer.slice(nl+1); if(!line) continue; let ev; try{ev=JSON.parse(line);}catch(e){continue;}
      if(ev.type==="session_started"){ if(ev.sessionId){agentSessionId=ev.sessionId; localStorage.setItem("spike_agent_session",ev.sessionId);} loadAgentSessions(); }
      else if(ev.type==="project_loaded"){ /* could show */ }
      else if(ev.type==="thinking"){ setAgentStatus("thinking"); }
      else if(ev.type==="tool_start"){ setAgentStatus("working"); const el=appendAgentTool(ev.tool, ev.input, "running"); pendingTools.set(ev.tool+JSON.stringify(ev.input), el); markTodoActive(); }
      else if(ev.type==="tool_result"){ const key=ev.tool+JSON.stringify(ev.input||{}); let el=pendingTools.get(key); if(!el){ const tools=agentMessages.querySelectorAll('.agent-tool'); for(let i=tools.length-1;i>=0;i--) if(tools[i].dataset.tool===ev.tool){ el={wrap:tools[i], body:tools[i].querySelector(".agent-tool-body"), badge:tools[i].querySelector(".tool-status")}; break; } } if(el&&el.badge){ el.badge.textContent=ev.success?"✓ done":"✗ failed"; el.badge.className="tool-status "+(ev.success?"ok":"err"); } if(el&&el.body){ el.body.textContent=(ev.output||"").slice(0,6000); el.body.classList.remove("collapsed"); } }
      else if(ev.type==="command_started"){ setAgentStatus("working"); }
      else if(ev.type==="command_result"){ appendAgentTerminal(ev.command||"", ev.output||"", !!ev.success); }
      else if(ev.type==="file_changed"){ appendAgentFileChange(ev.path); updateTodoForFile(ev.path); refreshExplorer(); }
      else if(ev.type==="approval_required"){ appendAgentApproval(ev.tool, ev.input, ev.reason); }
      else if(ev.type==="completed"){ completeAllTodos(); appendAgentBubble("assistant", renderMarkdown(ev.content||"")); setAgentStatus("completed"); setTimeout(()=>setAgentStatus("ready"),1800); }
      else if(ev.type==="error"){ appendAgentBubble("assistant", '<p style="color:#ef4444">⚠️ '+escapeHtml(ev.message||"Agent error")+'</p>'); setAgentStatus("error"); }
      else if(ev.type==="session_ended"){ loadAgentSessions(); }
    } }
    if(buffer.trim()){ try{ const ev=JSON.parse(buffer.trim()); if(ev.type==="completed"&&ev.content) appendAgentBubble("assistant", renderMarkdown(ev.content)); }catch(e){} }
  } catch(err){ if(err.name==="AbortError"){ appendAgentBubble("assistant", '<p style="color:var(--muted)"><em>Stopped by user.</em></p>'); setAgentStatus("ready"); } else { appendAgentBubble("assistant", '<p style="color:#ef4444">⚠️ '+escapeHtml(err.message||"Agent failed")+'</p>'); setAgentStatus("error"); } }
  finally{ agentBusy=false; if(agentSend) agentSend.disabled=false; if(agentStopBtn) agentStopBtn.hidden=true; agentController=null; if(agentStatus&&agentStatus.textContent.includes("Thinking")) setAgentStatus("ready"); scrollAgentBottom(); refreshExplorer(); }
};

// Wiring for + menu and modals
if (addChatBtn && addPopover) {
  // Override previous click that showed chat view — now show popover
  const old = addChatBtn.getAttribute("data-old-wired");
  if (!old) {
    // remove old listener that called showChatView — we added one earlier; replace by cloning
    const clone = addChatBtn.cloneNode(true);
    addChatBtn.parentNode.replaceChild(clone, addChatBtn);
    // reassign var
    const newAddBtn = document.getElementById("add-chat-btn");
    newAddBtn.addEventListener("click", (e)=>{
      e.stopPropagation();
      addPopover.hidden = !addPopover.hidden;
    });
    document.addEventListener("click", (e)=>{
      if (!addPopover.hidden && !addPopover.contains(e.target) && e.target!==newAddBtn) addPopover.hidden=true;
    });
    // keep reference for project wiring
    window._newAddBtn = newAddBtn;
  }
}
document.getElementById("add-project-btn")?.addEventListener("click", ()=>{ if(addPopover) addPopover.hidden=true; openProjectSelector(); });
if (projectSelectorClose) projectSelectorClose.addEventListener("click", closeProjectSelector);
if (projectSelectorBackdrop) projectSelectorBackdrop.addEventListener("click", closeProjectSelector);
if (projectSearch) projectSearch.addEventListener("input", ()=> loadProjects(projectSearch.value.trim()));
if (createProjectOpen) createProjectOpen.addEventListener("click", openCreateModal);
if (createProjectClose) createProjectClose.addEventListener("click", closeCreateModal);
if (createProjectBackdrop) createProjectBackdrop.addEventListener("click", closeCreateModal);
document.getElementById("create-cancel")?.addEventListener("click", closeCreateModal);
if (templateGrid) templateGrid.addEventListener("click", (e)=>{
  const b=e.target.closest(".template-btn");
  if(!b) return;
  templateGrid.querySelectorAll(".template-btn").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");
  selectedTemplate=b.dataset.template;
});
if (createProjectForm) createProjectForm.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const name=cpName.value.trim();
  if(!name) { toast("Project name required"); return; }
  const desc=cpDesc.value.trim();
  const btn=document.getElementById("create-submit");
  if(btn) btn.disabled=true;
  try {
    const res=await fetch("/api/projects", { method:"POST", headers: authHeaders(), body: JSON.stringify({ name, description: desc, template: selectedTemplate }) });
    if(res.status===401){ toast("Sign in to create projects"); showAuthScreen(true); return; }
    if(!res.ok){ const err=await res.json().catch(()=>({detail:"Failed"})); throw new Error(err.detail||"Create failed"); }
    const p=await res.json();
    closeCreateModal();
    await selectProject(p);
    loadProjects();
  } catch(err){ toast(err.message); }
  finally{ if(btn) btn.disabled=false; }
});
const importProjectBtn = document.getElementById("import-project-btn");
const projectZipInput = document.getElementById("project-zip-input");
if (importProjectBtn && projectZipInput) {
  importProjectBtn.addEventListener("click", ()=> projectZipInput.click());
  projectZipInput.addEventListener("change", async ()=>{
    const file = projectZipInput.files && projectZipInput.files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) { toast("Select a .zip file"); return; }
    const name = file.name.replace(/\.zip$/i, "").slice(0,80) || "Imported Project";
    try {
      toast("Creating project...");
      const res = await fetch("/api/projects", { method:"POST", headers: authHeaders(), body: JSON.stringify({ name, description:"Imported from "+file.name, template:"other" }) });
      if(res.status===401){ toast("Sign in required"); showAuthScreen(true); return; }
      if(!res.ok){ const err=await res.json().catch(()=>({detail:"Create failed"})); throw new Error(err.detail||"Create failed"); }
      const p = await res.json();
      toast("Uploading and extracting...");
      const fd = new FormData();
      fd.append("file", file, file.name);
      const hdr = {};
      const tok = getToken();
      if (tok) hdr["Authorization"]="Bearer "+tok;
      const up = await fetch("/api/projects/"+p.id+"/import", { method:"POST", headers: hdr, body: fd });
      if(!up.ok){ const err=await up.json().catch(()=>({detail:"Import failed"})); throw new Error(err.detail||"Import failed"); }
      closeProjectSelector();
      const fresh = await fetch("/api/projects/"+p.id, { headers: authHeaders() }).then(r=>r.json()).catch(()=>p);
      await selectProject(fresh);
      toast("Project imported: "+name);
    } catch(e){ toast(e.message); }
    finally{ projectZipInput.value=""; }
  });
}
if (projectBarMain) projectBarMain.addEventListener("click", openProjectSelector);
if (projectChangeBtn) projectChangeBtn.addEventListener("click", openProjectSelector);
if (sidebarProjectBtn) sidebarProjectBtn.addEventListener("click", openProjectSelector);
if (explorerToggle) explorerToggle.addEventListener("click", ()=>{
  if(fileExplorer) fileExplorer.hidden = !fileExplorer.hidden;
  if(!fileExplorer.hidden) refreshExplorer();
});
if (explorerRefresh) explorerRefresh.addEventListener("click", refreshExplorer);

// Init project on load (after auth)
const _origInitProjects = fetchSelectedProject;
// Hook into auth flow: after verifyAndEnter or guest, fetch project
const _origEnterGuest2 = enterGuest;
enterGuest = function(){ _origEnterGuest2.apply(this, arguments); fetchSelectedProject(); };
const _origVerify = verifyAndEnter;
verifyAndEnter = async function(t){ const r=await _origVerify.apply(this, arguments); await fetchSelectedProject(); return r; };
// Also patch showAgentView to refresh explorer
const _origShowAgentView = showAgentView;
showAgentView = function(){ _origShowAgentView.apply(this, arguments); if(selectedProject) refreshExplorer(); };

// Make New Chat and chat list return to chat view
const origNewChat = newChat;
// Patch renderChatList click to show chat view
const _renderChatList = renderChatList;
renderChatList = function() {
  const r=_renderChatList.apply(this, arguments);
  // ensure agent button not active when chat view
  // (active state managed by showChatView/showAgentView)
  return r;
};
// Override chat item click to show chat view (via capturing after render)
const _oldRenderChatList = renderChatList;
// We monkey-patch after each render: chat items already switch active; also ensure view
// Do it via event delegation on chatListEl
if (chatListEl) chatListEl.addEventListener("click", (e)=>{
  if (e.target.closest(".chat-item")) showChatView();
});

setAgentMode(agentMode);
init();
