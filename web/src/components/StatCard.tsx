interface StatCardProps {
  icon: string;
  label: string;
  value: string | number;
  trend?: "up" | "down" | "neutral";
  color?: string;
}

export function StatCard({ icon, label, value, trend, color = "var(--color-accent)" }: StatCardProps) {
  const trendArrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "";
  const trendColor = trend === "up" ? "var(--color-success)" : trend === "down" ? "var(--color-danger)" : "";

  return (
    <div
      style={{
        textAlign: "center",
        padding: "1.25rem",
        background: "var(--glass-bg-medium)",
        backdropFilter: "var(--glass-blur-sm)",
        WebkitBackdropFilter: "var(--glass-blur-sm)",
        border: "1px solid var(--glass-border-medium)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-diffused)",
        transition: "transform var(--transition-fast), box-shadow var(--transition-fast)",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: "var(--radius-md)",
          background: `color-mix(in srgb, ${color} 15%, transparent)`,
          border: "1px solid var(--glass-border-light)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          margin: "0 auto 0.75rem",
          fontSize: "1.25rem",
        }}
        aria-hidden="true"
      >
        {icon}
      </div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--color-text)" }}>
        {value}
        {trendArrow && (
          <span style={{ fontSize: "0.875rem", marginLeft: "0.25rem", color: trendColor }}>
            {trendArrow}
          </span>
        )}
      </div>
      <div style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)", marginTop: "0.25rem" }}>
        {label}
      </div>
    </div>
  );
}
