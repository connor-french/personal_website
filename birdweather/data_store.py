"""
BirdWeather local Parquet cache and aggregation module.

Stores raw detections and environment sensor data as Parquet files,
supports incremental sync (only fetches new data since the last sync),
and computes all aggregations locally from cached data using Polars.
"""

import os
import polars as pl
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fetch_data import (
    get_detections,
    get_environment_history,
    get_top_species,
    get_species_by_ids,
    get_species_probabilities,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

DETECTIONS_PATH = DATA_DIR / "detections.parquet"
ENVIRONMENT_PATH = DATA_DIR / "environment.parquet"
SPECIES_META_PATH = DATA_DIR / "species_meta.parquet"
SPECIES_PROBS_PATH = DATA_DIR / "species_probabilities.parquet"


def _ensure_data_dir() -> None:
    """Create the data directory if it doesn't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Sync: Detections
# ---------------------------------------------------------------------------

def sync_detections(
    station_id: str,
    earliest_detection_at: str | None = None,
) -> pl.DataFrame:
    """
    Incrementally sync detections to a local Parquet file.

    On first run, fetches all available detections. On subsequent runs,
    only fetches detections newer than the latest cached timestamp
    (detections are returned newest-first from the API, so we stop
    paginating once we hit the cached boundary).

    Parameters
    ----------
    station_id : str
        BirdWeather station ID.
    earliest_detection_at : str, optional
        ISO timestamp of the station's earliest detection. Used as a
        floor to stop pagination on the initial seed fetch.

    Returns the full detections DataFrame.
    """
    _ensure_data_dir()

    existing: pl.DataFrame | None = None
    stop_before: datetime | None = None

    if DETECTIONS_PATH.exists():
        existing = pl.read_parquet(DETECTIONS_PATH)
        if existing.height > 0:
            max_ts = existing["timestamp"].max()
            # Use max timestamp as the stop boundary — the API returns
            # detections newest-first, so once we see one at or before
            # this timestamp we know we've caught up.
            stop_before = max_ts.replace(tzinfo=timezone.utc) if max_ts.tzinfo is None else max_ts
            print(f"  Detections cache: {existing.height:,} rows, latest: {max_ts}")
        else:
            print("  Detections cache: empty, fetching all...")
    else:
        print("  Detections cache: not found, fetching all (this may take a while)...")

    new_data = get_detections(
        station_id=station_id,
        page_size=100,
        max_pages=1000,
        stop_before=stop_before,
        earliest_detection_at=earliest_detection_at,
    )

    print(f"  Fetched {new_data.height:,} new detections")

    if existing is not None and existing.height > 0:
        if new_data.height > 0:
            # Align schemas: add any new columns (e.g. ebirdUrl) missing
            # from the cached parquet as null so concat works.
            for col in new_data.columns:
                if col not in existing.columns:
                    existing = existing.with_columns(pl.lit(None).cast(new_data[col].dtype).alias(col))
            for col in existing.columns:
                if col not in new_data.columns:
                    new_data = new_data.with_columns(pl.lit(None).cast(existing[col].dtype).alias(col))
            # Ensure identical column order before concat
            new_data = new_data.select(existing.columns)
            combined = pl.concat([existing, new_data])
            # Deduplicate by detection id, keeping the latest
            combined = combined.unique(subset=["id"], keep="last").sort("timestamp")
        else:
            combined = existing
    else:
        combined = new_data.sort("timestamp") if new_data.height > 0 else new_data

    if combined.height > 0:
        combined.write_parquet(DETECTIONS_PATH)

    return combined


# ---------------------------------------------------------------------------
# Sync: Environment sensor history
# ---------------------------------------------------------------------------

def sync_environment(station_id: str) -> pl.DataFrame:
    """
    Incrementally sync environment sensor readings to a local Parquet file.

    On first run, fetches a large window of history. On subsequent runs,
    only fetches readings newer than the latest cached timestamp.

    Returns the full environment DataFrame.
    """
    _ensure_data_dir()

    existing: pl.DataFrame | None = None
    period: dict | None = None

    if ENVIRONMENT_PATH.exists():
        existing = pl.read_parquet(ENVIRONMENT_PATH)
        if existing.height > 0:
            max_ts = existing["timestamp"].max()
            from_ts = (max_ts + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            to_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            period = {"from": from_ts, "to": to_ts}

    new_data = get_environment_history(
        station_id=station_id,
        period=period,
        page_size=1000,
        max_pages=400,
    )

    if existing is not None and existing.height > 0:
        if new_data.height > 0:
            combined = pl.concat([existing, new_data])
            # Deduplicate by timestamp
            combined = combined.unique(subset=["timestamp"], keep="last").sort("timestamp")
        else:
            combined = existing
    else:
        combined = new_data.sort("timestamp") if new_data.height > 0 else new_data

    if combined.height > 0:
        combined.write_parquet(ENVIRONMENT_PATH)

    return combined


# ---------------------------------------------------------------------------
# Sync: Species metadata
# ---------------------------------------------------------------------------

def sync_species_meta(station_id: str, detections: pl.DataFrame) -> pl.DataFrame:
    """
    Ensure species metadata is cached for all species in the detections.

    Uses the station's topSpecies API for the bulk of metadata, then
    fetches any remaining species via the allSpecies(ids: [...]) root
    query — the only reliable way to get ebirdUrl, imageUrl, etc. for
    species that topSpecies doesn't cover.

    Returns a DataFrame with species metadata columns.
    """
    _ensure_data_dir()

    meta_cols = [
        "speciesId", "commonName", "scientificName",
        "imageUrl", "thumbnailUrl", "color",
        "ebirdUrl", "wikipediaSummary",
    ]

    existing: pl.DataFrame | None = None
    if SPECIES_META_PATH.exists():
        existing = pl.read_parquet(SPECIES_META_PATH)

    # Check for species IDs not yet in metadata
    detection_species_ids = set(detections["speciesId"].unique().to_list()) if detections.height > 0 else set()
    cached_species_ids = set(existing["speciesId"].unique().to_list()) if existing is not None and existing.height > 0 else set()

    missing = detection_species_ids - cached_species_ids

    # Also check for species in the cache that are missing ebirdUrl
    if existing is not None and existing.height > 0 and "ebirdUrl" in existing.columns:
        null_url_ids = set(
            existing.filter(pl.col("ebirdUrl").is_null())
            ["speciesId"].to_list()
        )
        missing = missing | null_url_ids

    if missing or existing is None or existing.height == 0:
        # Start with topSpecies (covers the station's most-detected species)
        api_species = get_top_species(station_id=station_id, limit=1000)
        if api_species.height > 0:
            meta = api_species.select([c for c in meta_cols if c in api_species.columns])
            meta = meta.unique(subset=["speciesId"])
        elif existing is not None and existing.height > 0:
            meta = existing
        else:
            meta = pl.DataFrame(schema={c: pl.Utf8 for c in meta_cols})

        # Fill gaps: use the allSpecies(ids: [...]) root query to fetch
        # full metadata for species not covered by topSpecies.
        meta_ids = set(meta["speciesId"].unique().to_list()) if meta.height > 0 else set()
        still_missing = detection_species_ids - meta_ids

        if still_missing:
            print(f"  Fetching metadata for {len(still_missing)} additional species via allSpecies...")
            extra_meta = get_species_by_ids(sorted(still_missing))
            if extra_meta.height > 0:
                # Ensure both DataFrames have the same columns in the same order
                for col in meta_cols:
                    if col not in extra_meta.columns:
                        extra_meta = extra_meta.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))
                extra_meta = extra_meta.select(meta_cols)
                meta = meta.select(meta_cols)
                meta = pl.concat([meta, extra_meta]).unique(subset=["speciesId"])

        meta.write_parquet(SPECIES_META_PATH)
        return meta

    return existing


# ---------------------------------------------------------------------------
# Sync: Species probabilities
# ---------------------------------------------------------------------------

def sync_species_probabilities(station_id: str) -> pl.DataFrame:
    """
    Sync species probability (seasonal model) data.

    Re-fetches if the cached file doesn't exist or is older than 7 days.
    This is BirdWeather model data that changes slowly.

    Returns a DataFrame with speciesId, commonName, week, probability.
    """
    _ensure_data_dir()

    if SPECIES_PROBS_PATH.exists():
        # Check file age
        mtime = datetime.fromtimestamp(
            SPECIES_PROBS_PATH.stat().st_mtime, tz=timezone.utc
        )
        age = datetime.now(timezone.utc) - mtime
        if age < timedelta(days=7):
            return pl.read_parquet(SPECIES_PROBS_PATH)

    probs = get_species_probabilities(station_id=station_id)
    if probs.height > 0:
        probs.write_parquet(SPECIES_PROBS_PATH)

    return probs


# ---------------------------------------------------------------------------
# Local aggregations
# ---------------------------------------------------------------------------

def compute_top_species(
    detections: pl.DataFrame,
    species_meta: pl.DataFrame,
    period_days: int | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """
    Compute top species from cached detections, matching the schema of
    get_top_species().

    Parameters
    ----------
    detections : pl.DataFrame
        Raw detections with columns: id, timestamp, speciesId, commonName,
        scientificName, confidence, probability, score, certainty.
    species_meta : pl.DataFrame
        Species metadata with imageUrl, thumbnailUrl, color, etc.
    period_days : int, optional
        If set, only include detections from the last N days.
    limit : int
        Maximum number of species to return.

    Returns
    -------
    pl.DataFrame matching the get_top_species() schema.
    """
    if detections.height == 0:
        return pl.DataFrame(
            schema={
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "scientificName": pl.Utf8,
                "imageUrl": pl.Utf8,
                "thumbnailUrl": pl.Utf8,
                "color": pl.Utf8,
                "ebirdUrl": pl.Utf8,
                "wikipediaSummary": pl.Utf8,
                "count": pl.Int64,
                "almostCertain": pl.Int64,
                "veryLikely": pl.Int64,
                "uncertain": pl.Int64,
                "unlikely": pl.Int64,
                "averageProbability": pl.Float64,
            }
        )

    df = detections
    if period_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        df = df.filter(pl.col("timestamp") >= cutoff)

    if df.height == 0:
        return compute_top_species(pl.DataFrame(schema=detections.schema), species_meta, limit=limit)

    # Map certainty strings to the column names used by the API
    certainty_map = {
        "almost_certain": "almostCertain",
        "very_likely": "veryLikely",
        "uncertain": "uncertain",
        "unlikely": "unlikely",
    }

    # Compute per-species aggregates
    agg = (
        df
        .group_by("speciesId")
        .agg(
            pl.len().cast(pl.Int64).alias("count"),
            pl.col("probability").mean().alias("averageProbability"),
            pl.col("commonName").first().alias("commonName"),
            pl.col("scientificName").first().alias("scientificName"),
            # Certainty breakdown
            (pl.col("certainty") == "almost_certain").sum().cast(pl.Int64).alias("almostCertain"),
            (pl.col("certainty") == "very_likely").sum().cast(pl.Int64).alias("veryLikely"),
            (pl.col("certainty") == "uncertain").sum().cast(pl.Int64).alias("uncertain"),
            (pl.col("certainty") == "unlikely").sum().cast(pl.Int64).alias("unlikely"),
        )
        .sort("count", descending=True)
        .head(limit)
    )

    # Join with species metadata for images, wiki, ebird, etc.
    # Drop commonName/scientificName from metadata to avoid conflicts —
    # we already have them from detections.
    meta_cols = [c for c in species_meta.columns if c not in ("commonName", "scientificName")]
    result = agg.join(species_meta.select(meta_cols), on="speciesId", how="left")

    # Ensure all expected columns exist
    for col in ["imageUrl", "thumbnailUrl", "color", "ebirdUrl", "wikipediaSummary"]:
        if col not in result.columns:
            result = result.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))

    # Reorder columns to match API schema
    col_order = [
        "speciesId", "commonName", "scientificName",
        "imageUrl", "thumbnailUrl", "color", "ebirdUrl", "wikipediaSummary",
        "count", "almostCertain", "veryLikely", "uncertain", "unlikely",
        "averageProbability",
    ]
    result = result.select([c for c in col_order if c in result.columns])

    return result


def compute_daily_detection_counts(
    detections: pl.DataFrame,
    period_days: int | None = None,
) -> pl.DataFrame:
    """
    Compute daily per-species detection counts from cached detections,
    matching the schema of get_daily_detection_counts().

    Returns a DataFrame with columns: date, dayOfYear, dailyTotal,
    speciesId, commonName, count.
    """
    if detections.height == 0:
        return pl.DataFrame(
            schema={
                "date": pl.Date,
                "dayOfYear": pl.Int64,
                "dailyTotal": pl.Int64,
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "count": pl.Int64,
            }
        )

    df = detections
    if period_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        df = df.filter(pl.col("timestamp") >= cutoff)

    if df.height == 0:
        return compute_daily_detection_counts(
            pl.DataFrame(schema=detections.schema)
        )

    # Extract date from timestamp
    df = df.with_columns(pl.col("timestamp").dt.date().alias("date"))

    # Per-species daily counts
    species_daily = (
        df
        .group_by("date", "speciesId", "commonName")
        .agg(pl.len().alias("count"))
    )

    # Daily totals
    daily_totals = (
        species_daily
        .group_by("date")
        .agg(pl.col("count").sum().alias("dailyTotal"))
    )

    # Join and add dayOfYear
    result = (
        species_daily
        .join(daily_totals, on="date", how="left")
        .with_columns(
            pl.col("date").dt.ordinal_day().cast(pl.Int64).alias("dayOfYear")
        )
        .sort("date", "commonName")
    )

    # Reorder columns
    return result.select("date", "dayOfYear", "dailyTotal", "speciesId", "commonName", "count")


def compute_time_of_day_counts(
    detections: pl.DataFrame,
) -> pl.DataFrame:
    """
    Compute detection counts binned by hour of day from cached detections,
    matching the schema of get_time_of_day_counts().

    Returns a DataFrame with columns: speciesId, commonName, totalCount,
    hour, count.
    """
    if detections.height == 0:
        return pl.DataFrame(
            schema={
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "totalCount": pl.Int64,
                "hour": pl.Float64,
                "count": pl.Int64,
            }
        )

    # Extract hour from timestamp
    df = detections.with_columns(
        pl.col("timestamp").dt.hour().cast(pl.Float64).alias("hour")
    )

    # Per-species, per-hour counts
    hourly = (
        df
        .group_by("speciesId", "commonName", "hour")
        .agg(pl.len().alias("count"))
    )

    # Per-species totals
    species_totals = (
        hourly
        .group_by("speciesId")
        .agg(pl.col("count").sum().alias("totalCount"))
    )

    # Join
    result = (
        hourly
        .join(species_totals, on="speciesId", how="left")
        .sort("speciesId", "hour")
    )

    return result.select("speciesId", "commonName", "totalCount", "hour", "count")
