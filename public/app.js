const app = document.querySelector("#app");

const state = {
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
  ttsVoices: [],
  selectedWord: null,
  wordsVisibleCount: 100,
  pendingRegistrationEmail: "",
  message: ""
};

let pendingReaderScrollTop = null;
let ttsVoicesBound = false;

const MAX_UPLOAD_FILE_BYTES = 100 * 1024;
const MAX_RAW_TEXT_LINES = 2000;
const SUPPORTED_UPLOAD_EXTENSIONS = new Set([".txt", ".srt"]);
const SUPPORTED_UPLOAD_MIME_TYPES = new Set(["", "text/plain", "application/x-subrip"]);
const UI_MODE_STORAGE_KEY = "languagePuzzle.uiMode";

const routes = [
  ["/dashboard", "Dashboard", "⌂"],
  ["/upload", "Upload", "+"],
  ["/knowledge", "Knowledge", "◎"],
  ["/learn", "Learn", "◫"],
  ["/words", "Words", "≡"],
  ["/help", "Help", "?"],
  ["/settings", "Settings", "⚙"]
];

function readUiMode() {
  try {
    return localStorage.getItem("languagePuzzle.uiMode") === "mobile" ? "mobile" : "desktop";
  } catch {
    return "desktop";
  }
}

function setUiMode(mode) {
  state.uiMode = mode === "mobile" ? "mobile" : "desktop";
  try {
    localStorage.setItem(UI_MODE_STORAGE_KEY, state.uiMode);
  } catch {
    // localStorage can be unavailable in restricted browser modes.
  }
  renderApp();
}

window.addEventListener("popstate", () => {
  state.route = window.location.pathname;
  if (state.user && (state.route === "/login" || state.route === "/register")) {
    window.history.replaceState({}, "", "/dashboard");
    state.route = "/dashboard";
    loadRoute();
    return;
  }
  if (!state.user && state.route === "/") {
    state.message = "";
    renderLanding();
    return;
  }
  if (!state.user && state.route === "/help") {
    state.message = "";
    renderPublicHelp();
    return;
  }
  if (!state.user && (state.route === "/login" || state.route === "/register")) {
    state.message = "";
    if (state.route !== "/register") state.pendingRegistrationEmail = "";
    renderAuth();
    return;
  }
  loadRoute();
});

document.addEventListener("click", async (event) => {
  const link = event.target.closest("a[data-link]");
  if (!link) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || "Request failed");
  return data;
}

async function navigate(path) {
  window.history.pushState({}, "", path);
  state.route = window.location.pathname;
  if (state.user && (state.route === "/login" || state.route === "/register")) {
    window.history.replaceState({}, "", "/dashboard");
    state.route = "/dashboard";
    await loadRoute();
    return;
  }
  if (!state.user && state.route === "/") {
    state.message = "";
    renderLanding();
    return;
  }
  if (!state.user && state.route === "/help") {
    state.message = "";
    renderPublicHelp();
    return;
  }
  if (!state.user && (state.route === "/login" || state.route === "/register")) {
    state.message = "";
    if (state.route !== "/register") state.pendingRegistrationEmail = "";
    renderAuth();
    return;
  }
  await loadRoute();
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || "").trim());
}

async function boot() {
  try {
    const { user } = await api("/api/me");
    state.user = normalizeUser(user);
    initTtsVoices();
    if (state.route === "/login" || state.route === "/register") await navigate("/dashboard");
    else if (state.route === "/") renderLanding();
    else await loadRoute();
  } catch {
    if (state.route === "/login" || state.route === "/register") renderAuth();
    else if (state.route === "/help") renderPublicHelp();
    else renderLanding();
  }
}

async function loadRoute() {
  state.message = "";
  try {
    if (state.route === "/") {
      renderLanding();
      return;
    }
    if (state.route === "/dashboard") {
      state.dashboard = await api("/api/dashboard");
    } else if (state.route === "/words") {
      const { words, phrases } = await api("/api/words");
      state.words = [...(words || []), ...(phrases || [])];
      state.wordsVisibleCount = 100;
    } else if (state.route === "/learn") {
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      const existingIds = new Set(state.learnBlocks.map((block) => block.id));
      state.selectedLearnBlockIds = new Set([...state.selectedLearnBlockIds].filter((id) => existingIds.has(id)));
      const learnUnits = state.learnBlocks.flatMap((block) => block.units || []);
      if (state.selectedLearnKey && !learnUnits.some((unit) => learnUnitKey(unit) === state.selectedLearnKey)) {
        state.selectedLearnKey = null;
      }
    } else if (state.route === "/knowledge") {
      const params = new URLSearchParams(window.location.search);
      const hasExplicitContext = Boolean(params.get("document_id") || params.get("context_id"));
      const hasInputText = Boolean((state.knowledgeInput || "").trim());
      if (!hasExplicitContext && !hasInputText) {
        state.knowledgeContexts = [];
        state.knowledgeContext = null;
      } else if (hasExplicitContext || !state.knowledgeContext) {
        const suffix = params.get("document_id")
          ? `?document_id=${encodeURIComponent(params.get("document_id"))}`
          : params.get("context_id")
            ? `?context_id=${encodeURIComponent(params.get("context_id"))}`
            : "";
        const { contexts, context } = await api(`/api/knowledge${suffix}`);
        state.knowledgeContexts = contexts;
        state.knowledgeContext = context;
        state.knowledgeInput = state.knowledgeInput || "";
      }
    } else if (state.route.startsWith("/document/")) {
      const [, , id, view] = state.route.split("/");
      state.lastDocumentId = id;
      if (view === "analysis") {
        if (state.analysisDocumentId !== id) {
          state.selectedAnalysisKey = null;
          state.analysisVisibleKeys = null;
          state.analysisVisibleDocId = null;
        }
        const [{ document }, { analysis }] = await Promise.all([
          api(`/api/documents/${id}`),
          api(`/api/documents/${id}/analysis`)
        ]);
        state.analysisDocumentId = id;
        state.currentDocument = document;
        state.currentAnalysis = analysis;
      } else {
        const { document } = await api(`/api/documents/${id}`);
        state.currentDocument = document;
      }
    }
    renderApp();
  } catch (error) {
    state.message = error.message;
    renderApp();
  }
}

function renderAuth() {
  const isRegister = state.route === "/register";
  const isVerification = isRegister && state.pendingRegistrationEmail;
  app.innerHTML = `
    <main class="auth">
      <a class="auth-home" data-link href="/">Language Puzzle</a>
      <section class="card auth-card">
        <h1>${isVerification ? "Подтвердите email" : isRegister ? "Регистрация" : "Вход"}</h1>
        <p class="subtle">${
          isVerification
            ? `Мы отправили код на ${escapeHtml(state.pendingRegistrationEmail)}.`
            : isRegister
              ? "Введите email и пароль, чтобы создать аккаунт."
              : "Войдите по email и паролю."
        }</p>
        <form class="form" id="authForm">
          ${isVerification ? `
            <label class="label">Код из письма<input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required autofocus></label>
            <button class="primary" type="submit">Подтвердить и войти</button>
            <button class="ghost" type="button" id="changeEmailBtn">Изменить email</button>
          ` : `
            <label class="label">Email<input name="email" type="email" autocomplete="email" inputmode="email" pattern="[^\\s@]+@[^\\s@]+\\.[^\\s@]+" required></label>
            <label class="label">Пароль<input name="password" type="password" autocomplete="${isRegister ? "new-password" : "current-password"}" required></label>
            <button class="primary" type="submit">${isRegister ? "Создать аккаунт" : "Войти"}</button>
          `}
        </form>
        <p>${isRegister ? "Уже есть аккаунт?" : "Нужен аккаунт?"} <a data-link href="${isRegister ? "/login" : "/register"}">${isRegister ? "Войти" : "Зарегистрироваться"}</a></p>
        ${state.message ? `<p class="notice">${escapeHtml(state.message)}</p>` : ""}
      </section>
    </main>
  `;
  document.querySelector("#changeEmailBtn")?.addEventListener("click", () => {
    state.pendingRegistrationEmail = "";
    state.message = "";
    renderAuth();
  });
  document.querySelector("#authForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (isVerification) {
        const { user } = await api("/api/register/verify", {
          method: "POST",
          body: { email: state.pendingRegistrationEmail, code: form.code }
        });
        state.pendingRegistrationEmail = "";
        state.user = normalizeUser(user);
        initTtsVoices();
        await navigate("/dashboard");
        return;
      }
      if (!isValidEmail(form.email)) {
        state.message = "Введите корректный email, например name@example.com.";
        renderAuth();
        return;
      }
      if (isRegister) {
        form.native_language = "ru";
        form.target_language = "en";
      }
      const result = await api(isRegister ? "/api/register" : "/api/login", { method: "POST", body: form });
      if (result.requires_verification) {
        state.pendingRegistrationEmail = result.email || form.email;
        state.message = "Введите код подтверждения из письма.";
        renderAuth();
        return;
      }
      const { user } = result;
      state.user = normalizeUser(user);
      initTtsVoices();
      await navigate("/dashboard");
    } catch (error) {
      state.message = error.message;
      renderAuth();
    }
  });
}

function renderLanding() {
  const landingNavActions = state.user
    ? `<a data-link href="/dashboard"><button class="primary">Продолжить работу</button></a>`
    : `<a data-link href="/login"><button class="ghost">Войти</button></a><a data-link href="/register"><button class="primary">Зарегистрироваться</button></a>`;
  const landingHeroActions = state.user
    ? `<a data-link href="/dashboard"><button class="primary">Продолжить работу</button></a>`
    : `<a data-link href="/register"><button class="primary">Начать по email</button></a><a data-link href="/login"><button>У меня есть аккаунт</button></a>`;
  const landingFinalAction = state.user
    ? `<a data-link href="/dashboard"><button class="primary">Продолжить работу</button></a>`
    : `<a data-link href="/register"><button class="primary">Создать личную базу знаний</button></a>`;
  app.innerHTML = `
    <main class="landing">
      <nav class="landing-nav">
        <a class="brand" data-link href="/">Language Puzzle</a>
        <div class="toolbar">${landingNavActions}</div>
      </nav>
      <section class="landing-hero">
        <div class="landing-copy">
          <h1>Разбирайте английские тексты как личную карту знаний</h1>
          <p>Сервис выделяет незнакомые слова и устойчивые фразы, показывает покрытие текста, собирает Theme Card и помогает постепенно переводить слова из неизвестных в знакомые.</p>
          <div class="landing-actions">${landingHeroActions}</div>
        </div>
        <div class="landing-visual" aria-label="Пример анализа текста">
          <div class="analysis-window">
            <div class="analysis-bar"><span></span><span></span><span></span></div>
            <div class="analysis-text">
              <mark class="known">travel</mark> opens a <mark class="unknown">route</mark> to
              <mark class="learning">grow up</mark> with real stories.
            </div>
            <div class="analysis-row"><strong>72%</strong><span>покрытие текста</span></div>
            <div class="analysis-chips">
              <span>18 знакомо</span><span>7 новых</span><span>3 фразы</span>
            </div>
          </div>
        </div>
      </section>
      <section class="landing-points">
        <article><h2>Тексты</h2><p>Загружайте статьи, диалоги или субтитры и сразу видите, что уже понятно.</p></article>
        <article><h2>Словарь</h2><p>Статусы слов и фраз хранятся отдельно для каждого пользователя.</p></article>
        <article><h2>Knowledge</h2><p>Theme Card подбирает мостовые темы и лексику для следующего шага.</p></article>
      </section>
      <section class="landing-story">
        <div class="landing-section-head">
          <h2>Учите язык не с нуля, а от того, что уже знаете</h2>
          <p>Большинство курсов начинают одинаково: набор случайных слов, простые диалоги и темы, которые вы давно проходили или которые пока не нужны.</p>
          <p>Но у взрослого человека уже есть огромный багаж знаний: фильмы, книги, работа, хобби, путешествия, игры, жизненный опыт. Проблема не в отсутствии знаний, а в том, что они существуют фрагментами и не связаны между собой.</p>
          <p>Language Puzzle постепенно собирает и расширяет вашу <strong>личную базу знаний языка</strong>.</p>
        </div>

        <div class="landing-workflow">
          <article>
            <span class="step-index">01</span>
            <h3>Добавьте небольшой понятный материал</h3>
            <p>Глава книги, субтитры одной серии, статья, диалог или фрагмент текста. Небольшие тексты работают лучше: система точнее строит связи, когда материал поступает порциями.</p>
            <div class="landing-tags"><span>одна глава</span><span>15-30 минут субтитров</span><span>короткая статья</span></div>
          </article>
          <article>
            <span class="step-index">02</span>
            <h3>Система пассивно собирает базу</h3>
            <p>Во время чтения она отмечает знакомые и новые слова, распознает устойчивые выражения, находит фразовые глаголы, объединяет лексику по темам и сохраняет связи.</p>
          </article>
          <article>
            <span class="step-index">03</span>
            <h3>Вы повторяете только полезное</h3>
            <p>Новые слова и выражения превращаются в карточки с переводом, примерами из вашего текста, контекстом и связями с другими словами.</p>
          </article>
        </div>

        <div class="landing-knowledge">
          <div>
            <h2>Язык изучается через темы и связи</h2>
            <p>Вместо случайных наборов слов система определяет темы внутри текста и расширяет их близкими понятиями. Так словарный запас растет естественно, через смысловые связи.</p>
          </div>
          <div class="topic-map" aria-label="Пример тематической карты">
            <strong>Путешествие</strong>
            <div><span>аэропорт</span><span>багаж</span><span>паспорт</span><span>регистрация</span><span>задержка рейса</span></div>
            <hr>
            <div><span>отель</span><span>городской транспорт</span><span>документы</span><span>проблемы в поездке</span><span>рестораны</span></div>
          </div>
        </div>

        <div class="landing-feature-grid">
          <article><h3>Не просто слова, а живой контекст</h3><p>Система учитывает частоту, реальные примеры, устойчивые выражения, контекст и уже изученные слова, чтобы выбирать то, что действительно используется людьми.</p></article>
          <article><h3>Автоматические карточки для повторения</h3><p>Карточки могут включать слово, перевод, пример, устойчивое выражение, изображение-ассоциацию, контекст и связи с другими словами.</p></article>
          <article><h3>Чем больше вы читаете, тем умнее система</h3><p>Каждый новый текст уточняет карту знаний, отмечает знакомое, находит пробелы и постепенно уменьшает количество неизвестных слов.</p></article>
        </div>

        <blockquote class="landing-quote">
          <p>Система начинает понимать, что вы уже знаете, что почти знаете и что стоит изучить дальше.</p>
        </blockquote>

        <div class="landing-final">
          <h2>Не курс подгоняет вас под программу. Программа постепенно подстраивается под вас.</h2>
          ${landingFinalAction}
        </div>
      </section>
    </main>
  `;
}

function renderPublicHelp() {
  const navActions = state.user
    ? `<a data-link href="/dashboard"><button class="primary">В кабинет</button></a>`
    : `<a data-link href="/login"><button class="ghost">Войти</button></a><a data-link href="/register"><button class="primary">Начать</button></a>`;
  app.innerHTML = `
    <main class="landing">
      <nav class="landing-nav">
        <a class="brand" data-link href="/">Language Puzzle</a>
        <div class="toolbar">${navActions}</div>
      </nav>
      ${renderHelpContent(true)}
    </main>
  `;
}

function renderApp() {
  const isMobileMode = state.uiMode === "mobile";
  app.innerHTML = `
    <div class="shell ${isMobileMode ? "mobile-mode" : "desktop-mode"}">
      <aside class="sidebar">
        <a class="brand" data-link href="/">Language Puzzle</a>
        ${renderUiModeSwitch()}
        <nav class="nav">
          ${renderNavigationLinks("desktop")}
        </nav>
        <div class="userline">
          <div>${escapeHtml(state.user?.email || "")}</div>
        </div>
      </aside>
      <main class="main ${isDocumentReaderRoute() ? "document-main" : ""}">
        ${state.message ? `<p class="notice">${escapeHtml(state.message)}</p>` : ""}
        ${renderRoute()}
      </main>
      <nav class="mobile-bottom-nav" aria-label="Mobile navigation">
        ${renderNavigationLinks("mobile")}
        ${renderMobileModeButton()}
      </nav>
    </div>
  `;
  document.querySelectorAll("[data-logout]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    state.user = null;
    state.route = "/login";
    window.history.pushState({}, "", "/login");
    renderAuth();
  }));
  document.querySelectorAll("[data-ui-mode]").forEach((button) => {
    button.addEventListener("click", () => setUiMode(button.dataset.uiMode));
  });
  bindRoute();
}

function isNavRouteActive(path) {
  if (state.route === path) return true;
  return path === "/dashboard" && state.route.startsWith("/document/");
}

function navigationItems() {
  const documentId = currentDocumentIdFromRoute() || state.lastDocumentId || state.dashboard?.documents?.[0]?.id || "";
  const textPath = documentId ? `/document/${documentId}` : "";
  const analysisPath = documentId ? `/document/${documentId}/analysis` : "";
  return [
    routes[0],
    [textPath, "Текст", "T", !documentId],
    [analysisPath, "Анализ", "A", !documentId],
    ...routes.slice(1)
  ];
}

function renderNavigationLinks(variant = "desktop") {
  return navigationItems().map(([path, label, icon, disabled]) => {
    const active = isNavigationItemActive(path);
    const content = variant === "mobile"
      ? `<span>${icon}</span><small>${label}</small>`
      : `<span>${icon}</span> ${label}`;
    if (disabled) {
      return `<span class="nav-disabled" title="Сначала откройте текст из Dashboard">${content}</span>`;
    }
    return `<a data-link class="${active ? "active" : ""}" href="${path}" title="${label}">${content}</a>`;
  }).join("");
}

function isNavigationItemActive(path) {
  if (path.includes("/document/")) return state.route === path;
  if (path === "/dashboard" && currentDocumentIdFromRoute()) return false;
  return isNavRouteActive(path);
}

function renderUiModeSwitch() {
  const mode = state.uiMode === "mobile" ? "mobile" : "desktop";
  return `
    <div class="ui-mode-switch" role="group" aria-label="Версия интерфейса">
      <button type="button" class="${mode === "desktop" ? "active" : ""}" data-ui-mode="desktop" aria-pressed="${mode === "desktop"}">Desktop</button>
      <button type="button" class="${mode === "mobile" ? "active" : ""}" data-ui-mode="mobile" aria-pressed="${mode === "mobile"}">Mobile</button>
    </div>
  `;
}

function renderMobileModeButton() {
  const nextMode = state.uiMode === "mobile" ? "desktop" : "mobile";
  const label = state.uiMode === "mobile" ? "Desktop" : "Mobile";
  return `<button type="button" class="mobile-mode-nav-button" data-ui-mode="${nextMode}" title="${label}"><span>⇄</span><small>${label}</small></button>`;
}

function currentDocumentIdFromRoute() {
  if (!state.route.startsWith("/document/")) return "";
  return state.route.split("/")[2] || "";
}

function renderRoute() {
  if (state.route === "/") return renderLanding();
  if (state.route === "/dashboard") return renderDashboard();
  if (state.route === "/upload") return renderUpload();
  if (state.route === "/knowledge") return renderKnowledge();
  if (state.route === "/learn") return renderLearn();
  if (state.route === "/words") return renderWords();
  if (state.route === "/help") return renderHelp();
  if (state.route === "/settings") return renderSettings();
  if (state.route.startsWith("/document/") && state.route.endsWith("/analysis")) return renderAnalysis();
  if (state.route.startsWith("/document/")) return renderDocument();
  return renderDashboard();
}

function renderHeader(title, subtitle, actions = "") {
  return `<div class="topbar"><div><h1>${title}</h1><p class="subtle">${subtitle}</p></div><div class="toolbar">${actions}</div></div>`;
}

function renderHelp() {
  return renderHelpContent(false);
}

function renderHelpContent(isPublic = false) {
  const primaryAction = state.user
    ? `<a data-link href="/upload"><button class="primary">Загрузить текст</button></a>`
    : `<a data-link href="/register"><button class="primary">Создать аккаунт</button></a>`;
  const secondaryAction = state.user
    ? `<a data-link href="/dashboard"><button>Посмотреть тексты</button></a>`
    : `<a data-link href="/"><button>На главную</button></a>`;
  return `
    <section class="help-page ${isPublic ? "help-page-public" : ""}">
      <section class="help-hero">
        <div class="help-copy">
          <span class="step-index">HELP / SYSTEM WALKTHROUGH</span>
          <h1>Как Language Puzzle превращает текст в личную систему изучения</h1>
          <p>Сервис проходит материал по цепочке: принимает текст, разбирает лексику, сравнивает ее с вашим словарем, строит карту знаний и отдает готовые блоки для повторения.</p>
          <div class="landing-actions">${primaryAction}${secondaryAction}</div>
        </div>
        <div class="help-flow" aria-label="Последовательность работы системы">
          <div><strong>Input</strong><span>текст, субтитры, диалог</span></div>
          <div><strong>Analysis</strong><span>слова, фразы, покрытие</span></div>
          <div><strong>Knowledge</strong><span>темы, связи, мосты</span></div>
          <div><strong>Learn</strong><span>карточки и повторение</span></div>
        </div>
      </section>

      <section class="help-strip">
        <article><strong>01</strong><span>Загрузка</span><p>Вы добавляете небольшой фрагмент текста. Система сохраняет документ и готовит его к разбору.</p></article>
        <article><strong>02</strong><span>Разметка</span><p>Текст делится на токены, леммы и устойчивые выражения, чтобы видеть не только отдельные слова.</p></article>
        <article><strong>03</strong><span>Сравнение</span><p>Каждая единица сверяется с личным словарем и получает один из двух рабочих статусов: знаю или не знаю.</p></article>
        <article><strong>04</strong><span>Обучение</span><p>Новые единицы превращаются в понятные блоки для чтения, повторения и дальнейшего расширения.</p></article>
      </section>

      <section class="landing-story help-story">
        <div class="landing-section-head">
          <h2>Принцип работы по шагам</h2>
          <p>Каждый блок отвечает за свой слой: документ хранит исходный материал, Analysis показывает структуру текста, Knowledge объясняет смысловые связи, Learn собирает практику, а Words фиксирует устойчивый результат.</p>
        </div>

        <div class="help-timeline">
          <article>
            <span class="step-index">Шаг 1</span>
            <h3>Upload принимает материал</h3>
            <p>В систему попадает текст, название и тип документа. Лучше работают короткие порции: одна сцена, статья, глава или фрагмент субтитров.</p>
          </article>
          <article>
            <span class="step-index">Шаг 2</span>
            <h3>Reader показывает текст в рабочем виде</h3>
            <p>Документ становится интерактивным: знакомые слова остаются спокойными, новые подсвечиваются, устойчивые фразы выделяются как цельные элементы.</p>
          </article>
          <article>
            <span class="step-index">Шаг 3</span>
            <h3>Analysis считает покрытие</h3>
            <p>Блок анализа показывает процент понятного текста, частотность, части речи, примеры и облако неизвестной лексики. Здесь удобно быстро менять статусы.</p>
          </article>
          <article>
            <span class="step-index">Шаг 4</span>
            <h3>Knowledge строит смысловую карту</h3>
            <p>Theme Card объединяет слова и выражения вокруг темы, предлагает близкие понятия и помогает перейти от разрозненных слов к связанной области знания.</p>
          </article>
          <article>
            <span class="step-index">Шаг 5</span>
            <h3>Learn собирает тренировочные блоки</h3>
            <p>Новые слова и фразы попадают в компактные наборы. По каждому блоку можно сгенерировать ANKI-экспорт с примерами предложений из изучаемого текста и озвучкой.</p>
          </article>
          <article>
            <span class="step-index">Шаг 6</span>
            <h3>Words хранит накопленный результат</h3>
            <p>Общий словарь показывает то, что уже закреплено. Каждый следующий текст использует эту базу, поэтому анализ становится точнее и персональнее.</p>
          </article>
        </div>

        <div class="landing-quote help-quote">
          <p>Первые тексты могут выглядеть почти полностью неизвестными - это нормально. В начале нужно один раз помочь системе: отметить слова, которые вы уже знаете. Так пополняется личная база, и в следующих текстах неизвестного становится заметно меньше. Дальше Language Puzzle все точнее показывает не весь шум подряд, а именно ваши реальные пробелы, которые стоит закрывать.</p>
        </div>

        <div class="landing-knowledge help-system-card">
          <div>
            <h2>Блоки работают как один цикл</h2>
            <p>Система не заканчивается после одного анализа. Каждый новый документ уточняет словарь, Knowledge расширяет темы, Learn возвращает полезные единицы в повторение, а статусы снова влияют на будущие тексты.</p>
          </div>
          <div class="topic-map help-map" aria-label="Цикл работы блоков">
            <strong>Language Puzzle Loop</strong>
            <div><span>Upload</span><span>Reader</span><span>Analysis</span><span>Knowledge</span><span>Learn</span><span>Words</span></div>
            <hr>
            <div><span>статусы</span><span>переводы</span><span>примеры</span><span>темы</span><span>повторение</span><span>покрытие</span></div>
          </div>
        </div>

        <div class="landing-feature-grid">
          <article><h3>Dashboard</h3><p>Стартовая панель показывает тексты, размер словаря, количество слов в изучении и среднее покрытие материалов.</p></article>
          <article><h3>ANKI</h3><p>ANKI - программа для интервального повторения: карточки возвращаются тогда, когда их пора освежить. Экспорт помогает учить слова вне Language Puzzle.</p></article>
          <article><h3>Settings</h3><p>Настройки управляют учетной записью и озвучкой: голосом, скоростью, тоном и громкостью для повторения вслух.</p></article>
          <article><h3>Статусы</h3><p>Кнопки “знаю” и “не знаю” связывают все экраны в единую персональную модель и помогают системе точнее понимать ваш словарь.</p></article>
        </div>

        <blockquote class="landing-quote">
          <p>Главная идея: вы не учите абстрактный список слов, а постепенно улучшаете понимание конкретных текстов, которые вам действительно нужны.</p>
        </blockquote>

        <div class="help-recommendations">
          <div class="landing-section-head">
            <h2>Рекомендации</h2>
            <p>Ниже два полезных внешних ресурса для работы с текстами и повторением слов вне Language Puzzle.</p>
          </div>
          <div class="help-resource-grid">
            <article class="help-resource-card">
              <img src="https://www.gutenberg.org/gutenberg/pg-logo-129x80.svg" alt="Project Gutenberg logo">
              <div>
                <h3>Проект «Гутенберг»</h3>
                <p>Большая библиотека бесплатных электронных книг на английском и других языках. Хороший источник классики и коротких текстов для загрузки в Language Puzzle.</p>
                <a href="https://www.gutenberg.org/" target="_blank" rel="noopener noreferrer">Открыть Project Gutenberg</a>
              </div>
            </article>
            <article class="help-resource-card">
              <img src="https://apps.ankiweb.net/logo.svg" alt="Anki logo">
              <div>
                <h3>Anki</h3>
                <p>Программа для интервального повторения: карточки возвращаются в нужный момент, чтобы память не проседала. Экспорт из Learn можно использовать для повторения слов с примерами и озвучкой.</p>
                <a href="https://apps.ankiweb.net/" target="_blank" rel="noopener noreferrer">Открыть Anki</a>
              </div>
            </article>
          </div>
        </div>
      </section>
    </section>
  `;
}

function renderDashboard() {
  if (!state.dashboard) return `<div class="empty">Dashboard загружается...</div>`;
  const data = state.dashboard || { stats: {}, documents: [] };
  const stats = data.stats;
  return `
    ${renderHeader("Мои тексты", "Загрузите текст, отметьте знакомое и смотрите, как растет покрытие.", `<a data-link href="/upload"><button class="primary">+ Загрузить</button></a>`)}
    <section class="grid stats">
      ${metric("Тексты", stats.documents_count || 0)}
      ${metric("Словарь", stats.vocabulary_count || 0)}
      ${metric("В изучении", stats.learning_words || 0)}
      ${metric("Среднее покрытие", `${stats.average_coverage || 0}%`)}
    </section>
    <section class="card" style="margin-top:16px">
      <table class="table desktop-table">
        <thead><tr><th>Название</th><th>Тип</th><th>Слов</th><th>Уникальных</th><th>Покрытие</th><th></th></tr></thead>
        <tbody>
          ${data.documents.length ? data.documents.map((doc) => `
            <tr>
              <td><a data-link href="/document/${doc.id}">${escapeHtml(doc.title)}</a></td>
              <td>${escapeHtml(doc.type)}</td>
              <td>${doc.total_words}</td>
              <td>${doc.unique_words}</td>
              <td><span class="pill known">${doc.coverage_percent}%</span></td>
              <td class="toolbar"><a data-link href="/document/${doc.id}"><button>Открыть</button></a><button class="icon" data-delete-doc="${doc.id}" title="Удалить">×</button></td>
            </tr>`).join("") : `<tr><td colspan="6"><div class="empty">Пока нет текстов. Первый анализ начинается с кнопки “Загрузить”.</div></td></tr>`}
        </tbody>
      </table>
      <div class="mobile-card-list dashboard-mobile-list">
        ${data.documents.length ? data.documents.map((doc) => `
          <article class="mobile-list-card">
            <div>
              <h3><a data-link href="/document/${doc.id}">${escapeHtml(doc.title)}</a></h3>
              <p class="meta">${escapeHtml(doc.type)} · ${doc.total_words} слов · ${doc.unique_words} уникальных</p>
            </div>
            <div class="mobile-card-actions">
              <span class="pill known">${doc.coverage_percent}%</span>
              <a data-link href="/document/${doc.id}"><button>Открыть</button></a>
              <button class="icon" data-delete-doc="${doc.id}" title="Удалить">×</button>
            </div>
          </article>
        `).join("") : `<div class="empty">Пока нет текстов. Первый анализ начинается с кнопки “Загрузить”.</div>`}
      </div>
    </section>
  `;
}

function metric(label, value) {
  return `<div class="card metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderUpload() {
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

function renderDocument() {
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

function renderDocumentViewSwitch(documentId, activeView) {
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
    <div class="detail-title">
      <h2>${escapeHtml(label)} <span class="pill status-${word.status}">${statusText(word.status)}</span></h2>
      ${renderTtsButton(label, `Озвучить ${label}`)}
    </div>
    ${translation ? `<p><strong>Перевод:</strong> ${escapeHtml(translation)}</p>` : ""}
    ${!isPhrase && transcription ? `<p><strong>Транскрипция:</strong> /${escapeHtml(transcription)}/</p>` : ""}
    ${examples.length ? `<div><strong>Пример в тексте:</strong><ul class="detail-examples">${examples.map((example) => `<li><span>${escapeHtml(example)}</span>${renderTtsButton(example, "Озвучить пример", "mini")}</li>`).join("")}</ul></div>` : ""}
    ${isPhrase ? `<p class="meta">Устойчивое выражение: ${escapeHtml(word.phrase_type || "phrase")}</p>` : ""}
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

function translationTooltip(value) {
  return cleanTranslation(value) || "";
}

function renderAnalysis() {
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

function renderKnowledge() {
  const context = state.knowledgeContext;
  const units = context?.units || [];
  const phrases = units.filter((item) => item.kind === "phrase");
  const selected = units.find((item) => knowledgeUnitKey(item) === state.selectedKnowledgeKey) || null;
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
              <button data-kg-bridge-id="${escapeHtml(bridge.id || "")}" data-kg-bridge="${escapeHtml(bridge.title)}" ${bridgeLoadingId && bridgeLoadingId === (bridge.id || "") ? "disabled" : ""}>
                <strong>${escapeHtml(bridge.title)}</strong>
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

function knowledgeUnitKey(item) {
  return `${item.kind === "phrase" ? "phrase" : "word"}:${item.knowledge_id}`;
}

function renderKnowledgeToken(item, selected) {
  const kind = item.kind === "phrase" ? "phrase" : "word";
  const status = item.status || "unknown";
  const active = selected && knowledgeUnitKey(item) === knowledgeUnitKey(selected);
  const nextStatus = status === "known" ? "unknown" : "known";
  return `
    <button
      class="cloud-token ${status} ${active ? "active" : ""}"
      data-kg-key="${escapeHtml(knowledgeUnitKey(item))}"
      data-kg-status="${item.knowledge_id}"
      data-kind="${kind}"
      data-status="${nextStatus}"
      data-tooltip-kind="${kind}"
      data-tooltip-id="${escapeHtml(item.knowledge_id || "")}"
      title="${escapeHtml(translationTooltip(item.translation_ru))}"
    >${escapeHtml(item.text)}</button>
  `;
}

function renderKnowledgeDetail(item) {
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
    ${example ? `<div><strong>Пример:</strong><ul class="detail-examples"><li><span>${escapeHtml(example)}</span>${renderTtsButton(example, "Озвучить пример", "mini")}</li></ul></div>` : ""}
  `;
}

function renderKnowledgeGroup(name, items) {
  const labels = { place: "Places", person: "People", action: "Actions", object: "Objects", phrase: "Phrases", problem: "Qualities" };
  return `
    <section class="graph-group">
      <h3>${labels[name] || name}</h3>
      <div>${items.length ? items.slice(0, 12).map((item) => `<span class="graph-node status-${item.status}">${escapeHtml(item.text)}</span>`).join("") : `<span class="meta">пусто</span>`}</div>
    </section>
  `;
}

function renderLearn() {
  const blocks = state.learnBlocks || [];
  const selectedCount = [...state.selectedLearnBlockIds].filter((id) => blocks.some((block) => block.id === id)).length;
  const allUnits = blocks.flatMap((block) => block.units || []);
  const selected = allUnits.find((unit) => learnUnitKey(unit) === state.selectedLearnKey) || allUnits[0] || null;
  if (selected) state.selectedLearnKey = learnUnitKey(selected);
  return `
    ${renderHeader("Learn", "Блоки слов для изучения.", selectedCount > 1 ? `<button class="primary" data-learn-merge>Объединить</button>` : "")}
    <section class="learn-layout">
      <div class="learn-board">
        ${blocks.length ? blocks.map((block) => renderLearnBlock(block, selectedCount, selected)).join("") : `<section class="card"><div class="empty">Пока нет блоков. Добавьте слова из Analysis или Knowledge.</div></section>`}
      </div>
      <aside class="card side-panel word-detail analysis-detail">
        ${renderLearnDetail(selected)}
      </aside>
    </section>
  `;
}

function renderLearnBlock(block, selectedCount, selectedUnit) {
  const selected = state.selectedLearnBlockIds.has(block.id);
  const filter = block.frequency_filter || "all";
  const units = filterLearnUnits(block.units || [], filter);
  const isAnkiGenerating = state.ankiGeneratingBlockId === block.id;
  return `
    <section class="card kg-theme-card learn-block">
      <div class="learn-block-head">
        <label class="learn-select-button ${selected ? "active" : ""}" title="Объединить блоки">
          <input type="checkbox" data-learn-select="${escapeHtml(block.id)}" ${selected ? "checked" : ""}>
          <span>✓</span>
        </label>
        <div class="toolbar">
          ${selectedCount > 1 && selected ? `<button class="primary" data-learn-merge>Объединить</button>` : ""}
          <button data-learn-delete="${escapeHtml(block.id)}">Удалить блок</button>
        </div>
      </div>
      <div>
        <h2>${escapeHtml(block.title)}</h2>
        <p class="subtle">${(block.units || []).length} слов · показано ${units.length}</p>
      </div>
      <div class="learn-filter-row">
        <label class="label learn-filter">Частотность
          <select data-learn-filter="${escapeHtml(block.id)}">
            ${learnFilterOptions().map(([value, label, description]) => `<option value="${value}" ${filter === value ? "selected" : ""}>${label} - ${description}</option>`).join("")}
          </select>
        </label>
        <button data-learn-anki="${escapeHtml(block.id)}" ${isAnkiGenerating ? "disabled" : ""}>${isAnkiGenerating ? "Генерация..." : "ANKI Generator"}</button>
      </div>
      ${isAnkiGenerating ? `<p class="notice learn-anki-notice">Идет генерация ANKI-файла и перевод примеров...</p>` : ""}
      <div>
        <h3>Vocabulary</h3>
        <div class="word-cloud kg-vocabulary">
          ${units.length ? units.map((item) => renderLearnToken(item, selectedUnit)).join("") : `<p class="subtle">В выбранном диапазоне пока пусто.</p>`}
        </div>
      </div>
    </section>
  `;
}

function learnUnitKey(item) {
  return `${item.kind === "phrase" ? "phrase" : "word"}:${item.knowledge_id}`;
}

function renderLearnToken(item, selected) {
  const status = item.status || "unknown";
  const kind = item.kind === "phrase" ? "phrase" : "word";
  const active = selected && learnUnitKey(item) === learnUnitKey(selected);
  const nextStatus = status === "known" ? "unknown" : "known";
  return `
    <button
      class="cloud-token learn-token ${status} ${active ? "active" : ""}"
      data-learn-token="${escapeHtml(learnUnitKey(item))}"
      data-learn-status="${escapeHtml(item.knowledge_id)}"
      data-learn-kind="${kind}"
      data-learn-next-status="${nextStatus}"
      data-tooltip-kind="${kind}"
      data-tooltip-id="${escapeHtml(item.knowledge_id || "")}"
      title="${escapeHtml(translationTooltip(item.translation_ru))}"
    >${escapeHtml(item.text)}</button>
  `;
}

function renderLearnDetail(item) {
  if (!item) return `<h2>Слово</h2><p class="subtle">Кликни по слову или фразе в блоке Learn.</p>`;
  return renderKnowledgeDetail(item);
}

function learnFilterOptions() {
  return [
    ["20-80", "20-80", "Самые полезные и частые слова"],
    ["50-50", "50-50", "50% самых частотных слов"],
    ["all", "Все", "Все слова блока"],
  ];
}

function filterLearnUnits(units, filter) {
  const sorted = [...(units || [])].sort((a, b) => learnFrequencyRank(a) - learnFrequencyRank(b) || String(a.text || "").localeCompare(String(b.text || "")));
  if (filter === "all" || !sorted.length) return sorted;
  if (filter === "20-80") return sorted.slice(0, Math.ceil(sorted.length * 0.2));
  if (filter === "50-50") return sorted.slice(0, Math.ceil(sorted.length * 0.5));
  return sorted;
}

function learnFrequencyRank(item) {
  const value = Number(item?.frequency_rank || 999999);
  return Number.isFinite(value) ? value : 999999;
}

function ankiFileName(title) {
  return String(title || "learn_block")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 80) || "learn_block";
}

function analysisUnitsForLearn(analysis) {
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

function knowledgeUnitsForLearn(context) {
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

function renderWords() {
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

function renderSettings() {
  const user = normalizeUser(state.user || {});
  const voices = ttsVoiceOptions(user.target_language);
  return `
    ${renderHeader("Настройки", "Языки MVP и учетная запись.")}
    <form class="card form" id="settingsForm">
      <label class="label">Email<input value="${escapeHtml(state.user.email)}" disabled></label>
      <div class="form-row">
        <label class="label">Родной язык<input value="${escapeHtml(state.user.native_language)}" disabled></label>
        <label class="label">Изучаемый язык<input value="${escapeHtml(state.user.target_language)}" disabled></label>
        <span></span>
      </div>
      <label class="checkbox-control">
        <input type="checkbox" name="tts_enabled" ${user.tts_enabled ? "checked" : ""}>
        <span>Включить TTS</span>
      </label>
      <label class="label">Голос
        <select name="tts_voice">
          <option value="">Авто (по языку)</option>
          ${voices.map((voice) => `<option value="${escapeHtml(voice.voiceURI)}" ${voice.voiceURI === user.tts_voice ? "selected" : ""}>${escapeHtml(`${voice.name} (${voice.lang})`)}</option>`).join("")}
        </select>
      </label>
      <div class="tts-grid">
        <label class="label">Скорость
          <div class="range-control">
            <input type="range" name="tts_rate" min="0.5" max="2" step="0.05" value="${Number(user.tts_rate || 1).toFixed(2)}" data-range-name="tts_rate">
            <span class="range-value" data-range-value="tts_rate">${formatRangeValue(user.tts_rate)}</span>
          </div>
        </label>
        <label class="label">Тон
          <div class="range-control">
            <input type="range" name="tts_pitch" min="0.5" max="2" step="0.05" value="${Number(user.tts_pitch || 1).toFixed(2)}" data-range-name="tts_pitch">
            <span class="range-value" data-range-value="tts_pitch">${formatRangeValue(user.tts_pitch)}</span>
          </div>
        </label>
        <label class="label">Громкость
          <div class="range-control">
            <input type="range" name="tts_volume" min="0" max="1" step="0.05" value="${Number(user.tts_volume || 1).toFixed(2)}" data-range-name="tts_volume">
            <span class="range-value" data-range-value="tts_volume">${formatRangeValue(user.tts_volume)}</span>
          </div>
        </label>
      </div>
      <label class="label">Тестовая фраза<input name="tts_preview_text" value="This is a TTS preview for your settings."></label>
      <div class="toolbar">
        <button type="button" data-tts-preview>▶ Проверить голос</button>
      </div>
      <button class="primary">Сохранить</button>
      <div class="settings-account-actions">
        <button type="button" class="ghost" data-logout>Выйти</button>
      </div>
    </form>
  `;
}

function normalizeUser(user) {
  return {
    ...user,
    tts_enabled: parseBool(user?.tts_enabled, true),
    tts_voice: String(user?.tts_voice || ""),
    tts_rate: clampNumber(user?.tts_rate, 1, 0.5, 2),
    tts_pitch: clampNumber(user?.tts_pitch, 1, 0.5, 2),
    tts_volume: clampNumber(user?.tts_volume, 1, 0, 1),
  };
}

function parseBool(value, fallback = true) {
  if (value === true || value === false) return value;
  if (value == null) return fallback;
  const text = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(text)) return true;
  if (["0", "false", "no", "off"].includes(text)) return false;
  return fallback;
}

function clampNumber(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function formatRangeValue(value) {
  return clampNumber(value, 1, 0, 2).toFixed(2);
}

function initTtsVoices() {
  if (ttsVoicesBound) return;
  if (!window.speechSynthesis) return;
  ttsVoicesBound = true;
  refreshTtsVoices();
  window.speechSynthesis.addEventListener("voiceschanged", refreshTtsVoices);
}

function refreshTtsVoices() {
  if (!window.speechSynthesis) {
    state.ttsVoices = [];
    return;
  }
  state.ttsVoices = window.speechSynthesis.getVoices() || [];
  if (state.route === "/settings") renderApp();
}

function ttsVoiceOptions(targetLanguage = "en") {
  const voices = state.ttsVoices || [];
  if (!voices.length) return [];
  const target = String(targetLanguage || "en").toLowerCase();
  const preferred = voices.filter((voice) => String(voice.lang || "").toLowerCase().startsWith(target));
  const secondary = voices.filter((voice) => !String(voice.lang || "").toLowerCase().startsWith(target));
  return [...preferred, ...secondary];
}

function resolveTtsVoice(voiceUri, targetLanguage = "en") {
  const voices = ttsVoiceOptions(targetLanguage);
  if (!voices.length) return null;
  if (voiceUri) {
    const selected = voices.find((voice) => voice.voiceURI === voiceUri);
    if (selected) return selected;
  }
  return voices[0] || null;
}

function speakText(text, overrideSettings = null) {
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

function renderTtsButton(text, title = "Озвучить", size = "default") {
  const className = size === "mini" ? "tts-btn tts-btn-mini" : "tts-btn";
  return `<button type="button" class="${className}" data-speak="${escapeHtml(text)}" title="${escapeHtml(title)}">▶</button>`;
}

function isDocumentReaderRoute() {
  return state.route.startsWith("/document/") && !state.route.endsWith("/analysis");
}

function looksLikeSubtitleText(value) {
  const text = String(value || "");
  return /\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b/.test(text);
}

function countTextLines(value) {
  const text = String(value || "");
  return text ? text.split(/\r\n|\r|\n/).length : 0;
}

function validateRawText(value) {
  const lines = countTextLines(value);
  if (lines > MAX_RAW_TEXT_LINES) {
    throw new Error(`Текст слишком длинный: ${lines} строк. Максимум ${MAX_RAW_TEXT_LINES} строк.`);
  }
}

function uploadFileExtension(fileName) {
  const match = String(fileName || "").toLowerCase().match(/\.[^.]+$/);
  return match ? match[0] : "";
}

function hasBinaryContent(bytes) {
  if (!bytes.length) return false;
  let suspicious = 0;
  for (const byte of bytes) {
    if (byte === 0) return true;
    const isAllowedControl = byte === 9 || byte === 10 || byte === 13;
    if (byte < 32 && !isAllowedControl) suspicious += 1;
  }
  return suspicious / bytes.length > 0.05;
}

async function readSupportedUploadFile(file) {
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

function bindRoute() {
  document.querySelectorAll("[data-delete-doc]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/documents/${button.dataset.deleteDoc}`, { method: "DELETE" });
      await loadRoute();
    });
  });

  document.querySelectorAll("[data-speak]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      speakText(button.dataset.speak || "");
    });
  });

  document.querySelectorAll("[data-range-name]").forEach((input) => {
    input.addEventListener("input", () => {
      const marker = document.querySelector(`[data-range-value="${input.dataset.rangeName}"]`);
      if (marker) marker.textContent = formatRangeValue(input.value);
    });
  });

  document.querySelector("#uploadForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const file = form.file.files[0];
    const submitButton = form.querySelector("button[type=submit]");
    const notice = form.querySelector("[data-upload-analysis-notice]");

    try {
      if (file) data.raw_text = await readSupportedUploadFile(file);
      validateRawText(data.raw_text);
    } catch (error) {
      state.message = error.message || "Не удалось прочитать файл или текст.";
      renderApp();
      return;
    }

    form.querySelectorAll("input, select, textarea, button").forEach((control) => {
      control.disabled = true;
    });
    if (submitButton) submitButton.textContent = "Анализируется...";
    if (notice) notice.hidden = false;
    state.message = "";

    try {
      if (looksLikeSubtitleText(data.raw_text)) data.type = "srt";
      const { document } = await api("/api/documents", { method: "POST", body: data });
      await navigate(`/document/${document.id}/analysis`);
    } catch (error) {
      state.message = error.message || "Не удалось выполнить анализ текста.";
      renderApp();
    }
  });

  document.querySelector("input[type=file]")?.addEventListener("change", async (event) => {
    const file = event.currentTarget.files[0];
    if (!file) return;
    try {
      const text = await readSupportedUploadFile(file);
      state.message = "";
      document.querySelector("textarea[name=raw_text]").value = text;
      if (!document.querySelector("input[name=title]").value) document.querySelector("input[name=title]").value = file.name.replace(/\.[^.]+$/, "");
      if (file.name.toLowerCase().endsWith(".srt") || looksLikeSubtitleText(text)) document.querySelector("select[name=type]").value = "srt";
    } catch (error) {
      event.currentTarget.value = "";
      state.message = error.message || "Не удалось прочитать файл.";
      renderApp();
    }
  });

  document.querySelector("textarea[name=raw_text]")?.addEventListener("paste", (event) => {
    const textarea = event.currentTarget;
    const pastedText = event.clipboardData?.getData("text") || "";
    const nextValue = `${textarea.value.slice(0, textarea.selectionStart)}${pastedText}${textarea.value.slice(textarea.selectionEnd)}`;
    if (countTextLines(nextValue) > MAX_RAW_TEXT_LINES) {
      event.preventDefault();
      state.message = `Текст из буфера слишком длинный. Максимум ${MAX_RAW_TEXT_LINES} строк.`;
      renderApp();
    }
  });

  document.querySelector("textarea[name=raw_text]")?.addEventListener("input", (event) => {
    try {
      validateRawText(event.currentTarget.value);
      if (state.message?.includes("строк")) state.message = "";
    } catch (error) {
      state.message = error.message;
    }
    if (looksLikeSubtitleText(event.currentTarget.value)) {
      document.querySelector("select[name=type]").value = "srt";
    }
  });

  document.querySelectorAll("[data-piece-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      pendingReaderScrollTop = document.querySelector(".document-reader")?.scrollTop ?? null;
      const piece = state.currentDocument.pieces[Number(button.dataset.pieceIndex)];
      const full = piece.type === "phrase"
        ? piece
        : state.currentDocument.analysis.words.find((word) => word.word_id === piece.word_id);
      const selected = { ...piece, ...(full || {}), type: piece.type };
      const status = selected.status === "known" ? "unknown" : "known";
      const kind = piece.type === "phrase" ? "phrase" : "word";
      const knowledgeId = piece.type === "phrase" ? selected.user_phrase_id : selected.user_word_id;
      if (!knowledgeId) {
        state.selectedWord = selected;
        renderApp();
        return;
      }
      await patchKnowledgeStatus(kind, knowledgeId, status);
      state.selectedWord = { ...selected, status };
      await ensureTranslation(kind, knowledgeId, state.selectedWord.translation_ru);
      renderApp();
    });
  });

  document.querySelectorAll("[data-cloud-kind]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.cloudKind;
      const id = button.dataset.cloudId;
      const nextStatus = button.dataset.cloudNextStatus || "known";
      state.selectedAnalysisKey = button.dataset.cloudKey || `${kind}:${id}`;
      await patchKnowledgeStatus(kind, id, nextStatus);
      await ensureTranslation(kind, id, localTranslation(kind, id));
      renderApp();
    });
  });

  document.querySelectorAll("[data-status]:not([data-kg-status])").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus(button.dataset.kind === "phrase" ? "phrase" : "word", button.dataset.knowledgeId, button.dataset.status);
      if (state.selectedWord && state.selectedWord.type) {
        const isPhrase = state.selectedWord.type === "phrase";
        const selectedKnowledgeId = isPhrase ? state.selectedWord.user_phrase_id : state.selectedWord.user_word_id;
        if (selectedKnowledgeId === button.dataset.knowledgeId) state.selectedWord = { ...state.selectedWord, status: button.dataset.status };
      }
      renderApp();
    });
  });

  document.querySelectorAll("[data-quick-word]").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus("word", button.dataset.quickWord, button.dataset.status);
      renderApp();
    });
  });

  document.querySelectorAll("[data-quick-phrase]").forEach((button) => {
    button.addEventListener("click", async () => {
      await patchKnowledgeStatus("phrase", button.dataset.quickPhrase, button.dataset.status);
      renderApp();
    });
  });

  document.querySelectorAll("[data-tooltip-kind][data-tooltip-id]").forEach((button) => {
    button.addEventListener("mouseenter", async () => {
      const kind = button.dataset.tooltipKind;
      const knowledgeId = button.dataset.tooltipId;
      if (!knowledgeId || cleanTranslation(button.getAttribute("title"))) return;
      await ensureTranslation(kind, knowledgeId, localTranslation(kind, knowledgeId), { render: false });
      const translation = cleanTranslation(localTranslation(kind, knowledgeId));
      if (translation) button.setAttribute("title", translation);
    }, { once: true });
  });

  document.querySelector("[data-words-next]")?.addEventListener("click", () => {
    state.wordsVisibleCount = Math.max(100, Number(state.wordsVisibleCount || 100)) + 100;
    renderApp();
  });

  document.querySelectorAll("[data-refresh-important]").forEach((button) => {
    button.addEventListener("click", async () => {
      const { analysis } = await api(`/api/documents/${button.dataset.refreshImportant}/analyze`, {
        method: "POST",
        body: { refresh_important: true }
      });
      state.currentAnalysis = analysis;
      state.analysisVisibleKeys = null;
      state.analysisVisibleDocId = button.dataset.refreshImportant;
      state.selectedAnalysisKey = null;
      renderApp();
    });
  });

  document.querySelectorAll("[data-analysis-to-learn]").forEach((button) => {
    button.addEventListener("click", async () => {
      const units = analysisUnitsForLearn(state.currentAnalysis);
      if (!units.length) {
        state.message = "В этом анализе нет новых слов для Learn.";
        renderApp();
        return;
      }
      await api("/api/learn/blocks", {
        method: "POST",
        body: { title: state.currentDocument?.title || "Analysis", units }
      });
      state.message = "Блок добавлен в Learn.";
      renderApp();
    });
  });

  document.querySelector("#knowledgeGraphForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    state.knowledgeInput = data.text || "";
    state.knowledgeLoading = true;
    state.message = "";
    renderApp();
    try {
      const { contexts, context } = await api("/api/knowledge/analyze", { method: "POST", body: data });
      state.knowledgeContexts = contexts || [context];
      state.knowledgeContext = context;
      state.selectedKnowledgeKey = null;
      state.message = "";
    } catch (error) {
      state.message = error.message || "Не удалось сгенерировать словарь.";
    } finally {
      state.knowledgeLoading = false;
      renderApp();
    }
  });

  document.querySelector("[data-knowledge-to-learn]")?.addEventListener("click", async () => {
    const units = knowledgeUnitsForLearn(state.knowledgeContext);
    if (!units.length) {
      state.message = "В Theme Card нет новых слов для Learn.";
      renderApp();
      return;
    }
    await api("/api/learn/blocks", {
      method: "POST",
      body: { title: state.knowledgeInput || state.knowledgeContext?.title || "Knowledge", units }
    });
    state.message = "Блок добавлен в Learn.";
    renderApp();
  });

  document.querySelectorAll("[data-learn-select]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selectedLearnBlockIds.add(input.dataset.learnSelect);
      else state.selectedLearnBlockIds.delete(input.dataset.learnSelect);
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-filter]").forEach((select) => {
    select.addEventListener("change", async () => {
      const { blocks } = await api(`/api/learn/blocks/${select.dataset.learnFilter}`, {
        method: "PATCH",
        body: { frequency_filter: select.value }
      }).then(async () => api("/api/learn"));
      state.learnBlocks = blocks || [];
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/learn/blocks/${button.dataset.learnDelete}`, { method: "DELETE" });
      state.selectedLearnBlockIds.delete(button.dataset.learnDelete);
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-anki]").forEach((button) => {
    button.addEventListener("click", async () => {
      const blockId = button.dataset.learnAnki;
      const block = (state.learnBlocks || []).find((item) => item.id === blockId);
      state.ankiGeneratingBlockId = blockId;
      state.message = "Идет генерация ANKI-файла...";
      renderApp();
      try {
        const response = await fetch(`/api/learn/blocks/${blockId}/anki`, {
          credentials: "same-origin",
          cache: "no-store"
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || data.detail || "Не удалось создать файл ANKI.");
        }
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${ankiFileName(block?.title || "learn_block")}_anki.txt`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
        state.message = "ANKI-файл готов и скачивание началось.";
      } catch (error) {
        state.message = error.message || "Не удалось создать файл ANKI.";
      } finally {
        state.ankiGeneratingBlockId = null;
        renderApp();
      }
    });
  });

  document.querySelectorAll("[data-learn-merge]").forEach((button) => {
    button.addEventListener("click", async () => {
      const block_ids = [...state.selectedLearnBlockIds];
      if (block_ids.length < 2) return;
      const { blocks } = await api("/api/learn/blocks/merge", {
        method: "POST",
        body: { block_ids }
      }).then(async () => api("/api/learn"));
      state.learnBlocks = blocks || [];
      state.selectedLearnBlockIds = new Set();
      renderApp();
    });
  });

  document.querySelectorAll("[data-learn-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.learnKind === "phrase" ? "phrase" : "word";
      const knowledgeId = button.dataset.learnStatus;
      state.selectedLearnKey = button.dataset.learnToken || `${kind}:${knowledgeId}`;
      await patchKnowledgeStatus(kind, knowledgeId, button.dataset.learnNextStatus || "known", { refreshAnalysis: true });
      await ensureTranslation(kind, knowledgeId, localTranslation(kind, knowledgeId));
      const { blocks } = await api("/api/learn");
      state.learnBlocks = blocks || [];
      const learnUnits = state.learnBlocks.flatMap((block) => block.units || []);
      if (!learnUnits.some((unit) => learnUnitKey(unit) === state.selectedLearnKey)) {
        state.selectedLearnKey = learnUnits[0] ? learnUnitKey(learnUnits[0]) : null;
      }
      renderApp();
    });
  });

  document.querySelectorAll("[data-kg-bridge]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bridgeTopic = button.dataset.kgBridge || "";
      const bridgeId = button.dataset.kgBridgeId || "";
      state.knowledgeInput = bridgeTopic;
      state.knowledgeBridgeLoadingId = bridgeId;
      state.knowledgeLoading = true;
      state.message = "";
      renderApp();
      try {
        const { contexts, context } = await api("/api/knowledge/bridge", {
          method: "POST",
          body: {
            context_id: bridgeId || `kg:${bridgeTopic.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
            bridge_title: bridgeTopic,
            starter_words: [],
            document_id: state.knowledgeContext?.document_id || null
          }
        });
        state.knowledgeContexts = contexts || [context];
        state.knowledgeContext = context;
        state.selectedKnowledgeKey = null;
        state.message = "";
      } catch (error) {
        state.message = error.message || "Не удалось сгенерировать словарь.";
      } finally {
        state.knowledgeBridgeLoadingId = null;
        state.knowledgeLoading = false;
        renderApp();
      }
    });
  });

  document.querySelectorAll("[data-kg-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.kind === "phrase" ? "phrase" : "word";
      state.selectedKnowledgeKey = button.dataset.kgKey || null;
      await patchKnowledgeStatus(kind, button.dataset.kgStatus, button.dataset.status);
      applyKnowledgeContextStatus(kind, button.dataset.kgStatus, button.dataset.status);
      await ensureTranslation(kind, button.dataset.kgStatus, localTranslation(kind, button.dataset.kgStatus));
      renderApp();
    });
  });

  document.querySelector("#settingsForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    data.native_language = state.user?.native_language || "ru";
    data.target_language = state.user?.target_language || "en";
    data.tts_enabled = form.querySelector("[name=tts_enabled]")?.checked ? "true" : "false";
    delete data.tts_preview_text;
    const { user } = await api("/api/settings", { method: "PATCH", body: data });
    state.user = normalizeUser(user);
    state.message = "Настройки сохранены.";
    renderApp();
  });

  document.querySelector("[data-tts-preview]")?.addEventListener("click", (event) => {
    event.preventDefault();
    const form = document.querySelector("#settingsForm");
    if (!form) return;
    const text = String(form.querySelector("[name=tts_preview_text]")?.value || "").trim();
    const tempSettings = {
      tts_enabled: form.querySelector("[name=tts_enabled]")?.checked ?? true,
      tts_voice: form.querySelector("[name=tts_voice]")?.value || "",
      tts_rate: form.querySelector("[name=tts_rate]")?.value,
      tts_pitch: form.querySelector("[name=tts_pitch]")?.value,
      tts_volume: form.querySelector("[name=tts_volume]")?.value,
    };
    speakText(text || "This is a voice preview.", tempSettings);
  });

  if (pendingReaderScrollTop !== null) {
    const reader = document.querySelector(".document-reader");
    if (reader) reader.scrollTop = pendingReaderScrollTop;
    pendingReaderScrollTop = null;
  }
}

async function patchKnowledgeStatus(kind, knowledgeId, status, options = {}) {
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

function applyLocalStatusUpdate(kind, knowledgeId, status) {
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

async function ensureTranslation(kind, knowledgeId, currentTranslation = "", options = {}) {
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

function localTranslation(kind, knowledgeId) {
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

function applyLocalTranslation(kind, knowledgeId, translation) {
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

function applyKnowledgeContextStatus(kind, knowledgeId, status) {
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

function updateKnowledgeContextStats(context) {
  const units = context?.units || [];
  const knownStatuses = new Set(["known", "ignored"]);
  context.known_count = units.filter((unit) => knownStatuses.has(unit.status)).length;
  context.unknown_count = units.filter((unit) => !knownStatuses.has(unit.status)).length;
  context.coverage_percent = units.length ? Math.round((context.known_count / units.length) * 100) : 0;
  context.phrases_count = units.filter((unit) => unit.kind === "phrase").length;
}

function statusButtons(knowledgeId, kind = "word") {
  return [
    ["known", "Знаю"],
    ["seen", "Примерно знаю"],
    ["learning", "Учу"],
    ["unknown", "Не знаю"],
    ["ignored", "Игнорировать"]
  ].map(([status, label]) => `<button data-kind="${kind}" data-knowledge-id="${knowledgeId}" data-status="${status}">${label}</button>`).join("");
}

function statusText(status) {
  return ({ unknown: "не знаю", seen: "примерно знаю", learning: "учу", known: "знаю", ignored: "игнор" })[status] || status;
}

function isShortWord(value) {
  const lettersOnly = String(value || "")
    .toLowerCase()
    .replace(/[^a-z]/g, "");
  return lettersOnly.length <= 1;
}

function buildUnknownCloudData(analysis, selectedKey, visibleKeys, documentId, sourceText = "") {
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

function posToCloudGroup(pos) {
  const value = (pos || "").toLowerCase();
  if (value === "verb" || value === "aux") return "verb";
  if (value === "noun" || value === "propn") return "noun";
  if (value === "adj") return "adjective";
  if (value === "adv") return "adverb";
  return "noun";
}

function cleanTranslation(value) {
  return value && value !== "перевод уточняется" ? value : "";
}

function cleanTranscription(value) {
  return String(value || "").replace(/\*/g, "").trim();
}

function cleanExample(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function extractSpanExample(text, start, end) {
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

function posLabel(pos) {
  return {
    verb: "verb",
    aux: "verb",
    noun: "noun",
    propn: "noun",
    adj: "adjective",
    adv: "adverb",
  }[(pos || "").toLowerCase()] || (pos || "word");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

boot();
