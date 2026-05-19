import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Signup } from "../../pages/auth/Signup";

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

describe("Signup page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders signup form without crashing", () => {
    render(
      <MemoryRouter>
        <Signup />
      </MemoryRouter>
    );

    expect(screen.getByLabelText("Signup form")).toBeInTheDocument();
    expect(screen.getByLabelText("Sign up")).toBeInTheDocument();
    expect(screen.getByLabelText("Email", { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password", { selector: "input" })).toBeInTheDocument();
  });
});
