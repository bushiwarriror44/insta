import { describe, expect, it } from "vitest";

import { ACCOUNT_FORM_FIELDS, askFormIncomplete } from "../setupForms";

const filled = {
  proxy_label: "px",
  username: "studio",
  platform: "youtube",
};

describe("ACCOUNT_FORM_FIELDS", () => {
  it("includes vendor line and imap host for IG email login", () => {
    const ids = ACCOUNT_FORM_FIELDS.map((f) => f.id);
    expect(ids).toContain("email_password");
    expect(ids).toContain("vendor_line");
    expect(ids).toContain("imap_host");
  });

  it("asks for an Instagram password and lets YouTube through without one", () => {
    expect(askFormIncomplete(ACCOUNT_FORM_FIELDS, { ...filled, platform: "youtube" })).toBe(false);
    expect(askFormIncomplete(ACCOUNT_FORM_FIELDS, { ...filled, platform: "tiktok" })).toBe(false);
    expect(askFormIncomplete(ACCOUNT_FORM_FIELDS, { ...filled, platform: "instagram" })).toBe(true);
    expect(askFormIncomplete(ACCOUNT_FORM_FIELDS, { ...filled, platform: "" })).toBe(true);
    expect(
      askFormIncomplete(ACCOUNT_FORM_FIELDS, { ...filled, platform: "instagram", password: "secret" })
    ).toBe(false);
  });
});
