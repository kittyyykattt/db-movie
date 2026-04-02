from flask import Flask, render_template, request, jsonify, redirect, url_for
import random
import string
from collections import Counter

app = Flask(__name__)
FRIEND_SESSIONS = {}

@app.context_processor
def inject_user():
    return {"current_user": None}


@app.route("/")
def index():
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

    has_query = any([
        q, director, actor, genre, year_from, year_to,
        rating_min, rating_max, language, runtime_min, runtime_max, sort_by
    ])
    results = []
    if has_query:
        results = _stub_search(
            q=q, director=director, actor=actor,
            genre=genre, year_from=year_from, year_to=year_to,
            rating_min=rating_min, rating_max=rating_max,
            language=language, runtime_min=runtime_min, runtime_max=runtime_max,
            sort_by=sort_by,
        )

    filters = {
        "q": q,
        "director": director,
        "actor": actor,
        "genre": genre,
        "year_from": year_from,
        "year_to": year_to,
        "rating_min": rating_min,
        "rating_max": rating_max,
        "language": language,
        "runtime_min": runtime_min,
        "runtime_max": runtime_max,
        "sort_by": sort_by,
    }
    return render_template(
        "index.html",
        results=results,
        result_count=len(results),
        filters=filters,
        search_query=q,
        genres=_stub_genres(),
        languages=LANGUAGES,
        sort_options=SORT_OPTIONS,
        recommendations=_stub_recommendations(),
        top_favorite_genres=_stub_user_top_genres(),
        favorite_genre_recommendations=_stub_favorite_genre_recommendations(),
    )


@app.route("/search")
def search_page():
    return redirect(url_for("index", **request.args))


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
    return render_template("recommendations.html", recommendations=recs, genres=_stub_genres())


@app.route("/favorites")
def favorites_page():
    return render_template("favorites.html")


@app.route("/choose-with-friends")
def choose_with_friends_page():
    return render_template("choose_with_friends.html", genres=_stub_genres())


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


@app.route("/api/friend-sessions", methods=["POST"])
def api_create_friend_session():
    data = request.get_json() or {}
    member_name = str(data.get("member_name") or "Host").strip()[:40]
    member_id = str(data.get("member_id") or "").strip()
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    code = _generate_friend_code()
    session = {
        "code": code,
        "stage": "preferences",
        "members": {},
        "preference_submissions": {},
        "candidate_ids": [],
        "pick_submissions": {},
        "results": [],
    }
    session["members"][member_id] = member_name or "Host"
    FRIEND_SESSIONS[code] = session
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>/join", methods=["POST"])
def api_join_friend_session(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json() or {}
    member_name = str(data.get("member_name") or "Friend").strip()[:40]
    member_id = str(data.get("member_id") or "").strip()
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    session["members"][member_id] = member_name or "Friend"
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>", methods=["GET"])
def api_get_friend_session(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>/preferences", methods=["POST"])
def api_submit_friend_preferences(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session["stage"] != "preferences":
        return jsonify({"error": "Preference stage is closed"}), 400
    data = request.get_json() or {}
    member_id = str(data.get("member_id") or "").strip()
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    if member_id not in session["members"]:
        session["members"][member_id] = "Friend"
    media_type = str(data.get("media_type") or "movie").strip().lower()
    if media_type not in {"movie", "show", "either"}:
        media_type = "movie"
    genres = data.get("genres") or []
    if not isinstance(genres, list):
        genres = []
    clean_genres = [str(g).strip() for g in genres if str(g).strip()]
    session["preference_submissions"][member_id] = {
        "media_type": media_type,
        "genres": clean_genres[:4],
    }
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>/start-picks", methods=["POST"])
def api_start_friend_picks(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if not session["preference_submissions"]:
        return jsonify({"error": "At least one preference is required"}), 400
    session["candidate_ids"] = _friend_candidates_for_session(session)
    session["stage"] = "picks"
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>/picks", methods=["POST"])
def api_submit_friend_picks(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session["stage"] not in {"picks", "results"}:
        return jsonify({"error": "Pick stage is not active"}), 400
    data = request.get_json() or {}
    member_id = str(data.get("member_id") or "").strip()
    picks = data.get("picks") or []
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    if member_id not in session["members"]:
        session["members"][member_id] = "Friend"
    if not isinstance(picks, list):
        picks = []
    allowed = set(session["candidate_ids"])
    ordered = []
    for p in picks:
        try:
            pid = int(p)
        except (TypeError, ValueError):
            continue
        if pid in allowed and pid not in ordered:
            ordered.append(pid)
        if len(ordered) == 3:
            break
    session["pick_submissions"][member_id] = ordered
    return jsonify(_friend_session_payload(session))


@app.route("/api/friend-sessions/<code>/finalize", methods=["POST"])
def api_finalize_friend_session(code):
    session = FRIEND_SESSIONS.get(code.upper())
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session["stage"] not in {"picks", "results"}:
        return jsonify({"error": "Pick stage is not active"}), 400
    session["results"] = _friend_results_for_session(session)
    session["stage"] = "results"
    return jsonify(_friend_session_payload(session))


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

    if sort_by == "year_desc":
        items.sort(key=lambda m: m["release_year"], reverse=True)
    elif sort_by == "year_asc":
        items.sort(key=lambda m: m["release_year"])
    elif sort_by == "rating_desc":
        items.sort(key=lambda m: m["average_rating"], reverse=True)
    elif sort_by == "title_asc":
        items.sort(key=lambda m: m["title"].lower())

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
    ids = ["drama", "sci-fi", "thriller", "comedy"]
    by_id = {g["genre_id"]: g for g in _stub_genres()}
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
    for g in _stub_genres():
        if g["genre_id"] == genre_id:
            return g["genre_name"]
    return genre_id


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


def _generate_friend_code():
    for _ in range(8):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in FRIEND_SESSIONS:
            return code
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _friend_session_payload(session):
    base_url = request.host_url.rstrip("/")
    join_url = f"{base_url}{url_for('choose_with_friends_page')}?code={session['code']}"
    candidate_movies = []
    for mid in session["candidate_ids"]:
        movie = _stub_movie(mid)
        if movie:
            candidate_movies.append(movie)
    return {
        "code": session["code"],
        "stage": session["stage"],
        "join_url": join_url,
        "member_count": len(session["members"]),
        "members": [
            {
                "member_id": member_id,
                "name": session["members"][member_id],
                "has_preferences": member_id in session["preference_submissions"],
                "has_picks": bool(session["pick_submissions"].get(member_id)),
            }
            for member_id in session["members"]
        ],
        "preferences": session["preference_submissions"],
        "candidates": candidate_movies,
        "results": session["results"],
    }


def _friend_candidates_for_session(session):
    preferences = list(session["preference_submissions"].values())
    media_votes = Counter([p["media_type"] for p in preferences if p.get("media_type") and p["media_type"] != "either"])
    target_media = media_votes.most_common(1)[0][0] if media_votes else "movie"

    genre_votes = Counter()
    for pref in preferences:
        genre_votes.update(pref.get("genres", []))
    top_genres = [g for g, _ in genre_votes.most_common(3)]

    items = list(_stub_catalog())
    media_items = [m for m in items if m["media_type"] == target_media]
    candidate_pool = media_items if media_items else items
    if top_genres:
        filtered = [m for m in candidate_pool if set(m["genre_ids"]).intersection(set(top_genres))]
        if filtered:
            candidate_pool = filtered
    candidate_pool = sorted(candidate_pool, key=lambda m: m["average_rating"], reverse=True)
    return [m["movie_id"] for m in candidate_pool[:8]]


def _friend_results_for_session(session):
    if not session["candidate_ids"]:
        return []
    score = Counter()
    voters = {}
    weights = [3, 2, 1]
    for member_id, picks in session["pick_submissions"].items():
        voter_name = session["members"].get(member_id, "Friend")
        for idx, movie_id in enumerate(picks[:3]):
            score[movie_id] += weights[idx]
            voters.setdefault(movie_id, []).append(voter_name)
    ranked = []
    for movie_id in session["candidate_ids"]:
        if movie_id not in score:
            continue
        movie = _stub_movie(movie_id)
        if not movie:
            continue
        ranked.append({
            "movie": movie,
            "points": score[movie_id],
            "voters": voters.get(movie_id, []),
        })
    ranked.sort(key=lambda row: row["points"], reverse=True)
    return ranked


if __name__ == "__main__":
    app.run(debug=True, port=5000)
