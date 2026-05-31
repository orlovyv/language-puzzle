// Words view: the user's consolidated "known" vocabulary with pagination.

import { state } from "../state.js";
import { cleanTranscription, escapeHtml, isShortWord, statusText } from "../utils.js";
import { renderHeader } from "./shell.js";

export function renderWords() {
  const rows = state.words || [];
  const words = rows
    .map((item) => {
      if (item.word) {
        return {
          label: item.word.lemma,
          part_of_speech: item.word.part_of_speech,
          translation_ru: item.word.translation_ru,
          transcription: item.word.transcription,
          status: item.status
        };
      }
      if (item.phrase) {
        return {
          label: item.phrase.base_form || item.phrase.phrase,
          part_of_speech: "phrase",
          translation_ru: item.phrase.translation_ru,
          transcription: "",
          status: item.status
        };
      }
      return null;
    })
    .filter(
      (item) =>
        item &&
        item.status === "known" &&
        (item.part_of_speech === "phrase" || !isShortWord(item.label))
    );
  const visibleCount = Math.max(100, Number(state.wordsVisibleCount || 100));
  const visibleWords = words.slice(0, visibleCount);
  const hasMoreWords = visibleWords.length < words.length;
  return `
    ${renderHeader("Общий словарь", `Знаю: ${words.length}`, "")}
    <section class="card">
      <table class="table desktop-table">
        <thead><tr><th>Слово</th><th>POS</th><th>Перевод</th><th>Транскрипция</th><th>Статус</th></tr></thead>
        <tbody>${visibleWords.map((item) => `<tr><td>${escapeHtml(item.label)}</td><td>${escapeHtml(item.part_of_speech)}</td><td>${escapeHtml(item.translation_ru || "")}</td><td>${cleanTranscription(item.transcription) ? `/${escapeHtml(cleanTranscription(item.transcription))}/` : ""}</td><td><span class="pill status-${item.status}">${statusText(item.status)}</span></td></tr>`).join("") || `<tr><td colspan="5"><div class="empty">Пока нет слов/фраз со статусом “знаю”.</div></td></tr>`}</tbody>
      </table>
      <div class="mobile-card-list words-mobile-list">
        ${visibleWords.map((item) => `
          <article class="mobile-list-card word-mobile-card">
            <div>
              <h3>${escapeHtml(item.label)}</h3>
              <p class="meta">${escapeHtml(item.part_of_speech)}${cleanTranscription(item.transcription) ? ` · /${escapeHtml(cleanTranscription(item.transcription))}/` : ""}</p>
              ${item.translation_ru ? `<p>${escapeHtml(item.translation_ru)}</p>` : ""}
            </div>
            <span class="pill status-${item.status}">${statusText(item.status)}</span>
          </article>
        `).join("") || `<div class="empty">Пока нет слов/фраз со статусом “знаю”.</div>`}
      </div>
      ${hasMoreWords ? `<div class="pagination-actions"><button data-words-next>Далее</button><span class="meta">Показано ${visibleWords.length} из ${words.length}</span></div>` : words.length ? `<p class="meta pagination-summary">Показано ${visibleWords.length} из ${words.length}</p>` : ""}
    </section>
  `;
}
