(function() {
  var LIKED_KEY = 'moviedb_liked';
  var PREFS_KEY = 'moviedb_prefs';
  var RATINGS_KEY = 'moviedb_ratings';

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

  function isHalfStep01to10(n) {
    var x = Math.round(n * 2);
    return Math.abs(n * 2 - x) < 1e-9;
  }

  function getLocalRating(movieId) {
    var id = String(movieId);
    var v = getRatingsMap()[id];
    if (v == null) return null;
    var n = Number(v);
    if (n < 0 || n > 5 || !isHalfStep01to10(n)) return null;
    return n;
  }

  function setLocalRating(movieId, ratingValue) {
    var id = String(movieId);
    var n = Number(ratingValue);
    if (!id || n < 0 || n > 5 || !isHalfStep01to10(n)) return;
    try {
      var map = getRatingsMap();
      map[id] = n;
      localStorage.setItem(RATINGS_KEY, JSON.stringify(map));
    } catch (_) {}
  }

  function clearLocalRating(movieId) {
    var id = String(movieId);
    if (!id) return;
    try {
      var map = getRatingsMap();
      delete map[id];
      localStorage.setItem(RATINGS_KEY, JSON.stringify(map));
    } catch (_) {}
  }

  window.MovieDB = {
    getLiked: getLiked,
    setLiked: setLiked,
    toggleLiked: toggleLiked,
    isLiked: isLiked,
    setLikedFromRating: setLikedFromRating,
    getPrefs: getPrefs,
    setPrefs: setPrefs,
    getLocalRating: getLocalRating,
    setLocalRating: setLocalRating,
    clearLocalRating: clearLocalRating
  };
})();
