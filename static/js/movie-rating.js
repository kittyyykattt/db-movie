(function() {
  function formatRatingLabel(v) {
    if (v == null || v === '' || Number.isNaN(v)) return '—';
    var n = Number(v);
    if (n === Math.floor(n)) return String(n);
    return n.toFixed(1);
  }

  function isValidHalfStep(n) {
    if (n < 0 || n > 5) return false;
    var x = Math.round(n * 2);
    return Math.abs(n * 2 - x) < 1e-9;
  }

  function initWidget(widget) {
    var movieId = widget.dataset.movieId;
    if (!movieId) return;

    var stars = widget.querySelectorAll('.rating-stars button');
    var valueText = widget.querySelector('.rating-value-text');
    var savedEl = widget.querySelector('.saved');
    var hintEl = document.getElementById('rating-local-hint');
    var clearBtn = widget.querySelector('#rating-clear-btn');
    var ratedValue = null;

    function setStarVisual(value) {
      stars.forEach(function(btn) {
        var i = parseInt(btn.dataset.starIndex, 10);
        btn.classList.remove('filled', 'is-half', 'hovered');
        if (value == null || value === '') return;
        var v = Number(value);
        if (v >= i) btn.classList.add('filled');
        else if (v >= i - 0.5) btn.classList.add('is-half');
      });
    }

    function setDisplay(value) {
      ratedValue = value;
      setStarVisual(value);
      if (valueText) {
        valueText.textContent =
          value == null || value === ''
            ? 'Your rating: —'
            : 'Your rating: ' + formatRatingLabel(value) + '/5';
      }
    }

    function persistRating(v) {
      if (hintEl) {
        hintEl.hidden = true;
        hintEl.textContent = '';
      }

      function showSaved() {
        if (savedEl) {
          savedEl.style.display = 'block';
          setTimeout(function() {
            savedEl.style.display = 'none';
          }, 2000);
        }
      }

      if (!window.MovieAPI) {
        if (window.MovieDB) {
          if (v === 0 || v === null) window.MovieDB.clearLocalRating(movieId);
          else window.MovieDB.setLocalRating(movieId, v);
        }
        setDisplay(v === null ? null : v);
        if (hintEl) {
          hintEl.textContent = 'Saved on this device only.';
          hintEl.hidden = false;
        }
        return;
      }

      if (v === 0 || v === null) {
        window.MovieAPI.deleteRating(Number(movieId))
          .then(function() {
            setDisplay(null);
            showSaved();
          })
          .catch(function(err) {
            if (err && err.status === 404) {
              setDisplay(null);
              return;
            }
            if (err && err.status === 401 && window.MovieDB) {
              window.MovieDB.clearLocalRating(movieId);
              setDisplay(null);
              if (hintEl) {
                hintEl.textContent =
                  'Cleared on this device. Sign in to update your account.';
                hintEl.hidden = false;
              }
              return;
            }
            if (valueText) {
              valueText.textContent =
                err && err.status === 401
                  ? 'Sign in to save ratings to the database.'
                  : 'Could not clear rating.';
            }
          });
        return;
      }

      window.MovieAPI.setRating(Number(movieId), v)
        .then(function() {
          setDisplay(v);
          showSaved();
        })
        .catch(function(err) {
          if (err && err.status === 401 && window.MovieDB) {
            window.MovieDB.setLocalRating(movieId, v);
            setDisplay(v);
            if (hintEl) {
              hintEl.textContent =
                'Saved on this device. Sign in (header) to store ratings in your account.';
              hintEl.hidden = false;
            }
            return;
          }
          if (valueText) {
            valueText.textContent =
              err && err.status === 401
                ? 'Sign in to save ratings to the database.'
                : 'Could not save rating.';
          }
        });
    }

    function previewAtButton(btn, clientX) {
      var i = parseInt(btn.dataset.starIndex, 10);
      var rect = btn.getBoundingClientRect();
      var half = clientX - rect.left < rect.width / 2;
      var preview = i - (half ? 0.5 : 0);
      stars.forEach(function(s) {
        var si = parseInt(s.dataset.starIndex, 10);
        s.classList.remove('hovered', 'is-half');
        if (preview >= si) s.classList.add('hovered');
        else if (preview >= si - 0.5) {
          s.classList.add('hovered');
          s.classList.add('is-half');
        }
      });
    }

    stars.forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        var i = parseInt(btn.dataset.starIndex, 10);
        var rect = btn.getBoundingClientRect();
        var half = e.clientX - rect.left < rect.width / 2;
        var v = i - (half ? 0.5 : 0);
        if (!isValidHalfStep(v)) return;
        persistRating(v);
      });
      btn.addEventListener('mouseenter', function(e) {
        previewAtButton(btn, e.clientX);
      });
      btn.addEventListener('mousemove', function(e) {
        previewAtButton(btn, e.clientX);
      });
    });

    var starRow = widget.querySelector('.rating-stars');
    if (starRow) {
      starRow.addEventListener('mouseleave', function() {
        setStarVisual(ratedValue);
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        persistRating(null);
      });
    }

    function loadRating() {
      var local = window.MovieDB ? window.MovieDB.getLocalRating(movieId) : null;
      if (!window.MovieAPI) {
        if (local != null) {
          setDisplay(local);
          if (hintEl) {
            hintEl.textContent = 'On this device only — sign in to use your account.';
            hintEl.hidden = false;
          }
        }
        return;
      }
      window.MovieAPI.getRating(Number(movieId))
        .then(function(r) {
          var server = r && r.rating_value != null ? Number(r.rating_value) : null;
          if (server != null && server >= 0 && server <= 5 && isValidHalfStep(server)) {
            setDisplay(server);
            return;
          }
          if (local != null) {
            setDisplay(local);
            if (hintEl) {
              hintEl.textContent =
                'Device-only rating — sign in to sync with your account.';
              hintEl.hidden = false;
            }
          }
        })
        .catch(function() {
          if (local != null) {
            setDisplay(local);
            if (hintEl) {
              hintEl.textContent = 'Could not reach server; showing device rating.';
              hintEl.hidden = false;
            }
          }
        });
    }

    loadRating();
  }

  document.querySelectorAll('.rating-widget').forEach(initWidget);
})();
