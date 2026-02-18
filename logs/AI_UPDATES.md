# AI Updates

## 2026-02-18 — Automated daily birdweather render via launchd
- Created `scripts/render-birdweather.sh`: renders `birdweather/index.qmd` (via `pixi run`), then renders the full site, commits `_freeze/` changes, and pushes to GitHub (triggering Netlify auto-deploy). Logs to `~/Library/Logs/render-birdweather.log` and sends a macOS notification on failure.
- Created `~/Library/LaunchAgents/com.connorfrench.render-birdweather.plist`: runs the script daily at 12 PM local time via macOS launchd. Handles wake-from-sleep catch-up.
- Parquet data (`birdweather/data/`) stays local and gitignored; only `_freeze/` and tracked file changes are committed.
- To manage: `launchctl load|unload ~/Library/LaunchAgents/com.connorfrench.render-birdweather.plist`

## 2026-02-18 — Move pixi environment to birdweather/
- Created `birdweather/pixi.toml` as a standalone pixi workspace with all previously root-level dependencies (polars, altair, seaborn, matplotlib, requests, python-dotenv, jupyter, vl-convert-python, Python 3.14).
- Ran `pixi install` in `birdweather/` to generate `birdweather/pixi.lock`.
- Removed `[tool.pixi.*]` sections from root `pyproject.toml` (kept project/build-system metadata).
- Deleted root `pixi.lock`.
- Updated `.gitattributes` to track `birdweather/pixi.lock` instead of root `pixi.lock`.
- Render birdweather from within its directory: `cd birdweather && pixi run quarto render index.qmd`

## 2026-02-18 — Fix overview counts using local cached detections
- The "Species Detected" and "Total Detections" cards in the BirdWeather overview were using `overview["counts"]` from the GraphQL API, which returned stale/incomplete numbers (19 species, 607 detections). Changed `birdweather/index.qmd` to compute these counts from the locally synced `detections` DataFrame instead, which has the full data (96K+ detections, 136 species).

## 2026-02-18 — Incremental Parquet Cache for BirdWeather

### What changed
- **New module**: Added `birdweather/data_store.py` — local Parquet caching layer with incremental sync and local aggregation functions
- **Incremental sync**: Raw detections and environment sensor data are stored in `birdweather/data/` as Parquet files. On each render, only new data since the last sync is fetched from the BirdWeather API.
- **Local aggregations**: Top species, daily detection counts, and time-of-day counts are now computed locally from cached raw detections using Polars instead of calling the API for server-side aggregations.
- **Species metadata**: Cached in `species_meta.parquet`, re-fetched only when new species appear in detections.
- **Species probabilities**: Cached in `species_probabilities.parquet`, re-fetched if older than 7 days (BirdWeather model data).
- **Station overview**: Still fetched live from the API on each render (contains current weather).
- **`.gitignore`**: Added `birdweather/data/` to exclude cached Parquet files from git.
- **`fetch_data.py`**: Increased default `max_pages` for `get_detections()` from 100 to 500 for initial seed load.
- **`index.qmd`**: Rewrote setup and fetch-data cells to use `data_store` sync/compute functions instead of direct API calls. All downstream visualization cells unchanged (same DataFrame schemas).

## 2026-02-18
- Fixed `TypeError: 'DataFrame' object is not callable` in `birdweather/index.qmd`: removed spurious `()` after `env_hist.with_columns(...)` (line ~785) and changed `pdf = combined()` to `pdf = combined` (line ~694). Log
- Fixed "Not enough overlapping data" in env-correlations cell: changed inner join to full outer join with explicit `pl.Date` casting, used `daily_counts` (365-day) instead of only `daily_counts_30d` for more overlap with env sensor data, and filled missing detections with 0.
- Root-caused env correlation issue: PUC sensor reports every ~40 seconds, so the old pagination defaults (100 rows × 50 pages = 5,000 rows) only covered ~2.3 days. Increased `page_size` from 100→1000 and `max_pages` from 50→100 in `get_environment_history()`, now fetching ~65K rows covering the full 30-day period. Updated both the default parameters in `fetch_data.py` and the call in `index.qmd`.
- Removed station name/number from the overview footer to avoid exposing the station ID on the public page (location is still shown).
- Fixed "Unavailable" weather: when the BirdWeather weather API returns null, the page now falls back to the PUC environment sensor's temperature and humidity readings.
- Downsampled env-timeseries chart from ~65K raw sensor readings to hourly averages (~720 points) to stay within Altair's 5,000-row limit.
- Extended env history fetch from 30 to 180 days (max_pages 100→400) to cover the full detection history for environmental correlations.
- Added `scale=alt.Scale(zero=False)` to x-axes on all three env correlation scatter plots so the axis range fits the data rather than starting from zero.

## 2026-02-18 — BirdWeather Dashboard Page

### What changed
- **New page**: Added `birdweather/index.qmd` — a full bird detection dashboard page with interactive Altair visualizations
- **New module**: Added `birdweather/fetch_data.py` — Python module that wraps the BirdWeather GraphQL API, returning Polars DataFrames for station overview, top species, daily/hourly detection counts, environment sensor history, and species probability data
- **Navigation**: Added "BirdWeather" tab to the navbar in `_quarto.yml` (between Projects and Teaching)
- **Python environment**: Initialized Pixi (`pyproject.toml`) with dependencies: polars, altair, seaborn, matplotlib, requests, python-dotenv, jupyter, vl-convert-python
- **Config**: Created `.env` (for `BIRDWEATHER_STATION_ID`) and added `.env` and `.pixi/` to `.gitignore`

### Dashboard sections
1. **Station Overview** — metric cards showing total species, detections, date range, current weather & sensor readings
2. **Recent Activity** — top 10 species in the last 7 days, new arrivals this week, 30-day detection trend, daily species richness
3. **All-Time Highlights** — top 15 species with certainty breakdown (stacked bar), rarest visitors table
4. **When Do Birds Sing?** — hourly detection bar chart + species × hour heatmap
5. **Seasonal Trends** — monthly detection volume with species richness overlay, species probability heatmap (week of year × species)
6. **Environmental Correlations** — scatter plots with trend lines for temperature, humidity, and barometric pressure vs. detection count; sensor time series
7. **Species Gallery** — grid of top 20 species with images, names, detection counts, and Wikipedia summaries

### Why
User requested a fun bird detection summary page for their BirdWeather PUC station, with short-term and long-term trends and environmental correlations.
