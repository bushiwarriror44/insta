import { afterEach, describe, expect, it } from "vitest";

import { panelHref, panelPath } from "../panelHref";

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("panelHref", () => {
  it("keeps the secret gate prefix when opening accounts", () => {
    window.history.replaceState({}, "", "/uSecretPath/activity");
    expect(panelHref("/accounts?id=7")).toBe(
      `${window.location.origin}/uSecretPath/accounts?id=7`
    );
  });

  it("does not treat known app segments as the gate prefix", () => {
    window.history.replaceState({}, "", "/accounts");
    expect(panelHref("/activity?job=9")).toBe(
      `${window.location.origin}/activity?job=9`
    );
  });
});

describe("panelPath", () => {
  it("strips the secret gate prefix", () => {
    expect(panelPath("/uSecretPath/accounts")).toBe("/accounts");
  });

  it("keeps known app routes", () => {
    expect(panelPath("/accounts")).toBe("/accounts");
    expect(panelPath("/")).toBe("/");
  });
});
