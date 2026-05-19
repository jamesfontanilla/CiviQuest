import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForgotPassword } from "../../pages/auth/ForgotPassword";

vi.mock("../../api/client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({}),
    get: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("../../stores/auth", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  isAuthenticated: () => false,
  getToken: () => null,
  getLastAuthenticatedAt: () => null,
}));

describe("ForgotPassword page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders forgot password form without crashing", () => {
    render(
      <MemoryRouter>
        <ForgotPassword />
      </MemoryRouter>
    );

    expect(screen.getByLabelText("Forgot password form")).toBeInTheDocument();
    expect(screen.getByLabelText("Send reset code")).toBeInTheDocument();
  });
});
