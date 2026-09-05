# EnergiPro Intelligence Platform — Enterprise Public Demo

Public showcase deployment of the full EIP v6.x commercial-intelligence platform
(the same codebase family used for branded client trials), adapted for
always-on public access:

- **AI Sales Assistant runs in its built-in rule-based fallback mode.** No
  `ANTHROPIC_API_KEY` is set, so `/api/assistant/ask` never calls the real
  Anthropic API — it uses the deterministic, rule-based responder already
  built into `api/routes/assistant.py` for this exact case, clearly labeled
  `"powered_by": "Rule-based (...)"` in every response.
- **Trial/licensing gate is neutralized for perpetual public use** — see
  `.env.example` (`EIP_TRIAL_DAYS` set very high, no license ID/check URL).
  A real client trial package should NOT be configured this way.
- Single-container deployment: FastAPI backend serves the static
  `frontend/index.html` app directly (see `Dockerfile`).
- Seeded with the platform's own built-in synthetic demo data
  (`POST /api/trust/demo/load-pilot`, admin-only) — a fictional 8-week KSA
  market scenario. No real client/operator data is included anywhere in
  this deployment.

## Local dev

```
cd backend
cp .env.example .env   # fill in a real JWT_SECRET_KEY
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open http://localhost:8000 — the backend serves the frontend directly.
