import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiClient } from "../../api/client";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassInput } from "../../components/GlassInput";
import { GlassButton } from "../../components/GlassButton";
import { GoogleSignInWithCategoryPicker } from "../../components/GoogleSignInButton";

export function Signup() {
  const navigate = useNavigate();
  const [showEmailForm, setShowEmailForm] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [age, setAge] = useState("");
  const [category, setCategory] = useState("PROFESSIONAL");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await apiClient.post("/v1/auth/signups", {
        email,
        display_name: displayName,
        password,
        age: parseInt(age, 10),
        category,
      });
      navigate("/login");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Signup failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageTransition>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "calc(100vh - 4rem)",
          padding: "2rem 1rem",
        }}
      >
        <GlassCard
          blur="lg"
          style={{
            width: "100%",
            maxWidth: "420px",
            padding: "2.5rem",
          }}
        >
          <h1
            style={{
              fontFamily: "var(--font-family)",
              fontSize: "var(--font-size-3xl)",
              fontWeight: 700,
              color: "var(--color-text)",
              textAlign: "center",
              marginBottom: "2rem",
              letterSpacing: "-0.02em",
            }}
          >
            Create Account
          </h1>

          {/* Google OAuth */}
          <GoogleSignInWithCategoryPicker />

          {/* Divider */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              margin: "1.5rem 0",
              gap: "0.75rem",
            }}
          >
            <div style={{ flex: 1, height: "1px", background: "var(--glass-border-light)" }} />
            <span
              style={{
                fontSize: "var(--font-size-sm)",
                color: "var(--color-text-secondary)",
                whiteSpace: "nowrap",
              }}
            >
              or
            </span>
            <div style={{ flex: 1, height: "1px", background: "var(--glass-border-light)" }} />
          </div>

          {/* Continue with Email toggle */}
          {!showEmailForm ? (
            <GlassButton
              variant="secondary"
              type="button"
              onClick={() => setShowEmailForm(true)}
              aria-label="Continue with email"
              style={{ width: "100%" }}
            >
              Continue with Email
            </GlassButton>
          ) : (
            <form onSubmit={handleSubmit} aria-label="Signup form">
              <GlassInput
                id="signup-email"
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />

              <GlassInput
                id="signup-display-name"
                label="Display Name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                maxLength={255}
                placeholder="Your name"
                autoComplete="name"
              />

              <GlassInput
                id="signup-password"
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="new-password"
              />
              <p
                style={{
                  color: "var(--color-text-secondary)",
                  fontSize: "var(--font-size-sm)",
                  marginTop: "-0.5rem",
                  marginBottom: "0.75rem",
                }}
              >
                Min 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 special character
              </p>

              <GlassInput
                id="signup-age"
                label="Age"
                type="number"
                min={15}
                max={100}
                value={age}
                onChange={(e) => setAge(e.target.value)}
                required
              />

              <div style={{ marginBottom: "1rem" }}>
                <label
                  htmlFor="signup-category"
                  className="glass-input-label"
                  style={{
                    display: "block",
                    marginBottom: "0.375rem",
                    fontSize: "var(--font-size-sm)",
                    fontWeight: 500,
                    color: "var(--color-text-secondary)",
                  }}
                >
                  Category
                </label>
                <select
                  id="signup-category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  aria-label="Exam category"
                  className="glass-input"
                  style={{
                    width: "100%",
                    padding: "0.625rem 0.875rem",
                    fontSize: "var(--font-size-base)",
                    borderRadius: "var(--radius-md)",
                    background: "rgba(255, 255, 255, 0.05)",
                    border: "1px solid var(--glass-border-light)",
                    color: "var(--color-text)",
                  }}
                >
                  <option value="PROFESSIONAL">Professional</option>
                  <option value="SUB_PROFESSIONAL">Sub-Professional</option>
                </select>
              </div>

              {error && (
                <p
                  role="alert"
                  style={{
                    color: "var(--color-danger)",
                    fontSize: "var(--font-size-sm)",
                    marginBottom: "1rem",
                    padding: "0.5rem 0.75rem",
                    borderRadius: "var(--radius-sm)",
                    background: "rgba(229, 115, 115, 0.1)",
                    border: "1px solid rgba(229, 115, 115, 0.2)",
                  }}
                >
                  {error}
                </p>
              )}

              <GlassButton
                variant="primary"
                type="submit"
                disabled={loading}
                loading={loading}
                aria-label="Sign up"
                style={{ width: "100%", marginTop: "0.5rem" }}
              >
                Sign Up
              </GlassButton>
            </form>
          )}

          <p
            style={{
              marginTop: "1.5rem",
              fontSize: "var(--font-size-sm)",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            Already have an account?{" "}
            <Link to="/login" style={{ color: "var(--color-accent)" }}>
              Log in
            </Link>
          </p>
        </GlassCard>
      </div>
    </PageTransition>
  );
}
