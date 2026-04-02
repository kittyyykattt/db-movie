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
  search(params = {}) {
    const q = new URLSearchParams();
    if (params.q) q.set('q', params.q);
    if (params.genre_id) q.set('genre_id', params.genre_id);
    if (params.actor) q.set('actor', params.actor);
    if (params.director) q.set('director', params.director);
    return request(`/search?${q.toString()}`);
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

  getRating(movieId) {
    return request(`/ratings?movie_id=${movieId}`);
  },

  recommendations() {
    return request('/recommendations');
  },
};

if (typeof window !== 'undefined') {
  window.MovieAPI = api;
  window.MovieAPIRequest = request;
}
