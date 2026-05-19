import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AdminDashboard } from "../../pages/AdminDashboard";

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

describe("AdminDashboard page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders analytics and user list", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === "/v1/admin/analytics") {
        return Promise.resolve({
          total_users: 100,
          verified_count: 80,
          banned_count: 2,
          lessons_completed: 500,
          quiz_attempts: 300,
          mock_attempts: 50,
          mock_pass_rate: 0.72,
        });
      }
      if (url.startsWith("/v1/admin/users")) {
        return Promise.resolve({
          items: [
            { id: 1, email: "admin@test.com", role: "ADMIN", account_state: "VERIFIED", is_banned: false },
          ],
          total: 1,
        });
      }
      return Promise.resolve({});
    });

    render(
      <MemoryRouter>
        <AdminDashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument(); // total users
      expect(screen.getByText("admin@test.com")).toBeInTheDocument();
    });

    expect(mockGet).toHaveBeenCalledWith("/v1/admin/analytics");
  });
});
