// Pure, dependency-free helpers: HTML escaping, value cleaning, coercion,
// POS labelling and unit-key construction.

import { MAX_RAW_TEXT_LINES } from "./state.js";

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

export function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || "").trim());
}

export function cleanTranslation(value) {
  return value && value !== "перевод уточняется" ? value : "";
}

export function cleanTranscription(value) {
  return String(value || "").replace(/\*/g, "").trim();
}

export function cleanExample(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function translationTooltip(value) {
  return cleanTranslation(value) || "";
}

export function extractSpanExample(text, start, end) {
  if (!text) return "";
  const safeStart = Math.max(0, Number.isFinite(start) ? start : 0);
  const safeEnd = Math.max(safeStart, Number.isFinite(end) ? end : safeStart);
  const boundary = /[.!?\n]/;
  let left = safeStart;
  let right = safeEnd;
  while (left > 0 && !boundary.test(text[left - 1])) left -= 1;
  while (right < text.length && !boundary.test(text[right])) right += 1;
  if (right < text.length) right += 1;
  const snippet = cleanExample(text.slice(left, right));
  if (snippet.length <= 220) return snippet;
  return `${snippet.slice(0, 217)}...`;
}

export function posLabel(pos) {
  return {
    verb: "verb",
    aux: "verb",
    noun: "noun",
    propn: "noun",
    adj: "adjective",
    adv: "adverb",
  }[(pos || "").toLowerCase()] || (pos || "word");
}

export function posToCloudGroup(pos) {
  const value = (pos || "").toLowerCase();
  if (value === "verb" || value === "aux") return "verb";
  if (value === "noun" || value === "propn") return "noun";
  if (value === "adj") return "adjective";
  if (value === "adv") return "adverb";
  return "noun";
}

export function statusText(status) {
  return ({ unknown: "не знаю", seen: "примерно знаю", learning: "учу", known: "знаю", ignored: "игнор" })[status] || status;
}

export function isShortWord(value) {
  const lettersOnly = String(value || "")
    .toLowerCase()
    .replace(/[^a-z]/g, "");
  return lettersOnly.length <= 1;
}

export function countTextLines(value) {
  const text = String(value || "");
  return text ? text.split(/\r\n|\r|\n/).length : 0;
}

export function looksLikeSubtitleText(value) {
  const text = String(value || "");
  return /\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b/.test(text);
}

export function validateRawText(value) {
  const lines = countTextLines(value);
  if (lines > MAX_RAW_TEXT_LINES) {
    throw new Error(`Текст слишком длинный: ${lines} строк. Максимум ${MAX_RAW_TEXT_LINES} строк.`);
  }
}

export function parseBool(value, fallback = true) {
  if (value === true || value === false) return value;
  if (value == null) return fallback;
  const text = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(text)) return true;
  if (["0", "false", "no", "off"].includes(text)) return false;
  return fallback;
}

export function clampNumber(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

export function formatRangeValue(value) {
  return clampNumber(value, 1, 0, 2).toFixed(2);
}

export function ankiFileName(title) {
  return String(title || "learn_block")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 80) || "learn_block";
}

export function learnFrequencyRank(item) {
  const value = Number(item?.frequency_rank || 999999);
  return Number.isFinite(value) ? value : 999999;
}

// Identity key for a vocabulary unit. Replaces the byte-identical
// `knowledgeUnitKey` / `learnUnitKey` from the original monolith.
export function unitKey(item) {
  return `${item.kind === "phrase" ? "phrase" : "word"}:${item.knowledge_id}`;
}

export function normalizeUser(user) {
  return {
    ...user,
    tts_enabled: parseBool(user?.tts_enabled, true),
    tts_voice: String(user?.tts_voice || ""),
    tts_rate: clampNumber(user?.tts_rate, 1, 0.5, 2),
    tts_pitch: clampNumber(user?.tts_pitch, 1, 0.5, 2),
    tts_volume: clampNumber(user?.tts_volume, 1, 0, 1),
  };
}
