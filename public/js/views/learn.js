// Learn view: study blocks with frequency filtering and per-unit tokens.

import { state } from "../state.js";
import { escapeHtml, learnFrequencyRank, statusText, translationTooltip, unitKey } from "../utils.js";
import { renderHeader } from "./shell.js";
import { renderKnowledgeDetail } from "./knowledge.js";

export function renderLearn() {
  const blocks = state.learnBlocks || [];
  const selectedCount = [...state.selectedLearnBlockIds].filter((id) => blocks.some((block) => block.id === id)).length;
  const allUnits = blocks.flatMap((block) => block.units || []);
  const selected = allUnits.find((unit) => unitKey(unit) === state.selectedLearnKey) || allUnits[0] || null;
  if (selected) state.selectedLearnKey = unitKey(selected);
  return `
    ${renderHeader("Learn", "Блоки слов для изучения.", selectedCount > 1 ? `<button class="primary" data-learn-merge>Объединить</button>` : "")}
    <section class="learn-layout">
      <div class="learn-board">
        ${blocks.length ? blocks.map((block) => renderLearnBlock(block, selectedCount, selected)).join("") : `<section class="card"><div class="empty">Пока нет блоков. Добавьте слова из Analysis или Knowledge.</div></section>`}
      </div>
      <aside class="card side-panel word-detail analysis-detail">
        ${renderLearnDetail(selected)}
      </aside>
    </section>
  `;
}

function renderLearnBlock(block, selectedCount, selectedUnit) {
  const selected = state.selectedLearnBlockIds.has(block.id);
  const filter = block.frequency_filter || "all";
  const units = filterLearnUnits(block.units || [], filter);
  const isAnkiGenerating = state.ankiGeneratingBlockId === block.id;
  return `
    <section class="card kg-theme-card learn-block">
      <div class="learn-block-head">
        <label class="learn-select-button ${selected ? "active" : ""}" title="Объединить блоки">
          <input type="checkbox" data-learn-select="${escapeHtml(block.id)}" ${selected ? "checked" : ""}>
          <span>✓</span>
        </label>
        <div class="toolbar">
          ${selectedCount > 1 && selected ? `<button class="primary" data-learn-merge>Объединить</button>` : ""}
          <button data-learn-delete="${escapeHtml(block.id)}">Удалить блок</button>
        </div>
      </div>
      <div>
        <h2>${escapeHtml(block.title)}</h2>
        <p class="subtle">${(block.units || []).length} слов · показано ${units.length}</p>
      </div>
      <div class="learn-filter-row">
        <label class="label learn-filter">Частотность
          <select data-learn-filter="${escapeHtml(block.id)}">
            ${learnFilterOptions().map(([value, label, description]) => `<option value="${value}" ${filter === value ? "selected" : ""}>${label} - ${description}</option>`).join("")}
          </select>
        </label>
        <button data-learn-anki="${escapeHtml(block.id)}" ${isAnkiGenerating ? "disabled" : ""}>${isAnkiGenerating ? "Генерация..." : "ANKI Generator"}</button>
      </div>
      ${isAnkiGenerating ? `<p class="notice learn-anki-notice">Идет генерация ANKI-файла и перевод примеров...</p>` : ""}
      <div>
        <h3>Vocabulary</h3>
        <div class="word-cloud kg-vocabulary">
          ${units.length ? units.map((item) => renderLearnToken(item, selectedUnit)).join("") : `<p class="subtle">В выбранном диапазоне пока пусто.</p>`}
        </div>
      </div>
    </section>
  `;
}

function renderLearnToken(item, selected) {
  const status = item.status || "unknown";
  const kind = item.kind === "phrase" ? "phrase" : "word";
  const active = selected && unitKey(item) === unitKey(selected);
  const nextStatus = status === "known" ? "unknown" : "known";
  return `
    <button
      class="cloud-token learn-token ${status} ${active ? "active" : ""}"
      data-learn-token="${escapeHtml(unitKey(item))}"
      data-learn-status="${escapeHtml(item.knowledge_id)}"
      data-learn-kind="${kind}"
      data-learn-next-status="${nextStatus}"
      data-tooltip-kind="${kind}"
      data-tooltip-id="${escapeHtml(item.knowledge_id || "")}"
      title="${escapeHtml(translationTooltip(item.translation_ru))}"
    >${escapeHtml(item.text)}</button>
  `;
}

function renderLearnDetail(item) {
  if (!item) return `<h2>Слово</h2><p class="subtle">Кликни по слову или фразе в блоке Learn.</p>`;
  return renderKnowledgeDetail(item);
}

function learnFilterOptions() {
  return [
    ["20-80", "20-80", "Самые полезные и частые слова"],
    ["50-50", "50-50", "50% самых частотных слов"],
    ["all", "Все", "Все слова блока"],
  ];
}

export function filterLearnUnits(units, filter) {
  const sorted = [...(units || [])].sort((a, b) => learnFrequencyRank(a) - learnFrequencyRank(b) || String(a.text || "").localeCompare(String(b.text || "")));
  if (filter === "all" || !sorted.length) return sorted;
  if (filter === "20-80") return sorted.slice(0, Math.ceil(sorted.length * 0.2));
  if (filter === "50-50") return sorted.slice(0, Math.ceil(sorted.length * 0.5));
  return sorted;
}
