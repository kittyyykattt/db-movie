(function() {
  function initSearchUI(options) {
    options = options || {};
    var form = document.querySelector(options.formSelector || '#search-form');
    if (!form) return;

    function resolveSel(key, fallback) {
      if (key in options) {
        return options[key] ? document.querySelector(options[key]) : null;
      }
      return fallback ? document.querySelector(fallback) : null;
    }

    var panel = resolveSel('panelSelector', '#advanced-panel');
    var toggle = resolveSel('toggleSelector', '#advanced-toggle');
    var countEl = resolveSel('countSelector', '#advanced-count');
    var actionsEl = resolveSel('actionsSelector', '#search-actions');
    var savePrefs = options.savePrefs !== false;

    function countActiveFilters() {
      var count = 0;
      var inputs = form.querySelectorAll('input[name], select[name]');
      inputs.forEach(function(inp) {
        if (inp.type === 'checkbox') {
          if (inp.checked) {
            count++;
          }
          return;
        }
        if (inp.name === 'genre' && inp.tagName === 'SELECT') {
          if (inp.selectedOptions && inp.selectedOptions.length) {
            count += inp.selectedOptions.length;
          }
          return;
        }
        if (inp.value && String(inp.value).trim()) {
          count++;
        }
      });
      return count;
    }

    function updateUI() {
      var n = countActiveFilters();
      if (countEl) countEl.textContent = '(' + n + ')';
      if (actionsEl) actionsEl.style.display = n > 0 ? 'block' : 'none';
    }

    if (toggle && panel) {
      toggle.addEventListener('click', function() {
        var open = panel.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }

    form.addEventListener('input', updateUI);
    form.addEventListener('change', updateUI);
    updateUI();

    if (window.MovieDB) {
      if (savePrefs) {
        form.addEventListener('submit', function() {
          var sortBy = form.querySelector('select[name="sort_by"]');
          var lang = form.querySelector('select[name="language"]');
          if (sortBy && sortBy.value) window.MovieDB.setPrefs({ sortBy: sortBy.value });
          if (lang && lang.value) window.MovieDB.setPrefs({ language: lang.value });
        });
      }

      if (savePrefs) {
        var prefs = window.MovieDB.getPrefs();
        if (prefs.sortBy) {
          var s = form.querySelector('select[name="sort_by"]');
          if (s && s.querySelector('option[value="' + prefs.sortBy + '"]')) s.value = prefs.sortBy;
        }
        if (prefs.language) {
          var l = form.querySelector('select[name="language"]');
          if (l && l.querySelector('option[value="' + prefs.language + '"]')) l.value = prefs.language;
        }
      }
    }

    var genreMulti = form.querySelector('select[name="genre"][multiple]');
    if (genreMulti) {
      genreMulti.addEventListener('mousedown', function(e) {
        var target = e.target;
        if (!target || target.tagName !== 'OPTION') return;
        e.preventDefault();
        target.selected = !target.selected;
        updateUI();
      });
    }
  }

  window.SearchUI = {
    init: initSearchUI
  };
})();
