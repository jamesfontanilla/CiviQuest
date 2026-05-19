import { useState, type FormEvent } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { apiClient } from "../../api/client";
import { login } from "../../stores/auth";
import { PageTransition } from "../../components/PageTransition";
import { GlassCard } from "../../components/GlassCard";
import { GlassInput } from "../../components/GlassInput";
import { GlassButton } from "../../components/GlassButton";

interface VerifyResponse {
  token?: string;
}

export function OTPVerification() {
  const navigate = useNavigate();
  const location = useLocation();
  const { email = "", purpose = "VERIFY_EMAIL" } = (location.state as { email?: string; purpose?: string }) ?? {};

  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isPasswordReset = purpose === "PASSWORD_RESET";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isPasswordReset) {
        await apiClient.post("/v1/auth/password-resets", {
          email,
          code,
          new_password: newPassword,
        });
        navigate("/login");
      } else {
        const res = await apiClient.post<VerifyResponse>("/v1/auth/email-verifications", {
          email,
          code,
        });
        if (res.token) {
          login(res.token);
          navigate("/modules");
        } else {
          navigate("/login");
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification failed";
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
              marginBottom: "0.5rem",
              letterSpacing: "-0.02em",
            }}
          >
            {isPasswordReset ? "Reset Password" : "Verify Email"}
          </h1>

          <p
            style={{
              color: "var(--color-text-secondary)",
              fontSize: "var(--font-size-sm)",
              textAlign: "center",
              marginBottom: "2rem",
            }}
          >
            Enter the 6-digit code sent to {email || "your email"}
          </p>

          <form onSubmit={handleSubmit} aria-label="OTP verification form">
            <GlassInput
              id="otp-code"
              label="Verification Code"
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              autoComplete="one-time-code"
            />

            {isPasswordReset && (
              <GlassInput
                id="new-password"
                label="New Password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                autoComplete="new-password"
              />
            )}

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
              aria-label="Verify code"
              style={{ width: "100%", marginTop: "0.5rem" }}
            >
              Verify
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
