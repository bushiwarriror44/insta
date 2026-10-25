import { api, formatApiError } from "../api/client";
import type { AccountOut, PostType } from "../api/types";
import type { FormKind } from "./setupForms";

export type FormSubmitOk = {
  userLine: string;
  assistantLine: string;
  created?: { accounts?: number[]; proxies?: number[] };
};

function trim(answers: Record<string, string>, id: string): string {
  return (answers[id] ?? "").trim();
}

function postTypeForPlatform(platform: string | null | undefined): PostType {
  if (platform === "youtube") return "youtube_short";
  if (platform === "tiktok") return "tiktok";
  return "reel";
}

export async function submitSetupForm(
  kind: FormKind,
  answers: Record<string, string>
): Promise<FormSubmitOk> {
  if (kind === "account") {
    const platform = (trim(answers, "platform") || "instagram") as
      | "instagram"
      | "youtube"
      | "tiktok";
    const created = await api.accounts.create({
      username: trim(answers, "username"),
      platform,
      password: trim(answers, "password"),
      proxy_label: trim(answers, "proxy_label"),
      email: trim(answers, "email") || null,
      email_password: trim(answers, "email_password") || null,
      imap_host: trim(answers, "imap_host") || null,
      login_identifier: trim(answers, "login_identifier") || null,
      vendor_line: trim(answers, "vendor_line") || null,
      totp_seed: trim(answers, "totp_seed") || null,
    });
    return {
      userLine: `Форма аккаунта: @${created.username} (${created.platform})`,
      assistantLine: `Аккаунт @${created.username} создан (id=${created.id}).`,
      created: { accounts: [created.id] },
    };
  }

  if (kind === "proxy") {
    const created = await api.proxies.create({
      label: trim(answers, "label"),
      url: trim(answers, "url"),
      country: trim(answers, "country") || null,
      skip_health_check: true,
    });
    return {
      userLine: `Форма прокси: ${created.label}`,
      assistantLine: `Прокси «${created.label}» создан (id=${created.id}).`,
      created: { proxies: [created.id] },
    };
  }

  const accountId = Number(trim(answers, "account_id"));
  if (!Number.isFinite(accountId) || accountId <= 0) {
    throw new Error("Выберите аккаунт");
  }
  const filename = trim(answers, "filename");
  if (!filename) throw new Error("Выберите файл из библиотеки");

  let account: AccountOut | undefined;
  try {
    const accounts = await api.accounts.list();
    account = accounts.find((row) => row.id === accountId);
  } catch {
    account = undefined;
  }
  if (!account) throw new Error(`Аккаунт id=${accountId} не найден`);

  const explicitType = trim(answers, "post_type") as PostType | "";
  const postType =
    explicitType === "reel" ||
    explicitType === "youtube_short" ||
    explicitType === "tiktok"
      ? explicitType
      : postTypeForPlatform(account.platform);

  const whenRaw = trim(answers, "when");
  let when: string | null = null;
  if (whenRaw) {
    const parsed = new Date(whenRaw);
    when = Number.isNaN(parsed.getTime()) ? whenRaw : parsed.toISOString();
  }

  const job = await api.jobs.enqueue({
    username: account.username,
    account_id: account.id,
    media_filename: filename,
    post_type: postType,
    title: trim(answers, "title") || null,
    caption_template: trim(answers, "caption") || null,
    description: trim(answers, "description") || null,
    tags: trim(answers, "tags") || null,
    when,
  });

  return {
    userLine: `Форма публикации: @${account.username} · ${filename}`,
    assistantLine: when
      ? `Публикация запланирована (job id=${job.id}).`
      : `Публикация добавлена в очередь (job id=${job.id}).`,
  };
}

export function formSubmitError(err: unknown): string {
  return formatApiError(err);
}
