# Deployment guide

Three ways to run the project, from simplest to most production-like.

## 1. Docker Compose (local / any VM)

```bash
cp .env.example .env     # set GROQ_API_KEY, JWT_SECRET, ADMIN_PASSWORD
docker compose up --build
```
API: http://localhost:8000/docs · Web UI: http://localhost:8501. Migrations run automatically.

## 2. Publish images to GitHub Container Registry (CD)

```bash
git tag v1.0.0 && git push origin v1.0.0
```
`.github/workflows/cd.yml` builds `ghcr.io/<owner>/<repo>-api` and `-web`. The first time, make the packages
public (GitHub -> your profile -> Packages -> package settings) if you want others to pull them.

## 3. Render (quick public demo)

1. Push the repo to GitHub, then Render -> New -> Blueprint -> pick the repo (it reads `render.yaml`).
2. Fill the prompted variables: `GROQ_API_KEY`, `ADMIN_PASSWORD`, and, after the API is live, `API_URL` of the web service.
3. Put the web service URL at the top of the README.

Caveats - verify current plans on render.com before relying on any of this:
- The embedding model (MiniLM) needs roughly 0.5-1 GB RAM including PyTorch, so a 512 MB free instance can run out of
  memory. The blueprint therefore uses a paid `starter` instance for the API.
- Free Postgres instances may be time-limited or paused. Fine for a demo, not for real data.
- The FAISS index lives on the container disk: documents uploaded through the UI are lost on redeploy unless you
  attach a persistent disk (paid) mounted at `/app/data`.

## 4. AWS ECS Fargate (production-like)

Prerequisites: an RDS PostgreSQL instance, an ECR repository (or use GHCR), an Application Load Balancer.

1. **Secrets** in AWS Secrets Manager: `pharma/groq-api-key`, `pharma/jwt-secret`, `pharma/db-password`,
   `pharma/admin-password`, `pharma/readonly-db-password`.
2. **Task definition**: edit `deploy/ecs-task-definition.json` (account id, region, image, RDS endpoint) and register it:
   `aws ecs register-task-definition --cli-input-json file://deploy/ecs-task-definition.json`
3. **Service**: Fargate service behind the ALB, target group health check path `/health` (use `/ready` for a deeper check),
   port 8000, security group allowing ALB -> task and task -> RDS.
4. The container runs `alembic upgrade head` on every start, creates the read-only DB role (because
   `READONLY_DB_PASSWORD` is set) and starts the API. The RDS master user is allowed to create roles.
5. **CD**: uncomment `deploy-ecs` in `cd.yml` and use GitHub OIDC (no long-lived AWS keys).

### Known limits you must handle before real production use
| Limit | Why | Fix |
|---|---|---|
| Conversation memory is per process | `MemorySaver` lives in RAM | `langgraph-checkpoint-postgres` |
| FAISS index is on local disk | lost on redeploy, not shared by several tasks | EFS volume, or move to pgvector |
| Rate limiter is per process | each task counts separately | Redis-backed limiter |
| Access tokens only (no refresh) | simplicity | refresh tokens + token revocation list |
| `FORWARDED_ALLOW_IPS=*` | needed behind an ALB so client IPs are correct | restrict to the ALB subnet CIDR |

Until the first three are fixed, run a **single** task.
