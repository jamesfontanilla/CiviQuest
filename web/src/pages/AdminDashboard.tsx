import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import { useToast } from "../context/ToastContext";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface Analytics {
  total_users: number;
  verified_users: number;
  banned_users: number;
  total_lessons_completed: number;
  total_quiz_attempts: number;
  total_mock_attempts: number;
  mock_pass_rate: number;
  weakest_subtopics: { subtopic_id: number; title: string; avg_score: number }[];
}

interface UserEntry {
  id: number;
  email: string;
  display_name: string;
  role: string;
  account_state: string;
  is_banned: boolean;
}

interface UsersResponse {
  items: UserEntry[];
  total: number;
}

export function AdminDashboard() {
  const toast = useToast();
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      apiClient.get<Analytics>("/v1/admin/analytics"),
      apiClient.get<UsersResponse>("/v1/admin/users?limit=50"),
    ])
      .then(([analyticsRes, usersRes]) => {
        setAnalytics(analyticsRes);
        setUsers(usersRes.items);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  const handleDeleteUser = async (userId: number, email: string) => {
    if (!confirm(`Are you sure you want to delete user "${email}"? This cannot be undone.`)) {
      return;
    }
    try {
      await apiClient.delete(`/v1/admin/users/${userId}`);
      toast.success(`User "${email}" deleted.`);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Delete failed";
      toast.error(msg);
    }
  };

  const handleBanToggle = async (userId: number, currentlyBanned: boolean) => {
    try {
      await apiClient.patch(`/v1/admin/users/${userId}`, { is_banned: !currentlyBanned });
      toast.success(currentlyBanned ? "User unbanned." : "User banned.");
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_banned: !currentlyBanned } : u))
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Action failed";
      toast.error(msg);
    }
  };

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 960 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            ⚙️ Admin Dashboard
          </h1>
          <GlassCard>
            <GlassSkeleton height="1.25rem" width="40%" />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
              {[1, 2, 3, 4, 5, 6, 7].map((i) => (
                <div key={i}>
                  <GlassSkeleton height="1.5rem" width="50%" />
                  <div style={{ marginTop: "0.25rem" }}>
                    <GlassSkeleton height="0.75rem" width="70%" />
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
          <div style={{ marginTop: "1.5rem" }}>
            <GlassCard>
              <GlassSkeleton height="1.25rem" width="30%" />
              <div style={{ marginTop: "1rem" }}>
                <GlassSkeleton height="15rem" />
              </div>
            </GlassCard>
          </div>
        </div>
      </PageTransition>
    );
  }

  if (error) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 960 }}>
          <p style={{ color: "var(--color-danger)" }}>{error}</p>
        </div>
      </PageTransition>
    );
  }

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 960 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          ⚙️ Admin Dashboard
        </h1>

        {analytics && (
          <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginTop: 0, marginBottom: "1rem" }}>
              Platform Analytics
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "1rem" }}>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.total_users}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Total Users</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.verified_users}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Verified</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.banned_users}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Banned</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.total_lessons_completed}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Lessons Done</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.total_quiz_attempts}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Quiz Attempts</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{analytics.total_mock_attempts}</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Mock Attempts</p>
              </div>
              <div>
                <p style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{(analytics.mock_pass_rate * 100).toFixed(1)}%</p>
                <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", margin: 0 }}>Mock Pass Rate</p>
              </div>
            </div>
          </GlassCard>
        )}

        <GlassCard as="section" blur="lg">
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginTop: 0, marginBottom: "1rem" }}>
            User Management
          </h2>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--font-size-sm)" }}
              aria-label="User list"
            >
              <thead>
                <tr style={{ borderBottom: "2px solid var(--glass-border-medium)" }}>
                  <th style={{ textAlign: "left", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontWeight: 500 }}>Email</th>
                  <th style={{ textAlign: "left", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontWeight: 500 }}>Name</th>
                  <th style={{ textAlign: "left", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontWeight: 500 }}>Role</th>
                  <th style={{ textAlign: "center", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontWeight: 500 }}>Banned</th>
                  <th style={{ textAlign: "center", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontWeight: 500 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: "1px solid var(--glass-border-light)" }}>
                    <td style={{ padding: "0.75rem 0.5rem", color: "var(--color-text)" }}>{u.email}</td>
                    <td style={{ padding: "0.75rem 0.5rem", color: "var(--color-text)" }}>{u.display_name}</td>
                    <td style={{ padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)" }}>{u.role}</td>
                    <td style={{ textAlign: "center", padding: "0.75rem 0.5rem", color: "var(--color-text)" }}>{u.is_banned ? "🚫" : "—"}</td>
                    <td style={{ textAlign: "center", padding: "0.75rem 0.5rem" }}>
                      <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center" }}>
                        <GlassButton
                          variant="ghost"
                          size="sm"
                          onClick={() => handleBanToggle(u.id, u.is_banned)}
                          aria-label={u.is_banned ? `Unban ${u.email}` : `Ban ${u.email}`}
                        >
                          {u.is_banned ? "Unban" : "Ban"}
                        </GlassButton>
                        <GlassButton
                          variant="danger"
                          size="sm"
                          onClick={() => handleDeleteUser(u.id, u.email)}
                          aria-label={`Delete ${u.email}`}
                        >
                          Delete
                        </GlassButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {users.length === 0 && (
            <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", textAlign: "center", marginTop: "1rem" }}>
              No users found.
            </p>
          )}
        </GlassCard>

        <Link
          to="/modules"
          style={{
            display: "inline-block",
            marginTop: "1.5rem",
            color: "var(--color-accent)",
            fontSize: "var(--font-size-sm)",
            textDecoration: "none",
          }}
          aria-label="Back to modules"
        >
          ← Back to Modules
        </Link>
      </div>
    </PageTransition>
  );
}
