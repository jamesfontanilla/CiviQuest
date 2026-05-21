import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { apiClient } from "../../api/client";
import { GlassCard } from "../../components/GlassCard";
import { GlassSkeleton } from "../../components/GlassSkeleton";
import { PageTransition } from "../../components/PageTransition";
import { staggerContainer, staggerItem } from "../../design-system";

interface Subtopic {
  id: number;
  title: string;
  slug: string;
}

export function SubtopicList() {
  const { topicId } = useParams<{ topicId: string }>();
  const [subtopics, setSubtopics] = useState<Subtopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<Subtopic[]>(`/v1/topics/${topicId}/subtopics`)
      .then((res) => setSubtopics(res))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load subtopics"))
      .finally(() => setLoading(false));
  }, [topicId]);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container">
          <h1>Subtopics</h1>
          <div style={{ display: "grid", gap: "1rem" }}>
            {[1, 2, 3, 4].map((i) => (
              <div key={i} style={{ padding: "1.5rem", borderRadius: "var(--radius-lg)" }}>
                <GlassSkeleton width="70%" height="1.25rem" />
                <div style={{ marginTop: "0.75rem" }}>
                  <GlassSkeleton width="40%" height="0.875rem" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </PageTransition>
    );
  }

  if (error) return <div className="page container error-text">{error}</div>;

  return (
    <PageTransition>
      <div className="page container">
        <Link
          to="/modules"
          aria-label="Back to modules"
          style={{ color: "var(--color-text-secondary)", textDecoration: "none", fontSize: "var(--font-size-sm)" }}
        >
          ← Back
        </Link>
        <h1 style={{ marginTop: "0.75rem" }}>Subtopics</h1>
        <motion.div
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          style={{ display: "grid", gap: "1rem" }}
        >
          {subtopics.map((s) => (
            <motion.div key={s.id} variants={staggerItem}>
              <GlassCard hoverable style={{ cursor: "pointer" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "1.125rem", fontWeight: 600 }}>{s.title}</span>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <Link
                      to={`/subtopics/${s.id}/lesson`}
                      className="btn-glass btn-glass-primary"
                      aria-label={`Read lesson: ${s.title}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      Lesson
                    </Link>
                    <Link
                      to={`/quiz/subtopic/${s.id}`}
                      className="btn-glass btn-glass-primary"
                      aria-label={`Start quiz: ${s.title}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      Quiz
                    </Link>
                  </div>
                </div>
              </GlassCard>
            </motion.div>
          ))}
        </motion.div>
        {subtopics.length === 0 && (
          <p style={{ textAlign: "center", color: "var(--color-text-secondary)", marginTop: "2rem" }}>
            No subtopics in this topic.
          </p>
        )}
      </div>
    </PageTransition>
  );
}
