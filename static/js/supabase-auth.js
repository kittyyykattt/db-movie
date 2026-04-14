import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

function readConfig() {
  const el = document.getElementById('app-supabase-config');
  if (!el) return {};
  try {
    return JSON.parse(el.textContent.trim() || '{}');
  } catch (_) {
    return {};
  }
}

function showErr(el, msg) {
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.hidden = false;
  } else {
    el.textContent = '';
    el.hidden = true;
  }
}

async function syncFlaskSession(accessToken) {
  const res = await fetch('/auth/supabase', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ access_token: accessToken }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.error || res.statusText || 'Session sync failed');
    err.body = body;
    throw err;
  }
  return body;
}

const config = readConfig();
if (config.url && config.anonKey) {
  const supabase = createClient(config.url, config.anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });

  const dlg = document.getElementById('auth-dialog');
  const openBtn = document.getElementById('auth-open');
  const closeBtn = document.getElementById('auth-close');
  if (openBtn && dlg) {
    openBtn.addEventListener('click', function () {
      dlg.showModal();
    });
  }
  if (closeBtn && dlg) {
    closeBtn.addEventListener('click', function () {
      dlg.close();
    });
  }

  const loginForm = document.getElementById('auth-login-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const errEl = document.getElementById('auth-login-error');
      showErr(errEl, '');
      const fd = new FormData(loginForm);
      const email = String(fd.get('email') || '').trim();
      const password = String(fd.get('password') || '');
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        showErr(errEl, error.message);
        return;
      }
      if (!data.session) {
        showErr(errEl, 'No session returned.');
        return;
      }
      try {
        const body = await syncFlaskSession(data.session.access_token);
        window.location.href = body.redirect_to || '/';
      } catch (err) {
        showErr(errEl, err.message || 'Could not start app session.');
      }
    });
  }

  const regForm = document.getElementById('auth-register-form');
  if (regForm) {
    regForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const errEl = document.getElementById('auth-register-error');
      showErr(errEl, '');
      const fd = new FormData(regForm);
      const email = String(fd.get('email') || '').trim();
      const password = String(fd.get('password') || '');
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) {
        showErr(errEl, error.message);
        return;
      }
      if (data.session) {
        try {
          const body = await syncFlaskSession(data.session.access_token);
          window.location.href = body.redirect_to || '/';
        } catch (err) {
          showErr(errEl, err.message || 'Could not start app session.');
        }
      } else {
        showErr(
          errEl,
          'If email confirmation is enabled in Supabase, check your inbox—then sign in here.'
        );
      }
    });
  }

  document.querySelectorAll('a.auth-logout').forEach(function (a) {
    a.addEventListener('click', async function (e) {
      e.preventDefault();
      await supabase.auth.signOut();
      window.location.href = a.getAttribute('href') || '/logout';
    });
  });
}
