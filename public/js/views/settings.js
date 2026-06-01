// Settings view: account info, TTS configuration, and (on mobile) the relocated
// Help / Words / Desktop menu.

import { state } from "../state.js";
import { escapeHtml, formatRangeValue, normalizeUser } from "../utils.js";
import { ttsVoiceOptions } from "../tts.js";
import { renderHeader } from "./shell.js";

export function renderSettings() {
  const user = normalizeUser(state.user || {});
  const voices = ttsVoiceOptions(user.target_language);
  const isPremium = Boolean(state.user?.is_premium);
  const mustChange = Boolean(state.user?.must_change_password);
  const premiumBadge = isPremium
    ? `<span class="pill known">Premium</span>`
    : `<a data-link href="/premium"><button class="primary">Оформить Premium</button></a>`;
  return `
    ${renderHeader("Настройки", "Языки MVP и учетная запись.")}
    ${mustChange ? `<section class="card notice must-change-banner">Вы вошли по временному паролю. Смените его ниже.</section>` : ""}
      ${state.uiMode === "mobile" ? `<section class="card settings-card"><h2 class="settings-menu-title">Меню</h2><div class="settings-menu"><a class="settings-menu-link" data-link href="/premium"><span class="nav-icon">★</span><span>Premium</span></a><a class="settings-menu-link" data-link href="/help"><span class="nav-icon">?</span><span>Help</span></a><a class="settings-menu-link" data-link href="/words"><span class="nav-icon">≡</span><span>Words</span></a><button type="button" class="settings-menu-link" data-ui-mode="desktop"><span class="nav-icon">🖥</span><span>Desktop</span></button></div></section>` : ""}
    <section class="card settings-card subscription-row">
      <div><h2 class="settings-menu-title">Подписка</h2><p class="subtle">${isPremium ? "Premium активен — ИИ-функции включены." : "Бесплатный план."}</p></div>
      <div class="toolbar">${premiumBadge}</div>
    </section>
    <form class="card form" id="settingsForm">
      <label class="label">Email<input value="${escapeHtml(state.user.email)}" disabled></label>
      <div class="form-row">
        <label class="label">Родной язык<input value="${escapeHtml(state.user.native_language)}" disabled></label>
        <label class="label">Изучаемый язык<input value="${escapeHtml(state.user.target_language)}" disabled></label>
        <span></span>
      </div>
      <label class="checkbox-control">
        <input type="checkbox" name="tts_enabled" ${user.tts_enabled ? "checked" : ""}>
        <span>Включить TTS</span>
      </label>
      <label class="label">Голос
        <select name="tts_voice">
          <option value="">Авто (по языку)</option>
          ${voices.map((voice) => `<option value="${escapeHtml(voice.voiceURI)}" ${voice.voiceURI === user.tts_voice ? "selected" : ""}>${escapeHtml(`${voice.name} (${voice.lang})`)}</option>`).join("")}
        </select>
      </label>
      <div class="tts-grid">
        <label class="label">Скорость
          <div class="range-control">
            <input type="range" name="tts_rate" min="0.5" max="2" step="0.05" value="${Number(user.tts_rate || 1).toFixed(2)}" data-range-name="tts_rate">
            <span class="range-value" data-range-value="tts_rate">${formatRangeValue(user.tts_rate)}</span>
          </div>
        </label>
        <label class="label">Тон
          <div class="range-control">
            <input type="range" name="tts_pitch" min="0.5" max="2" step="0.05" value="${Number(user.tts_pitch || 1).toFixed(2)}" data-range-name="tts_pitch">
            <span class="range-value" data-range-value="tts_pitch">${formatRangeValue(user.tts_pitch)}</span>
          </div>
        </label>
        <label class="label">Громкость
          <div class="range-control">
            <input type="range" name="tts_volume" min="0" max="1" step="0.05" value="${Number(user.tts_volume || 1).toFixed(2)}" data-range-name="tts_volume">
            <span class="range-value" data-range-value="tts_volume">${formatRangeValue(user.tts_volume)}</span>
          </div>
        </label>
      </div>
      <label class="label">Тестовая фраза<input name="tts_preview_text" value="This is a TTS preview for your settings."></label>
      <div class="toolbar">
        <button type="button" data-tts-preview>▶ Проверить голос</button>
      </div>
      <button class="primary">Сохранить</button>
      <div class="settings-account-actions">
        <button type="button" class="ghost" data-logout>Выйти</button>
      </div>
    </form>
    <form class="card form" id="passwordForm">
      <h2 class="settings-menu-title">Смена пароля</h2>
      <label class="label">Текущий пароль<input name="current_password" type="password" autocomplete="current-password" required></label>
      <label class="label">Новый пароль<input name="new_password" type="password" autocomplete="new-password" minlength="4" required></label>
      <button class="primary">Сменить пароль</button>
    </form>
  `;
}
