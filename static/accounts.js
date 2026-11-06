'use strict';

/* Аккаунты устройства: один раз вошёл с паролем — дальше переключение в одно касание.
   Токены лежат в HttpOnly-куке на сервере, страница их не видит. */
(function () {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const initials = (n) => String(n || '?').split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

  async function call(path, body) {
    const res = await fetch(path, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || 'Не получилось');
    return data.data;
  }

  const list = () => call('/api/accounts').catch(() => []);
  const switchTo = (login, company) => call('/api/accounts/switch', { логин: login, цех: company });
  const forget = (login, company) => call('/api/accounts/forget', { логин: login, цех: company });
  const logout = () => fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});

  function close() { document.querySelectorAll('.v2acc-menu').forEach((m) => m.remove()); }

  // меню под кнопкой: список аккаунтов, «Добавить», «Выйти»
  async function open(anchor, opts = {}) {
    if (document.querySelector('.v2acc-menu')) { close(); return; }
    const menu = document.createElement('div');
    menu.className = 'v2acc-menu';
    menu.innerHTML = '<div class="v2acc-load">…</div>';
    document.body.appendChild(menu);
    const place = () => {
      const r = anchor.getBoundingClientRect();
      menu.style.top = `${Math.round(r.bottom + 8)}px`;
      menu.style.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`;
    };
    place();
    const accs = await list();
    menu.innerHTML = `
      <div class="v2acc-h">Аккаунты на этом устройстве</div>
      ${accs.map((a) => `
        <div class="v2acc-row ${a.текущий ? 'cur' : ''}" data-v2acc-login="${esc(a.логин)}" data-v2acc-company="${esc(a.цех)}">
          <i>${esc(initials(a.фио || a.логин))}</i>
          <span><b>${esc(a.фио || a.логин)}</b><span>${esc(a.роль_название)} · ${esc(a.логин)} · ${esc(a.цех)}</span></span>
          ${a.текущий ? '<em>сейчас</em>' : '<button type="button" class="v2acc-x" data-v2acc-forget title="Забыть на этом устройстве">×</button>'}
        </div>`).join('') || '<div class="v2acc-load">Пока только вы</div>'}
      <button type="button" class="v2acc-btn" data-v2acc-add>+ Добавить аккаунт</button>
      <button type="button" class="v2acc-btn danger" data-v2acc-out>Выйти из этого аккаунта</button>`;
    place();
    menu.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const row = ev.target.closest('[data-v2acc-login]');
      try {
        if (ev.target.closest('[data-v2acc-forget]') && row) {
          await forget(row.dataset.v2accLogin, row.dataset.v2accCompany);
          close(); open(anchor, opts); return;
        }
        if (row && !row.classList.contains('cur')) {
          if (opts.beforeLeave && !opts.beforeLeave()) return;
          await switchTo(row.dataset.v2accLogin, row.dataset.v2accCompany);
          location.href = opts.after || location.pathname;
          return;
        }
        if (ev.target.closest('[data-v2acc-add]')) {
          if (opts.beforeLeave && !opts.beforeLeave()) return;
          location.href = '/?add=1'; return;
        }
        if (ev.target.closest('[data-v2acc-out]')) {
          if (!confirm('Выйти из этого аккаунта на этом устройстве?')) return;
          await logout();
          const rest = await list();
          if (rest.length) { await switchTo(rest[0].логин, rest[0].цех); location.href = opts.after || location.pathname; }
          else location.href = '/';
        }
      } catch (err) { alert(err.message); }
    });
  }

  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('.v2acc-menu') && !ev.target.closest('[data-v2acc-anchor]')) close();
  });
  window.addEventListener('resize', close);

  window.V2Acc = { list, switchTo, forget, open, close, initials };
})();
