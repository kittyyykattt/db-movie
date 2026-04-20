#!/usr/bin/env python3
"""
Insert standard movie genres into an empty "Genres" table so imports and fix_genres.py work.

Run once after creating the schema:
    python3 seed_genres.py

Requires DATABASE_URL. Safe to run again: skips if the table already has rows.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
import psycopg2


# Names aligned with tmdb_client.TMDB_GENRE_ID_TO_NAME / movie_import.resolve_db_genre_name
GENRE_NAMES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
]


def main() -> int:
    load_dotenv()
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Genres"')
            n = cur.fetchone()[0]
            if n > 0:
                print(f'Genres table already has {n} row(s). Nothing to do.')
                return 0

            for name in GENRE_NAMES:
                cur.execute('INSERT INTO "Genres" (genre_name) VALUES (%s)', (name,))
            conn.commit()
            print(f"Inserted {len(GENRE_NAMES)} genres.")
            return 0
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
