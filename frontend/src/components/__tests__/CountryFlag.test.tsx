import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CountryFlag, countryCodeToFlag } from "../CountryFlag";

describe("countryCodeToFlag", () => {
  it("converts ISO-2 codes to flag emoji", () => {
    expect(countryCodeToFlag("US")).toBe("🇺🇸");
    expect(countryCodeToFlag("de")).toBe("🇩🇪");
  });

  it("returns null for invalid codes", () => {
    expect(countryCodeToFlag(null)).toBeNull();
    expect(countryCodeToFlag("")).toBeNull();
    expect(countryCodeToFlag("USA")).toBeNull();
  });
});

describe("CountryFlag", () => {
  it("renders flag emoji with title", () => {
    render(<CountryFlag code="US" />);
    expect(screen.getByTitle("US")).toHaveTextContent("🇺🇸");
  });

  it("renders fallback for missing code", () => {
    render(<CountryFlag code={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
