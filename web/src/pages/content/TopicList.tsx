import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { apiClient } from "../../api/client";
import { GlassCard } from "../../components/GlassCard";
import { GlassSkeleton } from "../../components/GlassSkeleton";
import { PageTransition } from "../../components/PageTransition";
import { staggerContainer, staggerItem } from "../../design-system";

interface Topic {
  id: number;
  title: string;
  slug: string;
}

export function TopicList() {
  const { moduleId } = useParams<{ moduleId: string }>();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get<Topic[]>(`/v1/modules/${moduleId}/topics`)
      .then((res) => setTopics(res))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [moduleId]);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container">
          <h1>Topics</h1>
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
          ← Modules
        </Link>
        <h1 style={{ marginTop: "0.75rem" }}>Topics</h1>
        <motion.div
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          style={{ display: "grid", gap: "1rem" }}
        >
          {topics.map((t) => (
            <motion.div key={t.id} variants={staggerItem}>
              <GlassCard
                hoverable
                onClick={() => navigate(`/topics/${t.id}/subtopics`)}
                style={{ cursor: "pointer" }}
              >
                <h2 style={{ margin: 0, fontSize: "1.125rem", fontWeight: 600 }}>{t.title}</h2>
              </GlassCard>
            </motion.div>
          ))}
        </motion.div>
        {topics.length === 0 && (
          <p style={{ textAlign: "center", color: "var(--color-text-secondary)", marginTop: "2rem" }}>
            No topics in this module.
          </p>
        )}
      </div>
    </PageTransition>
  );
}
