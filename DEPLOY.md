# Deployment Guide — Zero-Cost, Zero-Downtime

## Stack

| Layer | Service | Free tier |
|-------|---------|-----------|
| Backend API | [Koyeb](https://koyeb.com) | 1 always-on service, 512 MB RAM, 0.1 vCPU |
| Database | [Supabase](https://supabase.com) | 500 MB Postgres, unlimited connections via pooler |
| Frontend | [Vercel](https://vercel.com) | Unlimited static deploys, global CDN |
| Email | [Resend](https://resend.com) | 3,000 emails/month, 100/day |

**Capacity:** Handles 1,000+ users comfortably. Koyeb does rolling deploys
(new instance starts before old one stops) so there is no downtime during
redeploys. Supabase Postgres is always-on once you disable auto-pause.

---

## 1. Supabase (Database)

1. Go to [supabase.com](https://supabase.com) → New project.
2. Choose a region close to your users.
3. After the project is ready, go to **Project Settings → Database**.
4. Under **Connection pooling**, copy the **Session mode** URL (port 5432).
   It looks like:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
5. **Disable auto-pause**: Project Settings → General → "Pause project when
   inactive" → toggle OFF. (This keeps the DB always-on.)
6. Save the connection string — you'll need it in step 3.

---

## 2. Resend (Email)

1. Sign up at [resend.com](https://resend.com).
2. Go to **Domains** → Add your domain and follow the DNS verification steps.
   - If you don't have a domain yet, use the `resend.dev` sandbox for testing
     (emails only deliver to your own verified address on the free tier).
3. Go to **API Keys** → Create API key → copy it.
4. Note your verified sender address (e.g. `noreply@yourdomain.com`).

---

## 3. Koyeb (Backend)

1. Sign up at [koyeb.com](https://koyeb.com) (requires a credit card for
   fraud prevention, but the free instance is never charged).
2. **New App** → **GitHub** → select this repository.
3. Configure the service:
   - **Branch**: `main`
   - **Build command**: `pip install -e .`
   - **Run command**: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
   - **Port**: `8000`
   - **Region**: Frankfurt or Washington D.C. (free tier regions)
   - **Instance**: Free (512 MB)
4. Add **Environment Variables**:

   | Key | Value |
   |-----|-------|
   | `DATABASE_URL` | Your Supabase Session-mode pooler URL |
   | `JWT_SECRET` | A random 32-byte hex string (see below) |
   | `RESEND_API_KEY` | Your Resend API key |
   | `EMAIL_FROM_ADDR` | `CiviQuest <noreply@yourdomain.com>` |

   Generate a JWT secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

5. Deploy. Koyeb will build and start the service. The first deploy runs
   `Base.metadata.create_all` and seeds the database automatically.

6. Note your Koyeb app URL (e.g. `https://civiquest-api-<hash>.koyeb.app`).

---

## 4. Vercel (Frontend)

1. Sign up at [vercel.com](https://vercel.com).
2. **New Project** → Import this repository.
3. Set the **Root Directory** to `web`.
4. Vercel auto-detects Vite. Confirm:
   - **Build command**: `npm run build`
   - **Output directory**: `dist`
5. Add **Environment Variable**:

   | Key | Value |
   |-----|-------|
   | `VITE_API_URL` | Your Koyeb app URL (e.g. `https://civiquest-api-<hash>.koyeb.app`) |

6. Deploy.

The frontend API client already reads `import.meta.env.VITE_API_URL` and
falls back to `""` (same-origin) when unset. Setting it to your Koyeb URL
is all that's needed.

---

## 5. Tighten CORS (after deploy)

Once you know your Vercel URL, update `app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-app.vercel.app"],  # replace *
    ...
)
```

---

## Ongoing limits to watch

| Resource | Free limit | At 1,000 users |
|----------|-----------|----------------|
| Supabase DB size | 500 MB | ~50–100 MB typical |
| Supabase bandwidth | 5 GB/month | Well within range |
| Resend emails | 3,000/month, 100/day | ~3 OTPs/user/month average |
| Koyeb RAM | 512 MB | FastAPI + SQLAlchemy pool ≈ 150–200 MB |
| Vercel bandwidth | 100 GB/month | Static assets, very low |

The only realistic bottleneck at 1,000 users is the Resend 100/day cap if
many users trigger OTPs on the same day. Upgrade to Resend's $20/month plan
(50,000 emails/month) if that becomes an issue.
