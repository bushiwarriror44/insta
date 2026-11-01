# Merge-миграция аккаунтов на прод-сервер

Перенос **карточек аккаунтов**, **прокси** и **файлов сессий** с локальной/QA машины на сервер, где уже есть свои аккаунты, рендеры и очередь постов. **Не** заменяет целиком `data/app.db` и **не** копирует jobs/renders/media.

См. также [data-and-ops.md](data-and-ops.md).

## Что входит в бандл

Архив `migration-bundle-v1/` внутри `.tar.gz`:

| Файл | Содержимое |
| --- | --- |
| `manifest.json` | Метаданные, sha256 файлов, **без паролей** |
| `entities.json` | Прокси (URL) и аккаунты (**с паролями и email_password**) |
| `files/` | `playwright/…/state.json`, `devices/device_*.json`, `sessions/session_*.json` |

**Секреты:** не коммитьте архив в git, не отправляйте в чаты. Передавайте по SCP/SFTP.

## Локально: экспорт

```powershell
python scripts/export_migration_bundle.py --out data/migration-bundle-YYYYMMDD.tar.gz
# или
python -m app.cli export-migration-bundle --out data/migration-bundle-YYYYMMDD.tar.gz
```

Опция `--platform instagram,youtube,tiktok` — только выбранные площадки (по умолчанию все аккаунты из БД).

## На сервере: merge-импорт

1. **Обязательно** снять копию БД: UI «Обслуживание» → «Снять копию» или `take_backup`.
2. Остановить worker: `docker compose stop reels-worker`.
3. Dry-run:

```bash
python scripts/import_migration_bundle.py data/migration-bundle-YYYYMMDD.tar.gz --dry-run --prefix qa-
```

4. Импорт:

```bash
python scripts/import_migration_bundle.py data/migration-bundle-YYYYMMDD.tar.gz --prefix qa-
```

5. Отчёт: `data/migration_import_report.json` (added/skipped/remapped, без паролей).
6. Playwright в Docker (если нужно): `scripts/setup_docker_playwright.sh`.
7. Проверка: `python scripts/qa_batch_connection_test.py` по новым аккаунтам.
8. Поднять worker: `docker compose start reels-worker`.

### Флаги импорта

| Флаг | Эффект |
| --- | --- |
| `--dry-run` | Только отчёт |
| `--prefix qa-` | При конфликте label прокси с другим URL — новый label `qa-<old>` |
| `--merge-session-files` | Для аккаунтов уже в БД — докинуть файлы сессий, если на диске их ещё нет |
| `--force-session-files` | Перезаписать файлы сессий на диске (осторожно) |

По умолчанию:

- существующие `(platform, username)` **не** обновляются в БД;
- URL существующих прокси **не** перезаписываются;
- существующие файлы на диске **не** перезаписываются.

## Повторный импорт

Идемпотентен: те же аккаунты попадут в `accounts_skipped`, прокси — в `proxies_reused`.

## Чего нет в бандле

- `PostJob`, renders, media library, operators, настройки панели.
- Полная замена `app.db` (используйте backup/restore только если сознательно откатываете **всю** БД).

## Антипаттерны

- **Не** копировать локальный `app.db` поверх серверного.
- **Не** запускать `scripts/import_accounts_folder.py` на prod — перезапишет URL прокси по label.
