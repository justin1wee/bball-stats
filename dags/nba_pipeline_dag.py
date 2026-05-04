"""
Airflow DAG — NBA Stats Pipeline
Schedule: daily at 03:00 UTC

Stages
──────
extract_players  → transform_players  ─┐
                                        ├→ load_postgres
extract_stats    → transform_stats    ─┘
                                        └→ upload_s3
"""

import sys
import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

# Make the project root importable when running inside Airflow
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from bball_etl import (
    get_api_key,
    fetch_players,
    fetch_season_averages,
    clean_players,
    clean_stats,
    build_teams_df,
    load_all_to_postgres,
    upload_pipeline_outputs,
    upload_parquet_to_s3,
)

import pandas as pd
import boto3
from io import BytesIO

# ---------------------------------------------------------------------------
# Helpers — S3 staging (avoids XCom size limits for large DataFrames)
# ---------------------------------------------------------------------------

def _staging_key(date_str: str, name: str) -> str:
    return f"{config.S3_PREFIX}/staging/{date_str}/{name}.parquet"


def _write_staging(df: pd.DataFrame, date_str: str, name: str) -> str:
    key = _staging_key(date_str, name)
    upload_parquet_to_s3(df, key)
    return key


def _read_staging(key: str) -> pd.DataFrame:
    s3 = boto3.client("s3", region_name=config.AWS_REGION)
    buf = BytesIO()
    s3.download_fileobj(config.S3_BUCKET, key, buf)
    buf.seek(0)
    return pd.read_parquet(buf)


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}


@dag(
    dag_id="nba_stats_pipeline",
    description="Daily NBA stats ETL → PostgreSQL + S3 (PowerBI source)",
    schedule="0 3 * * *",
    start_date=days_ago(1),
    catchup=False,
    default_args=default_args,
    tags=["nba", "etl", "s3", "postgres"],
)
def nba_stats_pipeline():

    @task()
    def extract_players(date_str: str) -> str:
        api_key = get_api_key(config.API_KEY_PATH)
        df = fetch_players(api_key, max_rows=config.MAX_PLAYERS)
        return _write_staging(df, date_str, "raw_players")

    @task()
    def extract_stats(players_key: str, date_str: str) -> str:
        api_key = get_api_key(config.API_KEY_PATH)
        players_raw = _read_staging(players_key)
        player_ids = players_raw["id"].tolist()
        df = fetch_season_averages(api_key, player_ids, seasons=config.SEASONS)
        return _write_staging(df, date_str, "raw_stats")

    @task()
    def transform_players(players_key: str, date_str: str) -> str:
        df = clean_players(_read_staging(players_key))
        return _write_staging(df, date_str, "players")

    @task()
    def transform_stats(stats_key: str, date_str: str) -> str:
        df = clean_stats(_read_staging(stats_key))
        return _write_staging(df, date_str, "stats")

    @task()
    def load_postgres(players_key: str, stats_key: str) -> dict:
        players_df = _read_staging(players_key)
        stats_df   = _read_staging(stats_key)
        teams_df   = build_teams_df(players_df)
        load_all_to_postgres(players_df, teams_df, stats_df)
        return {
            "players": len(players_df),
            "teams":   len(teams_df),
            "stats":   len(stats_df),
        }

    @task()
    def upload_s3(players_key: str, stats_key: str, date_str: str) -> dict:
        players_df = _read_staging(players_key)
        stats_df   = _read_staging(stats_key)
        teams_df   = build_teams_df(players_df)
        uris = upload_pipeline_outputs(players_df, teams_df, stats_df, date_partition=date_str)
        return uris

    # ── Wire up the graph ──────────────────────────────────────────────────
    date_str = "{{ ds }}"   # Airflow logical date, e.g. "2025-05-03"

    raw_players_key = extract_players(date_str)
    raw_stats_key   = extract_stats(raw_players_key, date_str)

    clean_players_key = transform_players(raw_players_key, date_str)
    clean_stats_key   = transform_stats(raw_stats_key, date_str)

    load_postgres(clean_players_key, clean_stats_key)
    upload_s3(clean_players_key, clean_stats_key, date_str)


nba_stats_pipeline()
