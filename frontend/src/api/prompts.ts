export interface Prompt {
  label: string;
  text: string;
}

export interface PromptGroup {
  title: string;
  hint: string;
  prompts: Prompt[];
}

function p(text: string, label = text): Prompt {
  return { label, text };
}

export function library(usernames: string[]): PromptGroup[] {
  const groups: PromptGroup[] = [
    {
      title: "Разобраться",
      hint: "что происходит прямо сейчас",
      prompts: [
        p("что застряло?"),
        p("какие публикации ждут моего одобрения?"),
        p("что вышло за последние сутки?"),
        p("какие рендеры сейчас выполняются?"),
        p("что сломалось и почему?"),
        p("что ты умеешь?"),
        p("что сломалось в коде?"),
        p("покажи логи docker api"),
      ],
    },
    {
      title: "Открыть",
      hint: "перейти туда, где это делается",
      prompts: [
        p("открой аккаунты"),
        p("открой прокси"),
        p("открой библиотеку"),
        p("открой очередь"),
        p("открой календарь"),
        p("открой агента"),
        p("открой обслуживание"),
      ],
    },
    {
      title: "Сделать",
      hint: "агент сам ставит план, публикации, аккаунты и прокси",
      prompts: [
        p("поставь план на 5 роликов для первого активного аккаунта"),
        p("поставь план на неделю"),
        p("покажи аккаунты и поставь на паузу тот, который заблокирован, если он на паузе не стоит"),
        p("как добавить аккаунт?"),
        p("как добавить прокси?"),
        p("что нужно для публикации?"),
        p("как работают доступы?"),
      ],
    },
  ];
  if (usernames.length) {
    groups.push({
      title: "Аккаунты",
      hint: "по имени",
      prompts: [
        ...usernames.slice(0, 6).map((name) =>
          p(`открой аккаунт ${name} и покажи, что у него в очереди`, name)
        ),
        p(`покажи пароль аккаунта ${usernames[0]}`, `пароль ${usernames[0]}`),
      ],
    });
  }
  return groups;
}

export function search(groups: PromptGroup[], needle: string): PromptGroup[] {
  const q = needle.trim().toLowerCase();
  if (!q) return groups;
  return groups
    .map((group) => ({
      ...group,
      prompts: group.prompts.filter(
        (prompt) => prompt.label.toLowerCase().includes(q) || prompt.text.toLowerCase().includes(q)
      ),
    }))
    .filter((group) => group.prompts.length > 0);
}
