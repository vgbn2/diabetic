"""
diabetic.auth — authentication & authorization for Bio-Quant web surfaces.

- telegram_webapp: validate Telegram Mini App `initData` (HMAC) server-side.
- authorization:   shared singleton patient/caregiver allow check.
- dependencies:    FastAPI dependency guarding the TWA bridge endpoints.
"""
