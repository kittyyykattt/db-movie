(function() {
  var hosts = document.querySelectorAll('.unified-like-host');
  if (!hosts.length) return;

  function showStatus(el, msg) {
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.hidden = false;
    } else {
      el.textContent = '';
      el.hidden = true;
    }
  }

  function isSignedIn() {
    return !!document.querySelector('.auth-logout');
  }

  function updateBtn(btn, liked) {
    btn.textContent = liked ? 'Liked' : 'Like';
    btn.classList.toggle('is-liked', liked);
  }

  function bindHost(host) {
    var grid = host.querySelector('.unified-like-grid');
    if (!grid) return;
    var statusEl = host.querySelector('.search-like-status');

    grid.querySelectorAll('.movie-card-unified-search').forEach(function(card) {
      var btn = card.querySelector('.search-like-btn');
      if (!btn) return;
      var source = card.getAttribute('data-search-source');

      if (source === 'catalog') {
        var mid = card.getAttribute('data-movie-id');
        if (window.MovieDB && mid) {
          updateBtn(btn, window.MovieDB.isLiked(mid));
        }
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          if (!window.MovieDB || !mid) return;
          var on = window.MovieDB.toggleLiked(mid);
          updateBtn(btn, on);
          showStatus(statusEl, '');
        });
        return;
      }

      var tid = card.getAttribute('data-tmdb-id');
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        if (!tid) return;
        if (!isSignedIn()) {
          showStatus(statusEl, 'Sign in to like titles from the web and save them to your catalog.');
          return;
        }
        if (!window.MovieAPI || !window.MovieAPI.likeFromTmdb) return;
        btn.disabled = true;
        showStatus(statusEl, 'Saving…');
        window.MovieAPI.likeFromTmdb(tid)
          .then(function(res) {
            if (window.MovieDB && res && res.movie_id) {
              window.MovieDB.toggleLiked(res.movie_id);
            }
            window.location.reload();
          })
          .catch(function(err) {
            btn.disabled = false;
            var m = 'Could not save that title.';
            if (err && err.body && err.body.error) m = String(err.body.error);
            showStatus(statusEl, m);
          });
      });
    });
  }

  hosts.forEach(bindHost);
})();
