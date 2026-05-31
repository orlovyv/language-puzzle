// Text-to-speech: voice discovery, selection and speaking via the Web Speech API.

import { state } from "./state.js";
import { clampNumber, escapeHtml, normalizeUser } from "./utils.js";
import { renderApp } from "./views/shell.js";

let ttsVoicesBound = false;

export function initTtsVoices() {
  if (ttsVoicesBound) return;
  if (!window.speechSynthesis) return;
  ttsVoicesBound = true;
  refreshTtsVoices();
  window.speechSynthesis.addEventListener("voiceschanged", refreshTtsVoices);
}

export function refreshTtsVoices() {
  if (!window.speechSynthesis) {
    state.ttsVoices = [];
    return;
  }
  state.ttsVoices = window.speechSynthesis.getVoices() || [];
  if (state.route === "/settings") renderApp();
}

export function ttsVoiceOptions(targetLanguage = "en") {
  const voices = state.ttsVoices || [];
  if (!voices.length) return [];
  const target = String(targetLanguage || "en").toLowerCase();
  const preferred = voices.filter((voice) => String(voice.lang || "").toLowerCase().startsWith(target));
  const secondary = voices.filter((voice) => !String(voice.lang || "").toLowerCase().startsWith(target));
  return [...preferred, ...secondary];
}

export function resolveTtsVoice(voiceUri, targetLanguage = "en") {
  const voices = ttsVoiceOptions(targetLanguage);
  if (!voices.length) return null;
  if (voiceUri) {
    const selected = voices.find((voice) => voice.voiceURI === voiceUri);
    if (selected) return selected;
  }
  return voices[0] || null;
}

export function speakText(text, overrideSettings = null) {
  const value = String(text || "").trim();
  if (!value || !window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") return;
  const profile = normalizeUser({ ...(state.user || {}), ...(overrideSettings || {}) });
  if (!profile.tts_enabled) return;
  const utterance = new SpeechSynthesisUtterance(value);
  const voice = resolveTtsVoice(profile.tts_voice, state.user?.target_language || "en");
  if (voice) {
    utterance.voice = voice;
    utterance.lang = voice.lang;
  } else {
    utterance.lang = state.user?.target_language || "en";
  }
  utterance.rate = clampNumber(profile.tts_rate, 1, 0.5, 2);
  utterance.pitch = clampNumber(profile.tts_pitch, 1, 0.5, 2);
  utterance.volume = clampNumber(profile.tts_volume, 1, 0, 1);
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

export function renderTtsButton(text, title = "Озвучить", size = "default") {
  const className = size === "mini" ? "tts-btn tts-btn-mini" : "tts-btn";
  return `<button type="button" class="${className}" data-speak="${escapeHtml(text)}" title="${escapeHtml(title)}">▶</button>`;
}
