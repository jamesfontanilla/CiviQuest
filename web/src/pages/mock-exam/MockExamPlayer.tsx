import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { apiClient } from "../../api/client";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassButton } from "../../components/GlassButton";
import { scaleIn, staggerContainer, staggerItem, springDefault } from "../../design-system";

interface MockQuestion {
  id: number;
  ordinal: number;
  stem: string;
  qtype: string;
  options: string[] | null;
  selected?: string | null;
  finalized_at?: string | null;
  is_correct?: boolean;
  correct_answer?: string;
  explanation?: string;
}

interface WeaknessSummary {
  module_id: number;
  module_title: string;
  percentage: number;
}

interface MockAttempt {
  id: number;
  status: string;
  remaining_seconds?: number;
  nav_policy: string;
  score?: number;
  max_score?: number;
  percentage?: number;
  passed?: boolean;
  weakness_summary?: WeaknessSummary[];
  questions: MockQuestion[];
}

export function MockExamPlayer() {
  const [attempt, setAttempt] = useState<MockAttempt | null>(null);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Timer countdown
  useEffect(() => {
    if (attempt?.status === "IN_PROGRESS" && attempt.remaining_seconds !== undefined) {
      setRemainingSeconds(attempt.remaining_seconds);
      timerRef.current = setInterval(() => {
        setRemainingSeconds((prev) => {
          if (prev <= 1) {
            if (timerRef.current) clearInterval(timerRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [attempt?.id, attempt?.status]);

  // Focus loss detection
  useEffect(() => {
    if (!attempt || attempt.status !== "IN_PROGRESS") return;

    function handleVisibilityChange() {
      if (document.hidden && attempt) {
        apiClient
          .post(`/v1/mock-exams/attempts/${attempt.id}:report-focus-loss`, {
            kind: "visibility_hidden",
            at: new Date().toISOString(),
          })
          .catch(() => {
            /* best-effort */
          });
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [attempt?.id, attempt?.status]);

  async function startExam() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<MockAttempt>("/v1/mock-exams/attempts");
      setAttempt(res);
      setCurrentIdx(0);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start mock exam");
    } finally {
      setLoading(false);
    }
  }

  async function selectAnswer(questionId: number, selected: string) {
    if (!attempt) return;
    try {
      await apiClient.patch(`/v1/mock-exams/attempts/${attempt.id}/answers/${questionId}`, { selected });
      setAttempt((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          questions: prev.questions.map((q) =>
            q.id === questionId ? { ...q, selected, finalized_at: new Date().toISOString() } : q
          ),
        };
      });
      // LINEAR_NO_REVISIT: auto-advance
      if (attempt.nav_policy === "LINEAR_NO_REVISIT") {
        setCurrentIdx((i) => Math.min(i + 1, attempt.questions.length - 1));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save answer");
    }
  }

  async function submitExam() {
    if (!attempt) return;
    setSubmitting(true);
    try {
      const res = await apiClient.post<MockAttempt>(`/v1/mock-exams/attempts/${attempt.id}:submit`, {
        mode: "MANUAL",
      });
      setAttempt(res);
      if (timerRef.current) clearInterval(timerRef.current);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit exam");
    } finally {
      setSubmitting(false);
    }
  }

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  // Not started
  if (!attempt && !loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 600 }}>
          <h1 style={{ color: "var(--color-text)" }}>Mock Exam</h1>
          <p style={{ color: "var(--color-text-secondary)" }}>50 questions · 3 hours · 80% to pass</p>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
            Once started, you cannot access other content until the exam is submitted.
          </p>
          {error && <p className="error-text" style={{ color: "var(--color-danger)" }}>{error}</p>}
          <GlassButton variant="primary" onClick={startExam} aria-label="Start mock exam">
            Start Mock Exam
          </GlassButton>
          <p style={{ marginTop: "1rem" }}>
            <Link to="/modules" aria-label="Back to modules" style={{ color: "var(--color-accent)" }}>
              ← Back
            </Link>
          </p>
        </div>
      </PageTransition>
    );
  }

  if (loading) return <div className="page container" style={{ color: "var(--color-text)" }}>Starting mock exam…</div>;
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
              <h1 style={{ color: "var(--color-text)", marginBottom: "0.5rem" }}>Mock Exam Results</h1>
              <p style={{ fontSize: "2rem", fontWeight: 700, color: "var(--color-accent)" }}>
                {attempt.percentage !== undefined ? `${attempt.percentage.toFixed(1)}%` : "—"}
              </p>
              <p style={{ color: "var(--color-text-secondary)" }}>
                Score: {attempt.score} / {attempt.max_score}
                {attempt.passed !== undefined && (
                  <span style={{ marginLeft: "1rem", color: attempt.passed ? "var(--color-success)" : "var(--color-danger)" }}>
                    {attempt.passed ? "PASSED" : "FAILED"}
                  </span>
                )}
              </p>
            </GlassCard>
          </motion.div>

          {attempt.weakness_summary && attempt.weakness_summary.length > 0 && (
            <motion.section
              aria-label="Weakness summary"
              initial={scaleIn.initial}
              animate={scaleIn.animate}
              transition={{ ...scaleIn.transition, delay: 0.1 }}
            >
              <GlassCard blur="md" style={{ marginBottom: "1.5rem" }}>
                <h2 style={{ color: "var(--color-text)", marginBottom: "0.75rem" }}>Areas to Improve</h2>
                <ol style={{ paddingLeft: "1.25rem", color: "var(--color-text-secondary)" }}>
                  {attempt.weakness_summary.map((w) => (
                    <li key={w.module_id} style={{ marginBottom: "0.375rem" }}>
                      {w.module_title} — {w.percentage.toFixed(1)}%
                    </li>
                  ))}
                </ol>
              </GlassCard>
            </motion.section>
          )}

          <motion.div
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            style={{ display: "grid", gap: "1rem" }}
          >
            {attempt.questions.map((q) => (
              <motion.div key={q.id} variants={staggerItem} transition={springDefault}>
                <GlassCard blur="sm">
                  <p style={{ color: "var(--color-text)", marginBottom: "0.5rem" }}>
                    <strong>
                      {q.ordinal}. {q.stem}
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

  const isLinearNoRevisit = attempt.nav_policy === "LINEAR_NO_REVISIT";
  const isFinalized = !!question.finalized_at;
  const isTimeLow = remainingSeconds < 300;

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 720 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <span style={{ fontSize: "0.875rem", color: "var(--color-text-secondary)" }}>
            Question {currentIdx + 1} of {attempt.questions.length}
          </span>
          <div
            className="glass-sm"
            style={{
              padding: "0.5rem 1rem",
              position: "relative",
              animation: isTimeLow ? "gentle-pulse 2s ease-in-out infinite" : undefined,
            }}
            role="timer"
            aria-label={`Time remaining: ${formatTime(remainingSeconds)}`}
          >
            <span
              style={{
                fontWeight: 600,
                background: "linear-gradient(135deg, var(--color-accent), var(--color-metallic))",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              ⏱ {formatTime(remainingSeconds)}
            </span>
          </div>
        </div>

        <GlassCard blur="md" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ color: "var(--color-text)", margin: 0 }}>{question.stem}</h2>
        </GlassCard>

        {question.qtype === "MULTIPLE_CHOICE" && question.options && (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {question.options.map((opt) => {
              const isSelected = question.selected === opt;
              const isDisabled = isLinearNoRevisit && isFinalized;
              return (
                <motion.button
                  key={opt}
                  onClick={() => !isDisabled && selectAnswer(question.id, opt)}
                  disabled={isDisabled}
                  whileHover={!isDisabled ? { scale: 1.01 } : undefined}
                  whileTap={!isDisabled ? { scale: 0.98 } : undefined}
                  transition={springDefault}
                  aria-label={`Select option: ${opt}`}
                  aria-pressed={isSelected}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    cursor: isDisabled ? "not-allowed" : "pointer",
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
                    opacity: isDisabled ? 0.6 : 1,
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
              htmlFor="mock-answer"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}
            >
              Your Answer
            </label>
            <input
              id="mock-answer"
              type="text"
              className="glass-input"
              value={question.selected ?? ""}
              onChange={(e) => selectAnswer(question.id, e.target.value)}
              disabled={isLinearNoRevisit && isFinalized}
            />
          </div>
        )}

        {error && <p className="error-text" style={{ color: "var(--color-danger)", marginTop: "0.5rem" }}>{error}</p>}

        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1.5rem" }}>
          {!isLinearNoRevisit && (
            <GlassButton
              variant="secondary"
              onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
              disabled={currentIdx === 0}
              aria-label="Previous question"
            >
              Previous
            </GlassButton>
          )}
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
              onClick={submitExam}
              disabled={submitting}
              loading={submitting}
              aria-label="Submit exam"
            >
              {submitting ? "Submitting…" : "Submit Exam"}
            </GlassButton>
          )}
        </div>
      </div>
    </PageTransition>
  );
}
