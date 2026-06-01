// Application shell: the logged-in chrome (sidebar, mobile bottom nav), route
// dispatch and the shared section header. `renderApp` is the central re-render
// entry point used across the app.

import { routes, state } from "../state.js";
import { escapeHtml } from "../utils.js";
import { renderUiModeSwitch } from "../uimode.js";
import { bindRoute } from "../events.js";
import { renderDashboard } from "./dashboard.js";
import { renderUpload } from "./upload.js";
import { renderDocument } from "./document.js";
import { renderAnalysis } from "./analysis.js";
import { renderKnowledge } from "./knowledge.js";
import { renderLearn } from "./learn.js";
import { renderWords } from "./words.js";
import { renderSettings } from "./settings.js";
import { renderBilling } from "./billing.js";
import { renderAdmin } from "./admin.js";
import { renderLanding, renderHelp } from "./static.js";

const app = document.querySelector("#app");

export function renderApp() {
  const isMobileMode = state.uiMode === "mobile";
  app.innerHTML = `
    <div class="shell ${isMobileMode ? "mobile-mode" : "desktop-mode"}">
      <aside class="sidebar">
        <a class="brand" data-link href="/">Language Puzzle</a>
        ${renderUiModeSwitch()}
        <nav class="nav">
          ${renderNavigationLinks("desktop")}
        </nav>
        <div class="userline">
          <div>${escapeHtml(state.user?.email || "")}</div>
        </div>
      </aside>
      <main class="main ${isDocumentReaderRoute() ? "document-main" : ""}">
        ${state.message ? `<p class="notice">${escapeHtml(state.message)}</p>` : ""}
        ${renderRoute()}
      </main>
      <nav class="mobile-bottom-nav" aria-label="Mobile navigation">
        ${renderNavigationLinks("mobile")}
      </nav>
    </div>
  `;
  bindRoute();
}

function isNavRouteActive(path) {
  if (state.route === path) return true;
  return path === "/dashboard" && state.route.startsWith("/document/");
}

function navigationItems() {
  const documentId = currentDocumentIdFromRoute() || state.lastDocumentId || state.dashboard?.documents?.[0]?.id || "";
  const textPath = documentId ? `/document/${documentId}` : "";
  const analysisPath = documentId ? `/document/${documentId}/analysis` : "";
  return [
    routes[0],
    [textPath, "Текст", "T", !documentId],
    [analysisPath, "Анализ", "A", !documentId],
    ...routes.slice(1)
  ];
}

export function renderNavigationLinks(variant = "desktop") {
  const isAdmin = Boolean(state.user?.is_admin);
  return navigationItems()
    .filter(([path]) => path !== "/admin" || isAdmin)
    .filter(([path]) => variant !== "mobile" || !["/help", "/words", "/premium", "/admin"].includes(path))
    .map(([path, label, icon, disabled]) => {
    const active = isNavigationItemActive(path);
    const content = variant === "mobile"
      ? `<span>${icon}</span><small>${label}</small>`
      : `<span>${icon}</span> ${label}`;
    if (disabled) {
      return `<span class="nav-disabled" title="Сначала откройте текст из Dashboard">${content}</span>`;
    }
    return `<a data-link class="${active ? "active" : ""}" href="${path}" title="${label}">${content}</a>`;
  }).join("");
}

function isNavigationItemActive(path) {
  if (path.includes("/document/")) return state.route === path;
  if (path === "/dashboard" && currentDocumentIdFromRoute()) return false;
  return isNavRouteActive(path);
}

export function currentDocumentIdFromRoute() {
  if (!state.route.startsWith("/document/")) return "";
  return state.route.split("/")[2] || "";
}

export function isDocumentReaderRoute() {
  return state.route.startsWith("/document/") && !state.route.endsWith("/analysis");
}

function renderRoute() {
  if (state.route === "/") return renderLanding();
  if (state.route === "/dashboard") return renderDashboard();
  if (state.route === "/upload") return renderUpload();
  if (state.route === "/knowledge") return renderKnowledge();
  if (state.route === "/learn") return renderLearn();
  if (state.route === "/words") return renderWords();
  if (state.route === "/premium") return renderBilling();
  if (state.route === "/admin") return renderAdmin();
  if (state.route === "/help") return renderHelp();
  if (state.route === "/settings") return renderSettings();
  if (state.route.startsWith("/document/") && state.route.endsWith("/analysis")) return renderAnalysis();
  if (state.route.startsWith("/document/")) return renderDocument();
  return renderDashboard();
}

export function renderHeader(title, subtitle, actions = "") {
  return `<div class="topbar"><div><h1>${title}</h1><p class="subtle">${subtitle}</p></div><div class="toolbar">${actions}</div></div>`;
}
