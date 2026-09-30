import { describe, expect, it } from "vitest";

import { AGENT_PAGE_MANUAL, agentWorkHint, pageHint, toolHint } from "../agentManual";

function sectionBody(id: string): string {
  const section = AGENT_PAGE_MANUAL.find((s) => s.id === id);
  return section ? section.body.join(" ") : "";
}

describe("agentWorkHint", () => {
  const ready = {
    accounts: 1,
    brief: "nature",
    questions: 0,
    busy: false,
    autoSchedule: true,
  };

  it("prefers missing accounts, then empty brief, questions, busy, schedule", () => {
    expect(agentWorkHint({ ...ready, accounts: 0 })).toMatch(/аккаунт/i);
    expect(agentWorkHint({ ...ready, brief: "  " })).toMatch(/бриф пустой/i);
    expect(agentWorkHint({ ...ready, questions: 1 })).toMatch(/открытые вопросы/i);
    expect(agentWorkHint({ ...ready, busy: true })).toMatch(/planjob/i);
    expect(agentWorkHint({ ...ready, autoSchedule: false })).toMatch(/расписание/i);
  });
});

describe("pageHint", () => {
  it("describes /agent as PlanJob, not the chat", () => {
    expect(pageHint("/agent?id=1")).toMatch(/planjob/i);
  });

  it("points /administration and /renders at billing", () => {
    expect(pageHint("/administration")).toMatch(/оплата/i);
    expect(pageHint("/administration")).toMatch(/блокнот/i);
    expect(pageHint("/renders")).toMatch(/fal/i);
  });

  it("points /accounts login and proxy failures at diagnose", () => {
    expect(pageHint("/accounts")).toMatch(/diagnose/i);
  });
});

describe("AGENT_PAGE_MANUAL parity", () => {
  it("describes preview as sync renders without PlanJob", () => {
    const plan = sectionBody("plan");
    expect(plan).toMatch(/превью/i);
    expect(plan).toMatch(/без planjob/i);
    expect(plan).toMatch(/не пробн/i);
    expect(plan).toMatch(/воркер/i);
  });

  it("does not claim open questions block planning", () => {
    const sources = sectionBody("sources");
    expect(sources).toMatch(/не блокируются/i);
    expect(sources).not.toMatch(/следующий план упрётся/i);
  });
});

describe("toolHint", () => {
  it("explains plan_account needs a live worker", () => {
    expect(toolHint("plan_account")).toMatch(/воркер/i);
    expect(toolHint(undefined)).toBe("");
  });

  it("explains preview_plan like the Agent preview button", () => {
    const hint = toolHint("preview_plan");
    expect(hint).toMatch(/без planjob/i);
    expect(hint).toMatch(/dry-run/i);
    expect(hint).toMatch(/превью/i);
  });

  it("explains create_render fal vs Salad hours", () => {
    expect(toolHint("create_render")).toMatch(/0\.05/i);
    expect(toolHint("create_render")).toMatch(/salad/i);
    expect(toolHint("diagnose")).toMatch(/stop/i);
  });
});
