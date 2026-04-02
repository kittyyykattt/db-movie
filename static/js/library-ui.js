(function() {
  function initLibraryUI(options) {
    options = options || {};
    var grid = document.querySelector(options.gridSelector || '#library-grid');
    var empty = document.querySelector(options.emptySelector || '#library-empty');
    var tabs = document.querySelectorAll(options.tabsSelector || '.library-tab');
    var statsRow = document.querySelector(options.statsSelector || '#library-stats');
    var sortSelect = document.querySelector(options.sortSelector || '#library-sort');
    var filterPillsWrap = document.querySelector(options.filterSelector || '#library-filter-pills');
    var activeClass = options.activeClass || 'is-active';
    var initialTab = options.initialTab || 'liked';
    var activeTab = initialTab;
    var activeSort = 'recent';
    var activeGenre = 'all';
    var currentMovies = [];

    if (!grid || !empty) return;

    function escapeHtml(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function genrePlaceholderBackground(genre) {
      var paletteByGenre = {
        'sci-fi': { bg: 'linear-gradient(135deg, #5f5cff, #9d4edd)', chipBg: '#d6ccff', chipText: '#40208f' },
        'science fiction': { bg: 'linear-gradient(135deg, #5f5cff, #9d4edd)', chipBg: '#d6ccff', chipText: '#40208f' },
        drama: { bg: 'linear-gradient(135deg, #0f766e, #14b8a6)', chipBg: '#b7efe4', chipText: '#0f4f4d' },
        romance: { bg: 'linear-gradient(135deg, #b45309, #f59e0b)', chipBg: '#ffe3b8', chipText: '#7a4406' },
        thriller: { bg: 'linear-gradient(135deg, #7f1d1d, #b91c1c)', chipBg: '#f9c5c5', chipText: '#6b1515' },
        action: { bg: 'linear-gradient(135deg, #991b1b, #ef4444)', chipBg: '#ffc4c4', chipText: '#751616' },
        comedy: { bg: 'linear-gradient(135deg, #0369a1, #38bdf8)', chipBg: '#cdeeff', chipText: '#104e78' },
        horror: { bg: 'linear-gradient(135deg, #3f3f46, #71717a)', chipBg: '#d6d6dc', chipText: '#3f3f46' },
        documentary: { bg: 'linear-gradient(135deg, #15803d, #4ade80)', chipBg: '#c7f7d7', chipText: '#146134' },
        mystery: { bg: 'linear-gradient(135deg, #312e81, #4338ca)', chipBg: '#d7d4ff', chipText: '#332890' },
        crime: { bg: 'linear-gradient(135deg, #334155, #475569)', chipBg: '#dbe3ec', chipText: '#334155' }
      };
      return paletteByGenre[String(genre || '').toLowerCase()] || { bg: 'linear-gradient(135deg, #1f2937, #374151)', chipBg: '#dde3ec', chipText: '#334155' };
    }

    function idsForTab(tabName) {
      if (!window.MovieDB) return [];
      return tabName === 'saved' ? window.MovieDB.getWatchLater() : window.MovieDB.getLiked();
    }

    function idsForActiveTab() {
      return idsForTab(activeTab);
    }

    function updateTabCounts() {
      var likedCount = idsForTab('liked').length;
      var savedCount = idsForTab('saved').length;
      var likedEl = document.querySelector('[data-count-for="liked"]');
      var savedEl = document.querySelector('[data-count-for="saved"]');
      if (likedEl) likedEl.textContent = '(' + likedCount + ')';
      if (savedEl) savedEl.textContent = '(' + savedCount + ')';
    }

    function fetchMoviesForIds(ids) {
      if (!ids.length) return Promise.resolve([]);
      var done = 0;
      var out = [];
      return new Promise(function(resolve) {
        ids.forEach(function(id, index) {
          fetch('/api/movies/' + id)
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(movie) {
              if (movie) {
                movie._addedIndex = index;
                out.push(movie);
              }
              done++;
              if (done === ids.length) resolve(out);
            })
            .catch(function() {
              done++;
              if (done === ids.length) resolve(out);
            });
        });
      });
    }

    function buildGenreFilters(movies) {
      if (!filterPillsWrap) return;
      var unique = {};
      movies.forEach(function(movie) {
        var label = movie.genre_name || '';
        if (label) unique[label] = true;
      });
      var labels = Object.keys(unique).sort();
      var html = '<button type="button" class="genre-filter-pill ' + (activeGenre === 'all' ? 'is-active' : '') + '" data-genre="all">All</button>';
      labels.forEach(function(label) {
        var val = label.toLowerCase();
        html += '<button type="button" class="genre-filter-pill ' + (activeGenre === val ? 'is-active' : '') + '" data-genre="' + val + '">' + escapeHtml(label) + '</button>';
      });
      filterPillsWrap.innerHTML = html;
      filterPillsWrap.querySelectorAll('.genre-filter-pill').forEach(function(btn) {
        btn.addEventListener('click', function() {
          activeGenre = btn.getAttribute('data-genre') || 'all';
          buildGenreFilters(currentMovies);
          renderCards();
        });
      });
    }

    function sortMovies(movies) {
      var copy = movies.slice();
      if (activeSort === 'title_asc') {
        copy.sort(function(a, b) { return String(a.title || '').localeCompare(String(b.title || '')); });
      } else if (activeSort === 'genre') {
        copy.sort(function(a, b) { return String(a.genre_name || '').localeCompare(String(b.genre_name || '')); });
      } else if (activeSort === 'year_desc') {
        copy.sort(function(a, b) { return Number(b.release_year || 0) - Number(a.release_year || 0); });
      } else {
        copy.sort(function(a, b) { return Number(b._addedIndex || 0) - Number(a._addedIndex || 0); });
      }
      return copy;
    }

    function filteredMovies(movies) {
      if (activeGenre === 'all') return movies;
      return movies.filter(function(movie) {
        return String(movie.genre_name || '').toLowerCase().indexOf(activeGenre) >= 0;
      });
    }

    function renderStats() {
      if (!statsRow || !window.MovieDB) return;
      var likedIds = idsForTab('liked');
      fetchMoviesForIds(likedIds).then(function(likedMovies) {
        var genres = {};
        var avg = 0;
        likedMovies.forEach(function(movie) {
          if (movie.genre_name) genres[movie.genre_name] = true;
          avg += Number(movie.average_rating || 0);
        });
        var avgRating = likedMovies.length ? (avg / likedMovies.length).toFixed(1) : '0.0';
        statsRow.innerHTML =
          '<span class="library-stat">' + likedIds.length + ' watched</span>' +
          '<span class="library-stat">' + Object.keys(genres).length + ' genres</span>' +
          '<span class="library-stat">Avg rating ' + avgRating + '★</span>';
      });
    }

    function renderCard(movie, isLikedTab) {
      var genres = (movie.genre_names || (movie.genre_name ? [movie.genre_name] : [])).slice(0, 3);
      var palette = genrePlaceholderBackground(movie.genre_name);
      var genreHtml = genres.map(function(g) {
        var chipPalette = genrePlaceholderBackground(g);
        return '<span class="genre-pill library-genre-pill" style="background:' + chipPalette.chipBg + '; color:' + chipPalette.chipText + '; border-color:' + chipPalette.chipText + '33;">' + escapeHtml(g) + '</span>';
      }).join('');
      var moveLabel = isLikedTab ? 'Move to Saved for Later' : 'Move to Watched & Liked';

      var card = document.createElement('article');
      card.className = 'movie-card library-card';
      card.setAttribute('data-movie-id', movie.movie_id);
      card.setAttribute('data-genre', (movie.genre_name || '').toLowerCase());
      card.setAttribute('data-tab-source', activeTab);
      card.innerHTML =
        '<button type="button" class="btn-favorite ' + (isLikedTab ? 'is-liked-heart is-favorite' : '') + '" aria-label="Saved state" title="Saved state">' + (isLikedTab ? '♥' : '♡') + '</button>' +
        '<button type="button" class="library-card-menu-trigger" aria-label="Card options">⋯</button>' +
        '<div class="library-card-menu">' +
          '<button type="button" data-action="remove">Remove from Library</button>' +
          '<button type="button" data-action="move">' + moveLabel + '</button>' +
        '</div>' +
        '<a href="/movie/' + movie.movie_id + '">' +
          '<div class="poster-wrap" data-primary-genre="' + (movie.genre_name || '') + '">' +
            (movie.poster_url ? '<img src="' + movie.poster_url + '" alt="" loading="lazy" />' : '<div class="poster-placeholder"><span class="poster-icon" aria-hidden="true">🎬</span></div>') +
          '</div>' +
          '<div class="info">' +
            '<div class="title">' + escapeHtml(movie.title || '') + '</div>' +
            '<div class="meta">' + escapeHtml(movie.release_year || '') + (movie.genre_name ? ' · ' + escapeHtml(movie.genre_name) : '') + '</div>' +
            (genreHtml ? '<div class="genre-pills">' + genreHtml + '</div>' : '') +
            '<span class="view-details view-details-btn">View Details</span>' +
          '</div>' +
        '</a>';
      var placeholder = card.querySelector('.poster-placeholder');
      if (placeholder) placeholder.style.background = palette.bg;
      return card;
    }

    function applySingleLayoutClass() {
      grid.classList.toggle('favorites-grid-single', grid.querySelectorAll('.library-card').length === 1);
    }

    function renderCards() {
      var visible = sortMovies(filteredMovies(currentMovies));
      if (!visible.length) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        applySingleLayoutClass();
        return;
      }
      empty.style.display = 'none';
      grid.innerHTML = '';
      visible.forEach(function(item) {
        grid.appendChild(renderCard(item, activeTab === 'liked'));
      });
      applySingleLayoutClass();
    }

    function switchTab(tabName) {
      activeTab = tabName;
      grid.classList.add('is-switching');
      setTimeout(function() {
        render();
        grid.classList.remove('is-switching');
      }, 150);
    }

    function render() {
      updateTabCounts();
      renderStats();
      var ids = idsForActiveTab();
      if (!ids.length) {
        currentMovies = [];
        buildGenreFilters(currentMovies);
        renderCards();
        return;
      }
      empty.style.display = 'none';
      grid.innerHTML = '<div class="loading-state"><span class="loading-spinner"></span><p>Loading...</p></div>';
      fetchMoviesForIds(ids).then(function(movies) {
        currentMovies = movies;
        buildGenreFilters(currentMovies);
        renderCards();
      });
    }

    tabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        tabs.forEach(function(t) { t.classList.remove(activeClass); });
        tab.classList.add(activeClass);
        switchTab(tab.getAttribute('data-tab') || initialTab);
      });
    });

    if (sortSelect) {
      sortSelect.addEventListener('change', function() {
        activeSort = sortSelect.value || 'recent';
        renderCards();
      });
    }

    grid.addEventListener('click', function(e) {
      var menuBtn = e.target.closest('.library-card-menu-trigger');
      if (menuBtn) {
        e.preventDefault();
        e.stopPropagation();
        var cardForMenu = menuBtn.closest('.library-card');
        if (!cardForMenu) return;
        grid.querySelectorAll('.library-card').forEach(function(card) {
          if (card !== cardForMenu) card.classList.remove('is-menu-open');
        });
        cardForMenu.classList.toggle('is-menu-open');
        return;
      }

      var actionBtn = e.target.closest('.library-card-menu button');
      if (!actionBtn) return;
      e.preventDefault();
      e.stopPropagation();
      var card = actionBtn.closest('.library-card');
      if (!card || !window.MovieDB) return;
      var movieId = Number(card.getAttribute('data-movie-id'));
      var action = actionBtn.getAttribute('data-action');
      var sourceTab = card.getAttribute('data-tab-source');

      if (action === 'remove') {
        if (sourceTab === 'liked' && window.MovieDB.isLiked(movieId)) window.MovieDB.toggleLiked(movieId);
        if (sourceTab === 'saved' && window.MovieDB.isWatchLater(movieId)) window.MovieDB.toggleWatchLater(movieId);
      } else if (action === 'move') {
        if (sourceTab === 'liked') {
          if (window.MovieDB.isLiked(movieId)) window.MovieDB.toggleLiked(movieId);
          if (!window.MovieDB.isWatchLater(movieId)) window.MovieDB.toggleWatchLater(movieId);
        } else {
          if (window.MovieDB.isWatchLater(movieId)) window.MovieDB.toggleWatchLater(movieId);
          if (!window.MovieDB.isLiked(movieId)) window.MovieDB.toggleLiked(movieId);
        }
      }
      render();
    });

    document.addEventListener('click', function() {
      grid.querySelectorAll('.library-card').forEach(function(card) {
        card.classList.remove('is-menu-open');
      });
    });

    render();
    window.addEventListener('storage', function(e) {
      if (e.key === 'moviedb_favorites' || e.key === 'moviedb_liked') {
        render();
      }
    });
  }

  window.LibraryUI = {
    init: initLibraryUI
  };
})();
