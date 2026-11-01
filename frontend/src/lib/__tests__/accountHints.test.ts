import { describe, expect, it, vi } from "vitest";

import {
  fallbackConnectionHint,
  fallbackFirstLoginHint,
  hintActionToToast,
  severityToToastKind,
} from "../accountHints";
import type { AccountConnectionTestOut } from "../api/types";

describe("accountHints", () => {
  it("maps warn severity to info toast", () => {
    expect(severityToToastKind("warn")).toBe("info");
    expect(severityToToastKind("error")).toBe("error");
  });

  it("fallbackFirstLoginHint for challenge", () => {
    const hint = fallbackFirstLoginHint({
      run_id: 1,
      ok: false,
      challenge: true,
      session_imported: false,
      login_debug_available: false,
      logs: [],
    });
    expect(hint?.title).toMatch(/подтвержд/i);
  });

  it("fallbackConnectionHint for session_missing", () => {
    const hint = fallbackConnectionHint({
      username: "a",
      proxy_assigned: true,
      proxy_health: { ok: true, geo_mismatch: false },
      session_storage: {
        has_session_id: false,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "none",
      },
      instagram_auth: {
        ok: false,
        method: "none",
        error_code: "session_missing",
      },
      overall_ok: false,
      checked_at: "2026-01-01T00:00:00Z",
      run_id: 1,
      logs: [],
    } as AccountConnectionTestOut);
    expect(hint?.steps?.[0]).toMatch(/Настройка сессии/i);
  });

  it("hintActionToToast maps open_session_setup", () => {
    const onOpen = vi.fn();
    const action = hintActionToToast(
      {
        severity: "info",
        title: "t",
        message: "m",
        steps: [],
        action_key: "open_session_setup",
        action_label: "Настроить",
      },
      { onOpenSessionSetup: onOpen }
    );
    expect(action?.label).toBe("Настроить");
    action?.onClick?.();
    expect(onOpen).toHaveBeenCalled();
  });
});
