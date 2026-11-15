import { apiLink, type DocSpan } from "./docText";

export type ConnectionsSection = {
  id: string;
  title: string;
  body: DocSpan[][];
};

export const CONNECTIONS_INTRO: DocSpan[] = [
  "Здесь описывается внешний доступ к агенту панели и к модели. Ключ шлюза и тумблер ниже управляют ",
  apiLink("POST /mcp"),
  " и ",
  apiLink("GET /llm/v1/{path}"),
  "; они не заменяют Bearer сессии для методов вроде ",
  apiLink("POST /api/assistant/jobs"),
  ".",
];

export const CONNECTIONS_SECTIONS: ConnectionsSection[] = [
  {
    id: "purpose",
    title: "Назначение",
    body: [
      [
        "Два внешних канала к API: JSON-RPC ",
        apiLink("POST /mcp"),
        " с инструментом chat — запускается тот же прогон агента владельца, что из чата (аккаунты, рендеры, внутренний браузер); путь ",
        apiLink("GET /llm/v1/{path}"),
        " и ",
        apiLink("POST /llm/v1/{path}"),
        " только пересылают запросы к модели по AGENT_BASE_URL и инструменты панели не вызывают.",
      ],
      [
        "Программный прогон с полным контролем (пауза, журнал, статусы) оформляется через ",
        apiLink("POST /api/assistant/jobs"),
        " с заголовком Authorization: Bearer текущей сессии панели — как на вкладке API. Отчёты и строки журнала читаются через ",
        apiLink("GET /api/agent-reports"),
        " и ",
        apiLink("GET /api/agent-reports/logs"),
        ".",
      ],
    ],
  },
  {
    id: "keys",
    title: "Ключи",
    body: [
      [
        "Ключ шлюза хранится в SQLite (поле llm_gateway_token) и не совпадает с паролем панели, ADMIN_TOKEN и паролем оператора. Клиенты MCP и OpenAI-совместимые передают его как Bearer в ",
        apiLink("POST /mcp"),
        " и ",
        apiLink("GET /llm/v1/{path}"),
        ".",
      ],
      [
        "Владелец (или открытый режим без пароля) получает ключ методом ",
        apiLink("GET /api/llm-gateway/credentials"),
        "; смена — ",
        apiLink("POST /api/llm-gateway/rotate"),
        ". После ротации предыдущий ключ сразу перестаёт приниматься.",
      ],
    ],
  },
  {
    id: "enable",
    title: "Включение",
    body: [
      [
        "Перед первым внешним вызовом шлюз нужно включить тумблером «Шлюз включён» ниже или запросом ",
        apiLink("POST /api/llm-gateway/enabled"),
        " с телом ",
        '{ "enabled": true }',
        ". Пока шлюз выключен, ",
        apiLink("POST /mcp"),
        " и ",
        apiLink("GET /llm/v1/{path}"),
        " отвечают HTTP 503.",
      ],
      [
        "Включение не запускает GPU Salad и не меняет AGENT_BASE_URL: проверяется только доступность уже настроенной модели (поле upstream_ok в ответе credentials).",
      ],
    ],
  },
  {
    id: "mcp",
    title: "MCP",
    body: [
      [
        "Сервер отвечает на ",
        apiLink("POST /mcp"),
        " по протоколу MCP (JSON-RPC 2.0). Для Cursor и аналогов в конфиг вставляется блок mcp_json из карточки ниже: в нём уже указаны mcp_url и заголовок Authorization.",
      ],
      [
        "Доступный инструмент — chat. В tools/call передаётся prompt (строка) или messages (массив role/content, как в OpenAI). Сервер стартует один прогон actor=owner с allow_browser=true и дожидается завершения; если агент уже выполняет задачу, возвращается занятость без второго прогона.",
      ],
      [
        "Заголовок запроса: Authorization: Bearer <ключ шлюза>. Content-Type: application/json. Подробности полей — в описании операции ",
        apiLink("POST /mcp"),
        " на вкладке API.",
      ],
    ],
  },
  {
    id: "openai",
    title: "OpenAI-совместимый API",
    body: [
      [
        "В Cursor (Models → OpenAI Compatible) или другом клиенте указываются Base URL и API Key из карточки ниже. Имя модели — значение AGENT_MODEL на сервере (поле model в credentials), например qwen3:30b-a3b.",
      ],
      [
        "Этот канал подходит для прямого чата с моделью (completions, chat). Чтобы выполнить задачу агента в панели, используется MCP chat или ",
        apiLink("POST /api/assistant/jobs"),
        ", а не только ",
        apiLink("POST /llm/v1/{path}"),
        ".",
      ],
    ],
  },
  {
    id: "network",
    title: "Адрес и порты",
    body: [
      [
        "URL в карточке строятся из Host запроса к панели (с учётом X-Forwarded-Host за внешним nginx). Образ reels-frontend проксирует /api/, /mcp и /llm/ на reels-api:8000, поэтому при доступе к панели с порта 3000 те же адреса в mcp_json и base_url работают без смены порта.",
      ],
      [
        "Если открыт только прямой порт API (8000 на хосте), допустимо подставлять тот же хост с :8000 вместо порта UI. Секретный путь входа в панель в URL шлюза не участвует.",
      ],
    ],
  },
];