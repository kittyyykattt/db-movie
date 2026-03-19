/**
 * Client-side persistence for Movie DB (localStorage).
 * Keys: moviedb_favorites, moviedb_search_history, moviedb_prefs
 */
(function() {
  var FAVORITES_KEY = 'moviedb_favorites';
  var HISTORY_KEY = 'moviedb_search_history';
  var PREFS_KEY = 'moviedb_prefs';
  var HISTORY_MAX = 5;

  function getFavorites() {
    try {
      var raw = localStorage.getItem(FAVORITES_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (_) {
      return [];
    }
  }

  function setFavorites(ids) {
    try {
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(Array.isArray(ids) ? ids : []));
    } catch (_) {}
  }

  function toggleFavorite(movieId) {
    movieId = Number(movieId);
    if (!movieId) return false;
    var ids = getFavorites();
    var i = ids.indexOf(movieId);
    if (i >= 0) {
      ids.splice(i, 1);
      setFavorites(ids);
      return false;
    } else {
      ids.push(movieId);
      setFavorites(ids);
      return true;
    }
  }

  function isFavorite(movieId) {
    return getFavorites().indexOf(Number(movieId)) >= 0;
  }

  function getSearchHistory() {
    try {
      var raw = localStorage.getItem(HISTORY_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.slice(0, HISTORY_MAX) : [];
    } catch (_) {
      return [];
    }
  }

  function addSearchHistory(term) {
    term = String(term).trim();
    if (!term) return;
    var arr = getSearchHistory();
    arr = arr.filter(function(t) { return t !== term; });
    arr.unshift(term);
    arr = arr.slice(0, HISTORY_MAX);
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(arr));
    } catch (_) {}
  }

  function removeSearchHistory(term) {
    var arr = getSearchHistory().filter(function(t) { return t !== term; });
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(arr));
    } catch (_) {}
  }

  function getPrefs() {
    try {
      var raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return {};
      var o = JSON.parse(raw);
      return o && typeof o === 'object' ? o : {};
    } catch (_) {
      return {};
    }
  }

  function setPrefs(prefs) {
    try {
      var o = Object.assign({}, getPrefs(), prefs);
      localStorage.setItem(PREFS_KEY, JSON.stringify(o));
    } catch (_) {}
  }

  window.MovieDB = {
    getFavorites: getFavorites,
    setFavorites: setFavorites,
    toggleFavorite: toggleFavorite,
    isFavorite: isFavorite,
    getSearchHistory: getSearchHistory,
    addSearchHistory: addSearchHistory,
    removeSearchHistory: removeSearchHistory,
    getPrefs: getPrefs,
    setPrefs: setPrefs
  };

  /* Initialize favorite buttons on the page */
  function initFavoriteButtons() {
    document.querySelectorAll('[data-movie-id]').forEach(function(el) {
      var movieId = el.getAttribute('data-movie-id');
      if (!movieId) return;
      var btn = el.querySelector('.btn-favorite');
      if (!btn) return;
      function updateState() {
        btn.classList.toggle('is-favorite', window.MovieDB.isFavorite(movieId));
        btn.innerHTML = window.MovieDB.isFavorite(movieId) ? '♥' : '♡';
        btn.setAttribute('aria-pressed', window.MovieDB.isFavorite(movieId));
      }
      updateState();
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        window.MovieDB.toggleFavorite(movieId);
        btn.classList.add('btn-favorite-ani');
        setTimeout(function() { btn.classList.remove('btn-favorite-ani'); }, 300);
        updateState();
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFavoriteButtons);
  } else {
    initFavoriteButtons();
  }
})();
