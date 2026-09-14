# Deployment plan

The vertical slice runs end to end today: upload a document, extract a typed
draft with verified evidence, validate it deterministically, approve the current
version, and write it once to the mock CRM. That is enough to put a live link in
front of a buyer.

Platform free tiers change often. Everything below was accurate when written and
should be re-checked against each provider's current pricing page before signing
up.

## What a public deployment must not do

- **Never run the live model provider in a public demo.** The endpoints are
  unauthenticated, so anyone with the link could spend the API key. Public
  deployments run `EVIDENCEFLOW_PROVIDER=fake`, which serves the committed
  fixtures. The live path stays a local, opt-in command.
- **Never carry a real API key in the deployed environment.** If the key is not
  set, it cannot leak.
- Cap upload size and keep the mock CRM in-process. Nothing this service writes
  leaves it.

## Candidate platforms

| Platform | Free tier shape | Fit |
|---|---|---|
| **Render** web service | 512 MB, sleeps after ~15 minutes idle, cold start under a minute, no persistent disk | Best fit. Real Docker or native Python, a stable URL, pairs with hosted Postgres |
| **Neon** Postgres | Free project, suspends when idle, wakes on connect | Best fit for state. Week 4 needs `SELECT ... FOR UPDATE SKIP LOCKED` |
| **Hugging Face Spaces** (Docker) | Free CPU, no card required, public by default, ephemeral storage | Best fallback. Zero friction, good for a portfolio link, but storage resets |
| **Koyeb** | One free instance | Workable alternative to Render |
| **Supabase** Postgres | Free project with idle pausing | Alternative to Neon |
| **Fly.io** | Card required, small allowance | Avoid for a free demo |
| **Railway** | Trial credit, then paid | Not free in practice |
| **Vercel / Cloudflare Workers** | Serverless | Poor fit: long-lived database connections and, from week 4, a background worker |

**Recommendation: Render free web service + Neon free Postgres.** Hugging Face
Spaces is the fallback if a card-free signup matters more than durable state.

Both sleep when idle. A cold start costs the first visitor under a minute, which
is acceptable for a portfolio link and worth saying out loud in the case study
rather than hiding.

## What is still missing

| Needed | Status | Week |
|---|---|---|
| `Dockerfile` and `docker-compose.yml` | not written | 6 |
| Postgres schema creation beyond `create_all` | not written; fine for a demo, Alembic before anything real | 6 |
| A review screen | not written; today the demo is the OpenAPI page at `/docs` | 6 |
| Seeded synthetic documents on boot | not written | 6 |
| Request size limits and basic rate limiting | not written | before any public URL |
| A worker process | week 4 work | 4 |

None of these block the plan. They are week 6 items, and the plan already puts
deployment there.

## Week 4 consequence

Week 4 introduces a durable job table with a claim-and-lease poller. Free tiers
give one process, not two, so the deployed demo runs the poller as a background
task inside the web process while the local Compose setup runs it as its own
service. The job table is the source of truth either way, so recovery behaves
identically; the case study should say which shape the demo is running.

This is also why the plan chose a database-backed job table over Redis and
Celery: the free-tier deployment needs no second service and no broker.

## Deployment steps, when week 6 arrives

1. Create a Neon project, copy the pooled connection string.
2. Create a Render web service from the repository, Docker runtime.
3. Set environment variables:

   ```
   EVIDENCEFLOW_DATABASE_URL=<neon pooled connection string>
   EVIDENCEFLOW_PROVIDER=fake
   ```

   No `OPENAI_API_KEY`.
4. Point the health check at `/health`.
5. Seed the synthetic documents on first boot.
6. Confirm the public slice: upload, extract, approve, write, then replay the
   write and show one record.

## Cost

Zero, with these choices. The only cost risk in the project is the model
provider, and public deployments do not carry the key.
