import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { OTPVerification } from "../../pages/auth/OTPVerification";

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

describe("OTPVerification page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders OTP verification form without crashing", () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/verify-otp", state: { email: "test@example.com", purpose: "VERIFY_EMAIL" } }]}>
        <OTPVerification />
      </MemoryRouter>
    );

    expect(screen.getByLabelText("OTP verification form")).toBeInTheDocument();
    expect(screen.getByLabelText("Verify code")).toBeInTheDocument();
  });
});
