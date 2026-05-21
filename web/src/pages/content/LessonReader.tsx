import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "../../api/client";
import { GlassCard } from "../../components/GlassCard";
import { GlassSkeleton } from "../../components/GlassSkeleton";
import { PageTransition } from "../../components/PageTransition";
import { GlassProgressBar } from "../../components/GlassProgressBar";
import { MarkdownText } from "../../components/MarkdownText";
import { useToast } from "../../context/ToastContext";

interface LessonExplanation {
  title: string;
  body: string;
}

interface LessonWorkedExample {
  title: string;
  problem?: string;
  solution?: string;
  body?: string;
}

interface LessonContent {
  explanations: LessonExplanation[];
  worked_examples: LessonWorkedExample[];
  key_takeaways: string[];
  summary: string;
}

interface LessonResponse {
  id: number;
  subtopic_id: number;
  content_json: LessonContent;
  status: string;
}

export function LessonReader() {
  const { subtopicId } = useParams<{ subtopicId: string }>();
  const toast = useToast();
  const [lesson, setLesson] = useState<LessonResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [completing, setCompleting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    explanations: true,
    examples: false,
    takeaways: false,
    summary: false,
  });

  useEffect(() => {
    apiClient
      .get<LessonResponse>(`/v1/subtopics/${subtopicId}/lesson`)
      .then((res) => setLesson(res))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [subtopicId]);

  async function handleMarkComplete() {
    setCompleting(true);
    try {
      await apiClient.post(`/v1/subtopics/${subtopicId}/lesson:complete`, {});
      setCompleted(true);
      toast.success("✅ Lesson marked complete");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to mark complete";
      toast.error(msg);
      setError(msg);
    } finally {
      setCompleting(false);
    }
  }

  function toggleSection(key: string) {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 720 }}>
          <div style={{ marginBottom: "1.5rem" }}>
            <GlassSkeleton width="120px" height="1rem" />
          </div>
          <GlassSkeleton width="100%" height="4px" borderRadius="var(--radius-full)" />
          <div style={{ marginTop: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
            <GlassSkeleton width="60%" height="1.25rem" />
            <GlassSkeleton width="100%" height="6rem" borderRadius="var(--radius-lg)" />
            <GlassSkeleton width="100%" height="6rem" borderRadius="var(--radius-lg)" />
          </div>
        </div>
      </PageTransition>
    );
  }

  if (error) return <div className="page container error-text">{error}</div>;
  if (!lesson) return <div className="page container" style={{ color: "var(--color-text-secondary)" }}>Lesson not found.</div>;

  const content = lesson.content_json;
  const sections = [
    { key: "explanations", title: "📖 Explanations", items: content.explanations.map((e) => typeof e === "string" ? e : `**${e.title}**\n\n${e.body}`) },
    { key: "examples", title: "💡 Worked Examples", items: content.worked_examples.map((e) => typeof e === "string" ? e : `**${e.title}**\n\n${e.problem || ""}${e.solution ? "\n\n" + e.solution : ""}${e.body ? "\n\n" + e.body : ""}`) },
    { key: "takeaways", title: "🔑 Key Takeaways", items: content.key_takeaways },
  ];
  const totalSections = sections.length + 1; // +1 for summary
  const expandedCount = Object.values(expandedSections).filter(Boolean).length;

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 720 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <Link
            to="/modules"
            aria-label="Back to modules"
            className="btn-glass"
            style={{ padding: "0.375rem 0.75rem", fontSize: "var(--font-size-sm)" }}
          >
            ← Back
          </Link>
          <div style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
            Step {expandedCount} of {totalSections}
          </div>
        </div>

        <GlassProgressBar value={expandedCount} max={totalSections} height={4} />

        <article style={{ marginTop: "1.5rem" }}>
          {sections.map((section) => (
            <CollapsibleSection
              key={section.key}
              title={section.title}
              expanded={expandedSections[section.key]}
              onToggle={() => toggleSection(section.key)}
            >
              {section.key === "takeaways" ? (
                <GlassCard blur="sm" style={{ background: "rgba(212, 165, 116, 0.08)", border: "1px solid var(--color-accent)" }}>
                  <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                    {section.items.map((text, i) => (
                      <li key={i} style={{ marginBottom: "0.5rem", lineHeight: 1.7, color: "var(--color-text)" }}>
                        <MarkdownText text={text} />
                      </li>
                    ))}
                  </ul>
                </GlassCard>
              ) : section.key === "examples" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  {section.items.map((text, i) => (
                    <GlassCard key={i} blur="sm">
                      <MarkdownText text={text} style={{ lineHeight: 1.7, color: "var(--color-text)" }} />
                    </GlassCard>
                  ))}
                </div>
              ) : (
                section.items.map((text, i) => (
                  <ExplanationDropdown key={i} text={text} index={i} />
                ))
              )}
            </CollapsibleSection>
          ))}

          <CollapsibleSection
            title="📝 Summary"
            expanded={expandedSections.summary}
            onToggle={() => toggleSection("summary")}
          >
            <MarkdownText text={content.summary} style={{ lineHeight: 1.7, color: "var(--color-text)" }} />
          </CollapsibleSection>
        </article>

        <div style={{ marginTop: "2rem", paddingBottom: "2rem" }}>
          {completed ? (
            <p style={{ color: "var(--color-success)", fontWeight: 600 }}>✓ Lesson completed</p>
          ) : (
            <button
              className="btn-glass btn-glass-primary"
              onClick={handleMarkComplete}
              disabled={completing}
              aria-label="Mark lesson as complete"
              style={{ padding: "0.75rem 1.5rem" }}
            >
              {completing ? "Marking…" : "Mark Complete"}
            </button>
          )}
        </div>
      </div>
    </PageTransition>
  );
}

function CollapsibleSection({
  title,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} style={{ marginBottom: "1.25rem" }}>
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "0.75rem 0",
          background: "none",
          border: "none",
          borderBottom: "1px solid var(--glass-border-medium)",
          cursor: "pointer",
          fontSize: "1.0625rem",
          fontWeight: 600,
          color: "var(--color-text)",
          textAlign: "left",
        }}
      >
        {title}
        <span style={{ fontSize: "0.875rem", color: "var(--color-text-muted)", transition: "transform var(--transition-fast)", transform: expanded ? "rotate(180deg)" : "rotate(0)" }}>
          ▼
        </span>
      </button>
      {expanded && (
        <div style={{ padding: "1rem 0", animation: "fadeIn 0.2s ease" }}>
          {children}
        </div>
      )}
    </section>
  );
}

function ExplanationDropdown({ text, index }: { text: string; index: number }) {
  const [open, setOpen] = useState(index === 0);

  // Extract the title from the markdown bold heading (first line like **Title**)
  // The text format is: "**Title**\n\nBody..."
  const titleMatch = text.match(/^\*\*(.+?)\*\*/);
  const title = titleMatch ? titleMatch[1] : `Section ${index + 1}`;
  const body = titleMatch ? text.slice(titleMatch[0].length).trim() : text;

  // Detect if this is a numbered section (4.1, 4.2, etc.) — these get dropdowns
  const isNumberedSection = /^\d+\.\d+\s/.test(title);

  // Non-numbered sections (Introduction, Why it Matters, Learning Objectives, etc.)
  // render inline without a dropdown
  if (!isNumberedSection) {
    return (
      <div style={{ marginBottom: "1.5rem" }}>
        <MarkdownText text={text} style={{ lineHeight: 1.7, color: "var(--color-text)" }} />
      </div>
    );
  }

  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "0.625rem 0.75rem",
          background: "rgba(255, 255, 255, 0.03)",
          border: "1px solid var(--glass-border-medium)",
          borderRadius: "var(--radius-md)",
          cursor: "pointer",
          fontSize: "0.9375rem",
          fontWeight: 600,
          color: "var(--color-text)",
          textAlign: "left",
        }}
      >
        {title}
        <span
          style={{
            fontSize: "0.75rem",
            color: "var(--color-text-muted)",
            transition: "transform var(--transition-fast)",
            transform: open ? "rotate(180deg)" : "rotate(0)",
            flexShrink: 0,
            marginLeft: "0.5rem",
          }}
        >
          ▼
        </span>
      </button>
      {open && (
        <div
          style={{
            padding: "1rem 0.75rem",
            borderLeft: "2px solid var(--color-accent)",
            marginLeft: "0.5rem",
            marginTop: "0.25rem",
            animation: "fadeIn 0.2s ease",
          }}
        >
          <MarkdownText text={body} style={{ lineHeight: 1.7, color: "var(--color-text)" }} />
        </div>
      )}
    </div>
  );
}
