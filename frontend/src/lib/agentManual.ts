export type ManualSection = {
  id: string;
  title: string;
  body: string[];
};

export const AGENT_PAGE_MANUAL: ManualSection[] = [
  {
    id: "what",
    title: "Что это",
    body: [
      "Страница ставит PlanJob: идеи роликов по брифу аккаунта. Это не нижний чат и не тумблер «Агент работает» — тот тумблер запускает воркер очереди.",
      "Без живого воркера план встанет в очередь, но рендер и слоты календаря не поедут.",
    ],
  },
  {
    id: "plan",
    title: "Как поставить план",
    body: [
      "Выберите аккаунт, при необходимости пресет, заполните бриф. «Сколько роликов» и «Длительность, с» (5–10) уходят в PlanJob.",
      "«Запланировать» — один прогон. «План на неделю» раскладывает слоты на 7 дней с учётом капа и часов аккаунта. «Превью» ставит очередь рендера без слотов календаря.",
    ],
  },
  {
    id: "sources",
    title: "Источники и вопросы",
    body: [
      "URL в «Источники» — дополнительный контекст для плана. «Проверить» читает источник, не ставит ролики.",
      "Если бриф пустой или модели не хватает фактов, ниже появятся «Вопросы агента». Пока они открыты, следующий план упрётся в те же уточнения.",
    ],
  },
  {
    id: "runs",
    title: "Прогоны",
    body: [
      "Таблица — история PlanJob: модель, сколько идей вернулось, ошибка. Строка открывает промпт и JSON идей.",
    ],
  },
];

export const CHAT_MANUAL: ManualSection[] = [
  {
    id: "chat",
    title: "Что делает чат",
    body: [
      "Нижний чат вызывает tools в ту же SQLite, что и кнопки панели. Справочник модели — сжатый handbook, не этот мануал.",
      "Сломанный постинг, вход или прокси — секции handbook «Если постинг сломался» / «Если вход сломался» / «Если прокси сломался» и tool diagnose, не память.",
      "Неполная задача (нет username, прокси, ролика, промпта) — чат спросит уточнения. Пока нет ответа «Уточнения: …» — create не вызывает.",
    ],
  },
  {
    id: "limits",
    title: "Чего нет",
    body: [
      "Удалять ничего нельзя. Операторов, секретный путь и мастер-пароль чат не меняет.",
      "Живой Playwright из нижнего чата не стартует. Баннер «Агент остановлен» — воркер, не этот чат: задачи встанут, очередь не поедет.",
    ],
  },
  {
    id: "pay",
    title: "Оплата",
    body: [
      "Панель не касса. cost_usd — только оценка ролика fal (0.05 USD/с Wan 2.5). Часы Salad, VPS и прокси в эту цифру не входят.",
      "Salad тарится, пока группа Running: не пользуешься — Stop с карточки GPU Salad на Администрировании. Чат Start/Stop группы не вызывает. $/час Salad не выдумывать.",
    ],
  },
];

const PAGE_HINTS: Record<string, string> = {
  "/": "Сейчас панель: сводка очередей. Чат смотрит overview и открывает страницы здесь.",
  "/accounts": "Сейчас аккаунты: карточка, прокси, сессия. Чат создаёт и правит, удалять нельзя. Сломался вход или прокси — diagnose, не память.",
  "/publishing": "Сейчас библиотека: клипы, рендер, публикация. Чат не загружает файлы с диска и не удаляет клипы.",
  "/agent": "Сейчас страница Агент: план роликов (PlanJob), не этот чат и не тумблер воркера.",
  "/renders": "Сейчас рендеры: $ в таблице — fal. local на Salad тарится часами GPU, пока нода Running.",
  "/calendar": "Сейчас календарь. Новые слоты — enqueue_publish / plan_account; дату — reschedule_job.",
  "/activity": "Сейчас активность: публикации, рендеры, склейки. Одобрить / повторить / логи — tools чата.",
  "/maintenance": "Сейчас обслуживание: Ollama и копии базы. Чат делает diagnose, docker_logs, take_backup.",
  "/operators": "Сейчас доступы. Чат только list_operators — создать или отозвать нельзя.",
  "/settings": "Сейчас настройки владельца. Чат секретный путь и мастер-пароль не меняет.",
  "/administration": "Сейчас администрирование: вкладки Обзор, Блокнот и API. GPU Salad и карточка Оплата на Обзоре. Чат блокнот не читает, группу не стартует и Try it out не жмёт.",
};

const TOOL_HINTS: Record<string, string> = {
  overview: "Сводка из базы: аккаунты, клипы, публикации, рендеры — без выдуманных цифр.",
  list_accounts: "Список из SQLite: имя, площадка, статус, бриф, прокси.",
  account_details: "Полная карточка, включая секреты. Чат обязан отдать как есть.",
  list_posts: "Очередь публикаций PostJob, не PlanJob.",
  list_clips: "Клипы библиотеки на диске data/, не загрузка с вашего компьютера.",
  list_renders: "Очередь GenerationJob. Поедет, если воркер запущен. Колонка $ — fal, не Salad.",
  list_render_backends: "Кто жив в цепочке. fal при ключе списывает cost_usd; local — GPU-хост, пока Running.",
  list_compositions: "Склейки клипов библиотеки, не файлы с диска оператора.",
  list_proxies: "Прокси аккаунтов. К Ollama и чату они не относятся.",
  list_questions: "Открытые вопросы контент-агента со страницы /agent.",
  list_sources: "URL-источники плана. «Проверить» — check_source.",
  list_presets: "Пресеты брифа. В бриф — apply_preset.",
  list_plans: "История прогонов PlanJob, та же таблица на /agent.",
  apply_preset: "Подставляет текст пресета в бриф аккаунта.",
  list_errors: "Свежие ошибки из базы, не догадки про прокси.",
  list_operators: "Как устроены доступы. Создать или отозвать чат не может.",
  list_project_files: "Только внутри репозитория и data/.",
  read_project_file: "Содержимое файла проекта как есть, без выдумок.",
  job_logs: "Логи публикации и переход на Активность.",
  account_logs: "DiagnosticRun входа/проверки. Пароль в ответе скрыт.",
  open_page: "Откроет страницу в этой вкладке, URL сам не пишет.",
  open_clip: "Найдёт клип в библиотеке и откроет.",
  open_post: "Найдёт публикацию и откроет на Активности.",
  open_account: "Откроет карточку аккаунта.",
  screenshot_page: "Снимок в data/screenshots, только если попросили.",
  plan_account: "Ставит PlanJob. Нужен живой воркер. Если цепочка дойдёт до fal — cost_usd; local — часы Salad, не строка $.",
  preview_plan: "Очередь рендера без слотов календаря. Как кнопка «Превью».",
  enqueue_publish: "Слот в очереди PostJob. Нужны ролик на диске и аккаунт.",
  reschedule_job: "Новая дата слота. Drag календаря чат сам не делает.",
  pause_account: "Пауза аккаунта: новые публикации не едут.",
  resume_account: "Снимает паузу. Лимиты и cooldown остаются как в карточке.",
  answer_question: "Пишет ответ в вопрос контент-агента, как кнопка «Ответить».",
  add_source: "Добавляет URL в источники плана выбранного аккаунта.",
  check_source: "Читает источник. Ролики не ставит.",
  create_account: "Один аккаунт: username и существующий proxy_label. Instagram обычно ещё пароль.",
  create_accounts: "До 20 строк. Частичный успех: created и failed — не все создались.",
  update_account: "Лимиты, hold_for_review, login_surface, бриф. Удаления нет.",
  create_proxy: "Нужны label и url вида http://user:pass@host:port.",
  create_proxies: "До 20 прокси. Частичный успех вернётся как created и failed.",
  update_proxy: "Правит уже существующий прокси по label.",
  attach_proxy: "Привязывает proxy_label к аккаунту.",
  page_guide: "Секция handbook другой страницы. Не снимок экрана.",
  ask_operator: "Не хватает полей. Ответьте формой «Уточнения», иначе create не пойдёт.",
  diagnose: "Воркер, блоки posting / login / proxies (очередь, сессии, geo, hints), Ollama, движки рендера, хвост data/app.log. Сломанный постинг, вход или прокси — не память. GPU 503 при Stop Salad — не выдумывать $/час, цитата ошибки.",
  docker_logs: "Только сервисы compose панели, не произвольный контейнер.",
  approve_job: "Публикация в awaiting_review. Без одобрения воркер её не берёт.",
  cancel_job: "Отмена после подтверждения. Сама собой не отменяет.",
  retry_job: "Повтор failed/dead публикации.",
  start_worker: "Запуск воркера очереди. Без него план, fal и публикация стоят.",
  stop_worker: "Остановка только своего процесса и только после подтверждения.",
  take_backup: "Копия базы, как кнопка на Обслуживании. Restore в чате нет.",
  test_proxy: "Проверка одного прокси. К чату и Ollama не относится.",
  test_proxies: "Пакетная проверка прокси.",
  test_connection: "Та же проверка, что «Подключение» на аккаунте.",
  test_connections: "Пакетная проверка подключений.",
  export_cookies: "Скачает файл в браузере, как кнопка модалки «Сессия».",
  export_fingerprint: "Только Instagram (instagrapi device).",
  export_playwright_state: "state.json Studio для YouTube/TikTok.",
  import_cookies: "JSON Dolphin или Playwright state. Нет данных — уточнения.",
  import_fingerprint: "Только Instagram.",
  get_session: "Instagram: sessionid; Studio: есть ли state.json, без значений cookies.",
  publish_now: "Сначала проверка подключения. Если не ok — ролика не ставит.",
  first_login: "Автовход только Instagram. Живой браузер из этого чата не откроет.",
  mint_mobile_session: "Mobile-сессия только Instagram.",
  retry_render: "Повтор GenerationJob.",
  cancel_render: "Отмена рендера после подтверждения.",
  create_render: "Промпт обязателен. backend auto. fal пишет cost_usd (0.05 USD/с Wan 2.5). local — часы Salad, пока Running; не пользуешься — Stop.",
  generate_wan: "Ролик на Wan (local). Пока рендерится, чат-модель на этой видеокарте выгружается. Ждать — только если попросили.",
  compose: "Нужны минимум два clip_ids из библиотеки.",
  cancel_composition: "Отмена склейки после подтверждения.",
  retry_composition: "Повтор склейки.",
  refresh_stats: "Обновить статистику публикации, как кнопка в библиотеке.",
};

export function pageHint(page: string | undefined): string {
  const path = (page || "/").split("?")[0] || "/";
  return PAGE_HINTS[path] ?? PAGE_HINTS["/"] ?? "";
}

export function toolHint(name: string | undefined): string {
  if (!name) return "";
  return TOOL_HINTS[name] ?? "";
}

export type AgentWorkState = {
  accounts: number;
  brief: string;
  questions: number;
  busy: boolean;
  autoSchedule: boolean;
};

export function agentWorkHint(state: AgentWorkState): string {
  if (state.accounts === 0) {
    return "Сначала аккаунт на странице Аккаунты. Без него план не ставится.";
  }
  if (!state.brief.trim()) {
    return "Бриф пустой — план задаст вопросы в блоке ниже. Лучше написать нишу и тон заранее.";
  }
  if (state.questions > 0) {
    return "Есть открытые вопросы агента. Ответьте, иначе следующий план упрётся в те же уточнения.";
  }
  if (state.busy) {
    return "План в очереди PlanJob. Прогоны — таблица ниже. Ролики поедут, если воркер запущен.";
  }
  if (!state.autoSchedule) {
    return "«Сразу ставить в расписание» выключено: слотов в календаре не будет, только очередь рендера.";
  }
  return "Запланировать ставит PlanJob. План на неделю раскладывает слоты на 7 дней. Превью — очередь рендера без календаря.";
}
