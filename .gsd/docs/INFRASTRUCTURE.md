# Bio-Quant Infrastructure & Stack

## 💻 Tech Stack
- **Language**: Python 3.10+ (Native or venv)
- **Deployment**: Local execution via `start.ps1` / `start.sh`
- **Data Validation**: Pydantic v2
- **DSP**: FilterPy (Kalman Filters)
- **ML**: Scikit-learn / XGBoost
- **API**: FastAPI (for local dashboard/monitoring)
- **Database**: MongoDB (Cloud persistence for alert logs)
- **Messaging**: Telegram Bot API

## 📁 Directory Structure
```text
hyperglycemia-faint-predictor/
├── .gsd/               # GSD Planning & Documentation
├── data/               # Historical & Sim Data
├── src/
│   ├── ingestion/      # Data Bridges
│   ├── smoothing/      # DSP / Signal Cleaning
│   ├── features/       # Metabolic Math
│   ├── forecasting/    # ML Models
│   ├── alert_engine/   # Guard Logic
│   ├── comms/          # Telegram Bot
│   ├── registry.py     # Identity-based Pydantic Models
│   ├── config.py       # Environment Config
│   └── coordinator.py  # System Orchestrator
├── tests/              # Validation Suite
└── requirements.txt
```

## 🔐 Environment Secrets
- `NIGHTSCOUT_URL`: Remote CGM URL
- `NIGHTSCOUT_API_SECRET`: Auth for Nightscout
- `TELEGRAM_TOKEN`: Bot authentication
- `USER_TELEGRAM_ID`: Primary recipient
- `CAREGIVER_TELEGRAM_ID`: Emergency recipient
