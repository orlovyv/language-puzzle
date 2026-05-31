// Status and translation mutations: network calls plus the local-state patching
// that keeps every cached view (document, analysis, words, knowledge, learn) in
// sync without a full reload.

import { api } from "./api.js";
import { state } from "./state.js";
import { cleanTranslation } from "./utils.js";
import { renderApp } from "./views/shell.js";

export async function patchKnowledgeStatus(kind, knowledgeId, status, options = {}) {
  const endpoint = kind === "phrase" ? "user-phrases" : "user-words";
  await api(`/api/${endpoint}/${knowledgeId}`, {
    method: "PATCH",
    body: {
      status,
      document_id: state.currentDocument?.id || null,
      refresh_analysis: Boolean(options.refreshAnalysis)
    }
  });
  applyLocalStatusUpdate(kind, knowledgeId, status);
}

export function applyLocalStatusUpdate(kind, knowledgeId, status) {
  if (!knowledgeId) return;
  if (state.currentDocument?.analysis) {
    if (kind === "phrase") {
      for (const phrase of (state.currentDocument.analysis.phrases || [])) {
        if (phrase.user_phrase_id === knowledgeId) phrase.status = status;
      }
      for (const piece of (state.currentDocument.pieces || [])) {
        if (piece.type === "phrase" && piece.user_phrase_id === knowledgeId) piece.status = status;
      }
    } else {
      const wordIds = new Set();
      for (const word of (state.currentDocument.analysis.words || [])) {
        if (word.user_word_id === knowledgeId) {
          word.status = status;
          if (word.word_id) wordIds.add(word.word_id);
        }
      }
      for (const piece of (state.currentDocument.pieces || [])) {
        if (piece.type === "word" && piece.word_id && wordIds.has(piece.word_id)) piece.status = status;
      }
    }
  }

  if (state.currentAnalysis) {
    if (kind === "phrase") {
      for (const phrase of (state.currentAnalysis.phrases || [])) {
        if (phrase.user_phrase_id === knowledgeId) phrase.status = status;
      }
    } else {
      for (const word of (state.currentAnalysis.words || [])) {
        if (word.user_word_id === knowledgeId) word.status = status;
      }
      for (const word of (state.currentAnalysis.important_words || [])) {
        if (word.user_word_id === knowledgeId) word.status = status;
      }
    }
  }

  if (state.selectedWord) {
    if (kind === "phrase" && state.selectedWord.user_phrase_id === knowledgeId) state.selectedWord = { ...state.selectedWord, status };
    if (kind === "word" && state.selectedWord.user_word_id === knowledgeId) state.selectedWord = { ...state.selectedWord, status };
  }

  if (state.words?.length && kind === "word") {
    for (const item of state.words) {
      if (item?.id === knowledgeId) item.status = status;
    }
  }

  if (state.knowledgeContext?.units?.length) {
    for (const unit of state.knowledgeContext.units) {
      if (unit.kind === kind && unit.knowledge_id === knowledgeId) unit.status = status;
    }
    for (const key of ["recommended_words", "recommended_phrases", "reviews"]) {
      for (const unit of (state.knowledgeContext[key] || [])) {
        if (unit.kind === kind && unit.knowledge_id === knowledgeId) unit.status = status;
      }
    }
    for (const group of Object.values(state.knowledgeContext.groups || {})) {
      for (const unit of group) {
        if (unit.kind === kind && unit.knowledge_id === knowledgeId) unit.status = status;
      }
    }
    updateKnowledgeContextStats(state.knowledgeContext);
  }

  if (state.learnBlocks?.length) {
    for (const block of state.learnBlocks) {
      for (const unit of (block.units || [])) {
        if (unit.kind === kind && unit.knowledge_id === knowledgeId) unit.status = status;
      }
    }
  }
}

export async function ensureTranslation(kind, knowledgeId, currentTranslation = "", options = {}) {
  if (!["word", "phrase"].includes(kind) || !knowledgeId || cleanTranslation(currentTranslation)) return;
  if (state.translationLoadingIds.has(knowledgeId)) return;
  state.translationLoadingIds.add(knowledgeId);
  state.translationFailedIds.delete(knowledgeId);
  if (options.render !== false) renderApp();

  try {
    const endpoint = kind === "phrase" ? "user-phrases" : "user-words";
    let data = await api(`/api/${endpoint}/${knowledgeId}/translation`, {
      method: "POST"
    });
    let item = kind === "phrase" ? data.phrase : data.word;
    let translation = cleanTranslation(item?.translation_ru);
    if (!translation) {
      const source = translationSourceText(kind, item, knowledgeId);
      translation = await translateWithClientGoogle(source);
      if (translation) {
        data = await api(`/api/${endpoint}/${knowledgeId}/translation`, {
          method: "POST",
          body: { translation_ru: translation }
        });
        item = kind === "phrase" ? data.phrase : data.word;
        translation = cleanTranslation(item?.translation_ru) || translation;
      }
    }
    if (translation) {
      applyLocalTranslation(kind, knowledgeId, translation);
    } else {
      state.translationFailedIds.add(knowledgeId);
    }
  } catch {
    state.translationFailedIds.add(knowledgeId);
  } finally {
    state.translationLoadingIds.delete(knowledgeId);
  }
}

function translationSourceText(kind, item, knowledgeId) {
  if (kind === "phrase") {
    return item?.base_form || item?.phrase || sourceTextFromLocalState(kind, knowledgeId);
  }
  return item?.lemma || sourceTextFromLocalState(kind, knowledgeId);
}

function sourceTextFromLocalState(kind, knowledgeId) {
  if (!knowledgeId) return "";

  if (kind === "phrase") {
    const candidates = [
      ...(state.currentDocument?.analysis?.phrases || []),
      ...(state.currentAnalysis?.phrases || []),
    ];
    for (const phrase of candidates) {
      if (phrase?.user_phrase_id === knowledgeId) return phrase.base_form || phrase.phrase || "";
    }
    for (const item of (state.words || [])) {
      if (item?.id === knowledgeId && item.phrase) return item.phrase.base_form || item.phrase.phrase || "";
    }
  } else {
    const candidates = [
      ...(state.currentDocument?.analysis?.words || []),
      ...(state.currentAnalysis?.words || []),
      ...(state.currentAnalysis?.important_words || []),
    ];
    for (const word of candidates) {
      if (word?.user_word_id === knowledgeId) return word.lemma || "";
    }
    for (const item of (state.words || [])) {
      if (item?.id === knowledgeId && item.word) return item.word.lemma || "";
    }
  }

  for (const context of [state.knowledgeContext, ...(state.knowledgeContexts || [])].filter(Boolean)) {
    for (const collection of [
      context.units || [],
      context.recommended_words || [],
      context.recommended_phrases || [],
      context.reviews || [],
      ...Object.values(context.groups || {})
    ]) {
      const unit = collection.find((item) => item.kind === kind && item.knowledge_id === knowledgeId);
      if (unit) return unit.base_form || unit.text || "";
    }
  }

  return "";
}

async function translateWithClientGoogle(source) {
  const text = String(source || "").trim();
  if (!text) return "";
  const params = new URLSearchParams({
    client: "gtx",
    sl: "en",
    tl: "ru",
    dt: "t",
    q: text
  });
  const response = await fetch(`https://translate.googleapis.com/translate_a/single?${params.toString()}`, {
    method: "GET",
    cache: "no-store"
  });
  if (!response.ok) return "";
  const data = await response.json();
  const translated = Array.isArray(data?.[0])
    ? data[0].map((part) => Array.isArray(part) ? part[0] : "").join("")
    : "";
  const cleaned = cleanTranslation(translated);
  return cleaned && cleaned.toLowerCase() !== text.toLowerCase() ? cleaned : "";
}

export function localTranslation(kind, knowledgeId) {
  if (!knowledgeId) return "";

  if (kind === "phrase") {
    const candidates = [
      ...(state.currentDocument?.analysis?.phrases || []),
      ...(state.currentAnalysis?.phrases || []),
    ];
    for (const phrase of candidates) {
      if (phrase?.user_phrase_id === knowledgeId) {
        return phrase.translation_ru || "";
      }
    }

    for (const item of (state.words || [])) {
      if (item?.id === knowledgeId && item.phrase) {
        return item.phrase.translation_ru || "";
      }
    }

    for (const block of (state.learnBlocks || [])) {
      const unit = (block.units || []).find((item) => item.kind === "phrase" && item.knowledge_id === knowledgeId);
      if (unit) return unit.translation_ru || "";
    }
  } else {
    const candidates = [
      ...(state.currentDocument?.analysis?.words || []),
      ...(state.currentAnalysis?.words || []),
      ...(state.currentAnalysis?.important_words || []),
    ];
    for (const word of candidates) {
      if (word?.user_word_id === knowledgeId) {
        return word.translation_ru || "";
      }
    }

    for (const item of (state.words || [])) {
      if (item?.id === knowledgeId && item.word) {
        return item.word.translation_ru || "";
      }
    }

    for (const block of (state.learnBlocks || [])) {
      const unit = (block.units || []).find((item) => item.kind !== "phrase" && item.knowledge_id === knowledgeId);
      if (unit) return unit.translation_ru || "";
    }
  }

  for (const context of [state.knowledgeContext, ...(state.knowledgeContexts || [])].filter(Boolean)) {
    for (const collection of [
      context.units || [],
      context.recommended_words || [],
      context.reviews || [],
      ...Object.values(context.groups || {})
    ]) {
      const unit = collection.find((item) => item.kind === kind && item.knowledge_id === knowledgeId);
      if (unit) return unit.translation_ru || "";
    }
  }

  return "";
}

export function applyLocalTranslation(kind, knowledgeId, translation) {
  if (!knowledgeId || !translation) return;
  if (kind === "phrase") {
    applyLocalPhraseTranslation(knowledgeId, translation);
    return;
  }

  const wordIds = new Set();

  const updateWord = (word) => {
    if (word?.user_word_id !== knowledgeId) return;
    word.translation_ru = translation;
    if (word.word_id) wordIds.add(word.word_id);
  };

  for (const word of (state.currentDocument?.analysis?.words || [])) {
    updateWord(word);
  }
  for (const word of (state.currentAnalysis?.words || [])) {
    updateWord(word);
  }
  for (const word of (state.currentAnalysis?.important_words || [])) {
    updateWord(word);
  }
  for (const piece of (state.currentDocument?.pieces || [])) {
    if (piece.type === "word" && piece.word_id && wordIds.has(piece.word_id)) {
      piece.translation_ru = translation;
    }
  }

  if (state.selectedWord?.user_word_id === knowledgeId) {
    state.selectedWord = { ...state.selectedWord, translation_ru: translation };
  }

  for (const item of (state.words || [])) {
    if (item?.id === knowledgeId && item.word) {
      item.word.translation_ru = translation;
    }
  }

  applyKnowledgeTranslation(kind, knowledgeId, translation);
  applyLearnTranslation(kind, knowledgeId, translation);
}

function applyLocalPhraseTranslation(knowledgeId, translation) {
  const phraseIds = new Set();

  const updatePhrase = (phrase) => {
    if (phrase?.user_phrase_id !== knowledgeId) return;
    phrase.translation_ru = translation;
    if (phrase.phrase_id) phraseIds.add(phrase.phrase_id);
  };

  for (const phrase of (state.currentDocument?.analysis?.phrases || [])) {
    updatePhrase(phrase);
  }
  for (const phrase of (state.currentAnalysis?.phrases || [])) {
    updatePhrase(phrase);
  }
  for (const piece of (state.currentDocument?.pieces || [])) {
    if (piece.type === "phrase" && piece.phrase_id && phraseIds.has(piece.phrase_id)) {
      piece.translation_ru = translation;
    }
  }

  if (state.selectedWord?.user_phrase_id === knowledgeId) {
    state.selectedWord = { ...state.selectedWord, translation_ru: translation };
  }

  for (const item of (state.words || [])) {
    if (item?.id === knowledgeId && item.phrase) {
      item.phrase.translation_ru = translation;
    }
  }

  applyKnowledgeTranslation("phrase", knowledgeId, translation);
  applyLearnTranslation("phrase", knowledgeId, translation);
}

function applyKnowledgeTranslation(kind, knowledgeId, translation) {
  const contexts = [
    state.knowledgeContext,
    ...(state.knowledgeContexts || []),
  ].filter(Boolean);

  for (const context of contexts) {
    for (const collection of [
      context.units || [],
      context.recommended_words || [],
      context.recommended_phrases || [],
      context.reviews || [],
      ...Object.values(context.groups || {})
    ]) {
      for (const unit of collection) {
        if (unit.kind === kind && unit.knowledge_id === knowledgeId) {
          unit.translation_ru = translation;
        }
      }
    }
  }
}

function applyLearnTranslation(kind, knowledgeId, translation) {
  for (const block of (state.learnBlocks || [])) {
    for (const unit of (block.units || [])) {
      if (unit.kind === kind && unit.knowledge_id === knowledgeId) {
        unit.translation_ru = translation;
      }
    }
  }
}

export function applyKnowledgeContextStatus(kind, knowledgeId, status) {
  for (const context of (state.knowledgeContexts || [])) {
    for (const collection of [
      context.units || [],
      context.recommended_words || [],
      context.recommended_phrases || [],
      context.reviews || [],
      ...Object.values(context.groups || {})
    ]) {
      for (const unit of collection) {
        if (unit.kind === kind && unit.knowledge_id === knowledgeId) unit.status = status;
      }
    }
    updateKnowledgeContextStats(context);
  }
}

export function updateKnowledgeContextStats(context) {
  const units = context?.units || [];
  const knownStatuses = new Set(["known", "ignored"]);
  context.known_count = units.filter((unit) => knownStatuses.has(unit.status)).length;
  context.unknown_count = units.filter((unit) => !knownStatuses.has(unit.status)).length;
  context.coverage_percent = units.length ? Math.round((context.known_count / units.length) * 100) : 0;
  context.phrases_count = units.filter((unit) => unit.kind === "phrase").length;
}
