export type CostSection = {
  id: string;
  title: string;
  body: string[];
};

export const COST_SECTIONS: CostSection[] = [
  {
    id: "rule",
    title: "Правило",
    body: [
      "Панель не касса: списаний из UI нет. Деньги берут кабинеты снаружи. Ключи, GPU-URL и секретный путь сюда не пишем.",
      "cost_usd в SQLite (колонка $ на Рендерах и в прогонах Агента) — оценка ролика fal. Часы Salad, счёт VPS и прокси в эту цифру не входят.",
    ],
  },
  {
    id: "what",
    title: "Что",
    body: [
      "Платить: админ-VPS (compose без Ollama), Salad GPU пока группа Running (AGENT_BASE_URL и WAN_BASE_URL), либо Clore/Vast вместо Salad, не оба сразу; fal.ai при FAL_API_KEY; прокси аккаунтов — продавцу прокси.",
      "huggingface / pollinations / hfspace в cost_usd пишут 0. Telegram-бот бесплатный. Graph / YouTube Data API / TikTok Content Posting не используются — им не платить.",
    ],
  },
  {
    id: "when",
    title: "Когда",
    body: [
      "VPS — пока машина жива. Salad — с Ready до Stop: простой Running тарится, первый pull образа на узел — нет. Start после Stop снова качает образ. Start/Stop — карточка GPU Salad на этой странице, не кабинет Salad и не тумблер воркера.",
      "fal — успешный ролик backend=fal (в том числе из auto). local — часы GPU-хоста, не строка $. Чат и PlanJob — пока нода AGENT_BASE_URL Running. Одна 24 GB карта: чат XOR видео.",
    ],
  },
  {
    id: "where",
    title: "Где",
    body: [
      "Salad: кабинет для баланса и кредитов USDC / EURC / RENDER в Solana, не USDT. Группу Start/Stop — карточка GPU Salad выше. fal: dashboard fal.ai. HF: billing Hugging Face. Прокси и VPS — кабинеты продавца и хостера.",
      "В панели балансы не читаются. Карточка Оплата на этой странице; колонка $ на /renders и прогоны /agent.",
    ],
  },
  {
    id: "volume",
    title: "Объём",
    body: [
      "fal Wan 2.5: 0.05 USD за секунду выхода (код app/generation/fal.py). Клип 5 с = 0.25, 10 с = 0.50. Неизвестная модель — 0.0, не выдумывать.",
      "Salad $/час в репозиторий не зашит: смотри баланс в кабинете. Не пользуешься — Stop группы с карточки GPU Salad. reels-ollama на 6 GB админки не поднимать.",
    ],
  },
];
