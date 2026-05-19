import { useState, useEffect } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { GlassProgressBar } from "../components/GlassProgressBar";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface PlanData {
  id: number;
  target_exam_date: string;
  available_hours_per_day: number;
  target_score: number;
  status: string;
  total_days: number;
  days_remaining: number;
  completion_percentage: number;
}

interface TaskData {
  id: number;
  plan_date: string;
  subtopic_title: string;
  activity_type: string;
  estimated_minutes: number;
  completed: boolean;
}

export function StudyPlan() {
  const [plan, setPlan] = useState<PlanData | null>(null);
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  // Form state
  const [examDate, setExamDate] = useState("");
  const [hours, setHours] = useState("2");
  const [targetScore, setTargetScore] = useState("0.8");

  const fetchPlan = async () => {
    try {
      const data = await apiClient.get<PlanData | null>("/v1/planner/plans/me");
      setPlan(data);
      if (data) {
        const todayTasks = await apiClient.get<TaskData[]>("/v1/planner/plans/me/today");
        setTasks(todayTasks);
      }
    } catch {
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlan();
  }, []);

  const handleCreate = async () => {
    if (!examDate) return;
    setCreating(true);
    try {
      const data = await apiClient.post<PlanData>("/v1/planner/plans", {
        target_exam_date: examDate,
        available_hours_per_day: Number(hours),
        target_score: Number(targetScore),
      });
      setPlan(data);
      const todayTasks = await apiClient.get<TaskData[]>("/v1/planner/plans/me/today");
      setTasks(todayTasks);
    } catch {
      alert("Failed to create plan");
    } finally {
      setCreating(false);
    }
  };

  const handleComplete = async (taskId: number) => {
    try {
      await apiClient.post(`/v1/planner/plans/me/tasks/${taskId}:complete`);
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, completed: true } : t)));
    } catch {
      // silent
    }
  };

  const handleAbandon = async () => {
    if (!confirm("Abandon your current study plan?")) return;
    try {
      await apiClient.delete("/v1/planner/plans/me");
      setPlan(null);
      setTasks([]);
    } catch {
      // silent
    }
  };

  if (loading) {
    return (
      <PageTransition>
        <main className="page container" style={{ maxWidth: 720 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            📅 Study Plan
          </h1>
          <GlassCard style={{ marginBottom: "1.5rem" }}>
            <GlassSkeleton height="1.25rem" width="60%" />
            <div style={{ marginTop: "1rem" }}>
              <GlassSkeleton height="0.5rem" />
            </div>
            <div style={{ marginTop: "0.5rem" }}>
              <GlassSkeleton height="0.75rem" width="30%" />
            </div>
          </GlassCard>
          <GlassCard>
            <GlassSkeleton height="8rem" />
          </GlassCard>
        </main>
      </PageTransition>
    );
  }

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 720 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          📅 Study Plan
        </h1>

        {!plan ? (
          <GlassCard>
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
              Create a Study Plan
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", maxWidth: 320 }}>
              <label>
                <span style={{ fontSize: "var(--font-size-sm)", display: "block", marginBottom: "0.25rem", color: "var(--color-text-secondary)" }}>
                  Target Exam Date
                </span>
                <input
                  type="date"
                  value={examDate}
                  onChange={(e) => setExamDate(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--glass-border-medium)",
                    background: "var(--glass-bg-subtle)",
                    color: "var(--color-text)",
                    fontSize: "var(--font-size-base)",
                  }}
                />
              </label>
              <label>
                <span style={{ fontSize: "var(--font-size-sm)", display: "block", marginBottom: "0.25rem", color: "var(--color-text-secondary)" }}>
                  Hours per Day
                </span>
                <input
                  type="number"
                  min="0.5"
                  max="12"
                  step="0.5"
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--glass-border-medium)",
                    background: "var(--glass-bg-subtle)",
                    color: "var(--color-text)",
                    fontSize: "var(--font-size-base)",
                  }}
                />
              </label>
              <label>
                <span style={{ fontSize: "var(--font-size-sm)", display: "block", marginBottom: "0.25rem", color: "var(--color-text-secondary)" }}>
                  Target Score (%)
                </span>
                <input
                  type="number"
                  min="50"
                  max="100"
                  value={Math.round(Number(targetScore) * 100)}
                  onChange={(e) => setTargetScore(String(Number(e.target.value) / 100))}
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--glass-border-medium)",
                    background: "var(--glass-bg-subtle)",
                    color: "var(--color-text)",
                    fontSize: "var(--font-size-base)",
                  }}
                />
              </label>
              <GlassButton variant="primary" onClick={handleCreate} disabled={creating || !examDate}>
                {creating ? "Creating..." : "Create Plan"}
              </GlassButton>
            </div>
          </GlassCard>
        ) : (
          <div>
            {/* Plan overview */}
            <GlassCard style={{ marginBottom: "1.5rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                <div>
                  <p style={{ fontWeight: 600, color: "var(--color-text)" }}>Exam: {plan.target_exam_date}</p>
                  <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                    {plan.days_remaining} days remaining • {plan.available_hours_per_day}h/day
                  </p>
                </div>
                <GlassButton variant="danger" size="sm" onClick={handleAbandon}>
                  Abandon
                </GlassButton>
              </div>
              <GlassProgressBar
                value={plan.completion_percentage}
                label={`${plan.completion_percentage.toFixed(1)}% complete`}
              />
            </GlassCard>

            {/* Today's Tasks */}
            <GlassCard as="section">
              <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.75rem" }}>
                Today's Tasks
              </h2>
              {tasks.length === 0 ? (
                <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>
                  No tasks scheduled for today.
                </p>
              ) : (
                <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  {tasks.map((task) => (
                    <li
                      key={task.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.75rem",
                        padding: "0.75rem",
                        background: "var(--glass-bg-subtle)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--glass-border-light)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={task.completed}
                        onChange={() => !task.completed && handleComplete(task.id)}
                        disabled={task.completed}
                        aria-label={`Complete ${task.subtopic_title}`}
                      />
                      <div style={{ flex: 1 }}>
                        <p style={{ fontWeight: 500, color: "var(--color-text)", textDecoration: task.completed ? "line-through" : "none" }}>
                          {task.subtopic_title}
                        </p>
                        <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>
                          {task.activity_type} • {task.estimated_minutes} min
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>
          </div>
        )}
      </main>
    </PageTransition>
  );
}
