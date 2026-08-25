# ReTryPay Deployment Guide

This repository supports two deployment scopes:

1. **Static dashboard only** (GitHub Pages)
2. **Full ReTryPay app** (FastAPI backend + React frontend on separate hosts)

---

## 1) Static Dashboard Deployment (GitHub Pages)

Workflow: `/home/runner/work/retrypay/retrypay/.github/workflows/static.yml`

- Trigger: push to `main` or manual dispatch.
- Build source: `web/`
- Artifact deployed to Pages: `web/dist`

The workflow builds with:

```bash
npm run build -- --base "/retrypay/"
```

so assets resolve correctly for the repository Pages path.

---

## 2) Full-Stack Deployment (Recommended)

Deploy backend and frontend separately.

### Backend (FastAPI)

Deploy `retrypay.api.app:app` on a Python host (Render/Railway/Fly.io) with:

- `RETRYPAY_ENV=demo` (or `development`)
- `DATABASE_URL=<managed db or persistent sqlite path>`
- `RETRYPAY_EXPECTED_DATABASE_TARGET=<same target as DATABASE_URL>`
- Razorpay test-mode variables from `/home/runner/work/retrypay/retrypay/.env.example`
- `RAZORPAY_TEST_MODE_ONLY=true`

Use HTTPS and never configure live-mode Razorpay keys.

### Frontend (React/Vite)

Deploy `web/` to Vercel/Netlify (or any static host) and set:

- `VITE_API_BASE_URL=https://<your-backend-domain>/api/v1`

The frontend falls back to `/api/v1` when `VITE_API_BASE_URL` is unset, which is suitable for local proxy development.

---

## 3) Pre-Deploy Validation Checklist

Run these before deployment:

```bash
# Backend
ruff check .
ruff format --check .
mypy retrypay tests
pytest --cov=retrypay --cov-report=json:coverage.json tests/

# Frontend
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
```

Also verify:

- webhook signature secret is configured
- only `rzp_test_*` key IDs are used
- HTTPS endpoints are used for backend and frontend
