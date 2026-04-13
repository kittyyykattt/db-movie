(function() {
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var box = document.getElementById('tmdb-discover');
  if (!box || !window.MovieAPI) return;

  var input = document.getElementById('hero-search-input');
  var btn = document.getElementById('tmdb-search-btn');
  var out = document.getElementById('tmdb-results');
  var statusEl = document.getElementById('tmdb-status');

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  function renderResults(items) {
    if (!out) return;
    if (!items || !items.length) {
      out.innerHTML = '<p class="tmdb-status">No TMDB results.</p>';
      return;
    }
    var html = '';
    items.forEach(function(m) {
      var title = escapeHtml(m.title || '');
      var year = m.release_year != null ? escapeHtml(String(m.release_year)) : '—';
      var poster = m.poster_url
        ? '<img src="' + escapeHtml(m.poster_url) + '" alt="" loading="lazy" />'
        : '<div class="poster-placeholder"><span class="poster-icon" aria-hidden="true">🎬</span></div>';
      var tid = m.tmdb_id;
      html += '<article class="tmdb-card movie-card" data-tmdb-id="' + tid + '">';
      html += '<div class="poster-wrap">' + poster + '</div>';
      html += '<div class="tmdb-card-body">';
      html += '<div class="title">' + title + '</div>';
      html += '<div class="tmdb-meta">' + year + '</div>';
      html += '<div class="tmdb-card-actions">';
      html += '<button type="button" class="btn btn-primary btn-sm tmdb-import" data-tmdb-id="' + tid + '">Add to catalog</button>';
      html += '<button type="button" class="btn btn-clear btn-sm tmdb-preview" data-tmdb-id="' + tid + '">Preview DB row</button>';
      html += '</div></div></article>';
    });
    out.innerHTML = html;

    out.querySelectorAll('.tmdb-preview').forEach(function(b) {
      b.addEventListener('click', function() {
        var id = b.getAttribute('data-tmdb-id');
        setStatus('Loading preview…');
        window.MovieAPI.tmdbPreview(id)
          .then(function(data) {
            console.info('TMDB → DB payload (for insertion)', data);
            setStatus('Preview logged to console (movie_row + credits).');
          })
          .catch(function() {
            setStatus('Preview failed.');
          });
      });
    });

    out.querySelectorAll('.tmdb-import').forEach(function(b) {
      b.addEventListener('click', function() {
        var id = b.getAttribute('data-tmdb-id');
        b.disabled = true;
        setStatus('Importing…');
        window.MovieAPI.importFromTmdb(id)
          .then(function(res) {
            if (res && res.movie_id) {
              window.location.href = '/movie/' + res.movie_id;
              return;
            }
            setStatus('Import response missing movie_id.');
            b.disabled = false;
          })
          .catch(function(err) {
            var msg = 'Import failed.';
            if (err && err.body && err.body.error) msg = String(err.body.error);
            setStatus(msg);
            b.disabled = false;
          });
      });
    });
  }

  function runSearch() {
    var q = (input && input.value) ? input.value.trim() : '';
    if (q.length < 2) {
      setStatus('Enter at least 2 characters.');
      return;
    }
    setStatus('Searching TMDB…');
    window.MovieAPI.tmdbSearch(q)
      .then(function(data) {
        if (data && data.error) {
          setStatus(String(data.error));
          return;
        }
        setStatus('');
        renderResults(Array.isArray(data) ? data : []);
        try {
          box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (_) {}
      })
      .catch(function() {
        setStatus('TMDB search failed.');
      });
  }

  if (btn) btn.addEventListener('click', runSearch);
  if (input) {
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        runSearch();
      }
    });
  }
})();
