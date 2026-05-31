// Dashboard: document list with coverage stats.

import { state } from "../state.js";
import { escapeHtml } from "../utils.js";
import { renderHeader } from "./shell.js";

export function renderDashboard() {
  if (!state.dashboard) return `<div class="empty">Dashboard загружается...</div>`;
  const data = state.dashboard || { stats: {}, documents: [] };
  const stats = data.stats;
  return `
    ${renderHeader("Мои тексты", "Загрузите текст, отметьте знакомое и смотрите, как растет покрытие.", `<a data-link href="/upload"><button class="primary">+ Загрузить</button></a>`)}
    <section class="grid stats">
      ${metric("Тексты", stats.documents_count || 0)}
      ${metric("Словарь", stats.vocabulary_count || 0)}
      ${metric("В изучении", stats.learning_words || 0)}
      ${metric("Среднее покрытие", `${stats.average_coverage || 0}%`)}
    </section>
    <section class="card" style="margin-top:16px">
      <table class="table desktop-table">
        <thead><tr><th>Название</th><th>Тип</th><th>Слов</th><th>Уникальных</th><th>Покрытие</th><th></th></tr></thead>
        <tbody>
          ${data.documents.length ? data.documents.map((doc) => `
            <tr>
              <td><a data-link href="/document/${doc.id}">${escapeHtml(doc.title)}</a></td>
              <td>${escapeHtml(doc.type)}</td>
              <td>${doc.total_words}</td>
              <td>${doc.unique_words}</td>
              <td><span class="pill known">${doc.coverage_percent}%</span></td>
              <td class="toolbar"><a data-link href="/document/${doc.id}"><button>Открыть</button></a><button class="icon" data-delete-doc="${doc.id}" title="Удалить">×</button></td>
            </tr>`).join("") : `<tr><td colspan="6"><div class="empty">Пока нет текстов. Первый анализ начинается с кнопки “Загрузить”.</div></td></tr>`}
        </tbody>
      </table>
      <div class="mobile-card-list dashboard-mobile-list">
        ${data.documents.length ? data.documents.map((doc) => `
          <article class="mobile-list-card">
            <div>
              <h3><a data-link href="/document/${doc.id}">${escapeHtml(doc.title)}</a></h3>
              <p class="meta">${escapeHtml(doc.type)} · ${doc.total_words} слов · ${doc.unique_words} уникальных</p>
            </div>
            <div class="mobile-card-actions">
              <span class="pill known">${doc.coverage_percent}%</span>
              <a data-link href="/document/${doc.id}"><button>Открыть</button></a>
              <button class="icon" data-delete-doc="${doc.id}" title="Удалить">×</button>
            </div>
          </article>
        `).join("") : `<div class="empty">Пока нет текстов. Первый анализ начинается с кнопки “Загрузить”.</div>`}
      </div>
    </section>
  `;
}

function metric(label, value) {
  return `<div class="card metric"><span>${label}</span><strong>${value}</strong></div>`;
}
