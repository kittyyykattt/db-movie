(function() {
  var LIKED_KEY = 'moviedb_liked';
  var HISTORY_KEY = 'moviedb_search_history';
  var PREFS_KEY = 'moviedb_prefs';
  var RATINGS_KEY = 'moviedb_ratings';
  var HISTORY_MAX = 5;

  function getLiked() {
    try {
      var raw = localStorage.getItem(LIKED_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (_) {
      return [];
    }
  }

  function setLiked(ids) {
    try {
      localStorage.setItem(LIKED_KEY, JSON.stringify(Array.isArray(ids) ? ids : []));
    } catch (_) {}
  }

  function toggleLiked(movieId) {
    movieId = Number(movieId);
    if (!movieId) return false;
    var ids = getLiked();
    var i = ids.indexOf(movieId);
    if (i >= 0) {
      ids.splice(i, 1);
      setLiked(ids);
      return false;
    }
    ids.push(movieId);
    setLiked(ids);
    return true;
  }

  function isLiked(movieId) {
    return getLiked().indexOf(Number(movieId)) >= 0;
  }

  function setLikedFromRating(movieId, ratingValue) {
    movieId = Number(movieId);
    ratingValue = Number(ratingValue);
    if (!movieId || !ratingValue) return;
    var ids = getLiked();
    var i = ids.indexOf(movieId);
    if (ratingValue >= 4 && i < 0) ids.push(movieId);
    if (ratingValue < 4 && i >= 0) ids.splice(i, 1);
    setLiked(ids);
  }

  function getSearchHistory() {
    try {
      var raw = localStorage.getItem(HISTORY_KEY);
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

  function getRatingsMap() {
    try {
      var raw = localStorage.getItem(RATINGS_KEY);
      var o = JSON.parse(raw);
      return o && typeof o === 'object' ? o : {};
    } catch (_) {
      return {};
    }
  }

  function getLocalRating(movieId) {
    var id = String(movieId);
    var v = getRatingsMap()[id];
    if (v == null) return null;
    var n = Number(v);
    return n >= 1 && n <= 5 ? n : null;
  }

  function setLocalRating(movieId, ratingValue) {
    var id = String(movieId);
    var n = Number(ratingValue);
    if (!id || n < 1 || n > 5) return;
    try {
      var map = getRatingsMap();
      map[id] = n;
      localStorage.setItem(RATINGS_KEY, JSON.stringify(map));
    } catch (_) {}
  }

  window.MovieDB = {
    getLiked: getLiked,
    setLiked: setLiked,
    toggleLiked: toggleLiked,
    isLiked: isLiked,
    setLikedFromRating: setLikedFromRating,
    getSearchHistory: getSearchHistory,
    addSearchHistory: addSearchHistory,
    removeSearchHistory: removeSearchHistory,
    getPrefs: getPrefs,
    setPrefs: setPrefs,
    getLocalRating: getLocalRating,
    setLocalRating: setLocalRating
  };
})();
