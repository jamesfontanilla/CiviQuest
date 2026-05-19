import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { apiClient } from "../../api/client";
import { GlassCard } from "../../components/GlassCard";
import { GlassSkeleton } from "../../components/GlassSkeleton";
import { GlassBadge } from "../../components/GlassBadge";
import { GlassProgressBar } from "../../components/GlassProgressBar";
import { PageTransition } from "../../components/PageTransition";
import { staggerContainer, staggerItem } from "../../design-system";
import { useInView } from "../../hooks/useInView";

interface Module {
  id: number;
  title: string;
  description: string | null;
  category: string;
}

interface ModulesResponse {
  items: Module[];
  total: number;
}

export function ModuleList() {
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get<ModulesResponse>("/v1/modules")
      .then((res) => setModules(res.items))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container">
          <h1>Modules</h1>
          <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} style={{ padding: "1.5rem", borderRadius: "var(--radius-lg)" }}>
                <GlassSkeleton width="60%" height="1.25rem" />
                <div style={{ marginTop: "0.75rem" }}>
                  <GlassSkeleton width="100%" height="0.875rem" />
                </div>
                <div style={{ marginTop: "0.5rem" }}>
                  <GlassSkeleton width="80%" height="0.875rem" />
                </div>
                <div style={{ marginTop: "1rem" }}>
                  <GlassSkeleton width="100%" height="8px" borderRadius="var(--radius-full)" />
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
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <h1 style={{ margin: 0 }}>Modules</h1>
          <Link to="/mastery" className="btn-glass btn-glass-primary" style={{ padding: "0.625rem 1.25rem", borderRadius: "var(--radius-md)", textDecoration: "none", fontWeight: 600 }} aria-label="View mastery dashboard">
            Mastery Dashboard
          </Link>
        </div>
        <LazyModuleGrid modules={modules} navigate={navigate} />
        {modules.length === 0 && (
          <p style={{ textAlign: "center", color: "var(--color-text-secondary)", marginTop: "2rem" }}>
            No modules available.
          </p>
        )}
      </div>
    </PageTransition>
  );
}

function LazyModuleGrid({ modules, navigate }: { modules: Module[]; navigate: ReturnType<typeof useNavigate> }) {
  const [gridRef, isGridInView] = useInView();

  return (
    <div ref={gridRef}>
      {isGridInView ? (
        <motion.div
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
        >
          {modules.map((m) => (
            <motion.div key={m.id} variants={staggerItem}>
              <GlassCard
                hoverable
                onClick={() => navigate(`/modules/${m.id}/topics`)}
                style={{
                  borderImage: "linear-gradient(135deg, var(--color-accent), var(--color-metallic)) 1",
                  borderImageSlice: 1,
                  border: "1px solid",
                  borderColor: "rgba(212, 165, 116, 0.2)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                  <h2 style={{ margin: 0, fontSize: "1.0625rem", fontWeight: 600 }}>{m.title}</h2>
                  <GlassBadge label={m.category} color="accent" />
                </div>
                {m.description && (
                  <p style={{ margin: "0 0 1rem 0", color: "var(--color-text-secondary)", fontSize: "0.875rem", lineHeight: 1.5 }}>
                    {m.description}
                  </p>
                )}
                <GlassProgressBar value={0} max={100} label="Progress" height={6} />
              </GlassCard>
            </motion.div>
          ))}
        </motion.div>
      ) : (
        <div style={{ minHeight: "200px" }} />
      )}
    </div>
  );
}
