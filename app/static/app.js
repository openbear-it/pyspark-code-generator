const state = { chatId: null, context: null, selection: "" };
const chatList = document.querySelector("#chat-list");
const messages = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const form = document.querySelector("#prompt-form");
const files = document.querySelector("#files");
const contextFileInput = document.querySelector("#context-files");
const contextFilesList = document.querySelector("#context-files-list");
const sourceAnalysis = document.querySelector("#source-analysis");
const codeEditor = document.querySelector("#code-editor");
const suggestionPanel = document.querySelector("#code-suggestion");
const suggestionCode = document.querySelector("#suggestion-code");
const suggestionStatus = document.querySelector("#suggestion-status");
const acceptSuggestionButton = document.querySelector("#accept-suggestion");
const lineNumbers = document.querySelector("#line-numbers");
const selectionStatus = document.querySelector("#selection-status");
const selectionButton = document.querySelector("#use-selection");
const contextChip = document.querySelector("#context-chip");
const contextChipText = document.querySelector("#context-chip-text");
const activeContext = document.querySelector("#active-context");
let suggestionTimer;
let suggestionController;
let suggestion = "";
let suggestionSource = "";
let suggestionCursor = 0;

const escapeHtml = (text) => text.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const renderMarkdown = (text) => window.marked && window.DOMPurify
  ? window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true, breaks: true }))
  : escapeHtml(text).replace(/\n/g, "<br>");
const renderMessageContent = (message) => message.role === "assistant" ? renderMarkdown(message.content) : escapeHtml(message.content);
const renderIcons = () => window.lucide?.createIcons();
const isNearMessageBottom = () => messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;

function clearSuggestion() {
  suggestion = "";
  suggestionPanel.hidden = true;
  acceptSuggestionButton.disabled = true;
}

async function requestSuggestion() {
  if (!state.chatId || !codeEditor.value.trim()) return;
  const source = codeEditor.value;
  const cursor = codeEditor.selectionStart;
  suggestionController?.abort();
  suggestionController = new AbortController();
  suggestionPanel.hidden = false;
  suggestionStatus.textContent = "Sto pensando...";
  suggestionCode.textContent = "";
  acceptSuggestionButton.disabled = true;
  try {
    const response = await api(`/api/chats/${state.chatId}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: source, cursor }),
      signal: suggestionController.signal,
    });
    if (source !== codeEditor.value || cursor !== codeEditor.selectionStart) return;
    suggestion = response.code.trim();
    if (!suggestion) { clearSuggestion(); return; }
    suggestionSource = source;
    suggestionCursor = cursor;
    suggestionCode.textContent = suggestion;
    suggestionStatus.textContent = "Pronto";
    acceptSuggestionButton.disabled = false;
  } catch (error) {
    if (error.name !== "AbortError") clearSuggestion();
  }
}

function scheduleSuggestion() {
  window.clearTimeout(suggestionTimer);
  suggestionController?.abort();
  clearSuggestion();
  if (codeEditor.value.trim().length < 8) return;
  suggestionTimer = window.setTimeout(requestSuggestion, 900);
}

function acceptSuggestion() {
  if (!suggestion || codeEditor.value !== suggestionSource) { clearSuggestion(); return; }
  codeEditor.setRangeText(suggestion, suggestionCursor, suggestionCursor, "end");
  codeEditor.dispatchEvent(new Event("input"));
  codeEditor.focus();
}

async function copyCode(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const temporaryInput = document.createElement("textarea");
    temporaryInput.value = text;
    temporaryInput.style.position = "fixed";
    document.body.append(temporaryInput);
    temporaryInput.select();
    document.execCommand("copy");
    temporaryInput.remove();
  }
}

function addCodeActions(container) {
  container.querySelectorAll("pre").forEach((codeBlock) => {
    if (codeBlock.parentElement.classList.contains("code-block")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "code-block";
    const actions = document.createElement("div");
    actions.className = "code-actions";
    actions.innerHTML = `<button type="button" data-code-action="copy" title="Copia codice"><i data-lucide="copy"></i><span>Copia</span></button><button type="button" data-code-action="insert" title="Inserisci nell'editor"><i data-lucide="corner-down-left"></i><span>Inserisci</span></button>`;
    codeBlock.before(wrapper);
    wrapper.append(actions, codeBlock);
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || "Richiesta non riuscita"); }
  return response.json();
}

async function streamResponse(path, body, onStart, onChunk) {
  const response = await fetch(path, { method: "POST", body });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || "Richiesta non riuscita"); }
  if (!response.body) throw new Error("Il browser non supporta lo streaming");
  await onStart();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value, { stream: true }));
  }
  const remaining = decoder.decode();
  if (remaining) onChunk(remaining);
}

function renderMessages(chat) {
  chatTitle.textContent = chat.title;
  messages.innerHTML = chat.messages.length ? chat.messages.map((message) => `
    <article class="message ${message.role}">
      <div class="message-label">${message.role === "assistant" ? "PySpark assistant" : "Tu"}</div>
      ${message.attachments.map((name) => `<span class="attachment">${escapeHtml(name)}</span>`).join("")}
      <div class="message-content ${message.role === "assistant" ? "markdown-content" : ""}">${renderMessageContent(message)}</div>
    </article>`).join("") : `<div class="empty-state"><i data-lucide="messages-square"></i><h2>Inizia dal codice</h2><p>Seleziona una parte dell'editor per usarla come contesto, poi poni una domanda.</p></div>`;
  addCodeActions(messages);
  messages.scrollTop = messages.scrollHeight;
  renderIcons();
}

function addStreamingMessage() {
  messages.insertAdjacentHTML("beforeend", `<article class="message assistant"><div class="message-label">PySpark assistant <span class="streaming-dot"></span></div><div class="message-content markdown-content"></div></article>`);
  return messages.lastElementChild.querySelector(".message-content");
}

function renderLineNumbers() {
  const lines = Math.max(1, codeEditor.value.split("\n").length);
  lineNumbers.textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
}

function updateCaret() {
  const beforeCaret = codeEditor.value.slice(0, codeEditor.selectionStart);
  const line = beforeCaret.split("\n").length;
  const column = beforeCaret.length - beforeCaret.lastIndexOf("\n");
  document.querySelector("#editor-position").textContent = `Ln ${line}, Col ${column}`;
}

function selectionSummary(text) {
  const lineCount = text.split("\n").length;
  return `${lineCount} ${lineCount === 1 ? "riga" : "righe"} selezionate`;
}

function updateSelection() {
  state.selection = codeEditor.value.slice(codeEditor.selectionStart, codeEditor.selectionEnd);
  const hasSelection = Boolean(state.selection.trim());
  selectionButton.disabled = !hasSelection;
  selectionStatus.textContent = hasSelection ? `${selectionSummary(state.selection)} · ${state.selection.length} caratteri` : "Nessuna selezione";
  updateCaret();
}

function renderContext(context) {
  state.context = context;
  codeEditor.value = context.relevant_code;
  state.selection = "";
  clearSuggestion();
  renderLineNumbers();
  updateSelection();
  const hasContext = Boolean(context.selected_code);
  contextChip.hidden = !hasContext;
  activeContext.hidden = !hasContext;
  if (hasContext) contextChipText.textContent = `${selectionSummary(context.selected_code)} nel contesto`;
  contextFilesList.innerHTML = context.files.map((file) => `<span class="context-file" title="${escapeHtml(file.name)}"><i data-lucide="file-text"></i><span>${escapeHtml(file.name)}</span><button class="icon-button" type="button" data-file="${escapeHtml(file.name)}" title="Rimuovi ${escapeHtml(file.name)}"><i data-lucide="x"></i></button></span>`).join("");
  const analyzedFiles = context.files.filter((file) => file.analysis);
  sourceAnalysis.hidden = !analyzedFiles.length;
  sourceAnalysis.innerHTML = analyzedFiles.map((file) => `<article class="source-card"><div><i data-lucide="table-properties"></i><strong>${escapeHtml(file.name)}</strong></div><p>${escapeHtml(file.analysis)}</p></article>`).join("");
  renderIcons();
}

async function persistContext(changes) {
  state.context = await api(`/api/chats/${state.chatId}/context`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...state.context, ...changes }),
  });
  renderContext(state.context);
}

async function loadChat(chatId) {
  state.chatId = chatId;
  const chat = await api(`/api/chats/${chatId}`);
  renderMessages(chat);
  renderContext(chat.context);
  await refreshChats();
}

async function refreshChats() {
  const chats = await api("/api/chats");
  chatList.innerHTML = chats.map((chat) => `<button class="chat-link nav-link ${chat.id === state.chatId ? "active" : ""}" data-id="${chat.id}"><i data-lucide="message-square"></i><span>${escapeHtml(chat.title)}</span></button>`).join("");
  chatList.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => loadChat(button.dataset.id)));
  renderIcons();
}

async function createChat() {
  const chat = await api("/api/chats", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await loadChat(chat.id);
}

document.querySelector("#new-chat").addEventListener("click", createChat);
document.querySelector("#refresh-chats").addEventListener("click", refreshChats);
document.querySelector("#dismiss-suggestion").addEventListener("click", clearSuggestion);
acceptSuggestionButton.addEventListener("click", acceptSuggestion);
messages.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-code-action]");
  if (!button) return;
  const code = button.closest(".code-block").querySelector("code").textContent;
  if (button.dataset.codeAction === "copy") {
    await copyCode(code);
    const label = button.querySelector("span");
    label.textContent = "Copiato";
    window.setTimeout(() => { label.textContent = "Copia"; }, 1600);
    return;
  }
  const start = codeEditor.selectionStart;
  const end = codeEditor.selectionEnd;
  const separator = start === end && start === codeEditor.value.length && codeEditor.value ? "\n" : "";
  codeEditor.setRangeText(`${separator}${code}`, start, end, "end");
  codeEditor.dispatchEvent(new Event("input"));
  codeEditor.focus();
});
document.querySelector("#save-code").addEventListener("click", async () => {
  if (!state.chatId) return;
  try { await persistContext({ relevant_code: codeEditor.value }); } catch (error) { alert(error.message); }
});
selectionButton.addEventListener("click", async () => {
  if (!state.selection.trim()) return;
  selectionButton.disabled = true;
  try { await persistContext({ relevant_code: codeEditor.value, selected_code: state.selection }); document.querySelector("#prompt").focus(); }
  catch (error) { alert(error.message); } finally { updateSelection(); }
});
document.querySelector("#clear-context").addEventListener("click", async () => {
  try { await persistContext({ relevant_code: codeEditor.value, selected_code: "" }); }
  catch (error) { alert(error.message); }
});
contextFileInput.addEventListener("change", async () => {
  if (!contextFileInput.files.length || !state.chatId) return;
  const body = new FormData();
  [...contextFileInput.files].forEach((file) => body.append("files", file));
  try { state.context = await api(`/api/chats/${state.chatId}/context/files`, { method: "POST", body }); renderContext(state.context); }
  catch (error) { alert(error.message); } finally { contextFileInput.value = ""; }
});
contextFilesList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-file]");
  if (!button) return;
  try { await persistContext({ files: state.context.files.filter((file) => file.name !== button.dataset.file) }); }
  catch (error) { alert(error.message); }
});
codeEditor.addEventListener("input", () => { renderLineNumbers(); updateSelection(); scheduleSuggestion(); });
codeEditor.addEventListener("select", updateSelection);
codeEditor.addEventListener("click", updateSelection);
codeEditor.addEventListener("keyup", updateSelection);
codeEditor.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    if (suggestion) { acceptSuggestion(); return; }
    codeEditor.setRangeText("  ", codeEditor.selectionStart, codeEditor.selectionEnd, "end");
    codeEditor.dispatchEvent(new Event("input"));
  }
  if (event.key === "Escape") clearSuggestion();
});
codeEditor.addEventListener("scroll", () => { lineNumbers.scrollTop = codeEditor.scrollTop; });
files.addEventListener("change", () => { document.querySelector("#file-count").textContent = files.files.length ? `${files.files.length} file` : ""; });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.chatId) await createChat();
  const button = document.querySelector("#send"); button.disabled = true;
  try {
    if (codeEditor.value !== state.context.relevant_code) await persistContext({ relevant_code: codeEditor.value });
    const body = new FormData(); body.append("prompt", document.querySelector("#prompt").value); body.append("operation", document.querySelector("#operation").value);
    [...files.files].forEach((file) => body.append("files", file));
    let answer = "";
    let streamingContent;
    await streamResponse(`/api/chats/${state.chatId}/messages`, body, async () => {
      const chat = await api(`/api/chats/${state.chatId}`);
      renderMessages(chat);
      streamingContent = addStreamingMessage();
    }, (chunk) => {
      const shouldScroll = isNearMessageBottom();
      answer += chunk;
      streamingContent.innerHTML = renderMarkdown(answer);
      addCodeActions(streamingContent);
      renderIcons();
      if (shouldScroll) messages.scrollTop = messages.scrollHeight;
    });
    form.reset(); document.querySelector("#file-count").textContent = ""; await loadChat(state.chatId);
  } catch (error) { alert(error.message); } finally { button.disabled = false; }
});

(async () => { await refreshChats(); const first = chatList.querySelector("button"); if (first) await loadChat(first.dataset.id); else await createChat(); renderIcons(); })().catch((error) => alert(error.message));