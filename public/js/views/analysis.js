// Analysis view: coverage hero, unknown-word cloud grouped by POS, detail panel.

import { state } from "../state.js";
import {
  cleanExample,
  cleanTranscription,
  cleanTranslation,
  escapeHtml,
  isShortWord,
  posLabel,
  posToCloudGroup,
  statusText,
  extractSpanExample,
  translationTooltip,
} from "../utils.js";
import { renderTtsButton } from "../tts.js";
import { renderHeader } from "./shell.js";
import { renderDocumentViewSwitch } from "./document.js";

export function renderAnalysis() {
  const analysis = state.currentAnalysis;
  const doc = state.currentDocument;
  if (!analysis || !doc) return `<div class="empty">Анализ загружается...</div>`;
  const sourceText = doc.clean_text || doc.raw_text || "";
  const cloud = buildUnknownCloudData(analysis, state.selectedAnalysisKey, state.analysisVisibleKeys, doc.id, sourceText);
  state.analysisVisibleKeys = cloud.visibleKeys;
  state.analysisVisibleDocId = doc.id;
  const selected = cloud.selected;
  return `
    ${renderHeader(escapeHtml(doc.title), "Результат анализа текста", renderDocumentViewSwitch(doc.id, "analysis"))}
    <section class="card analysis-hero">
      <div class="ring" style="--value:${analysis.coverage_percent}"><strong>${analysis.coverage_percent}%</strong></div>
      <div>
        <h2>После 25 слов: примерно ${analysis.projected_coverage_percent}%</h2>
        <p class="subtle">Всего слов: ${analysis.total_words}. Уникальных: ${analysis.unique_words}. Уже знакомо: ${analysis.known_words}. В списке: ${cloud.total}.</p>
        <p class="notice">Кликни по слову или фразе в облаке, чтобы увидеть перевод, частоту и сразу поменять статус.</p>
      </div>
    </section>
    <section class="analysis-layout" style="margin-top:16px">
      <div class="grid analysis-clouds">
        <div class="card">
        <div class="section-title">
          <h2>Новые важные слова</h2>
          <div class="toolbar">
            <button data-analysis-to-learn="${escapeHtml(doc.id)}">В Learn</button>
            <button class="primary" data-refresh-important="${doc.id}">Обновить список</button>
          </div>
        </div>
          <div class="analysis-groups">
            ${cloud.groups.map((group) => renderWordCloudGroup(group, selected)).join("")}
          </div>
        </div>
      </div>
      <aside class="card side-panel word-detail analysis-detail">
        ${renderAnalysisDetail(selected)}
      </aside>
    </section>
  `;
}

function renderWordCloudGroup(group, selected) {
  return `
    <section class="cloud-group">
      <h3>${escapeHtml(group.title)} <span class="pill">${group.items.length}</span></h3>
      ${group.items.length ? `
      <div class="word-cloud">
        ${group.items.map((item) => {
          const active = selected && selected.key === item.key;
          const weightClass = item.count > 1 ? "repeated" : "";
          const nextStatus = item.status === "known" ? "unknown" : "known";
          return `
            <button
              class="cloud-token ${item.status} ${weightClass} ${active ? "active" : ""}"
              data-cloud-kind="${item.kind}"
              data-cloud-id="${item.knowledge_id}"
              data-cloud-key="${item.key}"
              data-cloud-next-status="${nextStatus}"
              data-tooltip-kind="${item.kind}"
              data-tooltip-id="${escapeHtml(item.knowledge_id || "")}"
              title="${escapeHtml(translationTooltip(item.translation_ru))}"
            >${escapeHtml(item.label)}</button>
          `;
        }).join("")}
      </div>` : `<p class="meta">Пока пусто</p>`}
    </section>
  `;
}

function renderAnalysisDetail(item) {
  if (!item) return `<h2>Слово</h2><p class="subtle">Кликни по слову или фразе в облаке слева.</p>`;
  const examples = (item.examples || []).filter(Boolean).slice(0, 3);
  const transcription = cleanTranscription(item.transcription);
  return `
    <div class="detail-title">
      <h2>${escapeHtml(item.label)} <span class="pill status-${item.status}">${statusText(item.status)}</span></h2>
      ${renderTtsButton(item.label, `Озвучить ${item.label}`)}
    </div>
    <p><strong>Частота в тексте:</strong> ${item.count}×</p>
    ${item.translation_ru ? `<p><strong>Перевод:</strong> ${escapeHtml(item.translation_ru)}</p>` : ""}
    ${item.kind === "word" && transcription ? `<p><strong>Транскрипция:</strong> /${escapeHtml(transcription)}/</p>` : ""}
    ${examples.length ? `<div><strong>Примеры в тексте:</strong><ul class="detail-examples">${examples.map((example) => `<li><span>${escapeHtml(example)}</span>${renderTtsButton(example, "Озвучить пример", "mini")}</li>`).join("")}</ul></div>` : ""}
    ${item.kind === "phrase"
      ? `<p class="meta">Устойчивое выражение / фразовый глагол</p>`
      : `<p class="meta">Часть речи: ${escapeHtml(posLabel(item.part_of_speech))}</p>`}
  `;
}

export function buildUnknownCloudData(analysis, selectedKey, visibleKeys, documentId, sourceText = "") {
  const groups = [
    { id: "verb", title: "verbs", items: [] },
    { id: "noun", title: "nouns", items: [] },
    { id: "adjective", title: "adjectives", items: [] },
    { id: "adverb", title: "adverbs", items: [] },
    { id: "phrase", title: "Устойчивые выражения", items: [] },
  ];
  const groupMap = new Map(groups.map((group) => [group.id, group]));
  const byKey = new Map();
  for (const word of (analysis.words || [])) {
    if (!word || word.status === "ignored") continue;
    if (!word.user_word_id) continue;
    if (isShortWord(word.lemma)) continue;
    const groupId = posToCloudGroup(word.part_of_speech);
    const item = {
      key: `word:${word.user_word_id}`,
      kind: "word",
      knowledge_id: word.user_word_id,
      label: word.lemma,
      translation_ru: cleanTranslation(word.translation_ru),
      transcription: cleanTranscription(word.transcription),
      count: Number(word.count || 1),
      status: word.status || "unknown",
      part_of_speech: word.part_of_speech || "word",
      examples: cleanExample(word.example) ? [cleanExample(word.example)] : [],
    };
    groupMap.get(groupId).items.push(item);
    byKey.set(item.key, item);
  }

  const phraseMap = new Map();
  for (const phrase of (analysis.phrases || [])) {
    if (!phrase || phrase.status === "ignored") continue;
    if (!phrase.user_phrase_id) continue;
    const key = phrase.base_form || phrase.phrase;
    if (!key) continue;
    const phraseKey = `phrase:${phrase.user_phrase_id}`;
    if (!phraseMap.has(phraseKey)) {
      phraseMap.set(phraseKey, {
        key: phraseKey,
        kind: "phrase",
        knowledge_id: phrase.user_phrase_id,
        label: key,
        translation_ru: cleanTranslation(phrase.translation_ru),
        count: 0,
        status: phrase.status || "unknown",
        part_of_speech: "phrase",
        examples: [],
      });
    }
    const phraseItem = phraseMap.get(phraseKey);
    phraseItem.count += 1;
    const phraseExample = extractSpanExample(sourceText, Number(phrase.start || 0), Number(phrase.end || 0));
    if (phraseExample && !phraseItem.examples.includes(phraseExample)) {
      phraseItem.examples.push(phraseExample);
    }
  }
  for (const item of phraseMap.values()) {
    groupMap.get("phrase").items.push(item);
    byKey.set(item.key, item);
  }

  const allItems = groups.flatMap((group) => group.items);
  const defaultKeys = new Set(
    allItems
      .filter((item) => item.status !== "known" && item.status !== "ignored")
      .map((item) => item.key)
  );
  let effectiveVisibleKeys = visibleKeys;
  const shouldResetVisibleKeys = !(effectiveVisibleKeys instanceof Set) || state.analysisVisibleDocId !== documentId;
  if (shouldResetVisibleKeys) {
    effectiveVisibleKeys = defaultKeys;
  }

  for (const group of groups) {
    group.items = group.items.filter((item) => effectiveVisibleKeys.has(item.key));
    group.items.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }
  const total = groups.reduce((acc, group) => acc + group.items.length, 0);
  const first = groups.flatMap((group) => group.items)[0] || null;
  const selected = (selectedKey && byKey.get(selectedKey)) || first || null;
  if (!selected && selectedKey) state.selectedAnalysisKey = null;
  if (selected) state.selectedAnalysisKey = selected.key;
  return { groups, byKey, total, selected, visibleKeys: effectiveVisibleKeys };
}

export function analysisUnitsForLearn(analysis) {
  return [
    ...(analysis?.words || []).map((word) => ({
      id: word.word_id,
      knowledge_id: word.user_word_id,
      kind: "word",
      text: word.lemma,
      translation_ru: cleanTranslation(word.translation_ru),
      transcription: cleanTranscription(word.transcription),
      part_of_speech: word.part_of_speech,
      status: word.status,
      example: cleanExample(word.example),
      count: Number(word.count || 1),
      frequency_rank: Number(word.frequency_rank || 999999),
      score: Number(word.priority || 0),
    })),
    ...(analysis?.phrases || []).map((phrase) => ({
      id: phrase.phrase_id,
      knowledge_id: phrase.user_phrase_id,
      kind: "phrase",
      text: phrase.base_form || phrase.phrase,
      base_form: phrase.base_form || phrase.phrase,
      translation_ru: cleanTranslation(phrase.translation_ru),
      part_of_speech: "phrase",
      status: phrase.status,
      count: 1,
      frequency_rank: 999999,
      score: 70,
    })),
  ].filter((unit) => unit.knowledge_id && unit.text && unit.status !== "known" && unit.status !== "ignored" && !isShortWord(unit.text));
}
