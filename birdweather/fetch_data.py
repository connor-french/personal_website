"""
BirdWeather GraphQL API data fetching module.

Fetches bird detection data, species info, environmental sensor readings,
and weather data from a BirdWeather PUC station via the GraphQL API.
Returns data as Polars DataFrames for analysis and visualization.
"""

import os
import requests
import polars as pl
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GRAPHQL_URL = "https://app.birdweather.com/graphql"
REST_BASE_URL = "https://app.birdweather.com/api/v1"

# Cache for resolved numeric station ID
_station_numeric_id_cache: dict[str, str] = {}


def get_token() -> str | None:
    """Get the BirdWeather station token from environment (may be same as station ID)."""
    return os.getenv("BIRDWEATHER_TOKEN") or os.getenv("BIRDWEATHER_STATION_ID")


def query_graphql(query: str, variables: dict | None = None, retries: int = 3) -> dict:
    """Send a GraphQL query and return the JSON response data."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    token = get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    import time
    for attempt in range(retries):
        try:
            resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                raise RuntimeError(f"GraphQL errors: {result['errors']}")
            return result["data"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def resolve_station_numeric_id(token: str) -> str:
    """
    Resolve the numeric station ID from a token/slug using a GraphQL search.
    The GraphQL `station(id: $id)` query requires the numeric ID.
    Caches the result to avoid repeated calls.
    """
    if token in _station_numeric_id_cache:
        return _station_numeric_id_cache[token]

    query = """
    query FindStation($query: String) {
      stations(query: $query, first: 1) {
        nodes { id name }
      }
    }
    """
    data = query_graphql(query, {"query": token})
    nodes = data.get("stations", {}).get("nodes", [])
    if not nodes:
        raise ValueError(
            f"Could not find a station matching '{token}'. "
            "Check your BIRDWEATHER_STATION_ID in .env."
        )
    numeric_id = str(nodes[0]["id"])
    _station_numeric_id_cache[token] = numeric_id
    return numeric_id


def get_station_id() -> str:
    """
    Get the numeric station ID for use in GraphQL queries.
    Resolves from the token/slug via the REST API if needed.
    """
    token = os.getenv("BIRDWEATHER_STATION_ID")
    if not token:
        raise ValueError(
            "BIRDWEATHER_STATION_ID not set. "
            "Add it to your .env file."
        )
    # If the value is already numeric, use it directly
    if token.isdigit():
        return token
    # Otherwise resolve the numeric ID via REST
    return resolve_station_numeric_id(token)


# ---------------------------------------------------------------------------
# Station overview
# ---------------------------------------------------------------------------

def get_station_overview(station_id: str | None = None) -> dict:
    """
    Fetch station metadata: name, location, total counts, date range,
    current weather, and current environment sensor reading.
    """
    station_id = station_id or get_station_id()
    query = """
    query StationOverview($id: ID!) {
      station(id: $id) {
        name
        location
        timezone
        type
        coords { lat lon }
        counts { detections species }
        earliestDetectionAt
        latestDetectionAt
        weather {
          temp
          feelsLike
          humidity
          pressure
          description
          windSpeed
          cloudiness
          sunrise
          sunset
        }
        sensors {
          environment {
            temperature
            humidity
            barometricPressure
            soundPressureLevel
            aqi
            eco2
            voc
            timestamp
          }
        }
      }
    }
    """
    data = query_graphql(query, {"id": station_id})
    return data["station"]


# ---------------------------------------------------------------------------
# Top species
# ---------------------------------------------------------------------------

def get_top_species(
    station_id: str | None = None,
    period: dict | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """
    Fetch top species for a station within a time period.

    Parameters
    ----------
    station_id : str, optional
        BirdWeather station ID. Falls back to env var.
    period : dict, optional
        InputDuration dict, e.g. {"count": 7, "unit": "day"} or
        {"from": "2025-01-01", "to": "2025-12-31"}. Defaults to all-time.
    limit : int
        Max species to return (default 100).

    Returns
    -------
    pl.DataFrame with columns: speciesId, commonName, scientificName,
        imageUrl, thumbnailUrl, color, count, almostCertain, veryLikely,
        uncertain, unlikely, averageProbability
    """
    station_id = station_id or get_station_id()
    query = """
    query TopSpecies($id: ID!, $limit: Int, $period: InputDuration) {
      station(id: $id) {
        topSpecies(limit: $limit, period: $period) {
          speciesId
          count
          averageProbability
          breakdown { almostCertain veryLikely uncertain unlikely }
          species {
            commonName
            scientificName
            imageUrl
            thumbnailUrl
            color
            ebirdUrl
            wikipediaSummary
          }
        }
      }
    }
    """
    variables: dict = {"id": station_id, "limit": limit}
    if period:
        variables["period"] = period

    data = query_graphql(query, variables)
    rows = []
    for sp in data["station"]["topSpecies"]:
        species = sp["species"]
        bd = sp.get("breakdown") or {}
        rows.append({
            "speciesId": sp["speciesId"],
            "commonName": species["commonName"],
            "scientificName": species["scientificName"],
            "imageUrl": species.get("imageUrl"),
            "thumbnailUrl": species.get("thumbnailUrl"),
            "color": species.get("color"),
            "ebirdUrl": species.get("ebirdUrl"),
            "wikipediaSummary": species.get("wikipediaSummary"),
            "count": sp["count"],
            "almostCertain": bd.get("almostCertain", 0),
            "veryLikely": bd.get("veryLikely", 0),
            "uncertain": bd.get("uncertain", 0),
            "unlikely": bd.get("unlikely", 0),
            "averageProbability": sp.get("averageProbability"),
        })

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Daily detection counts
# ---------------------------------------------------------------------------

def get_daily_detection_counts(
    station_id: str | None = None,
    period: dict | None = None,
) -> pl.DataFrame:
    """
    Fetch per-day, per-species detection counts.

    Returns a DataFrame with columns: date, dayOfYear, total,
    speciesId, commonName, count.
    """
    station_id = station_id or get_station_id()
    query = """
    query DailyDetections($period: InputDuration, $stationIds: [ID!]) {
      dailyDetectionCounts(period: $period, stationIds: $stationIds) {
        date
        dayOfYear
        total
        counts {
          speciesId
          count
          species { commonName }
        }
      }
    }
    """
    variables: dict = {"stationIds": [station_id]}
    if period:
        variables["period"] = period

    data = query_graphql(query, variables)
    rows = []
    for day in data["dailyDetectionCounts"]:
        for sp in day["counts"]:
            rows.append({
                "date": day["date"],
                "dayOfYear": day["dayOfYear"],
                "dailyTotal": day["total"],
                "speciesId": sp["speciesId"],
                "commonName": sp["species"]["commonName"],
                "count": sp["count"],
            })

    if not rows:
        return pl.DataFrame(
            schema={
                "date": pl.Utf8,
                "dayOfYear": pl.Int64,
                "dailyTotal": pl.Int64,
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "count": pl.Int64,
            }
        )

    return pl.DataFrame(rows).with_columns(
        pl.col("date").str.to_date("%Y-%m-%d")
    )


# ---------------------------------------------------------------------------
# Time-of-day detection counts
# ---------------------------------------------------------------------------

def get_time_of_day_counts(
    station_id: str | None = None,
    period: dict | None = None,
) -> pl.DataFrame:
    """
    Fetch detection counts binned by hour of day.

    Returns a DataFrame with columns: speciesId, commonName, hour, count.
    """
    station_id = station_id or get_station_id()
    query = """
    query TimeOfDay($id: ID!, $period: InputDuration) {
      station(id: $id) {
        timeOfDayDetectionCounts(period: $period) {
          speciesId
          count
          species { commonName }
          bins { count key }
        }
      }
    }
    """
    variables: dict = {"id": station_id}
    if period:
        variables["period"] = period

    data = query_graphql(query, variables)
    rows = []
    for sp in data["station"]["timeOfDayDetectionCounts"]:
        for b in sp["bins"]:
            rows.append({
                "speciesId": sp["speciesId"],
                "commonName": sp["species"]["commonName"],
                "totalCount": sp["count"],
                "hour": float(b["key"]),
                "count": b["count"],
            })

    if not rows:
        return pl.DataFrame(
            schema={
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "totalCount": pl.Int64,
                "hour": pl.Float64,
                "count": pl.Int64,
            }
        )

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Environment sensor history
# ---------------------------------------------------------------------------

def get_environment_history(
    station_id: str | None = None,
    period: dict | None = None,
    page_size: int = 1000,
    max_pages: int = 100,
) -> pl.DataFrame:
    """
    Fetch PUC environment sensor readings (temperature, humidity,
    barometric pressure, sound pressure level, AQI, eCO2, VOC).

    Paginates through all available readings within the period.
    """
    station_id = station_id or get_station_id()
    query = """
    query EnvHistory($id: ID!, $first: Int, $after: String, $period: InputDuration) {
      station(id: $id) {
        sensors {
          environmentHistory(first: $first, after: $after, period: $period) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes {
              timestamp
              temperature
              humidity
              barometricPressure
              soundPressureLevel
              aqi
              eco2
              voc
            }
          }
        }
      }
    }
    """
    all_nodes: list[dict] = []
    cursor = None

    for _ in range(max_pages):
        variables: dict = {"id": station_id, "first": page_size}
        if cursor:
            variables["after"] = cursor
        if period:
            variables["period"] = period

        data = query_graphql(query, variables)
        hist = data["station"]["sensors"]["environmentHistory"]
        all_nodes.extend(hist["nodes"])

        if not hist["pageInfo"]["hasNextPage"]:
            break
        cursor = hist["pageInfo"]["endCursor"]

    if not all_nodes:
        return pl.DataFrame(
            schema={
                "timestamp": pl.Utf8,
                "temperature": pl.Float64,
                "humidity": pl.Float64,
                "barometricPressure": pl.Float64,
                "soundPressureLevel": pl.Float64,
                "aqi": pl.Float64,
                "eco2": pl.Float64,
                "voc": pl.Float64,
            }
        )

    return pl.DataFrame(all_nodes).with_columns(
        pl.col("timestamp").str.to_datetime("%+")
    )


# ---------------------------------------------------------------------------
# Species probabilities (seasonal patterns)
# ---------------------------------------------------------------------------

def get_species_probabilities(
    station_id: str | None = None,
) -> pl.DataFrame:
    """
    Fetch per-species, per-week-of-year probability data.

    Returns a long-form DataFrame with columns:
    speciesId, commonName, week, probability.
    """
    station_id = station_id or get_station_id()
    query = """
    query Probabilities($id: ID!) {
      station(id: $id) {
        probabilities {
          speciesId
          species { commonName }
          weeks
        }
      }
    }
    """
    data = query_graphql(query, {"id": station_id})
    rows = []
    for sp in data["station"]["probabilities"]:
        for week_idx, prob in enumerate(sp["weeks"]):
            rows.append({
                "speciesId": sp["speciesId"],
                "commonName": sp["species"]["commonName"],
                "week": week_idx,
                "probability": prob,
            })

    if not rows:
        return pl.DataFrame(
            schema={
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "week": pl.Int64,
                "probability": pl.Float64,
            }
        )

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Detections (paginated)
# ---------------------------------------------------------------------------

def get_detections(
    station_id: str | None = None,
    page_size: int = 100,
    max_pages: int = 1000,
    stop_before: datetime | None = None,
    earliest_detection_at: str | None = None,
) -> pl.DataFrame:
    """
    Fetch individual detections with species, timestamp, confidence.

    Parameters
    ----------
    station_id : str, optional
        BirdWeather station ID.
    page_size : int
        Number of detections per page (API max is 100).
    max_pages : int
        Maximum pages to fetch.
    stop_before : datetime, optional
        If provided, stop fetching once we encounter a detection with a
        timestamp at or before this value. Useful for incremental sync —
        detections are returned newest-first, so once we see one older
        than our cache boundary we can stop.
    earliest_detection_at : str, optional
        ISO timestamp of the station's earliest detection. If set, stop
        fetching once we've gone past this timestamp (prevents endlessly
        paginating through global data).

    Returns a DataFrame with columns: id, timestamp, speciesId,
    commonName, scientificName, confidence, probability, score,
    certainty.
    """
    station_id = station_id or get_station_id()

    # Parse the earliest detection boundary if provided
    earliest_dt: datetime | None = None
    if earliest_detection_at:
        earliest_dt = datetime.fromisoformat(
            earliest_detection_at.replace("Z", "+00:00")
        )

    query = """
    query Detections($id: ID!, $first: Int, $after: String) {
      station(id: $id) {
        detections(first: $first, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            timestamp
            speciesId
            species {
              commonName
              scientificName
            }
            confidence
            probability
            score
            certainty
          }
        }
      }
    }
    """
    all_nodes: list[dict] = []
    cursor = None
    hit_boundary = False

    for page_num in range(max_pages):
        variables: dict = {"id": station_id, "first": page_size}
        if cursor:
            variables["after"] = cursor

        data = query_graphql(query, variables)
        det = data["station"]["detections"]
        nodes = det["nodes"]

        # If we got an empty page, we've exhausted this station's data
        if not nodes:
            break

        page_count_before = len(all_nodes)

        for node in nodes:
            node_ts = datetime.fromisoformat(
                node["timestamp"].replace("Z", "+00:00")
            )

            # Stop if we've reached the cached data boundary
            if stop_before is not None and node_ts <= stop_before:
                hit_boundary = True
                break

            # Stop if we've gone past the station's earliest detection
            if earliest_dt is not None and node_ts < earliest_dt:
                hit_boundary = True
                break

            all_nodes.append({
                "id": node["id"],
                "timestamp": node["timestamp"],
                "speciesId": node["speciesId"],
                "commonName": node["species"]["commonName"],
                "scientificName": node["species"]["scientificName"],
                "confidence": node["confidence"],
                "probability": node.get("probability"),
                "score": node["score"],
                "certainty": node["certainty"],
            })

        if hit_boundary or not det["pageInfo"]["hasNextPage"]:
            break
        cursor = det["pageInfo"]["endCursor"]

        if (page_num + 1) % 10 == 0:
            print(f"  Fetched {len(all_nodes):,} detections so far (page {page_num + 1})...")

    if not all_nodes:
        return pl.DataFrame(
            schema={
                "id": pl.Utf8,
                "timestamp": pl.Utf8,
                "speciesId": pl.Utf8,
                "commonName": pl.Utf8,
                "scientificName": pl.Utf8,
                "confidence": pl.Float64,
                "probability": pl.Float64,
                "score": pl.Float64,
                "certainty": pl.Utf8,
            }
        )

    return pl.DataFrame(all_nodes).with_columns(
        pl.col("timestamp").str.to_datetime("%+")
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kelvin_to_fahrenheit(k: float) -> float:
    """Convert Kelvin to Fahrenheit."""
    return (k - 273.15) * 9 / 5 + 32


def kelvin_to_celsius(k: float) -> float:
    """Convert Kelvin to Celsius."""
    return k - 273.15
