# migration-bundle-export.tar.gz

One-off merge bundle: **23 accounts**, **6 proxies**, session files (Studio + IG devices).

**Contains secrets** (passwords, proxy URLs, cookies in Playwright state). After successful import on prod:

1. Delete this file from the server and from git history if it was pushed to a public remote.
2. Rotate any credentials that were exposed in a shared repo.

Import: see [docs/migration-server-merge.md](../docs/migration-server-merge.md).

```bash
docker compose exec reels-api python scripts/import_migration_bundle.py \
  /app/deploy/migration-bundle-export.tar.gz --prefix qa-
```

Mount note: copy into container or bind-mount `deploy/` — on standard compose, place under repo `deploy/` and run from host:

```bash
python scripts/import_migration_bundle.py deploy/migration-bundle-export.tar.gz --prefix qa-
```
