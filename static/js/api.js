/**
 * Frontend API client for Flask backend.
 * Connect these to your Flask routes (search, movie details, ratings, recommendations).
 */

const API_BASE = '/api';

async function request(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    config.body = JSON.stringify(options.body);
  }
  const res = await fetch(url, config);
  if (!res.ok) {
    const err = new Error(res.statusText || 'Request failed');
    err.status = res.status;
    try {
      err.body = await res.json();
    } catch (_) {
      err.body = await res.text();
    }
    throw err;
  }
  const contentType = res.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return res.json();
  }
  return res.text();
}

const api = {
  /** Search: GET /api/search?q=...&genre_id=...&actor=...&director=... */
  search(params = {}) {
    const q = new URLSearchParams();
    if (params.q) q.set('q', params.q);
    if (params.genre_id) q.set('genre_id', params.genre_id);
    if (params.actor) q.set('actor', params.actor);
    if (params.director) q.set('director', params.director);
    return request(`/search?${q.toString()}`);
  },

  /** Genres: GET /api/genres */
  genres() {
    return request('/genres');
  },

  /** Movie by id: GET /api/movies/<id> */
  movie(id) {
    return request(`/movies/${id}`);
  },

  /** Rate movie: POST /api/ratings { movie_id, rating_value } */
  setRating(movieId, ratingValue) {
    return request('/ratings', {
      method: 'POST',
      body: { movie_id: movieId, rating_value: ratingValue },
    });
  },

  /** User's rating for a movie: GET /api/ratings?movie_id=... (or from session) */
  getRating(movieId) {
    return request(`/ratings?movie_id=${movieId}`);
  },

  /** Recommendations: GET /api/recommendations */
  recommendations() {
    return request('/recommendations');
  },
};

// Export for use in pages
if (typeof window !== 'undefined') {
  window.MovieAPI = api;
  window.MovieAPIRequest = request;
}
