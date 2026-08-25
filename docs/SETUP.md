# ReTryPay — Setup & Execution Guide

This document contains step-by-step instructions for running, testing, and verifying the ReTryPay backend and frontend operator dashboard.

---

## 1. Environment & Prerequisites

- **Python**: 3.11+ (Python 3.14 recommended)
- **Node.js**: 18+ and `npm`
- **PowerShell** (Windows) or **Bash** (macOS/Linux)

---

## 2. Backend Setup & Run

### 2.1 Virtual Environment Installation
```powershell
# Create virtual environment
python -m venv .venv

# Activate on Windows PowerShell:
.venv\Scripts\Activate.ps1

# Or on Linux / macOS:
source .venv/bin/activate

# Install package in development mode with dev dependencies
pip install -e ".[dev]"
```

### 2.2 Environment Configuration
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

### 2.3 Running the API Server (Test Environment)
```powershell
$env:RETRYPAY_ENV = "test"
$env:DATABASE_URL = "sqlite+aiosqlite:///./retrypay_test.db"
$env:RETRYPAY_EXPECTED_DATABASE_TARGET = "retrypay_test.db"

python -m uvicorn retrypay.api.app:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation will be accessible at: `http://127.0.0.1:8000/docs`.

---

## 3. Frontend Dashboard Setup & Run

### 3.1 Installation
```powershell
cd web
npm install
```

### 3.2 Running the Vite Dev Server
```powershell
npm run dev
```
The operator console opens at `http://localhost:5173`.

---

## 4. Verification & Testing

### 4.1 Backend Verification Suite
```powershell
# Run full pytest test suite (294 passed)
python -m pytest

# Run strict type checks across backend, tests, and scripts
python -m mypy retrypay tests scripts

# Run ruff code quality checks
python -m ruff check .
python -m ruff format --check .
```

### 4.2 Frontend Verification Suite
```powershell
# Linting
npm --prefix web run lint

# Component & Integration Tests (16 passed)
npm --prefix web run test -- --run

# Production Build
npm --prefix web run build
```

---

## 5. Local Webhook Simulator

To trigger synthetic failure scenarios locally without calling external APIs:
1. Ensure `$env:RETRYPAY_ENV = "test"`.
2. Open `http://localhost:5173` and navigate to **Webhook Simulator**.
3. Select any scenario (e.g. *Eligible Outreach Flow*, *Quiet Hours Deferral*, *Suspected Fraud Manual Review*).
4. Click **Trigger Simulation Scenario** to dispatch a locally signed HMAC webhook fixture.
