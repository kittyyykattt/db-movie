import os
import unittest

from app import app


def _tmdb_env_configured():
    return bool(
        (os.getenv("TMDB_API_KEY") or "").strip()
        or (os.getenv("TMDB_READ_ACCESS_TOKEN") or "").strip()
    )


class UserFlowTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_home_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"MOVIETRACK", r.data)

    def test_browse_renders(self):
        r = self.client.get("/films")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Browse titles", r.data)

    def test_recommendations_renders(self):
        r = self.client.get("/recommendations")
        self.assertEqual(r.status_code, 200)

    def test_movie_detail_stub(self):
        r = self.client.get("/movie/1")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"movie-detail", r.data)

    def test_movie_detail_missing(self):
        r = self.client.get("/movie/999999")
        if os.getenv("DATABASE_URL"):
            self.assertIn(r.status_code, (200, 404))
        else:
            self.assertEqual(r.status_code, 404)

    def test_api_genres(self):
        r = self.client.get("/api/genres")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("genre_id", data[0])
            self.assertIn("genre_name", data[0])

    def test_api_search_json(self):
        r = self.client.get("/api/search?q=edge")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, list)

    def test_api_browse_json(self):
        r = self.client.get("/api/browse?sort_by=year_desc")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.get_json(), list)

    def test_api_recommendations_json(self):
        r = self.client.get("/api/recommendations")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.get_json(), list)

    def test_api_ratings_get_guest(self):
        r = self.client.get("/api/ratings?movie_id=1")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json().get("rating_value"))

    def test_api_ratings_post_requires_login(self):
        r = self.client.post(
            "/api/ratings",
            json={"movie_id": 1, "rating_value": 4},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)

    def test_api_tmdb_search_short_query(self):
        r = self.client.get("/api/tmdb/search?q=a")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])

    def test_api_tmdb_preview_requires_key_or_errors(self):
        r = self.client.get("/api/tmdb/preview?tmdb_id=550")
        if _tmdb_env_configured():
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertIn("movie_row", body)
            self.assertIn("credits", body)
        else:
            self.assertEqual(r.status_code, 503)

    def test_api_import_tmdb_requires_db(self):
        r = self.client.post(
            "/api/movies/from-tmdb",
            json={"tmdb_id": 550},
            content_type="application/json",
        )
        if not os.getenv("DATABASE_URL"):
            self.assertEqual(r.status_code, 503)
            return
        if not _tmdb_env_configured():
            self.assertIn(r.status_code, (502, 503))
            return
        self.assertIn(r.status_code, (200, 502))


if __name__ == "__main__":
    unittest.main()
