// Event wiring for the rendered shell. `bindRoute` runs after every `renderApp`
// and re-attaches handlers to the fresh DOM; it delegates to small per-area
// binders so each page's interactions are easy to find.

import { api } from "./api.js";
import { MAX_RAW_TEXT_LINES, state } from "./state.js";
import { ankiFileName, cleanTranslation, countTextLines, formatRangeValue, looksLikeSubtitleText, normalizeUser, unitKey, validateRawText } from "./utils.js";
import {
  applyKnowledgeContextStatus,
  ensureTranslation,
  localTranslation,
  patchKnowledgeStatus,
} from "./mutations.js";
import { readSupportedUploadFile } from "./upload.js";
import { speakText } from "./tts.js";
import { analysisUnitsForLearn } from "./views/analysis.js";
import { knowledgeUnitsForLearn } from "./views/knowledge.js";
import { renderApp } from "./views/shell.js";
import { loadRoute, navigate } from "./router.js";

// Scroll position to restore in the document reader after a re-render.
let pendingReaderScrollTop = null;

export function bindRoute() {
  bindSharedEvents();
  bindUploadEvents();
  bindDocumentEvents();
  bindAnalysisEvents();
  bindKnowledgeEvents();
  bindLearnEvents();
  bindSettingsEvents();
  bindBillingEvents();
  bindAdminEvents();
  restoreReaderScroll();
}

// Delete-doc, speak, range sliders, tooltips, status buttons, words pagination —
// controls that can appear on several pages.
function bindSharedEvents() {
  document.querySelectorAll("[data-delete-doc]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/documents/${button.dataset.deleteDoc}`, { method: "DELETE" });
      await loadRoute();
    });
  });

  document.querySelectorAll("[data-speak]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      speakText(button.dataset.speak || "");
    });
  });

  document.querySelectorAll("[data-range-name]").forEach((input) => {
    input.addEventListener("input", () => {
      const marker = document.querySelector(`[data-range-value="${input.dataset.rangeName}"]`);
      if (marker) marker.textContent = formatRangeValue(input.value);
    });
  });

  document.querySelectorAll("[data-status]:not([data-kg-status])").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus(button.dataset.kind === "phrase" ? "phrase" : "word", button.dataset.knowledgeId, button.dataset.status);
      if (state.selectedWord && state.selectedWord.type) {
        const isPhrase = state.selectedWord.type === "phrase";
        const selectedKnowledgeId = isPhrase ? state.selectedWord.user_phrase_id : state.selectedWord.user_word_id;
        if (selectedKnowledgeId === button.dataset.knowledgeId) state.selectedWord = { ...state.selectedWord, status: button.dataset.status };
      }
      renderApp();
    });
  });

  document.querySelectorAll("[data-quick-word]").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus("word", button.dataset.quickWord, button.dataset.status);
      renderApp();
    });
  });

  document.querySelectorAll("[data-quick-phrase]").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus("phrase", button.dataset.quickPhrase, button.dataset.status);
      renderApp();
    });
  });

  document.querySelectorAll("[data-tooltip-kind][data-tooltip-id]").forEach((button) => {
    button.addEventListener("mouseenter", async () => {
      const kind = button.dataset.tooltipKind;
      const knowledgeId = button.dataset.tooltipId;
      if (!knowledgeId || cleanTranslation(button.getAttribute("title"))) return;
      await ensureTranslation(kind, knowledgeId, localTranslation(kind, knowledgeId), { render: false });
      const translation = cleanTranslation(localTranslation(kind, knowledgeId));
      if (translation) button.setAttribute("title", translation);
    }, { once: true });
  });

  document.querySelector("[data-words-next]")?.addEventListener("click", () => {
    state.wordsVisibleCount = Math.max(100, Number(state.wordsVisibleCount || 100)) + 100;
    renderApp();
  });
}

function bindUploadEvents() {
  document.querySelector("#uploadForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const file = form.file.files[0];
    const submitButton = form.querySelector("button[type=submit]");
    const notice = form.querySelector("[data-upload-analysis-notice]");

    try {
      if (file) data.raw_text = await readSupportedUploadFile(file);
      validateRawText(data.raw_text);
    } catch (error) {
      state.message = error.message || "Не удалось прочитать файл или текст.";
      renderApp();
      return;
    }

    form.querySelectorAll("input, select, textarea, button").forEach((control) => {
      control.disabled = true;
    });
    if (submitButton) submitButton.textContent = "Анализируется...";
    if (notice) notice.hidden = false;
    state.message = "";

    try {
      if (looksLikeSubtitleText(data.raw_text)) data.type = "srt";
      const { document } = await api("/api/documents", { method: "POST", body: data });
      await navigate(`/document/${document.id}/analysis`);
    } catch (error) {
      state.message = error.message || "Не удалось выполнить анализ текста.";
      renderApp();
    }
  });

  document.querySelector("input[type=file]")?.addEventListener("change", async (event) => {
    const file = event.currentTarget.files[0];
    if (!file) return;
    try {
      const text = await readSupportedUploadFile(file);
      state.message = "";
      document.querySelector("textarea[name=raw_text]").value = text;
      if (!document.querySelector("input[name=title]").value) document.querySelector("input[name=title]").value = file.name.replace(/\.[^.]+$/, "");
      if (file.name.toLowerCase().endsWith(".srt") || looksLikeSubtitleText(text)) document.querySelector("select[name=type]").value = "srt";
    } catch (error) {
      event.currentTarget.value = "";
      state.message = error.message || "Не удалось прочитать файл.";
      renderApp();
    }
  });

  document.querySelector("textarea[name=raw_text]")?.addEventListener("paste", (event) => {
    const textarea = event.currentTarget;
    const pastedText = event.clipboardData?.getData("text") || "";
    const nextValue = `${textarea.value.slice(0, textarea.selectionStart)}${pastedText}${textarea.value.slice(textarea.selectionEnd)}`;
    if (countTextLines(nextValue) > MAX_RAW_TEXT_LINES) {
      event.preventDefault();
      state.message = `Текст из буфера слишком длинный. Максимум ${MAX_RAW_TEXT_LINES} строк.`;
      renderApp();
    }
  });

  document.querySelector("textarea[name=raw_text]")?.addEventListener("input", (event) => {
    try {
      validateRawText(event.currentTarget.value);
      if (state.message?.includes("строк")) state.message = "";
    } catch (error) {
      state.message = error.message;
    }
    if (looksLikeSubtitleText(event.currentTarget.value)) {
      document.querySelector("select[name=type]").value = "srt";
    }
  });
}

function bindDocumentEvents() {
  document.querySelectorAll("[data-piece-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      pendingReaderScrollTop = document.querySelector(".document-reader")?.scrollTop ?? null;
      const piece = state.currentDocument.pieces[Number(button.dataset.pieceIndex)];
      const full = piece.type === "phrase"
        ? piece
        : state.currentDocument.analysis.words.find((word) => word.word_id === piece.word_id);
      const selected = { ...piece, ...(full || {}), type: piece.type };
      const status = selected.status === "known" ? "unknown" : "known";
      const kind = piece.type === "phrase" ? "phrase" : "word";
      const knowledgeId = piece.type === "phrase" ? selected.user_phrase_id : selected.user_word_id;
      if (!knowledgeId) {
        state.selectedWord = selected;
        renderApp();
        return;
      }
      await patchKnowledgeStatus(kind, knowledgeId, status);
      state.selectedWord = { ...selected, status };
      await ensureTranslation(kind, knowledgeId, state.selectedWord.translation_ru);
      renderApp();
    });
  });
}

function bindAnalysisEvents() {
  document.querySelectorAll("[data-cloud-kind]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.cloudKind;
      const id = button.dataset.cloudId;
      const nextStatus = button.dataset.cloudNextStatus || "known";
      state.selectedAnalysisKey = button.dataset.cloudKey || `${kind}:${id}`;
      await patchKnowledgeStatus(kind, id, nextStatus);
      await ensureTranslation(kind, id, localTranslation(kind, id));
      renderApp();
    });
  });

  document.querySelectorAll("[data-refresh-important]").forEach((button) => {
    button.addEventListener("click", async () => {
      const { analysis } = await api(`/api/documents/${button.dataset.refreshImportant}/analyze`, {
        method: "POST",
        body: { refresh_important: true }
      });
      state.currentAnalysis = analysis;
      state.analysisVisibleKeys = null;
      state.analysisVisibleDocId = button.dataset.refreshImportant;
      state.selectedAnalysisKey = null;
      renderApp();
    });
  });

  document.querySelectorAll("[data-analysis-to-learn]").forEach((button) => {
    button.addEventListener("click", async () => {
      const units = analysisUnitsForLearn(state.currentAnalysis);
      if (!units.length) {
        state.message = "В этом анализе нет новых слов для Learn.";
        renderApp();
        return;
      }
      await api("/api/learn/blocks", {
        method: "POST",
        body: { title: state.currentDocument?.title || "Analysis", units }
      });
      state.message = "Блок добавлен в Learn.";
      renderApp();
    });
  });
}

function bindKnowledgeEvents() {
  document.querySelector("#knowledgeGraphForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    state.knowledgeInput = data.text || "";
    state.knowledgeLoading = true;
    state.message = "";
    renderApp();
    try {
      const { contexts, context } = await api("/api/knowledge/analyze", { method: "POST", body: data });
      state.knowledgeContexts = contexts || [context];
      state.knowledgeContext = context;
      state.selectedKnowledgeKey = null;
      state.message = "";
    } catch (error) {
      state.message = error.message || "Не удалось сгенерировать словарь.";
    } finally {
      state.knowledgeLoading = false;
      renderApp();
    }
  });

  document.querySelector("[data-knowledge-to-learn]")?.addEventListener("click", async () => {
    const units = knowledgeUnitsForLearn(state.knowledgeContext);
    if (!units.length) {
      state.message = "В Theme Card нет новых слов для Learn.";
      renderApp();
      return;
    }
    await api("/api/learn/blocks", {
      method: "POST",
      body: { title: state.knowledgeInput || state.knowledgeContext?.title || "Knowledge", units }
    });
    state.message = "Блок добавлен в Learn.";
    renderApp();
  });

  document.querySelectorAll("[data-kg-bridge]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bridgeTopic = button.dataset.kgBridge || "";
      const bridgeId = button.dataset.kgBridgeId || "";
      state.knowledgeInput = bridgeTopic;
      state.knowledgeBridgeLoadingId = bridgeId;
      state.knowledgeLoading = true;
      state.message = "";
      renderApp();
      try {
        const { contexts, context } = await api("/api/knowledge/bridge", {
          method: "POST",
          body: {
            context_id: bridgeId || `kg:${bridgeTopic.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
            bridge_title: bridgeTopic,
            starter_words: [],
            document_id: state.knowledgeContext?.document_id || null
          }
        });
        state.knowledgeContexts = contexts || [context];
        state.knowledgeContext = context;
        state.selectedKnowledgeKey = null;
        state.message = "";
      } catch (error) {
        state.message = error.message || "Не удалось сгенерировать словарь.";
      } finally {
        state.knowledgeBridgeLoadingId = null;
        state.knowledgeLoading = false;
        renderApp();
      }
    });
  });

  document.querySelectorAll("[data-kg-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.kind === "phrase" ? "phrase" : "word";
      state.selectedKnowledgeKey = button.dataset.kgKey || null;
      await patchKnowledgeStatus(kind, button.dataset.kgStatus, button.dataset.status);
      applyKnowledgeContextStatus(kind, button.dataset.kgStatus, button.dataset.status);
      await ensureTranslation(kind, button.dataset.kgStatus, localTranslation(kind, button.dataset.kgStatus));
      renderApp();
    });
  });
}

function bindLearnEvents() {
  document.querySelectorAll("[data-learn-select]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selectedLearnBlockIds.add(input.dataset.learnSelect);
      else state.selectedLearnBlockIds.delete(input.dataset.learnSelect);
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-filter]").forEach((select) => {
    select.addEventListener("change", async () => {
      const { blocks } = await api(`/api/learn/blocks/${select.dataset.learnFilter}`, {
        method: "PATCH",
        body: { frequency_filter: select.value }
      }).then(async () => api("/api/learn"));
      state.learnBlocks = blocks || [];
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/learn/blocks/${button.dataset.learnDelete}`, { method: "DELETE" });
      state.selectedLearnBlockIds.delete(button.dataset.learnDelete);
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-anki]").forEach((button) => {
    button.addEventListener("click", async () => {
      const blockId = button.dataset.learnAnki;
      const block = (state.learnBlocks || []).find((item) => item.id === blockId);
      state.ankiGeneratingBlockId = blockId;
      state.message = "Идет генерация ANKI-файла...";
      renderApp();
      try {
        const response = await fetch(`/api/learn/blocks/${blockId}/anki`, {
          credentials: "same-origin",
          cache: "no-store"
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || data.detail || "Не удалось создать файл ANKI.");
        }
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${ankiFileName(block?.title || "learn_block")}_anki.txt`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
        state.message = "ANKI-файл готов и скачивание началось.";
      } catch (error) {
        state.message = error.message || "Не удалось создать файл ANKI.";
      } finally {
        state.ankiGeneratingBlockId = null;
        renderApp();
      }
    });
  });

  document.querySelectorAll("[data-learn-merge]").forEach((button) => {
    button.addEventListener("click", async () => {
      const block_ids = [...state.selectedLearnBlockIds];
      if (block_ids.length < 2) return;
      const { blocks } = await api("/api/learn/blocks/merge", {
        method: "POST",
        body: { block_ids }
      }).then(async () => api("/api/learn"));
      state.learnBlocks = blocks || [];
      state.selectedLearnBlockIds = new Set();
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.learnKind === "phrase" ? "phrase" : "word";
      const knowledgeId = button.dataset.learnStatus;
      state.selectedLearnKey = button.dataset.learnToken || `${kind}:${knowledgeId}`;
      await patchKnowledgeStatus(kind, knowledgeId, button.dataset.learnNextStatus || "known", { refreshAnalysis: true });
      await ensureTranslation(kind, knowledgeId, localTranslation(kind, knowledgeId));
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      const learnUnits = state.learnBlocks.flatMap((block) => block.units || []);
      if (!learnUnits.some((unit) => unitKey(unit) === state.selectedLearnKey)) {
        state.selectedLearnKey = learnUnits[0] ? unitKey(learnUnits[0]) : null;
      }
      renderApp();
    });
  });
}

function bindSettingsEvents() {
  document.querySelector("#settingsForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    data.native_language = state.user?.native_language || "ru";
    data.target_language = state.user?.target_language || "en";
    data.tts_enabled = form.querySelector("[name=tts_enabled]")?.checked ? "true" : "false";
    delete data.tts_preview_text;
    const { user } = await api("/api/settings", { method: "PATCH", body: data });
    state.user = normalizeUser(user);
    state.message = "Настройки сохранены.";
    renderApp();
  });

  document.querySelector("[data-tts-preview]")?.addEventListener("click", (event) => {
    event.preventDefault();
    const form = document.querySelector("#settingsForm");
    if (!form) return;
    const text = String(form.querySelector("[name=tts_preview_text]")?.value || "").trim();
    const tempSettings = {
      tts_enabled: form.querySelector("[name=tts_enabled]")?.checked ?? true,
      tts_voice: form.querySelector("[name=tts_voice]")?.value || "",
      tts_rate: form.querySelector("[name=tts_rate]")?.value,
      tts_pitch: form.querySelector("[name=tts_pitch]")?.value,
      tts_volume: form.querySelector("[name=tts_volume]")?.value,
    };
    speakText(text || "This is a voice preview.", tempSettings);
  });

  document.querySelector("#passwordForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const { user } = await api("/api/password/change", { method: "POST", body: data });
      state.user = normalizeUser(user);
      state.message = "Пароль изменён.";
    } catch (error) {
      state.message = error.message || "Не удалось сменить пароль.";
    }
    renderApp();
  });
}

function bindBillingEvents() {
  document.querySelector("[data-billing-checkout]")?.addEventListener("click", async () => {
    state.billingLoading = true;
    renderApp();
    try {
      const { confirmation_url } = await api("/api/billing/checkout", { method: "POST", body: {} });
      if (confirmation_url) {
        window.location.href = confirmation_url;
        return;
      }
      state.message = "Не удалось создать платёж.";
    } catch (error) {
      state.message = error.message || "Оплата временно недоступна.";
    } finally {
      state.billingLoading = false;
      renderApp();
    }
  });

  document.querySelector("[data-billing-cancel]")?.addEventListener("click", async () => {
    state.billingLoading = true;
    renderApp();
    try {
      await api("/api/billing/cancel", { method: "POST" });
      state.billing = await api("/api/billing/status");
      state.message = "Автопродление отключено.";
    } catch (error) {
      state.message = error.message || "Не удалось отменить подписку.";
    } finally {
      state.billingLoading = false;
      renderApp();
    }
  });
}

async function reloadAdminUsers() {
  const data = await api(`/api/admin/users?q=${encodeURIComponent(state.adminQuery || "")}`);
  state.adminUsers = data.users || [];
  state.adminUsersTotal = data.total || 0;
}

async function adminAction(userId, fn) {
  state.adminLoading = true;
  renderApp();
  try {
    await fn();
    await reloadAdminUsers();
    const stats = await api("/api/admin/stats");
    state.adminStats = stats.stats;
  } catch (error) {
    state.message = error.message || "Не удалось выполнить действие.";
  } finally {
    state.adminLoading = false;
    renderApp();
  }
}

function bindAdminEvents() {
  document.querySelector("[data-admin-ai-health]")?.addEventListener("click", async () => {
    state.adminLoading = true;
    renderApp();
    try {
      const { health } = await api("/api/admin/ai-health");
      state.adminAiHealth = health;
    } catch (error) {
      state.adminAiHealth = { ok: false, error: error.message || "Запрос не удался" };
    } finally {
      state.adminLoading = false;
      renderApp();
    }
  });

  const search = document.querySelector("#adminSearch");
  if (search) {
    search.addEventListener("change", async () => {
      state.adminQuery = search.value.trim();
      await reloadAdminUsers();
      state.adminSelectedUser = null;
      renderApp();
    });
  }

  document.querySelectorAll("[data-admin-user]").forEach((row) => {
    row.addEventListener("click", async () => {
      try {
        const { user } = await api(`/api/admin/users/${row.dataset.adminUser}`);
        state.adminSelectedUser = user;
      } catch (error) {
        state.message = error.message;
      }
      renderApp();
    });
  });

  const grant = document.querySelector("[data-admin-grant]");
  grant?.addEventListener("click", () => {
    const raw = document.querySelector("#adminPremiumUntil")?.value || "";
    const premiumUntil = raw ? new Date(raw).toISOString() : null;
    adminAction(grant.dataset.adminGrant, async () => {
      const { user } = await api(`/api/admin/users/${grant.dataset.adminGrant}/subscription`,
        { method: "PATCH", body: { plan: "premium", premium_until: premiumUntil } });
      state.adminSelectedUser = user;
    });
  });

  const revoke = document.querySelector("[data-admin-revoke]");
  revoke?.addEventListener("click", () => adminAction(revoke.dataset.adminRevoke, async () => {
    const { user } = await api(`/api/admin/users/${revoke.dataset.adminRevoke}/subscription`,
      { method: "PATCH", body: { plan: "free" } });
    state.adminSelectedUser = user;
  }));

  const block = document.querySelector("[data-admin-block]");
  block?.addEventListener("click", () => adminAction(block.dataset.adminBlock, async () => {
    const { user } = await api(`/api/admin/users/${block.dataset.adminBlock}/block`,
      { method: "PATCH", body: { blocked: true } });
    state.adminSelectedUser = user;
  }));

  const unblock = document.querySelector("[data-admin-unblock]");
  unblock?.addEventListener("click", () => adminAction(unblock.dataset.adminUnblock, async () => {
    const { user } = await api(`/api/admin/users/${unblock.dataset.adminUnblock}/block`,
      { method: "PATCH", body: { blocked: false } });
    state.adminSelectedUser = user;
  }));

  const reset = document.querySelector("[data-admin-reset]");
  reset?.addEventListener("click", () => adminAction(reset.dataset.adminReset, async () => {
    await api(`/api/admin/users/${reset.dataset.adminReset}/reset-password`, { method: "POST" });
    state.message = "Временный пароль отправлен пользователю.";
  }));
}

function restoreReaderScroll() {
  if (pendingReaderScrollTop !== null) {
    const reader = document.querySelector(".document-reader");
    if (reader) reader.scrollTop = pendingReaderScrollTop;
    pendingReaderScrollTop = null;
  }
}
