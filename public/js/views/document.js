// Document reader view: annotated text pieces and the word-detail side panel.

import { state } from "../state.js";
import { cleanExample, cleanTranscription, cleanTranslation, escapeHtml, statusText, translationTooltip } from "../utils.js";
import { renderTtsButton } from "../tts.js";
import { renderHeader } from "./shell.js";
import { renderAiCard } from "./knowledge.js";

export function renderDocument() {
  const doc = state.currentDocument;
  if (!doc) return `<div class="empty">Документ загружается...</div>`;
  return `
    ${renderHeader(escapeHtml(doc.title), `Покрытие: ${doc.analysis.coverage_percent}% · Уникальное: ${doc.analysis.unique_coverage_percent}%`, renderDocumentViewSwitch(doc.id, "text"))}
    <section class="grid two document-workspace">
      <article class="card text-reader document-reader">
        ${doc.pieces.map((piece, index) => piece.type === "text"
          ? renderTextPiece(piece.value)
          : renderLanguagePiece(piece, index)).join("")}
      </article>
      <aside class="card side-panel word-detail">
        ${renderWordDetail(state.selectedWord)}
      </aside>
    </section>
  `;
}

export function renderDocumentViewSwitch(documentId, activeView) {
  return `
    <div class="view-switch" role="tablist" aria-label="Режим просмотра документа">
      <a data-link role="tab" aria-selected="${activeView === "text"}" class="${activeView === "text" ? "active" : ""}" href="/document/${documentId}">Текст</a>
      <a data-link role="tab" aria-selected="${activeView === "analysis"}" class="${activeView === "analysis" ? "active" : ""}" href="/document/${documentId}/analysis">Анализ</a>
    </div>
  `;
}

function renderWordDetail(word) {
  if (!word) return `<h2>Слово</h2><p class="subtle">Кликните по подсвеченному слову в тексте.</p>`;
  const isPhrase = word.type === "phrase";
  const label = isPhrase ? word.base_form : word.lemma;
  const translation = cleanTranslation(word.translation_ru);
  const transcription = cleanTranscription(word.transcription);
  const examples = cleanExample(word.example) ? [cleanExample(word.example)] : [];
  return `
    <div class="sheet-grabber" data-sheet-grabber aria-hidden="true"><span></span></div>
    <div class="detail-title">
      <h2>${escapeHtml(label)} <span class="pill status-${word.status}">${statusText(word.status)}</span></h2>
      ${renderTtsButton(label, `Озвучить ${label}`)}
    </div>
    ${translation ? `<p><strong>Перевод:</strong> ${escapeHtml(translation)}</p>` : ""}
    ${!isPhrase && transcription ? `<p><strong>Транскрипция:</strong> /${escapeHtml(transcription)}/</p>` : ""}
    ${examples.length ? `<div><strong>Пример в тексте:</strong><ul class="detail-examples">${examples.map((example) => `<li><span>${escapeHtml(example)}</span>${renderTtsButton(example, "Озвучить пример", "mini")}</li>`).join("")}</ul></div>` : ""}
    ${isPhrase ? `<p class="meta">Устойчивое выражение: ${escapeHtml(word.phrase_type || "phrase")}</p>` : ""}
    ${renderAiCard({ knowledge_id: isPhrase ? word.user_phrase_id : word.user_word_id, kind: isPhrase ? "phrase" : "word" })}
  `;
}

function renderTextPiece(value) {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function renderLanguagePiece(piece, index) {
  const label = piece.type === "phrase" ? piece.base_form : piece.lemma;
  const className = piece.type === "phrase" ? "phrase-token" : "word-token";
  const title = translationTooltip(piece.translation_ru);
  const kind = piece.type === "phrase" ? "phrase" : "word";
  const knowledgeId = piece.type === "phrase" ? piece.user_phrase_id : piece.user_word_id;
  return `<button class="${className} ${piece.status}" data-piece-index="${index}" data-tooltip-kind="${kind}" data-tooltip-id="${escapeHtml(knowledgeId || "")}" aria-label="${escapeHtml(label)}" title="${escapeHtml(title)}">${escapeHtml(piece.value)}</button>`;
}
