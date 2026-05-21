# Deployment Guide — Zero-Cost, Near-Zero-Downtime

## Stack

| Layer | Service | Free tier |
|-------|---------|-----------|
| Database | [Supabase](https://supabase.com) | 500 MB Postgres, session pooler (IPv4) |
| Backend API | [Render](https://render.com) | 750 hrs/month, zero-downtime deploys |
| Frontend | [Vercel](https://vercel.com) | Unlimited static deploys, global CDN |
| Email | [Resend](https://resend.com) | 3,000 emails/month, 100/day |
| Keep-alive | [cron-job.org](https://cron-job.org) + [UptimeRobot](https://uptimerobot.com) | Free pings to prevent sleep |

**Capacity:** Handles 1,000+ users comfortably. Render does zero-downtime
deploys (new instance starts before old one stops) even on the free tier.
The cron keep-alive prevents the 15-minute inactivity sleep. Supabase
Postgres persists data across all deploys.

---

## 1. Supabase (Database)

1. Go to [supabase.com](https://supabase.com) → sign up / log in.
2. **New Project** → pick a name, set a database password, choose a region
   close to your users (e.g. Singapore for PH users).
3. Wait for provisioning (~1 min).
4. Go to **Project Settings → Database → Connection string**.
5. Select **Session pooler** (port 5432). Copy the full URI:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   Use Session pooler because:
   - It works over IPv4 (direct connection is IPv6-only on newer projects).
   - It matches SQLAlchemy's session-based connection model.
   - Do NOT use Transaction pooler — it breaks session-level state.
6. Save this connection string — you'll need it in Step 3.

> **Note:** Free-tier projects may pause after ~1 week of zero connections.
> The keep-alive pings in Step 5 will also keep Supabase awake since every
> ping hits the backend which holds a DB connection.

---

## 2. Resend (Email)

1. Sign up at [resend.com](https://resend.com).
2. Go to **Domains** → Add your domain and follow the DNS verification steps.
   - If you don't have a domain yet, use the `resend.dev` sandbox for testing
     (emails only deliver to your own verified address on the free tier).
3. Go to **API Keys** → Create API key → copy it.
4. Note your verified sender address (e.g. `noreply@yourdomain.com`).

---

## 3. Render (Backend)

1. Sign up at [render.com](https://render.com).
2. **New** → **Web Service** → connect your GitHub repo (`civiquest`).
3. Configure the service:
   - **Branch**: `main`
   - **Root Directory**: (leave blank — the repo root)
   - **Runtime**: Python
   - **Build command**: `pip install -e .`
   - **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance type**: Free
4. Add **Environment Variables**:

   | Key | Value |
   |-----|-------|
   | `DATABASE_URL` | Your Supabase Session pooler URI from Step 1 |
   | `JWT_SECRET` | A random 32-byte hex string (see below) |
   | `RESEND_API_KEY` | Your Resend API key from Step 2 |
   | `EMAIL_FROM_ADDR` | `CiviQuest <noreply@yourdomain.com>` |
   | `PYTHON_VERSION` | `3.11.9` |

   Generate a JWT secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

5. Click **Deploy**. The first boot will:
   - Create all tables in Supabase Postgres via `Base.metadata.create_all`
   - Seed the database if the admin user doesn't exist yet
6. Note your Render URL (e.g. `https://civiquest-api.onrender.com`).
7. Verify: `GET https://your-url/health` → `{"status": "ok"}`

---

## 4. Vercel (Frontend)

1. Sign up at [vercel.com](https://vercel.com).
2. **New Project** → Import the `civiquest` repo from GitHub.
3. Set **Root Directory** to `web`.
4. Vercel auto-detects Vite. Confirm:
   - **Build command**: `npm run build`
   - **Output directory**: `dist`
5. Add **Environment Variable**:

   | Key | Value |
   |-----|-------|
   | `VITE_API_URL` | Your Render URL (e.g. `https://civiquest-api.onrender.com`) |

6. Deploy.

The frontend API client reads `import.meta.env.VITE_API_URL` and falls back
to `""` (same-origin) when unset. Setting it to your Render URL is all
that's needed.

---

## 5. Keep-Alive Pings (Prevent Sleep)

Render free tier sleeps after 15 minutes of inactivity. Prevent this with
two independent cron services for redundancy:

### cron-job.org (primary)
1. Sign up at [cron-job.org](https://console.cron-job.org).
2. Create a new cron job:
   - **URL**: `https://your-render-url/health`
   - **Schedule**: Every 14 minutes (`*/14 * * * *`)
   - **Method**: GET
3. Save and enable.

### UptimeRobot (backup)
1. Sign up at [uptimerobot.com](https://uptimerobot.com).
2. Add a new monitor:
   - **Type**: HTTP(s)
   - **URL**: `https://your-render-url/health`
   - **Interval**: 5 minutes (free tier minimum)
3. Save.

With both running, your backend stays awake 24/7. If one service has an
outage, the other covers it.

---

## 6. Tighten CORS (after deploy)

Once you know your Vercel URL, update `app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-app.vercel.app"],  # replace *
    ...
)
```

Push the change — Render auto-redeploys from `main` with zero downtime.

---

## 7. Verify the Full Loop

1. Open your Vercel URL in a browser.
2. Sign up → confirm OTP email arrives (Resend).
3. Complete a quiz → check leaderboard has your score.
4. Push a dummy commit to trigger a Render redeploy.
5. After deploy finishes, refresh leaderboard → score persists.
6. Wait 20 minutes → hit the site again → should load instantly (no cold start).

---

## Ongoing Limits to Watch

| Resource | Free limit | At 1,000 users |
|----------|-----------|----------------|
| Supabase DB size | 500 MB | ~50–100 MB typical |
| Supabase bandwidth | 5 GB/month | Well within range |
| Resend emails | 3,000/month, 100/day | ~3 OTPs/user/month average |
| Render instance hours | 750 hrs/month | 24/7 = 720–744 hrs (fits) |
| Render RAM | 512 MB | FastAPI + SQLAlchemy ≈ 150–200 MB |
| Vercel bandwidth | 100 GB/month | Static assets, negligible |

**First bottleneck:** Resend's 100/day email cap if many users sign up on
the same day. Upgrade to Resend's $20/month plan (50k emails/month) if
that becomes an issue.

**Second bottleneck:** In a 31-day month, 24/7 uptime = 744 hrs, which is
under the 750 hr limit. You have ~6 hrs of buffer. If Render ever reduces
the free allowance, the service will sleep during the overflow hours at
month-end.
