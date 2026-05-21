import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import { login } from "../stores/auth";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: GoogleIdConfig) => void;
          renderButton: (element: HTMLElement, config: GoogleButtonConfig) => void;
        };
      };
    };
  }
}

interface GoogleIdConfig {
  client_id: string;
  callback: (response: GoogleCredentialResponse) => void;
  auto_select?: boolean;
}

interface GoogleButtonConfig {
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with";
  shape?: "rectangular" | "pill" | "circle" | "square";
  width?: number;
  logo_alignment?: "left" | "center";
}

interface GoogleCredentialResponse {
  credential: string;
  select_by: string;
}

interface GoogleAuthApiResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  is_new_user: boolean;
  user: {
    id: number;
    email: string;
    display_name: string;
    category: string;
  };
}

interface GoogleSignInButtonProps {
  /** Category to send for new signups. If null, shows category picker on new user. */
  category?: string | null;
  /** Button text variant */
  text?: "signin_with" | "signup_with" | "continue_with";
}

export function GoogleSignInButton({
  category = null,
  text = "continue_with",
}: GoogleSignInButtonProps) {
  const navigate = useNavigate();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId || !buttonRef.current) return;

    const interval = setInterval(() => {
      if (window.google?.accounts?.id && buttonRef.current) {
        clearInterval(interval);

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleCredentialResponse,
        });

        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: "outline",
          size: "large",
          text,
          shape: "rectangular",
          width: 360,
          logo_alignment: "left",
        });
      }
    }, 100);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  async function handleCredentialResponse(response: GoogleCredentialResponse) {
    setError(null);
    setLoading(true);

    try {
      const res = await apiClient.post<GoogleAuthApiResponse>("/v1/auth/google", {
        id_token: response.credential,
        category,
      });

      login(res.access_token);
      navigate("/modules");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Google sign-in failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  // Expose submitWithCategory via a ref-like pattern
  // We'll use a simpler approach: render the category modal inline
  if (!clientId) {
    return null; // Don't render if Google Client ID isn't configured
  }

  return (
    <div style={{ width: "100%" }}>
      <div
        ref={buttonRef}
        style={{
          display: "flex",
          justifyContent: "center",
          minHeight: "44px",
          opacity: loading ? 0.6 : 1,
          pointerEvents: loading ? "none" : "auto",
        }}
      />
      {error && (
        <p
          role="alert"
          style={{
            color: "var(--color-danger)",
            fontSize: "var(--font-size-sm)",
            marginTop: "0.5rem",
            textAlign: "center",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A version of the Google button that handles category selection inline.
 * Use this on the Login page where category isn't pre-selected.
 */
export function GoogleSignInWithCategoryPicker() {
  const navigate = useNavigate();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCategoryPicker, setShowCategoryPicker] = useState(false);
  const [pendingCredential, setPendingCredential] = useState<string | null>(null);

  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId || !buttonRef.current) return;

    const interval = setInterval(() => {
      if (window.google?.accounts?.id && buttonRef.current) {
        clearInterval(interval);

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleCredentialResponse,
        });

        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          width: 360,
          logo_alignment: "left",
        });
      }
    }, 100);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  async function handleCredentialResponse(response: GoogleCredentialResponse) {
    setError(null);
    setLoading(true);

    try {
      // First try without category (works for returning users)
      const res = await apiClient.post<GoogleAuthApiResponse>("/v1/auth/google", {
        id_token: response.credential,
        category: null,
      });

      login(res.access_token);
      navigate("/modules");
    } catch (err: unknown) {
      if (err instanceof Error && err.message.includes("category_required")) {
        // New user — show category picker
        setPendingCredential(response.credential);
        setShowCategoryPicker(true);
      } else {
        const msg = err instanceof Error ? err.message : "Google sign-in failed";
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleCategorySelect(selectedCategory: string) {
    if (!pendingCredential) return;
    setError(null);
    setLoading(true);

    try {
      const res = await apiClient.post<GoogleAuthApiResponse>("/v1/auth/google", {
        id_token: pendingCredential,
        category: selectedCategory,
      });

      login(res.access_token);
      setPendingCredential(null);
      setShowCategoryPicker(false);
      navigate("/modules");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Google sign-in failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (!clientId) {
    return null;
  }

  return (
    <div style={{ width: "100%" }}>
      {!showCategoryPicker && (
        <div
          ref={buttonRef}
          style={{
            display: "flex",
            justifyContent: "center",
            minHeight: "44px",
            opacity: loading ? 0.6 : 1,
            pointerEvents: loading ? "none" : "auto",
          }}
        />
      )}

      {showCategoryPicker && (
        <div
          style={{
            padding: "1.25rem",
            borderRadius: "var(--radius-md)",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid var(--glass-border-light)",
          }}
        >
          <p
            style={{
              fontSize: "var(--font-size-sm)",
              fontWeight: 600,
              color: "var(--color-text)",
              marginBottom: "0.75rem",
              textAlign: "center",
            }}
          >
            Choose your review category
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={() => handleCategorySelect("PROFESSIONAL")}
              disabled={loading}
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--glass-border-light)",
                background: "rgba(26, 115, 232, 0.1)",
                color: "var(--color-text)",
                cursor: "pointer",
                fontSize: "var(--font-size-sm)",
                fontWeight: 500,
                textAlign: "left",
                transition: "background 0.2s",
              }}
            >
              <strong>Professional</strong>
              <br />
              <span style={{ color: "var(--color-text-secondary)", fontSize: "0.75rem" }}>
                For bachelor's degree holders
              </span>
            </button>
            <button
              type="button"
              onClick={() => handleCategorySelect("SUB_PROFESSIONAL")}
              disabled={loading}
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--glass-border-light)",
                background: "rgba(26, 115, 232, 0.1)",
                color: "var(--color-text)",
                cursor: "pointer",
                fontSize: "var(--font-size-sm)",
                fontWeight: 500,
                textAlign: "left",
                transition: "background 0.2s",
              }}
            >
              <strong>Sub-Professional</strong>
              <br />
              <span style={{ color: "var(--color-text-secondary)", fontSize: "0.75rem" }}>
                For high school graduates
              </span>
            </button>
          </div>
        </div>
      )}

      {error && (
        <p
          role="alert"
          style={{
            color: "var(--color-danger)",
            fontSize: "var(--font-size-sm)",
            marginTop: "0.5rem",
            textAlign: "center",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
