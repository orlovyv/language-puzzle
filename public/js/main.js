// Application entry point: global listeners (link interception, back/forward,
// UI-mode and logout buttons) and the initial boot.

import { api } from "./api.js";
import { state } from "./state.js";
import { setUiMode } from "./uimode.js";
import { boot, handlePopState, navigate } from "./router.js";
import { renderAuth } from "./views/static.js";

// Intercept internal navigation links anywhere in the app.
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-link]");
  if (!link) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});

// UI-mode (Desktop/Mobile) toggles — delegated so they work in the sidebar,
// mobile bottom nav and the relocated Settings menu without re-binding.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ui-mode]");
  if (!button) return;
  setUiMode(button.dataset.uiMode);
});

// Logout buttons — delegated for the same reason.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-logout]");
  if (!button) return;
  await api("/api/logout", { method: "POST" });
  state.user = null;
  state.route = "/login";
  window.history.pushState({}, "", "/login");
  renderAuth();
});

window.addEventListener("popstate", handlePopState);

boot();
