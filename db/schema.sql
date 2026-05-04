-- NBA Stats Pipeline Schema
-- Run once to initialise the PostgreSQL database.

CREATE TABLE IF NOT EXISTS teams (
    id            INTEGER PRIMARY KEY,
    conference    TEXT,
    division      TEXT,
    city          TEXT,
    name          TEXT,
    full_name     TEXT,
    abbreviation  CHAR(3)
);

CREATE TABLE IF NOT EXISTS players (
    id                INTEGER PRIMARY KEY,
    first_name        TEXT        NOT NULL,
    last_name         TEXT        NOT NULL,
    position          TEXT,
    primary_position  CHAR(1),            -- G / F / C
    height            TEXT,
    weight            INTEGER,
    jersey_number     TEXT,
    college           TEXT,
    country           TEXT,
    draft_year        SMALLINT,
    draft_round       SMALLINT,
    draft_number      SMALLINT,
    team_id           INTEGER     REFERENCES teams(id)
);

CREATE TABLE IF NOT EXISTS season_averages (
    player_id    INTEGER   NOT NULL REFERENCES players(id),
    season       SMALLINT  NOT NULL,
    games_played SMALLINT,
    min          NUMERIC(5,2),   -- minutes per game
    pts          NUMERIC(5,2),
    reb          NUMERIC(5,2),
    ast          NUMERIC(5,2),
    stl          NUMERIC(5,2),
    blk          NUMERIC(5,2),
    turnover     NUMERIC(5,2),
    fg_pct       NUMERIC(5,4),
    fg3_pct      NUMERIC(5,4),
    ft_pct       NUMERIC(5,4),
    fgm          NUMERIC(5,2),
    fga          NUMERIC(5,2),
    fg3m         NUMERIC(5,2),
    fg3a         NUMERIC(5,2),
    ftm          NUMERIC(5,2),
    fta          NUMERIC(5,2),
    oreb         NUMERIC(5,2),
    dreb         NUMERIC(5,2),
    pf           NUMERIC(5,2),
    PRIMARY KEY (player_id, season)
);

-- Indexes used by typical PowerBI / analytical queries
CREATE INDEX IF NOT EXISTS idx_players_primary_position ON players(primary_position);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_season_averages_season ON season_averages(season);
CREATE INDEX IF NOT EXISTS idx_season_averages_player ON season_averages(player_id);
