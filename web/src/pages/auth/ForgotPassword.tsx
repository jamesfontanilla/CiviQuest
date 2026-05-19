import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiClient } from "../../api/client";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassInput } from "../../components/GlassInput";
import { GlassButton } from "../../components/GlassButton";

export function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await apiClient.post("/v1/auth/password-reset-requests", { email });
      setSubmitted(true);
    } catch (err: unknown) {
      // Per spec, response shape is identical whether email exists or not.
      // We still show success to avoid enumeration.
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
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
              Check Your Email
            </h1>
            <p
              style={{
                fontSize: "var(--font-size-base)",
                color: "var(--color-text-secondary)",
                textAlign: "center",
                marginBottom: "1.5rem",
              }}
            >
              If an account exists for {email}, we sent a password reset code.
            </p>
            <GlassButton
              variant="primary"
              onClick={() => navigate("/verify-otp", { state: { email, purpose: "PASSWORD_RESET" } })}
              aria-label="Enter reset code"
              style={{ width: "100%" }}
            >
              Enter Code
            </GlassButton>
          </GlassCard>
        </div>
      </PageTransition>
    );
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
            Forgot Password
          </h1>

          <form onSubmit={handleSubmit} aria-label="Forgot password form">
            <GlassInput
              id="forgot-email"
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
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
              aria-label="Send reset code"
              style={{ width: "100%", marginTop: "0.5rem" }}
            >
              Send Reset Code
            </GlassButton>
          </form>

          <p
            style={{
              marginTop: "1.5rem",
              fontSize: "var(--font-size-sm)",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <Link to="/login" style={{ color: "var(--color-accent)" }}>
              Back to login
            </Link>
          </p>
        </GlassCard>
      </div>
    </PageTransition>
  );
}
