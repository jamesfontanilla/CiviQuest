import { useState } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { PageTransition } from "../components/PageTransition";

interface TutorResponseData {
  interaction_id: number;
  response_text: string;
  interaction_type: string;
}

interface SimilarQuestionData {
  interaction_id: number;
  stem: string;
  options: string[] | null;
  correct_answer: string;
  explanation: string;
}

interface StepByStepData {
  interaction_id: number;
  steps: string[];
}

export function Tutor() {
  const [questionId, setQuestionId] = useState("");
  const [selectedAnswer, setSelectedAnswer] = useState("");
  const [response, setResponse] = useState<string | null>(null);
  const [steps, setSteps] = useState<string[] | null>(null);
  const [similarQ, setSimilarQ] = useState<SimilarQuestionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [interactionId, setInteractionId] = useState<number | null>(null);

  const clearResults = () => {
    setResponse(null);
    setSteps(null);
    setSimilarQ(null);
    setInteractionId(null);
  };

  const handleAction = async (action: string) => {
    if (!questionId) return;
    setLoading(true);
    clearResults();
    try {
      const body: Record<string, unknown> = { question_id: Number(questionId) };
      if (selectedAnswer) body.selected_answer = selectedAnswer;

      if (action === "step-by-step") {
        const data = await apiClient.post<StepByStepData>(`/v1/tutor/${action}`, body);
        setSteps(data.steps);
        setInteractionId(data.interaction_id);
      } else if (action === "similar") {
        const data = await apiClient.post<SimilarQuestionData>(`/v1/tutor/${action}`, body);
        setSimilarQ(data);
        setInteractionId(data.interaction_id);
      } else {
        const data = await apiClient.post<TutorResponseData>(`/v1/tutor/${action}`, body);
        setResponse(data.response_text);
        setInteractionId(data.interaction_id);
      }
    } catch {
      setResponse("Error: Could not get response from tutor.");
    } finally {
      setLoading(false);
    }
  };

  const handleRate = async (helpful: boolean) => {
    if (!interactionId) return;
    try {
      await apiClient.post(`/v1/tutor/interactions/${interactionId}:rate`, { helpful });
    } catch {
      // silent fail for rating
    }
  };

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 720 }}>
        <h1 style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)", marginBottom: "1rem" }}>
          🤖 AI Tutor
        </h1>
        <p style={{ color: "var(--color-text-secondary)", marginBottom: "1.5rem", fontSize: "var(--font-size-sm)" }}>
          Get explanations, hints, and practice questions for any question in the bank.
        </p>

        {/* Input section */}
        <GlassCard style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
            <input
              type="number"
              placeholder="Question ID"
              value={questionId}
              onChange={(e) => setQuestionId(e.target.value)}
              aria-label="Question ID"
              style={{
                padding: "0.5rem 0.75rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--glass-border-medium)",
                background: "var(--glass-bg-subtle)",
                color: "var(--color-text)",
                width: 140,
                fontSize: "var(--font-size-base)",
              }}
            />
            <input
              type="text"
              placeholder="Your answer (optional)"
              value={selectedAnswer}
              onChange={(e) => setSelectedAnswer(e.target.value)}
              aria-label="Selected answer"
              style={{
                padding: "0.5rem 0.75rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--glass-border-medium)",
                background: "var(--glass-bg-subtle)",
                color: "var(--color-text)",
                width: 180,
                fontSize: "var(--font-size-base)",
              }}
            />
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {["explain", "simplify", "hint", "step-by-step", "similar"].map((action) => (
              <GlassButton
                key={action}
                variant="primary"
                size="sm"
                onClick={() => handleAction(action)}
                disabled={loading || !questionId}
                style={{ textTransform: "capitalize" }}
              >
                {action.replace("-", " ")}
              </GlassButton>
            ))}
          </div>
        </GlassCard>

        {loading && (
          <GlassCard>
            <p style={{ color: "var(--color-text-secondary)" }}>Loading...</p>
          </GlassCard>
        )}

        {response && (
          <GlassCard style={{ marginBottom: "1rem", whiteSpace: "pre-wrap", color: "var(--color-text)" }}>
            {response}
          </GlassCard>
        )}

        {steps && (
          <GlassCard style={{ marginBottom: "1rem" }}>
            <h3 style={{ marginBottom: "0.75rem", color: "var(--color-text)", fontWeight: 600 }}>Step-by-Step Solution</h3>
            <ol style={{ paddingLeft: "1.25rem", color: "var(--color-text)" }}>
              {steps.map((step, i) => (
                <li key={i} style={{ marginBottom: "0.5rem" }}>{step}</li>
              ))}
            </ol>
          </GlassCard>
        )}

        {similarQ && (
          <GlassCard style={{ marginBottom: "1rem" }}>
            <h3 style={{ marginBottom: "0.75rem", color: "var(--color-text)", fontWeight: 600 }}>Similar Question</h3>
            <p style={{ color: "var(--color-text)" }}><strong>Q:</strong> {similarQ.stem}</p>
            {similarQ.options && (
              <ul style={{ paddingLeft: "1.25rem", margin: "0.5rem 0", color: "var(--color-text)" }}>
                {similarQ.options.map((opt, i) => (
                  <li key={i}>{opt}</li>
                ))}
              </ul>
            )}
            <p style={{ color: "var(--color-text)" }}><strong>Answer:</strong> {similarQ.correct_answer}</p>
            <p style={{ color: "var(--color-text-secondary)", marginTop: "0.5rem", fontSize: "var(--font-size-sm)" }}>
              {similarQ.explanation}
            </p>
          </GlassCard>
        )}

        {interactionId && (
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>Was this helpful?</span>
            <GlassButton variant="ghost" size="sm" onClick={() => handleRate(true)} aria-label="Helpful">👍</GlassButton>
            <GlassButton variant="ghost" size="sm" onClick={() => handleRate(false)} aria-label="Not helpful">👎</GlassButton>
          </div>
        )}
      </main>
    </PageTransition>
  );
}
