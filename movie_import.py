from __future__ import annotations

import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from tmdb_client import (
    build_movie_insert_row,
    credits_for_db,
    resolve_db_genre_name,
    tmdb_movie_with_credits,
)


def _connect():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def find_movie_by_title_year(cur, title: str, release_year: int | None) -> int | None:
    cur.execute(
        """
        SELECT movie_id FROM "Movies"
        WHERE title = %s AND (release_year IS NOT DISTINCT FROM %s)
        LIMIT 1
        """,
        (title, release_year),
    )
    row = cur.fetchone()
    return int(row["movie_id"]) if row else None


def get_or_create_person_id(cur, name: str) -> int:
    cur.execute('SELECT person_id FROM "People" WHERE name = %s', (name,))
    row = cur.fetchone()
    if row:
        return int(row["person_id"])
    cur.execute('INSERT INTO "People" (name) VALUES (%s) RETURNING person_id', (name,))
    return int(cur.fetchone()["person_id"])


def insert_credit_if_missing(cur, movie_id: int, person_id: int, role: str, character_name: str | None) -> None:
    cur.execute(
        """
        INSERT INTO "Credits" (movie_id, person_id, role, character_name)
        SELECT %s, %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM "Credits" c
            WHERE c.movie_id = %s AND c.person_id = %s AND c.role = %s
        )
        """,
        (movie_id, person_id, role, character_name, movie_id, person_id, role),
    )


def import_tmdb_movie(tmdb_id: int, db_genres: list[dict[str, Any]]) -> dict[str, Any]:
    detail = tmdb_movie_with_credits(tmdb_id)
    gids = [int(x) for x in (detail.get("genre_ids") or [])]
    genre_id, genre_name, genre_names = resolve_db_genre_name(gids, db_genres)
    row = build_movie_insert_row(detail, genre_id)
    title = row["title"]
    if not title:
        raise ValueError("TMDB movie has no title")

    cast_rows, crew_rows = credits_for_db(detail)

    with _connect() as conn:
        with conn.cursor() as cur:
            existing = find_movie_by_title_year(cur, title, row["release_year"])
            if existing:
                conn.commit()
                return {
                    "movie_id": existing,
                    "already_existed": True,
                    "title": title,
                    "genre_name": genre_name,
                    "genre_names": genre_names,
                }

            cur.execute(
                """
                INSERT INTO "Movies" (title, release_year, runtime, language, description, poster_url, genre_id)
                VALUES (%(title)s, %(release_year)s, %(runtime)s, %(language)s, %(description)s, %(poster_url)s, %(genre_id)s)
                RETURNING movie_id
                """,
                row,
            )
            movie_id = int(cur.fetchone()["movie_id"])

            for c in crew_rows + cast_rows:
                pid = get_or_create_person_id(cur, c["name"])
                insert_credit_if_missing(cur, movie_id, pid, c["role"], c["character_name"])

            conn.commit()

    return {
        "movie_id": movie_id,
        "already_existed": False,
        "title": title,
        "genre_name": genre_name,
        "genre_names": genre_names,
    }


def preview_tmdb_import(tmdb_id: int, db_genres: list[dict[str, Any]]) -> dict[str, Any]:
    detail = tmdb_movie_with_credits(tmdb_id)
    gids = [int(x) for x in (detail.get("genre_ids") or [])]
    genre_id, genre_name, genre_names = resolve_db_genre_name(gids, db_genres)
    insert_row = build_movie_insert_row(detail, genre_id)
    cast_rows, crew_rows = credits_for_db(detail)
    return {
        "tmdb_id": tmdb_id,
        "movie_row": insert_row,
        "credits": {"cast": cast_rows, "crew": crew_rows},
        "genre_name": genre_name,
        "genre_names": genre_names,
    }
