import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantCards, type ChatBrowserTarget } from "../AssistantCards";

describe("AssistantCards", () => {
  const onNavigate = vi.fn();
  const onOpenAccount = vi.fn();
  const onOpenBrowser = vi.fn();

  it("expands long account lists", async () => {
    const items = Array.from({ length: 10 }, (_, i) => ({
      id: i + 1,
      username: `user${i}`,
      platform: "instagram",
      status: "active",
      proxy_label: "res-1",
    }));
    render(
      <AssistantCards
        blocks={[{ kind: "accounts", items }]}
        onNavigate={onNavigate}
        onOpenAccount={onOpenAccount}
        onOpenBrowser={onOpenBrowser}
      />
    );
    expect(screen.queryByText("@user8")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("assistant-cards-expand-accounts"));
    expect(screen.getByText("@user8")).toBeInTheDocument();
  });

  it("offers proxy assignment when proxy is missing", async () => {
    render(
      <AssistantCards
        blocks={[
          {
            kind: "accounts",
            items: [{ id: 5, username: "bob", platform: "instagram", status: "active" }],
          },
        ]}
        onNavigate={onNavigate}
        onOpenAccount={onOpenAccount}
        onOpenBrowser={onOpenBrowser}
      />
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /назначить прокси/i }));
    expect(onNavigate).toHaveBeenCalledWith("/accounts?id=5");
  });

  it("opens browser when proxy is set", async () => {
    const target: ChatBrowserTarget = {
      username: "alice",
      platform: "instagram",
      proxy_label: "res-1",
    };
    render(
      <AssistantCards
        blocks={[
          {
            kind: "accounts",
            items: [{ id: 1, username: "alice", platform: "instagram", status: "active", proxy_label: "res-1" }],
          },
        ]}
        onNavigate={onNavigate}
        onOpenAccount={onOpenAccount}
        onOpenBrowser={onOpenBrowser}
      />
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^браузер$/i }));
    expect(onOpenBrowser.mock.calls[0]?.[0]).toMatchObject({
      username: target.username,
      proxy_label: "res-1",
    });
  });
});
