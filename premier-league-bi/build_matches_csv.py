"""
Pulls 11 seasons of Premier League match data (2015/16 through 2025/26)
from football-data.co.uk's historical results archive, reconciles team
name inconsistencies across seasons, and writes the combined result to
matches_combined.csv for import into the Power BI semantic model.

Source data:
    football-data.co.uk publishes one CSV per season per league
    (E0 = English Premier League), keyed by a 4-digit season code
    (e.g. "1516" for 2015/16). Column layout and even date formatting
    drift slightly between seasons, which is why this script pins down
    a fixed core column set and a mixed-format date parser rather than
    trusting each season's file to be identical.

Output shape:
    The output stays in the same "one row per match, home/away side by
    side" wide format as the source files (Date, HomeTeam, AwayTeam,
    FTHG, FTAG, ...). It is intentionally NOT unpivoted into a
    per-team-per-match shape here — that transformation happens inside
    the Power BI semantic model's Power Query step (see
    premier-league.SemanticModel/definition/tables/Team_Matches.tmdl), so this
    script's output mirrors the raw source schema plus a Season column.

Usage:
    python build_matches_csv.py

Requires: pandas
    pip install pandas
"""

import pandas as pd

# ---------------------------------------------------------------------
# Seasons to pull — 2015/16 through 2025/26 (11 seasons)
# ---------------------------------------------------------------------
SEASONS: list[str] = ["1516", "1617", "1718", "1819", "1920",
                       "2021", "2122", "2223", "2324", "2425", "2526"]

CORE_COLS: list[str] = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
                         "HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST", "AST",
                         "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"]

SEASON_URL_TEMPLATE: str = "https://www.football-data.co.uk/mmz4281/{season}/E0.csv"
OUTPUT_CSV_PATH: str = "matches_combined.csv"
SOURCE_ENCODING: str = "cp1252"

hist_frames: list[pd.DataFrame] = []
for season in SEASONS:
    url: str = SEASON_URL_TEMPLATE.format(season=season)
    print(f"Fetching season {season}...")
    df: pd.DataFrame = pd.read_csv(url, encoding=SOURCE_ENCODING)
    df = df[[c for c in CORE_COLS if c in df.columns]]
    df["Season"] = season
    hist_frames.append(df)

Matches: pd.DataFrame = pd.concat(hist_frames, ignore_index=True)

# Some older season files use DD/MM/YY (2-digit year) instead of
# DD/MM/YYYY, so we can't rely on one fixed format string.
# format="mixed" parses each date individually rather than caching one
# guessed format for the whole column; dayfirst=True resolves ambiguous
# dates using the UK day-first convention.
Matches["Date"] = pd.to_datetime(Matches["Date"], format="mixed", dayfirst=True)

# ---------------------------------------------------------------------
# Reconcile team name inconsistencies across seasons
# (e.g. "Nott'm Forest" appearing differently across years)
# ---------------------------------------------------------------------
name_map: dict[str, str] = {
    "Man United": "Man United",
    "Man City": "Man City",
    "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle",
    "Brighton": "Brighton",
    "Leeds": "Leeds",
    "Spurs": "Tottenham",
    "Tottenham": "Tottenham",
    "West Brom": "West Brom",
    "Wolves": "Wolverhampton",
}
Matches["HomeTeam"] = Matches["HomeTeam"].replace(name_map)
Matches["AwayTeam"] = Matches["AwayTeam"].replace(name_map)

# ---------------------------------------------------------------------
# Sanity check + export
# ---------------------------------------------------------------------
all_teams: list[str] = sorted(set(Matches["HomeTeam"]).union(Matches["AwayTeam"]))
print("\nDistinct team names in final data:")
for t in all_teams:
    print(f"  - {t}")

Matches.to_csv(OUTPUT_CSV_PATH, index=False)
print(f"\nDone. Wrote {len(Matches)} rows to {OUTPUT_CSV_PATH}")
