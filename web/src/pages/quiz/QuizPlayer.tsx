import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { apiClient } from "../../api/client";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassButton } from "../../components/GlassButton";
import { scaleIn, staggerContainer, staggerItem, springDefault } from "../../design-system";

interface QuizQuestion {
  id: number;
  stem: string;
  qtype: string;
  options: string[] | null;
  selected?: string | null;
  is_correct?: boolean;
  correct_answer?: string;
  explanation?: string;
}

interface QuizAttempt {
  id: number;
  status: string;
  score?: number;
  max_score?: number;
  questions: QuizQuestion[];
}

export function QuizPlayer() {
  const { scope, scopeId } = useParams<{ scope: string; scopeId: string }>();
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function startUrl(): string {
    switch (scope) {
      case "topic":
        return `/v1/topics/${scopeId}/quiz-attempts`;
      case "module":
        return `/v1/modules/${scopeId}/quiz-attempts`;
      default:
        return `/v1/subtopics/${scopeId}/quiz-attempts`;
    }
  }

  async function startQuiz() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<QuizAttempt>(startUrl());
      setAttempt(res);
      setCurrentIdx(0);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start quiz");
    } finally {
      setLoading(false);
    }
  }

  async function selectAnswer(questionId: number, selected: string) {
    if (!attempt) return;
    try {
      await apiClient.patch(`/v1/quiz-attempts/${attempt.id}/answers/${questionId}`, { selected });
      setAttempt((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          questions: prev.questions.map((q) => (q.id === questionId ? { ...q, selected } : q)),
        };
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save answer");
    }
  }

  async function submitQuiz() {
    if (!attempt) return;
    setSubmitting(true);
    try {
      const res = await apiClient.post<QuizAttempt>(`/v1/quiz-attempts/${attempt.id}:submit`);
      setAttempt(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit quiz");
    } finally {
      setSubmitting(false);
    }
  }

  // Auto-start on mount
  useEffect(() => {
    startQuiz();
  }, [scope, scopeId]);

  if (loading) return <div className="page container">Starting quiz…</div>;
  if (error && !attempt) {
    return (
      <PageTransition>
        <div className="page container">
          <p className="error-text" style={{ color: "var(--color-danger)" }}>{error}</p>
          <Link to="/modules" aria-label="Back to modules" style={{ color: "var(--color-accent)" }}>
            ← Back
          </Link>
        </div>
      </PageTransition>
    );
  }
  if (!attempt) return null;

  // Results view
  if (attempt.status === "SUBMITTED") {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 720 }}>
          <motion.div
            initial={scaleIn.initial}
            animate={scaleIn.animate}
            transition={scaleIn.transition}
          >
            <GlassCard blur="lg" style={{ textAlign: "center", marginBottom: "1.5rem" }}>
              <h1 style={{ color: "var(--color-text)", marginBottom: "0.5rem" }}>Quiz Results</h1>
              <p style={{ fontSize: "2rem", fontWeight: 700, color: "var(--color-accent)" }}>
                {attempt.score} / {attempt.max_score}
              </p>
            </GlassCard>
          </motion.div>

          <motion.div
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            style={{ display: "grid", gap: "1rem" }}
          >
            {attempt.questions.map((q, i) => (
              <motion.div key={q.id} variants={staggerItem} transition={springDefault}>
                <GlassCard blur="sm">
                  <p style={{ color: "var(--color-text)", marginBottom: "0.5rem" }}>
                    <strong>
                      {i + 1}. {q.stem}
                    </strong>
                  </p>
                  <p style={{ color: "var(--color-text-secondary)" }}>
                    Your answer: <code style={{ color: "var(--color-highlight)" }}>{q.selected ?? "(none)"}</code>
                    {q.is_correct !== undefined && (
                      <span style={{ marginLeft: "0.5rem", color: q.is_correct ? "var(--color-success)" : "var(--color-danger)" }}>
                        {q.is_correct ? "✓" : "✗"}
                      </span>
                    )}
                  </p>
                  {q.correct_answer && (
                    <p style={{ color: "var(--color-text-secondary)" }}>
                      Correct: <code style={{ color: "var(--color-success)" }}>{q.correct_answer}</code>
                    </p>
                  )}
                  {q.explanation && (
                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem", marginTop: "0.5rem" }}>
                      {q.explanation}
                    </p>
                  )}
                </GlassCard>
              </motion.div>
            ))}
          </motion.div>

          <div style={{ marginTop: "1.5rem" }}>
            <Link to="/modules" aria-label="Back to modules" style={{ textDecoration: "none" }}>
              <GlassButton variant="primary">Back to Modules</GlassButton>
            </Link>
          </div>
        </div>
      </PageTransition>
    );
  }

  // In-progress view
  const question = attempt.questions[currentIdx];
  if (!question) return null;

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 720 }}>
        <p style={{ color: "var(--color-text-secondary)", fontSize: "0.875rem", marginBottom: "0.5rem" }}>
          Question {currentIdx + 1} of {attempt.questions.length}
        </p>

        <GlassCard blur="md" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ color: "var(--color-text)", margin: 0 }}>{question.stem}</h2>
        </GlassCard>

        {question.qtype === "MULTIPLE_CHOICE" && question.options && (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {question.options.map((opt) => {
              const isSelected = question.selected === opt;
              return (
                <motion.button
                  key={opt}
                  onClick={() => selectAnswer(question.id, opt)}
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.98 }}
                  transition={springDefault}
                  aria-label={`Select option: ${opt}`}
                  aria-pressed={isSelected}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    cursor: "pointer",
                    padding: "1rem 1.25rem",
                    borderRadius: "var(--radius-md)",
                    background: isSelected ? "var(--glass-bg-medium)" : "var(--glass-bg-subtle)",
                    border: isSelected
                      ? "1.5px solid var(--color-accent)"
                      : "1px solid var(--glass-border-medium)",
                    color: "var(--color-text)",
                    fontSize: "var(--font-size-base)",
                    fontFamily: "var(--font-family)",
                    boxShadow: isSelected ? "0 0 16px rgba(212, 165, 116, 0.2)" : "none",
                    transition: "box-shadow 150ms ease, border-color 150ms ease, background 150ms ease",
                  }}
                >
                  {opt}
                </motion.button>
              );
            })}
          </div>
        )}

        {question.qtype === "IDENTIFICATION" && (
          <div style={{ marginBottom: "1rem" }}>
            <label
              htmlFor="identification-answer"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}
            >
              Your Answer
            </label>
            <input
              id="identification-answer"
              type="text"
              className="glass-input"
              value={question.selected ?? ""}
              onChange={(e) => selectAnswer(question.id, e.target.value)}
            />
          </div>
        )}

        {error && <p className="error-text" style={{ color: "var(--color-danger)", marginTop: "0.5rem" }}>{error}</p>}

        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1.5rem" }}>
          <GlassButton
            variant="secondary"
            onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
            disabled={currentIdx === 0}
            aria-label="Previous question"
          >
            Previous
          </GlassButton>
          {currentIdx < attempt.questions.length - 1 ? (
            <GlassButton
              variant="primary"
              onClick={() => setCurrentIdx((i) => i + 1)}
              aria-label="Next question"
            >
              Next
            </GlassButton>
          ) : (
            <GlassButton
              variant="primary"
              onClick={submitQuiz}
              disabled={submitting}
              loading={submitting}
              aria-label="Submit quiz"
            >
              {submitting ? "Submitting…" : "Submit Quiz"}
            </GlassButton>
          )}
        </div>
      </div>
    </PageTransition>
  );
}
