import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LessonReader } from "../../pages/content/LessonReader";

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

describe("LessonReader page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders lesson content after fetching", async () => {
    mockGet.mockResolvedValue({
      id: 1,
      subtopic_id: 5,
      content_json: {
        explanations: ["This is an explanation."],
        worked_examples: ["Example 1"],
        key_takeaways: ["Takeaway 1"],
        summary: "A summary of the lesson.",
      },
      status: "COMPLETE",
    });

    render(
      <MemoryRouter initialEntries={["/subtopics/5/lesson"]}>
        <Routes>
          <Route path="/subtopics/:subtopicId/lesson" element={<LessonReader />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("This is an explanation.")).toBeInTheDocument();
      expect(screen.getByText("A summary of the lesson.")).toBeInTheDocument();
    });

    expect(mockGet).toHaveBeenCalledWith("/v1/subtopics/5/lesson");
  });
});
