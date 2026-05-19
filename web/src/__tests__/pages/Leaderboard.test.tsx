import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Leaderboard } from "../../pages/Leaderboard";

const mockGet = vi.fn();

vi.mock("../../api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("../../stores/auth", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  isAuthenticated: () => true,
  getToken: () => "mock-token",
  getLastAuthenticatedAt: () => Date.now(),
}));

describe("Leaderboard page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders leaderboard entries from /v1/leaderboards/global", async () => {
    mockGet.mockResolvedValue({
      entries: [
        { display_name: "Alice", level: 5, xp_window: 1200, category: "PROFESSIONAL" },
        { display_name: "Bob", level: 3, xp_window: 800, category: "PROFESSIONAL" },
      ],
    });

    render(
      <MemoryRouter>
        <Leaderboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(screen.getByText("Bob")).toBeInTheDocument();
    });

    expect(mockGet).toHaveBeenCalledWith("/v1/leaderboards/global");
  });
});
