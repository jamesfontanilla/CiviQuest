import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QuizPlayer } from "../../pages/quiz/QuizPlayer";

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

describe("QuizPlayer page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts a subtopic quiz and renders the first question", async () => {
    mockPost.mockResolvedValue({
      id: 10,
      status: "IN_PROGRESS",
      questions: [
        { id: 1, stem: "What is 2+2?", qtype: "MULTIPLE_CHOICE", options: ["3", "4", "5", "6"] },
        { id: 2, stem: "Capital of PH?", qtype: "IDENTIFICATION", options: null },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/quiz/subtopic/3"]}>
        <Routes>
          <Route path="/quiz/:scope/:scopeId" element={<QuizPlayer />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("What is 2+2?")).toBeInTheDocument();
    });

    expect(mockPost).toHaveBeenCalledWith("/v1/subtopics/3/quiz-attempts");
  });
});
