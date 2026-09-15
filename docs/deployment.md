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

| Needed | Status |
|---|---|
| `Dockerfile` and `docker-compose.yml` | done, with a `migrate` service the API and worker wait on. CI builds the image on every push, and the stack has been run end to end: migrations, API and worker as separate containers against PostgreSQL |
| Postgres schema creation beyond `create_all` | done. Alembic owns the schema; `python -m app.migrate` upgrades to head and Compose runs it before the API starts |
| A review screen | done, at `/review` |
| Seeded synthetic documents on boot | done, `EVIDENCEFLOW_SEED_ON_START=true`, which also queues each document for extraction |
| Request size limits and rate limiting | done, `app/api/limits.py` |
| A worker process | done, in-process or as its own service |

Nothing here blocks a public URL.

## Week 4 consequence

Week 4 introduces a durable job table with a claim-and-lease poller. Free tiers
give one process, not two, so the deployed demo runs the poller as a background
task inside the web process while the local Compose setup runs it as its own
service. The job table is the source of truth either way, so recovery behaves
identically; the case study should say which shape the demo is running.

This is also why the plan chose a database-backed job table over Redis and
Celery: the free-tier deployment needs no second service and no broker.

## Deployment steps

1. Create a Neon project, copy the pooled connection string.
2. Create a Render web service from the repository, Docker runtime.
3. Set environment variables:

   ```
   EVIDENCEFLOW_DATABASE_URL=<neon pooled connection string>
   EVIDENCEFLOW_PROVIDER=fake
   EVIDENCEFLOW_RUN_WORKER=true
   EVIDENCEFLOW_SEED_ON_START=true
   EVIDENCEFLOW_AUTO_CREATE_SCHEMA=false
   ```

   Run `python -m app.migrate` as the release command, before the service starts.

   No `OPENAI_API_KEY`.
4. Point the health check at `/health`.
5. Open `/review`. Thirty documents should be seeded and already processed:
   13 validated, 15 in review, 2 refused at the schema boundary.
6. Confirm the public slice: approve a validated document, write it, then press
   write again and show the same record.

## Cost

Zero, with these choices. The only cost risk in the project is the model
provider, and public deployments do not carry the key.


## Building behind a registry-blocked proxy

`FROM` is parameterised:

```dockerfile
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
```

The default is what everyone should use. Where a proxy blocks container
registries, point the build at a base you can obtain another way:

```bash
docker build --build-arg BASE_IMAGE=my-mirror/python:3.12-slim -t evidenceflow .
```

That base must trust whatever CA the proxy presents, or `pip install` inside the
build fails on certificate verification. Install the CA in the base image rather
than in this Dockerfile: the certificate belongs to the network the build runs
on, not to the application.

The stack has been verified this way — image built from the real Dockerfile,
migrations applied by the `migrate` container, API and worker running as separate
containers, 61 end-to-end checks passing against the containerised API, and a
worker container stopped and restarted mid-job with the work completing and no
duplicate record.
