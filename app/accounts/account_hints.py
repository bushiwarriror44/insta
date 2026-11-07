"""Operator-facing hints for account login and connection diagnostics (Russian UI + agent)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.api.schemas import AccountConnectionTestOut, FirstLoginOut
    from app.db import Account

HintSeverity = Literal["info", "warn", "error"]


@dataclass(frozen=True)
class AccountUserHint:
    severity: HintSeverity
    title: str
    message: str
    steps: tuple[str, ...] = ()
    action_key: str | None = None
    action_label: str | None = None

    def to_api_dict(self) -> dict:
        out: dict = {
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "steps": list(self.steps),
        }
        if self.action_key:
            out["action_key"] = self.action_key
        if self.action_label:
            out["action_label"] = self.action_label
        return out


def _log_blob(out) -> str:
    parts: list[str] = []
    err = getattr(out, "error", None) or ""
    if err:
        parts.append(str(err))
    for line in getattr(out, "logs", None) or []:
        msg = getattr(line, "message", None) or ""
        if msg:
            parts.append(str(msg))
    nested = getattr(out, "connection_test", None)
    if nested is not None:
        parts.append(_log_blob(nested))
    return "\n".join(parts).lower()


def _platform_value(account: Account) -> str:
    value = getattr(account, "platform", None)
    if hasattr(value, "value"):
        return value.value
    return value or "instagram"


def hint_for_first_login(out: FirstLoginOut, account: Account) -> AccountUserHint | None:
    if out.ok:
        return None

    blob = _log_blob(out)
    username = account.username
    platform = _platform_value(account)

    if platform == "instagram" and (
        "2fa" in blob
        or "totp" in blob
        or "two_step" in blob
        or "two-factor" in blob
        or "двухфактор" in blob
    ):
        return AccountUserHint(
            severity="warn",
            title="Требуется двухфакторная авторизация",
            message=(
                "Instagram запросил код приложения-аутентификатора или подтверждение входа. "
                "Автовход без браузера не завершится."
            ),
            steps=(
                "Нажмите «Открыть браузер» — войдите в Instagram через прокси аккаунта (VNC).",
                "Либо добавьте секрет TOTP в карточке аккаунта и повторите автовход.",
            ),
            action_key="open_session_browser",
            action_label="Открыть браузер",
        )

    if "challenge.timeout" in blob or ("таймаут" in blob and "challenge" in blob):
        return AccountUserHint(
            severity="warn",
            title="Код не получен вовремя",
            message="Время ожидания кода подтверждения истекло.",
            steps=(
                "Проверьте пароль почты в карточке аккаунта.",
                f"Повторите автовход или положите код в data/challenges/{username}.code.",
            ),
            action_key="submit_code",
            action_label="Повторить с кодом",
        )

    if out.challenge or "challenge" in blob or "two_step_verification" in blob:
        if "authenticationfailed" in blob or "email.imap_error" in blob or "imap" in blob:
            return AccountUserHint(
                severity="warn",
                title="Код подтверждения на почте",
                message=(
                    "Instagram запросил код, но автоматически прочитать почту не удалось "
                    "(неверный пароль IMAP или блокировка onet.pl)."
                ),
                steps=(
                    "Аккаунты → редактировать → проверьте «Пароль почты» и при необходимости IMAP "
                    "(для onet.pl: imap.poczta.onet.pl).",
                    "Введите код через агента (submit_login_code) или положите его в "
                    f"data/challenges/{username}.code и снова вызовите автовход.",
                    "Либо вкладка «Через браузер» / VNC в настройке сессии.",
                ),
                action_key="edit_account_email",
                action_label="Исправить пароль почты",
            )
        return AccountUserHint(
            severity="info",
            title="Нужно подтверждение",
            message="Instagram запросил код из почты, 2FA или проверку безопасности.",
            steps=(
                "Нажмите «Открыть браузер» и завершите вход в noVNC.",
                "Код из почты: provide-code или файл data/challenges/<user>.code.",
                "При 2FA можно указать секрет TOTP в карточке аккаунта.",
            ),
            action_key="open_session_browser",
            action_label="Открыть браузер",
        )

    if "verification" in blob and ("email" in blob or "caa" in blob):
        return AccountUserHint(
            severity="info",
            title="Код на почту",
            message="Instagram отправил код подтверждения на email аккаунта.",
            steps=(
                "Проверьте «Пароль почты» в карточке аккаунта (IMAP onet.pl: imap.poczta.onet.pl).",
                f"Код в data/challenges/{username}.code или submit_login_code в агенте.",
                "Либо вкладка «Через браузер».",
            ),
            action_key="edit_account_email",
            action_label="Пароль почты",
        )

    if (
        "pleasewaitfewminutes" in blob
        or "please wait" in blob
        or "spam" in blob
        or "checkpoint" in blob
    ):
        return AccountUserHint(
            severity="info",
            title="Instagram просит подождать",
            message="Слишком частые попытки входа или временная блокировка.",
            steps=(
                "Подождите 15–60 минут и не запускайте mobile probe подряд.",
                "Войдите через «Через браузер» / VNC, если срочно.",
            ),
            action_key="open_session_browser",
            action_label="Войти через браузер",
        )

    if "поля формы входа не найдены" in blob or "login_form_failed" in blob:
        return AccountUserHint(
            severity="warn",
            title="Браузер не нашёл форму входа",
            message="Страница Instagram изменилась или мешает баннер cookies.",
            steps=(
                "Откройте вкладку «Через браузер» или VNC и войдите вручную.",
                "Либо импортируйте cookie sessionid (вкладка «Вручную»).",
                "Скрин ошибки сохранён ниже в этом окне, если доступен login_debug.",
            ),
            action_key="open_session_browser",
            action_label="Войти через браузер",
        )

    if "playwright" in blob and ("не установлен" in blob or "install-playwright" in blob):
        return AccountUserHint(
            severity="error",
            title="Нет браузера Playwright",
            message="Chromium для автовхода не установлен на сервере.",
            steps=(
                "Docker: docker compose exec reels-api python -m app.cli install-playwright",
                "Windows: задайте PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\\ms-playwright",
            ),
            action_key="install_playwright",
            action_label="Инструкция в логе",
        )

    if "out of date" in blob or "needs_upgrade" in blob:
        return AccountUserHint(
            severity="warn",
            title="Устарела версия Instagram API",
            message="Мобильный клиент отклонён сервером Instagram.",
            steps=(
                "Обновите зависимости: pip install -r requirements.txt",
                "python -m app.cli sync-device-app-profiles",
                "Повторите автовход.",
            ),
        )

    if "прокси не назначен" in blob or not account.proxy_id:
        return AccountUserHint(
            severity="error",
            title="Нет прокси",
            message="Без прокси вход и публикация заблокированы.",
            steps=("Назначьте прокси в карточке аккаунта.",),
            action_key="attach_proxy",
            action_label="Назначить прокси",
        )

    if platform in ("youtube", "tiktok") and out.browser_tab_hint:
        return AccountUserHint(
            severity="info",
            title="Нужен вход в Studio",
            message="Headless-вход не завершился — откройте браузер/VNC.",
            steps=(
                "Дождитесь VNC или переключитесь на «Через браузер».",
                "После входа сохраните сессию (save_browser_session).",
            ),
            action_key="open_session_browser",
            action_label="Открыть браузер",
        )

    err = (out.error or "").strip()
    if err:
        return AccountUserHint(
            severity="error",
            title="Автовход не удался",
            message="Не удалось завершить автовход — подробности в логе ниже.",
            steps=(
                "Откройте лог ниже или account_logs в агенте.",
                "Попробуйте «Через браузер» или импорт sessionid.",
            ),
        )
    return None


def _last_log_message(out: AccountConnectionTestOut) -> str | None:
    logs = getattr(out, "logs", None) or []
    for line in reversed(logs):
        msg = getattr(line, "message", None) or ""
        if str(msg).strip():
            return str(msg).strip()[:200]
    return None


def _auth_rate_limited(auth) -> bool:
    if auth is None or not auth.error:
        return False
    lower = auth.error.lower()
    return (
        "please wait" in lower
        or "pleasewait" in lower
        or "few minutes" in lower
        or "rate" in lower
        or "spam" in lower
    )


def hint_for_connection_test(out: AccountConnectionTestOut, account: Account) -> AccountUserHint | None:
    platform = _platform_value(account)
    auth = out.instagram_auth
    ph = out.proxy_health

    if not out.proxy_assigned or (ph and not ph.ok and ph.error):
        err = (ph.error if ph else None) or "Прокси не назначен"
        return AccountUserHint(
            severity="error",
            title="Проблема с прокси",
            message=str(err)[:300],
            steps=(
                "Проверьте прокси в разделе «Прокси» (health).",
                "Назначьте рабочий прокси аккаунту.",
            ),
            action_key="attach_proxy",
            action_label="Назначить прокси",
        )

    if ph and ph.geo_mismatch and out.overall_ok:
        return AccountUserHint(
            severity="warn",
            title="Несовпадение гео прокси",
            message=(
                "Фактическая страна IP не совпадает с меткой прокси — для Instagram это риск."
            ),
            steps=(
                "Смените прокси на страну из метки или обновите country в записи прокси.",
                "Продолжайте только если осознанно принимаете риск.",
            ),
        )

    if platform == "instagram" and out.web_liveness_ok is False:
        err = (out.web_liveness_error or "").strip()
        return AccountUserHint(
            severity="warn",
            title="Instagram web-сессия устарела",
            message=err[:300] if err else "Playwright cookies не прошли headless-проверку.",
            steps=(
                "Повторите first-login или войдите через VNC и сохраните сессию.",
                "Проверку можно повторить с probe_web=true после обновления state.json.",
            ),
            action_key="open_session_setup",
            action_label="Настроить сессию",
        )

    if platform in ("youtube", "tiktok") and out.studio_liveness_ok is False:
        err = (out.studio_liveness_error or "").strip()
        if "подтвержд" in err.lower() or "2fa" in err.lower() or "captcha" in err.lower():
            label = "YouTube" if platform == "youtube" else "TikTok"
            return AccountUserHint(
                severity="warn",
                title=f"{label} Studio — нужно подтверждение",
                message=err[:300] or "Google/TikTok запросили 2FA или CAPTCHA.",
                steps=(
                    "Войдите через «Настройка сессии» → браузер / VNC.",
                    "После входа сохраните cookies (save_browser_session).",
                ),
                action_key="open_session_setup",
                action_label="Настроить сессию",
            )
        label = "YouTube Studio" if platform == "youtube" else "TikTok Studio"
        return AccountUserHint(
            severity="warn",
            title=f"Cookies {label} устарели",
            message=(
                err[:300]
                if err
                else "На диске есть cookies, но Studio перенаправил на вход."
            ),
            steps=(
                "Повторите «Создать сессию» (first-login) или вход через браузер.",
                "Проверку с probe_studio=true можно повторить после обновления cookies.",
            ),
            action_key="open_session_setup",
            action_label="Обновить сессию",
        )

    if out.overall_ok:
        return None

    if auth and auth.error_code == "session_missing":
        if platform == "instagram":
            return AccountUserHint(
                severity="info",
                title="Нет сессии Instagram",
                message="Sessionid или файл сессии не найдены.",
                steps=(
                    "Нажмите «Настройка сессии» → автовход, браузер или вставка sessionid.",
                    "Агент: ensure_account_session или login_account.",
                ),
                action_key="open_session_setup",
                action_label="Настроить сессию",
            )
        label = "YouTube Studio" if platform == "youtube" else "TikTok Studio"
        return AccountUserHint(
            severity="info",
            title=f"Нет cookies {label}",
            message="Playwright state для площадки не найден.",
            steps=(
                "Настройка сессии → «Создать сессию» или вход через браузер.",
                "Агент: login_account для этой площадки.",
            ),
            action_key="open_session_setup",
            action_label="Настроить сессию",
        )

    if auth and auth.error_code == "session_expired":
        return AccountUserHint(
            severity="warn",
            title="Сессия отклонена",
            message=(auth.error or "Mobile API или сервер отклонил cookie.")[:300],
            steps=(
                "Не используйте только проверку mobile для web-cookie из Dolphin.",
                "Выполните автовход заново или mint mobile session (Instagram).",
            ),
            action_key="open_session_setup",
            action_label="Обновить сессию",
        )

    if auth and auth.error_code == "challenge_required":
        return AccountUserHint(
            severity="warn",
            title="Instagram запросил проверку",
            message=(
                auth.error or "Mobile API требует код, 2FA или вход через браузер."
            )[:300],
            steps=(
                "Откройте браузер через прокси аккаунта и пройдите 2FA/challenge.",
                "Проверьте TOTP/пароль почты в карточке аккаунта.",
                "Код: provide-code или data/challenges/<user>.code.",
            ),
            action_key="open_session_browser",
            action_label="Открыть браузер",
        )

    if _auth_rate_limited(auth):
        return AccountUserHint(
            severity="info",
            title="Слишком частые проверки",
            message="Instagram временно ограничил запросы с этого аккаунта или IP.",
            steps=(
                "Подождите 15–60 минут перед повторным mobile probe.",
                "Проверку только cookies можно повторить без probe_mobile.",
            ),
        )

    if auth and auth.error:
        detail = auth.error[:300]
        if platform in ("youtube", "tiktok"):
            last = _last_log_message(out)
            if last:
                detail = last
        return AccountUserHint(
            severity="error",
            title="Проверка сессии не пройдена",
            message=detail,
            steps=("Смотрите лог проверки ниже.", "Повторите настройку сессии."),
            action_key="open_session_setup",
            action_label="Настроить сессию",
        )

    last = _last_log_message(out)
    msg = last or "Проверка подключения завершилась с ошибками."
    return AccountUserHint(
        severity="error",
        title="Подключение не готово",
        message=msg,
        steps=("Откройте лог диагностики.",),
    )


def enrich_connection_test_out(out: AccountConnectionTestOut, account: Account) -> AccountConnectionTestOut:
    hint = hint_for_connection_test(out, account)
    if hint is None:
        return out
    from app.api.schemas import AccountUserHintOut

    return out.model_copy(update={"user_hint": AccountUserHintOut(**hint.to_api_dict())})


def enrich_first_login_out(out: FirstLoginOut, account: Account) -> FirstLoginOut:
    hint = hint_for_first_login(out, account)
    updates: dict = {}
    if hint is not None:
        from app.api.schemas import AccountUserHintOut

        updates["user_hint"] = AccountUserHintOut(**hint.to_api_dict())
    if out.connection_test is not None:
        updates["connection_test"] = enrich_connection_test_out(out.connection_test, account)
    if not updates:
        return out
    return out.model_copy(update=updates)
