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
    let confidence = 1;
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      const t = res[0].transcript;
      if (res.isFinal) {
        finalText += (finalText ? " " : "") + t;
        if (typeof res[0].confidence === "number") confidence = Math.min(confidence, res[0].confidence);
      } else {
        interim += t;
      }
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
      // Ignore noise / the assistant echoing itself (very short or low-confidence captures).
      // This is what stops the feedback loop that was freezing the desktop tab.
      if (clean.length < 2 || (typeof confidence === "number" && confidence < 0.5)) {
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
init();
