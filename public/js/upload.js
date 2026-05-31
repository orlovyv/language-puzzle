// Client-side validation and decoding of uploaded .txt / .srt files.

import {
  MAX_UPLOAD_FILE_BYTES,
  SUPPORTED_UPLOAD_EXTENSIONS,
  SUPPORTED_UPLOAD_MIME_TYPES,
} from "./state.js";
import { validateRawText } from "./utils.js";

export function uploadFileExtension(fileName) {
  const match = String(fileName || "").toLowerCase().match(/\.[^.]+$/);
  return match ? match[0] : "";
}

export function hasBinaryContent(bytes) {
  if (!bytes.length) return false;
  let suspicious = 0;
  for (const byte of bytes) {
    if (byte === 0) return true;
    const isAllowedControl = byte === 9 || byte === 10 || byte === 13;
    if (byte < 32 && !isAllowedControl) suspicious += 1;
  }
  return suspicious / bytes.length > 0.05;
}

export async function readSupportedUploadFile(file) {
  if (file.size > MAX_UPLOAD_FILE_BYTES) {
    throw new Error("Файл слишком большой. Максимальный размер субтитров или текста - 100 КБ.");
  }
  const extension = uploadFileExtension(file.name);
  if (!SUPPORTED_UPLOAD_EXTENSIONS.has(extension) || !SUPPORTED_UPLOAD_MIME_TYPES.has(file.type || "")) {
    throw new Error("Неподдерживаемый файл. Загрузите .txt или .srt в текстовом формате.");
  }
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  if (hasBinaryContent(bytes)) {
    throw new Error("Похоже, это бинарный файл. Загрузите текстовый .txt или .srt.");
  }
  const text = new TextDecoder("utf-8").decode(bytes);
  validateRawText(text);
  return text;
}
