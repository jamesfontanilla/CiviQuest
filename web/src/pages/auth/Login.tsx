import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiClient } from "../../api/client";
import { login } from "../../stores/auth";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassInput } from "../../components/GlassInput";
import { GlassButton } from "../../components/GlassButton";
import { GoogleSignInWithCategoryPicker } from "../../components/GoogleSignInButton";

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await apiClient.post<LoginResponse>("/v1/auth/sessions", {
        email,
        password,
      });
      login(res.access_token);
      // Redirect admins to admin dashboard, learners to modules
      if (email.toLowerCase() === "admin@cse.local") {
        navigate("/admin");
      } else {
        navigate("/modules");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
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
            Log In
          </h1>

          <form onSubmit={handleSubmit} aria-label="Login form">
            <GlassInput
              id="login-email"
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />

            <GlassInput
              id="login-password"
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />

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
              aria-label="Log in"
              style={{ width: "100%", marginTop: "0.5rem" }}
            >
              Log In
            </GlassButton>
          </form>

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

          <GoogleSignInWithCategoryPicker />

          <p
            style={{
              marginTop: "1.5rem",
              fontSize: "var(--font-size-sm)",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <Link to="/forgot-password" style={{ color: "var(--color-accent)" }}>
              Forgot password?
            </Link>
            {" · "}
            <Link to="/signup" style={{ color: "var(--color-accent)" }}>
              Create account
            </Link>
          </p>
        </GlassCard>
      </div>
    </PageTransition>
  );
}
