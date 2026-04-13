from __future__ import annotations

import os
from typing import Any

import requests

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

TMDB_GENRE_ID_TO_NAME: dict[int, str] = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}

GENRE_NAME_ALIASES: dict[str, str] = {
    "science fiction": "Sci-Fi",
    "sci fi": "Sci-Fi",
    "sci-fi": "Sci-Fi",
    "tv movie": "Drama",
}


def get_read_access_token() -> str | None:
    t = (os.getenv("TMDB_READ_ACCESS_TOKEN") or "").strip()
    return t or None


def get_api_key() -> str | None:
    key = (os.getenv("TMDB_API_KEY") or "").strip()
    return key or None


def tmdb_is_configured() -> bool:
    return bool(get_read_access_token() or get_api_key())


def _tmdb_headers() -> dict[str, str]:
    # Prefer API key when both are set: a stale/invalid Bearer token should not
    # override a valid v3 api_key (common misconfiguration → 401 on all TMDB calls).
    if get_api_key():
        return {"Accept": "application/json"}
    token = get_read_access_token()
    if token:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    return {"Accept": "application/json"}


def _params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    key = get_api_key()
    if key:
        p = {"api_key": key}
        if extra:
            p.update(extra)
        return p
    if get_read_access_token():
        return dict(extra or {})
    raise RuntimeError("Set TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY")


def tmdb_search_movies(query: str, page: int = 1) -> dict[str, Any]:
    r = requests.get(
        f"{TMDB_BASE}/search/movie",
        params=_params({"query": query, "page": page}),
        headers=_tmdb_headers(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def tmdb_popular_movies(page: int = 1) -> dict[str, Any]:
    """Paged list from GET /movie/popular (useful for bulk DB seeding)."""
    r = requests.get(
        f"{TMDB_BASE}/movie/popular",
        params=_params({"page": page}),
        headers=_tmdb_headers(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def tmdb_movie_with_credits(tmdb_id: int) -> dict[str, Any]:
    r = requests.get(
        f"{TMDB_BASE}/movie/{tmdb_id}",
        params=_params({"append_to_response": "credits"}),
        headers=_tmdb_headers(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def poster_url(path: str | None) -> str | None:
    if not path:
        return None
    path = str(path).strip()
    if path.startswith("http"):
        return path
    return f"{IMAGE_BASE}{path}"


def tmdb_genre_names(genre_ids: list[int] | None) -> list[str]:
    if not genre_ids:
        return []
    out = []
    for gid in genre_ids:
        name = TMDB_GENRE_ID_TO_NAME.get(int(gid))
        if name:
            out.append(name)
    return out


def resolve_db_genre_name(tmdb_genre_ids: list[int] | None, db_genres: list[dict]) -> tuple[int | None, str | None, list[str]]:
    names = tmdb_genre_names(tmdb_genre_ids)
    if not names and tmdb_genre_ids:
        names = [str(g) for g in tmdb_genre_ids]
    by_lower = {g["genre_name"].lower(): g for g in db_genres}
    primary_name = names[0] if names else None
    genre_id = None
    resolved_primary = primary_name
    if primary_name:
        lookup = primary_name.lower()
        lookup = GENRE_NAME_ALIASES.get(lookup, lookup)
        row = by_lower.get(lookup)
        if row:
            genre_id = row["genre_id"]
            resolved_primary = row["genre_name"]
        else:
            for g in db_genres:
                if g["genre_name"].lower() in lookup or lookup in g["genre_name"].lower():
                    genre_id = g["genre_id"]
                    resolved_primary = g["genre_name"]
                    break
    return genre_id, resolved_primary, names


def format_tmdb_search_result(item: dict[str, Any]) -> dict[str, Any]:
    tid = int(item["id"])
    year = None
    rd = item.get("release_date") or ""
    if rd and len(rd) >= 4:
        try:
            year = int(rd[:4])
        except ValueError:
            year = None
    gnames = tmdb_genre_names(item.get("genre_ids") or [])
    return {
        "tmdb_id": tid,
        "title": item.get("title") or "",
        "release_year": year,
        "overview": (item.get("overview") or "").strip(),
        "poster_url": poster_url(item.get("poster_path")),
        "genre_names": gnames,
        "genre_name": gnames[0] if gnames else None,
        "source": "tmdb",
    }


def format_movie_detail_for_api(
    detail: dict[str, Any],
    *,
    movie_id: int,
    genre_name: str | None,
    genre_names: list[str],
    average_rating: float = 0.0,
) -> dict[str, Any]:
    rd = detail.get("release_date") or ""
    year = None
    if rd and len(rd) >= 4:
        try:
            year = int(rd[:4])
        except ValueError:
            year = None
    runtime = detail.get("runtime")
    lang = detail.get("original_language") or ""
    lang_label = lang.upper() if lang else None
    return {
        "movie_id": movie_id,
        "title": detail.get("title") or "",
        "media_type": "movie",
        "release_year": year,
        "runtime": int(runtime) if runtime is not None else None,
        "language": lang_label,
        "description": (detail.get("overview") or "").strip(),
        "poster_url": poster_url(detail.get("poster_path")),
        "genre_name": genre_name,
        "genre_names": genre_names or ([genre_name] if genre_name else []),
        "average_rating": float(average_rating),
        "tmdb_id": int(detail.get("id", 0)),
    }


def credits_for_db(detail: dict[str, Any], limit_cast: int = 12) -> tuple[list[dict], list[dict]]:
    credits = detail.get("credits") or {}
    cast_out = []
    for c in (credits.get("cast") or [])[:limit_cast]:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        cast_out.append(
            {
                "name": name,
                "role": "Actor",
                "character_name": (c.get("character") or "").strip() or None,
            }
        )
    crew_out = []
    for c in credits.get("crew") or []:
        job = (c.get("job") or "").strip()
        if job != "Director":
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        crew_out.append({"name": name, "role": "Director", "character_name": None})
        break
    return cast_out, crew_out


def build_movie_insert_row(detail: dict[str, Any], genre_id: int | None) -> dict[str, Any]:
    rd = detail.get("release_date") or ""
    year = None
    if rd and len(rd) >= 4:
        try:
            year = int(rd[:4])
        except ValueError:
            year = None
    runtime = detail.get("runtime")
    lang = detail.get("original_language") or ""
    return {
        "title": (detail.get("title") or "").strip(),
        "release_year": year,
        "runtime": int(runtime) if runtime is not None else None,
        "language": lang.upper() if lang else None,
        "description": (detail.get("overview") or "").strip() or None,
        "poster_url": poster_url(detail.get("poster_path")),
        "genre_id": genre_id,
    }
