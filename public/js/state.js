// Shared application state and static configuration.
//
// `state` is exported as a live binding: every module imports the same object
// reference, so mutations are visible everywhere (this preserves the original
// single-global-state model).

export const UI_MODE_STORAGE_KEY = "languagePuzzle.uiMode";

export const MAX_UPLOAD_FILE_BYTES = 100 * 1024;
export const MAX_RAW_TEXT_LINES = 2000;
export const SUPPORTED_UPLOAD_EXTENSIONS = new Set([".txt", ".srt"]);
export const SUPPORTED_UPLOAD_MIME_TYPES = new Set(["", "text/plain", "application/x-subrip"]);

export const routes = [
  ["/dashboard", "Dashboard", "⌂"],
  ["/upload", "Upload", "+"],
  ["/knowledge", "Knowledge", "◎"],
  ["/learn", "Learn", "◫"],
  ["/words", "Words", "≡"],
  ["/premium", "Premium", "★"],
  ["/help", "Help", "?"],
  ["/settings", "Settings", "⚙"]
];

// Kept here (not in uimode.js) because it is evaluated while building `state`
// below — placing it in a module that imports `state` would create an
// evaluation-time cycle.
export function readUiMode() {
  try {
    return localStorage.getItem(UI_MODE_STORAGE_KEY) === "mobile" ? "mobile" : "desktop";
  } catch {
    return "desktop";
  }
}

export const state = {
  user: null,
  route: window.location.pathname,
  uiMode: readUiMode(),
  dashboard: null,
  documents: [],
  currentDocument: null,
  lastDocumentId: "",
  currentAnalysis: null,
  analysisDocumentId: null,
  selectedAnalysisKey: null,
  analysisVisibleKeys: null,
  analysisVisibleDocId: null,
  knowledgeContexts: [],
  knowledgeContext: null,
  knowledgeInput: "",
  knowledgeBridgeLoadingId: null,
  knowledgeLoading: false,
  learnBlocks: [],
  selectedLearnBlockIds: new Set(),
  selectedLearnKey: null,
  ankiGeneratingBlockId: null,
  translationLoadingIds: new Set(),
  translationFailedIds: new Set(),
  selectedKnowledgeKey: null,
  billing: null,
  billingLoading: false,
  publicConfig: null,
  ttsVoices: [],
  selectedWord: null,
  wordsVisibleCount: 100,
  pendingRegistrationEmail: "",
  message: ""
};
