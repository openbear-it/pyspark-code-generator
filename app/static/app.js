const state = { chatId: null };
const chatList = document.querySelector("#chat-list");
const messages = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const form = document.querySelector("#prompt-form");
const files = document.querySelector("#files");
const contextPanel = document.querySelector("#context-panel");
const contextToggle = document.querySelector("#context-toggle");
const contextForm = document.querySelector("#context-form");

const escapeHtml = (text) => text.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const renderMarkdown = (text) => {
  if (window.marked && window.DOMPurify) return window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true, breaks: true }));
  return escapeHtml(text).replace(/\n/g, "<br>");
};
const renderMessageContent = (message) => message.role === "assistant" ? renderMarkdown(message.content) : escapeHtml(message.content);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || "Request failed"); }
  return response.json();
}

function renderMessages(chat) {
  chatTitle.textContent = chat.title;
  messages.innerHTML = chat.messages.length ? chat.messages.map((message) => `
    <article class="message ${message.role}">
      <div class="message-label">${message.role === "assistant" ? "PySpark assistant" : "You"}</div>
      ${message.attachments.map((name) => `<span class="attachment">${escapeHtml(name)}</span>`).join("")}
      <div class="message-content ${message.role === "assistant" ? "markdown-content" : ""}">${renderMessageContent(message)}</div>
    </article>`).join("") : `<div class="empty-state"><span class="spark-mark">*</span><h2>Build the Spark job</h2><p>Describe a transformation, upload a file, or paste code to inspect.</p></div>`;
  messages.scrollTop = messages.scrollHeight;
}

function renderContext(context) {
  contextForm.elements.relevant_code.value = context.relevant_code;
  contextForm.elements.programming_language.value = context.programming_language;
  contextForm.elements.requirements.value = context.requirements;
  contextForm.elements.libraries.value = context.libraries;
}

async function loadChat(chatId) { state.chatId = chatId; const chat = await api(`/api/chats/${chatId}`); renderMessages(chat); renderContext(chat.context); await refreshChats(); }
async function refreshChats() {
  const chats = await api("/api/chats");
  chatList.innerHTML = chats.map((chat) => `<button class="chat-link ${chat.id === state.chatId ? "active" : ""}" data-id="${chat.id}">${escapeHtml(chat.title)}</button>`).join("");
  chatList.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => loadChat(button.dataset.id)));
}
async function createChat() { const chat = await api("/api/chats", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await loadChat(chat.id); }

document.querySelector("#new-chat").addEventListener("click", createChat);
contextToggle.addEventListener("click", () => { contextPanel.hidden = !contextPanel.hidden; contextToggle.setAttribute("aria-expanded", String(!contextPanel.hidden)); });
contextForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.chatId) return;
  const button = contextForm.querySelector("button"); button.disabled = true;
  try {
    const context = Object.fromEntries(new FormData(contextForm));
    await api(`/api/chats/${state.chatId}/context`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(context) });
  } catch (error) { alert(error.message); } finally { button.disabled = false; }
});
files.addEventListener("change", () => { document.querySelector("#file-count").textContent = files.files.length ? `${files.files.length} selected` : ""; });
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.chatId) await createChat();
  const button = document.querySelector("#send"); button.disabled = true;
  const body = new FormData(); body.append("prompt", document.querySelector("#prompt").value); body.append("operation", document.querySelector("#operation").value);
  [...files.files].forEach((file) => body.append("files", file));
  try { await api(`/api/chats/${state.chatId}/messages`, { method: "POST", body }); form.reset(); document.querySelector("#file-count").textContent = ""; await loadChat(state.chatId); }
  catch (error) { alert(error.message); } finally { button.disabled = false; }
});

(async () => { await refreshChats(); const first = chatList.querySelector("button"); if (first) await loadChat(first.dataset.id); else await createChat(); })().catch((error) => alert(error.message));