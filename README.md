# DMS

Multi-tenant Document Management System for SMEs. See `docs/product` (PRD), `docs/implementation` (baseline, traceability, status) and `docs/adr`.

## Layout
- `services/api`: FastAPI backend (Python 3.12, `uv`)
- `packages/domain`: shared TypeScript domain constants
- Planned: `apps/web`, `apps/mobile`, `services/workers`

## Develop
```bash
cd services/api && uv sync --group dev && uv run pytest -q
npm install && npm run build && npm test
```

Secrets: copy `.env.example` to `.env` (git-ignored) and fill locally. Never commit credentials.
