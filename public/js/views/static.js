// Full-page standalone screens that render outside the app shell:
// auth (login/register/verify), public landing and help.

import { api } from "../api.js";
import { state } from "../state.js";
import { escapeHtml, isValidEmail, normalizeUser } from "../utils.js";
import { initTtsVoices } from "../tts.js";
import { navigate } from "../router.js";
import { renderApp } from "./shell.js";

const app = document.querySelector("#app");

let turnstileToken = "";

async function loadPublicConfig() {
  if (state.publicConfig) return state.publicConfig;
  try {
    state.publicConfig = await api("/api/config");
  } catch {
    state.publicConfig = { turnstile_enabled: false, turnstile_site_key: "" };
  }
  return state.publicConfig;
}

function mountTurnstile() {
  const cfg = state.publicConfig;
  if (!cfg?.turnstile_enabled || !cfg.turnstile_site_key) return;
  const container = document.querySelector("#turnstileBox");
  if (!container) return;
  const render = () => window.turnstile?.render(container, {
    sitekey: cfg.turnstile_site_key,
    callback: (token) => { turnstileToken = token; },
  });
  if (window.turnstile) {
    render();
  } else if (!document.querySelector("#turnstileScript")) {
    const script = document.createElement("script");
    script.id = "turnstileScript";
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    script.defer = true;
    script.onload = render;
    document.head.appendChild(script);
  }
}

export function renderAuth() {
  const isReset = state.route === "/reset";
  const isRegister = state.route === "/register";
  const isVerification = isRegister && state.pendingRegistrationEmail;
  const heading = isReset ? "Восстановление пароля" : isVerification ? "Подтвердите email" : isRegister ? "Регистрация" : "Вход";
  const subtitle = isReset
    ? "Укажите email — пришлём временный пароль."
    : isVerification
      ? `Мы отправили код на ${escapeHtml(state.pendingRegistrationEmail)}.`
      : isRegister
        ? "Введите email и пароль, чтобы создать аккаунт."
        : "Войдите по email и паролю.";

  let formInner;
  if (isReset) {
    formInner = `
      <label class="label">Email<input name="email" type="email" autocomplete="email" inputmode="email" required autofocus></label>
      <button class="primary" type="submit">Отправить временный пароль</button>`;
  } else if (isVerification) {
    formInner = `
      <label class="label">Код из письма<input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required autofocus></label>
      <button class="primary" type="submit">Подтвердить и войти</button>
      <button class="ghost" type="button" id="changeEmailBtn">Изменить email</button>`;
  } else {
    formInner = `
      <label class="label">Email<input name="email" type="email" autocomplete="email" inputmode="email" pattern="[^\\s@]+@[^\\s@]+\\.[^\\s@]+" required></label>
      <label class="label">Пароль<input name="password" type="password" autocomplete="${isRegister ? "new-password" : "current-password"}" required></label>
      ${isRegister ? `<div id="turnstileBox" class="turnstile-box"></div>` : ""}
      <button class="primary" type="submit">${isRegister ? "Создать аккаунт" : "Войти"}</button>`;
  }

  const footerLink = isReset
    ? `<a data-link href="/login">Вернуться ко входу</a>`
    : isRegister
      ? `Уже есть аккаунт? <a data-link href="/login">Войти</a>`
      : `Нужен аккаунт? <a data-link href="/register">Зарегистрироваться</a>`;
  const forgotLink = (!isRegister && !isReset && !isVerification)
    ? `<p><a data-link href="/reset">Забыли пароль?</a></p>`
    : "";

  app.innerHTML = `
    <main class="auth">
      <a class="auth-home" data-link href="/">Language Puzzle</a>
      <section class="card auth-card">
        <h1>${heading}</h1>
        <p class="subtle">${subtitle}</p>
        <form class="form" id="authForm">${formInner}</form>
        ${forgotLink}
        <p>${footerLink}</p>
        ${state.message ? `<p class="notice">${escapeHtml(state.message)}</p>` : ""}
      </section>
    </main>
  `;

  if (isRegister) {
    turnstileToken = "";
    loadPublicConfig().then(() => mountTurnstile());
  }

  document.querySelector("#changeEmailBtn")?.addEventListener("click", () => {
    state.pendingRegistrationEmail = "";
    state.message = "";
    renderAuth();
  });

  document.querySelector("#authForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (isReset) {
        if (!isValidEmail(form.email)) {
          state.message = "Введите корректный email.";
          renderAuth();
          return;
        }
        await api("/api/password/reset-request", { method: "POST", body: { email: form.email } });
        state.message = "Если email зарегистрирован, мы отправили временный пароль.";
        renderAuth();
        return;
      }
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
        form.captcha_token = turnstileToken;
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
      await navigate(user.must_change_password ? "/settings" : "/dashboard");
      if (user.must_change_password) {
        state.message = "Войдено по временному паролю. Смените пароль в настройках.";
        renderApp();
      }
    } catch (error) {
      state.message = error.message;
      renderAuth();
    }
  });
}

export function renderLanding() {
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
      <section class="landing-contacts">
        <div class="landing-contacts-inner">
          <h2>Помогите сделать Language Puzzle лучше</h2>
          <p>Сервис находится в развитии, поэтому нам очень важна обратная связь. Если вы нашли ошибку, столкнулись с неудобством или хотите предложить идею — напишите на <a class="contacts-email" href="mailto:language.puzzle.com@gmail.com">language.puzzle.com@gmail.com</a>.</p>
        </div>
      </section>
    </main>
  `;
}

export function renderPublicHelp() {
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

export function renderHelp() {
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
