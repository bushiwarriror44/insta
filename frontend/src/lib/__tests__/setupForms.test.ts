import { describe, expect, it } from "vitest";

import {
  ACCOUNT_FORM_FIELDS,
  askFormIncomplete,
  detectFormKind,
  optionLabel,
  optionValue,
  PROXY_FORM_FIELDS,
  PUBLISH_FORM_FIELDS,
} from "../setupForms";

describe("setupForms", () => {
  it("detects form kinds from field ids", () => {
    expect(detectFormKind(ACCOUNT_FORM_FIELDS)).toBe("account");
    expect(detectFormKind(PROXY_FORM_FIELDS)).toBe("proxy");
    expect(detectFormKind(PUBLISH_FORM_FIELDS)).toBe("publish");
    expect(detectFormKind([{ id: "code", label: "Код" }])).toBeNull();
    expect(detectFormKind(ACCOUNT_FORM_FIELDS, "publish")).toBe("publish");
  });

  it("requires account_id and filename for publish", () => {
    expect(
      askFormIncomplete(PUBLISH_FORM_FIELDS, {
        account_id: "1",
        filename: "clip.mp4",
      })
    ).toBe(false);
    expect(askFormIncomplete(PUBLISH_FORM_FIELDS, { account_id: "1" })).toBe(true);
  });

  it("normalizes select options", () => {
    expect(optionValue("reel")).toBe("reel");
    expect(optionLabel({ value: "12", label: "@alice" })).toBe("@alice");
    expect(optionValue({ value: "12", label: "@alice" })).toBe("12");
  });
});
