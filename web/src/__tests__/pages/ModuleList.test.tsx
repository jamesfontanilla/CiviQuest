import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ModuleList } from "../../pages/content/ModuleList";

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

describe("ModuleList page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders modules after fetching from /v1/modules", async () => {
    mockGet.mockResolvedValue({
      items: [
        { id: 1, title: "Module A", description: "First module", category: "PROFESSIONAL" },
        { id: 2, title: "Module B", description: null, category: "SUB_PROFESSIONAL" },
      ],
      total: 2,
    });

    render(
      <MemoryRouter>
        <ModuleList />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Module A")).toBeInTheDocument();
      expect(screen.getByText("Module B")).toBeInTheDocument();
    });

    expect(mockGet).toHaveBeenCalledWith("/v1/modules");
  });
});
