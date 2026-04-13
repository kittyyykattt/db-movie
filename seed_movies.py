#!/usr/bin/env python3
"""
Bulk-import movies from TMDB's /movie/popular list into Postgres.

Use for Milestone-style initial datasets (~150–200 movies). Requires DATABASE_URL,
TMDB_API_KEY (or TMDB_READ_ACCESS_TOKEN), and a reachable DB with your schema.

  python3 seed_movies.py --count 200
"""

from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Import popular TMDB movies into Postgres.")
    parser.add_argument(
        "--count",
        type=int,
        default=200,
        help="Stop after this many successful new inserts (default 200)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Seconds to sleep after each import (rate limiting; default 0.35)",
    )
    args = parser.parse_args()

    if not (os.getenv("DATABASE_URL") or "").strip():
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    from tmdb_client import tmdb_is_configured, tmdb_popular_movies

    if not tmdb_is_configured():
        print("Set TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN.", file=sys.stderr)
        return 1

    from app import get_genres
    from movie_import import import_tmdb_movie

    genres = get_genres()
    if not genres:
        print("No genres from database; check DB connection and Genres table.", file=sys.stderr)
        return 1

    target = max(1, min(args.count, 500))
    imported = 0
    existed = 0
    errors = 0
    page = 1
    pages_no_new = 0

    while imported < target and page <= 500:
        try:
            data = tmdb_popular_movies(page)
        except Exception as e:
            print(f"TMDB popular page {page} failed: {e}", file=sys.stderr)
            return 1

        results = data.get("results") or []
        if not results:
            print("No more TMDB /movie/popular results.", file=sys.stderr)
            break

        new_this_page = 0
        for item in results:
            if imported >= target:
                break
            tid = int(item["id"])
            try:
                res = import_tmdb_movie(tid, genres)
            except Exception as e:
                errors += 1
                print(f"[error] tmdb_id={tid}: {e}", file=sys.stderr)
                time.sleep(args.delay)
                continue

            if res.get("already_existed"):
                existed += 1
                print(f"[already in DB] {res.get('title')!r} (tmdb {tid})")
            else:
                new_this_page += 1
                imported += 1
                print(f"[{imported}/{target}] {res.get('title')!r} -> movie_id={res.get('movie_id')}")

            time.sleep(args.delay)

        if new_this_page == 0 and imported < target:
            pages_no_new += 1
            if pages_no_new >= 5:
                print(
                    "Stopping: 5 pages in a row with no new inserts "
                    "(list likely already imported or exhausted).",
                    file=sys.stderr,
                )
                break
        else:
            pages_no_new = 0

        page += 1

    print(
        f"Done. new_inserts={imported} (target {target}), "
        f"already_existed_skipped={existed}, tmdb_errors={errors}"
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
