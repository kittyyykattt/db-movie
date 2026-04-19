#!/usr/bin/env python3
"""
One-time script to update Movies.genre_id for all movies with NULL genre.
Searches TMDB by title+year, gets genre, and updates the database.

Usage:
    python3 fix_genres.py
"""

import os
import sys
import time

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

from tmdb_client import tmdb_search_movies, TMDB_GENRE_ID_TO_NAME, GENRE_NAME_ALIASES

load_dotenv()


def get_connection():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set in .env")
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def get_genres():
    """Fetch all genres from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT genre_id, genre_name FROM "Genres" ORDER BY genre_id')
            return [dict(row) for row in cur.fetchall()]


def get_movies_without_genre():
    """Fetch all movies with NULL genre_id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT movie_id, title, release_year 
                FROM "Movies" 
                WHERE genre_id IS NULL
                ORDER BY movie_id
            ''')
            return [dict(row) for row in cur.fetchall()]


def search_tmdb_for_genre(title, release_year):
    """Search TMDB for a movie and return genre_ids."""
    try:
        result = tmdb_search_movies(title, page=1)
        results = result.get("results", [])
        
        if not results:
            return None
        
        # Try to find exact match by year
        for item in results:
            rd = item.get("release_date", "")
            if rd and release_year:
                try:
                    tmdb_year = int(rd[:4])
                    if tmdb_year == release_year:
                        return item.get("genre_ids", [])
                except (ValueError, IndexError):
                    pass
        
        # Fall back to first result
        return results[0].get("genre_ids", [])
        
    except Exception as e:
        print(f"    TMDB search failed: {e}")
        return None


def match_genre_to_db(tmdb_genre_ids, db_genres):
    """Match TMDB genre IDs to database genre, with proper alias handling."""
    if not tmdb_genre_ids:
        return None, None
    
    # Build lowercase lookup dict
    by_lower = {g["genre_name"].lower(): g for g in db_genres}
    
    # Try each TMDB genre in order until we find a match
    for gid in tmdb_genre_ids:
        tmdb_name = TMDB_GENRE_ID_TO_NAME.get(gid)
        if not tmdb_name:
            continue
        
        # Apply alias mapping and lowercase for lookup
        lookup = tmdb_name.lower()
        lookup = GENRE_NAME_ALIASES.get(lookup, lookup).lower()  # Lowercase after alias!
        
        # Try exact match
        if lookup in by_lower:
            row = by_lower[lookup]
            return row["genre_id"], row["genre_name"]
        
        # Try partial match
        for g in db_genres:
            gname = g["genre_name"].lower()
            if gname in lookup or lookup in gname:
                return g["genre_id"], g["genre_name"]
    
    return None, None


def update_movie_genre(movie_id, genre_id):
    """Update a movie's genre_id in the database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Movies" SET genre_id = %s WHERE movie_id = %s',
                (genre_id, movie_id)
            )
            conn.commit()


def main():
    print("=" * 50)
    print("Fix Genres Script")
    print("=" * 50)
    print()
    
    # Get genres from database
    db_genres = get_genres()
    if not db_genres:
        print("ERROR: No genres found in database. Populate Genres table first.")
        sys.exit(1)
    print(f"Found {len(db_genres)} genres in database")
    
    # Get movies without genre
    movies = get_movies_without_genre()
    if not movies:
        print("All movies already have genre_id assigned!")
        sys.exit(0)
    print(f"Found {len(movies)} movies without genre_id")
    print()
    
    # Process each movie
    updated = 0
    failed = 0
    
    for i, movie in enumerate(movies, 1):
        movie_id = movie["movie_id"]
        title = movie["title"]
        year = movie["release_year"]
        
        print(f"[{i}/{len(movies)}] {title} ({year})")
        
        # Search TMDB
        tmdb_genre_ids = search_tmdb_for_genre(title, year)
        
        if not tmdb_genre_ids:
            print(f"    ❌ No genre found on TMDB")
            failed += 1
            continue
        
        # Resolve to database genre
        genre_id, genre_name = match_genre_to_db(tmdb_genre_ids, db_genres)
        
        if genre_id is None:
            print(f"    ❌ TMDB genres {tmdb_genre_ids} didn't match any DB genre")
            failed += 1
            continue
        
        # Update database
        update_movie_genre(movie_id, genre_id)
        print(f"    Set genre_id={genre_id} ({genre_name})")
        updated += 1
        
        # Rate limit to avoid hitting TMDB too hard
        time.sleep(0.25)
    
    print()
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    print(f"  Updated: {updated}")
    print(f"  Failed:  {failed}")
    print(f"  Total:   {len(movies)}")


if __name__ == "__main__":
    main()
