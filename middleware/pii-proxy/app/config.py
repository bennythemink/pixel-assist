import os

ANYTHINGLLM_BASE_URL = os.getenv("ANYTHINGLLM_BASE_URL", "http://anythingllm1:3001")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
SCRUB_SCORE_THRESHOLD = float(os.getenv("SCRUB_SCORE_THRESHOLD", "0.35"))
