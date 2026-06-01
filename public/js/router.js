// Client-side routing: initial boot, navigation and per-route data loading.

import { api } from "./api.js";
import { state } from "./state.js";
import { normalizeUser, unitKey } from "./utils.js";
import { initTtsVoices } from "./tts.js";
import { renderApp } from "./views/shell.js";
import { renderAuth, renderLanding, renderPublicHelp } from "./views/static.js";

// Unauthenticated screens handled by renderAuth.
const AUTH_ROUTES = new Set(["/login", "/register", "/reset"]);

export async function boot() {
  try {
    const { user } = await api("/api/me");
    state.user = normalizeUser(user);
    initTtsVoices();
    if (AUTH_ROUTES.has(state.route)) await navigate("/dashboard");
    else if (state.route === "/") renderLanding();
    else await loadRoute();
  } catch {
    if (AUTH_ROUTES.has(state.route)) renderAuth();
    else if (state.route === "/help") renderPublicHelp();
    else renderLanding();
  }
}

export async function navigate(path) {
  window.history.pushState({}, "", path);
  await routeTo({ replaceAuth: true });
}

export function handlePopState() {
  routeTo({ replaceAuth: false });
}

// Shared guard logic for navigate() and back/forward. Returns once the correct
// view has been rendered (or data loading kicked off).
async function routeTo({ replaceAuth }) {
  state.route = window.location.pathname;
  if (state.user && AUTH_ROUTES.has(state.route)) {
    window.history.replaceState({}, "", "/dashboard");
    state.route = "/dashboard";
    await loadRoute();
    return;
  }
  if (!state.user && state.route === "/") {
    state.message = "";
    renderLanding();
    return;
  }
  if (!state.user && state.route === "/help") {
    state.message = "";
    renderPublicHelp();
    return;
  }
  if (!state.user && AUTH_ROUTES.has(state.route)) {
    state.message = "";
    if (state.route !== "/register") state.pendingRegistrationEmail = "";
    renderAuth();
    return;
  }
  await loadRoute();
}

export async function loadRoute() {
  state.message = "";
  try {
    if (state.route === "/") {
      renderLanding();
      return;
    }
    if (state.route === "/dashboard") {
      state.dashboard = await api("/api/dashboard");
    } else if (state.route === "/premium") {
      state.billing = await api("/api/billing/status");
    } else if (state.route === "/admin") {
      const [{ stats }, users] = await Promise.all([
        api("/api/admin/stats"),
        api(`/api/admin/users?q=${encodeURIComponent(state.adminQuery || "")}`),
      ]);
      state.adminStats = stats;
      state.adminUsers = users.users || [];
      state.adminUsersTotal = users.total || 0;
      state.adminSelectedUser = null;
    } else if (state.route === "/words") {
      const { words, phrases } = await api("/api/words");
      state.words = [...(words || []), ...(phrases || [])];
      state.wordsVisibleCount = 100;
    } else if (state.route === "/learn") {
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      const existingIds = new Set(state.learnBlocks.map((block) => block.id));
      state.selectedLearnBlockIds = new Set([...state.selectedLearnBlockIds].filter((id) => existingIds.has(id)));
      const learnUnits = state.learnBlocks.flatMap((block) => block.units || []);
      if (state.selectedLearnKey && !learnUnits.some((unit) => unitKey(unit) === state.selectedLearnKey)) {
        state.selectedLearnKey = null;
      }
    } else if (state.route === "/knowledge") {
      const params = new URLSearchParams(window.location.search);
      const hasExplicitContext = Boolean(params.get("document_id") || params.get("context_id"));
      const hasInputText = Boolean((state.knowledgeInput || "").trim());
      if (!hasExplicitContext && !hasInputText) {
        state.knowledgeContexts = [];
        state.knowledgeContext = null;
      } else if (hasExplicitContext || !state.knowledgeContext) {
        const suffix = params.get("document_id")
          ? `?document_id=${encodeURIComponent(params.get("document_id"))}`
          : params.get("context_id")
            ? `?context_id=${encodeURIComponent(params.get("context_id"))}`
            : "";
        const { contexts, context } = await api(`/api/knowledge${suffix}`);
        state.knowledgeContexts = contexts;
        state.knowledgeContext = context;
        state.knowledgeInput = state.knowledgeInput || "";
      }
    } else if (state.route.startsWith("/document/")) {
      const [, , id, view] = state.route.split("/");
      state.lastDocumentId = id;
      if (view === "analysis") {
        if (state.analysisDocumentId !== id) {
          state.selectedAnalysisKey = null;
          state.analysisVisibleKeys = null;
          state.analysisVisibleDocId = null;
        }
        const [{ document }, { analysis }] = await Promise.all([
          api(`/api/documents/${id}`),
          api(`/api/documents/${id}/analysis`)
        ]);
        state.analysisDocumentId = id;
        state.currentDocument = document;
        state.currentAnalysis = analysis;
      } else {
        const { document } = await api(`/api/documents/${id}`);
        state.currentDocument = document;
      }
    }
    renderApp();
  } catch (error) {
    state.message = error.message;
    renderApp();
  }
}
