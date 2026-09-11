# Quickstart Guide

> **Diátaxis Type**: Tutorial / How-to | **Status**: Canonical | **Review**: Continuous

This guide walks through cloning, configuring, and verifying the Bio-Quant platform from scratch.

---

## 1. Prerequisites

- **Python 3.11+**
- **Docker Engine 24+** & **Docker Compose v2** (optional for containerized deployment)
- **Git**

---

## 2. Setup Step-by-Step

```bash
# 1. Clone the repository
git clone https://github.com/vgbn2/diabetic.git
cd diabetic

# 2. Configure environment
cp .env.example .env

# 3. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 4. Verify system cleanliness and contract parity
python scripts/check_repo_cleanliness.py
```

---

## 3. Launching the Local Services

```bash
# Start MongoDB & Nightscout
docker compose up -d mongodb nightscout

# Launch the live Bio-Quant monitoring daemon
python -m diabetic.main live
```

Open your browser at `http://localhost:8000` to view the live Canvas HUD dashboard.
