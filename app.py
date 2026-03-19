"""
Flask app for COP4710 Movie DB.
Serves frontend (templates + static) and API routes for frontend integration.
Backend developer (Mateo) will replace API logic with PostgreSQL + TMDB.
"""
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Optional: inject a fake current_user for template nav (replace with Supabase/session)
@app.context_processor
def inject_user():
    return {"current_user": None}


# ----- Page routes (serve frontend) -----

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search")
def search_page():
    # Basic
    q = request.args.get("q", "").strip()
    director = request.args.get("director", "").strip()
    actor = request.args.get("actor", "").strip()
    # Advanced
    genre = request.args.getlist("genre")  # multi-select
    year_from = request.args.get("year_from", "").strip()
    year_to = request.args.get("year_to", "").strip()
    rating_min = request.args.get("rating_min", "").strip()
    rating_max = request.args.get("rating_max", "").strip()
    language = request.args.get("language", "").strip()
    runtime_min = request.args.get("runtime_min", "").strip()
    runtime_max = request.args.get("runtime_max", "").strip()
    sort_by = request.args.get("sort_by", "").strip()

    results = []
    if q or director or actor or genre or year_from or year_to or rating_min or rating_max or language or runtime_min or runtime_max:
        results = _stub_search(
            q=q, director=director, actor=actor,
            genre=genre, year_from=year_from, year_to=year_to,
            rating_min=rating_min, rating_max=rating_max,
            language=language, runtime_min=runtime_min, runtime_max=runtime_max,
            sort_by=sort_by,
        )
    result_count = len(results)
    filters = {
        "q": q, "director": director, "actor": actor,
        "genre": genre, "year_from": year_from, "year_to": year_to,
        "rating_min": rating_min, "rating_max": rating_max,
        "language": language, "runtime_min": runtime_min, "runtime_max": runtime_max,
        "sort_by": sort_by,
    }
    return render_template(
        "search.html",
        results=results,
        result_count=result_count,
        filters=filters,
        search_query=q,
        genres=_stub_genres(),
        languages=LANGUAGES,
        sort_options=SORT_OPTIONS,
    )


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
    )


@app.route("/recommendations")
def recommendations_page():
    recs = _stub_recommendations()
    return render_template("recommendations.html", recommendations=recs)


@app.route("/favorites")
def favorites_page():
    return render_template("favorites.html")


# ----- API routes (for JS api.js) -----

@app.route("/api/genres")
def api_genres():
    return jsonify(_stub_genres())


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    director = request.args.get("director", "").strip()
    actor = request.args.get("actor", "").strip()
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


@app.route("/api/movies/<int:movie_id>")
def api_movie(movie_id):
    movie = _stub_movie(movie_id)
    if not movie:
        return jsonify({"error": "Not found"}), 404
    return jsonify(movie)


@app.route("/api/movies")
def api_movies_bulk():
    """Optional: return multiple movies by ids=1,2,3 for Favorites page."""
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


# ----- Stub data -----

def _stub_genres():
    return [
        {"genre_id": "action", "genre_name": "Action"},
        {"genre_id": "comedy", "genre_name": "Comedy"},
        {"genre_id": "drama", "genre_name": "Drama"},
        {"genre_id": "horror", "genre_name": "Horror"},
        {"genre_id": "romance", "genre_name": "Romance"},
        {"genre_id": "sci-fi", "genre_name": "Sci-Fi"},
        {"genre_id": "thriller", "genre_name": "Thriller"},
        {"genre_id": "documentary", "genre_name": "Documentary"},
        {"genre_id": "animation", "genre_name": "Animation"},
        {"genre_id": "crime", "genre_name": "Crime"},
        {"genre_id": "mystery", "genre_name": "Mystery"},
        {"genre_id": "fantasy", "genre_name": "Fantasy"},
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


def _stub_search(
    q="", director="", actor="",
    genre=None, year_from="", year_to="", rating_min="", rating_max="",
    language="", runtime_min="", runtime_max="", sort_by="",
):
    genre = genre or []
    # Stub: return fake list with rich fields for UI
    return [
        {
            "movie_id": 1,
            "title": "Example Movie One",
            "release_year": 2020,
            "genre_name": "Drama",
            "genre_names": ["Drama", "Thriller"],
            "director": "Director One",
            "synopsis": "A short synopsis of the first example movie. It has enough text to test two-line truncation with ellipsis in the card layout.",
            "average_rating": 7.8,
            "poster_url": None,
        },
        {
            "movie_id": 2,
            "title": "Example Movie Two",
            "release_year": 2022,
            "genre_name": "Comedy",
            "genre_names": ["Comedy", "Romance"],
            "director": "Director Two",
            "synopsis": "Another example for the grid.",
            "average_rating": 6.5,
            "poster_url": None,
        },
        {
            "movie_id": 3,
            "title": "Example Movie Three",
            "release_year": 2019,
            "genre_name": "Sci-Fi",
            "genre_names": ["Sci-Fi", "Action"],
            "director": "Director Three",
            "synopsis": "Third stub movie for testing the advanced search results and card design.",
            "average_rating": 8.1,
            "poster_url": None,
        },
    ]


def _stub_movie(movie_id):
    return {
        "movie_id": movie_id,
        "title": "Example Movie",
        "release_year": 2020,
        "runtime": 120,
        "language": "English",
        "description": "A short description of the movie.",
        "poster_url": None,
        "genre_name": "Drama",
        "genre_names": ["Drama"],
    }


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
    return [
        {"movie_id": 1, "title": "Recommended One", "release_year": 2021, "genre_name": "Drama", "genre_names": ["Drama"], "poster_url": None},
        {"movie_id": 2, "title": "Recommended Two", "release_year": 2023, "genre_name": "Comedy", "genre_names": ["Comedy"], "poster_url": None},
    ]


if __name__ == "__main__":
    app.run(debug=True, port=5000)
