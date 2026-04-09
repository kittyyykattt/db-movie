import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
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


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def db_get_user_by_id(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT user_id, email, password_hash FROM "Users" WHERE user_id = %s', (user_id,))
            return cur.fetchone()


def db_get_user_by_email(email):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT user_id, email, password_hash FROM "Users" WHERE LOWER(email) = LOWER(%s)', (email,))
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
    """Fetch all genres from the database."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT genre_id, genre_name FROM "Genres" ORDER BY genre_name')
            return cur.fetchall()


def db_get_movie_by_id(movie_id):
    """Fetch a single movie with its genre and average rating."""
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
    """Fetch cast/crew for a movie. role='Director' for directors, role='Actor' for cast."""
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


def db_search_movies(
    q="", director="", actor="",
    genre=None, year_from=None, year_to=None,
    rating_min=None, rating_max=None,
    language="", runtime_min=None, runtime_max=None,
    sort_by="", limit=100
):
    """
    Search movies with filters. Uses ILIKE for title/actor/director search.
    Max's homepage: simple search by title/actor/director (3 separate ILIKE queries)
    Max's browse page: master filter query with all filters
    """
    genre = genre or []
    params = []
    
    base_query = '''
        SELECT DISTINCT
            m.movie_id, m.title, m.release_year, m.runtime,
            m.language, m.description, m.poster_url, m.genre_id,
            g.genre_name,
            COALESCE(avg_r.avg_rating, 0) as average_rating
        FROM "Movies" m
        LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
        LEFT JOIN (
            SELECT movie_id, AVG(rating_value) as avg_rating
            FROM "Ratings"
            GROUP BY movie_id
        ) avg_r ON m.movie_id = avg_r.movie_id
    '''
    
    joins = []
    conditions = []
    
    # Title search (ILIKE)
    if q:
        conditions.append("m.title ILIKE %s")
        params.append(f"%{q}%")
    
    # Director search (ILIKE) - join Credits and People
    if director:
        joins.append('''
            JOIN "Credits" c_dir ON m.movie_id = c_dir.movie_id AND c_dir.role = 'Director'
            JOIN "People" p_dir ON c_dir.person_id = p_dir.person_id
        ''')
        conditions.append("p_dir.name ILIKE %s")
        params.append(f"%{director}%")
    
    # Actor search (ILIKE) - join Credits and People
    if actor:
        joins.append('''
            JOIN "Credits" c_act ON m.movie_id = c_act.movie_id AND c_act.role = 'Actor'
            JOIN "People" p_act ON c_act.person_id = p_act.person_id
        ''')
        conditions.append("p_act.name ILIKE %s")
        params.append(f"%{actor}%")
    
    # Genre filter
    if genre:
        placeholders = ", ".join(["%s"] * len(genre))
        conditions.append(f"m.genre_id IN ({placeholders})")
        params.extend(genre)
    
    # Year range filter
    if year_from:
        conditions.append("m.release_year >= %s")
        params.append(int(year_from))
    if year_to:
        conditions.append("m.release_year <= %s")
        params.append(int(year_to))
    
    # Runtime filter
    if runtime_min:
        conditions.append("m.runtime >= %s")
        params.append(int(runtime_min))
    if runtime_max:
        conditions.append("m.runtime <= %s")
        params.append(int(runtime_max))
    
    # Language filter
    if language:
        conditions.append("m.language ILIKE %s")
        params.append(f"%{language}%")
    
    # Rating filter (applied in HAVING since it's an aggregate)
    having_conditions = []
    if rating_min:
        having_conditions.append("COALESCE(avg_r.avg_rating, 0) >= %s")
        params.append(float(rating_min))
    if rating_max:
        having_conditions.append("COALESCE(avg_r.avg_rating, 0) <= %s")
        params.append(float(rating_max))
    
    # Build full query
    full_query = base_query
    for join in joins:
        full_query += join
    
    if conditions:
        full_query += " WHERE " + " AND ".join(conditions)
    
    if having_conditions:
        full_query += " HAVING " + " AND ".join(having_conditions)
    
    # Sorting
    sort_map = {
        "year_desc": "m.release_year DESC",
        "year_asc": "m.release_year ASC",
        "rating_desc": "average_rating DESC",
        "rating_asc": "average_rating ASC",
        "runtime_desc": "m.runtime DESC",
        "runtime_asc": "m.runtime ASC",
        "title_asc": "m.title ASC",
    }
    order = sort_map.get(sort_by, "m.release_year DESC")
    full_query += f" ORDER BY {order}"
    full_query += f" LIMIT {int(limit)}"
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(full_query, params)
            return cur.fetchall()


def db_get_user_rating(user_id, movie_id):
    """Get a user's rating for a specific movie."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT rating_value, rating_date
                FROM "Ratings"
                WHERE user_id = %s AND movie_id = %s
            ''', (user_id, movie_id))
            return cur.fetchone()


def db_set_user_rating(user_id, movie_id, rating_value):
    """Set or update a user's rating for a movie."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Upsert: update if exists, insert if not
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


def db_get_user_ratings_history(user_id):
    """Get all movies rated by a user with movie details."""
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


def db_get_recommendations(user_id, limit=12):
    """
    Get movie recommendations based on user's rated movies.
    Strategy: find movies in genres the user rates highly.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get genres user rates highly (avg rating >= 3.5)
            cur.execute('''
                SELECT m.genre_id, AVG(r.rating_value) as avg_genre_rating
                FROM "Ratings" r
                JOIN "Movies" m ON r.movie_id = m.movie_id
                WHERE r.user_id = %s AND m.genre_id IS NOT NULL
                GROUP BY m.genre_id
                HAVING AVG(r.rating_value) >= 3.5
                ORDER BY avg_genre_rating DESC
                LIMIT 5
            ''', (user_id,))
            top_genres = [row["genre_id"] for row in cur.fetchall()]
            
            if not top_genres:
                # Fallback: return highly rated movies overall
                cur.execute('''
                    SELECT 
                        m.movie_id, m.title, m.release_year, m.runtime,
                        m.language, m.poster_url, m.genre_id,
                        g.genre_name,
                        COALESCE(AVG(r.rating_value), 0) as average_rating
                    FROM "Movies" m
                    LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                    LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id
                    GROUP BY m.movie_id, g.genre_name
                    ORDER BY average_rating DESC
                    LIMIT %s
                ''', (limit,))
                return cur.fetchall()
            
            # Get movies in user's preferred genres they haven't rated
            placeholders = ", ".join(["%s"] * len(top_genres))
            cur.execute(f'''
                SELECT 
                    m.movie_id, m.title, m.release_year, m.runtime,
                    m.language, m.poster_url, m.genre_id,
                    g.genre_name,
                    COALESCE(AVG(r.rating_value), 0) as average_rating
                FROM "Movies" m
                LEFT JOIN "Genres" g ON m.genre_id = g.genre_id
                LEFT JOIN "Ratings" r ON m.movie_id = r.movie_id
                WHERE m.genre_id IN ({placeholders})
                AND m.movie_id NOT IN (
                    SELECT movie_id FROM "Ratings" WHERE user_id = %s
                )
                GROUP BY m.movie_id, g.genre_name
                ORDER BY average_rating DESC
                LIMIT %s
            ''', (*top_genres, user_id, limit))
            return cur.fetchall()


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class AppUser(UserMixin):
    def __init__(self, user_id, email, password_hash):
        self.id = str(user_id)
        self.email = email
        self.password_hash = password_hash

    @staticmethod
    def from_db_row(row):
        if not row:
            return None
        return AppUser(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
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


def _read_form_or_json():
    return request.get_json(silent=True) or request.form


def _wants_json_response():
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _normalize_email(raw):
    return str(raw or "").strip().lower()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if _wants_json_response():
            return jsonify({"message": "Send POST /register with email and password"}), 200
        return redirect(url_for("index"))

    data = _read_form_or_json()
    email = _normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    
    existing = db_get_user_by_email(email)
    if existing:
        return jsonify({"error": "email already registered"}), 409

    password_hash = generate_password_hash(password)
    user_id = db_create_user(email, password_hash)
    user = AppUser(user_id=user_id, email=email, password_hash=password_hash)
    login_user(user)

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

    data = _read_form_or_json()
    email = _normalize_email(data.get("email"))
    password = str(data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    row = db_get_user_by_email(email)
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    user = AppUser.from_db_row(row)
    login_user(user)
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
        results = _stub_search(
            q=quick["title_q"],
            director=quick["director_q"],
            actor=quick["actor_q"],
        )

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
        result_count=len(results),
        filters=filters,
        search_query=search_query,
        search_attempted=search_attempted,
        search_by=search_by,
        search_by_label=search_by_label,
        genres=get_genres(),
        recommendations=_stub_recommendations(),
        top_favorite_genres=_stub_user_top_genres(),
        favorite_genre_recommendations=_stub_favorite_genre_recommendations(),
    )


@app.route("/films")
def all_films_page():
    genre = request.args.getlist("genre")
    decade = request.args.get("decade", "").strip()
    year_from = request.args.get("year_from", "").strip()
    year_to = request.args.get("year_to", "").strip()
    q = request.args.get("q", "").strip()
    media_type = request.args.get("media_type", "").strip()
    language = request.args.get("language", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "year_desc").strip()

    y_from, y_to = _browse_year_bounds(decade, year_from, year_to)
    results = _stub_search(
        q=q,
        genre=genre,
        year_from=y_from,
        year_to=y_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
        media_type=media_type,
    )
    filters = {
        "genre": genre,
        "decade": decade,
        "year_from": year_from,
        "year_to": year_to,
        "q": q,
        "media_type": media_type,
        "language": language,
        "rating_min": rating_min,
        "rating_max": rating_max,
        "runtime_min": runtime_min,
        "runtime_max": runtime_max,
        "sort_by": sort_by,
    }
    return render_template(
        "all_films.html",
        results=results,
        result_count=len(results),
        filters=filters,
        genres=get_genres(),
        decades=DECADES,
        browse_sort_options=BROWSE_SORT_OPTIONS,
        media_type_options=MEDIA_TYPE_OPTIONS,
        languages=LANGUAGES,
    )


@app.route("/search")
def search_page():
    return redirect(url_for("all_films_page", **request.args))


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    movie = _stub_movie(movie_id)
    if not movie:
        return "Movie not found", 404
    cast = _stub_credits(movie_id, role="cast")
    crew = _stub_credits(movie_id, role="crew")
    return render_template(
        "movie.html",
        movie=movie,
        cast=cast,
        crew=crew,
        similar_movies=_stub_similar_movies(movie_id),
    )


@app.route("/recommendations")
def recommendations_page():
    recs = _stub_recommendations()
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
    results = _stub_search(
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
    year_from = request.args.get("year_from", "").strip()
    year_to = request.args.get("year_to", "").strip()
    q = request.args.get("q", "").strip()
    media_type = request.args.get("media_type", "").strip()
    language = request.args.get("language", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "year_desc").strip()
    y_from, y_to = _browse_year_bounds(decade, year_from, year_to)
    results = _stub_search(
        q=q,
        genre=genre,
        year_from=y_from,
        year_to=y_to,
        rating_min=rating_min,
        rating_max=rating_max,
        language=language,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        sort_by=sort_by,
        media_type=media_type,
    )
    return jsonify(results)


@app.route("/api/movies/<int:movie_id>")
def api_movie(movie_id):
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
        m = _stub_movie(i)
        if m:
            out.append(m)
    return jsonify(out)


@app.route("/api/ratings", methods=["GET"])
def api_get_rating():
    movie_id = request.args.get("movie_id", type=int)
    if not movie_id:
        return jsonify({"error": "movie_id required"}), 400
    return jsonify({"rating_value": None})


@app.route("/api/ratings", methods=["POST"])
def api_set_rating():
    data = request.get_json() or {}
    movie_id = data.get("movie_id")
    rating_value = data.get("rating_value")
    if movie_id is None or rating_value is None:
        return jsonify({"error": "movie_id and rating_value required"}), 400
    if not (1 <= rating_value <= 5):
        return jsonify({"error": "rating_value must be 1–5"}), 400
    return jsonify({"ok": True, "movie_id": movie_id, "rating_value": rating_value})


@app.route("/api/recommendations")
def api_recommendations():
    return jsonify(_stub_recommendations())


def get_genres():
    """Get genres from database, fallback to stub data if DB fails."""
    try:
        rows = db_get_genres()
        if rows:
            return [dict(row) for row in rows]
    except Exception:
        pass
    return _stub_genres()


def _stub_genres():
    """Fallback genre data if database is unavailable."""
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

MEDIA_TYPE_OPTIONS = [
    ("", "Movies & TV shows"),
    ("movie", "Movies only"),
    ("show", "TV shows only"),
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
    }
    bounds = decades.get(decade)
    if not bounds:
        return "", ""
    return str(bounds[0]), str(bounds[1])


def _browse_year_bounds(decade, year_from, year_to):
    yf = (year_from or "").strip()
    yt = (year_to or "").strip()
    if yf or yt:
        return yf, yt
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


def _stub_search(
    q="", director="", actor="",
    genre=None, year_from="", year_to="", rating_min="", rating_max="",
    language="", runtime_min="", runtime_max="", sort_by="",
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

    return [_stub_movie_card(m) for m in items]


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
    ids = [3, 6, 7, 2]  # drama, sci-fi, thriller, comedy (using numeric IDs from DB)
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
        "poster_url": movie["poster_url"],
    }


def _stub_movie_detail(movie):
    return {
        "movie_id": movie["movie_id"],
        "title": movie["title"],
        "media_type": movie["media_type"],
        "release_year": movie["release_year"],
        "runtime": movie["runtime"],
        "language": movie["language"],
        "description": movie["description"],
        "poster_url": movie["poster_url"],
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
