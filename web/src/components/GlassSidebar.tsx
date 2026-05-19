import { Link, useLocation } from "react-router-dom";

interface SidebarLink {
  to: string;
  label: string;
  icon?: React.ReactNode;
}

interface GlassSidebarProps {
  links: SidebarLink[];
}

export function GlassSidebar({ links }: GlassSidebarProps) {
  const location = useLocation();

  return (
    <aside
      className="glass-md"
      style={{
        padding: "1rem 0.75rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
        minWidth: "200px",
      }}
    >
      {links.map((link) => {
        const active = location.pathname.startsWith(link.to);
        return (
          <Link
            key={link.to}
            to={link.to}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.625rem 0.875rem",
              borderRadius: "var(--radius-sm)",
              fontSize: "var(--font-size-sm)",
              fontWeight: 500,
              color: active ? "var(--color-accent)" : "var(--color-text-secondary)",
              background: active ? "var(--glass-bg-medium)" : "transparent",
              textDecoration: "none",
              transition: "background var(--transition-fast), color var(--transition-fast)",
            }}
          >
            {link.icon && <span aria-hidden="true">{link.icon}</span>}
            {link.label}
          </Link>
        );
      })}
    </aside>
  );
}
