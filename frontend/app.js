const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("input-row");
const inputEl = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const bannerEl = document.getElementById("banner");

const sidebarTitleEl = document.querySelector(".sidebar-title");
const chatListEl = document.getElementById("chat-list");
const newChatBtn = document.getElementById("new-chat-btn");

const modeChatBtn = document.getElementById("mode-chat-btn");
const modeCodeBtn = document.getElementById("mode-code-btn");
const modeDbBtn = document.getElementById("mode-db-btn");
const chatPanel = document.getElementById("chat-panel");
const codePanel = document.getElementById("code-panel");
const dbPanel = document.getElementById("db-panel");
const modelSelect = document.getElementById("model-select");

const codeFolderLabel = document.getElementById("code-folder-label");
const chooseFolderBtn = document.getElementById("choose-folder-btn");
const codeMessagesEl = document.getElementById("code-messages");
const pendingQuestionsEl = document.getElementById("pending-questions");
const pendingWritesEl = document.getElementById("pending-writes");
const codeFormEl = document.getElementById("code-input-row");
const codeInputEl = document.getElementById("code-prompt-input");
const codeSendBtn = document.getElementById("code-send-btn");

const dbFileLabel = document.getElementById("db-file-label");
const useAppDbBtn = document.getElementById("use-app-db-btn");
const chooseDbBtn = document.getElementById("choose-db-btn");
const dbMessagesEl = document.getElementById("db-messages");
const dbFormEl = document.getElementById("db-input-row");
const dbInputEl = document.getElementById("db-prompt-input");
const dbSendBtn = document.getElementById("db-send-btn");

const loginModal = document.getElementById("login-modal");
const loginTitleEl = document.getElementById("login-title");
const loginHintEl = document.getElementById("login-hint");
const loginUserListEl = document.getElementById("login-user-list");
const loginEmailInput = document.getElementById("login-email-input");
const loginError = document.getElementById("login-error");
const loginSubmit = document.getElementById("login-submit");
const loginCancel = document.getElementById("login-cancel");

const accountBtn = document.getElementById("account-btn");
const accountAvatarEl = document.getElementById("account-avatar");
const accountEmailEl = document.getElementById("account-email");

const settingsBtn = document.getElementById("settings-btn");
const settingsModal = document.getElementById("settings-modal");
const apiKeyInput = document.getElementById("api-key-input");
const apiKeyError = document.getElementById("api-key-error");
const apiKeySubmit = document.getElementById("api-key-submit");
const apiKeyCancel = document.getElementById("api-key-cancel");

const localProviderSelect = document.getElementById("local-provider-select");
const localBaseUrlInput = document.getElementById("local-base-url-input");
const localModelInput = document.getElementById("local-model-input");
const localModelList = document.getElementById("local-model-list");
const localModelRefreshBtn = document.getElementById("local-model-refresh-btn");
const localLlmError = document.getElementById("local-llm-error");
const localLlmSubmit = document.getElementById("local-llm-submit");
const localLlmCancel = document.getElementById("local-llm-cancel");

const MODEL_LABELS = {
  "claude-haiku-4-5": "Haiku",
  "claude-sonnet-5": "Sonnet",
  "claude-opus-5": "Opus",
};

let currentMode = "chat";
let currentChatId = null;
let currentCodeChatId = null;
let codeFolderReady = false;
let codeAwaitingInput = false; // true while a write approval or a question set is pending

let currentDbChatId = null;
let dbReady = false;

let loggedIn = false;

const CODE_INPUT_DEFAULT_PLACEHOLDER = codeInputEl.placeholder;
const CODE_INPUT_WAITING_PLACEHOLDER = "Resolve the pending item(s) above before continuing…";

function setCodeAwaitingInput(awaiting) {
  codeAwaitingInput = awaiting;
  if (awaiting) {
    codeInputEl.disabled = true;
    codeSendBtn.disabled = true;
    codeInputEl.placeholder = CODE_INPUT_WAITING_PLACEHOLDER;
  } else {
    codeInputEl.disabled = !codeFolderReady;
    codeSendBtn.disabled = !codeFolderReady;
    codeInputEl.placeholder = CODE_INPUT_DEFAULT_PLACEHOLDER;
  }
}

function showBanner(text) {
  bannerEl.textContent = text;
  bannerEl.classList.remove("hidden");
}

function hideBanner() {
  bannerEl.classList.add("hidden");
}

// ---- clipboard helper (works even where navigator.clipboard is unavailable) ----

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch (err2) {
      return false;
    }
  }
}

// ---- generic floating popup menu (used by both the chat ⋮ menu and the bubble context menu) ----

const popupMenuEl = document.createElement("div");
popupMenuEl.className = "popup-menu hidden";
document.body.appendChild(popupMenuEl);

function hidePopupMenu() {
  popupMenuEl.classList.add("hidden");
  popupMenuEl.innerHTML = "";
}

function showPopupMenu(x, y, items, opts) {
  popupMenuEl.innerHTML = "";
  for (const item of items) {
    const btn = document.createElement("button");
    btn.textContent = item.label;
    btn.disabled = !!item.disabled;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      hidePopupMenu();
      item.onClick();
    });
    popupMenuEl.appendChild(btn);
  }
  const menuWidth = 170;
  const x2 = Math.min(x, window.innerWidth - menuWidth - 4);
  popupMenuEl.style.left = `${Math.max(4, x2)}px`;
  if (opts && opts.openUpward) {
    popupMenuEl.style.top = "auto";
    popupMenuEl.style.bottom = `${window.innerHeight - y}px`;
  } else {
    popupMenuEl.style.bottom = "auto";
    popupMenuEl.style.top = `${y}px`;
  }
  popupMenuEl.classList.remove("hidden");
}

document.addEventListener("click", hidePopupMenu);
window.addEventListener("blur", hidePopupMenu);
window.addEventListener("resize", hidePopupMenu);

// ---- custom right-click menu on message bubbles (Copy Selection / Copy Full Message) ----

const contextMenuEl = document.createElement("div");
contextMenuEl.id = "custom-context-menu";
contextMenuEl.className = "hidden";
document.body.appendChild(contextMenuEl);

function hideContextMenu() {
  contextMenuEl.classList.add("hidden");
  contextMenuEl.innerHTML = "";
}

function showContextMenu(x, y, items) {
  contextMenuEl.innerHTML = "";
  for (const item of items) {
    const btn = document.createElement("button");
    btn.textContent = item.label;
    btn.disabled = !!item.disabled;
    btn.addEventListener("click", () => {
      hideContextMenu();
      item.onClick();
    });
    contextMenuEl.appendChild(btn);
  }
  const menuWidth = 190;
  const x2 = Math.min(x, window.innerWidth - menuWidth - 4);
  contextMenuEl.style.left = `${Math.max(4, x2)}px`;
  contextMenuEl.style.top = `${y}px`;
  contextMenuEl.classList.remove("hidden");
}

function attachBubbleContextMenu(container) {
  container.addEventListener("contextmenu", (e) => {
    const bubble = e.target.closest(".bubble");
    if (!bubble) return;
    e.preventDefault();
    const selectedText = window.getSelection().toString();
    showContextMenu(e.clientX, e.clientY, [
      {
        label: "Copy Selection",
        disabled: !selectedText,
        onClick: () => copyText(selectedText),
      },
      {
        label: "Copy Full Message",
        onClick: () => copyText(bubble.dataset.rawText || ""),
      },
    ]);
  });
}

document.addEventListener("click", hideContextMenu);
document.addEventListener("contextmenu", (e) => {
  if (!e.target.closest(".bubble")) hideContextMenu();
});
window.addEventListener("blur", hideContextMenu);
window.addEventListener("resize", hideContextMenu);

// ---- message bubbles ----

function addBubble(container, role, text, meta) {
  const row = document.createElement("div");
  row.className = `bubble-row ${role}`;

  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  bubble.dataset.rawText = text;
  row.appendChild(bubble);

  if (role !== "system") {
    const copyBtn = document.createElement("button");
    copyBtn.className = "bubble-copy-btn";
    copyBtn.title = "Copy message";
    copyBtn.type = "button";
    copyBtn.textContent = "⧉";
    copyBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const ok = await copyText(text);
      if (ok) {
        copyBtn.classList.add("copied");
        copyBtn.textContent = "✓";
        setTimeout(() => {
          copyBtn.classList.remove("copied");
          copyBtn.textContent = "⧉";
        }, 1200);
      }
    });
    bubble.appendChild(copyBtn);
  }

  container.appendChild(row);

  if (meta) {
    const metaRow = document.createElement("div");
    metaRow.className = "bubble-row assistant";
    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.appendChild(meta);
    metaRow.appendChild(metaEl);
    container.appendChild(metaRow);
  }

  container.scrollTop = container.scrollHeight;
}

function buildMeta({ classification, model_used, cost_usd, latency_ms }) {
  const wrap = document.createDocumentFragment();

  if (classification) {
    const tag = document.createElement("span");
    tag.className = `tag ${classification}`;
    tag.textContent = classification;
    wrap.appendChild(tag);
  }

  const modelSpan = document.createElement("span");
  modelSpan.textContent = model_used;
  wrap.appendChild(modelSpan);

  const costSpan = document.createElement("span");
  costSpan.textContent = `$${Number(cost_usd).toFixed(6)}`;
  wrap.appendChild(costSpan);

  if (latency_ms != null) {
    const latSpan = document.createElement("span");
    latSpan.textContent = `${latency_ms}ms`;
    wrap.appendChild(latSpan);
  }

  return wrap;
}

// ---- chat mode ----

async function handleSubmit(e) {
  e.preventDefault();
  const prompt = inputEl.value.trim();
  if (!prompt) return;

  addBubble(messagesEl, "user", prompt, null);
  inputEl.value = "";
  inputEl.disabled = true;
  sendBtn.disabled = true;

  try {
    const result = await window.pywebview.api.send_message(prompt);
    if (result.ok) {
      addBubble(messagesEl, "assistant", result.output, buildMeta(result));
    } else {
      addBubble(messagesEl, "error", result.error || "Something went wrong.", null);
    }
  } catch (err) {
    addBubble(messagesEl, "error", `Unexpected error: ${err}`, null);
  } finally {
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
    refreshSidebar(); // picks up an auto-generated title after a chat's first message
  }
}

formEl.addEventListener("submit", handleSubmit);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

attachBubbleContextMenu(messagesEl);
attachBubbleContextMenu(codeMessagesEl);
attachBubbleContextMenu(dbMessagesEl);

// ---- sidebar: chat list (Chat mode) + code session list (Code mode) ----

function renderSidebarList(items, activeId, onSelect) {
  chatListEl.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "chat-item" + (item.id === activeId ? " active" : "");

    const titleSpan = document.createElement("span");
    titleSpan.className = "chat-item-title";
    titleSpan.textContent = item.title;
    titleSpan.addEventListener("click", () => onSelect(item.id));
    li.appendChild(titleSpan);

    const menuBtn = document.createElement("button");
    menuBtn.className = "chat-item-menu-btn";
    menuBtn.type = "button";
    menuBtn.textContent = "⋮";
    menuBtn.title = "More";
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const rect = menuBtn.getBoundingClientRect();
      showPopupMenu(rect.right, rect.bottom, [
        { label: "Rename", onClick: () => startInlineRename(li, titleSpan, item) },
      ]);
    });
    li.appendChild(menuBtn);

    chatListEl.appendChild(li);
  }
}

function startInlineRename(li, titleSpan, item) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "chat-item-rename-input";
  input.value = item.title;
  li.replaceChild(input, titleSpan);
  input.focus();
  input.select();

  let settled = false;
  async function commit() {
    if (settled) return;
    settled = true;
    const newTitle = input.value.trim();
    if (newTitle && newTitle !== item.title) {
      const result = await window.pywebview.api.rename_chat(item.id, newTitle);
      if (result.ok) item.title = result.title;
    }
    titleSpan.textContent = item.title;
    if (input.parentNode) li.replaceChild(titleSpan, input);
  }
  function cancel() {
    if (settled) return;
    settled = true;
    if (input.parentNode) li.replaceChild(titleSpan, input);
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  });
  input.addEventListener("blur", commit);
  input.addEventListener("click", (e) => e.stopPropagation());
}

async function refreshSidebar() {
  if (currentMode === "chat") {
    const chats = await window.pywebview.api.list_chats();
    renderSidebarList(chats, currentChatId, switchChat);
  } else if (currentMode === "code") {
    const chats = await window.pywebview.api.list_code_chats();
    renderSidebarList(chats, currentCodeChatId, switchCodeChat);
  } else {
    const chats = await window.pywebview.api.list_db_chats();
    renderSidebarList(chats, currentDbChatId, switchDbChat);
  }
}

function renderChatHistory(history) {
  messagesEl.innerHTML = "";
  for (const turn of history) {
    addBubble(messagesEl, "user", turn.input_prompt, null);
    addBubble(
      messagesEl,
      "assistant",
      turn.output_response,
      buildMeta({
        classification: turn.classification,
        model_used: turn.model_used,
        cost_usd: turn.cost_usd,
        latency_ms: turn.latency_ms,
      })
    );
  }
}

async function switchChat(chatId) {
  if (chatId === currentChatId) return;
  const result = await window.pywebview.api.switch_chat(chatId);
  if (!result.ok) {
    showBanner(result.error || "Couldn't switch chats.");
    return;
  }
  currentChatId = chatId;
  renderChatHistory(result.history);
  await refreshSidebar();
  inputEl.focus();
}

newChatBtn.addEventListener("click", async () => {
  if (currentMode === "chat") {
    const result = await window.pywebview.api.create_chat();
    if (!result.ok) {
      showBanner(result.error || "Couldn't create a new chat.");
      return;
    }
    currentChatId = result.chat_id;
    messagesEl.innerHTML = "";
    await refreshSidebar();
    inputEl.focus();
  } else if (currentMode === "code") {
    await chooseFolder();
  } else {
    await useAppDb();
  }
});

// ---- mode toggle (Chat / Code / Database) ----

const SIDEBAR_TITLES = { chat: "Chats", code: "Code Sessions", database: "Database Chats" };
const NEW_BTN_TITLES = { chat: "New chat", code: "New code session", database: "New database chat" };

function switchMode(mode) {
  currentMode = mode;
  chatPanel.classList.toggle("hidden", mode !== "chat");
  codePanel.classList.toggle("hidden", mode !== "code");
  dbPanel.classList.toggle("hidden", mode !== "database");
  modeChatBtn.classList.toggle("active", mode === "chat");
  modeCodeBtn.classList.toggle("active", mode === "code");
  modeDbBtn.classList.toggle("active", mode === "database");
  sidebarTitleEl.textContent = SIDEBAR_TITLES[mode];
  newChatBtn.title = NEW_BTN_TITLES[mode];
  refreshSidebar();
  if (mode === "code") {
    if (codeFolderReady) codeInputEl.focus();
  } else if (mode === "database") {
    if (dbReady) dbInputEl.focus();
  } else {
    inputEl.focus();
  }
}

modeChatBtn.addEventListener("click", () => switchMode("chat"));
modeCodeBtn.addEventListener("click", () => switchMode("code"));
modeDbBtn.addEventListener("click", () => switchMode("database"));

// ---- model selection dropdown ----

function populateModelSelect(availableModels, selectedModel) {
  modelSelect.innerHTML = "";
  const autoOption = document.createElement("option");
  autoOption.value = "";
  autoOption.textContent = "Auto";
  modelSelect.appendChild(autoOption);

  for (const modelId of availableModels || []) {
    const opt = document.createElement("option");
    opt.value = modelId;
    opt.textContent = MODEL_LABELS[modelId] || modelId;
    modelSelect.appendChild(opt);
  }
  modelSelect.value = selectedModel || "";
}

modelSelect.addEventListener("change", () => {
  window.pywebview.api.set_model_override(modelSelect.value || null);
});

// ---- code mode ----

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function formatDiff(diffText) {
  return diffText
    .split("\n")
    .map((line) => {
      const escaped = escapeHtml(line);
      if (line.startsWith("+") && !line.startsWith("+++")) return `<span class="diff-add">${escaped}</span>`;
      if (line.startsWith("-") && !line.startsWith("---")) return `<span class="diff-del">${escaped}</span>`;
      return escaped;
    })
    .join("\n");
}

function renderPendingWrites(writes) {
  pendingWritesEl.innerHTML = "";
  for (const w of writes) {
    const card = document.createElement("div");
    card.className = "pending-write";

    const path = document.createElement("div");
    path.className = "pending-write-path";
    path.textContent = w.path;
    card.appendChild(path);

    const diff = document.createElement("div");
    diff.className = "pending-write-diff";
    diff.innerHTML = formatDiff(w.diff);
    card.appendChild(diff);

    const actions = document.createElement("div");
    actions.className = "pending-write-actions";

    const approveBtn = document.createElement("button");
    approveBtn.className = "btn-approve";
    approveBtn.textContent = "Approve & Write";
    approveBtn.addEventListener("click", () => resolveWrite(w.id, true));
    actions.appendChild(approveBtn);

    const rejectBtn = document.createElement("button");
    rejectBtn.className = "btn-reject";
    rejectBtn.textContent = "Reject";
    rejectBtn.addEventListener("click", () => resolveWrite(w.id, false));
    actions.appendChild(rejectBtn);

    card.appendChild(actions);
    pendingWritesEl.appendChild(card);
  }
}

// Each question set gets one card with all its questions; a single "Submit Answers"
// button is disabled until every question in the set has a selection (or Other filled in).
function renderPendingQuestions(questionSets) {
  pendingQuestionsEl.innerHTML = "";
  for (const qs of questionSets) {
    const card = document.createElement("div");
    card.className = "question-set";

    const questionRefs = []; // {getAnswer(): string|null}

    qs.questions.forEach((q, qIndex) => {
      const block = document.createElement("div");
      const inputName = `qset-${qs.id}-q-${qIndex}`;
      const inputType = q.multiSelect ? "checkbox" : "radio";

      const label = document.createElement("div");
      label.className = "pending-question-text";
      label.textContent = q.question;
      block.appendChild(label);

      const optionsWrap = document.createElement("div");
      optionsWrap.className = "pending-question-options";

      const checkboxes = [];

      for (const opt of q.options) {
        const chip = document.createElement("label");
        chip.className = "option-chip";

        const input = document.createElement("input");
        input.type = inputType;
        input.name = inputName;
        input.value = opt.label;
        checkboxes.push(input);
        chip.appendChild(input);

        const textWrap = document.createElement("span");
        textWrap.className = "option-chip-label";
        const mainText = document.createElement("span");
        mainText.textContent = opt.label;
        textWrap.appendChild(mainText);
        if (opt.description) {
          const desc = document.createElement("span");
          desc.className = "option-desc";
          desc.textContent = opt.description;
          textWrap.appendChild(desc);
        }
        chip.appendChild(textWrap);

        optionsWrap.appendChild(chip);
      }

      // Always offer a free-form "Other" answer, same as Claude's own question UI.
      const otherChip = document.createElement("label");
      otherChip.className = "option-chip other";
      const otherInput = document.createElement("input");
      otherInput.type = inputType;
      otherInput.name = inputName;
      otherInput.value = "__other__";
      checkboxes.push(otherInput);
      otherChip.appendChild(otherInput);
      const otherText = document.createElement("input");
      otherText.type = "text";
      otherText.className = "other-input";
      otherText.placeholder = "Other…";
      otherText.addEventListener("click", (e) => e.stopPropagation());
      otherText.addEventListener("input", () => {
        otherInput.checked = otherText.value.trim().length > 0;
        updateSubmitState();
      });
      otherChip.appendChild(otherText);
      optionsWrap.appendChild(otherChip);

      block.appendChild(optionsWrap);
      card.appendChild(block);

      questionRefs.push({
        getAnswer() {
          const chosen = checkboxes.filter((cb) => cb.checked);
          if (!chosen.length) return null;
          const labels = chosen.map((cb) =>
            cb.value === "__other__" ? otherText.value.trim() : cb.value
          );
          if (labels.some((l) => !l)) return null;
          return labels.join(", ");
        },
      });

      optionsWrap.addEventListener("change", updateSubmitState);
    });

    const submitBtn = document.createElement("button");
    submitBtn.className = "question-set-submit";
    submitBtn.type = "button";
    submitBtn.textContent = "Submit Answers";
    submitBtn.disabled = true;
    submitBtn.addEventListener("click", () => {
      const answers = questionRefs.map((q) => q.getAnswer());
      submitQuestionAnswers(qs.id, answers);
    });
    card.appendChild(submitBtn);

    function updateSubmitState() {
      submitBtn.disabled = questionRefs.some((q) => q.getAnswer() === null);
    }

    pendingQuestionsEl.appendChild(card);
  }
}

function handleCodeResult(result) {
  if (!result.ok) {
    addBubble(codeMessagesEl, "error", result.error || "Something went wrong.", null);
    // A stale double-submit can still race in and get rejected by the backend's own
    // pending-input guard — don't clear the real pending cards or unblock input for that.
    if (result.error_type !== "pending_input") {
      pendingWritesEl.innerHTML = "";
      pendingQuestionsEl.innerHTML = "";
      setCodeAwaitingInput(false);
    }
    return;
  }
  if (result.status === "final") {
    addBubble(codeMessagesEl, "assistant", result.text, buildMeta(result));
    pendingWritesEl.innerHTML = "";
    pendingQuestionsEl.innerHTML = "";
    setCodeAwaitingInput(false);
  } else if (result.status === "pending_input") {
    if (!codeAwaitingInput) {
      addBubble(
        codeMessagesEl,
        "system",
        "⏳ Waiting for your input below before continuing.",
        null
      );
    }
    renderPendingWrites(result.pending_writes || []);
    renderPendingQuestions(result.pending_questions || []);
    setCodeAwaitingInput(true);
  }
}

async function chooseFolder() {
  const result = await window.pywebview.api.choose_code_folder();
  if (result.ok) {
    currentCodeChatId = result.chat_id;
    codeFolderLabel.textContent = result.folder;
    codeFolderReady = true;
    setCodeAwaitingInput(false); // fresh session — also enables input now that a folder is set
    codeMessagesEl.innerHTML = "";
    pendingWritesEl.innerHTML = "";
    pendingQuestionsEl.innerHTML = "";
    await refreshSidebar();
    codeInputEl.focus();
  } else if (result.error) {
    addBubble(codeMessagesEl, "error", result.error, null);
  }
}

async function switchCodeChat(chatId) {
  if (chatId === currentCodeChatId) return;
  const result = await window.pywebview.api.switch_code_chat(chatId);
  if (!result.ok) {
    showBanner(result.error || "Couldn't switch code session.");
    return;
  }
  currentCodeChatId = chatId;
  codeFolderLabel.textContent = result.folder;
  codeFolderReady = true;
  setCodeAwaitingInput(false); // reopening starts a fresh CodeSession — nothing pending yet
  codeMessagesEl.innerHTML = "";
  pendingWritesEl.innerHTML = "";
  pendingQuestionsEl.innerHTML = "";
  await refreshSidebar();
  codeInputEl.focus();
}

chooseFolderBtn.addEventListener("click", chooseFolder);

async function handleCodeSubmit(e) {
  e.preventDefault();
  const prompt = codeInputEl.value.trim();
  if (!prompt || !codeFolderReady || codeAwaitingInput) return;

  addBubble(codeMessagesEl, "user", prompt, null);
  codeInputEl.value = "";
  codeInputEl.disabled = true;
  codeSendBtn.disabled = true;

  try {
    const result = await window.pywebview.api.send_code_message(prompt);
    handleCodeResult(result);
  } catch (err) {
    addBubble(codeMessagesEl, "error", `Unexpected error: ${err}`, null);
    setCodeAwaitingInput(false);
  } finally {
    // Only re-enable if handleCodeResult() didn't just put us in a pending-input state.
    if (!codeAwaitingInput) {
      codeInputEl.disabled = false;
      codeSendBtn.disabled = false;
      codeInputEl.focus();
    }
    refreshSidebar(); // picks up an auto-generated title after this session's first message
  }
}

codeFormEl.addEventListener("submit", handleCodeSubmit);
codeInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    codeFormEl.requestSubmit();
  }
});

async function resolveWrite(writeId, approve) {
  popupMenuEl.classList.add("hidden");
  pendingWritesEl.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    const result = await window.pywebview.api.resolve_code_write(writeId, approve);
    handleCodeResult(result);
  } catch (err) {
    addBubble(codeMessagesEl, "error", `Unexpected error: ${err}`, null);
    setCodeAwaitingInput(false);
  }
}

async function submitQuestionAnswers(questionSetId, answers) {
  pendingQuestionsEl.querySelectorAll("button, input").forEach((el) => (el.disabled = true));
  try {
    const result = await window.pywebview.api.resolve_code_questions(questionSetId, answers);
    handleCodeResult(result);
  } catch (err) {
    addBubble(codeMessagesEl, "error", `Unexpected error: ${err}`, null);
    setCodeAwaitingInput(false);
  }
}

// ---- database mode ----

function setDbInputEnabled(enabled) {
  dbInputEl.disabled = !enabled;
  dbSendBtn.disabled = !enabled;
}

function addDbUserBubble(text) {
  addBubble(dbMessagesEl, "user", text, null);
}

// Renders one answer as a bubble containing the NL answer, a collapsible SQL block,
// and a results table — richer than the plain-text addBubble() used elsewhere, since
// there's structured data (SQL + rows) to show alongside the answer.
function renderDbAnswer(result) {
  const row = document.createElement("div");
  row.className = "bubble-row assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble assistant db-result";

  const answerEl = document.createElement("div");
  answerEl.className = "db-answer-text";
  answerEl.textContent = result.answer;
  bubble.appendChild(answerEl);

  if (result.sql) {
    const details = document.createElement("details");
    details.className = "db-sql-details";
    const summary = document.createElement("summary");
    summary.textContent = "SQL used";
    details.appendChild(summary);
    const pre = document.createElement("pre");
    pre.className = "db-sql";
    pre.textContent = result.sql;
    details.appendChild(pre);
    bubble.appendChild(details);
  }

  if (result.columns && result.columns.length) {
    bubble.appendChild(buildDbTable(result.columns, result.rows || []));
  }

  row.appendChild(bubble);
  dbMessagesEl.appendChild(row);
  dbMessagesEl.scrollTop = dbMessagesEl.scrollHeight;
}

function buildDbTable(columns, rows) {
  const wrap = document.createElement("div");
  wrap.className = "db-table-wrap";

  const table = document.createElement("table");
  table.className = "db-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const cell of r) {
      const td = document.createElement("td");
      td.textContent = cell === null ? "NULL" : String(cell);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  wrap.appendChild(table);
  return wrap;
}

function renderDbHistory(history) {
  dbMessagesEl.innerHTML = "";
  for (const turn of history) {
    addDbUserBubble(turn.input_prompt);
    let parsed = { columns: [], rows: [] };
    if (turn.result_json) {
      try {
        parsed = JSON.parse(turn.result_json);
      } catch (e) {
        // ignore malformed/legacy rows
      }
    }
    renderDbAnswer({
      answer: turn.output_response,
      sql: turn.sql_query,
      columns: parsed.columns,
      rows: parsed.rows,
    });
  }
}

async function useAppDb() {
  const result = await window.pywebview.api.create_db_chat();
  if (result.ok) {
    currentDbChatId = result.chat_id;
    dbFileLabel.textContent = result.db_path;
    dbReady = true;
    setDbInputEnabled(true);
    dbMessagesEl.innerHTML = "";
    await refreshSidebar();
    dbInputEl.focus();
  } else if (result.error) {
    addBubble(dbMessagesEl, "error", result.error, null);
  }
}

async function chooseDbFile() {
  const result = await window.pywebview.api.choose_db_file();
  if (result.ok) {
    currentDbChatId = result.chat_id;
    dbFileLabel.textContent = result.db_path;
    dbReady = true;
    setDbInputEnabled(true);
    dbMessagesEl.innerHTML = "";
    await refreshSidebar();
    dbInputEl.focus();
  } else if (result.error) {
    addBubble(dbMessagesEl, "error", result.error, null);
  }
}

async function switchDbChat(chatId) {
  if (chatId === currentDbChatId) return;
  const result = await window.pywebview.api.switch_db_chat(chatId);
  if (!result.ok) {
    showBanner(result.error || "Couldn't switch database chat.");
    return;
  }
  currentDbChatId = chatId;
  dbFileLabel.textContent = result.db_path;
  dbReady = true;
  setDbInputEnabled(true);
  renderDbHistory(result.history || []);
  await refreshSidebar();
  dbInputEl.focus();
}

useAppDbBtn.addEventListener("click", useAppDb);
chooseDbBtn.addEventListener("click", chooseDbFile);

async function handleDbSubmit(e) {
  e.preventDefault();
  const prompt = dbInputEl.value.trim();
  if (!prompt || !dbReady) return;

  addDbUserBubble(prompt);
  dbInputEl.value = "";
  setDbInputEnabled(false);

  try {
    const result = await window.pywebview.api.send_db_message(prompt);
    if (result.ok) {
      renderDbAnswer(result);
    } else {
      addBubble(dbMessagesEl, "error", result.error || "Something went wrong.", null);
      if (result.sql) {
        const pre = document.createElement("pre");
        pre.className = "db-sql db-sql-failed";
        pre.textContent = result.sql;
        dbMessagesEl.appendChild(pre);
      }
    }
  } catch (err) {
    addBubble(dbMessagesEl, "error", `Unexpected error: ${err}`, null);
  } finally {
    setDbInputEnabled(true);
    dbInputEl.focus();
    refreshSidebar(); // picks up an auto-generated title after this chat's first message
  }
}

dbFormEl.addEventListener("submit", handleDbSubmit);
dbInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    dbFormEl.requestSubmit();
  }
});

// ---- account: login / switch account / logout ----

function isValidEmail(value) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
}

function updateAccountFooter(email) {
  accountEmailEl.textContent = email || "Not signed in";
  accountAvatarEl.textContent = email ? email[0].toUpperCase() : "?";
}

function resetModePanelsForAccountSwitch() {
  // Code mode: the backend drops its CodeSession on login/logout, so the folder
  // picker must be re-chosen for the new account too.
  currentCodeChatId = null;
  codeFolderReady = false;
  setCodeAwaitingInput(false);
  codeFolderLabel.textContent = "No folder selected";
  codeMessagesEl.innerHTML = "";
  pendingWritesEl.innerHTML = "";
  pendingQuestionsEl.innerHTML = "";

  // Database mode: same story for the DBSession.
  currentDbChatId = null;
  dbReady = false;
  setDbInputEnabled(false);
  dbFileLabel.textContent = "No database selected";
  dbMessagesEl.innerHTML = "";
}

async function applyAccountState(state) {
  loggedIn = true;
  updateAccountFooter(state.email);
  resetModePanelsForAccountSwitch();
  currentChatId = state.current_chat_id;
  renderChatHistory(state.history);
  populateModelSelect(state.available_models, state.selected_model);
  switchMode("chat");

  if (!state.local_llm_ready) {
    showBanner(`⚠ ${state.local_llm_message}`);
  } else if (!state.has_api_key) {
    showBanner("⚠ No Anthropic API key configured. Click the gear icon to add one.");
  } else {
    hideBanner();
  }
  inputEl.focus();
}

async function showLoginModal(opts) {
  const allowCancel = !!(opts && opts.allowCancel);
  loginError.classList.add("hidden");
  loginEmailInput.value = "";
  loginCancel.classList.toggle("hidden", !allowCancel);

  const users = await window.pywebview.api.list_users();
  loginUserListEl.innerHTML = "";
  if (users.length) {
    loginTitleEl.textContent = "Switch account";
    loginHintEl.textContent = "Choose an account, or continue with a different email. Each account's chats and history are kept separate and untouched while you're away.";
    for (const u of users) {
      const btn = document.createElement("button");
      btn.className = "account-option";
      btn.type = "button";
      btn.textContent = u.email;
      btn.addEventListener("click", () => doLogin(u.email));
      loginUserListEl.appendChild(btn);
    }
  } else {
    loginTitleEl.textContent = "Welcome";
    loginHintEl.textContent = "Enter your email to get started. No password needed — this is just used to label your local activity.";
  }

  loginModal.classList.remove("hidden");
}

async function doLogin(email) {
  email = (email || "").trim();
  if (!isValidEmail(email)) {
    loginError.textContent = "Enter a valid email address.";
    loginError.classList.remove("hidden");
    return;
  }
  const result = await window.pywebview.api.login(email);
  if (result.ok) {
    loginModal.classList.add("hidden");
    const state = await window.pywebview.api.get_bootstrap_state();
    await applyAccountState(state);
  } else {
    loginError.textContent = result.error || "Couldn't log in.";
    loginError.classList.remove("hidden");
  }
}

loginSubmit.addEventListener("click", () => doLogin(loginEmailInput.value));
loginEmailInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    doLogin(loginEmailInput.value);
  }
});
loginCancel.addEventListener("click", () => {
  loginModal.classList.add("hidden");
});

async function handleLogout() {
  await window.pywebview.api.logout();
  loggedIn = false;
  updateAccountFooter(null);
  resetModePanelsForAccountSwitch();
  currentChatId = null;
  messagesEl.innerHTML = "";
  hideBanner();
  await showLoginModal({ allowCancel: false });
}

accountBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  const rect = accountBtn.getBoundingClientRect();
  showPopupMenu(
    rect.left,
    rect.top - 6,
    [
      { label: "Switch Account", onClick: () => showLoginModal({ allowCancel: true }) },
      { label: "Log Out", onClick: handleLogout },
    ],
    { openUpward: true }
  );
});

// ---- settings modal (API key + local LLM provider) ----

function populateProviderSelect(providers, selected) {
  localProviderSelect.innerHTML = "";
  for (const p of providers || []) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.label;
    localProviderSelect.appendChild(opt);
  }
  localProviderSelect.value = selected || "";
}

function populateModelDatalist(models) {
  localModelList.innerHTML = "";
  for (const m of models || []) {
    const opt = document.createElement("option");
    opt.value = m;
    localModelList.appendChild(opt);
  }
}

async function refreshLocalModelList() {
  const result = await window.pywebview.api.list_local_llm_models(
    localProviderSelect.value,
    localBaseUrlInput.value.trim()
  );
  populateModelDatalist(result.models || []);
  if (!result.ok) {
    localLlmError.textContent = result.error || "Couldn't reach that runtime.";
    localLlmError.classList.remove("hidden");
  } else {
    localLlmError.classList.add("hidden");
  }
}

localProviderSelect.addEventListener("change", async () => {
  // Only replace the base URL with the new provider's default if the user hadn't
  // customized it away from the previous provider's default already.
  const prevDefault = await window.pywebview.api.default_local_llm_base_url(
    localProviderSelect.dataset.prevProvider || ""
  );
  if (!localBaseUrlInput.value.trim() || localBaseUrlInput.value.trim() === prevDefault) {
    const newDefault = await window.pywebview.api.default_local_llm_base_url(localProviderSelect.value);
    localBaseUrlInput.value = newDefault;
  }
  localProviderSelect.dataset.prevProvider = localProviderSelect.value;
});

localModelRefreshBtn.addEventListener("click", refreshLocalModelList);

settingsBtn.addEventListener("click", async () => {
  apiKeyInput.value = "";
  apiKeyError.classList.add("hidden");

  const local = await window.pywebview.api.get_local_llm_settings();
  populateProviderSelect(local.providers, local.provider);
  localProviderSelect.dataset.prevProvider = local.provider;
  localBaseUrlInput.value = local.base_url;
  localModelInput.value = local.model;
  localLlmError.classList.add("hidden");
  populateModelDatalist([]);
  refreshLocalModelList();

  settingsModal.classList.remove("hidden");
});

apiKeyCancel.addEventListener("click", () => {
  settingsModal.classList.add("hidden");
});

localLlmCancel.addEventListener("click", () => {
  settingsModal.classList.add("hidden");
});

apiKeySubmit.addEventListener("click", async () => {
  const key = apiKeyInput.value.trim();
  if (!key) {
    apiKeyError.textContent = "API key can't be empty.";
    apiKeyError.classList.remove("hidden");
    return;
  }
  const result = await window.pywebview.api.save_api_key(key);
  if (result.ok) {
    settingsModal.classList.add("hidden");
    hideBanner();
  } else {
    apiKeyError.textContent = result.error || "Couldn't save that key.";
    apiKeyError.classList.remove("hidden");
  }
});

localLlmSubmit.addEventListener("click", async () => {
  const model = localModelInput.value.trim();
  if (!model) {
    localLlmError.textContent = "Model can't be empty.";
    localLlmError.classList.remove("hidden");
    return;
  }
  const result = await window.pywebview.api.save_local_llm_settings(
    localProviderSelect.value,
    localBaseUrlInput.value.trim(),
    model
  );
  if (result.ok) {
    settingsModal.classList.add("hidden");
    const state = await window.pywebview.api.get_bootstrap_state();
    if (!state.local_llm_ready) {
      showBanner(`⚠ ${state.local_llm_message}`);
    } else {
      hideBanner();
    }
  } else {
    localLlmError.textContent = result.error || "Couldn't save those settings.";
    localLlmError.classList.remove("hidden");
  }
});

// ---- bootstrap ----

window.addEventListener("pywebviewready", async () => {
  const state = await window.pywebview.api.get_bootstrap_state();

  populateModelSelect(state.available_models, state.selected_model);

  if (state.first_run) {
    await showLoginModal({ allowCancel: false });
  } else {
    loggedIn = true;
    updateAccountFooter(state.email);
    currentChatId = state.current_chat_id;
    renderSidebarList(state.chats, currentChatId, switchChat);
    renderChatHistory(state.history);

    if (!state.local_llm_ready) {
      showBanner(`⚠ ${state.local_llm_message}`);
    } else if (!state.has_api_key) {
      showBanner("⚠ No Anthropic API key configured. Click the gear icon to add one.");
    }
  }

  inputEl.focus();
});
