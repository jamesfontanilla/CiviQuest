interface GlassSkeletonProps {
  width?: string;
  height?: string;
  borderRadius?: string;
}

export function GlassSkeleton({
  width = "100%",
  height = "1rem",
  borderRadius = "var(--radius-md)",
}: GlassSkeletonProps) {
  return (
    <div
      aria-hidden="true"
      style={{
        width,
        height,
        borderRadius,
        background:
          "linear-gradient(90deg, var(--glass-bg-subtle) 25%, var(--glass-bg-medium) 50%, var(--glass-bg-subtle) 75%)",
        backgroundSize: "200% 100%",
        animation: "glass-shimmer 1.5s ease-in-out infinite",
      }}
    />
  );
}
