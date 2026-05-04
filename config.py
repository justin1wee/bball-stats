import os

# --- API ---
API_KEY_PATH: str = os.getenv("NBA_API_KEY_PATH", "secrets/api_key.txt")
MAX_PLAYERS: int = int(os.getenv("NBA_MAX_PLAYERS", "5000"))
# Seasons to collect averages for (newest first so recent data loads first)
SEASONS: list[int] = [
    int(s) for s in os.getenv("NBA_SEASONS", "2023,2022,2021,2020,2019").split(",")
]

# --- PostgreSQL ---
POSTGRES_CONN: str = os.getenv(
    "POSTGRES_CONN",
    "postgresql://postgres:password@localhost:5432/nba_stats",
)

# --- AWS S3 ---
S3_BUCKET: str = os.getenv("S3_BUCKET", "nba-stats-pipeline")
S3_PREFIX: str = os.getenv("S3_PREFIX", "nba")
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
