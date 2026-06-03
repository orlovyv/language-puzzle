// Knowledge Graph view: Theme Card input, bridge topics, vocabulary tokens.

import { state } from "../state.js";
import {
  cleanExample,
  cleanTranscription,
  cleanTranslation,
  escapeHtml,
  isShortWord,
  posLabel,
  statusText,
  translationTooltip,
  unitKey,
} from "../utils.js";
import { renderTtsButton } from "../tts.js";
import { renderHeader } from "./shell.js";

export function renderKnowledge() {
  const context = state.knowledgeContext;
  const units = context?.units || [];
  const phrases = units.filter((item) => item.kind === "phrase");
  const selected = units.find((item) => unitKey(item) === state.selectedKnowledgeKey) || null;
  const sourceValue = state.knowledgeInput || "";
  const bridgeLoadingId = state.knowledgeBridgeLoadingId || "";
  const isKnowledgeLoading = Boolean(state.knowledgeLoading);
  return `
    ${renderHeader("Knowledge Graph Mode", "Текст или тема превращается в Theme Card, мосты и личный граф слов.", "")}
    <section class="kg-mode">
      <div class="kg-main">
        <section class="card kg-input-card">
          <div class="section-title">
            <h2>Input</h2>
            <span class="pill">semantic + frequency</span>
          </div>
          <form class="kg-form" id="knowledgeGraphForm">
            <textarea name="text" spellcheck="false" placeholder="Airport travel, job interview, cooking at home или вставьте кусок текста..." ${isKnowledgeLoading ? "disabled" : ""}>${escapeHtml(sourceValue)}</textarea>
            <div class="toolbar">
              <button class="primary" ${isKnowledgeLoading ? "disabled" : ""}>${isKnowledgeLoading ? "Generating..." : "Generate vocabulary"}</button>
              ${context ? `<button type="button" data-knowledge-to-learn>В Learn</button>` : ""}
            </div>
            ${isKnowledgeLoading ? `<p class="subtle">Идет расчет словаря, подождите...</p>` : ""}
          </form>
        </section>

        ${context ? `
        <section class="card kg-bridge-card">
          <div class="section-title">
            <h2>Bridge topics</h2>
          </div>
          <div class="kg-bridges">
            ${(context.bridges || []).map((bridge) => `
              <button data-kg-bridge-id="${escapeHtml(bridge.id || "")}" data-kg-bridge="${escapeHtml(bridge.title)}" title="${escapeHtml(bridge.description || "")}" ${bridgeLoadingId && bridgeLoadingId === (bridge.id || "") ? "disabled" : ""}>
                <strong>${escapeHtml(bridge.title)}</strong>
                ${bridge.description ? `<span class="kg-bridge-reason">${escapeHtml(bridge.description)}</span>` : ""}
              </button>
            `).join("") || `<span class="meta">Мосты появятся после генерации.</span>`}
          </div>
        </section>

        <section class="knowledge-layout">
          <section class="card kg-theme-card">
            <div>
              <p class="meta">Theme Card</p>
              <h2>${escapeHtml(context.title)}</h2>
              <p class="subtle">${context.known_count || 0} знакомо · ${context.unknown_count || 0} новых · ${phrases.length} фраз</p>
            </div>
            <div>
              <h3>Vocabulary</h3>
              <div class="word-cloud kg-vocabulary">
                ${units.length ? units.slice(0, 30).map((item) => renderKnowledgeToken(item, selected)).join("") : `<p class="subtle">Пока нет слов. Запустите генерацию.</p>`}
              </div>
            </div>
          </section>
          <aside class="card side-panel word-detail analysis-detail">
            ${renderKnowledgeDetail(selected)}
          </aside>
        </section>` : `<section class="card"><div class="empty">Введите тему или текст и нажмите Generate vocabulary.</div></section>`}
      </div>
    </section>
  `;
}

function renderKnowledgeToken(item, selected) {
  const kind = item.kind === "phrase" ? "phrase" : "word";
  const status = item.status || "unknown";
  const active = selected && unitKey(item) === unitKey(selected);
  const nextStatus = status === "known" ? "unknown" : "known";
  const isAi = item.source === "ai";
  // For AI-picked words, prefer the AI explanation as the tooltip.
  const tip = isAi && item.why ? item.why : translationTooltip(item.translation_ru);
  return `
    <button
      class="cloud-token ${status} ${active ? "active" : ""} ${isAi ? "ai-pick" : ""}"
      data-kg-key="${escapeHtml(unitKey(item))}"
      data-kg-status="${item.knowledge_id}"
      data-kind="${kind}"
      data-status="${nextStatus}"
      data-tooltip-kind="${kind}"
      data-tooltip-id="${escapeHtml(item.knowledge_id || "")}"
      title="${escapeHtml(tip)}"
    >${escapeHtml(item.text)}${isAi ? `<sup class="ai-badge" title="Подобрано ИИ">AI</sup>` : ""}</button>
  `;
}

export function renderKnowledgeDetail(item) {
  if (!item) return `<h2>Слово</h2><p class="subtle">Кликни по слову или фразе в Theme Card.</p>`;
  const transcription = cleanTranscription(item.transcription);
  const example = cleanExample(item.example);
  const translation = cleanTranslation(item.translation_ru);
  const translationLoading = state.translationLoadingIds.has(item.knowledge_id);
  const translationFailed = state.translationFailedIds.has(item.knowledge_id);
  return `
    <div class="detail-title">
      <h2>${escapeHtml(item.text)} <span class="pill status-${item.status || "unknown"}">${statusText(item.status || "unknown")}</span></h2>
      ${renderTtsButton(item.text, `Озвучить ${item.text}`)}
    </div>
    ${translation ? `<p><strong>Перевод:</strong> ${escapeHtml(translation)}</p>` : ""}
    ${!translation && translationLoading ? `<p class="subtle">Загружаю перевод...</p>` : ""}
    ${!translation && translationFailed ? `<p class="subtle">Перевод пока не найден.</p>` : ""}
    ${item.kind === "word" && transcription ? `<p><strong>Транскрипция:</strong> /${escapeHtml(transcription)}/</p>` : ""}
    ${item.kind === "word"
      ? `<p class="meta">Часть речи: ${escapeHtml(posLabel(item.part_of_speech))}</p>`
      : `<p class="meta">Устойчивое выражение / фразовый глагол</p>`}
    ${item.source === "ai" && item.why ? `<p class="meta ai-why">✦ ИИ: ${escapeHtml(item.why)}</p>` : ""}
    ${example ? `<div><strong>Пример:</strong><ul class="detail-examples"><li><span>${escapeHtml(example)}</span>${renderTtsButton(example, "Озвучить пример", "mini")}</li></ul></div>` : ""}
    ${renderAiCard(item)}
  `;
}

// Premium-only AI hints (synonyms / mnemonic / context), loaded on demand.
export function renderAiCard(item) {
  if (!item || !item.knowledge_id) return "";
  if (!(state.user?.is_premium || state.user?.is_admin)) return "";
  const kind = item.kind === "phrase" ? "phrase" : "word";
  const card = state.aiCards?.[item.knowledge_id];
  const loading = state.aiCardLoadingIds?.has(item.knowledge_id);
  if (card) {
    return `
      <div class="ai-card">
        <p class="meta ai-card-title">AI-подсказки</p>
        ${card.translation_ru ? `<p><strong>AI-перевод:</strong> ${escapeHtml(card.translation_ru)}</p>` : ""}
        ${card.synonyms?.length ? `<p><strong>Синонимы:</strong> ${escapeHtml(card.synonyms.join(", "))}</p>` : ""}
        ${card.mnemonic ? `<p><strong>Мнемоника:</strong> ${escapeHtml(card.mnemonic)}</p>` : ""}
        ${card.context ? `<p class="subtle">${escapeHtml(card.context)}</p>` : ""}
      </div>`;
  }
  return `<button data-ai-card="${escapeHtml(item.knowledge_id)}" data-ai-kind="${kind}" ${loading ? "disabled" : ""}>${loading ? "Загрузка..." : "✦ AI-подсказки"}</button>`;
}

// Builds Learn-ready units from the current Theme Card context.
export function knowledgeUnitsForLearn(context) {
  return (context?.units || [])
    .map((unit) => ({
      id: unit.id,
      knowledge_id: unit.knowledge_id,
      kind: unit.kind === "phrase" ? "phrase" : "word",
      text: unit.text,
      base_form: unit.base_form || unit.text,
      translation_ru: cleanTranslation(unit.translation_ru),
      transcription: cleanTranscription(unit.transcription),
      part_of_speech: unit.part_of_speech || (unit.kind === "phrase" ? "phrase" : "word"),
      status: unit.status,
      example: cleanExample(unit.example),
      count: Number(unit.count || 1),
      frequency_rank: Number(unit.frequency_rank || 999999),
      score: Number(unit.score || 0),
    }))
    .filter((unit) => unit.knowledge_id && unit.text && unit.status !== "known" && unit.status !== "ignored" && !isShortWord(unit.text));
}
