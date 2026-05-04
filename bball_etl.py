import ast
import logging
import time
from io import BytesIO

import boto3
import pandas as pd
import psycopg2
import requests
from psycopg2.extras import execute_values

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def get_api_key(filepath: str = config.API_KEY_PATH) -> str:
    with open(filepath) as f:
        return f.read().strip()


def fetch_players(api_key: str, max_rows: int = config.MAX_PLAYERS) -> pd.DataFrame:
    """Paginate /v1/players until max_rows records are collected."""
    url = "https://api.balldontlie.io/v1/players"
    headers = {"Authorization": api_key}
    params: dict = {"per_page": 100}
    rows: list = []

    while len(rows) < max_rows:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        rows.extend(body["data"])
        log.info("Players fetched: %d", len(rows))

        if "next_cursor" not in body.get("meta", {}):
            break
        params["cursor"] = body["meta"]["next_cursor"]
        time.sleep(0.25)   # stay within rate limit

    return pd.DataFrame(rows[:max_rows])


def fetch_season_averages(
    api_key: str,
    player_ids: list[int],
    seasons: list[int] | None = None,
) -> pd.DataFrame:
    """Batch-fetch season averages for given player IDs across multiple seasons."""
    if seasons is None:
        seasons = config.SEASONS
    url = "https://api.balldontlie.io/v1/season_averages"
    headers = {"Authorization": api_key}
    all_stats: list = []

    for season in seasons:
        for i in range(0, len(player_ids), 100):
            batch = player_ids[i : i + 100]
            params = [("season", season)] + [("player_ids[]", pid) for pid in batch]
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            records = resp.json().get("data", [])
            for r in records:
                r["season"] = season
            all_stats.extend(records)
            log.info("Season %d — stats collected: %d total", season, len(all_stats))
            time.sleep(0.25)

    return pd.DataFrame(all_stats)


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _parse_team(val):
    """Convert stringified dict or real dict to a dict."""
    if isinstance(val, dict):
        return val
    try:
        return ast.literal_eval(val)
    except Exception:
        return {}


def flatten_team_column(df: pd.DataFrame) -> pd.DataFrame:
    """Expand the nested team column into prefixed columns."""
    team_dicts = df["team"].apply(_parse_team)
    team_df = pd.json_normalize(team_dicts).add_prefix("team_")
    return pd.concat([df.drop(columns=["team"]), team_df], axis=1)


def _minutes_to_float(val) -> float | None:
    """Convert 'MM:SS' or numeric string to float minutes."""
    if pd.isna(val):
        return None
    s = str(val)
    if ":" in s:
        parts = s.split(":")
        return round(int(parts[0]) + int(parts[1]) / 60, 2)
    try:
        return float(s)
    except ValueError:
        return None


def clean_players(df: pd.DataFrame) -> pd.DataFrame:
    required = ["position", "draft_year", "draft_round", "draft_number"]
    df = df.dropna(subset=required).reset_index(drop=True)

    df[["draft_year", "draft_round", "draft_number"]] = df[
        ["draft_year", "draft_round", "draft_number"]
    ].astype(int)

    # Primary position is the first token before any hyphen
    df["primary_position"] = df["position"].str.split("-").str[0]

    if "team" in df.columns:
        df = flatten_team_column(df)

    return df


def clean_stats(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.dropna(subset=["player_id", "season"]).reset_index(drop=True)
    df["min"] = df["min"].apply(_minutes_to_float)

    numeric = [
        "pts", "reb", "ast", "stl", "blk", "turnover",
        "fg_pct", "fg3_pct", "ft_pct", "games_played",
        "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
        "oreb", "dreb", "pf",
    ]
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["player_id"] = df["player_id"].astype(int)
    df["season"] = df["season"].astype(int)
    return df


def build_teams_df(players_df: pd.DataFrame) -> pd.DataFrame:
    team_cols = [c for c in players_df.columns if c.startswith("team_")]
    teams = players_df[team_cols].drop_duplicates(subset=["team_id"])
    teams.columns = [c.replace("team_", "") for c in teams.columns]
    return teams.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Load — PostgreSQL
# ---------------------------------------------------------------------------

def _get_conn(conn_str: str = config.POSTGRES_CONN):
    return psycopg2.connect(conn_str)


def upsert_dataframe(
    df: pd.DataFrame,
    table: str,
    pk_cols: list[str],
    conn_str: str = config.POSTGRES_CONN,
) -> None:
    """Bulk upsert a DataFrame into a PostgreSQL table via ON CONFLICT DO UPDATE."""
    if df.empty:
        log.warning("upsert_dataframe: empty frame for %s, skipping", table)
        return

    cols = list(df.columns)
    update_cols = [c for c in cols if c not in pk_cols]
    conflict_target = ", ".join(pk_cols)
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    sql = f"""
        INSERT INTO {table} ({', '.join(cols)})
        VALUES %s
        ON CONFLICT ({conflict_target}) DO UPDATE SET {set_clause}
    """
    values = [tuple(row) for row in df.itertuples(index=False, name=None)]

    conn = _get_conn(conn_str)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=500)
        log.info("Upserted %d rows into %s", len(df), table)
    finally:
        conn.close()


def load_all_to_postgres(
    players_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> None:
    player_cols = [
        "id", "first_name", "last_name", "position", "primary_position",
        "height", "weight", "jersey_number", "college", "country",
        "draft_year", "draft_round", "draft_number", "team_id",
    ]
    team_cols = ["id", "conference", "division", "city", "name", "full_name", "abbreviation"]
    stat_cols = [
        "player_id", "season", "games_played", "min",
        "pts", "reb", "ast", "stl", "blk", "turnover",
        "fg_pct", "fg3_pct", "ft_pct",
        "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "pf",
    ]

    upsert_dataframe(
        teams_df[[c for c in team_cols if c in teams_df.columns]],
        "teams", pk_cols=["id"],
    )
    upsert_dataframe(
        players_df[[c for c in player_cols if c in players_df.columns]],
        "players", pk_cols=["id"],
    )
    if not stats_df.empty:
        upsert_dataframe(
            stats_df[[c for c in stat_cols if c in stats_df.columns]],
            "season_averages", pk_cols=["player_id", "season"],
        )


# ---------------------------------------------------------------------------
# Load — S3
# ---------------------------------------------------------------------------

def upload_parquet_to_s3(
    df: pd.DataFrame,
    key: str,
    bucket: str = config.S3_BUCKET,
) -> str:
    """Upload a DataFrame as Parquet to S3 and return the s3:// URI."""
    s3 = boto3.client("s3", region_name=config.AWS_REGION)
    buf = BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    buf.seek(0)
    s3.upload_fileobj(buf, bucket, key)
    uri = f"s3://{bucket}/{key}"
    log.info("Uploaded %s (%d rows)", uri, len(df))
    return uri


def upload_pipeline_outputs(
    players_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    date_partition: str,
) -> dict[str, str]:
    prefix = f"{config.S3_PREFIX}/{date_partition}"
    return {
        "players": upload_parquet_to_s3(players_df, f"{prefix}/players.parquet"),
        "teams":   upload_parquet_to_s3(teams_df,   f"{prefix}/teams.parquet"),
        "stats":   upload_parquet_to_s3(stats_df,   f"{prefix}/season_averages.parquet"),
    }


# ---------------------------------------------------------------------------
# Orchestration (standalone run)
# ---------------------------------------------------------------------------

def run_pipeline(date_partition: str | None = None) -> None:
    from datetime import date
    if date_partition is None:
        date_partition = date.today().isoformat()

    api_key = get_api_key()

    log.info("=== EXTRACT ===")
    players_raw = fetch_players(api_key, max_rows=config.MAX_PLAYERS)
    player_ids = players_raw["id"].tolist()
    stats_raw = fetch_season_averages(api_key, player_ids)

    log.info("=== TRANSFORM ===")
    players_df = clean_players(players_raw)
    teams_df = build_teams_df(players_df)
    stats_df = clean_stats(stats_raw)

    log.info(
        "Players: %d  |  Teams: %d  |  Stat rows: %d",
        len(players_df), len(teams_df), len(stats_df),
    )

    log.info("=== LOAD → PostgreSQL ===")
    load_all_to_postgres(players_df, teams_df, stats_df)

    log.info("=== UPLOAD → S3 ===")
    uris = upload_pipeline_outputs(players_df, teams_df, stats_df, date_partition)
    for name, uri in uris.items():
        log.info("  %-20s %s", name, uri)

    log.info("Pipeline complete for partition %s", date_partition)


if __name__ == "__main__":
    run_pipeline()
