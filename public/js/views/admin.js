// Admin panel: platform metrics, user search/list and per-user actions
// (subscription, block/unblock, password reset).

import { state } from "../state.js";
import { escapeHtml } from "../utils.js";
import { renderHeader } from "./shell.js";

const STAT_CARDS = [
  ["users_total", "Пользователи"],
  ["premium_active", "Premium активных"],
  ["blocked", "Заблокировано"],
  ["documents_total", "Документы"],
  ["learning_words", "Слов в изучении"],
  ["known_words", "Изучено слов"],
  ["payments_succeeded", "Платежей"],
  ["revenue_rub", "Выручка ₽"],
];

export function renderAdmin() {
  const stats = state.adminStats || {};
  const users = state.adminUsers || [];
  const selected = state.adminSelectedUser;
  return `
    ${renderHeader("Администрирование", "Метрики платформы и управление пользователями.")}
    <section class="grid stats admin-stats">
      ${STAT_CARDS.map(([key, label]) => metric(label, formatStat(stats[key]))).join("")}
    </section>
    <section class="admin-layout">
      <div class="card admin-users">
        <div class="section-title">
          <h2>Пользователи <span class="pill">${state.adminUsersTotal}</span></h2>
          <input type="search" id="adminSearch" placeholder="Поиск по email..." value="${escapeHtml(state.adminQuery || "")}">
        </div>
        <table class="table desktop-table">
          <thead><tr><th>Email</th><th>План</th><th>Док.</th><th>Словарь</th><th>Статус</th></tr></thead>
          <tbody>
            ${users.length ? users.map(renderUserRow).join("") : `<tr><td colspan="5"><div class="empty">Не найдено.</div></td></tr>`}
          </tbody>
        </table>
      </div>
      <aside class="card admin-detail">
        ${renderUserDetail(selected)}
      </aside>
    </section>
  `;
}

function renderUserRow(user) {
  const status = user.is_blocked ? "ignored" : user.is_premium ? "known" : "unknown";
  const label = user.is_blocked ? "блок" : user.is_premium ? "premium" : "free";
  return `
    <tr class="admin-user-row" data-admin-user="${escapeHtml(user.id)}">
      <td>${escapeHtml(user.email)}${user.is_admin ? ` <span class="pill">admin</span>` : ""}</td>
      <td>${escapeHtml(user.plan || "free")}</td>
      <td>${user.documents_count ?? 0}</td>
      <td>${user.vocabulary_count ?? 0}</td>
      <td><span class="pill status-${status}">${label}</span></td>
    </tr>`;
}

function renderUserDetail(user) {
  if (!user) return `<h2>Пользователь</h2><p class="subtle">Выберите пользователя в списке слева.</p>`;
  const loading = state.adminLoading;
  return `
    <div class="detail-title"><h2>${escapeHtml(user.email)}</h2></div>
    <p class="subtle">ID: ${escapeHtml(user.id)} · создан ${escapeHtml(formatDate(user.created_at))}</p>
    <p>План: <strong>${escapeHtml(user.plan || "free")}</strong>${
      user.premium_until ? ` · до ${escapeHtml(formatDate(user.premium_until))}` : ""
    } · ${user.is_premium ? "premium активен" : "free"}</p>
    <p>Статус входа: <strong>${user.is_blocked ? "заблокирован" : "активен"}</strong></p>

    <div class="admin-actions" ${loading ? "data-loading" : ""}>
      <div class="admin-action-row">
        <label class="label">Premium до (необязательно)
          <input type="datetime-local" id="adminPremiumUntil">
        </label>
        <button class="primary" data-admin-grant="${escapeHtml(user.id)}" ${loading ? "disabled" : ""}>Выдать Premium</button>
        <button data-admin-revoke="${escapeHtml(user.id)}" ${loading ? "disabled" : ""}>Снять Premium</button>
      </div>
      <div class="admin-action-row">
        ${user.is_blocked
          ? `<button data-admin-unblock="${escapeHtml(user.id)}" ${loading ? "disabled" : ""}>Разблокировать</button>`
          : `<button data-admin-block="${escapeHtml(user.id)}" ${loading ? "disabled" : ""}>Заблокировать</button>`}
        <button data-admin-reset="${escapeHtml(user.id)}" ${loading ? "disabled" : ""}>Сбросить пароль</button>
      </div>
    </div>
  `;
}

function metric(label, value) {
  return `<div class="card metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function formatStat(value) {
  if (value == null) return "0";
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  return String(value);
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("ru-RU");
}
