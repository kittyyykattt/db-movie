const API_BASE = '/api';

async function request(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const config = {
    credentials: 'include',
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
  search(params = {}) {
    const q = new URLSearchParams();
    if (params.q) q.set('q', params.q);
    if (params.search_by) q.set('search_by', params.search_by);
    if (params.genre_id) q.set('genre_id', params.genre_id);
    if (params.actor) q.set('actor', params.actor);
    if (params.director) q.set('director', params.director);
    return request(`/search?${q.toString()}`);
  },

  browse(params = {}) {
    const q = new URLSearchParams();
    if (params.genre && Array.isArray(params.genre)) {
      params.genre.forEach((g) => q.append('genre', g));
    } else if (params.genre) {
      q.set('genre', params.genre);
    }
    if (params.q) q.set('q', params.q);
    if (params.actor) q.set('actor', params.actor);
    if (params.director) q.set('director', params.director);
    if (params.decade) q.set('decade', params.decade);
    if (params.language) q.set('language', params.language);
    if (params.rating_min != null && params.rating_min !== '') q.set('rating_min', params.rating_min);
    if (params.rating_max != null && params.rating_max !== '') q.set('rating_max', params.rating_max);
    if (params.runtime_min != null && params.runtime_min !== '') q.set('runtime_min', params.runtime_min);
    if (params.runtime_max != null && params.runtime_max !== '') q.set('runtime_max', params.runtime_max);
    if (params.sort_by) q.set('sort_by', params.sort_by);
    if (params.page != null && params.page !== '') q.set('page', String(params.page));
    if (params.per_page != null && params.per_page !== '') q.set('per_page', String(params.per_page));
    const qs = q.toString();
    return request(`/browse${qs ? `?${qs}` : ''}`);
  },

  genres() {
    return request('/genres');
  },

  movie(id) {
    return request(`/movies/${id}`);
  },

  setRating(movieId, ratingValue) {
    return request('/ratings', {
      method: 'POST',
      body: { movie_id: movieId, rating_value: ratingValue },
    });
  },

  deleteRating(movieId) {
    const qs = new URLSearchParams();
    qs.set('movie_id', String(movieId));
    return request(`/ratings?${qs.toString()}`, { method: 'DELETE' });
  },

  updateProfile(username) {
    return request('/me', {
      method: 'PATCH',
      body: { username },
    });
  },

  getRating(movieId) {
    return request(`/ratings?movie_id=${movieId}`);
  },

  recommendations() {
    return request('/recommendations');
  },

  meRatings() {
    return request('/me/ratings');
  },

  tmdbSearch(q) {
    const qs = new URLSearchParams();
    if (q) qs.set('q', q);
    return request(`/tmdb/search?${qs.toString()}`);
  },

  tmdbPreview(tmdbId) {
    return request(`/tmdb/preview?tmdb_id=${encodeURIComponent(tmdbId)}`);
  },

  importFromTmdb(tmdbId) {
    return request('/movies/from-tmdb', {
      method: 'POST',
      body: { tmdb_id: tmdbId },
    });
  },

  likeFromTmdb(tmdbId) {
    return request('/movies/like-from-tmdb', {
      method: 'POST',
      body: { tmdb_id: tmdbId },
    });
  },
};

if (typeof window !== 'undefined') {
  window.MovieAPI = api;
  window.MovieAPIRequest = request;
}
