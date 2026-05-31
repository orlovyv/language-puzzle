// Premium subscription screen: plan status, checkout and cancellation.

import { state } from "../state.js";
import { escapeHtml } from "../utils.js";
import { renderHeader } from "./shell.js";

const AI_FEATURES = [
  "AI-переводы с учётом контекста и части речи",
  "Сгенерированные примеры предложений с переводом",
  "AI-подбор тематической лексики в Knowledge Graph",
  "Обогащённые Anki-карточки: мнемоники, синонимы, контекст",
];

export function renderBilling() {
  const data = state.billing;
  if (!data) return `<div class="empty">Загрузка...</div>`;
  const status = data.status || {};
  const isPremium = status.is_premium;
  const price = data.price_rub;
  const period = data.period_days;
  const loading = state.billingLoading;

  const statusLine = isPremium
    ? `<p class="subtle">Подписка активна до <strong>${escapeHtml(formatDate(status.premium_until))}</strong>${
        status.auto_renew ? " · автопродление включено" : " · автопродление отключено"
      }</p>`
    : `<p class="subtle">У вас бесплатный план. Оформите Premium, чтобы включить ИИ-функции.</p>`;

  const action = !data.available
    ? `<p class="notice">Оплата временно недоступна.</p>`
    : isPremium
      ? (status.auto_renew
          ? `<button data-billing-cancel ${loading ? "disabled" : ""}>${loading ? "..." : "Отменить автопродление"}</button>`
          : `<button class="primary" data-billing-checkout ${loading ? "disabled" : ""}>${loading ? "..." : "Возобновить автопродление"}</button>`)
      : `<button class="primary" data-billing-checkout ${loading ? "disabled" : ""}>${loading ? "Переход к оплате..." : `Оформить за ${price} ₽ / ${period} дн.`}</button>`;

  return `
    ${renderHeader("Premium", "ИИ-функции для более качественного изучения языка.")}
    <section class="card premium-card">
      <div class="premium-status ${isPremium ? "is-premium" : ""}">
        <h2>${isPremium ? "Premium активен" : "Бесплатный план"}</h2>
        ${statusLine}
      </div>
      <ul class="premium-features">
        ${AI_FEATURES.map((f) => `<li>${escapeHtml(f)}</li>`).join("")}
      </ul>
      <div class="toolbar">${action}</div>
      ${(data.payments || []).length ? `
        <h3 class="premium-history-title">История платежей</h3>
        <table class="table desktop-table premium-history">
          <thead><tr><th>Дата</th><th>Сумма</th><th>Статус</th></tr></thead>
          <tbody>
            ${data.payments.map((p) => `<tr><td>${escapeHtml(formatDate(p.created_at))}</td><td>${escapeHtml(String(p.amount))} ${escapeHtml(p.currency || "RUB")}</td><td>${escapeHtml(p.status)}</td></tr>`).join("")}
          </tbody>
        </table>` : ""}
    </section>
  `;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("ru-RU");
}
