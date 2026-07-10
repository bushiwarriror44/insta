import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Login } from "../Login";

const useAuthMock = vi.hoisted(() => vi.fn());
vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

function renderLogin() {
  return render(
    <ToastProvider>
      <Login />
    </ToastProvider>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
});

describe("Login page", () => {
  it("renders heading and submit button", () => {
    useAuthMock.mockReturnValue({ login: vi.fn().mockResolvedValue(true) });
    renderLogin();
    expect(screen.getByRole("heading", { name: /reels admin/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /войти/i })).toBeInTheDocument();
  });

  it("does not call login when token field is empty", () => {
    const login = vi.fn().mockResolvedValue(true);
    useAuthMock.mockReturnValue({ login });
    renderLogin();
    fireEvent.click(screen.getByRole("button", { name: /войти/i }));
    expect(login).not.toHaveBeenCalled();
  });

  it("calls login() with the trimmed token on submit", async () => {
    const login = vi.fn().mockResolvedValue(true);
    useAuthMock.mockReturnValue({ login });
    renderLogin();
    const input = screen.getByLabelText(/токен администратора/i);
    fireEvent.change(input, { target: { value: "  my-secret  " } });
    fireEvent.click(screen.getByRole("button", { name: /войти/i }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("my-secret"));
  });

  it("shows an error toast when login returns false", async () => {
    const login = vi.fn().mockResolvedValue(false);
    useAuthMock.mockReturnValue({ login });
    renderLogin();
    fireEvent.change(screen.getByLabelText(/токен администратора/i), {
      target: { value: "bad" },
    });
    fireEvent.click(screen.getByRole("button", { name: /войти/i }));
    await screen.findByText(/неверный токен/i);
  });

  it("disables the button while submitting", async () => {
    let resolveLogin!: (v: boolean) => void;
    const login = vi.fn(
      () => new Promise<boolean>((res) => (resolveLogin = res))
    );
    useAuthMock.mockReturnValue({ login });
    renderLogin();
    fireEvent.change(screen.getByLabelText(/токен администратора/i), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: /войти/i }));
    const btn = screen.getByRole("button", { name: /проверка/i });
    expect(btn).toBeDisabled();
    resolveLogin(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /войти/i })).not.toBeDisabled()
    );
  });
});
