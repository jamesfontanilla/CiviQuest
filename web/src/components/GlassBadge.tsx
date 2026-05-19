interface GlassBadgeProps {
  label: string;
  color?: "primary" | "success" | "warning" | "danger" | "accent";
  size?: "sm" | "md";
}

const colorMap: Record<string, { bg: string; border: string; text: string }> = {
  primary: {
    bg: "rgba(62, 39, 35, 0.2)",
    border: "rgba(62, 39, 35, 0.3)",
    text: "var(--color-highlight)",
  },
  success: {
    bg: "rgba(129, 199, 132, 0.15)",
    border: "rgba(129, 199, 132, 0.3)",
    text: "var(--color-success)",
  },
  warning: {
    bg: "rgba(255, 183, 77, 0.15)",
    border: "rgba(255, 183, 77, 0.3)",
    text: "var(--color-warning)",
  },
  danger: {
    bg: "rgba(229, 115, 115, 0.15)",
    border: "rgba(229, 115, 115, 0.3)",
    text: "var(--color-danger)",
  },
  accent: {
    bg: "rgba(212, 165, 116, 0.15)",
    border: "rgba(212, 165, 116, 0.3)",
    text: "var(--color-accent)",
  },
};

export function GlassBadge({ label, color = "primary", size = "sm" }: GlassBadgeProps) {
  const colors = colorMap[color];
  const sizeStyles = size === "sm"
    ? { padding: "0.125rem 0.5rem", fontSize: "var(--font-size-xs)" }
    : { padding: "0.25rem 0.75rem", fontSize: "var(--font-size-sm)" };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: "var(--radius-full)",
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        color: colors.text,
        fontWeight: 500,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        ...sizeStyles,
      }}
    >
      {label}
    </span>
  );
}
