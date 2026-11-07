import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HeroSmsPanel } from "../HeroSmsPanel";

const apiMock = vi.hoisted(() => ({
  heroSms: {
    status: vi.fn(),
    setApiKey: vi.fn(),
    countries: vi.fn(),
    services: vi.fn(),
    prices: vi.fn(),
    active: vi.fn(),
    history: vi.fn(),
  },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, api: apiMock };
});

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

beforeEach(() => {
  apiMock.heroSms.status.mockReset();
  apiMock.heroSms.countries.mockReset();
  apiMock.heroSms.services.mockReset();
  apiMock.heroSms.prices.mockReset();
  apiMock.heroSms.active.mockReset();
  localStorage.clear();
});

describe("HeroSmsPanel", () => {
  it("shows api key input at top when not configured", async () => {
    apiMock.heroSms.status.mockResolvedValue({ configured: false, key_from_env: false });
    render(
      <MemoryRouter>
        <HeroSmsPanel />
      </MemoryRouter>
    );
    expect(await screen.findByLabelText(/API-ключ/i)).toBeInTheDocument();
    expect(screen.getByTestId("hero-sms-balance")).toBeInTheDocument();
  });

  it("shows replace api key when configured", async () => {
    apiMock.heroSms.status.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 5.5,
    });
    apiMock.heroSms.countries.mockResolvedValue([{ id: 52, rus: "Таиланд" }]);
    apiMock.heroSms.services.mockResolvedValue([{ code: "ig", name: "Instagram" }]);
    apiMock.heroSms.prices.mockResolvedValue({
      service: "ig",
      rows: [{ country_id: 52, cost: 0.05, count: 3, physical_count: 0 }],
    });
    apiMock.heroSms.active.mockResolvedValue({ items: [] });
    render(
      <MemoryRouter>
        <HeroSmsPanel />
      </MemoryRouter>
    );
    expect(await screen.findByText(/Заменить API-ключ/i)).toBeInTheDocument();
    expect(screen.getByTestId("hero-buy-wizard")).toBeInTheDocument();
    expect(screen.getByTestId("hero-wizard-step-2")).toBeInTheDocument();
  });

  it("shows active phone in detail", async () => {
    apiMock.heroSms.status.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 1,
    });
    apiMock.heroSms.countries.mockResolvedValue([]);
    apiMock.heroSms.services.mockResolvedValue([]);
    apiMock.heroSms.prices.mockResolvedValue({ service: "ig", rows: [] });
    apiMock.heroSms.active.mockResolvedValue({
      items: [
        {
          activation_id: "99",
          service_code: "ig",
          phone_number: "66911112222",
          phone_e164: "+66911112222",
          activation_cost: 0.05,
          country_id: 52,
        },
      ],
    });
    render(
      <MemoryRouter>
        <HeroSmsPanel />
      </MemoryRouter>
    );
    const detail = await screen.findByTestId("hero-active-detail");
    expect(detail).toHaveTextContent("+66911112222");
  });
});
