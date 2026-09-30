import { describe, expect, it } from "vitest";

import { ACCOUNT_FORM_FIELDS } from "../setupForms";

describe("ACCOUNT_FORM_FIELDS", () => {
  it("includes vendor line and imap host for IG email login", () => {
    const ids = ACCOUNT_FORM_FIELDS.map((f) => f.id);
    expect(ids).toContain("email_password");
    expect(ids).toContain("vendor_line");
    expect(ids).toContain("imap_host");
  });
});
