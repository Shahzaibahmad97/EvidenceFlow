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

Free tiers move. These were checked in September 2026 and should be re-checked
against each provider's current pricing page before signing up.

| Platform | Free tier shape | Fit |
|---|---|---|
| **Render** web service | No card, Docker runtime, 512 MB, sleeps after ~15 minutes idle, cold start under a minute, ephemeral disk | Best fit, and what `render.yaml` describes |
| **Koyeb** | One free web service, 512 MB, scales to zero after an hour idle; may ask for card verification | Workable alternative |
| **Neon** PostgreSQL | Free project, no card, suspends when idle | Add only if the demo's state must survive a restart |
| **Hugging Face Spaces** | **Not free for this.** Static Spaces are free; a Space that runs compute — Docker or Gradio — needs PRO at $9/month | Avoid unless already paying |
| **Fly.io**, **Railway** | Card required, or trial credit only | Not free in practice |
| **Vercel / Cloudflare Workers** | Serverless | Poor fit: long-lived database connections and a background worker |

**Recommendation: a Render free web service, no database service.** The container
keeps its state in SQLite on the instance disk, which does not survive a restart
or deploy on the free plan, so the demo reseeds its thirty synthetic documents
whenever it comes back. Everything is synthetic, so nothing is lost that matters.

If the demo's state should survive restarts, create a free Neon project and set
its connection string as `EVIDENCEFLOW_DATABASE_URL` on the service. The same
image takes it with no change and migrations run on the way up.

Render free instances sleep when idle. The first visitor after a quiet period
waits under a minute, which is worth saying in the case study rather than hiding.

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

`render.yaml` in the repository root is a Render Blueprint: it declares the web
service, its free PostgreSQL database, the health check, and every environment
variable. Pointing Render at the repository is enough; the steps below are what
that blueprint does, for anyone deploying somewhere else.

The container start command is `scripts/start.sh`, which applies migrations and
then serves. A single-process host has no separate release step, so the migration
has to happen on the way up. Compose keeps them apart, as its own service.

1. Create a Neon project, copy the pooled connection string. Render's own free
   database works too and the blueprint declares one, but it expires; Neon's does
   not.
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


## Hugging Face Spaces — needs a paid plan

Kept because the work is done and it is a few minutes away if PRO is ever worth
it, but **a Space that runs compute is not free**: Docker and Gradio Spaces both
require PRO for a personal account. Only Static Spaces run on the free tier, and
a static page cannot run this.

The image satisfies what a Docker Space needs — it runs as uid 1000, writes only
under `/home/user`, and declares its port.

```bash
HF_TOKEN=hf_xxx ./scripts/publish_space.sh <username>/evidenceflow
```

The script builds a Space-shaped tree from `HEAD` — the repository as it is, with
`deploy/huggingface/README.md` in place of the project README, because a Space
reads its configuration from that file's front matter — and pushes it. Create the
Space first at <https://huggingface.co/new-space> with the Docker SDK, or let the
push create it if your token allows.

Settings worth knowing:

| Setting | Value | Why |
|---|---|---|
| `app_port` | 8000 | declared in the Space README front matter; the container listens there |
| user | uid 1000 | Spaces run the container as that user, and the image creates it |
| database | `sqlite:////home/user/data/evidenceflow.db` | the image default, under the only writable path |
| provider | `fake` | no key is present, so the Space cannot spend one |

**Storage on a free Space is ephemeral.** The demo seeds thirty documents on first
boot and keeps whatever reviewers do to them until the Space restarts, sleeps or
rebuilds, at which point it seeds again from scratch. Everything is synthetic, so
nothing is lost that matters. For state that survives a restart, set
`EVIDENCEFLOW_DATABASE_URL` as a Space secret to a hosted PostgreSQL connection
string — the same image takes it with no change, and migrations run on the way up.

Raise `EVIDENCEFLOW_RATE_LIMIT_PER_MINUTE` before running `scripts/e2e_live.py`
against a Space: the suite makes more than sixty writes a minute, and the default
is sized for a public URL rather than a test run.
