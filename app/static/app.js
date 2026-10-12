const state = { chatId: null, context: null, selection: "", suggestionPending: false };
const chatList = document.querySelector("#chat-list");
const messages = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const form = document.querySelector("#prompt-form");
const promptInput = document.querySelector("#prompt");
const files = document.querySelector("#files");
const contextFileInput = document.querySelector("#context-files");
const contextFilesList = document.querySelector("#context-files-list");
const sourceAnalysis = document.querySelector("#source-analysis");
const codeEditor = document.querySelector("#code-editor");
const lineNumbers = document.querySelector("#line-numbers");
const inlineSuggestion = document.querySelector("#inline-suggestion");
const inlineSuggestionCode = document.querySelector("#inline-suggestion-code");
const acceptSuggestionButton = document.querySelector("#accept-suggestion");
const dismissSuggestionButton = document.querySelector("#dismiss-suggestion");
const selectionStatus = document.querySelector("#selection-status");
const selectionButton = document.querySelector("#use-selection");
const contextChip = document.querySelector("#context-chip");
const contextChipText = document.querySelector("#context-chip-text");
const activeContext = document.querySelector("#active-context");

const escapeHtml = (text) => text.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const renderMarkdown = (text) => window.marked && window.DOMPurify
  ? window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true, breaks: true }))
  : escapeHtml(text).replace(/\n/g, "<br>");
const renderMessageContent = (message) => message.role === "assistant" ? renderMarkdown(message.content) : escapeHtml(message.content);
const renderIcons = () => window.lucide?.createIcons();

function decorateCodeBlocks(container) {
  container.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    let frame = pre.parentElement;
    if (!frame.classList.contains("code-block")) {
      frame = document.createElement("div");
      frame.className = "code-block";
      pre.before(frame);
      frame.append(pre);
    }
    if (window.hljs) {
      const languageClass = [...code.classList].find((className) => className.startsWith("language-"));
      const language = languageClass?.slice("language-".length);
      const highlighted = language && window.hljs.getLanguage(language)
        ? window.hljs.highlight(code.textContent, { language })
        : window.hljs.highlightAuto(code.textContent);
      code.innerHTML = highlighted.value;
      code.classList.add("hljs");
    }
    if (frame.querySelector(".copy-code-button")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code-button";
    button.title = "Copia codice";
    button.setAttribute("aria-label", "Copia codice");
    button.innerHTML = '<i data-lucide="copy"></i>';
    frame.append(button);
  });
  renderIcons();
}

async function copyCode(button) {
  const code = button.closest(".code-block")?.querySelector("pre > code")?.textContent;
  if (code === undefined) return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(code);
    else throw new Error("Clipboard API unavailable");
  } catch {
    const fallback = document.createElement("textarea");
    fallback.value = code;
    fallback.setAttribute("readonly", "");
    fallback.style.position = "fixed";
    fallback.style.opacity = "0";
    document.body.append(fallback);
    fallback.select();
    const copied = document.execCommand("copy");
    fallback.remove();
    if (!copied) {
      button.title = "Copia non riuscita";
      return;
    }
  }
  button.dataset.copied = "true";
  button.title = "Codice copiato";
  button.setAttribute("aria-label", "Codice copiato");
  button.innerHTML = '<i data-lucide="check"></i>';
  renderIcons();
  window.setTimeout(() => {
    if (!button.isConnected) return;
    delete button.dataset.copied;
    button.title = "Copia codice";
    button.setAttribute("aria-label", "Copia codice");
    button.innerHTML = '<i data-lucide="copy"></i>';
    renderIcons();
  }, 1400);
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
  messages.querySelectorAll(".markdown-content").forEach(decorateCodeBlocks);
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

function dismissInlineSuggestion() {
  state.inlineSuggestion = null;
  inlineSuggestion.hidden = true;
  inlineSuggestionCode.textContent = "";
}

function positionInlineSuggestion() {
  const suggestion = state.inlineSuggestion;
  if (!suggestion) return;
  const styles = getComputedStyle(codeEditor);
  const prefix = suggestion.source.slice(0, suggestion.selectionStart);
  const lineStart = prefix.lastIndexOf("\n") + 1;
  const lineText = prefix.slice(lineStart);
  const tabSize = Number.parseInt(styles.tabSize, 10) || 2;
  let column = 0;
  let expandedLine = "";
  for (const character of lineText) {
    if (character === "\t") {
      const spaces = tabSize - (column % tabSize);
      expandedLine += " ".repeat(spaces);
      column += spaces;
    } else {
      expandedLine += character;
      column += 1;
    }
  }
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  context.font = styles.font;
  const textOffset = context.measureText(expandedLine).width;
  const lineNumber = (prefix.match(/\n/g) || []).length;
  const lineHeight = Number.parseFloat(styles.lineHeight);
  const editorRect = codeEditor.getBoundingClientRect();
  const wrapRect = codeEditor.parentElement.getBoundingClientRect();
  const left = editorRect.left - wrapRect.left + Number.parseFloat(styles.borderLeftWidth)
    + Number.parseFloat(styles.paddingLeft) + textOffset - codeEditor.scrollLeft;
  const top = editorRect.top - wrapRect.top + Number.parseFloat(styles.borderTopWidth)
    + Number.parseFloat(styles.paddingTop) + lineNumber * lineHeight - codeEditor.scrollTop;
  inlineSuggestion.hidden = false;
  inlineSuggestionCode.textContent = suggestion.code;
  inlineSuggestion.style.left = `${Math.max(46, Math.min(left, wrapRect.width - inlineSuggestion.offsetWidth - 8))}px`;
  inlineSuggestion.style.top = `${Math.max(4, Math.min(top, wrapRect.height - inlineSuggestion.offsetHeight - 4))}px`;
  renderIcons();
}

function acceptInlineSuggestion() {
  const suggestion = state.inlineSuggestion;
  if (!suggestion) return;
  dismissInlineSuggestion();
  codeEditor.focus();
  codeEditor.setRangeText(suggestion.code, suggestion.selectionStart, suggestion.selectionEnd, "end");
  codeEditor.dispatchEvent(new Event("input", { bubbles: true }));
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
  const suggestion = state.inlineSuggestion;
  if (suggestion && (state.chatId !== suggestion.chatId || codeEditor.value !== suggestion.source
    || codeEditor.selectionStart !== suggestion.selectionStart || codeEditor.selectionEnd !== suggestion.selectionEnd)) {
    dismissInlineSuggestion();
  }
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
  dismissInlineSuggestion();
  state.chatId = chatId;
  const chat = await api(`/api/chats/${chatId}`);
  renderMessages(chat);
  renderContext(chat.context);
  await refreshChats();
}

async function refreshChats() {
  const chats = await api("/api/chats");
  chatList.innerHTML = chats.map((chat) => `<button class="chat-link ${chat.id === state.chatId ? "active" : ""}" data-id="${chat.id}"><i data-lucide="message-square"></i><span>${escapeHtml(chat.title)}</span></button>`).join("");
  chatList.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => loadChat(button.dataset.id)));
  renderIcons();
}

async function createChat() {
  const chat = await api("/api/chats", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await loadChat(chat.id);
}

document.querySelector("#new-chat").addEventListener("click", createChat);
document.querySelector("#refresh-chats").addEventListener("click", refreshChats);
promptInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  event.preventDefault();
  if (event.ctrlKey) {
    promptInput.setRangeText("\n", promptInput.selectionStart, promptInput.selectionEnd, "end");
    promptInput.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  form.requestSubmit();
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
messages.addEventListener("click", async (event) => {
  const button = event.target.closest(".copy-code-button");
  if (button) await copyCode(button);
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
codeEditor.addEventListener("input", () => { renderLineNumbers(); updateSelection(); });
codeEditor.addEventListener("select", updateSelection);
codeEditor.addEventListener("click", updateSelection);
codeEditor.addEventListener("keyup", updateSelection);
codeEditor.addEventListener("keydown", async (event) => {
  if (state.inlineSuggestion && event.key === "Tab") {
    event.preventDefault();
    acceptInlineSuggestion();
    return;
  }
  if (state.inlineSuggestion && event.key === "Escape") {
    event.preventDefault();
    dismissInlineSuggestion();
    updateSelection();
    return;
  }
  if (!event.ctrlKey || event.code !== "Space") return;
  event.preventDefault();
  if (state.suggestionPending || !state.chatId || !codeEditor.value.trim()) return;
  const codeAtRequest = codeEditor.value;
  const selectionStart = codeEditor.selectionStart;
  const selectionEnd = codeEditor.selectionEnd;
  const cursor = [...codeAtRequest.slice(0, selectionStart)].length;
  const chatId = state.chatId;
  state.suggestionPending = true;
  codeEditor.setAttribute("aria-busy", "true");
  selectionStatus.textContent = "Suggerimento in corso...";
  try {
    const suggestion = await api(`/api/chats/${chatId}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: codeAtRequest, cursor }),
    });
    if (!suggestion.code) return;
    if (state.chatId !== chatId || codeEditor.value !== codeAtRequest || document.activeElement !== codeEditor
      || codeEditor.selectionStart !== selectionStart || codeEditor.selectionEnd !== selectionEnd) return;
    state.inlineSuggestion = { chatId, source: codeAtRequest, selectionStart, selectionEnd, code: suggestion.code };
    positionInlineSuggestion();
  } catch (error) { alert(error.message); }
  finally {
    state.suggestionPending = false;
    codeEditor.removeAttribute("aria-busy");
    updateSelection();
    if (state.inlineSuggestion) selectionStatus.textContent = "Suggerimento pronto · Tab accetta · Esc ignora";
  }
});
acceptSuggestionButton.addEventListener("mousedown", (event) => event.preventDefault());
acceptSuggestionButton.addEventListener("click", acceptInlineSuggestion);
dismissSuggestionButton.addEventListener("mousedown", (event) => event.preventDefault());
dismissSuggestionButton.addEventListener("click", () => { dismissInlineSuggestion(); updateSelection(); });
codeEditor.addEventListener("scroll", () => { lineNumbers.scrollTop = codeEditor.scrollTop; positionInlineSuggestion(); });
files.addEventListener("change", () => { document.querySelector("#file-count").textContent = files.files.length ? `${files.files.length} file` : ""; });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.chatId) await createChat();
  const button = document.querySelector("#send"); button.disabled = true;
  let answer = "";
  let streamingContent;
  let renderFrame = 0;
  let followStream = true;
  const renderStream = () => {
    renderFrame = 0;
    if (!streamingContent?.isConnected) return;
    streamingContent.innerHTML = renderMarkdown(answer);
    if (followStream) messages.scrollTop = messages.scrollHeight;
  };
  try {
    if (codeEditor.value !== state.context.relevant_code) await persistContext({ relevant_code: codeEditor.value });
    const body = new FormData(); body.append("prompt", document.querySelector("#prompt").value); body.append("operation", document.querySelector("#operation").value);
    [...files.files].forEach((file) => body.append("files", file));
    await streamResponse(`/api/chats/${state.chatId}/messages`, body, async () => {
      const chat = await api(`/api/chats/${state.chatId}`);
      renderMessages(chat);
      streamingContent = addStreamingMessage();
    }, (chunk) => {
      followStream = messages.scrollHeight - messages.clientHeight - messages.scrollTop < 48;
      answer += chunk;
      if (!renderFrame) renderFrame = requestAnimationFrame(renderStream);
    });
    if (renderFrame) cancelAnimationFrame(renderFrame);
    renderStream();
    decorateCodeBlocks(streamingContent);
    streamingContent.closest(".message")?.querySelector(".streaming-dot")?.remove();
    form.reset(); document.querySelector("#file-count").textContent = ""; await refreshChats();
  } catch (error) {
    if (renderFrame) cancelAnimationFrame(renderFrame);
    if (streamingContent?.isConnected) {
      renderStream();
      decorateCodeBlocks(streamingContent);
      const message = streamingContent.closest(".message");
      message?.querySelector(".streaming-dot")?.remove();
      const warning = document.createElement("p");
      warning.className = "message-warning";
      warning.textContent = `Generazione interrotta; la risposta potrebbe essere incompleta. ${error.message}`;
      message?.append(warning);
    } else alert(error.message);
  } finally { button.disabled = false; }
});

(async () => { await refreshChats(); const first = chatList.querySelector("button"); if (first) await loadChat(first.dataset.id); else await createChat(); renderIcons(); })().catch((error) => alert(error.message));