/* Zinin Corp — auth (obfuscation only, NOT real security)
 * Sprint A 2026-05-03. Real protection = Cloudflare Access (separate sprint).
 * Hash chunks below decode at runtime; not robust against view-source.
 */
(function () {
  'use strict';

  // Hash split into 4 chunks, base64'd, reversed. Reassemble: join → reverse → atob
  var _h = ['==QYjVWO4IWNkNjZ1YGNhd', 'TOyQGOkZTOwYzY4YzMyEjN', '1MTYiZ2MxMmMzM2MjdTOmd', 'jYmJmY4YjNlVWOkZTZhhDO'];
  var _expected = atob(_h.join('').split('').reverse().join(''));
  var _key = 'zc_sess_v2'; // bumped from zc_auth — old sessions invalidated

  async function sha256(s) {
    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
    return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
  }

  function show(el)  { el.classList.remove('is-hidden'); }
  function hide(el)  { el.classList.add('is-hidden'); }

  document.addEventListener('DOMContentLoaded', function () {
    var overlay = document.getElementById('loginOverlay');
    var app     = document.getElementById('app');
    var input   = document.getElementById('passwordInput');
    var btn     = document.getElementById('loginBtn');
    var err     = document.getElementById('loginError');
    var signout = document.getElementById('signoutBtn');

    if (!overlay || !app) return;

    // Restore session
    if (localStorage.getItem(_key) === _expected) {
      hide(overlay); show(app);
    }

    async function attempt() {
      var h = await sha256(input.value);
      if (h === _expected) {
        localStorage.setItem(_key, _expected);
        hide(overlay); show(app); err.style.display = 'none';
      } else {
        err.style.display = 'block';
        input.value = ''; input.focus();
      }
    }

    btn && btn.addEventListener('click', attempt);
    input && input.addEventListener('keydown', function (e) { if (e.key === 'Enter') attempt(); });

    signout && signout.addEventListener('click', function () {
      localStorage.removeItem(_key);
      // also drop legacy key from old shell
      localStorage.removeItem('zc_auth');
      show(overlay); hide(app);
      input.value = ''; input.focus();
    });

    // Invalidate any legacy session under old hash
    if (localStorage.getItem('zc_auth')) {
      localStorage.removeItem('zc_auth');
    }
  });
})();
