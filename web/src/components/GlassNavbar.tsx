import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { isAuthenticated } from "../stores/auth";
import { slideDown, springDefault } from "../design-system";
import "./GlassNavbar.css";

const NAV_LINKS = [
  { to: "/modules", label: "Modules" },
  { to: "/mastery", label: "Mastery" },
  { to: "/focus", label: "Focus" },
  { to: "/study-plan", label: "Study Plan" },
  { to: "/readiness", label: "Readiness" },
  { to: "/goals", label: "Goals" },
  { to: "/tournaments", label: "Tournaments" },
  { to: "/analytics", label: "Analytics" },
  { to: "/leaderboard", label: "Leaderboard" },
];

export function GlassNavbar() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    function handleScroll() {
      setScrolled(window.scrollY > 10);
    }
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Close mobile menu on route change
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const authenticated = isAuthenticated();

  return (
    <header
      className="glass-navbar"
      style={{
        background: scrolled ? "var(--glass-bg-medium)" : "transparent",
        backdropFilter: scrolled ? "var(--glass-blur-md)" : "none",
        WebkitBackdropFilter: scrolled ? "var(--glass-blur-md)" : "none",
        borderBottom: scrolled
          ? "1px solid var(--glass-border-light)"
          : "1px solid transparent",
      }}
    >
      {/* Logo */}
      <Link to="/" className="glass-navbar-logo" aria-label="CiviQuest Home">
        🎓 CiviQuest
      </Link>

      {/* Desktop Nav */}
      {authenticated && (
        <nav aria-label="Main navigation" className="glass-navbar-desktop">
          {NAV_LINKS.map((link) => {
            const active = location.pathname.startsWith(link.to);
            return (
              <Link
                key={link.to}
                to={link.to}
                className={`glass-navbar-link${active ? " active" : ""}`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      )}

      {/* Right side */}
      <div className="glass-navbar-right">
        {authenticated && (
          <Link to="/profile" className="glass-navbar-profile" aria-label="Profile">
            👤
          </Link>
        )}
        {/* Mobile hamburger */}
        {authenticated && (
          <button
            className="glass-navbar-hamburger"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? "✕" : "☰"}
          </button>
        )}
      </div>

      {/* Mobile drawer */}
      <AnimatePresence>
        {menuOpen && authenticated && (
          <motion.nav
            className="glass-md glass-mobile-drawer"
            aria-label="Mobile navigation"
            initial={slideDown.initial}
            animate={slideDown.animate}
            exit={slideDown.exit}
            transition={springDefault}
          >
            {NAV_LINKS.map((link) => {
              const active = location.pathname.startsWith(link.to);
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  className={`glass-mobile-drawer-link${active ? " active" : ""}`}
                >
                  {link.label}
                </Link>
              );
            })}
            <Link to="/profile" className="glass-mobile-drawer-link">
              Profile
            </Link>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
