// Upload form view.

import { renderHeader } from "./shell.js";

export function renderUpload() {
  return `
    ${renderHeader("Загрузка текста", "Вставьте текст или содержимое .srt, сервис очистит таймкоды и построит анализ.")}
    <form class="card form" id="uploadForm">
      <div class="form-row">
        <label class="label">Название<input name="title" placeholder="Chapter 1" required></label>
        <label class="label">Язык<select name="language"><option value="en">English</option></select></label>
        <label class="label">Тип<select name="type"><option value="text">text</option><option value="srt">srt</option><option value="book_chapter">book_chapter</option><option value="article">article</option></select></label>
      </div>
      <label class="label">Файл .txt или .srt<input name="file" type="file" accept=".txt,.srt,text/plain"></label>
      <label class="label">Текст<textarea name="raw_text" placeholder="Paste English text here..." required></textarea></label>
      <button class="primary" type="submit">Анализировать</button>
      <p class="notice upload-analysis-notice" data-upload-analysis-notice hidden>Идет анализ текста, это может занять немного времени...</p>
    </form>
  `;
}
