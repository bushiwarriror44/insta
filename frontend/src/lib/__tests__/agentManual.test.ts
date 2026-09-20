import { describe, expect, it } from "vitest";

import { agentWorkHint, pageHint, toolHint } from "../agentManual";

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

describe("toolHint", () => {
  it("explains plan_account needs a live worker", () => {
    expect(toolHint("plan_account")).toMatch(/воркер/i);
    expect(toolHint(undefined)).toBe("");
  });

  it("explains create_render fal vs Salad hours", () => {
    expect(toolHint("create_render")).toMatch(/0\.05/i);
    expect(toolHint("create_render")).toMatch(/salad/i);
    expect(toolHint("diagnose")).toMatch(/stop/i);
  });
});
