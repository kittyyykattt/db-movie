# Frontend & Data Integration (Katya Serechenko)

## Run the app (with stub backend)

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — you get the full UI with stub data.

## Frontend structure

- **`templates/`** — Jinja2 HTML: `base.html`, `index.html`, `search.html`, `movie.html`, `recommendations.html`
- **`static/css/style.css`** — Layout, components, dark theme
- **`static/js/api.js`** — Fetch client for all backend API calls

## API contract (for backend)

The frontend expects these Flask routes. Replace the stubs in `app.py` with real DB/TMDB logic.

| Method | Route | Purpose |
|--------|--------|--------|
| GET | `/api/genres` | List genres `[{ genre_id, genre_name }, ...]` |
| GET | `/api/search?q=&genre_id=&actor=&director=` | Search movies; returns list of `{ movie_id, title, release_year, genre_name?, poster_url? }` |
| GET | `/api/movies/<id>` | Single movie: `{ movie_id, title, release_year, runtime?, language?, description?, poster_url?, genre_name? }` |
| GET | `/api/ratings?movie_id=<id>` | Current user’s rating: `{ rating_value }` or 404 |
| POST | `/api/ratings` | Body: `{ movie_id, rating_value }` (1–5). Persist and return `{ ok: true }` or error |
| GET | `/api/recommendations` | List of recommended movies (same shape as search results) |

Page routes (render templates with data from your DB):

- `GET /` — Home (pass `genres` for the dropdown)
- `GET /search` — Search page (query params: `q`, `genre_id`, `actor`, `director`; pass `genres`, `results`)
- `GET /movie/<movie_id>` — Movie detail (pass `movie`, `cast`, `crew`)
- `GET /recommendations` — Recommendations (pass `recommendations`)

## Data formatting for DB

- **Search/detail**: Use TMDB API response to fill `title`, `release_year`, `runtime`, `language`, `description`, `poster_url`, and map to your `MOVIES` / `GENRES` schema.
- **Ratings**: Frontend sends `movie_id` and `rating_value` (1–5); backend inserts/updates `RATINGS` and ties to current user (e.g. Supabase auth).
- **Recommendations**: Backend runs your recommendation SQL and returns the same movie list shape as search for the grid.

## User flow testing

1. **Search**: Home or Search → enter filters → Submit → results grid → click a movie.
2. **Movie detail**: Poster, title, meta, description, cast/crew; star rating widget loads existing rating and saves new one via `POST /api/ratings`.
3. **Recommendations**: Navigate to Recommendations → grid of recommended movies (or “Rate some movies…” if empty).
