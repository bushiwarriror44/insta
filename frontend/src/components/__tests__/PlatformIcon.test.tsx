import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlatformIcon, normalizePlatform, platformLabel } from "../PlatformIcon";

describe("PlatformIcon", () => {
  it("renders brand icons for each platform", () => {
    const { rerender } = render(<PlatformIcon platform="instagram" />);
    expect(screen.getByTestId("platform-icon-instagram")).toBeInTheDocument();
    rerender(<PlatformIcon platform="youtube" />);
    expect(screen.getByTestId("platform-icon-youtube")).toBeInTheDocument();
    rerender(<PlatformIcon platform="tiktok" />);
    expect(screen.getByTestId("platform-icon-tiktok")).toBeInTheDocument();
  });

  it("falls back to instagram for unknown values", () => {
    expect(normalizePlatform("")).toBe("instagram");
    expect(normalizePlatform("other")).toBe("instagram");
    expect(platformLabel("youtube")).toBe("YouTube");
  });
});
