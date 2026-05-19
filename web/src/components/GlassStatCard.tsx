import { GlassCard } from "./GlassCard";

interface GlassStatCardProps {
  title: string;
  value: string | number;
  icon?: React.ReactNode;
  trend?: { direction: "up" | "down"; label: string };
}

export function GlassStatCard({ title, value, icon, trend }: GlassStatCardProps) {
  return (
    <GlassCard blur="sm" hoverable>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)", fontWeight: 500 }}>
            {title}
          </p>
          <p style={{ margin: "0.25rem 0 0", fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)", background: "linear-gradient(135deg, var(--color-accent), var(--color-metallic))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            {value}
          </p>
          {trend && (
            <span style={{ fontSize: "var(--font-size-xs)", color: trend.direction === "up" ? "var(--color-success)" : "var(--color-danger)" }}>
              {trend.direction === "up" ? "↑" : "↓"} {trend.label}
            </span>
          )}
        </div>
        {icon && (
          <span style={{ fontSize: "1.5rem", color: "var(--color-accent)", opacity: 0.8 }} aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
    </GlassCard>
  );
}
