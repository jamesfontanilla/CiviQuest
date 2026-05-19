import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MockExamPlayer } from "../../pages/mock-exam/MockExamPlayer";

const mockPost = vi.fn();

vi.mock("../../api/client", () => ({
  apiClient: {
    get: vi.fn(),
    post: (...args: unknown[]) => mockPost(...args),
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

describe("MockExamPlayer page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders start screen and calls POST /v1/mock-exams/attempts on start", async () => {
    mockPost.mockResolvedValue({
      id: 1,
      status: "IN_PROGRESS",
      remaining_seconds: 10800,
      nav_policy: "LINEAR_NO_REVISIT",
      questions: [
        { id: 1, ordinal: 1, stem: "Mock Q1", qtype: "MULTIPLE_CHOICE", options: ["A", "B", "C", "D"] },
      ],
    });

    render(
      <MemoryRouter>
        <MockExamPlayer />
      </MemoryRouter>
    );

    // Start screen
    expect(screen.getByLabelText("Start mock exam")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Start mock exam"));

    await waitFor(() => {
      expect(screen.getByText("Mock Q1")).toBeInTheDocument();
    });

    expect(mockPost).toHaveBeenCalledWith("/v1/mock-exams/attempts");
  });
});
