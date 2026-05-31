// Desktop/Mobile UI-mode toggle and its rendered controls.
// `readUiMode` lives in state.js (evaluated at state-construction time).

import { state, UI_MODE_STORAGE_KEY } from "./state.js";
import { renderApp } from "./views/shell.js";

export function setUiMode(mode) {
  state.uiMode = mode === "mobile" ? "mobile" : "desktop";
  try {
    localStorage.setItem(UI_MODE_STORAGE_KEY, state.uiMode);
  } catch {
    // localStorage can be unavailable in restricted browser modes.
  }
  renderApp();
}

export function renderUiModeSwitch() {
  const mode = state.uiMode === "mobile" ? "mobile" : "desktop";
  return `
    <div class="ui-mode-switch" role="group" aria-label="Версия интерфейса">
      <button type="button" class="${mode === "desktop" ? "active" : ""}" data-ui-mode="desktop" aria-pressed="${mode === "desktop"}">Desktop</button>
      <button type="button" class="${mode === "mobile" ? "active" : ""}" data-ui-mode="mobile" aria-pressed="${mode === "mobile"}">Mobile</button>
    </div>
  `;
}

export function renderMobileModeButton() {
  const nextMode = state.uiMode === "mobile" ? "desktop" : "mobile";
  const label = state.uiMode === "mobile" ? "Desktop" : "Mobile";
  return `<button type="button" class="mobile-mode-nav-button" data-ui-mode="${nextMode}" title="${label}"><span>⇄</span><small>${label}</small></button>`;
}
