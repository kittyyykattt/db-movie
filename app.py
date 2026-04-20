import os
import secrets

import jwt
import psycopg2.errors
from jwt.exceptions import InvalidTokenError
from flask import Flask, render_template, request, jsonify, redirect, url_for
from tmdb_client import format_tmdb_search_result, tmdb_is_configured, tmdb_search_movies
from movie_import import import_tmdb_movie, preview_tmdb_import
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

DATABASE_URL = os.getenv("DATABASE_URL")

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_ANON_KEY = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
SUPABASE_JWT_SECRET = (os.getenv("SUPABASE_JWT_SECRET") or "").strip()


def supabase_auth_env_ready():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_JWT_SECRET)


def _supabase_jwt_issuer():
    if not SUPABASE_URL:
        return None
    return f"{SUPABASE_URL}/auth/v1"


def verify_supabase_access_token(token: str) -> dict:
    if not SUPABASE_JWT_SECRET:
        raise RuntimeError("SUPABASE_JWT_SECRET is not set")
    issuer = _supabase_jwt_issuer()
    common = {"algorithms": ["HS256"], "audience": "authenticated"}
    try:
        if issuer:
            return jwt.decode(token, SUPABASE_JWT_SECRET, issuer=issuer, **common)
        return jwt.decode(token, SUPABASE_JWT_SECRET, **common)
    except InvalidTokenError:
        if issuer:
            return jwt.decode(token, SUPABASE_JWT_SECRET, **common)
        raise


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def db_get_user_by_id(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT user_id, email, password_hash, supabase_uid, username FROM "Users" WHERE user_id = %s',
                (user_id,),
            )
            return cur.fetchone()


def db_get_user_by_email(email):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT user_id, email, password_hash, supabase_uid, username FROM "Users" WHERE LOWER(email) = LOWER(%s)',
                (email,),
            )
            return cur.fetchone()


def db_create_user(email, password_hash):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Users" (email, password_hash, username, join_date) VALUES (%s, %s, %s, CURRENT_DATE) RETURNING user_id',
                (email, password_hash, email.split('@')[0])
            )
            user_id = cur.fetchone()["user_id"]
            conn.commit()
            return user_id


def db_get_genres():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT genre_id, genre_name FROM "Genres" ORDER BY genre_name')
            return cur.fetchall()


def db_get_movie_by_id(movie_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT 
                    m.movie_id, m.title, m.release_year, m.runtime, 
                    m.language, m.description, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(AVG(r.rating_value), 0) as average_rating
                FROM "Movies" m
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id
                WHERE m.movie_id = %s
                GROUP BY m.movie_id, g.genre_name
            ''', (movie_id,))
            return cur.fetchone()


def db_get_credits(movie_id, role=None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if role:
                cur.execute('''
                    SELECT p.name, c.role, c.character_name
                    FROM "Credits" c
                    JOIN "People" p ON c.person_id = p.person_id
                    WHERE c.movie_id = %s AND c.role = %s
                    ORDER BY c.credit_id
                ''', (movie_id, role))
            else:
                cur.execute('''
                    SELECT p.name, c.role, c.character_name
                    FROM "Credits" c
                    JOIN "People" p ON c.person_id = p.person_id
                    WHERE c.movie_id = %s
                    ORDER BY c.credit_id
                ''', (movie_id,))
            return cur.fetchall()


MOVIE_BROWSE_BASE_FROM = """
        FROM "Movies" m
        LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
        LEFT JOIN (
            SELECT movie_id, AVG(rating_value) as avg_rating
            FROM "Ratings"
            GROUP BY movie_id
        ) avg_r ON m.movie_id = avg_r.movie_id
"""

MOVIE_BROWSE_SELECT_DISTINCT = """
        SELECT DISTINCT
            m.movie_id, m.title, m.release_year, m.runtime,
            m.language, m.description, m.poster_url, m.genre_id,
            g.genre_name,
            COALESCE(avg_r.avg_rating, 0) as average_rating,
            (
                SELECT p.name FROM "Credits" c_d
                JOIN "People" p ON c_d.person_id = p.person_id
                WHERE c_d.movie_id = m.movie_id AND c_d.role = 'Director'
                LIMIT 1
            ) AS director
"""


def _movie_browse_filter_parts(
    q="",
    director="",
    actor="",
    genre=None,
    year_from=None,
    year_to=None,
    rating_min=None,
    rating_max=None,
    language="",
    runtime_min=None,
    runtime_max=None,
):
    """Shared joins, WHERE, HAVING, and params for browse list + count queries."""
    genre = genre or []
    params = []
    joins = []
    conditions = []

    if q:
        conditions.append("m.title ILIKE %s")
        params.append(f"%{q}%")

    if director:
        joins.append(
            """
            JOIN "Credits" c_dir ON m.movie_id = c_dir.movie_id AND c_dir.role = 'Director'
            JOIN "People" p_dir ON c_dir.person_id = p_dir.person_id
        """
        )
        conditions.append("p_dir.name ILIKE %s")
        params.append(f"%{director}%")

    if actor:
        joins.append(
            """
            JOIN "Credits" c_act ON m.movie_id = c_act.movie_id AND c_act.role = 'Actor'
            JOIN "People" p_act ON c_act.person_id = p_act.person_id
        """
        )
        conditions.append("p_act.name ILIKE %s")
        params.append(f"%{actor}%")

    genre_ints = []
    for g in genre or []:
        try:
            genre_ints.append(int(g))
        except (TypeError, ValueError):
            continue
    if genre_ints:
        placeholders = ", ".join(["%s"] * len(genre_ints))
        conditions.append(f"m.genre_id IN ({placeholders})")
        params.extend(genre_ints)

    if year_from:
        conditions.append("m.release_year >= %s")
        params.append(int(year_from))
    if year_to:
        conditions.append("m.release_year <= %s")
        params.append(int(year_to))

    if runtime_min:
        conditions.append("m.runtime >= %s")
        params.append(int(runtime_min))
    if runtime_max:
        conditions.append("m.runtime <= %s")
        params.append(int(runtime_max))

    if language:
        conditions.append("m.language ILIKE %s")
        params.append(f"%{language}%")

    having_conditions = []
    if rating_min:
        having_conditions.append("COALESCE(avg_r.avg_rating, 0) >= %s")
        params.append(float(rating_min))
    if rating_max:
        having_conditions.append("COALESCE(avg_r.avg_rating, 0) <= %s")
        params.append(float(rating_max))

    return joins, conditions, having_conditions, params


def _movie_browse_order_clause(sort_by):
    sort_map = {
        "year_desc": "m.release_year DESC",
        "year_asc": "m.release_year ASC",
        "rating_desc": "average_rating DESC",
        "rating_asc": "average_rating ASC",
        "runtime_desc": "m.runtime DESC",
        "runtime_asc": "m.runtime ASC",
        "title_asc": "m.title ASC",
    }
    return sort_map.get(sort_by, "m.release_year DESC")


def db_count_search_movies(
    q="",
    director="",
    actor="",
    genre=None,
    year_from=None,
    year_to=None,
    rating_min=None,
    rating_max=None,
    language="",
    runtime_min=None,
    runtime_max=None,
):
    joins, conditions, having_conditions, params = _movie_browse_filter_parts(
        q=q,
        director=director,
        actor=actor,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
    )
    inner = "SELECT DISTINCT m.movie_id " + MOVIE_BROWSE_BASE_FROM
    for join in joins:
        inner += join
    if conditions:
        inner += " WHERE " + " AND ".join(conditions)
    if having_conditions:
        inner += " HAVING " + " AND ".join(having_conditions)
    count_sql = f"SELECT COUNT(*) AS c FROM ({inner}) AS browse_cnt"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            row = cur.fetchone()
            return int(row["c"]) if row and row.get("c") is not None else 0


def db_search_movies(
    q="",
    director="",
    actor="",
    genre=None,
    year_from=None,
    year_to=None,
    rating_min=None,
    rating_max=None,
    language="",
    runtime_min=None,
    runtime_max=None,
    sort_by="",
    limit=100,
    offset=0,
):
    joins, conditions, having_conditions, params = _movie_browse_filter_parts(
        q=q,
        director=director,
        actor=actor,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
    )
    full_query = MOVIE_BROWSE_SELECT_DISTINCT + MOVIE_BROWSE_BASE_FROM
    for join in joins:
        full_query += join

    if conditions:
        full_query += " WHERE " + " AND ".join(conditions)

    if having_conditions:
        full_query += " HAVING " + " AND ".join(having_conditions)

    order = _movie_browse_order_clause(sort_by)
    full_query += f" ORDER BY {order}"
    full_query += f" LIMIT {int(limit)}"
    if int(offset) > 0:
        full_query += f" OFFSET {int(offset)}"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(full_query, params)
            return cur.fetchall()


def db_get_user_rating(user_id, movie_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT rating_value, rating_date
                FROM "Ratings"
                WHERE user_id = %s AND movie_id = %s
            ''', (user_id, movie_id))
            return cur.fetchone()


def db_set_user_rating(user_id, movie_id, rating_value):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO "Ratings" (user_id, movie_id, rating_value, rating_date)
                VALUES (%s, %s, %s, CURRENT_DATE)
                ON CONFLICT (user_id, movie_id) 
                DO UPDATE SET rating_value = %s, rating_date = CURRENT_DATE
                RETURNING rating_id
            ''', (user_id, movie_id, rating_value, rating_value))
            result = cur.fetchone()
            conn.commit()
            return result


def db_delete_user_rating(user_id, movie_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "Ratings" WHERE user_id = %s AND movie_id = %s',
                (user_id, movie_id),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted


def db_update_username(user_id, username):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Users" SET username = %s WHERE user_id = %s',
                (username, user_id),
            )
            conn.commit()
            return cur.rowcount


def db_get_user_ratings_history(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT 
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.poster_url,
                    g.genre_name,
                    r.rating_value, r.rating_date,
                    COALESCE(avg_r.avg_rating, 0) as average_rating
                FROM "Ratings" r
                JOIN "Movies" m ON r.movie_id = m.movie_id
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN (
                    SELECT movie_id, AVG(rating_value) as avg_rating
                    FROM "Ratings"
                    GROUP BY movie_id
                ) avg_r ON m.movie_id = avg_r.movie_id
                WHERE r.user_id = %s
                ORDER BY r.rating_date DESC
            ''', (user_id,))
            return cur.fetchall()


def db_ensure_user_for_supabase(email: str, supabase_uid: str):
    """Create or link a Users row for a Supabase Auth identity."""
    email = str(email or "").strip().lower()
    supabase_uid = str(supabase_uid or "").strip()
    if not email or not supabase_uid:
        raise ValueError("email and Supabase user id are required")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT user_id, email, password_hash, supabase_uid, username FROM "Users" WHERE supabase_uid = %s',
                (supabase_uid,),
            )
            row = cur.fetchone()
            if row:
                return row
            cur.execute(
                'SELECT user_id, email, password_hash, supabase_uid, username FROM "Users" WHERE LOWER(email) = LOWER(%s)',
                (email,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    'UPDATE "Users" SET supabase_uid = %s WHERE user_id = %s',
                    (supabase_uid, row["user_id"]),
                )
                conn.commit()
                cur.execute(
                    'SELECT user_id, email, password_hash, supabase_uid, username FROM "Users" WHERE user_id = %s',
                    (row["user_id"],),
                )
                return cur.fetchone()
            password_hash = generate_password_hash(secrets.token_urlsafe(32))
            cur.execute(
                """
                INSERT INTO "Users" (email, password_hash, username, join_date, supabase_uid)
                VALUES (%s, %s, %s, CURRENT_DATE, %s)
                RETURNING user_id, email, password_hash, supabase_uid, username
                """,
                (email, password_hash, email.split("@")[0], supabase_uid),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def db_touch_email_verified(user_id: int, verified: bool):
    if not verified or not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE "Users"
                    SET email_verified_at = COALESCE(email_verified_at, CURRENT_TIMESTAMP)
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                conn.commit()
    except (psycopg2.errors.UndefinedColumn, psycopg2.errors.UndefinedTable):
        pass


def db_get_recommendations(user_id, limit=12):
    """Advanced multi-factor recommendation engine with weighted scoring."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) as cnt FROM "Ratings" WHERE user_id = %s', (user_id,))
            if cur.fetchone()["cnt"] == 0:
                cur.execute('''
                    SELECT 
                        m.movie_id, m.title, m.release_year, m.runtime,
                        m.language, m.poster_url, m.genre_id,
                        g.genre_name,
                        COALESCE(AVG(r.rating_value), 0) as average_rating,
                        0 as genre_score, 0 as creator_score,
                        COALESCE(ROUND(AVG(r.rating_value) * 6), 0) as community_score
                    FROM "Movies" m
                    LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                    LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id
                    GROUP BY m.movie_id, g.genre_name
                    ORDER BY average_rating DESC
                    LIMIT %s
                ''', (limit,))
                return cur.fetchall()
            
            cur.execute('''
                SELECT 
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(AVG(r.rating_value), 0) as average_rating,
                    
                    CASE 
                        WHEN m.genre_id IN (
                            SELECT m2.genre_id
                            FROM "Ratings" r2
                            JOIN "Movies" m2 ON r2.movie_id = m2.movie_id
                            WHERE r2.user_id = %s AND m2.genre_id IS NOT NULL
                            GROUP BY m2.genre_id
                            HAVING AVG(r2.rating_value) >= 3.5
                        ) THEN 40
                        ELSE 0
                    END AS genre_score,
                    
                    CASE 
                        WHEN EXISTS (
                            SELECT 1 
                            FROM "Credits" c1
                            JOIN "Credits" c2 ON c1.person_id = c2.person_id
                            JOIN "Ratings" r3 ON c2.movie_id = r3.movie_id
                            WHERE c1.movie_id = m.movie_id
                                AND r3.user_id = %s 
                                AND r3.rating_value >= 4.5
                        ) THEN 30
                        ELSE 0
                    END AS creator_score,
                    
                    COALESCE(ROUND(AVG(r.rating_value) * 6), 0) AS community_score

                FROM "Movies" m
                JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id

                WHERE m.movie_id NOT IN (
                    SELECT movie_id FROM "Ratings" WHERE user_id = %s
                )

                GROUP BY m.movie_id, m.title, m.release_year, m.runtime,
                         m.language, m.poster_url, m.genre_id, g.genre_name

                ORDER BY 
                    (CASE WHEN m.genre_id IN (
                        SELECT m2.genre_id FROM "Ratings" r2 
                        JOIN "Movies" m2 ON r2.movie_id = m2.movie_id
                        WHERE r2.user_id = %s AND m2.genre_id IS NOT NULL
                        GROUP BY m2.genre_id HAVING AVG(r2.rating_value) >= 3.5
                    ) THEN 40 ELSE 0 END) +
                    (CASE WHEN EXISTS (
                        SELECT 1 FROM "Credits" c1
                        JOIN "Credits" c2 ON c1.person_id = c2.person_id
                        JOIN "Ratings" r3 ON c2.movie_id = r3.movie_id
                        WHERE c1.movie_id = m.movie_id AND r3.user_id = %s AND r3.rating_value >= 4.5
                    ) THEN 30 ELSE 0 END) +
                    COALESCE(ROUND(AVG(r.rating_value) * 6), 0) DESC

                LIMIT %s
            ''', (user_id, user_id, user_id, user_id, user_id, limit))
            return cur.fetchall()


def db_get_spotlight_recommendations(limit=12):
    """Catalog-wide picks for guests or fallback UI; IDs match the database."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(AVG(r.rating_value), 0) as average_rating
                FROM "Movies" m
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id
                GROUP BY m.movie_id, g.genre_name
                ORDER BY average_rating DESC NULLS LAST, m.release_year DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


def db_similar_movies(movie_id, limit=10):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT genre_id FROM "Movies" WHERE movie_id = %s', (movie_id,))
            row = cur.fetchone()
            if not row or row.get("genre_id") is None:
                return []
            gid = row["genre_id"]
            cur.execute(
                """
                SELECT
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.description, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(avg_r.avg_rating, 0) AS average_rating,
                    (
                        SELECT p.name FROM "Credits" c_d
                        JOIN "People" p ON c_d.person_id = p.person_id
                        WHERE c_d.movie_id = m.movie_id AND c_d.role = 'Director'
                        LIMIT 1
                    ) AS director
                FROM "Movies" m
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN (
                    SELECT movie_id, AVG(rating_value) AS avg_rating
                    FROM "Ratings"
                    GROUP BY movie_id
                ) avg_r ON m.movie_id = avg_r.movie_id
                WHERE m.genre_id = %s AND m.movie_id != %s
                ORDER BY average_rating DESC NULLS LAST, m.release_year DESC NULLS LAST
                LIMIT %s
                """,
                (gid, movie_id, limit),
            )
            return cur.fetchall()


def db_user_top_genre_ids(user_id, limit=4):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.genre_id, AVG(r.rating_value) AS avg_genre_rating
                FROM "Ratings" r
                JOIN "Movies" m ON r.movie_id = m.movie_id
                WHERE r.user_id = %s AND m.genre_id IS NOT NULL
                GROUP BY m.genre_id
                ORDER BY avg_genre_rating DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [int(r["genre_id"]) for r in cur.fetchall()]


def db_favorite_genre_movies(genre_ids, limit=24):
    if not genre_ids:
        return []
    placeholders = ", ".join(["%s"] * len(genre_ids))
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.description, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(avg_r.avg_rating, 0) AS average_rating,
                    (
                        SELECT p.name FROM "Credits" c_d
                        JOIN "People" p ON c_d.person_id = p.person_id
                        WHERE c_d.movie_id = m.movie_id AND c_d.role = 'Director'
                        LIMIT 1
                    ) AS director
                FROM "Movies" m
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN (
                    SELECT movie_id, AVG(rating_value) AS avg_rating
                    FROM "Ratings"
                    GROUP BY movie_id
                ) avg_r ON m.movie_id = avg_r.movie_id
                WHERE m.genre_id IN ({placeholders})
                ORDER BY average_rating DESC NULLS LAST, m.release_year DESC NULLS LAST
                LIMIT %s
                """,
                (*genre_ids, limit),
            )
            return cur.fetchall()


def _use_db():
    return bool(DATABASE_URL)


def _normalize_poster_url(url):
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    if u.startswith("//"):
        return "https:" + u
    return u


def _serialize_db_search_row(row):
    r = dict(row)
    ar = r.get("average_rating")
    try:
        r["average_rating"] = float(ar) if ar is not None else 0.0
    except (TypeError, ValueError):
        r["average_rating"] = 0.0
    gn = r.get("genre_name")
    r["genre_names"] = [gn] if gn else []
    desc = r.get("description")
    r["synopsis"] = (desc or "") if desc is not None else ""
    r["media_type"] = r.get("media_type") if r.get("media_type") else "movie"
    if not r.get("director"):
        r["director"] = ""
    r["poster_url"] = _normalize_poster_url(r.get("poster_url"))
    return r


def _movie_detail_from_db(movie_id):
    try:
        row = db_get_movie_by_id(movie_id)
    except Exception:
        return None
    if not row:
        return None
    r = dict(row)
    try:
        r["average_rating"] = float(r.get("average_rating") or 0)
    except (TypeError, ValueError):
        r["average_rating"] = 0.0
    gn = r.get("genre_name")
    r["genre_names"] = [gn] if gn else []
    r["poster_url"] = _normalize_poster_url(r.get("poster_url"))
    return r


def _recommendation_from_db_row(row, top_genre_ids):
    card = _serialize_db_search_row(row)
    gid = row.get("genre_id")
    overlap = 0
    if top_genre_ids and gid is not None:
        try:
            overlap = 1 if int(gid) in top_genre_ids else 0
        except (TypeError, ValueError):
            overlap = 0
    base = 58 + overlap * 14 + int(card["average_rating"] * 2.2)
    card["match_percentage"] = max(62, min(98, base))
    return card


def _db_search_or_stub(**kwargs):
    media_type = kwargs.pop("media_type", "")
    if _use_db():
        try:
            rows = db_search_movies(**kwargs)
            cards = [_serialize_db_search_row(r) for r in rows]
            mt = (media_type or "").strip().lower()
            if mt in ("movie", "show"):
                cards = [c for c in cards if c.get("media_type") == mt]
            return cards
        except Exception:
            pass
    return _stub_search(media_type=media_type, **kwargs)


def _recommendations_for_home():
    if _use_db():
        try:
            if current_user.is_authenticated:
                uid = int(current_user.id)
                top = db_user_top_genre_ids(uid)
                rows = db_get_recommendations(uid, limit=12)
                return [_recommendation_from_db_row(r, top) for r in rows]
            rows = db_get_spotlight_recommendations(limit=12)
            return [_recommendation_from_db_row(r, []) for r in rows]
        except Exception:
            pass
    return _stub_recommendations()


def _user_top_genres_for_home():
    if current_user.is_authenticated and _use_db():
        try:
            gids = db_user_top_genre_ids(int(current_user.id))
            by_id = {g["genre_id"]: g for g in get_genres()}
            found = [by_id[g] for g in gids if g in by_id]
            if found:
                return found
        except Exception:
            pass
    return _stub_user_top_genres()


def _ensure_genre_ids_for_home_cards(cards):
    """
    Many DB rows have NULL genre_id (legacy seed). Without genre_id / genre_name,
    client-side genre filters cannot match. Assign a stable bucket genre from the
    user's top genres (or the first catalog genres) so filters work until data is backfilled.
    """
    if not cards:
        return cards
    genres_list = get_genres()
    by_gid = {g["genre_id"]: g["genre_name"] for g in genres_list}
    # Must match the same four genres shown as filter pills on the home page.
    gids = [g["genre_id"] for g in _user_top_genres_for_home()[:4]]
    if not gids:
        try:
            if current_user.is_authenticated:
                gids = db_user_top_genre_ids(int(current_user.id), limit=4)
        except Exception:
            gids = []
    if not gids:
        gids = [g["genre_id"] for g in genres_list[:4]]
    if not gids:
        return cards
    n = len(gids)
    for card in cards:
        gid = card.get("genre_id")
        if gid is not None:
            if not card.get("genre_name"):
                card["genre_name"] = by_gid.get(gid, "")
            if not card.get("favorite_genre_match_name"):
                card["favorite_genre_match"] = gid
                card["favorite_genre_match_name"] = by_gid.get(gid, "")
            continue
        mid = int(card.get("movie_id") or 0)
        gid = gids[mid % n]
        nm = by_gid.get(gid, "")
        card["genre_id"] = gid
        card["genre_name"] = nm
        card["favorite_genre_match"] = gid
        card["favorite_genre_match_name"] = nm
    return cards


def _ensure_genre_ids_for_recommendations_cards(cards):
    """
    Recommendations page filters use the full genre catalog. When Movies.genre_id is NULL,
    assign a stable bucket across all genres so pills match card data-genre-id.
    """
    if not cards:
        return cards
    genres_list = get_genres()
    if not genres_list:
        return cards
    by_gid = {g["genre_id"]: g["genre_name"] for g in genres_list}
    gids = [g["genre_id"] for g in genres_list]
    n = len(gids)
    for card in cards:
        gid = card.get("genre_id")
        if gid is not None:
            if not card.get("genre_name"):
                card["genre_name"] = by_gid.get(gid, "")
            continue
        mid = int(card.get("movie_id") or 0)
        gid = gids[mid % n]
        nm = by_gid.get(gid, "")
        card["genre_id"] = gid
        card["genre_name"] = nm
    return cards


def _favorite_genre_recommendations_for_home():
    if current_user.is_authenticated and _use_db():
        try:
            gids = db_user_top_genre_ids(int(current_user.id), limit=4)
            if not gids:
                raise ValueError("no genres")
            rows = db_favorite_genre_movies(gids, limit=24)
            by_gid = {g["genre_id"]: g["genre_name"] for g in get_genres()}
            genre_rank = {gid: idx for idx, gid in enumerate(gids)}
            out = []
            for r in rows:
                card = _serialize_db_search_row(r)
                gid = r.get("genre_id")
                if gid is not None and gid in genre_rank:
                    card["favorite_genre_match"] = gid
                    card["favorite_genre_match_name"] = by_gid.get(gid, "")
                out.append(card)
            if out:
                return _ensure_genre_ids_for_home_cards(out)
        except Exception:
            pass
    if _use_db():
        try:
            rows = db_get_spotlight_recommendations(limit=24)
            out = [_serialize_db_search_row(r) for r in rows]
            return _ensure_genre_ids_for_home_cards(out)
        except Exception:
            pass
    return _stub_favorite_genre_recommendations()


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.unauthorized_handler
def _handle_unauthorized():
    wants_json = request.path.startswith("/api/") or request.is_json or request.accept_mimetypes.best == "application/json"
    if wants_json:
        return jsonify({"error": "login required"}), 401
    return redirect(url_for("index"))


class AppUser(UserMixin):
    def __init__(self, user_id, email, password_hash, supabase_uid=None, username=None):
        self.id = str(user_id)
        self.email = email
        self.password_hash = password_hash
        self.supabase_uid = supabase_uid
        self.username = username

    @staticmethod
    def from_db_row(row):
        if not row:
            return None
        return AppUser(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
            supabase_uid=row.get("supabase_uid"),
            username=row.get("username"),
        )


@login_manager.user_loader
def load_user(user_id):
    row = db_get_user_by_id(int(user_id))
    return AppUser.from_db_row(row)

@app.context_processor
def inject_user():
    if current_user.is_authenticated:
        return {"current_user": current_user}
    return {"current_user": None}


@app.context_processor
def inject_supabase_client():
    return {
        "supabase_enabled": supabase_auth_env_ready(),
        "supabase_client_config": {"url": SUPABASE_URL, "anonKey": SUPABASE_ANON_KEY},
    }


def _read_form_or_json():
    return request.get_json(silent=True) or request.form


def _wants_json_response():
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _normalize_email(raw):
    return str(raw or "").strip().lower()


def _auth_requires_database_json():
    """Register/login need PostgreSQL; return a JSON 503 response if it is not configured."""
    if not DATABASE_URL:
        return jsonify(
            {"error": "Database is not configured. Set DATABASE_URL in your .env and restart the app."}
        ), 503
    return None


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if _wants_json_response():
            return jsonify({"message": "Send POST /register with email and password"}), 200
        return redirect(url_for("index"))

    no_db = _auth_requires_database_json()
    if no_db is not None:
        return no_db

    data = _read_form_or_json()
    email = _normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400

    try:
        existing = db_get_user_by_email(email)
    except Exception:
        return jsonify(
            {"error": "Could not connect to the database. Check DATABASE_URL and that PostgreSQL is running."}
        ), 503
    if existing:
        return jsonify({"error": "email already registered"}), 409

    password_hash = generate_password_hash(password)
    try:
        user_id = db_create_user(email, password_hash)
    except Exception:
        return jsonify(
            {"error": "Could not create your account in the database. Check DATABASE_URL and table setup."}
        ), 503
    user = AppUser(
        user_id=user_id,
        email=email,
        password_hash=password_hash,
        username=email.split("@")[0],
    )
    login_user(user)
    try:
        db_touch_email_verified(user_id, True)
    except Exception:
        pass

    redirect_to = url_for("index")
    if _wants_json_response():
        return jsonify({"ok": True, "redirect_to": redirect_to}), 201
    return redirect(redirect_to)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if _wants_json_response():
            return jsonify({"message": "Send POST /login with email and password"}), 200
        return redirect(url_for("index"))

    no_db = _auth_requires_database_json()
    if no_db is not None:
        return no_db

    data = _read_form_or_json()
    email = _normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    try:
        row = db_get_user_by_email(email)
    except Exception:
        return jsonify(
            {"error": "Could not connect to the database. Check DATABASE_URL and that PostgreSQL is running."}
        ), 503
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    user = AppUser.from_db_row(row)
    login_user(user)
    try:
        db_touch_email_verified(int(user.id), True)
    except Exception:
        pass
    redirect_to = url_for("index")
    if _wants_json_response():
        return jsonify({"ok": True, "redirect_to": redirect_to}), 200
    return redirect(redirect_to)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    if _wants_json_response():
        return jsonify({"ok": True}), 200
    return redirect(url_for("index"))


@app.route("/auth/supabase", methods=["POST"])
def auth_supabase_session():
    if not supabase_auth_env_ready():
        return jsonify({"error": "Supabase auth is not configured on the server"}), 503
    if not DATABASE_URL:
        return jsonify({"error": "database not configured"}), 503
    data = request.get_json(silent=True) or {}
    token = str(data.get("access_token") or "").strip()
    if not token:
        return jsonify({"error": "access_token required"}), 400
    try:
        payload = verify_supabase_access_token(token)
    except InvalidTokenError:
        return jsonify({"error": "invalid or expired token"}), 401
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    sub = str(payload.get("sub") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if not sub:
        return jsonify({"error": "token missing subject"}), 401
    if not email:
        return jsonify({"error": "token missing email"}), 400
    try:
        row = db_ensure_user_for_supabase(email, sub)
    except psycopg2.errors.UndefinedColumn:
        return jsonify(
            {"error": 'Database needs migration: add column "Users".supabase_uid (see schema/add_supabase_uid.sql)'}
        ), 503
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    user = AppUser.from_db_row(row)
    login_user(user)
    email_verified = bool(payload.get("email_verified"))
    try:
        db_touch_email_verified(int(user.id), email_verified)
    except Exception:
        pass
    return jsonify(
        {
            "ok": True,
            "user_id": int(user.id),
            "email": user.email,
            "email_verified": email_verified,
            "redirect_to": url_for("index"),
        }
    )


@app.route("/account")
def account_page():
    ratings = []
    if current_user.is_authenticated and _use_db():
        try:
            ratings = db_get_user_ratings_history(int(current_user.id))
        except Exception:
            ratings = []
    return render_template("account.html", ratings=ratings)


@app.route("/api/me", methods=["PATCH"])
@login_required
def api_update_profile():
    if not _use_db():
        return jsonify({"error": "database not configured"}), 503
    data = request.get_json(silent=True) or {}
    raw = data.get("username")
    if raw is None:
        return jsonify({"error": "username required"}), 400
    username = str(raw).strip()
    if len(username) < 2 or len(username) > 40:
        return jsonify({"error": "username must be 2–40 characters"}), 400
    try:
        db_update_username(int(current_user.id), username)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "username": username})


@app.route("/api/me/ratings", methods=["GET"])
def api_me_ratings():
    if not current_user.is_authenticated:
        return jsonify({"error": "login required"}), 401
    if not _use_db():
        return jsonify([])
    try:
        rows = db_get_user_ratings_history(int(current_user.id))
        out = []
        for r in rows:
            rd = r.get("rating_date")
            out.append(
                {
                    "movie_id": r["movie_id"],
                    "title": r["title"],
                    "release_year": r["release_year"],
                    "poster_url": _normalize_poster_url(r.get("poster_url")),
                    "genre_name": r.get("genre_name"),
                    "rating_value": float(r["rating_value"]) if r.get("rating_value") is not None else None,
                    "rating_date": rd.isoformat() if rd is not None else None,
                    "average_rating": float(r["average_rating"]) if r.get("average_rating") is not None else 0.0,
                }
            )
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _tmdb_parallel_search_results(q: str, search_by: str, limit: int = 15) -> list:
    """TMDB title search for the home page; only runs in title mode (API is movie-by-title)."""
    if not tmdb_is_configured():
        return []
    if (search_by or "").strip().lower() != "title":
        return []
    term = (q or "").strip()
    if len(term) < 2:
        return []
    try:
        data = tmdb_search_movies(term, page=1)
        return [format_tmdb_search_result(r) for r in (data.get("results") or [])[:limit]]
    except Exception:
        return []


def _catalog_movie_dedupe_key(m: dict) -> tuple:
    return ((m.get("title") or "").strip().lower(), m.get("release_year"))


def _merge_catalog_with_tmdb(catalog: list, tmdb_rows: list | None) -> list[dict]:
    """Catalog rows first, then TMDB rows not already represented (title + year)."""
    unified: list[dict] = []
    for m in catalog:
        row = dict(m)
        row["source"] = "catalog"
        unified.append(row)
    keys = {_catalog_movie_dedupe_key(m) for m in catalog}
    for tm in tmdb_rows or []:
        k = ((tm.get("title") or "").strip().lower(), tm.get("release_year"))
        if k in keys:
            continue
        row = dict(tm)
        row["poster_url"] = _normalize_poster_url(row.get("poster_url"))
        gn = row.get("genre_name")
        row["genre_names"] = row.get("genre_names") or ([gn] if gn else [])
        ov = row.get("overview") or ""
        row["synopsis"] = (ov[:280] + ("…" if len(ov) > 280 else "")) if ov else ""
        row["source"] = "tmdb"
        unified.append(row)
    return unified


def _filter_tmdb_for_browse_year(tmdb_rows: list | None, y_from: str, y_to: str) -> list:
    """Drop TMDB hits outside browse year bounds when bounds are set."""
    yf_s = (y_from or "").strip()
    yt_s = (y_to or "").strip()
    if not yf_s and not yt_s:
        return list(tmdb_rows or [])
    try:
        yf = int(yf_s) if yf_s else None
    except ValueError:
        yf = None
    try:
        yt = int(yt_s) if yt_s else None
    except ValueError:
        yt = None
    out = []
    for r in tmdb_rows or []:
        ry = r.get("release_year")
        if ry is None:
            continue
        if yf is not None and int(ry) < yf:
            continue
        if yt is not None and int(ry) > yt:
            continue
        out.append(r)
    return out


@app.route("/")
def index():
    raw_by = request.args.get("search_by", "title")
    q = request.args.get("q", "").strip()
    quick = _quick_search_params(raw_by, q)
    search_by = quick["search_by"]
    q = quick["q"]

    results = []
    search_attempted = "q" in request.args
    if search_attempted and q:
        results = _db_search_or_stub(
            q=quick["title_q"],
            director=quick["director_q"],
            actor=quick["actor_q"],
        )

    tmdb_parallel_results: list = []
    if search_attempted and q and tmdb_is_configured():
        tmdb_parallel_results = _tmdb_parallel_search_results(q, search_by)

    unified_search_results: list[dict] = []
    if search_attempted:
        unified_search_results = _merge_catalog_with_tmdb(results, tmdb_parallel_results)

    filters = {
        "search_by": search_by,
        "q": q,
    }
    search_query = q
    search_by_label = {
        "title": "title",
        "actor": "actor",
        "director": "director",
    }.get(search_by, "title")
    return render_template(
        "index.html",
        results=results,
        result_count=len(unified_search_results) if search_attempted else len(results),
        filters=filters,
        search_query=search_query,
        search_attempted=search_attempted,
        search_by=search_by,
        search_by_label=search_by_label,
        genres=get_genres(),
        tmdb_enabled=tmdb_is_configured(),
        unified_search_results=unified_search_results,
        recommendations=_recommendations_for_home(),
        top_favorite_genres=_user_top_genres_for_home(),
        favorite_genre_recommendations=_favorite_genre_recommendations_for_home(),
    )


@app.route("/films")
def all_films_page():
    genre = request.args.getlist("genre")
    decade = request.args.get("decade", "").strip()
    q = request.args.get("q", "").strip()
    actor = request.args.get("actor", "").strip()
    director = request.args.get("director", "").strip()
    language = request.args.get("language", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "year_desc").strip()

    try:
        page = int(request.args.get("page", "1") or 1)
    except ValueError:
        page = 1
    page = max(1, page)
    try:
        per_page = int(request.args.get("per_page", "") or BROWSE_PER_PAGE_DEFAULT)
    except ValueError:
        per_page = BROWSE_PER_PAGE_DEFAULT
    per_page = max(1, min(100, per_page))

    y_from, y_to = _browse_year_bounds(decade)
    results, total = _db_browse_catalog_and_total(
        page=page,
        per_page=per_page,
        q=q,
        actor=actor,
        director=director,
        genre=genre,
        year_from=y_from,
        year_to=y_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
    )

    total_pages = (total + per_page - 1) // per_page if total else 0
    if total_pages and page > total_pages:
        page = total_pages
        results, total = _db_browse_catalog_and_total(
            page=page,
            per_page=per_page,
            q=q,
            actor=actor,
            director=director,
            genre=genre,
            year_from=y_from,
            year_to=y_to,
            rating_min=rating_min,
            rating_max=rating_max,
            language=language,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            sort_by=sort_by,
        )
        total_pages = (total + per_page - 1) // per_page if total else 0

    range_start = 0 if total == 0 else (page - 1) * per_page + 1
    range_end = min(page * per_page, total)

    tmdb_browse_rows: list = []
    if page == 1 and q and len(q.strip()) >= 2 and tmdb_is_configured():
        raw_tmdb = _tmdb_parallel_search_results(q, "title")
        tmdb_browse_rows = _filter_tmdb_for_browse_year(raw_tmdb, y_from, y_to)

    unified_browse_results = _merge_catalog_with_tmdb(results, tmdb_browse_rows)

    filters = {
        "genre": genre,
        "decade": decade,
        "q": q,
        "actor": actor,
        "director": director,
        "language": language,
        "rating_min": rating_min,
        "rating_max": rating_max,
        "runtime_min": runtime_min,
        "runtime_max": runtime_max,
        "sort_by": sort_by,
        "page": page,
        "per_page": per_page,
    }
    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "range_start": range_start,
        "range_end": range_end,
        "extra_web": max(0, len(unified_browse_results) - len(results)),
        "page_items": _browse_pagination_items(page, total_pages),
    }
    return render_template(
        "all_films.html",
        results=results,
        result_count=len(unified_browse_results),
        unified_browse_results=unified_browse_results,
        filters=filters,
        pagination=pagination,
        genres=get_genres(),
        decades=DECADES,
        browse_sort_options=BROWSE_SORT_OPTIONS,
        languages=LANGUAGES,
    )


@app.route("/search")
def search_page():
    return redirect(url_for("all_films_page", **request.args))


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    movie = None
    cast, crew, similar_movies = [], [], []
    if _use_db():
        try:
            movie = _movie_detail_from_db(movie_id)
            if movie:
                cast = db_get_credits(movie_id, role="Actor")
                crew = db_get_credits(movie_id, role="Director")
                sim_rows = db_similar_movies(movie_id)
                similar_movies = [_serialize_db_search_row(r) for r in sim_rows]
        except Exception:
            movie = None
    if not movie:
        movie = _stub_movie(movie_id)
        if not movie:
            return "Movie not found", 404
        cast = _stub_credits(movie_id, role="cast")
        crew = _stub_credits(movie_id, role="crew")
        similar_movies = _stub_similar_movies(movie_id)
    return render_template(
        "movie.html",
        movie=movie,
        cast=cast,
        crew=crew,
        similar_movies=similar_movies,
    )


@app.route("/recommendations")
def recommendations_page():
    recs = []
    if _use_db():
        try:
            if current_user.is_authenticated:
                uid = int(current_user.id)
                top = db_user_top_genre_ids(uid)
                rows = db_get_recommendations(uid, limit=48)
                recs = [_recommendation_from_db_row(r, top) for r in rows]
            else:
                rows = db_get_spotlight_recommendations(limit=48)
                recs = [_recommendation_from_db_row(r, []) for r in rows]
        except Exception:
            recs = []
    if not recs and not _use_db():
        recs = _stub_recommendations()
    recs = _ensure_genre_ids_for_recommendations_cards(recs)
    return render_template("recommendations.html", recommendations=recs, genres=get_genres())


@app.route("/api/genres")
def api_genres():
    return jsonify(get_genres())


@app.route("/api/search")
def api_search():
    search_by = request.args.get("search_by", "").strip()
    q = request.args.get("q", "").strip()
    director = request.args.get("director", "").strip()
    actor = request.args.get("actor", "").strip()
    if search_by:
        quick = _quick_search_params(search_by, q)
        q = quick["title_q"]
        director = quick["director_q"]
        actor = quick["actor_q"]
    genre = request.args.getlist("genre")
    year_from = request.args.get("year_from", "").strip()
    year_to = request.args.get("year_to", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    language = request.args.get("language", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "").strip()
    results = _db_search_or_stub(
        q=q, director=director, actor=actor,
        genre=genre, year_from=year_from, year_to=year_to,
        rating_min=rating_min, rating_max=rating_max,
        language=language, runtime_min=runtime_min, runtime_max=runtime_max,
        sort_by=sort_by,
    )
    return jsonify(results)


@app.route("/api/browse")
def api_browse():
    genre = request.args.getlist("genre")
    decade = request.args.get("decade", "").strip()
    q = request.args.get("q", "").strip()
    actor = request.args.get("actor", "").strip()
    director = request.args.get("director", "").strip()
    language = request.args.get("language", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "year_desc").strip()
    try:
        page = int(request.args.get("page", "1") or 1)
    except ValueError:
        page = 1
    page = max(1, page)
    try:
        per_page = int(request.args.get("per_page", "") or BROWSE_PER_PAGE_DEFAULT)
    except ValueError:
        per_page = BROWSE_PER_PAGE_DEFAULT
    per_page = max(1, min(100, per_page))

    y_from, y_to = _browse_year_bounds(decade)
    results, total = _db_browse_catalog_and_total(
        page=page,
        per_page=per_page,
        q=q,
        actor=actor,
        director=director,
        genre=genre,
        year_from=y_from,
        year_to=y_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
    )
    total_pages = (total + per_page - 1) // per_page if total else 0
    if total_pages and page > total_pages:
        page = total_pages
        results, total = _db_browse_catalog_and_total(
            page=page,
            per_page=per_page,
            q=q,
            actor=actor,
            director=director,
            genre=genre,
            year_from=y_from,
            year_to=y_to,
            rating_min=rating_min,
            rating_max=rating_max,
            language=language,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            sort_by=sort_by,
        )
        total_pages = (total + per_page - 1) // per_page if total else 0

    return jsonify(
        {
            "results": results,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    )


@app.route("/api/movies/<int:movie_id>")
def api_movie(movie_id):
    if _use_db():
        try:
            m = _movie_detail_from_db(movie_id)
            if m:
                payload = {k: v for k, v in m.items() if k not in ("synopsis",)}
                return jsonify(payload)
        except Exception:
            pass
    movie = _stub_movie(movie_id)
    if not movie:
        return jsonify({"error": "Not found"}), 404
    return jsonify(movie)


@app.route("/api/movies")
def api_movies_bulk():
    ids_param = request.args.get("ids", "").strip()
    if not ids_param:
        return jsonify([])
    try:
        ids = [int(x) for x in ids_param.split(",") if x.strip()]
    except ValueError:
        return jsonify([])
    out = []
    for i in ids:
        if _use_db():
            try:
                m = _movie_detail_from_db(i)
                if m:
                    out.append({k: v for k, v in m.items() if k not in ("synopsis",)})
                    continue
            except Exception:
                pass
        m = _stub_movie(i)
        if m:
            out.append(m)
    return jsonify(out)


@app.route("/api/ratings", methods=["GET"])
def api_get_rating():
    movie_id = request.args.get("movie_id", type=int)
    if not movie_id:
        return jsonify({"error": "movie_id required"}), 400
    if not current_user.is_authenticated:
        return jsonify({"rating_value": None})
    if _use_db():
        try:
            row = db_get_user_rating(int(current_user.id), movie_id)
            if row and row.get("rating_value") is not None:
                return jsonify({"rating_value": float(row["rating_value"])})
        except Exception:
            pass
    return jsonify({"rating_value": None})


@app.route("/api/ratings", methods=["POST"])
def api_set_rating():
    if not current_user.is_authenticated:
        return jsonify({"error": "login required"}), 401
    data = request.get_json() or {}
    movie_id = data.get("movie_id")
    rating_value = data.get("rating_value")
    if movie_id is None or rating_value is None:
        return jsonify({"error": "movie_id and rating_value required"}), 400
    try:
        rating_value = float(rating_value)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid rating_value"}), 400
    if not (0 <= rating_value <= 5):
        return jsonify({"error": "rating_value must be 0–5"}), 400
    if (rating_value * 2) % 1 != 0:
        return jsonify({"error": "rating_value must be in 0.5 increments (0, 0.5, 1, ..., 5)"}), 400
    if _use_db():
        try:
            db_set_user_rating(int(current_user.id), int(movie_id), rating_value)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "movie_id": movie_id, "rating_value": rating_value})


@app.route("/api/ratings", methods=["DELETE"])
def api_delete_rating():
    if not current_user.is_authenticated:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    movie_id = request.args.get("movie_id", type=int)
    if movie_id is None and data.get("movie_id") is not None:
        try:
            movie_id = int(data["movie_id"])
        except (TypeError, ValueError):
            movie_id = None
    if not movie_id:
        return jsonify({"error": "movie_id required"}), 400
    if not _use_db():
        return jsonify({"error": "database not configured"}), 503
    try:
        deleted = db_delete_user_rating(int(current_user.id), movie_id)
        if deleted == 0:
            return jsonify({"error": "no rating found for this film"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "movie_id": movie_id})


@app.route("/api/recommendations")
def api_recommendations():
    if _use_db():
        try:
            if current_user.is_authenticated:
                uid = int(current_user.id)
                top = db_user_top_genre_ids(uid)
                rows = db_get_recommendations(uid, limit=24)
                return jsonify([_recommendation_from_db_row(r, top) for r in rows])
            rows = db_get_spotlight_recommendations(limit=24)
            return jsonify([_recommendation_from_db_row(r, []) for r in rows])
        except Exception:
            pass
    return jsonify(_stub_recommendations())


@app.route("/api/tmdb/search")
def api_tmdb_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    if not tmdb_is_configured():
        return jsonify({"error": "TMDB not configured"}), 503
    try:
        data = tmdb_search_movies(q)
        results = [format_tmdb_search_result(r) for r in (data.get("results") or [])[:15]]
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/tmdb/preview")
def api_tmdb_preview():
    tmdb_id = request.args.get("tmdb_id", type=int)
    if not tmdb_id:
        return jsonify({"error": "tmdb_id required"}), 400
    if not tmdb_is_configured():
        return jsonify({"error": "TMDB not configured"}), 503
    try:
        preview = preview_tmdb_import(tmdb_id, get_genres())
        return jsonify(preview)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/movies/from-tmdb", methods=["POST"])
def api_movies_from_tmdb():
    if not _use_db():
        return jsonify({"error": "database not configured"}), 503
    data = request.get_json(silent=True) or {}
    tmdb_id = data.get("tmdb_id")
    if tmdb_id is None:
        return jsonify({"error": "tmdb_id required"}), 400
    try:
        tid = int(tmdb_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid tmdb_id"}), 400
    try:
        result = import_tmdb_movie(tid, get_genres())
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/movies/like-from-tmdb", methods=["POST"])
def api_like_from_tmdb():
    if not current_user.is_authenticated:
        return jsonify({"error": "login required"}), 401
    if not _use_db():
        return jsonify({"error": "database not configured"}), 503
    if not tmdb_is_configured():
        return jsonify({"error": "TMDB not configured"}), 503
    data = request.get_json(silent=True) or {}
    tmdb_id = data.get("tmdb_id")
    if tmdb_id is None:
        return jsonify({"error": "tmdb_id required"}), 400
    try:
        tid = int(tmdb_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid tmdb_id"}), 400
    try:
        result = import_tmdb_movie(tid, get_genres())
        movie_id = int(result["movie_id"])
        db_set_user_rating(int(current_user.id), movie_id, 5)
        return jsonify(
            {
                "ok": True,
                "movie_id": movie_id,
                "title": result.get("title"),
                "already_existed": bool(result.get("already_existed")),
            }
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 502


def get_genres():
    try:
        rows = db_get_genres()
        if rows:
            return [dict(row) for row in rows]
    except Exception:
        pass
    return _stub_genres()


def _stub_genres():
    return [
        {"genre_id": 1, "genre_name": "Action"},
        {"genre_id": 2, "genre_name": "Comedy"},
        {"genre_id": 3, "genre_name": "Drama"},
        {"genre_id": 4, "genre_name": "Horror"},
        {"genre_id": 5, "genre_name": "Romance"},
        {"genre_id": 6, "genre_name": "Sci-Fi"},
        {"genre_id": 7, "genre_name": "Thriller"},
        {"genre_id": 8, "genre_name": "Documentary"},
        {"genre_id": 9, "genre_name": "Animation"},
        {"genre_id": 10, "genre_name": "Crime"},
        {"genre_id": 11, "genre_name": "Mystery"},
        {"genre_id": 12, "genre_name": "Fantasy"},
    ]


LANGUAGES = [
    ("", "Any"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("it", "Italian"),
    ("de", "German"),
    ("hi", "Hindi"),
    ("other", "Other"),
]

SORT_OPTIONS = [
    ("", "Relevance"),
    ("year_desc", "Year Newest"),
    ("year_asc", "Year Oldest"),
    ("rating_desc", "Rating High→Low"),
    ("title_asc", "Title A–Z"),
]

BROWSE_SORT_OPTIONS = [
    ("year_desc", "Year (newest first)"),
    ("year_asc", "Year (oldest first)"),
    ("rating_desc", "Rating (high to low)"),
    ("rating_asc", "Rating (low to high)"),
    ("runtime_desc", "Runtime (longest first)"),
    ("runtime_asc", "Runtime (shortest first)"),
    ("title_asc", "Title A–Z"),
]

DECADES = [
    ("", "Any decade"),
    ("2020s", "2020s"),
    ("2010s", "2010s"),
    ("2000s", "2000s"),
    ("1990s", "1990s"),
    ("1980s", "1980s"),
    ("1970s", "1970s"),
    ("1960s", "1960s"),
    ("1950s", "1950s"),
    ("1940s", "1940s"),
    ("1930s", "1930s"),
]


def _decade_year_range(decade):
    if not decade:
        return "", ""
    decades = {
        "2020s": (2020, 2029),
        "2010s": (2010, 2019),
        "2000s": (2000, 2009),
        "1990s": (1990, 1999),
        "1980s": (1980, 1989),
        "1970s": (1970, 1979),
        "1960s": (1960, 1969),
        "1950s": (1950, 1959),
        "1940s": (1940, 1949),
        "1930s": (1930, 1939),
    }
    bounds = decades.get(decade)
    if not bounds:
        return "", ""
    return str(bounds[0]), str(bounds[1])


def _browse_year_bounds(decade):
    return _decade_year_range(decade)


def _quick_search_params(search_by, q):
    search_by = (search_by or "title").strip().lower()
    if search_by not in {"title", "actor", "director"}:
        search_by = "title"
    q = (q or "").strip()
    return {
        "search_by": search_by,
        "q": q,
        "title_q": q if search_by == "title" else "",
        "actor_q": q if search_by == "actor" else "",
        "director_q": q if search_by == "director" else "",
    }


def _stub_catalog_search_results(
    q="",
    director="",
    actor="",
    genre=None,
    year_from="",
    year_to="",
    rating_min="",
    rating_max="",
    language="",
    runtime_min="",
    runtime_max="",
    sort_by="",
    media_type="",
):
    genre = genre or []
    items = list(_stub_catalog())

    if q:
        q_lower = q.lower()
        items = [m for m in items if q_lower in m["title"].lower()]
    if director:
        d_lower = director.lower()
        items = [m for m in items if d_lower in m["director"].lower()]
    if actor:
        a_lower = actor.lower()
        items = [m for m in items if any(a_lower in name.lower() for name in m["cast"])]
    if genre:
        wanted = set(genre)
        items = [m for m in items if wanted.intersection(set(m["genre_ids"]))]

    def _num_or_none(v, cast=float):
        try:
            if v == "" or v is None:
                return None
            return cast(v)
        except ValueError:
            return None

    year_from_v = _num_or_none(year_from, int)
    year_to_v = _num_or_none(year_to, int)
    rating_min_v = _num_or_none(rating_min, float)
    rating_max_v = _num_or_none(rating_max, float)
    runtime_min_v = _num_or_none(runtime_min, int)
    runtime_max_v = _num_or_none(runtime_max, int)

    if year_from_v is not None:
        items = [m for m in items if m["release_year"] >= year_from_v]
    if year_to_v is not None:
        items = [m for m in items if m["release_year"] <= year_to_v]
    if rating_min_v is not None:
        items = [m for m in items if m["average_rating"] >= rating_min_v]
    if rating_max_v is not None:
        items = [m for m in items if m["average_rating"] <= rating_max_v]
    if runtime_min_v is not None:
        items = [m for m in items if m["runtime"] >= runtime_min_v]
    if runtime_max_v is not None:
        items = [m for m in items if m["runtime"] <= runtime_max_v]
    if language:
        items = [m for m in items if m["language_code"] == language]

    mt = (media_type or "").strip().lower()
    if mt in ("movie", "show"):
        items = [m for m in items if m.get("media_type") == mt]

    if sort_by == "year_desc":
        items.sort(key=lambda m: m["release_year"], reverse=True)
    elif sort_by == "year_asc":
        items.sort(key=lambda m: m["release_year"])
    elif sort_by == "rating_desc":
        items.sort(key=lambda m: m["average_rating"], reverse=True)
    elif sort_by == "title_asc":
        items.sort(key=lambda m: m["title"].lower())
    elif sort_by == "rating_asc":
        items.sort(key=lambda m: m["average_rating"])
    elif sort_by == "runtime_desc":
        items.sort(key=lambda m: m["runtime"], reverse=True)
    elif sort_by == "runtime_asc":
        items.sort(key=lambda m: m["runtime"])

    return items


def _stub_search(
    q="", director="", actor="",
    genre=None, year_from="", year_to="", rating_min="", rating_max="",
    language="", runtime_min="", runtime_max="", sort_by="",
    media_type="",
):
    items = _stub_catalog_search_results(
        q=q,
        director=director,
        actor=actor,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
        media_type=media_type,
    )
    return [_stub_movie_card(m) for m in items]


BROWSE_PER_PAGE_DEFAULT = 24


def _browse_pagination_items(current_page: int, total_pages: int):
    """Build page / gap entries for numbered pagination controls."""
    if total_pages <= 1:
        return []
    nums = set()
    for p in (
        1,
        2,
        total_pages,
        total_pages - 1,
        current_page,
        current_page - 1,
        current_page + 1,
        current_page - 2,
        current_page + 2,
    ):
        if 1 <= p <= total_pages:
            nums.add(p)
    ordered = sorted(nums)
    out = []
    last = None
    for p in ordered:
        if last is not None and p - last > 1:
            out.append({"kind": "gap"})
        out.append({"kind": "page", "num": p, "current": p == current_page})
        last = p
    return out


def _db_browse_catalog_and_total(
    *,
    page=1,
    per_page=BROWSE_PER_PAGE_DEFAULT,
    sort_by="year_desc",
    q="",
    actor="",
    director="",
    genre=None,
    year_from=None,
    year_to=None,
    rating_min=None,
    rating_max=None,
    language="",
    runtime_min=None,
    runtime_max=None,
    media_type="",
):
    """Catalog rows for one browse page and total matching rows (for pagination)."""
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page
    search_kw = dict(
        q=q,
        director=director,
        actor=actor,
        genre=genre or [],
        year_from=year_from,
        year_to=year_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
    )
    if _use_db():
        try:
            total = db_count_search_movies(**search_kw)
            rows = db_search_movies(**search_kw, limit=per_page, offset=offset)
            cards = [_serialize_db_search_row(r) for r in rows]
            mt = (media_type or "").strip().lower()
            if mt in ("movie", "show"):
                cards = [c for c in cards if c.get("media_type") == mt]
            return cards, total
        except Exception:
            pass
    items = _stub_catalog_search_results(
        q=q,
        director=director,
        actor=actor,
        genre=genre,
        year_from=year_from or "",
        year_to=year_to or "",
        rating_min=rating_min or "",
        rating_max=rating_max or "",
        language=language or "",
        runtime_min=runtime_min or "",
        runtime_max=runtime_max or "",
        sort_by=sort_by,
        media_type=media_type,
    )
    total = len(items)
    cards = [_stub_movie_card(m) for m in items[offset : offset + per_page]]
    return cards, total


def _stub_movie(movie_id):
    for m in _stub_catalog():
        if m["movie_id"] == movie_id:
            return _stub_movie_detail(m)
    return None


def _stub_credits(movie_id, role="cast"):
    if role == "cast":
        return [
            {"name": "Actor One", "character_name": "Lead"},
            {"name": "Actor Two", "character_name": "Support"},
        ]
    return [
        {"name": "Director Name", "role": "Director"},
    ]


def _stub_recommendations():
    rec_ids = [4, 8, 3, 6, 1, 7]
    top_genres = set([g["genre_id"] for g in _stub_user_top_genres()])
    out = []
    for mid in rec_ids:
        movie = _movie_by_id(mid)
        if not movie:
            continue
        card = _stub_movie_card(movie)
        genre_overlap = len(set(movie["genre_ids"]).intersection(top_genres))
        base_score = 58 + (genre_overlap * 14) + int(movie["average_rating"] * 2.2)
        card["match_percentage"] = max(62, min(98, base_score))
        out.append(card)
    return out


def _stub_user_top_genres():
    ids = [3, 6, 7, 2]
    by_id = {g["genre_id"]: g for g in get_genres()}
    return [by_id[g] for g in ids if g in by_id][:4]


def _stub_favorite_genre_recommendations():
    top_genres = [g["genre_id"] for g in _stub_user_top_genres()]
    genre_rank = {gid: idx for idx, gid in enumerate(top_genres)}
    out = []
    for movie in _stub_catalog():
        overlap = [gid for gid in movie["genre_ids"] if gid in genre_rank]
        if not overlap:
            continue
        card = _stub_movie_card(movie)
        primary = sorted(overlap, key=lambda gid: genre_rank[gid])[0]
        card["favorite_genre_match"] = primary
        card["favorite_genre_match_name"] = _genre_name(primary)
        card["genre_id"] = primary
        out.append(card)

    out.sort(
        key=lambda m: (
            genre_rank.get(m["favorite_genre_match"], 99),
            -m["average_rating"],
            -m["release_year"],
        )
    )

    target = 24
    if len(out) >= target:
        return out[:target]

    cycle = sorted(out, key=lambda m: (-m["average_rating"], -m["release_year"]))
    i = 0
    while len(out) < target and cycle:
        out.append(cycle[i % len(cycle)])
        i += 1
    return out


def _stub_similar_movies(movie_id):
    base = _movie_by_id(movie_id)
    if not base:
        return []
    base_genres = set(base["genre_ids"])
    candidates = []
    for movie in _stub_catalog():
        if movie["movie_id"] == movie_id:
            continue
        overlap = len(base_genres.intersection(set(movie["genre_ids"])))
        if overlap == 0:
            continue
        candidates.append((overlap, movie["average_rating"], movie["release_year"], movie))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return [_stub_movie_card(row[3]) for row in candidates[:10]]


def _stub_movie_card(movie):
    pu = movie.get("poster_url")
    if not pu:
        pu = f"https://picsum.photos/seed/movietrack-{movie['movie_id']}/400/600"
    return {
        "movie_id": movie["movie_id"],
        "title": movie["title"],
        "media_type": movie["media_type"],
        "release_year": movie["release_year"],
        "runtime": movie["runtime"],
        "language": movie["language"],
        "genre_name": movie["genre_name"],
        "genre_names": movie["genre_names"],
        "director": movie["director"],
        "synopsis": movie["description"],
        "average_rating": movie["average_rating"],
        "poster_url": pu,
    }


def _stub_movie_detail(movie):
    pu = movie.get("poster_url")
    if not pu:
        pu = f"https://picsum.photos/seed/movietrack-{movie['movie_id']}/400/600"
    return {
        "movie_id": movie["movie_id"],
        "title": movie["title"],
        "media_type": movie["media_type"],
        "release_year": movie["release_year"],
        "runtime": movie["runtime"],
        "language": movie["language"],
        "description": movie["description"],
        "poster_url": pu,
        "genre_name": movie["genre_name"],
        "genre_names": movie["genre_names"],
    }


def _movie_by_id(movie_id):
    for m in _stub_catalog():
        if m["movie_id"] == movie_id:
            return m
    return None


def _genre_name(genre_id):
    for g in get_genres():
        if g["genre_id"] == genre_id:
            return g["genre_name"]
    return str(genre_id)


def _stub_catalog():
    return [
        {
            "movie_id": 1,
            "title": "Edge of Midnight",
            "media_type": "movie",
            "release_year": 2021,
            "runtime": 124,
            "language": "English",
            "language_code": "en",
            "description": "A detective uncovers a citywide conspiracy after one anonymous message changes everything.",
            "genre_name": "Drama",
            "genre_names": ["Drama", "Thriller"],
            "genre_ids": ["drama", "thriller"],
            "director": "Ari Nolan",
            "cast": ["Lia Ford", "Owen Pike"],
            "average_rating": 8.2,
            "poster_url": None,
        },
        {
            "movie_id": 2,
            "title": "Orbit Summer",
            "media_type": "movie",
            "release_year": 2023,
            "runtime": 108,
            "language": "English",
            "language_code": "en",
            "description": "A washed-up pilot joins a street race team and finds a second shot at life.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Romance"],
            "genre_ids": ["comedy", "romance"],
            "director": "Mila Park",
            "cast": ["Zane Quinn", "Ivy Soto"],
            "average_rating": 7.3,
            "poster_url": None,
        },
        {
            "movie_id": 3,
            "title": "Neon Harbor",
            "media_type": "movie",
            "release_year": 2022,
            "runtime": 131,
            "language": "English",
            "language_code": "en",
            "description": "A coder and a rebel broker peace between rival factions in a flooded megacity.",
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi", "Action"],
            "genre_ids": ["sci-fi", "action"],
            "director": "Rene Wallace",
            "cast": ["Nia Cross", "Kade Lin"],
            "average_rating": 8.0,
            "poster_url": None,
        },
        {
            "movie_id": 4,
            "title": "Parallel Hearts",
            "media_type": "show",
            "release_year": 2024,
            "runtime": 112,
            "language": "Spanish",
            "language_code": "es",
            "description": "Two strangers keep meeting in different versions of the same day.",
            "genre_name": "Romance",
            "genre_names": ["Romance", "Drama"],
            "genre_ids": ["romance", "drama"],
            "director": "Elena Mora",
            "cast": ["Marco Rios", "Luz Vega"],
            "average_rating": 7.8,
            "poster_url": None,
        },
        {
            "movie_id": 5,
            "title": "Crimson Run",
            "media_type": "movie",
            "release_year": 2020,
            "runtime": 116,
            "language": "English",
            "language_code": "en",
            "description": "An ex-operative races to stop a high-speed heist across three countries.",
            "genre_name": "Action",
            "genre_names": ["Action", "Thriller"],
            "genre_ids": ["action", "thriller"],
            "director": "Kai Mercer",
            "cast": ["Rex Dalton", "Mina Cho"],
            "average_rating": 7.9,
            "poster_url": None,
        },
        {
            "movie_id": 6,
            "title": "Echoes of Winter",
            "media_type": "show",
            "release_year": 2019,
            "runtime": 127,
            "language": "French",
            "language_code": "fr",
            "description": "A family returns to its hometown and unearths long-buried secrets.",
            "genre_name": "Drama",
            "genre_names": ["Drama"],
            "genre_ids": ["drama"],
            "director": "Noe Lambert",
            "cast": ["Camille Roy", "Etienne Blanc"],
            "average_rating": 8.4,
            "poster_url": None,
        },
        {
            "movie_id": 7,
            "title": "Last Light Hotel",
            "media_type": "show",
            "release_year": 2024,
            "runtime": 103,
            "language": "Korean",
            "language_code": "ko",
            "description": "Guests check into a hotel where every room holds a hidden clue.",
            "genre_name": "Mystery",
            "genre_names": ["Mystery", "Crime"],
            "genre_ids": ["mystery", "crime"],
            "director": "Han Seo-jin",
            "cast": ["Jin Woo", "Min-ah Song"],
            "average_rating": 7.7,
            "poster_url": None,
        },
        {
            "movie_id": 8,
            "title": "Jade Frequency",
            "media_type": "movie",
            "release_year": 2022,
            "runtime": 118,
            "language": "Japanese",
            "language_code": "ja",
            "description": "A musician decodes an alien signal hidden inside old radio tracks.",
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi"],
            "genre_ids": ["sci-fi"],
            "director": "Riku Tanaka",
            "cast": ["Aoi Nara", "Ken Ito"],
            "average_rating": 8.1,
            "poster_url": None,
        },
        {
            "movie_id": 9,
            "title": "Moonline District",
            "media_type": "show",
            "release_year": 2021,
            "runtime": 52,
            "language": "English",
            "language_code": "en",
            "description": "An investigative team exposes corporate crimes hidden across lunar colonies.",
            "genre_name": "Thriller",
            "genre_names": ["Thriller", "Sci-Fi"],
            "genre_ids": ["thriller", "sci-fi"],
            "director": "Tara Voss",
            "cast": ["Mara Kent", "Diego Hale"],
            "average_rating": 8.6,
            "poster_url": None,
        },
        {
            "movie_id": 10,
            "title": "Summer Loop",
            "media_type": "movie",
            "release_year": 2018,
            "runtime": 104,
            "language": "English",
            "language_code": "en",
            "description": "A young DJ relives one summer night until she changes one critical choice.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Drama"],
            "genre_ids": ["comedy", "drama"],
            "director": "Nadia Bloom",
            "cast": ["Kay Ross", "Hugo Lee"],
            "average_rating": 7.5,
            "poster_url": None,
        },
        {
            "movie_id": 11,
            "title": "Blackwater Files",
            "media_type": "show",
            "release_year": 2020,
            "runtime": 49,
            "language": "English",
            "language_code": "en",
            "description": "Two journalists decode a leak that ties five missing persons cases together.",
            "genre_name": "Crime",
            "genre_names": ["Crime", "Thriller"],
            "genre_ids": ["crime", "thriller"],
            "director": "M. Ortega",
            "cast": ["Nora Grant", "Shawn Patel"],
            "average_rating": 8.3,
            "poster_url": None,
        },
        {
            "movie_id": 12,
            "title": "Starlit Transit",
            "media_type": "show",
            "release_year": 2025,
            "runtime": 47,
            "language": "Japanese",
            "language_code": "ja",
            "description": "Passengers on a deep-space line discover the journey has no listed destination.",
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi", "Mystery"],
            "genre_ids": ["sci-fi", "mystery"],
            "director": "Y. Sato",
            "cast": ["Emi Hara", "Ko Tan"],
            "average_rating": 8.7,
            "poster_url": None,
        },
        {
            "movie_id": 13,
            "title": "City of Maybe",
            "media_type": "movie",
            "release_year": 2022,
            "runtime": 109,
            "language": "Spanish",
            "language_code": "es",
            "description": "An architect and a photographer map hidden stories in one changing city.",
            "genre_name": "Drama",
            "genre_names": ["Drama", "Romance"],
            "genre_ids": ["drama", "romance"],
            "director": "Carla Inez",
            "cast": ["Ren Soto", "Mia Flores"],
            "average_rating": 7.9,
            "poster_url": None,
        },
        {
            "movie_id": 14,
            "title": "Punchline Protocol",
            "media_type": "movie",
            "release_year": 2024,
            "runtime": 101,
            "language": "English",
            "language_code": "en",
            "description": "A stand-up comic is recruited to decode humor-based passphrases for an agency.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Action"],
            "genre_ids": ["comedy", "action"],
            "director": "Jo Kim",
            "cast": ["Ari Moss", "Nell Cade"],
            "average_rating": 7.6,
            "poster_url": None,
        },
        {
            "movie_id": 15,
            "title": "Thread of Night",
            "media_type": "show",
            "release_year": 2023,
            "runtime": 50,
            "language": "Korean",
            "language_code": "ko",
            "description": "A pattern analyst spots one symbol repeating in unrelated cyber incidents.",
            "genre_name": "Thriller",
            "genre_names": ["Thriller", "Drama"],
            "genre_ids": ["thriller", "drama"],
            "director": "Lee Min",
            "cast": ["Seo Rin", "Park Jun"],
            "average_rating": 8.1,
            "poster_url": None,
        },
        {
            "movie_id": 16,
            "title": "Blue Frequency",
            "media_type": "movie",
            "release_year": 2017,
            "runtime": 114,
            "language": "French",
            "language_code": "fr",
            "description": "A radio host receives midnight calls that describe crimes before they happen.",
            "genre_name": "Mystery",
            "genre_names": ["Mystery", "Thriller"],
            "genre_ids": ["mystery", "thriller"],
            "director": "R. Delon",
            "cast": ["Iris Bell", "Niko Perot"],
            "average_rating": 7.8,
            "poster_url": None,
        },
        {
            "movie_id": 17,
            "title": "Glass Terminal",
            "media_type": "show",
            "release_year": 2024,
            "runtime": 46,
            "language": "English",
            "language_code": "en",
            "description": "A transit AI starts predicting incidents before commuters arrive.",
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi", "Drama"],
            "genre_ids": ["sci-fi", "drama"],
            "director": "N. Clarke",
            "cast": ["Milo Hart", "Anya Perez"],
            "average_rating": 8.2,
            "poster_url": None,
        },
        {
            "movie_id": 18,
            "title": "Laugh Track Zero",
            "media_type": "show",
            "release_year": 2021,
            "runtime": 31,
            "language": "English",
            "language_code": "en",
            "description": "A sitcom writer discovers every joke predicts tomorrow's headlines.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Sci-Fi"],
            "genre_ids": ["comedy", "sci-fi"],
            "director": "R. Myers",
            "cast": ["Dina Cole", "Jae Rivers"],
            "average_rating": 7.4,
            "poster_url": None,
        },
        {
            "movie_id": 19,
            "title": "Northbound",
            "media_type": "movie",
            "release_year": 2016,
            "runtime": 121,
            "language": "English",
            "language_code": "en",
            "description": "Two siblings retrace an old map to find the town they left behind.",
            "genre_name": "Drama",
            "genre_names": ["Drama"],
            "genre_ids": ["drama"],
            "director": "L. Quinn",
            "cast": ["Nora Hale", "Brent Fox"],
            "average_rating": 7.7,
            "poster_url": None,
        },
        {
            "movie_id": 20,
            "title": "Zero Witnesses",
            "media_type": "movie",
            "release_year": 2025,
            "runtime": 112,
            "language": "German",
            "language_code": "de",
            "description": "A prosecutor reopens a closed case after encrypted footage surfaces.",
            "genre_name": "Thriller",
            "genre_names": ["Thriller", "Crime"],
            "genre_ids": ["thriller", "crime"],
            "director": "T. Varga",
            "cast": ["Lea Blum", "Eric Dorn"],
            "average_rating": 8.0,
            "poster_url": None,
        },
        {
            "movie_id": 21,
            "title": "Second Draft",
            "media_type": "show",
            "release_year": 2020,
            "runtime": 43,
            "language": "English",
            "language_code": "en",
            "description": "A novelist relives one chapter of life while trying to rewrite the ending.",
            "genre_name": "Drama",
            "genre_names": ["Drama", "Mystery"],
            "genre_ids": ["drama", "mystery"],
            "director": "P. Wu",
            "cast": ["Grace Lin", "Tom Sayers"],
            "average_rating": 8.1,
            "poster_url": None,
        },
        {
            "movie_id": 22,
            "title": "Comet Market",
            "media_type": "movie",
            "release_year": 2023,
            "runtime": 98,
            "language": "Japanese",
            "language_code": "ja",
            "description": "A street-food crew chases a cooking contest held during a meteor shower.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Drama"],
            "genre_ids": ["comedy", "drama"],
            "director": "K. Mori",
            "cast": ["Aki Ito", "Ryo Tan"],
            "average_rating": 7.2,
            "poster_url": None,
        },
        {
            "movie_id": 23,
            "title": "Cold Relay",
            "media_type": "show",
            "release_year": 2022,
            "runtime": 45,
            "language": "French",
            "language_code": "fr",
            "description": "A relay team tracks stolen climate data across six nations.",
            "genre_name": "Thriller",
            "genre_names": ["Thriller", "Action"],
            "genre_ids": ["thriller", "action"],
            "director": "A. Reine",
            "cast": ["Solene V", "Marc Dela"],
            "average_rating": 7.9,
            "poster_url": None,
        },
        {
            "movie_id": 24,
            "title": "Velvet Static",
            "media_type": "movie",
            "release_year": 2019,
            "runtime": 107,
            "language": "English",
            "language_code": "en",
            "description": "A late-night host deciphers coded messages hidden in call-in songs.",
            "genre_name": "Mystery",
            "genre_names": ["Mystery", "Drama"],
            "genre_ids": ["mystery", "drama"],
            "director": "M. Drew",
            "cast": ["Elise Ford", "Dean Kline"],
            "average_rating": 7.8,
            "poster_url": None,
        },
        {
            "movie_id": 25,
            "title": "Sundial Unit",
            "media_type": "show",
            "release_year": 2025,
            "runtime": 50,
            "language": "Korean",
            "language_code": "ko",
            "description": "A special unit handles events that repeat each solar cycle.",
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi", "Thriller"],
            "genre_ids": ["sci-fi", "thriller"],
            "director": "J. Hwan",
            "cast": ["Min Jae", "Eun Seo"],
            "average_rating": 8.5,
            "poster_url": None,
        },
        {
            "movie_id": 26,
            "title": "Weekend Clause",
            "media_type": "movie",
            "release_year": 2018,
            "runtime": 102,
            "language": "Spanish",
            "language_code": "es",
            "description": "Two rival lawyers must cooperate for one weekend to save their careers.",
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Romance"],
            "genre_ids": ["comedy", "romance"],
            "director": "B. Sierra",
            "cast": ["Lola Rey", "Ivan Costa"],
            "average_rating": 7.1,
            "poster_url": None,
        },
    ]


if __name__ == "__main__":
    app.run(debug=True, port=5001)
