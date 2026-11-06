/* Проект V2.1 · портал швейного цеха */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (n) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 });
const money = (n) => nf(n) + ' сом';
const num = (n) => Number(n || 0);

const COLORS = {
  'чёрный': '#2b2b2e', 'черный': '#2b2b2e', 'белый': '#f2f2f4', 'серый': '#9a9aa0',
  'синий': '#2f5fd0', 'голубой': '#7fb6e8', 'оранжевый': '#e2711d', 'красный': '#c0392b',
  'зелёный': '#2e7d32', 'бежевый': '#d8c6a8', 'жёлтый': '#e8c547', 'коричневый': '#7b5233',
};
const swatch = (name) => COLORS[String(name || '').toLowerCase().trim()] || '#d9d9de';

const STATE = { me: null, caps: {}, company: null, roles: {}, periods: [], route: 'dash' };

// ------------------------------------------------------------------ api
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) { STATE.me = null; renderLogin(); throw new Error('Войдите заново'); }
  const type = res.headers.get('Content-Type') || '';
  if (!type.includes('json')) return res;
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || 'Ошибка');
  return data;
}

function toast(text, kind = '') {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = text;
  box.appendChild(el);
  setTimeout(() => el.remove(), 3400);
}

const guard = (p) => p.catch((e) => toast(e.message || 'Ошибка', 'err'));

// ------------------------------------------------------------------ login
function renderOfflineStart() {
  $('#app').innerHTML = `<div class="login-wrap"><div class="login-card" style="text-align:center">
    <div class="need-net" style="padding:26px 18px 6px">
      <svg viewBox="0 0 24 24"><path d="M2 8.8a16 16 0 0 1 20 0"/><path d="M5.5 12.4a11 11 0 0 1 13 0"/><path d="M9 16a6 6 0 0 1 6 0"/><circle cx="12" cy="19" r="1.2"/><path d="M3 3l18 18"/></svg>
      <h3>Нет связи с сервером</h3>
      <p>Проверьте Wi-Fi и убедитесь, что на MacBook запущен «Проект V2.command».</p>
    </div>
    <button class="btn primary" id="offline-retry" style="margin:16px 0 4px">Повторить</button>
    <div class="hint" style="margin-top:14px">Склад, загруженный ранее, откроется без сети.</div>
  </div></div>`;
  $('#offline-retry').addEventListener('click', () => location.reload());
}

// аккаунты, которые входили на этом устройстве (без паролей) — для быстрого переключения
function savedAccounts() {
  try { return JSON.parse(localStorage.getItem('v2_accounts') || '[]').filter((a) => a && a.логин); } catch (e) { return []; }
}
function rememberAccount(acc) {
  try {
    const all = savedAccounts();
    const old = all.find((a) => a.логин === acc.логин && a.цех === acc.цех) || {};
    const list = all.filter((a) => !(a.логин === acc.логин && a.цех === acc.цех));
    list.unshift({ ...old, ...acc });
    localStorage.setItem('v2_accounts', JSON.stringify(list.slice(0, 12)));
  } catch (e) { /* нет хранилища */ }
}
function forgetAccount(login, company) {
  try {
    localStorage.setItem('v2_accounts', JSON.stringify(savedAccounts().filter((a) => !(a.логин === login && a.цех === company))));
  } catch (e) { /* нет хранилища */ }
}

async function renderLogin() {
  document.title = 'Вход · ' + BRAND.название;
  const quick = window.V2Acc ? await window.V2Acc.list() : [];
  const adding = new URLSearchParams(location.search).get('add') === '1';
  $('#app').className = 'login';
  let companies = [];
  try { companies = (await api('/api/companies')).data; } catch (e) { /* нет сети */ }
  const first = companies[0] || null;

  $('#app').innerHTML = `
    <div class="login-card">
      <div class="login-mark">${brandMark('logo')}</div>
      <h1>${esc(BRAND.название)}</h1>
      <div class="sub">Выберите цех и войдите по логину и паролю из карточки сотрудника.</div>
      ${quick.length ? `<div class="acc-list"><div class="acc-h">${adding ? 'Уже вошли на этом устройстве — переключиться без пароля' : 'Войти без пароля — уже входили на этом устройстве'}</div>
        ${quick.map((a) => `<div class="acc quick" data-quick-login="${esc(a.логин)}" data-quick-company="${esc(a.цех)}">
          <i>${esc((a.фио || a.логин).split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase())}</i>
          <span><b>${esc(a.фио || a.логин)}</b><span>${esc(a.логин)} · ${esc(a.роль_название)} · ${esc(a.цех)}</span></span>
          <em>${a.текущий ? 'сейчас' : 'войти →'}</em>
        </div>`).join('')}</div>` : ''}
      ${adding ? '<div class="acc-h" style="margin:2px 2px 8px">Добавить аккаунт: выберите цех и введите логин и пароль</div>' : ''}
      ${savedAccounts().filter((a) => !quick.some((q) => q.логин === a.логин && q.цех === a.цех)).length ? `<div class="acc-list"><div class="acc-h">Входили раньше — нажмите и введите пароль</div>
        ${savedAccounts().filter((a) => !quick.some((q) => q.логин === a.логин && q.цех === a.цех)).map((a) => `<div class="acc" data-acc-login="${esc(a.логин)}" data-acc-company="${esc(a.цех || '')}">
          <i>${esc((a.фио || a.логин).split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase())}</i>
          <span><b>${esc(a.фио || a.логин)}</b><span>${esc(a.логин)}${a.роль_название ? ' · ' + esc(a.роль_название) : ''}${a.цех ? ' · ' + esc(a.цех) : ''}</span></span>
          <button type="button" class="acc-x" data-acc-forget title="Убрать из списка">×</button>
        </div>`).join('')}</div>` : ''}
      <div class="company-list">
        ${companies.map((c) => `
          <button class="company ${first && c['код'] === first['код'] ? 'on' : ''}" data-company="${esc(c['код'])}">
            <i>${esc(String(c['код']).replace(/\D/g, '') || String(c['код']).slice(0, 2))}</i>
            <span><b>${esc(c['название'])}</b><span>${esc(c['город'] || '')} · код ${esc(c['код'])}</span></span>
          </button>`).join('') || '<div class="hint">Нет активных цехов в companies.xlsx</div>'}
      </div>
      <form id="login-form">
        <div class="field"><label>Логин</label>
          <input class="input" name="логин" autocomplete="username" required autofocus placeholder="boss"></div>
        <div class="field"><label>Пароль</label>
          <input class="input" name="пароль" type="password" autocomplete="current-password" required placeholder="••••••"></div>
        <button class="btn primary" type="submit" style="height:42px;margin-top:4px">Войти</button>
      </form>
    </div>`;

  let company = first ? first['код'] : '';

  $$('[data-company]').forEach((b) => b.addEventListener('click', () => {
    company = b.dataset.company;
    $$('[data-company]').forEach((x) => x.classList.toggle('on', x === b));
  }));

  $$('[data-quick-login]').forEach((el) => el.addEventListener('click', async () => {
    try {
      await window.V2Acc.switchTo(el.dataset.quickLogin, el.dataset.quickCompany);
      location.href = '/';
    } catch (err) { toast(err.message, 'err'); }
  }));

  $$('[data-acc-login]').forEach((el) => el.addEventListener('click', (ev) => {
    const login = el.dataset.accLogin, comp = el.dataset.accCompany;
    if (ev.target.closest('[data-acc-forget]')) { forgetAccount(login, comp); renderLogin(); return; }
    if (comp) {
      const b = $(`[data-company="${CSS.escape(comp)}"]`);
      if (b) b.click();
    }
    $('#login-form [name="логин"]').value = login;
    $$('[data-acc-login]').forEach((x) => x.classList.toggle('on', x === el));
    $('#login-form [name="пароль"]').value = '';
    $('#login-form [name="пароль"]').focus();
  }));

  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 'цех': company, 'логин': fd.get('логин'), 'пароль': fd.get('пароль') }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Не пускает');
      const u = data.user || (data.data && data.data.user) || {};
      rememberAccount({ цех: company, логин: String(fd.get('логин')).trim(), фио: u.фио || '', роль_название: u.роль_название || '' });
      await boot();
    } catch (err) { toast(err.message, 'err'); }
  });

}

// ------------------------------------------------------------------ shell
const ICONS = {
  dash: '<rect x="2.5" y="2.5" width="4.6" height="4.6" rx="1.2"/><rect x="8.9" y="2.5" width="4.6" height="4.6" rx="1.2"/><rect x="2.5" y="8.9" width="4.6" height="4.6" rx="1.2"/><rect x="8.9" y="8.9" width="4.6" height="4.6" rx="1.2"/>',
  tasks: '<path d="M3 4.5h10M3 8h10M3 11.5h6"/>',
  batches: '<circle cx="4.6" cy="11.4" r="1.7"/><circle cx="4.6" cy="4.6" r="1.7"/><path d="M5.9 5.7 13 12M5.9 10.3 13 4"/>',
  materials: '<path d="M2.5 6 8 2.6 13.5 6v7L8 16.4 2.5 13Z"/><path d="M2.5 6 8 9.4 13.5 6M8 9.4v7"/>',
  finished: '<path d="M2.5 4.5h11v9h-11z"/><path d="M2.5 8h11"/>',
  payroll: '<rect x="2" y="4" width="12" height="8.4" rx="1.8"/><circle cx="8" cy="8.2" r="1.7"/>',
  analytics: '<path d="M2.5 13.4h11"/><rect x="3.6" y="8.4" width="2.6" height="5"/><rect x="7" y="5" width="2.6" height="8.4"/><rect x="10.4" y="2.6" width="2.6" height="10.8"/>',
  users: '<circle cx="6" cy="6" r="2.3"/><path d="M2.4 13c0-2 1.6-3.3 3.6-3.3s3.6 1.3 3.6 3.3"/><path d="M10.6 4a2.1 2.1 0 0 1 0 4.1"/><path d="M11.5 9.9c1.4.4 2.2 1.5 2.2 3"/>',
  ann: '<path d="M3 6.6v2.8l6.8 3.4V3.2Z"/><path d="M9.8 5.6h2.4a1.4 1.4 0 0 1 0 2.8H9.8"/><path d="M4.4 9.8v3.4"/>',
  report: '<path d="M4 2.5h5l3 3v8H4Z"/><path d="M9 2.5v3h3"/><path d="M6 9h4M6 11.4h4"/>',
  bag: '<path d="M3.2 5.4h9.6l.9 8.4a1.2 1.2 0 0 1-1.2 1.3H3.5a1.2 1.2 0 0 1-1.2-1.3Z"/><path d="M5.8 5.4V4a2.2 2.2 0 0 1 4.4 0v1.4"/>',
  receipt: '<path d="M4 2.5h8v11l-2-1.4-2 1.4-2-1.4-2 1.4Z"/><path d="M6 5.5h4M6 8h4M6 10.5h2"/>',
  wh: '<path d="M2.5 5.5 8 2.5l5.5 3v7L8 15.5 2.5 12.5Z"/><path d="M2.5 5.5 8 8.5l5.5-3M8 8.5v7"/>',
};

const NAV = [
  { id: 'dash', label: 'Сводка', icon: 'dash', roles: ['admin', 'manager', 'technologist', 'storekeeper', 'accountant', 'prod'] },
  { id: 'tasks', label: 'Мои задачи', icon: 'tasks', roles: ['prod', 'technologist'] },
  { id: 'batches', label: 'Партии', icon: 'batches', roles: ['admin', 'manager', 'technologist', 'storekeeper', 'accountant', 'prod'] },
  { id: 'cex', label: 'Цех', icon: 'tasks', roles: ['admin', 'manager', 'technologist', 'cutter', 'packer', 'prod', 'accountant', 'storekeeper', 'designer', 'supply'], href: '/cex/' },
  { id: 'orders', label: 'Мои заказы', icon: 'receipt', roles: ['client'] },
  { id: 'fbs', label: 'Заказы WB', icon: 'receipt', roles: ['admin', 'manager', 'storekeeper'] },
  { id: 'wh', label: 'Склад', icon: 'wh', roles: ['admin', 'manager', 'storekeeper', 'accountant', 'technologist', 'prod'] },
  { id: 'materials', label: 'Материалы', icon: 'materials', roles: ['admin', 'manager', 'storekeeper', 'accountant', 'technologist'] },
  { id: 'finished', label: 'Готовая продукция', icon: 'finished', roles: ['admin', 'manager', 'storekeeper', 'accountant'] },
  { id: 'shop', label: 'Магазин', icon: 'bag', roles: ['admin', 'manager', 'storekeeper', 'accountant', 'technologist', 'prod', 'client'] },
  { id: 'sales', label: 'Продажи', icon: 'receipt', roles: ['admin', 'manager', 'storekeeper', 'accountant'] },
  { id: 'payroll', label: 'Зарплата', icon: 'payroll', roles: ['admin', 'manager', 'accountant', 'prod', 'technologist'] },
  { id: 'analytics', label: 'Аналитика', icon: 'analytics', roles: ['admin', 'manager', 'accountant'] },
  { id: 'users', label: 'Сотрудники', icon: 'users', roles: ['admin', 'manager'] },
  { id: 'ann', label: 'Объявления', icon: 'ann', roles: ['admin', 'manager', 'technologist', 'storekeeper', 'accountant', 'prod'] },
  { id: 'report', label: 'Отчёт', icon: 'report', roles: ['admin', 'manager', 'accountant'] },
];

const TITLES = {
  dash: 'Сводка', tasks: 'Мои задачи', batches: 'Партии', batch: 'Партия',
  materials: 'Материалы', finished: 'Готовая продукция', payroll: 'Зарплата',
  analytics: 'Аналитика', users: 'Сотрудники', ann: 'Объявления', report: 'Отчёт',
  shop: 'Магазин', sales: 'Продажи', wh: 'Склад', orders: 'Мои заказы', fbs: 'Заказы WB',
};

function tabbarHtml(nav, active) {
  const primary = nav.slice(0, 4);
  const rest = nav.slice(4);
  const item = (n) => `<a href="${n.href || '#/' + n.id}" class="tabbtn ${n.id === active ? 'on' : ''}" data-tab="${n.id}">
      <svg viewBox="0 0 16 16" stroke-linecap="round" stroke-linejoin="round">${ICONS[n.icon]}</svg>
      <span>${n.label}</span></a>`;
  return `<nav class="tabbar" id="tabbar">
    ${primary.map(item).join('')}
    ${rest.length ? `<button type="button" class="tabbtn" id="tab-more">
      <svg viewBox="0 0 16 16" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="3.4" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.6" cy="8" r="1.3"/>
      </svg><span>Ещё</span></button>` : ''}
  </nav>
  ${rest.length ? `<div class="sheet-wrap" id="sheet-more" hidden>
    <div class="sheet-scrim" data-sheet-close></div>
    <div class="sheet">
      <div class="sheet-grab"></div>
      ${rest.map((n) => `<a class="sheet-row" href="${n.href || '#/' + n.id}">
        <svg viewBox="0 0 16 16" stroke-linecap="round" stroke-linejoin="round">${ICONS[n.icon]}</svg>
        <span>${n.label}</span></a>`).join('')}
      <button class="sheet-row danger" id="sheet-logout">Выйти из аккаунта</button>
    </div>
  </div>` : ''}`;
}

function bindTabbar() {
  const more = $('#tab-more');
  const sheet = $('#sheet-more');
  if (more && sheet) {
    more.addEventListener('click', () => { sheet.hidden = false; requestAnimationFrame(() => sheet.classList.add('open')); });
  }
  if (sheet) {
    sheet.querySelectorAll('[data-sheet-close], .sheet-row').forEach((el) => {
      el.addEventListener('click', () => {
        sheet.classList.remove('open');
        setTimeout(() => { sheet.hidden = true; }, 220);
      });
    });
    const out = $('#sheet-logout');
    if (out) out.addEventListener('click', () => logout());
  }

  // долгое нажатие: усиленное стекло + лёгкое увеличение
  $$('.tabbtn').forEach((btn) => {
    let timer = null;
    const down = () => {
      timer = setTimeout(() => {
        btn.classList.add('press');
        if (navigator.vibrate) navigator.vibrate(12);
      }, 130);
    };
    const up = () => {
      clearTimeout(timer);
      btn.classList.remove('press');
    };
    btn.addEventListener('pointerdown', down);
    btn.addEventListener('pointerup', up);
    btn.addEventListener('pointerleave', up);
    btn.addEventListener('pointercancel', up);
  });
}

function needNetHtml() {
  return `<div class="card"><div class="need-net">
    <svg viewBox="0 0 24 24"><path d="M2 8.8a16 16 0 0 1 20 0"/><path d="M5.5 12.4a11 11 0 0 1 13 0"/><path d="M9 16a6 6 0 0 1 6 0"/><circle cx="12" cy="19" r="1.2"/><path d="M3 3l18 18"/></svg>
    <h3>Нужен интернет</h3>
    <p>Этот раздел работает только онлайн — данные приходят с сервера в реальном времени.<br>
       Офлайн доступен только «Склад».</p>
    <button class="btn primary" id="net-retry">Повторить</button>
  </div></div>`;
}

function bindNeedNet() {
  const b = $('#net-retry');
  if (b) b.addEventListener('click', () => go(STATE.route, STATE.param));
}

function visibleNav(role) {
  // все роли человека добавляют свои разделы; производственные (Оверлок, Карман…) — это «prod»
  const mine = (STATE.me && STATE.me.роль === role && STATE.me.роли_портала) || [role];
  const all = NAV.filter((n) => n.roles.some((r) => mine.includes(r)));
  const allowed = role === 'client' ? (STATE.clientVisible || []) : (STATE.visible || null);
  if (!Array.isArray(allowed) || !allowed.length) {
    return role === 'client' ? [] : all;
  }
  return all.filter((n) => allowed.includes(n.id));
}

function renderShell() {
  const role = STATE.me.роль;
  const cexOnly = ['cutter', 'packer', 'prod', 'designer', 'supply'];
  if ((STATE.me.роли_портала || [role]).every((r) => cexOnly.includes(r))) { location.replace('/cex/'); return; }
  let nav = visibleNav(role);
  const canWh = !!(STATE.caps && STATE.caps['wh.view']);
  if (MODE.sklad && canWh) nav = nav.filter((n) => n.id === 'wh');
  if (!nav.length) {
    $('#app').innerHTML = `<div class="login-wrap"><div class="login-card" style="text-align:center">
      <div class="need-net" style="padding:26px 18px 8px">
        <h3>Раздел пока недоступен</h3>
        <p>Для вашей роли разделы ещё не включены. Обратитесь к администратору.</p>
      </div>
      <button class="btn" id="logout-only">Выйти</button></div></div>`;
    const o = $('#logout-only');
    if (o) o.addEventListener('click', () => logout());
    return;
  }
  const initials = (STATE.me.фио || '?').split(' ').filter(Boolean).slice(0, 2)
    .map((w) => w[0]).join('').toUpperCase();
  const active = STATE.route === 'batch' ? 'batches' : STATE.route;

  document.title = (TITLES[STATE.route] || 'Портал') + ' · ' + BRAND.название;
  const pickMode = /#\/wh\/pick\/\d+/.test(location.hash);
  $('#app').className = 'shell' + (pickMode ? ' pickmode' : '');
  $('#app').innerHTML = `
    <aside class="side">
      <div class="brand"><i>${brandMark('logo')}</i><div><b>${esc(BRAND.название)}</b><span>${esc(BRAND.подзаголовок || (STATE.company ? STATE.company['название'] : ''))}</span></div></div>
      <nav class="nav">
        ${nav.map((n) => `<a href="${n.href || '#/' + n.id}" class="${n.id === active ? 'on' : ''}">
          <svg viewBox="0 0 16 16" stroke-linecap="round" stroke-linejoin="round">${ICONS[n.icon]}</svg>
          <span>${n.label}</span></a>`).join('')}
      </nav>
      <div class="foot">
        <div class="who"><b>${esc(STATE.me.фио)}</b>${esc(STATE.me.роль_название)}</div>
        <button id="logout">Выйти</button>
      </div>
    </aside>
    <div class="main">
      <header class="top">
        <h2>${TITLES[STATE.route] || ''}</h2>
        <div class="right">
          <span class="pill grey">${esc(STATE.me.цех)}</span>
          ${(STATE.caps && STATE.caps['wh.view']) ? syncChipHtml() : ''}
          <button class="v2acc-anchor" id="acc-top" data-v2acc-anchor title="Аккаунты">
            <span class="avatar">${esc(initials)}</span><span class="v2acc-name">${esc(STATE.me.фио)}</span>
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 6l4 4 4-4"/></svg>
          </button>
        </div>
      </header>
      <main class="page" id="page"></main>
      ${nav.length > 1 ? tabbarHtml(nav, active) : ''}
    </div>`;

  bindTabbar();

  const accTop = $('#acc-top');
  if (accTop && window.V2Acc) accTop.addEventListener('click', () => window.V2Acc.open(accTop, { after: '/' }));

  $('#logout').addEventListener('click', () => logout());
}

async function logout() {
  try { await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }); } catch (e) {}
  STATE.me = null;
  STATE.caps = null;
  WH.meta = null;
  SHOP.data = null;
  SHOP.корзина.clear();
  // устройство может быть общим: стираем режим и офлайн-данные прошлого пользователя
  MODE.sklad = false;
  SYNC.snap = null;
  SYNC.queue = [];
  SYNC.rejected = [];
  SYNC.last = '';
  ['v2mode', 'v2me', 'v2snap', 'v2queue', 'v2rejected', 'v2last'].forEach((k) => {
    try { localStorage.removeItem(k); } catch (e) {}
  });
  location.hash = '';
  renderLogin();
}

async function afterLogin() {
  try { await syncNow(false); } catch (e) { /* без связи — работаем офлайн */ }
}

// Раздел портала по умолчанию: «Цех» — отдельная страница, в него уходим только по клику,
// иначе кнопка «‹ Портал» в цехе сразу возвращает обратно и склад недоступен.
function homeRoute(allowed) { return allowed.find((id) => id !== 'cex') || allowed[0] || 'wh'; }

async function go(route, param) {
  if (route === 'cex') { location.href = '/cex/'; return; }
  if (STATE.me) {
    const allowed = visibleNav(STATE.me.роль).map((n) => n.id);
    if (route !== 'batch' && !allowed.includes(route)) {
      route = homeRoute(allowed);
      param = undefined;
    }
  }
  LAST_HASH = location.hash || '#/dash';
  if (SHOP.timer) { clearInterval(SHOP.timer); SHOP.timer = null; }
  STATE.route = route;
  syncLoad();
  renderShell();
  const page = $('#page');
  page.innerHTML = '<div class="empty">Загрузка…</div>';
  try {
    const html = await PAGES[route](param);
    page.innerHTML = html;
    bind(route, param);
    enhanceSelects(page);
  } catch (e) {
    page.innerHTML = `<div class="card"><div class="card-b"><div class="notice">${esc(e.message)}</div></div></div>`;
  }
}

// ------------------------------------------------------------------ ui bits
const kpi = (k, v, m = '', cls = '') => `
  <div class="kpi ${cls}"><div class="k">${esc(k)}</div><div class="v">${v}</div><div class="m">${m}</div></div>`;

const pill = (text, color = '') => `<span class="pill ${color}">${esc(text)}</span>`;

const progress = (pct, done) => `
  <div class="progress ${done ? 'done' : ''}"><i style="width:${Math.max(3, Math.min(100, pct))}%"></i></div>`;

function modal({ title, body, submit = 'Сохранить', wide = false, onSubmit, noSubmit = false }) {
  const root = $('#modal-root');
  root.innerHTML = `
    <div class="overlay" id="ov">
      <div class="modal ${wide ? 'wide' : ''}">
        <div class="modal-h"><h3>${esc(title)}</h3><button class="x" id="mx">×</button></div>
        <form id="mf">
          <div class="modal-b">${body}</div>
          ${noSubmit ? '' : `<div class="modal-f"><button type="button" class="btn" id="mc">Отмена</button>
            <button class="btn primary" type="submit">${esc(submit)}</button></div>`}
        </form>
      </div>
    </div>`;
  const close = () => { root.innerHTML = ''; };
  $('#mx').onclick = close;
  if ($('#mc')) $('#mc').onclick = close;
  $('#ov').addEventListener('click', (e) => { if (e.target.id === 'ov') close(); });
  const form = $('#mf');
  if (!onSubmit) {
    form.addEventListener('submit', (e) => e.preventDefault());
    return { close };
  }
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const data = {};
    $$('[name]', form).forEach((el) => {
      if (el.dataset.multi) {
        data[el.name] = data[el.name] || [];
        if (el.checked) data[el.name].push(el.value);
      } else if (el.type === 'checkbox') {
        data[el.name] = el.checked;
      } else {
        data[el.name] = el.value;
      }
    });
    try { await onSubmit(data, fd); close(); } catch (err) { toast(err.message, 'err'); }
  });
  return { close };
}

function timeAgo(startStr) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})$/.exec(String(startStr));
  if (!m) return '';
  const start = new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]);
  const mins = Math.max(0, Math.round((Date.now() - start.getTime()) / 60000));
  if (mins < 60) return mins + ' мин';
  return Math.floor(mins / 60) + ' ч ' + (mins % 60) + ' мин';
}

// ------------------------------------------------------------------ pages
const PAGES = {};

PAGES.dash = async () => {
  const { data } = await api('/api/dashboard');
  const role = STATE.me.роль;
  const tasks = data['мои_задачи'] || [];
  const wip = data['незавершёнка'] || {};
  const wipRows = Object.entries(wip).filter(([, v]) => v > 0);
  const worker = (STATE.me.роли_портала || []).includes('prod') || role === 'technologist';

  const kpis = worker ? `
    ${kpi('Мои задачи', tasks.length, tasks.length ? 'в работе сейчас' : 'свободно')}
    ${kpi('Сдано штук', nf(data['моя_выработка']['штук']), 'за всё время')}
    ${kpi('Заработано', money(data['моя_выработка']['сумма']), 'сдельно', 'ok')}
    ${kpi('Оценка качества', data['оценка_средняя'] ? data['оценка_средняя'] + ' / 5' : '—', 'проверок: ' + data['проверок'])}`
    : `
    ${kpi('Партий', data['партий'], 'в работе: ' + data['в_работе'])}
    ${kpi('Штук в производстве', nf(data['штук']), 'на складе: ' + nf(data['на_складе']))}
    ${kpi('Отгружено', nf(data['отгружено']), 'свободно: ' + nf(Math.max(0, num(data['на_складе']) - num(data['отгружено']))), 'ok')}
    ${kpi('Оценка технолога', data['оценка_средняя'] ? data['оценка_средняя'] + ' / 5' : '—', 'проверок: ' + data['проверок'])}`;

  return `
    <div class="hero">
      <div>
        <h1>${greeting()},<br><em>${esc((STATE.me.фио || '').split(' ')[0])}</em></h1>
        <div class="sub">${new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })} · ${esc(STATE.company['название'])}</div>
      </div>
      <div class="actions">
        ${STATE.caps['batches.create'] ? '<button class="btn primary" data-act="new-batch">Новая партия</button>' : ''}
        ${worker ? '<a class="btn" href="#/tasks">Мои задачи</a>' : '<a class="btn" href="#/batches">Все партии</a>'}
      </div>
    </div>
    <div class="kpis">${kpis}</div>
    ${tasks.length ? `
      <div class="card">
        <div class="card-h"><h3>В работе прямо сейчас</h3><div class="spacer"></div><a class="more" href="#/tasks">Все задачи</a></div>
        <div class="card-b"><div class="tasks">
          ${tasks.map((t) => `
            <div class="task">
              <div class="th"><b>#${t['партия']} · ${esc(t['артикул'])}</b></div>
              <div class="meta"><span>${esc(t['название'])}</span><span>${esc(t['цвет'])} / ${esc(t['размер'])}</span></div>
              <div class="meta"><span>начато: <b>${esc(String(t['начало']).slice(-5))}</b></span><span class="timer">${timeAgo(t['начало'])}</span></div>
              <div class="btn-row">
                <button class="btn primary sm" data-act="finish" data-arg="${t['pass_id']}">Завершить</button>
                <button class="btn sm" data-act="minus" data-arg="${t['pass_id']}">Минус 1</button>
              </div>
            </div>`).join('')}
        </div></div>
      </div>` : ''}
    <div class="split">
      <div class="card">
        <div class="card-h"><h3>Последние партии</h3><div class="spacer"></div><a class="more" href="#/batches">Все</a></div>
        <div class="card-b tight">
          <div class="blist">
            ${data['последние'].map(bitem).join('') || '<div class="empty">Партий пока нет</div>'}
          </div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-h"><h3>Незавершённое производство</h3></div>
          <div class="card-b">
            ${wipRows.length ? wipRows.map(([name, v]) => `
              <div class="kv"><span>${esc(name)}</span><b>${v} разд.</b></div>`).join('') : '<div class="hint">Всё разобрано</div>'}
          </div>
        </div>
        ${data['материалов'] !== undefined ? `
        <div class="card">
          <div class="card-h"><h3>Материалы</h3></div>
          <div class="card-b">
            <div class="kv"><span>Позиций</span><b>${data['материалов']}</b></div>
            <div class="kv"><span>Сумма остатков</span><b>${money(data['материалы_сумма'])}</b></div>
            <a class="btn" href="#/materials" style="width:100%;margin-top:8px">Открыть склад</a>
          </div>
        </div>` : ''}
      </div>
    </div>`;
};

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер';
}

function bitem(b) {
  return `
    <a class="bitem" href="#/batch/${b['номер']}">
      <div>
        <div class="top-line">
          <b>#${b['номер']} · ${esc(b['артикул'])}</b>
          ${pill(b['статус'], b['статус'] === 'закрыта' ? 'green' : 'blue')}
          <span class="cell-sub">${b['разделов']} разд. · ${nf(b['штук'])} шт</span>
        </div>
        <div class="sub">${esc(b['клиент'] || 'без клиента')} · создана ${esc(b['дата_создания'])}${b['срок'] ? ' · срок ' + esc(b['срок']) : ''}</div>
        ${progress(b['прогресс'], b['прогресс'] >= 100)}
      </div>
      <div style="text-align:right">
        <div class="cell-main">${b['прогресс']}%</div>
        <div class="cell-sub">${b['этапов']} этапов</div>
      </div>
    </a>`;
}

PAGES.tasks = async () => {
  const { data } = await api('/api/tasks');
  const mine = data.filter((t) => t['тип'] === 'в работе');
  const free = data.filter((t) => t['тип'] === 'можно взять');
  return `
    <div class="hero">
      <div><h1>Мои задачи</h1><div class="sub">Взял задачу — пошёл таймер. Закончил — начислилась сдельная оплата.</div></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>В работе</h3><div class="spacer"></div>${pill(mine.length + ' шт', 'orange')}</div>
      <div class="card-b"><div class="tasks">
        ${mine.map((t) => `
          <div class="task">
            <div class="th"><b>#${t['партия']} · ${esc(t['артикул'])}</b></div>
            <div class="meta"><span>${esc(t['название'])}</span><span>${esc(t['цвет'])} · тон ${esc(t['тон'])} · ${esc(t['размер'])}</span></div>
            <div class="meta"><span>${nf(t['количество'])} шт × ${nf(t['тариф'])} сом</span><span class="timer">${timeAgo(t['начало'])}</span></div>
            <div class="btn-row">
              <button class="btn primary sm" data-act="finish" data-arg="${t['pass_id']}">Завершить · ${money(num(t['количество']) * num(t['тариф']))}</button>
              <button class="btn sm" data-act="minus" data-arg="${t['pass_id']}">Минус 1</button>
            </div>
          </div>`).join('') || '<div class="empty">Сейчас ничего не в работе</div>'}
      </div></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Можно взять</h3><div class="spacer"></div>${pill(free.length + ' шт', 'blue')}</div>
      <div class="card-b"><div class="tasks">
        ${free.map((t) => `
          <div class="task">
            <div class="th"><b>#${t['партия']} · ${esc(t['артикул'])}</b></div>
            <div class="meta"><span>${esc(t['название'])}</span><span>${esc(t['цвет'])} · тон ${esc(t['тон'])} · ${esc(t['размер'])}</span></div>
            <div class="meta"><span>${nf(t['количество'])} шт × ${nf(t['тариф'])} сом</span><b>${money(num(t['количество']) * num(t['тариф']))}</b></div>
            <button class="btn dark sm" data-act="take" data-batch="${t['партия']}" data-sec="${t['раздел']}" data-proc="${esc(t['процесс'])}">Взять в работу</button>
          </div>`).join('') || '<div class="empty">Свободных операций нет — жди предыдущий этап</div>'}
      </div></div>
    </div>`;
};

PAGES.batches = async () => {
  const { data } = await api('/api/batches');
  const total = data.reduce((s, b) => s + num(b['штук']), 0);
  return `
    <div class="hero">
      <div><h1>Партии</h1><div class="sub">${data.length} партий · ${nf(total)} изделий · разделы с цветом, тоном и размерами</div></div>
      <div class="actions">
        ${STATE.caps['batches.create'] ? '<button class="btn primary" data-act="new-batch">Новая партия</button>' : ''}
      </div>
    </div>
    <div class="card"><div class="card-b tight"><div class="blist">
      ${data.map(bitem).join('') || '<div class="empty">Партий пока нет — создайте первую</div>'}
    </div></div></div>`;
};

PAGES.batch = async (batchNum) => {
  const { data } = await api('/api/batches/' + batchNum);
  const chain = data['цепочка'] || [];
  return `
    <div class="hero">
      <div>
        <div class="sub" style="margin-bottom:6px"><a href="#/batches">← Партии</a></div>
        <h1>#${data['номер']} · ${esc(data['артикул'])}</h1>
        <div class="sub">${esc(data['клиент'] || 'без клиента')} · создана ${esc(data['дата_создания'])}${data['срок'] ? ' · срок ' + esc(data['срок']) : ''}</div>
      </div>
      <div class="actions">
        ${pill(data['статус'], data['статус'] === 'закрыта' ? 'green' : 'blue')}
        ${pill(nf(data['штук']) + ' шт', 'grey')}
        ${pill(data['разделов'] + ' разделов', 'grey')}
      </div>
    </div>
    <div class="kpis">
      ${kpi('Готовность', data['прогресс'] + '%', 'этапов в цепочке: ' + data['этапов'])}
      ${kpi('На складе', nf(data['на_складе']), 'принято кладовщиком', 'ok')}
      ${kpi('Отгружено', nf(data['отгружено']), 'покупателям')}
      ${kpi('Свободно', nf(Math.max(0, num(data['на_складе']) - num(data['отгружено']))), 'можно отгрузить')}
    </div>
    ${data['примечание'] ? `<div class="notice">${esc(data['примечание'])}</div>` : ''}
    <div class="card">
      <div class="card-h"><h3>Цепочка процессов</h3><div class="spacer"></div>
        <span class="hint">настраивается в processes.xlsx</span></div>
      <div class="card-b"><div class="btn-row">
        ${chain.map((p, i) => `
          <span class="pill ${i === 0 ? 'blue' : 'grey'}" title="зависит от: ${p['зависимости'].join(', ') || '—'}">
            ${i + 1}. ${esc(p['название'])}${p['тариф'] ? ' · ' + nf(p['тариф']) + ' сом' : ''}
          </span>`).join('')}
      </div></div>
    </div>
    <div class="sections">
      ${data['разделы'].map((s, idx) => sectionCard(data['номер'], s, idx)).join('')}
    </div>`;
};

function sectionCard(numBatch, s, idx) {
  const steps = s['шаги'] || [];
  const doneCount = steps.filter((x) => x['статус'] === 'готово').length;
  return `
    <div class="section ${idx === 0 ? 'open' : ''}" data-section="${s['раздел']}">
      <div class="section-h">
        <div class="swatch" style="background:${swatch(s['цвет'])}"></div>
        <div class="t">
          <b>Раздел ${s['раздел']} · ${esc(s['цвет'])}</b>
          <div>тон ${esc(s['тон'] || '—')} · размер ${esc(s['размер'])} · ${nf(s['количество'])} шт</div>
        </div>
        ${pill(doneCount + ' / ' + steps.length, doneCount === steps.length ? 'green' : 'grey')}
        <span class="chev">›</span>
      </div>
      <div class="section-b">
        <div class="steps">
          ${steps.map((st, i) => stepRow(numBatch, s['раздел'], st, i)).join('')}
        </div>
        ${s['оценки'] && s['оценки'].length ? `
          <div class="sep"></div>
          <div class="hint" style="margin-bottom:6px">Проверки технолога</div>
          ${s['оценки'].map((c) => `<div class="kv"><span>${esc(c['дата'])} · ${esc(c['комментарий'] || '—')}</span><b>${'★'.repeat(num(c['оценка']))}</b></div>`).join('')}
        ` : ''}
        ${STATE.caps['checks.create'] ? `
          <div class="btn-row" style="margin-top:10px">
            <button class="btn sm" data-act="check" data-batch="${numBatch}" data-sec="${s['раздел']}">Оценить раскрой</button>
          </div>` : ''}
      </div>
    </div>`;
}

function stepRow(numBatch, sec, st, i) {
  const state = st['статус'];
  const cls = state === 'готово' ? 'done' : state === 'работает' ? 'active' : state === 'ждёт зависимости' ? 'waiting' : '';
  const mini = st['зависимости'].length ? ' · после ' + st['зависимости'].join(', ') : '';
  let act = '';
  if (state === 'можно взять' && STATE.caps['passes.take']) {
    act = `<button class="btn dark tiny" data-act="take" data-batch="${numBatch}" data-sec="${sec}" data-proc="${esc(st['код'])}">Взять</button>`;
  } else if (state === 'работает') {
    act = `<span class="pill orange">${esc(st['исполнитель'])}</span>`;
  } else if (state === 'готово') {
    act = `<span class="pill green">${nf(st['сделано'])} шт</span>`;
  } else {
    act = `<span class="pill grey">ждёт</span>`;
  }
  return `
    <div class="step ${cls}">
      <div class="n">${state === 'готово' ? '✓' : i + 1}</div>
      <div class="body">
        <b>${esc(st['название'])}</b>
        <div class="sub">${st['тариф'] ? 'тариф ' + nf(st['тариф']) + ' сом/шт' : 'без оплаты'}${mini}${state === 'работает' ? ' · с ' + esc(String(st['начало']).slice(-5)) : ''}</div>
      </div>
      <div class="act">${act}</div>
    </div>`;
}

PAGES.materials = async () => {
  const { data, moves } = await api('/api/materials');
  const sum = data.reduce((s, i) => s + num(i['сумма']), 0);
  const low = data.filter((i) => num(i['количество']) <= 20);
  return `
    <div class="hero">
      <div><h1>Материалы</h1><div class="sub">${data.length} позиций · остатки на ${money(sum)}</div></div>
      <div class="actions">
        ${STATE.caps['materials.move'] ? '<button class="btn primary" data-act="move" data-kind="приход">Приход</button>' : ''}
        ${STATE.caps['materials.move'] ? '<button class="btn" data-act="move" data-kind="расход">Расход</button>' : ''}
        ${STATE.caps['materials.move'] ? '<button class="btn" data-act="new-item">Новый артикул</button>' : ''}
      </div>
    </div>
    ${low.length ? `<div class="notice">Заканчивается: ${low.map((i) => `${esc(i['артикул'])} (${nf(i['количество'])} ${esc(i['ед'])})`).join(', ')}</div>` : ''}
    <div class="card"><div class="card-b tight tablescroll">
      <table class="resp">
        <thead><tr><th>Артикул</th><th>Наименование</th><th class="num">Остаток</th><th class="num">Цена</th><th class="num">Сумма</th><th>Поставщик</th><th></th></tr></thead>
        <tbody>${data.map((i) => `<tr>
          <td data-l="Артикул"><b>${esc(i['артикул'])}</b></td>
          <td data-l="Наименование">${esc(i['название'])}</td>
          <td data-l="Остаток" class="num"><b>${nf(i['количество'])}</b> <span class="muted">${esc(i['ед'])}</span></td>
          <td data-l="Цена" class="num">${nf(i['цена'])}</td>
          <td data-l="Сумма" class="num">${money(i['сумма'])}</td>
          <td data-l="Поставщик">${esc(i['поставщик'] || '—')}</td>
          <td>${STATE.caps['materials.move'] ? `<button class="btn tiny" data-act="move-one" data-arg="${esc(i['артикул'])}">Движение</button>` : ''}</td>
        </tr>`).join('') || '<tr><td colspan="7" class="empty">Склад пуст</td></tr>'}</tbody>
      </table>
    </div></div>
    <div class="card">
      <div class="card-h"><h3>Движения</h3><div class="spacer"></div><span class="hint">последние ${moves.length}</span></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>Дата</th><th>Артикул</th><th>Тип</th><th class="num">Кол-во</th><th>Партия</th><th>Кто</th><th>Комментарий</th></tr></thead>
          <tbody>${moves.map((m) => `<tr>
            <td data-l="Дата">${esc(m['дата'])}</td>
            <td data-l="Артикул">${esc(m['артикул'])}</td>
            <td data-l="Тип">${pill(m['тип'], m['тип'] === 'приход' ? 'green' : 'orange')}</td>
            <td data-l="Кол-во" class="num">${nf(m['количество'])}</td>
            <td data-l="Партия">${m['партия'] ? '#' + esc(m['партия']) : '—'}</td>
            <td data-l="Кто">${esc(m['кто'] || '')}</td>
            <td data-l="Комментарий" class="muted">${esc(m['комментарий'] || '')}</td>
          </tr>`).join('') || '<tr><td colspan="7" class="empty">Движений нет</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
};

PAGES.finished = async () => {
  const res = await api('/api/finished');
  const data = res.data;
  const shipments = res['отгрузки'];
  const free = data.reduce((s, g) => s + Math.max(0, num(g['принято']) - num(g['отгружено'])), 0);
  return `
    <div class="hero">
      <div><h1>Готовая продукция</h1><div class="sub">Принято на склад и отгружено покупателям</div></div>
      <div class="actions"><span class="pill green">Свободно ${nf(free)} шт</span></div>
    </div>
    <div class="card"><div class="card-b tight tablescroll">
      <table class="resp">
        <thead><tr><th>Партия</th><th>Изделие</th><th class="num">Принято</th><th class="num">Отгружено</th><th class="num">Свободно</th><th class="num">Сумма отгрузки</th><th></th></tr></thead>
        <tbody>${data.map((g) => {
          const rest = Math.max(0, num(g['принято']) - num(g['отгружено']));
          return `<tr>
            <td data-l="Партия"><a href="#/batch/${g['партия']}"><b>#${g['партия']}</b></a></td>
            <td data-l="Изделие">${esc(g['артикул'])}</td>
            <td data-l="Принято" class="num">${nf(g['принято'])}</td>
            <td data-l="Отгружено" class="num">${nf(g['отгружено'])}</td>
            <td data-l="Свободно" class="num"><b>${nf(rest)}</b></td>
            <td data-l="Сумма" class="num">${money(g['сумма'])}</td>
            <td>${STATE.caps['shipments.create'] && rest > 0 ? `<button class="btn tiny primary" data-act="ship" data-arg="${g['партия']}" data-free="${rest}">Отгрузить</button>` : ''}</td>
          </tr>`;
        }).join('') || '<tr><td colspan="7" class="empty">Пока ничего не принято на склад</td></tr>'}</tbody>
      </table>
    </div></div>
    <div class="card">
      <div class="card-h"><h3>Отгрузки</h3></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>Дата</th><th>Партия</th><th class="num">Количество</th><th>Покупатель</th><th class="num">Сумма</th></tr></thead>
          <tbody>${shipments.map((s) => `<tr>
            <td data-l="Дата">${esc(s['дата'])}</td>
            <td data-l="Партия">#${esc(s['партия'])}</td>
            <td data-l="Количество" class="num">${nf(s['количество'])}</td>
            <td data-l="Покупатель">${esc(s['покупатель'] || '—')}</td>
            <td data-l="Сумма" class="num">${money(s['сумма'])}</td>
          </tr>`).join('') || '<tr><td colspan="5" class="empty">Отгрузок не было</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
};

PAGES.payroll = async () => {
  const { data } = await api('/api/payroll');
  const periods = STATE.periods;
  const canAll = STATE.caps['payroll.all'];
  return `
    <div class="hero">
      <div><h1>${canAll ? 'Зарплата' : 'Мой заработок'}</h1>
        <div class="sub">Сдельно: каждая операция по своему тарифу из processes.xlsx</div></div>
    </div>
    <div class="card">
      <div class="card-b" style="padding-top:16px">
        <div class="btn-row">
          <button class="btn sm primary" data-period="">Весь месяц</button>
          ${periods.map((p) => `<button class="btn sm" data-period="${esc(p['код'])}">${esc(p['название'])}</button>`).join('')}
        </div>
        <div class="hint" id="period-hint" style="margin-top:8px">Периоды выплат задаются в periods.xlsx</div>
      </div>
      <div class="card-b tight tablescroll" id="payroll-table">
        ${payrollTable(data, canAll)}
      </div>
    </div>`;
};

function payrollTable(data, canAll) {
  return `
    <div class="kpis" style="margin:6px 0 10px">
      ${kpi('К выплате', money(data['итого']), data['месяц'] + (data['границы'][0] ? ' · ' + data['границы'][0] + ' — ' + data['границы'][1] : ''), 'ok')}
      ${kpi('Сотрудников', data['данные'].length, canAll ? 'по цеху' : 'только вы')}
    </div>
    <table class="resp">
      <thead><tr><th>Сотрудник</th><th>Роль</th><th class="num">Операций</th><th class="num">Штук</th><th class="num">К выплате</th></tr></thead>
      <tbody>${data['данные'].map((r) => `<tr>
        <td data-l="Сотрудник"><div class="cell-main">${esc(r['фио'])}</div><div class="cell-sub">${esc(r['логин'])}</div></td>
        <td data-l="Роль">${pill(r['роль'], 'grey')}</td>
        <td data-l="Операций" class="num">${r['операций']}</td>
        <td data-l="Штук" class="num">${nf(r['штук'])}</td>
        <td data-l="К выплате" class="num"><b>${money(r['сумма'])}</b></td>
      </tr>`).join('') || '<tr><td colspan="5" class="empty">Нет данных</td></tr>'}</tbody>
    </table>`;
}

PAGES.analytics = async () => {
  const { data } = await api('/api/analytics');
  const speed = Object.entries(data['скорость'] || {});
  const ratings = Object.entries(data['оценки'] || {});
  return `
    <div class="hero"><div><h1>Аналитика</h1><div class="sub">Производительность, качество и незавершённое производство</div></div></div>
    <div class="kpis">
      ${kpi('Партий', data['партий'], 'изделий: ' + nf(data['штук']))}
      ${kpi('Готово', nf(data['готово_штук']), 'принято на склад', 'ok')}
      ${kpi('Отгружено', nf(data['отгружено']), money(data['отгрузки_сумма']))}
      ${kpi('Сдельно начислено', money(data['сдельно']), 'по всем операциям')}
    </div>
    <div class="split">
      <div>
        <div class="card">
          <div class="card-h"><h3>Скорость по процессам</h3><div class="spacer"></div><span class="hint">среднее время, часы</span></div>
          <div class="card-b">
            ${speed.length ? speed.map(([code, hours]) => `
              <div class="kv"><span>${esc(code)}</span><b>${nf(hours)} ч</b></div>`).join('') : '<div class="hint">Пока нет завершённых операций</div>'}
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Незавершённое производство</h3></div>
          <div class="card-b">
            ${Object.entries(data['незавершёнка']).map(([k, v]) => `<div class="kv"><span>${esc(k)}</span><b>${v} разд.</b></div>`).join('')}
          </div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-h"><h3>Оценки технолога</h3><div class="spacer"></div>
            ${data['оценка_средняя'] ? pill(data['оценка_средняя'] + ' / 5', 'green') : ''}</div>
          <div class="card-b">
            ${ratings.length ? ratings.map(([name, r]) => `<div class="kv"><span>${esc(name)}</span><b>${nf(r)} / 5</b></div>`).join('') : '<div class="hint">Проверок ещё не было</div>'}
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Последние проверки</h3></div>
          <div class="card-b">
            ${(data['последние_проверки'] || []).map((c) => `
              <div class="kv"><span>#${esc(c['партия'])} · разд. ${esc(c['раздел'])} · ${esc(c['комментарий'] || '—')}</span>
              <b>${'★'.repeat(num(c['оценка']))}</b></div>`).join('') || '<div class="hint">Пусто</div>'}
          </div>
        </div>
      </div>
    </div>`;
};

PAGES.users = async () => {
  const { data } = await api('/api/users');
  return `
    <div class="hero">
      <div><h1>Сотрудники</h1><div class="sub">Доступ выдаёт начальник: логин и пароль</div></div>
      <div class="actions"><button class="btn primary" data-act="new-user">Добавить</button></div>
    </div>
    ${STATE.caps['users.manage'] ? `
    <div class="card">
      <div class="card-h"><h3>Оформление</h3><div class="spacer"></div>
        <span class="hint">название и логотип</span></div>
      <div class="card-b">
        <div class="grid2">
          <div class="field"><label>Название</label>
            <input class="input" id="brand-name" value="${esc(BRAND.название)}"></div>
          <div class="field"><label>Подзаголовок</label>
            <input class="input" id="brand-sub" value="${esc(BRAND.подзаголовок)}" placeholder="например, цех №1"></div>
        </div>
        <div class="field"><label>Логотип</label>
          <input class="input" id="brand-logo" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml">
          <div class="hint" style="margin-top:6px">PNG/JPG/WEBP/SVG, до 2 МБ. Квадратный, лучше 512×512 на прозрачном фоне.</div>
        </div>
        <div class="btn-row" style="margin-top:10px">
          <button class="btn primary" data-act="save-brand">Сохранить оформление</button>
        </div>
        <div class="hint" style="margin-top:8px">Эти же значения можно править в Excel — лист «настройки».</div>
      </div>
    </div>` : ''}
    <div class="card"><div class="card-b tight tablescroll">
      <div class="hint" style="padding:10px 14px">Логины, пароли и роли хранятся в Excel — лист «сотрудники». Список ниже читается оттуда.</div>
      <table class="resp">
        <thead><tr><th>ФИО</th><th>Логин</th><th>Роль</th><th>Статус</th><th></th></tr></thead>
        <tbody>${data.map((u) => `<tr>
          <td data-l="ФИО"><div class="cell-main">${esc(u['фио'])}</div></td>
          <td data-l="Логин"><span class="mono">${esc(u['логин'])}</span></td>
          <td data-l="Роль">${pill(u['роль_название'], 'grey')}</td>
          <td data-l="Статус">${u['активен'] ? pill('доступ открыт', 'green') : pill('закрыт', 'red')}</td>
          <td><button class="btn tiny" data-act="edit-user" data-arg="${esc(u['логин'])}">Изменить</button></td>
        </tr>`).join('')}</tbody>
      </table>
    </div></div>`;
};

PAGES.ann = async () => {
  const { data } = await api('/api/announcements');
  return `
    <div class="hero"><div><h1>Объявления</h1><div class="sub">${data.length} сообщений цеха</div></div></div>
    ${STATE.caps['announce.create'] ? `
      <div class="card"><div class="card-b" style="padding-top:16px">
        <form data-form="ann" class="row">
          <div class="field grow"><label>Текст</label>
            <textarea class="input" name="текст" placeholder="Что нужно сообщить смене?" required></textarea></div>
          <button class="btn primary">Опубликовать</button>
        </form>
      </div></div>` : ''}
    <div class="ann">
      ${data.map((a) => `<div class="item">
        <div class="h"><b>${esc(a['фио'])}</b><span>${esc(a['дата'])}</span></div>
        <p>${esc(a['текст'])}</p>
      </div>`).join('') || '<div class="empty">Объявлений пока нет</div>'}
    </div>`;
};

PAGES.report = async () => `
  <div class="hero"><div><h1>Отчёт</h1><div class="sub">Сборка Excel со всеми листами цеха</div></div></div>
  <div class="split">
    <div class="card">
      <div class="card-h"><h3>Что попадёт в файл</h3></div>
      <div class="card-b">
        ${['Партии и разделы: цвет, тон, размер, количество',
           'Проходы по процессам: кто, сколько, тариф, время',
           'Оценки технолога по каждому разделу',
           'Готовая продукция и отгрузки',
           'Материалы и цепочка процессов из Excel'].map((t) => `<div class="kv"><span>${t}</span><b>✓</b></div>`).join('')}
        <div style="margin-top:14px"><button class="btn primary" data-act="report">Собрать и скачать</button></div>
        <div class="hint" style="margin-top:8px">Файл также сохраняется в data/отчёты/</div>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Как это работает</h3></div>
      <div class="card-b" style="font-size:13px;color:var(--ink-2);line-height:1.6">
        Портал читает Excel-файлы в папке data, склеивает их в один workbook и отдаёт на скачивание.
        Данные не меняются — только чтение. Гибкие настройки (цепочка процессов, тарифы, периоды
        выплат, цеха) правятся прямо в Excel и подхватываются без перезапуска сервера.
      </div>
    </div>
  </div>`;

// ------------------------------------------------------------------ actions
const ACTIONS = {
  "save-brand": async () => {
    const name = ($('#brand-name') || {}).value || '';
    const sub = ($('#brand-sub') || {}).value || '';
    const file = ($('#brand-logo') || {}).files && $('#brand-logo').files[0];
    let logo = BRAND.логотип || '';
    if (file) {
      if (file.size > 2_000_000) throw new Error('Логотип больше 2 МБ');
      const dataUrl = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result));
        fr.onerror = () => rej(new Error('Не удалось прочитать файл'));
        fr.readAsDataURL(file);
      });
      const ext = (file.name.split('.').pop() || 'png').toLowerCase();
      const up = await api('/api/brand/logo', { method: 'POST', body: JSON.stringify({ 'данные': dataUrl, ext }) });
      logo = up.data['логотип'];
    }
    await api('/api/brand', {
      method: 'POST',
      body: JSON.stringify({ 'название': name, 'подзаголовок': sub, 'логотип': logo }),
    });
    await loadBrand();
    renderShell();
    toast('Оформление сохранено', 'ok');
    await go('users');
  },
};

ACTIONS['new-batch'] = async () => {
  const rowHtml = (i) => `
    <div data-row="${i}" style="display:grid;grid-template-columns:1.1fr 1fr .8fr .7fr auto;gap:8px;align-items:end">
      <div class="field"><label>Цвет</label><input class="input" name="цвет_${i}" placeholder="Чёрный"></div>
      <div class="field"><label>Код тона</label><input class="input" name="тон_${i}" placeholder="19-4013 TCX"></div>
      <div class="field"><label>Размер</label><input class="input" name="размер_${i}" placeholder="44 / XL"></div>
      <div class="field"><label>Кол-во</label><input class="input qty" name="qty_${i}" type="number" min="1" placeholder="40"></div>
      <button type="button" class="btn tiny" data-del="${i}" style="margin-bottom:2px">×</button>
    </div>`;

  modal({
    title: 'Новая партия',
    wide: true,
    submit: 'Создать партию',
    body: `
      <div class="grid2">
        <div class="field"><label>Изделие</label><input class="input" name="артикул" required placeholder="Куртка зимняя"></div>
        <div class="field"><label>Клиент</label><input class="input" name="клиент" placeholder="Азия Маркет"></div>
        <div class="field"><label>Срок готовности</label><input class="input" name="срок" placeholder="20.12.2026"></div>
        <div class="field"><label>Примечание</label><input class="input" name="примечание" placeholder="утеплитель 200 г"></div>
      </div>
      <div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <b style="font-size:13px">Разделы партии</b><span class="hint" id="total">итого: 0 шт</span>
        </div>
        <div id="rows" style="display:grid;gap:8px">${rowHtml(0)}</div>
        <button type="button" class="btn sm" id="add-row" style="margin-top:8px">+ Добавить раздел</button>
      </div>
      <div class="hint">Цвет, код тона и размерная сетка попадут в sections.xlsx.</div>`,
    onSubmit: async () => {
      const разделы = [];
      $$('#rows [data-row]').forEach((row) => {
        const i = row.dataset.row;
        const qty = num($(`[name="qty_${i}"]`).value);
        if (qty > 0) {
          разделы.push({
            цвет: $(`[name="цвет_${i}"]`).value,
            тон: $(`[name="тон_${i}"]`).value,
            размер: $(`[name="размер_${i}"]`).value,
            количество: qty,
          });
        }
      });
      if (!разделы.length) throw new Error('Заполни хотя бы один раздел');
      const res = await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          артикул: $('#mf [name="артикул"]').value,
          клиент: $('#mf [name="клиент"]').value,
          срок: $('#mf [name="срок"]').value,
          примечание: $('#mf [name="примечание"]').value,
          разделы,
        }),
      });
      toast('Партия #' + res['номер'] + ' создана');
      location.hash = '#/batch/' + res['номер'];
      await go('batch', String(res['номер']));
    },
  });

  let counter = 1;
  const recount = () => {
    let total = 0;
    $$('#rows .qty').forEach((el) => { total += num(el.value); });
    const t = $('#total');
    if (t) t.textContent = 'итого: ' + nf(total) + ' шт';
  };
  const bindRows = () => {
    $$('#rows [data-del]').forEach((b) => {
      b.onclick = () => { b.closest('[data-row]').remove(); recount(); };
    });
    $$('#rows .qty').forEach((el) => { el.oninput = recount; });
  };
  $('#add-row').onclick = () => {
    const div = document.createElement('div');
    div.innerHTML = rowHtml(counter++);
    $('#rows').appendChild(div.firstElementChild);
    bindRows();
  };
  bindRows();
};

ACTIONS['take'] = async (_, el) => {
  await api('/api/passes', {
    method: 'POST',
    body: JSON.stringify({
      'партия': num(el.dataset.batch),
      'раздел': num(el.dataset.sec),
      'процесс': el.dataset.proc,
    }),
  });
  toast('Задача взята · таймер пошёл');
  await go(STATE.route, STATE.route === 'batch' ? String(el.dataset.batch) : undefined);
};

ACTIONS['finish'] = async (id) => {
  const res = await api('/api/passes/' + id + '/finish', { method: 'POST' });
  toast('Готово · начислено ' + money(res['сумма']), 'ok');
  await go(STATE.route, STATE.route === 'batch' ? currentBatch() : undefined);
};

ACTIONS['minus'] = async (id) => {
  await api('/api/passes/' + id + '/minus', { method: 'POST', body: JSON.stringify({ 'количество': 1 }) });
  toast('Минус 1 учтён — штука вернулась на переделку');
  await go(STATE.route, STATE.route === 'batch' ? currentBatch() : undefined);
};

function currentBatch() {
  const m = /^#\/batch\/(\d+)/.exec(location.hash);
  return m ? m[1] : undefined;
}

ACTIONS['check'] = async (_, el) => {
  const batchNum = el.dataset.batch;
  const sec = el.dataset.sec;
  modal({
    title: 'Оценка раскроя',
    submit: 'Сохранить',
    body: `
      <div class="hint">Партия #${esc(batchNum)} · раздел ${esc(sec)}</div>
      <div class="field"><label>Оценка</label>
        <div class="btn-row" id="stars">
          ${[1, 2, 3, 4, 5].map((i) => `<button type="button" class="btn" data-star="${i}">${'★'.repeat(i)}</button>`).join('')}
        </div>
        <input type="hidden" name="оценка" value="5" id="score">
      </div>
      <div class="field"><label>Комментарий</label>
        <textarea class="input" name="комментарий" placeholder="Что заметил при проверке"></textarea></div>`,
    onSubmit: async (data) => {
      await api('/api/checks', {
        method: 'POST',
        body: JSON.stringify({ 'партия': num(batchNum), 'раздел': num(sec),
                               'оценка': num(data['оценка']), 'комментарий': data['комментарий'] }),
      });
      toast('Оценка сохранена');
      await go(STATE.route, STATE.route === 'batch' ? batchNum : undefined);
    },
  });
  $$('#stars [data-star]').forEach((b) => b.addEventListener('click', () => {
    $('#score').value = b.dataset.star;
    $$('#stars [data-star]').forEach((x) => x.classList.toggle('primary', x === b));
  }));
  $$('#stars [data-star]')[4].classList.add('primary');
};

ACTIONS['move'] = async (_, el) => openMove(el.dataset.kind);
ACTIONS['move-one'] = async (art) => openMove('расход', art);

async function openMove(kind, article) {
  const res = await api('/api/materials');
  const items = article ? res.data.filter((i) => i['артикул'] === article) : res.data;
  modal({
    title: kind === 'приход' ? 'Приход на склад' : 'Расход со склада',
    submit: kind === 'приход' ? 'Оприходовать' : 'Списать',
    body: `
      <div class="field"><label>Артикул</label>
        <select class="input" name="артикул" ${article ? 'disabled' : ''}>
          ${items.map((i) => `<option value="${esc(i['артикул'])}">${esc(i['артикул'])} · ${esc(i['название'])} · остаток ${nf(i['количество'])} ${esc(i['ед'])}</option>`).join('')}
        </select>
        ${article ? `<input type="hidden" name="артикул" value="${esc(article)}">` : ''}
      </div>
      <div class="grid2">
        <div class="field"><label>Количество</label><input class="input" name="количество" type="number" min="0.1" step="0.1" required></div>
        <div class="field"><label>Партия</label><input class="input" name="партия" placeholder="75"></div>
      </div>
      <div class="field"><label>Комментарий</label><input class="input" name="комментарий" placeholder="раскрой курток"></div>
      <input type="hidden" name="тип" value="${kind}">`,
    onSubmit: async (data) => {
      const r = await api('/api/materials/move', { method: 'POST', body: JSON.stringify(data) });
      toast('Остаток: ' + nf(r['остаток']));
      await go('materials');
    },
  });
}

ACTIONS['new-item'] = async () => modal({
  title: 'Новый артикул',
  submit: 'Добавить',
  body: `
    <div class="grid2">
      <div class="field"><label>Артикул</label><input class="input" name="артикул" required placeholder="TX-007"></div>
      <div class="field"><label>Наименование</label><input class="input" name="название" required placeholder="Ткань серая"></div>
      <div class="field"><label>Количество</label><input class="input" name="количество" type="number" step="0.1" value="0"></div>
      <div class="field"><label>Единица</label><input class="input" name="ед" placeholder="м / шт"></div>
      <div class="field"><label>Цена, сом</label><input class="input" name="цена" type="number" step="0.5" value="0"></div>
      <div class="field"><label>Поставщик</label><input class="input" name="поставщик" placeholder="Текстиль"></div>
    </div>`,
  onSubmit: async (data) => {
    await api('/api/materials/item', { method: 'POST', body: JSON.stringify(data) });
    toast('Артикул добавлен');
    await go('materials');
  },
});

ACTIONS['ship'] = async (batch, el) => {
  const free = num(el.dataset.free);
  modal({
    title: 'Отгрузка партии #' + batch,
    submit: 'Отгрузить',
    body: `
      <div class="hint">Свободно на складе: ${nf(free)} шт</div>
      <div class="grid2">
        <div class="field"><label>Количество</label><input class="input" name="количество" type="number" min="1" max="${free}" value="${free}" required></div>
        <div class="field"><label>Сумма, сом</label><input class="input" name="сумма" type="number" min="0" step="1000" placeholder="240000"></div>
      </div>
      <div class="field"><label>Покупатель</label><input class="input" name="покупатель" placeholder="Кумтор"></div>`,
    onSubmit: async (data) => {
      await api('/api/shipments', {
        method: 'POST',
        body: JSON.stringify({ 'партия': num(batch), 'количество': num(data['количество']),
                               'покупатель': data['покупатель'], 'сумма': num(data['сумма']) }),
      });
      toast('Отгружено');
      await go('finished');
    },
  });
};

ACTIONS['new-user'] = async () => openUser(null);
ACTIONS['edit-user'] = async (login) => {
  const { data } = await api('/api/users');
  openUser(data.find((u) => u['логин'] === login));
};

function openUser(user) {
  const roles = [
    ['cutter', 'Закройщик'], ['packer', 'Упаковщик'],
    ['technologist', 'Технолог'], ['storekeeper', 'Складчик'],
    ['designer', 'Конструктор'], ['supply', 'Снабженец'],
    ['manager', 'Менеджер'], ['accountant', 'Бухгалтер'], ['admin', 'Начальник'],
  ];
  modal({
    title: user ? 'Сотрудник' : 'Новый сотрудник',
    submit: 'Сохранить',
    body: `
      <div class="grid2">
        <div class="field"><label>Логин</label><input class="input" name="логин" required ${user ? 'readonly' : ''} value="${esc(user ? user['логин'] : '')}"></div>
        <div class="field"><label>ФИО</label><input class="input" name="фио" required value="${esc(user ? user['фио'] : '')}"></div>
        <div class="field"><label>Роль</label>
          <select class="input" name="роль">${roles.map(([v, t]) => `<option value="${v}" ${user && user['роль'] === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="field"><label>Пароль</label><input class="input" name="пароль" placeholder="123456"></div>
      </div>
      ${user ? `<div class="btn-row"><button type="button" class="btn sm" id="close-access" style="color:var(--red)">Закрыть доступ</button></div>` : ''}`,
    onSubmit: async (data) => {
      await api('/api/users', { method: 'POST', body: JSON.stringify(data) });
      toast('Сохранено');
      await go('users');
    },
  });
  if (user) {
    $('#close-access').addEventListener('click', async () => {
      await api('/api/users/delete', { method: 'POST', body: JSON.stringify({ 'логин': user['логин'] }) });
      toast('Доступ закрыт');
      $('#modal-root').innerHTML = '';
      await go('users');
    });
  }
}

ACTIONS['report'] = async () => {
  const res = await fetch('/api/report', { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) {
    const e = await res.json().catch(() => ({ error: 'не удалось' }));
    return toast(e.error || 'Не удалось собрать отчёт', 'err');
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'отчёт.xlsx';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast('Отчёт скачан');
};

// ------------------------------------------------------------------ магазин
const SHOP = {
  data: null,
  ф: { категория: '', модель: '', цвет: '', размер: '', q: '', только: true },
  корзина: new Map(),
  лимит: 48,
};

const ART_PATHS = {
  tshirt: '<path d="M60 46 82 32q18 14 36 0l22 14 20 28-19 11v83H59v-83L40 74Z"/>',
  longsleeve: '<path d="M60 46 82 32q18 14 36 0l22 14 17 26v96h-18l-7-58v67H66v-67l-7 58H41V72Z"/>',
  hoodie: '<path d="M60 48 82 34q18 14 36 0l22 14 18 28-19 11v82H61v-82L42 76Z"/><path d="M80 36q20 26 40 0" fill="none" stroke="currentColor" stroke-width="5" opacity=".45"/><rect x="78" y="132" width="44" height="20" rx="6" opacity=".55"/>',
  pants: '<path d="M70 30h60l7 54-9 92h-20l-7-78h-2l-7 78H72l-9-92Z"/>',
  bedding: '<rect x="44" y="78" width="112" height="66" rx="14"/><rect x="56" y="44" width="88" height="30" rx="10" opacity=".7"/><path d="M56 122h88" stroke="currentColor" stroke-width="3" opacity=".4"/>',
};

const COLOR_WORDS = [
  [/(бел|айвори|мрамор|ivory)/, '#f1efe8'],
  [/(чёрн|черн|графит|антрац|смол)/, '#33353a'],
  [/(беж|песоч|какао|кофе|шоколад|корич)/, '#c8ab8c'],
  [/(голуб|син|индиго|деним|василь)/, '#3f6fb5'],
  [/(бирюз|аква|морск)/, '#3fa0ad'],
  [/(зелён|зелен|хаки|олив|мят)/, '#6f9c6b'],
  [/(жёлт|желт|горчиц|лимон)/, '#dfc04c'],
  [/(оранж|персик|мандарин)/, '#e08a4a'],
  [/(красн|бордо|винн|алый)/, '#b8453f'],
  [/(розов|пудр|фукси)/, '#d98aa6'],
  [/(фиолет|сирен|лаванд|слив)/, '#8a6fb0'],
  [/(сер|дым|пыльн)/, '#9aa0a6'],
];
const PASTEL = ['#b9c6d8', '#c9b8a6', '#b8c4b0', '#d6c2b0', '#b0b8c9', '#cbb4b4', '#b4c7c2', '#c7bfae'];

function colorOf(name) {
  const text = String(name || '').toLowerCase();
  for (const [re, hex] of COLOR_WORDS) {
    if (re.test(text)) return hex;
  }
  let h = 0;
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) % 9973;
  return PASTEL[h % PASTEL.length];
}

function productArt(icon, color) {
  const path = ART_PATHS[icon] || ART_PATHS.tshirt;
  const fill = color || '#d9d9de';
  const dark = isLight(fill);
  return `<svg viewBox="0 0 200 200" class="art" aria-hidden="true">
    <defs><linearGradient id="g${Math.random().toString(36).slice(2, 8)}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${fill}" stop-opacity=".95"/>
      <stop offset="1" stop-color="${fill}" stop-opacity=".65"/>
    </linearGradient></defs>
    <g fill="${fill}" stroke="${dark ? '#c9ccd3' : 'rgba(0,0,0,.10)'}" stroke-width="2.5"
       stroke-linejoin="round">${path}</g>
  </svg>`;
}

function isLight(hex) {
  const h = String(hex).replace('#', '');
  if (h.length !== 6) return false;
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 190;
}

function shopFiltered() {
  const items = (SHOP.data ? SHOP.data.data : []) || [];
  const f = SHOP.ф;
  const q = f.q.trim().toLowerCase();
  return items.filter((it) => {
    if (f.категория && it['категория'] !== f.категория) return false;
    if (f.модель && it['модель'] !== f.модель) return false;
    if (f.цвет && String(it['цвет']).split(',')[0].trim() !== f.цвет) return false;
    if (f.размер && String(it['размер']) !== f.размер) return false;
    if (f.только && num(it['количество']) <= 0) return false;
    if (q) {
      const hay = (it['наименование'] + ' ' + it['модель'] + ' ' + it['цвет'] + ' ' + it['артикул']).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function shopGrid() {
  const items = shopFiltered();
  if (!items.length) {
    return '<div class="empty">Ничего не нашлось — снимите фильтры</div>';
  }
  const shown = items.slice(0, SHOP.лимит);
  return `<div class="products">${shown.map(productCard).join('')}</div>
    ${items.length > shown.length ? `<div style="text-align:center;margin-top:16px">
      <button class="btn" data-shop="more">Показать ещё ${items.length - shown.length}</button></div>` : ''}`;
}

function productCard(it) {
  const stock = num(it['количество']);
  const avail = (it['доступно'] !== undefined && it['доступно'] !== null) ? num(it['доступно']) : stock;
  const price = num(it['цена']);
  const color = colorOf(String(it['цвет']).split(',')[0]);
  const photo = String(it['фото'] || '').trim();
  const media = photo
    ? `<img class="photo" src="${esc(photo)}" alt="${esc(it['наименование'])}" loading="lazy">`
    : productArt(it['иконка'], color);
  const inCart = SHOP.корзина.get(String(it['id'])) || 0;
  return `
    <div class="product ${stock <= 0 ? 'out' : ''}">
      <div class="ph" style="background:linear-gradient(160deg, ${color}22, #ffffff 78%)">
        ${media}
        <span class="pill grey cat">${esc(it['категория'])}</span>
        ${STATE.caps['shop.price'] ? `<button class="price-edit" data-shop="price" data-id="${it['id']}" title="Изменить цену">₽</button>` : ''}
      </div>
      <div class="pbody">
        <div class="pname">${esc(it['категория'])} ${esc(it['модель'] || '')} · ${esc(it['размер'])}</div>
        <div class="pmeta">${esc(String(it['цвет']).split(',')[0])} · арт. ${esc(it['артикул'])}</div>
        <div class="prow">
          <b>${money(price)}</b>
          ${(STATE.caps['wh.view'] && num(it['склад']) < 0)
            ? `<span class="stock zero" style="color:#d12e2e" title="По складу минус — как в столбце ф.к">минус ${nf(-num(it['склад']))} шт</span>`
            : `<span class="stock ${avail > 0 ? '' : 'zero'}">${avail > 0 ? nf(avail) + ' шт' : 'нет в наличии'}</span>`}
        </div>
        ${avail > 0
          ? `<button class="btn primary sm" data-shop="add" data-id="${it['id']}">В корзину${inCart ? ' · ' + inCart : ''}</button>`
          : '<button class="btn sm" disabled>Всё заказано</button>'}
      </div>
    </div>`;
}

PAGES.shop = async () => {
  const res = await api('/api/shop');
  SHOP.data = res;
  SHOP.лимит = 48;
  const t = res['итоги'];
  const tree = {};
  res.data.forEach((it) => {
    const c = it['категория'] || 'Прочее';
    tree[c] = tree[c] || {};
    tree[c][it['модель']] = tree[c][it['модель']] || {};
    tree[c][it['модель']][it['цвет']] = tree[c][it['модель']][it['цвет']] || new Set();
    tree[c][it['модель']][it['цвет']].add(it['размер']);
  });
  SHOP.tree = tree;
  const models = SHOP.ф.категория ? Object.keys(tree[SHOP.ф.категория] || {}) : [];
  const colors = SHOP.ф.категория && SHOP.ф.модель
    ? Object.keys((tree[SHOP.ф.категория] || {})[SHOP.ф.модель] || {}) : [];
  const sizes = SHOP.ф.категория && SHOP.ф.модель && SHOP.ф.цвет
    ? Array.from(((tree[SHOP.ф.категория] || {})[SHOP.ф.модель] || {})[SHOP.ф.цвет] || []) : [];

  return `
    <div class="hero">
      <div><h1>Магазин</h1>
        <div class="sub">${nf(t['позиций'])} позиций · ${nf(t['в_наличии'])} в наличии · ${nf(t['штук'])} шт на складе${(STATE.caps['wh.view'] && t['пересорт']) ? ' · пересорт ' + nf(t['пересорт']) + ' шт' : ''}</div>
        <div class="hint">${shopSyncLine(res['источник'])}</div></div>
      <div class="actions">
        <input class="input" id="shop-q" placeholder="Поиск" style="width:200px">
      </div>
    </div>
    <div class="card shop-filters">
      <div class="filter-grid">
        <select class="input" class="wh-f" id="f-cat">
          <option value="">Все категории</option>
          ${Object.keys(tree).map((c) => `<option ${SHOP.ф.категория === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
        </select>
        <select class="input" id="f-model" ${models.length ? '' : 'disabled'}>
          <option value="">Все модели</option>
          ${models.map((m) => `<option ${SHOP.ф.модель === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}
        </select>
        <select class="input" id="f-color" ${colors.length ? '' : 'disabled'}>
          <option value="">Все цвета</option>
          ${colors.map((c) => `<option ${SHOP.ф.цвет === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
        </select>
        <select class="input" id="f-size" ${sizes.length ? '' : 'disabled'}>
          <option value="">Все размеры</option>
          ${sizes.map((x) => `<option ${SHOP.ф.размер === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}
        </select>
      </div>
      <div class="btn-row" style="margin-top:10px">
        <label class="checkline"><input type="checkbox" id="shop-only" ${SHOP.ф.только ? 'checked' : ''}> только в наличии</label>
        <span class="hint" id="shop-count" style="margin-left:auto"></span>
      </div>
    </div>
    <div id="shop-grid">${shopGrid()}</div>
    <div class="cart-fab" id="cart-fab" hidden>
      <span>Корзина</span>
      <b id="cart-sum">0 сом</b>
      <i id="cart-count">0</i>
    </div>`;
};

const SHOP_TABS = [
  ['', 'Витрина'], ['in', 'Приход'], ['out', 'Поставка'],
  ['move', 'Перевод'], ['boxes', 'Коробки'], ['archive', 'Архив'],
];

function opDetails(r) {
  const parts = [];
  if (r['тип'] === 'поставка') {
    parts.push([r['откуда'] || 'Основной склад', r['контрагент']].filter(Boolean).join(' → '));
  } else if (r['тип'] === 'перевод') {
    parts.push([r['откуда'], r['куда']].filter(Boolean).join(' → '));
  } else {
    parts.push(r['куда'] || 'Основной склад');
  }
  if (r['комментарий']) parts.push(r['комментарий']);
  return parts.filter(Boolean).join(' · ');
}

function shopTabs(active) {
  return `<div class="tabs">${SHOP_TABS.map(([id, label]) => `
    <a href="#/shop${id ? '/' + id : ''}" class="tab ${active === id ? 'on' : ''}">${label}</a>`).join('')}</div>`;
}

function productSelect(name, value) {
  const items = (SHOP.data ? SHOP.data.data : []) || [];
  if (!value) {
    const firstInStock = items.find((it) => num(it['количество']) > 0);
    if (firstInStock) value = firstInStock['id'];
  }
  const groups = {};
  items.forEach((it) => {
    const g = it['категория'] || 'Прочее';
    groups[g] = groups[g] || [];
    groups[g].push(it);
  });
  return `<select class="input" name="${name}">
    ${Object.keys(groups).sort().map((g) => `<optgroup label="${esc(g)}">
      ${groups[g].map((it) => `<option value="${it['id']}" ${String(value) === String(it['id']) ? 'selected' : ''}>
        ${esc(it['модель'] || it['наименование'])} · ${esc(it['размер'])} · ${esc(String(it['цвет']).split(',')[0])} · остаток ${nf(it['количество'])}
      </option>`).join('')}
    </optgroup>`).join('')}
  </select>`;
}

const LOCS = ['Основной склад', 'ЖСК', 'ААТ', 'ККМ', 'Магазин'];

async function opTab(tab) {
  const kinds = { in: 'приход', out: 'поставка', move: 'перевод' };
  const kind = kinds[tab];
  const res = await api('/api/shop/ops?тип=' + encodeURIComponent(kind));
  const rows = res.data;
  const titles = { приход: 'Приход на склад', поставка: 'Поставка клиенту', перевод: 'Перевод между складами' };
  const hints = {
    приход: 'Товар добавляется на склад и попадает в коробки.',
    поставка: 'Списывает товар со склада (как листы «паставка» в Excel).',
    перевод: 'Двигает товар между складами, общий остаток не меняется.',
  };

  const form = tab === 'in' ? `
    <form data-op="приход" class="grid2">
      <div class="field" style="grid-column:1/-1"><label>Товар</label>${productSelect('id_товара')}</div>
      <div class="field"><label>Количество, шт</label><input class="input" name="количество" type="number" min="1" required></div>
      <div class="field"><label>Номер коробки</label><input class="input" name="коробка" placeholder="авто"></div>
      <div class="field"><label>Поставщик</label><input class="input" name="контрагент" placeholder="Текстиль"></div>
      <div class="field"><label>Комментарий</label><input class="input" name="комментарий" placeholder="приход за октябрь"></div>
      <input type="hidden" name="куда" value="Основной склад">
      <div class="field" style="grid-column:1/-1"><button class="btn primary">Оприходовать</button></div>
    </form>` : tab === 'out' ? `
    <form data-op="поставка" class="grid2">
      <div class="field" style="grid-column:1/-1"><label>Товар</label>${productSelect('id_товара')}</div>
      <div class="field"><label>Количество, шт</label><input class="input" name="количество" type="number" min="1" required></div>
      <div class="field"><label>Кому</label>
        <select class="input" name="контрагент">
          <option>ЖСК</option><option>ААТ</option><option>ККМ</option><option>Магазин</option><option>другой</option>
        </select></div>
      <div class="field"><label>Со склада</label>
        <select class="input" name="откуда">${LOCS.map((l) => `<option>${l}</option>`).join('')}</select></div>
      <div class="field"><label>Комментарий</label><input class="input" name="комментарий" placeholder="отгрузка по заявке"></div>
      <div class="field" style="grid-column:1/-1"><button class="btn primary">Оформить поставку</button></div>
    </form>` : `
    <form data-op="перевод" class="grid2">
      <div class="field" style="grid-column:1/-1"><label>Товар</label>${productSelect('id_товара')}</div>
      <div class="field"><label>Количество, шт</label><input class="input" name="количество" type="number" min="1" required></div>
      <div class="field"><label>Откуда</label>
        <select class="input" name="откуда">${LOCS.map((l) => `<option>${l}</option>`).join('')}</select></div>
      <div class="field"><label>Куда</label>
        <select class="input" name="куда">${LOCS.map((l, i) => `<option ${i === 1 ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
      <div class="field"><label>Комментарий</label><input class="input" name="комментарий" placeholder="перевод в ЖСК"></div>
      <div class="field" style="grid-column:1/-1"><button class="btn primary">Перевести</button></div>
    </form>`;

  return `
    <div class="card">
      <div class="card-h"><h3>${titles[kind]}</h3><div class="spacer"></div><span class="hint">${hints[kind]}</span></div>
      <div class="card-b">${form}</div>
    </div>
    <div class="card">
      <div class="card-h"><h3>История</h3><div class="spacer"></div><span class="hint">${rows.length} записей</span></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>Дата</th><th>Товар</th><th class="num">Кол-во</th><th>Детали</th><th>Кто</th><th></th></tr></thead>
          <tbody>${rows.map((r) => `
            <tr style="${r['отменена'] ? 'opacity:.55' : ''}">
              <td data-l="Дата">${esc(r['дата'])}</td>
              <td data-l="Товар">${esc(r['наименование'])}</td>
              <td data-l="Кол-во" class="num">${nf(r['количество'])}</td>
              <td data-l="Детали" class="muted">${esc(opDetails(r))}</td>
              <td data-l="Кто">${esc(r['кто'] || '')}</td>
              <td>${r['отменена'] ? '<span class="pill red">отменена</span>'
                : (STATE.caps['shop.stock'] ? `<button class="btn tiny" data-act="cancel-op" data-arg="${r['id']}">Отменить</button>` : '')}</td>
            </tr>`).join('') || '<tr><td colspan="6" class="empty">Пока пусто</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>`;
}

async function boxesTab() {
  const res = await api('/api/shop/boxes');
  const t = res['итоги'];
  return `
    <div class="kpis">
      ${kpi('Коробок', t['коробок'], 'всего в реестре')}
      ${kpi('Проверено', t['проверено'], 'Nice✅', 'ok')}
      ${kpi('Штук в коробках', nf(t['штук']), 'по всем приходам')}
    </div>
    <div class="card"><div class="card-b tight tablescroll">
      <table class="resp">
        <thead><tr><th>Коробка</th><th>Дата</th><th>Товар</th><th class="num">Кол-во</th><th>Проверка</th><th>Кто</th></tr></thead>
        <tbody>${res.data.map((b) => `<tr>
          <td data-l="Коробка"><b>${esc(b['коробка'])}</b></td>
          <td data-l="Дата">${esc(b['дата'])}</td>
          <td data-l="Товар">${esc(b['наименование'])}</td>
          <td data-l="Кол-во" class="num">${nf(b['количество'])}</td>
          <td data-l="Проверка">
            ${STATE.caps['shop.stock']
              ? `<button class="btn tiny" data-act="box-check" data-arg="${b['id']}" data-on="${String(b['проверка']).startsWith('Nice') ? 1 : 0}">${esc(b['проверка'])}</button>`
              : `<span class="pill ${String(b['проверка']).startsWith('Nice') ? 'green' : 'grey'}">${esc(b['проверка'])}</span>`}
          </td>
          <td data-l="Кто">${esc(b['кто'] || '')}</td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty">Коробок пока нет — сделайте приход</td></tr>'}</tbody>
      </table>
    </div></div>`;
}

async function archiveTab() {
  const res = await api('/api/shop/ops');
  const rows = res.data;
  return `
    <div class="card">
      <div class="card-h"><h3>Архив операций</h3><div class="spacer"></div>
        <span class="hint">${res['итоги']['всего']} записей · активных ${res['итоги']['активных']}</span></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>Дата</th><th>Тип</th><th>Товар</th><th class="num">Кол-во</th><th>Детали</th><th>Кто</th><th></th></tr></thead>
          <tbody>${rows.map((r) => `<tr style="${r['отменена'] ? 'opacity:.55' : ''}">
            <td data-l="Дата">${esc(r['дата'])}</td>
            <td data-l="Тип">${pill(r['тип'], r['тип'] === 'приход' ? 'green' : r['тип'] === 'поставка' ? 'orange' : 'blue')}</td>
            <td data-l="Товар">${esc(r['наименование'])}</td>
            <td data-l="Кол-во" class="num">${nf(r['количество'])}</td>
            <td data-l="Детали" class="muted">${esc(opDetails(r))}</td>
            <td data-l="Кто">${esc(r['кто'] || '')}</td>
            <td>${r['отменена'] ? '<span class="pill red">отменена</span>'
              : (STATE.caps['shop.stock'] ? `<button class="btn tiny" data-act="cancel-op" data-arg="${r['id']}">Отменить</button>` : '')}</td>
          </tr>`).join('') || '<tr><td colspan="7" class="empty">Операций пока нет</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function shopSyncLine(src) {
  if (!src) return '';
  if (src.error) return `<span style="color:var(--red)">Excel недоступен: ${esc(src.error)}</span> — показаны последние данные`;
  const parts = [];
  if (src.source_name) parts.push('источник: ' + esc(src.source_name));
  if (src.synced_at) parts.push('обновлено ' + esc(src.synced_at));
  if (src['расхождений']) parts.push(`расхождений с «каробками»: ${src['расхождений']}`);
  return parts.join(' · ');
}

function startShopWatch() {
  if (SHOP.timer) clearInterval(SHOP.timer);
  SHOP.timer = setInterval(async () => {
    if (STATE.route !== 'shop') return;
    try {
      const res = await api('/api/shop');
      const prev = SHOP.data && SHOP.data['источник'] ? SHOP.data['источник'].synced_at : null;
      const next = res['источник'] ? res['источник'].synced_at : null;
      SHOP.data = res;
      const line = $('#shop-sync');
      if (line) line.innerHTML = shopSyncLine(res['источник']);
      if (next && next !== prev) {
        refreshShopGrid();
        toast('Каталог обновлён из Excel', 'ok');
      }
    } catch (e) { /* тихо: следующий тик попробует снова */ }
  }, 10000);
}

function bindShop() {
  startShopWatch();
  const page = $('#page');
  page.addEventListener('click', (e) => {
    const cat = e.target.closest('[data-cat]');
    if (cat) {
      SHOP.ф.категория = cat.dataset.cat;
      SHOP.лимит = 48;
      $$('#shop-cats .chipbtn').forEach((b) => b.classList.toggle('on', b === cat));
      refreshShopGrid();
      return;
    }
    const more = e.target.closest('[data-shop="more"]');
    if (more) {
      SHOP.лимит += 48;
      refreshShopGrid();
      return;
    }
    const add = e.target.closest('[data-shop="add"]');
    if (add) {
      const id = String(add.dataset.id);
      const item = ((SHOP.data && SHOP.data.data) || []).find((i) => String(i['id']) === id);
      const max = item ? stockOf(item) : 0;
      const cur = SHOP.корзина.get(id) || 0;
      if (cur >= max) {
        toast(max > 0 ? `Больше нет: доступно ${nf(max)} шт` : 'Товара нет в наличии', 'err');
        return;
      }
      SHOP.корзина.set(id, cur + 1);
      refreshShopGrid();
      return;
    }
    const price = e.target.closest('[data-shop="price"]');
    if (price) openPrice(price.dataset.id);
  });

  const q = $('#shop-q');
  if (q) q.addEventListener('input', () => { SHOP.ф.q = q.value; SHOP.лимит = 48; refreshShopGrid(); });
  const fcat = $('#f-cat');
  if (fcat) fcat.addEventListener('change', () => {
    SHOP.ф.категория = fcat.value; SHOP.ф.модель = ''; SHOP.ф.цвет = ''; SHOP.ф.размер = '';
    go('shop');
  });
  const fmodel = $('#f-model');
  if (fmodel) fmodel.addEventListener('change', () => {
    SHOP.ф.модель = fmodel.value; SHOP.ф.цвет = ''; SHOP.ф.размер = '';
    go('shop');
  });
  const fcolor = $('#f-color');
  if (fcolor) fcolor.addEventListener('change', () => {
    SHOP.ф.цвет = fcolor.value; SHOP.ф.размер = '';
    go('shop');
  });
  const fsize = $('#f-size');
  if (fsize) fsize.addEventListener('change', () => { SHOP.ф.размер = fsize.value; refreshShopGrid(); });
  const only = $('#shop-only');
  if (only) only.addEventListener('change', () => { SHOP.ф.только = only.checked; refreshShopGrid(); });

  const fab = $('#cart-fab');
  if (fab) fab.addEventListener('click', openCart);
  updateCartFab();
}

function refreshShopGrid() {
  const grid = $('#shop-grid');
  if (!grid) return;
  grid.innerHTML = shopGrid();
  const count = $('#shop-count');
  if (count) count.textContent = shopFiltered().length + ' поз.';
  updateCartFab();
}

function stockOf(it) {
  const v = it['доступно'];
  if (v === undefined || v === null) return num(it['количество']);
  return num(v);
}

function cartLines() {
  const items = (SHOP.data ? SHOP.data.data : []) || [];
  const byId = new Map(items.map((i) => [String(i['id']), i]));
  const out = [];
  SHOP.корзина.forEach((qty, id) => {
    const it = byId.get(id);
    if (it && qty > 0) out.push({ it, qty });
  });
  return out;
}

function cartTotal() {
  return cartLines().reduce((s, l) => s + num(l.it['цена']) * l.qty, 0);
}

function updateCartFab() {
  const fab = $('#cart-fab');
  if (!fab) return;
  const lines = cartLines();
  const count = lines.reduce((s, l) => s + l.qty, 0);
  fab.hidden = count === 0;
  const sum = $('#cart-sum');
  const cnt = $('#cart-count');
  if (sum) sum.textContent = money(cartTotal());
  if (cnt) cnt.textContent = count;
}

function openCart() {
  const lines = cartLines();
  if (!lines.length) return;
  const isClient = STATE.me.роль === 'client';
  modal({
    title: 'Корзина',
    submit: isClient ? 'Отправить заказ' : 'Оформить продажу',
    wide: true,
    body: `
      <div style="display:grid;gap:10px" id="cart-lines">
        ${lines.map((l) => `
          <div class="cartline" data-line="${l.it['id']}">
            <div class="cl-art" style="background:linear-gradient(160deg, ${colorOf(String(l.it['цвет']).split(',')[0])}33, #fff)">
              ${String(l.it['фото'] || '').trim()
                ? `<img class="photo" src="${esc(l.it['фото'])}" alt="">`
                : productArt(l.it['иконка'], colorOf(String(l.it['цвет']).split(',')[0]))}
            </div>
            <div class="cl-body">
              <b>${esc(l.it['категория'])} ${esc(l.it['модель'] || '')} · ${esc(l.it['размер'])}</b>
              <div class="cell-sub">${esc(String(l.it['цвет']).split(',')[0])} · арт. ${esc(l.it['артикул'])}</div>
              <div class="cell-sub">доступно ${nf(stockOf(l.it))} шт</div>
            </div>
            <div class="cl-qty">
              <button type="button" class="btn tiny" data-cl="minus">−</button>
              <span>${l.qty}</span>
              <button type="button" class="btn tiny" data-cl="plus" ${l.qty >= stockOf(l.it) ? 'disabled' : ''}>+</button>
            </div>
            <div class="cl-sum">${money(num(l.it['цена']) * l.qty)}</div>
            <button type="button" class="cl-del" data-cl="del">×</button>
          </div>`).join('')}
      </div>
      <div class="sep"></div>
      <div class="kv" style="font-size:15px"><span>Итого</span><b id="cart-modal-sum">${money(cartTotal())}</b></div>
      ${isClient ? '' : `<div class="field"><label>Покупатель</label>
        <input class="input" name="покупатель" placeholder="розница или имя клиента"></div>`}`,
    onSubmit: async () => {
      const lines = cartLines();
      if (!lines.length) throw new Error('Корзина пуста');
      if (STATE.me.роль === 'client') {
        const over = lines.find((l) => l.qty > stockOf(l.it));
        if (over) {
          throw new Error(`${over.it['наименование']}: доступно ${nf(stockOf(over.it))} шт`);
        }
        const позиции = lines.map((l) => ({ 'наименование': l.it['наименование'], 'количество': l.qty }));
        const res = await api('/api/orders', { method: 'POST', body: JSON.stringify({ позиции }) });
        SHOP.корзина.clear();
        toast('Заказ №' + res['id'] + ' отправлен на склад', 'ok');
        await go('orders');
        return;
      }
      const позиции = lines.map((l) => ({ id: num(l.it['id']), количество: l.qty }));
      const buyer = $('#mf [name="покупатель"]').value;
      const res = await api('/api/shop/sale', {
        method: 'POST',
        body: JSON.stringify({ позиции, 'покупатель': buyer }),
      });
      SHOP.корзина.clear();
      toast('Продано на ' + money(res['сумма']), 'ok');
      showUndoBar(res['ids'] || [], res['сумма']);
      await go('shop');
    },
  });

  const root = $('#modal-root');
  root.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cl]');
    if (!btn) return;
    const row = btn.closest('[data-line]');
    const id = String(row.dataset.line);
    const cur = SHOP.корзина.get(id) || 0;
    const act = btn.dataset.cl;
    if (act === 'plus') {
      const line = cartLines().find((l) => String(l.it['id']) === id);
      const max = line ? stockOf(line.it) : 0;
      if (cur >= max) { toast(`Доступно только ${nf(max)} шт`, 'err'); return; }
      SHOP.корзина.set(id, cur + 1);
    }
    if (act === 'minus') {
      if (cur <= 1) SHOP.корзина.delete(id); else SHOP.корзина.set(id, cur - 1);
    }
    if (act === 'del') SHOP.корзина.delete(id);
    const lines2 = cartLines();
    if (!lines2.length) { $('#modal-root').innerHTML = ''; refreshShopGrid(); return; }
    $('#cart-modal-sum').textContent = money(cartTotal());
    $$('#cart-lines [data-line]').forEach((el) => {
      const qty = SHOP.корзина.get(String(el.dataset.line)) || 0;
      el.querySelector('.cl-qty span').textContent = qty;
      const item = cartLines().find((l) => String(l.it['id']) === String(el.dataset.line));
      if (item) {
        el.querySelector('.cl-sum').textContent = money(num(item.it['цена']) * item.qty);
        const plus = el.querySelector('[data-cl="plus"]');
        if (plus) plus.disabled = qty >= stockOf(item.it);
      }
    });
    refreshShopGrid();
  });
}

function openPrice(id) {
  const items = (SHOP.data ? SHOP.data.data : []) || [];
  const it = items.find((i) => String(i['id']) === String(id));
  if (!it) return;
  modal({
    title: 'Цена товара',
    submit: 'Сохранить',
    body: `
      <div class="hint">${esc(it['наименование'])}</div>
      <div class="field"><label>Цена, сом</label>
        <input class="input" name="цена" type="number" min="0" step="10" value="${num(it['цена'])}" required></div>`,
    onSubmit: async (data) => {
      await api('/api/shop/price', { method: 'POST', body: JSON.stringify({ id: num(id), 'цена': num(data['цена']) }) });
      it['цена'] = num(data['цена']);
      toast('Цена обновлена');
      refreshShopGrid();
    },
  });
}

PAGES.orders = async () => {
  const res = await api('/api/orders');
  const rows = res.data || [];
  return `
    <div class="hero"><div><h1>Мои заказы</h1>
      <div class="sub">Заказы, отправленные на склад</div></div>
      <div class="actions"><a class="btn primary" href="#/shop">В каталог</a></div></div>
    ${rows.length ? rows.map((o) => `
      <div class="card">
        <div class="card-h"><h3>№${o['id']} · ${esc(o['дата'])}</h3><div class="spacer"></div>
          ${pill(o['статус'], o['статус'] === 'собран' ? 'green' : (o['статус'] === 'отменён' ? 'red' : 'orange'))}
          ${(o['статус'] || 'новый') === 'новый' ? `<button class="btn tiny" data-ocancel="${o['id']}">Отменить</button>` : ''}</div>
        <div class="card-b">
          ${o['позиции'].map((pos) => `<div class="order-row">
            <span>${esc(pos['наименование'])}</span>
            <b>${nf(pos['количество'])} шт</b>
            <span class="muted">собрано ${nf(pos['отгружено'])}</span>
          </div>`).join('')}
        </div>
      </div>`).join('') : '<div class="card"><div class="empty">Заказов пока нет — выберите товар в каталоге</div></div>'}`;
};

PAGES.fbs = async () => {
  const status = FBSPAGE.status || '';
  const res = await api('/api/wb/orders' + (status ? '?статус=' + encodeURIComponent(status) : ''));
  const rows = res.data || [];
  const counts = res['счётчики'] || { всего: 0, по_статусам: {} };
  const st = counts['по_статусам'] || {};
  const statuses = [['', 'Все'], ['new', 'Новые'], ['processing', 'В обработке'],
                    ['picking', 'Собирается'], ['picked', 'Собран'],
                    ['shipped', 'Отправлен'], ['done', 'Завершён']];
  const canManage = STATE.caps && STATE.caps['wb.manage'];

  return `
    <div class="hero">
      <div><h1>Заказы Wildberries</h1>
        <div class="sub">FBS · ${nf(counts['всего'])} заказов · новые ${nf(st['new'] || 0)}</div>
        <div class="hint">Заказы берутся из раздела «Новые» кабинета WB, сопоставление — по артикулу продавца</div></div>
      <div class="actions">
        ${canManage ? '<button class="btn primary" data-fbs="sync">Обновить из WB</button>' : ''}
      </div>
    </div>
    <div class="card"><div class="card-b" style="padding-top:12px">
      <div class="tabs" style="margin:0;flex-wrap:wrap">
        ${statuses.map(([v, l]) => `<button class="tab ${status === v ? 'on' : ''}" data-fbs="filter" data-v="${v}">${l}${st[v] ? ' · ' + st[v] : ''}</button>`).join('')}
      </div>
    </div></div>
    <div id="fbs-list">${fbsListHtml(rows, canManage)}</div>`;
};

function fbsListHtml(rows, canManage) {
  if (!rows.length) {
    return `<div class="card"><div class="empty">
      Новых заказов нет.<br><span class="muted">Нажмите «Обновить из WB», чтобы запросить их из кабинета.</span>
    </div></div>`;
  }
  return `<div class="card"><div class="card-b tight tablescroll">
    <table class="resp">
      <thead><tr>
        ${canManage ? '<th></th>' : ''}
        <th>Заказ</th><th>Кабинет</th><th>Товар (артикул продавца)</th>
        <th class="num">Цена</th><th>Дата</th><th>Статус</th>
      </tr></thead>
      <tbody>${rows.map((o) => `<tr>
        ${canManage ? `<td><input type="checkbox" class="fbs-check" value="${esc(o['id'])}"
            ${o['status'] === 'new' ? '' : 'disabled'}></td>` : ''}
        <td data-l="Заказ"><b>${esc(o['external_id'])}</b>${o['items'] > 1 ? ' · ' + o['items'] + ' поз.' : ''}</td>
        <td data-l="Кабинет"><span class="pill grey">${esc(o['cabinet_id'])}</span></td>
        <td data-l="Товар">${(o['items_detail'] || []).map((i) =>
            `${esc(i['title'] || '')}${i['product_id'] ? '' : ' <span class="pill orange">нет в каталоге</span>'}`).join('<br>')}</td>
        <td data-l="Цена" class="num">${o['amount'] ? money(o['amount']) : '—'}</td>
        <td data-l="Дата">${esc(o['ts'])}</td>
        <td data-l="Статус">${pill(o['status_label'], o['status'] === 'new' ? 'orange' : (o['status'] === 'processing' ? 'blue' : 'green'))}</td>
      </tr>`).join('')}</tbody>
    </table>
  </div>
  </div>`;
}

PAGES.orders = (() => {
  const orig = PAGES.orders;
  return async () => {
    const html = await orig();
    setTimeout(() => {
      $$('[data-ocancel]').forEach((b) => b.addEventListener('click', async () => {
        if (!confirm('Отменить заказ №' + b.dataset.ocancel + '?')) return;
        try {
          await api('/api/orders/cancel', { method: 'POST', body: JSON.stringify({ id: num(b.dataset.ocancel), причина: 'отменил клиент' }) });
          toast('Заказ отменён', 'ok');
          await go('orders');
        } catch (e) { toast(e.message, 'err'); }
      }));
    }, 0);
    return html;
  };
})();

PAGES.sales = async () => {
  const res = await api('/api/sales');
  const rows = res.data;
  const t = res['итоги'];
  const can = STATE.caps['shop.sell'];
  return `
    <div class="hero">
      <div><h1>Продажи</h1>
        <div class="sub">Магазин · всё, что оформлено через портал</div></div>
      <div class="actions"><a class="btn" href="#/shop">В магазин</a></div>
    </div>
    <div class="kpis">
      ${kpi('Продаж сегодня', t['сегодня_продаж'], money(t['сегодня_сумма']), 'ok')}
      ${kpi('Всего продаж', t['продаж'], money(t['сумма']))}
      ${kpi('Продано штук', nf(t['штук']), 'без отменённых')}
    </div>
    <div class="card"><div class="card-b tight tablescroll">
      <table class="resp">
        <thead><tr><th>Дата</th><th>Товар</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th><th>Покупатель</th><th>Оформил</th><th></th></tr></thead>
        <tbody>${rows.map((r) => `
          <tr style="${r['отменена'] ? 'opacity:.55' : ''}">
            <td data-l="Дата">${esc(r['дата'])}</td>
            <td data-l="Товар"><div class="cell-main">${esc(r['наименование'])}</div></td>
            <td data-l="Кол-во" class="num">${nf(r['количество'])}</td>
            <td data-l="Цена" class="num">${money(r['цена'])}</td>
            <td data-l="Сумма" class="num"><b>${money(r['сумма'])}</b></td>
            <td data-l="Покупатель">${esc(r['покупатель'] || '—')}</td>
            <td data-l="Оформил">${esc(r['кто'] || '')}</td>
            <td>${r['отменена']
              ? '<span class="pill red">отменена</span>'
              : (can ? `<button class="btn tiny" data-act="cancel-sale" data-arg="${r['id']}">Отменить</button>` : '')}</td>
          </tr>`).join('') || '<tr><td colspan="8" class="empty">Продаж пока нет</td></tr>'}
        </tbody>
      </table>
    </div></div>
    <div class="hint">Отмена возвращает товар на витрину и исключает продажу из выручки. История остаётся.</div>`;
};

ACTIONS['cancel-op'] = async (id) => {
  const res = await api('/api/shop/ops');
  const op = res.data.find((r) => String(r['id']) === String(id));
  if (!op) return toast('Операция не найдена', 'err');
  modal({
    title: 'Отменить операцию?',
    submit: 'Отменить',
    body: `
      <div class="kv"><span>Тип</span><b>${esc(op['тип'])}</b></div>
      <div class="kv"><span>Товар</span><b>${esc(op['наименование'])}</b></div>
      <div class="kv"><span>Количество</span><b>${nf(op['количество'])} шт</b></div>
      <div class="notice" style="margin:6px 0 0">Остаток вернётся к состоянию до операции. Запись останется в архиве.</div>`,
    onSubmit: async () => {
      await api('/api/shop/ops/cancel', { method: 'POST', body: JSON.stringify({ id: num(id) }) });
      toast('Операция отменена', 'ok');
      await go(STATE.route, STATE.route === 'shop' ? currentShopTab() : undefined);
    },
  });
};

ACTIONS['box-check'] = async (id, el) => {
  const on = String(el.dataset.on) === '1';
  await api('/api/shop/boxes/check', { method: 'POST', body: JSON.stringify({ id: num(id), 'проверка': on ? 0 : 1 }) });
  toast(on ? 'Проверка снята' : 'Коробка проверена', 'ok');
  await go('shop', 'boxes');
};

function currentShopTab() {
  const m = /^#\/shop\/?(\w*)/.exec(location.hash);
  return m ? m[1] : '';
}

ACTIONS['cancel-sale'] = async (id) => {
  const res = await api('/api/sales');
  const sale = res.data.find((r) => String(r['id']) === String(id));
  if (!sale) return toast('Продажа не найдена', 'err');
  modal({
    title: 'Отменить продажу?',
    submit: 'Отменить продажу',
    body: `
      <div class="hint">${esc(sale['наименование'])}</div>
      <div class="kv"><span>Количество</span><b>${nf(sale['количество'])} шт</b></div>
      <div class="kv"><span>Сумма</span><b>${money(sale['сумма'])}</b></div>
      <div class="kv"><span>Оформил</span><b>${esc(sale['кто'] || '—')} · ${esc(sale['дата'])}</b></div>
      <div class="notice" style="margin:6px 0 0">Товар вернётся на витрину, продажа уйдёт из выручки, запись останется в истории.</div>`,
    onSubmit: async () => {
      const r = await api('/api/sales/cancel', { method: 'POST', body: JSON.stringify({ id: num(id) }) });
      toast(`Отменено · на склад вернулось ${nf(r['вернулось'])} шт`, 'ok');
      await go('sales');
    },
  });
};

function showUndoBar(ids, sum) {
  const old = $('#undo-bar');
  if (old) old.remove();
  if (!ids.length) return;
  const bar = document.createElement('div');
  bar.id = 'undo-bar';
  bar.className = 'undo-bar';
  bar.innerHTML = `<span>Продажа на <b>${money(sum)}</b> записана</span>
    <button class="btn primary sm" id="undo-btn">Отменить</button>
    <button class="undo-x" id="undo-close">×</button>`;
  document.body.appendChild(bar);
  const close = () => bar.remove();
  $('#undo-close').onclick = close;
  $('#undo-btn').onclick = async () => {
    try {
      let back = 0;
      for (const id of ids) {
        const r = await api('/api/sales/cancel', { method: 'POST', body: JSON.stringify({ id }) });
        back += num(r['вернулось']);
      }
      toast(`Продажа отменена · на склад вернулось ${nf(back)} шт`, 'ok');
      close();
      if (STATE.route === 'shop' || STATE.route === 'sales') await go(STATE.route);
    } catch (e) { toast(e.message, 'err'); }
  };
  setTimeout(() => { if ($('#undo-bar')) close(); }, 90000);
}

// ------------------------------------------------------------------ офлайн-синхронизация

// Мост нативного сканера: Java (DataWedge Intent) вызывает эту функцию.
window.__nativeScan = function (data) {
  try {
    if (typeof SCAN === 'undefined') return;
    SCAN.buf = String(data || '').trim();
    if (SCAN.timer) clearTimeout(SCAN.timer);
    scanFlush();
  } catch (e) {}
};

const MODE = {
  sklad: (new URLSearchParams(location.search).get('mode') === 'sklad')
    || localStorage.getItem('v2mode') === 'sklad',
};

const BRAND = { название: 'Швейный цех', подзаголовок: '', логотип: '' };

async function loadBrand() {
  try {
    const res = await api('/api/brand');
    if (res && res.data) {
      BRAND.название = res.data['название'] || BRAND.название;
      BRAND.подзаголовок = res.data['подзаголовок'] || '';
      BRAND.логотип = res.data['логотип'] || '';
    }
  } catch (e) { /* нет связи — оставляем текущее */ }
}

function brandMark(cls) {
  if (BRAND.логотип) {
    const v = encodeURIComponent(BRAND.логотип).slice(0, 24);
    return `<img class="${cls || ''}" src="/api/logo?v=${v}" alt="">`;
  }
  return 'V2';
}

const SYNC = {
  snap: null,
  queue: [],
  rejected: [],
  last: '',
  busy: false,
  online: navigator.onLine,
};

function lsGet(key, def) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : def;
  } catch (e) { return def; }
}
function lsSet(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* переполнение */ }
}

function syncLoad() {
  SYNC.snap = lsGet('v2snap', null);
  SYNC.queue = lsGet('v2queue', []);
  SYNC.rejected = lsGet('v2rejected', []);
  SYNC.last = localStorage.getItem('v2last') || '';
}

function syncSave() {
  if (SYNC.snap) lsSet('v2snap', SYNC.snap);
  lsSet('v2queue', SYNC.queue);
  lsSet('v2rejected', SYNC.rejected);
  localStorage.setItem('v2last', SYNC.last || '');
  syncPaint();
}

function uuid() {
  if (crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'op-' + Date.now() + '-' + Math.random().toString(16).slice(2, 10);
}

function syncChipHtml() {
  const n = SYNC.queue.length;
  if (!SYNC.online) {
    return `<span class="sync-chip off" id="sync-chip"><i></i>офлайн${n ? ' · ' + n + ' в очереди' : ''}</span>`;
  }
  if (n) return `<span class="sync-chip wait" id="sync-chip"><i></i>${n} на отправку</span>`;
  return `<span class="sync-chip ok" id="sync-chip"><i></i>${SYNC.last ? 'обновлено ' + SYNC.last : 'онлайн'}</span>`;
}

function syncPaint() {
  const chip = $('#sync-chip');
  if (chip) chip.outerHTML = syncChipHtml();
  const bar = $('#sync-bar');
  if (bar) bar.innerHTML = syncBarHtml();
  bindSyncChip();
}

function bindSyncChip() {
  const chip = $('#sync-chip');
  if (chip) chip.addEventListener('click', () => syncNow(true));
}

async function syncNow(manual) {
  if (SYNC.busy) return;
  SYNC.busy = true;
  try {
    const res = await api('/api/sync/pull');
    SYNC.snap = res.data;
    SYNC.last = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    SYNC.online = true;
    syncSave();

    if (SYNC.queue.length) {
      const push = await api('/api/sync/push', {
        method: 'POST',
        body: JSON.stringify({ base_version: SYNC.snap.version, ops: SYNC.queue }),
      });
      const bad = (push['результаты'] || []).filter((r) => !r.ok);
      SYNC.queue = [];
      SYNC.rejected = bad.map((r) => ({ ...r, когда: new Date().toLocaleString('ru-RU') }));
      syncSave();
      if (bad.length) toast(`Принято ${push['принято']}, отклонено ${bad.length} — смотрите «Журнал»`, 'err');
      else if (push['принято']) toast(`Отправлено ${push['принято']} операций`, 'ok');
    }
    if (manual) toast('Данные обновлены', 'ok');
  } catch (e) {
    const msg = String(e.message || '');
    if (!/доступ|403/.test(msg)) SYNC.online = false;   // нет прав — это не офлайн
    syncSave();
    if (manual) toast('Нет связи с сервером — работаем офлайн', 'err');
  } finally {
    SYNC.busy = false;
    syncPaint();
  }
}

function queueOp(type, payload) {
  SYNC.queue.push({ uuid: uuid(), type, payload, ts: Date.now() });
  syncSave();
  return SYNC.queue.length;
}

async function sendOrQueue(path, body, type, payload, successMsg) {
  if (!navigator.onLine) {
    queueOp(type, payload);
    toast('Сохранено офлайн · отправится при связи', 'warn');
    return { offline: true };
  }
  try {
    const res = await api(path, { method: 'POST', body: JSON.stringify(body) });
    return res;
  } catch (e) {
    const msg = String(e.message || '');
    const network = /Failed to fetch|NetworkError|Load failed|не удалось|timeout/i.test(msg);
    if (!network) throw e;
    queueOp(type, payload);
    SYNC.online = false;
    syncSave();
    toast('Связь пропала — операция сохранена офлайн', 'warn');
    return { offline: true };
  }
}

// локальные данные из снимка
function localItems() {
  return (SYNC.snap && SYNC.snap.items) || [];
}

function localMeta() {
  const tree = {};
  localItems().forEach((it) => {
    const c = it['категория'] || 'Прочее';
    tree[c] = tree[c] || {};
    tree[c][it['модель']] = tree[c][it['модель']] || {};
    tree[c][it['модель']][it['цвет']] = tree[c][it['модель']][it['цвет']] || new Set();
    tree[c][it['модель']][it['цвет']].add(it['размер']);
  });
  const out = {};
  Object.keys(tree).forEach((c) => {
    out[c] = {};
    Object.keys(tree[c]).forEach((m) => {
      out[c][m] = {};
      Object.keys(tree[c][m]).forEach((col) => {
        out[c][m][col] = Array.from(tree[c][m][col]).sort(sizeKey);
      });
    });
  });
  return {
    категории: Object.keys(out).sort(),
    дерево: out,
    поставщики: (SYNC.snap && SYNC.snap.suppliers) || [],
    адреса: (SYNC.snap && SYNC.snap.addresses) || [],
    получатели: ['ЖСК', 'ККМ', 'ААТ'],
    позиций: localItems().length,
    штук: Math.round(localItems().reduce((a, i) => a + (i['остаток'] || 0), 0)),
    источник: SYNC.snap ? 'офлайн-снимок' : '',
    офлайн: true,
  };
}

function sizeKey(a, b) {
  const na = parseFloat(String(a).replace(',', '.'));
  const nb = parseFloat(String(b).replace(',', '.'));
  if (!isNaN(na) && !isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b), 'ru');
}

function localFind(q) {
  const v = String(q || '').trim().toLowerCase();
  if (!v) return null;
  const items = localItems();
  const exact = items.find((i) => i['наименование'].toLowerCase() === v);
  if (exact) return exact;
  const part = items.filter((i) => i['наименование'].toLowerCase().includes(v));
  part.sort((a, b) => a['наименование'].length - b['наименование'].length);
  return part[0] || null;
}

function syncBarHtml() {
  const n = SYNC.queue.length;
  if (!n && !SYNC.rejected.length) return '';
  const q = SYNC.queue.slice(-4).map((op) =>
    `<div class="qrow"><span>${esc(op.type)}</span><span class="muted">${esc(op.payload['наименование'] || op.payload['id'] || '')}</span></div>`).join('');
  const bad = SYNC.rejected.slice(-4).map((r) =>
    `<div class="qrow bad"><span>${esc(r.type || 'операция')}</span><span>${esc(r.error || '')}</span></div>`).join('');
  return `
    <div class="card"><div class="card-h"><h3>Очередь синхронизации</h3><div class="spacer"></div>
      <span class="hint">${n} ждут отправки · ${SYNC.rejected.length} отклонено</span></div>
      <div class="card-b">
        ${q}
        ${bad}
        <div class="btn-row" style="margin-top:10px">
          <button class="btn primary" data-sync="now">Отправить сейчас</button>
          <button class="btn" data-sync="clear">Очистить отклонённые</button>
        </div>
      </div>
    </div>`;
}

function bindSyncBar() {
  $$('[data-sync="now"]').forEach((b) => b.addEventListener('click', () => syncNow(true)));
  $$('[data-sync="clear"]').forEach((b) => b.addEventListener('click', () => {
    SYNC.rejected = [];
    syncSave();
    go('wh', 'log');
  }));
}

window.addEventListener('online', () => { SYNC.online = true; syncPaint(); syncNow(false); });
window.addEventListener('offline', () => { SYNC.online = false; syncPaint(); });

// ------------------------------------------------------------------ склад
const FBSPAGE = { status: '' };

const WH = { meta: null, tab: 'stock', ф: { cat: '', model: '', color: '', size: '', only: true }, stock: [] };
const WH_TABS = [['stock', 'Главная'], ['in', 'Приход'], ['addr', 'Адрес'], ['out', 'Поставка'], ['log', 'Журнал']];

function whTabs(active) {
  return `<div class="tabs">${WH_TABS.map(([id, label]) => `
    <a href="#/wh${id === 'stock' ? '' : '/' + id}" class="tab ${active === id ? 'on' : ''}">${label}</a>`).join('')}
    ${active !== 'stock' ? '<a href="#/wh" class="tab back">← Главная</a>' : ''}</div>`;
}

async function whMeta(force) {
  if (!WH.meta || force) {
    try {
      WH.meta = (await api('/api/wh/meta')).data;
      if (!SYNC.snap) syncNow(false);
    } catch (e) {
      WH.meta = localMeta();
    }
  }
  return WH.meta;
}

PAGES.wh = async (param) => {
  let m = location.hash.match(/#\/wh\/pick\/([\w-]+)/);
  if (m) return pickPage(m[1]);
  const tab = param || 'stock';
  WH.tab = tab;
  const meta = await whMeta();
  const head = `
    <div class="hero">
      <div><h1>Склад</h1>
        <div class="sub">${nf(meta['позиций'])} позиций · ${nf(meta['штук'])} шт на складе · источник: ${esc(meta['источник'] || '')}</div></div>
      <div class="actions"><span class="pill grey">${esc(STATE.me.цех)}</span></div>
    </div>
    ${whTabs(tab)}`;
  if (tab === 'in') return head + whIn(meta);
  if (tab === 'addr') return head + whAddr(meta);
  if (tab === 'out') return head + await whOut(meta);
  if (tab === 'log') return head + await whLog();
  return head + await whStock(meta);
};

// ---------- Главная: остатки с каскадными фильтрами ----------
async function whStock(meta) {
  const q = '?только=' + (WH.ф.only ? '1' : '0');
  try {
    const res = await api('/api/wh/stock' + q);
    WH.stock = res.data;
  } catch (e) {
    WH.stock = localItems().filter((i) => (WH.ф.only ? (i['остаток'] || 0) !== 0 : true));
  }
  const models = WH.ф.cat ? Object.keys(meta['дерево'][WH.ф.cat] || {}) : [];
  const colors = WH.ф.cat && WH.ф.model ? Object.keys(meta['дерево'][WH.ф.cat][WH.ф.model] || {}) : [];
  const sizes = WH.ф.cat && WH.ф.model && WH.ф.color
    ? (meta['дерево'][WH.ф.cat][WH.ф.model][WH.ф.color] || []) : [];

  return `
    <div class="card">
      <div class="card-b" style="padding-top:16px">
        <div class="grid2">
          <div class="field"><label>Категория</label>
            <select class="input wh-f" data-f="cat">
              <option value="">Все категории</option>
              ${meta['категории'].map((c) => `<option ${WH.ф.cat === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Модель</label>
            <select class="input wh-f" data-f="model" ${models.length ? '' : 'disabled'}>
              <option value="">Все модели</option>
              ${models.map((m) => `<option ${WH.ф.model === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Цвет</label>
            <select class="input wh-f" data-f="color" ${colors.length ? '' : 'disabled'}>
              <option value="">Все цвета</option>
              ${colors.map((c) => `<option ${WH.ф.color === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Размер</label>
            <select class="input wh-f" data-f="size" ${sizes.length ? '' : 'disabled'}>
              <option value="">Все размеры</option>
              ${sizes.map((s) => `<option ${WH.ф.size === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
            </select></div>
        </div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn ${WH.ф.only ? 'primary' : ''} sm" data-wh="only">Только с остатком</button>
          <button class="btn ${WH.ф.only ? '' : 'primary'} sm" data-wh="all">Все товары</button>
          <span class="hint" id="wh-count" style="margin-left:auto"></span>
        </div>
      </div>
    </div>
    <div id="wh-list">${whListHtml()}</div>`;
}

function whListHtml() {
  const f = WH.ф;
  const rows = WH.stock.filter((i) =>
    (!f.cat || i['категория'] === f.cat) &&
    (!f.model || i['модель'] === f.model) &&
    (!f.color || i['цвет'] === f.color) &&
    (!f.size || i['размер'] === f.size) &&
    (!f.only || i['остаток'] > 0));
  if (!rows.length) return '<div class="card"><div class="empty">Ничего не найдено</div></div>';
  const shown = rows.slice(0, 120);
  return `<div class="card"><div class="card-b tight tablescroll">
    <table class="resp">
      <thead><tr><th></th><th>Товар</th><th class="num">Остаток на складе</th><th class="num">В размещении</th><th class="num">Отгружено</th></tr></thead>
      <tbody>${shown.map((i) => `<tr>
        <td data-l=""><div class="wh-art" style="background:${colorOf(i['цвет'])}22">${productArt(iconFor(i['категория']), colorOf(i['цвет']))}</div></td>
        <td data-l="Товар"><div class="cell-main">${esc(i['модель'])} · ${esc(i['размер'])}</div>
          <div class="cell-sub">${esc(i['категория'])} · ${esc(i['цвет'])}</div></td>
        <td data-l="Остаток" class="num"><b style="font-size:16px;${i['остаток'] < 0 ? 'color:#d12e2e' : ''}">${nf(i['остаток'])}</b>${i['остаток'] < 0 ? '<div class="cell-sub" style="color:#d12e2e">пересорт</div>' : ''}</td>
        <td data-l="В размещении" class="num muted">${i['ожидает'] > 0 ? '<b style="color:var(--orange)">' + nf(i['ожидает']) + '</b>' : '0'}</td>
        <td data-l="Отгружено" class="num muted">${nf(i['отгружено'])}</td>
      </tr>`).join('')}</tbody>
    </table>
    ${rows.length > shown.length ? `<div class="hint" style="padding:10px 14px">Показано ${shown.length} из ${rows.length}</div>` : ''}
  </div></div>`;
}

function iconFor(cat) {
  const c = String(cat || '').toLowerCase();
  if (c.includes('постел')) return 'bedding';
  if (c.includes('худи') || c.includes('толст')) return 'hoodie';
  if (c.includes('лонг')) return 'longsleeve';
  if (c.includes('брюк')) return 'pants';
  return 'tshirt';
}

// ---------- Приход: шаг 1 — выбор, шаг 2 — сетка размеров ----------
function whIn(meta) {
  const st = WH.in || (WH.in = { cat: '', model: '', color: '', supplier: '', batch: '', defect: 0, sizes: {} });
  const today = new Date().toLocaleDateString('ru-RU');
  const head = `
    <div class="card">
      <div class="card-h"><h3>Приход на склад</h3><div class="spacer"></div><span class="hint">${esc(today)}</span></div>
      <div class="card-b">`;

  if (!st.cat || !st.model || !st.color) {
    const models = st.cat ? Object.keys(meta['дерево'][st.cat] || {}) : [];
    const colors = st.cat && st.model ? Object.keys(meta['дерево'][st.cat][st.model] || {}) : [];
    return head + `
        <div class="grid2">
          <div class="field"><label>Поставщик</label>
            <select class="input scan" id="in-supplier">
              <option value="">Выберите</option>
              ${meta['поставщики'].map((x) => `<option ${st.supplier === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Партия (если свой цех)</label>
            <input class="input scan" id="in-batch" placeholder="например 75" value="${esc(st.batch || '')}"></div>
          <div class="field"><label>Категория</label>
            <select class="input scan" id="in-cat">
              <option value="">Выберите</option>
              ${meta['категории'].map((c) => `<option ${st.cat === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Модель</label>
            <select class="input scan" id="in-model" ${models.length ? '' : 'disabled'}>
              <option value="">${models.length ? 'Выберите' : '—'}</option>
              ${models.map((m) => `<option ${st.model === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}
            </select></div>
          <div class="field"><label>Цвет</label>
            <select class="input scan" id="in-color" ${colors.length ? '' : 'disabled'}>
              <option value="">${colors.length ? 'Выберите' : '—'}</option>
              ${colors.map((c) => `<option ${st.color === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select></div>
        </div>
        <button class="btn primary big" data-wh="next">Далее → размеры</button>
        <div class="hint" style="margin-top:10px">Размер на этом шаге не нужен — количества вводятся в следующей таблице.</div>
      </div></div>`;
  }

  const sizes = ((meta['дерево'][st.cat] || {})[st.model] || {})[st.color] || [];
  return head + `
        <div class="wh-headline">
          <b>${esc(st.cat)} · ${esc(st.model)} · ${esc(st.color)}</b>
          <button class="btn sm" data-wh="back">← изменить</button>
        </div>
        <div class="size-grid">
          ${sizes.map((size) => `
            <label class="size-cell">
              <span>${esc(size)}</span>
              <input class="input scan" type="number" min="0" inputmode="numeric"
                     data-size="${esc(size)}" value="${st.sizes[size] || ''}" placeholder="—">
            </label>`).join('') || '<div class="empty">У этой модели нет размеров в справочнике</div>'}
        </div>
        <div class="wh-total">Итого к приёму: <b id="in-total">0</b> шт</div>
        <button class="btn primary big" data-wh="accept">Принять товар</button>
        <div class="hint" style="margin-top:10px">Пустые ячейки пропускаются — заполняйте только те размеры, что пришли.</div>
      </div></div>`;
}

// ---------- Адрес ----------
function whAddr(meta) {
  return `
    <div class="card">
      <div class="card-h"><h3>Адресное хранение</h3><div class="spacer"></div><span class="hint">сканер: адрес → товар → количество</span></div>
      <div class="card-b">
        <div class="field"><label>1. Адрес (коробка)</label>
          <input class="input scan big" id="wh-box" list="wh-addresses" placeholder="сканируйте адрес" autocomplete="off">
          <datalist id="wh-addresses">${(meta['адреса'] || []).map((a) => `<option value="${esc(a)}">`).join('')}</datalist>
        </div>
        <div class="wh-found" id="wh-box-state"></div>
        <div style="height:0"></div>
        <div class="field" style="margin-top:10px"><label>2. Товар (штрихкод или название)</label>
          <input class="input scan big" id="wh-prod" placeholder="сканируйте товар" autocomplete="off"></div>
        <div class="wh-found" id="wh-found">Отсканируйте товар — покажу остаток</div>
        <div class="field" style="margin-top:10px"><label>3. Количество</label>
          <input class="input scan big" id="wh-qty" type="number" min="1" inputmode="numeric" placeholder="шт"></div>
        <button class="btn primary big" data-wh="place">Разместить</button>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Последние размещения</h3></div>
      <div class="card-b tight" id="wh-addr-list">Загрузка…</div>
    </div>`;
}

// ---------- Поставка: заказы клиентов + ручная отгрузка ----------
async function whOut(meta) {
  const target = WH.outTarget || 'ЖСК';
  WH.outTarget = target;
  const res = await api('/api/wh/shipments?получатель=' + encodeURIComponent(target));
  const rows = res.data || [];
  let orders = [];
  try { orders = (await api('/api/orders')).data || []; }
  catch (e) { orders = (SYNC.snap && SYNC.snap.orders) || []; }
  let fbs = null;
  try { fbs = (await api('/api/fbs/aggregate')).data; } catch (e) { fbs = null; }
  const open = orders.filter((o) => (o['статус'] || 'новый') === 'новый');
  const archive = orders.filter((o) => (o['статус'] || 'новый') !== 'новый');

  return `
    ${fbs && fbs['позиции'] && fbs['позиции'].length ? `
    <div class="card">
      <div class="card-h"><h3>Wildberries · FBS</h3><div class="spacer"></div>
        <span class="pill blue">FBS</span></div>
      <div class="card-b">
        <div class="order-head"><b>Сборка FBS · ${fbs['позиции'].length} позиций</b>
          <span class="pill orange">${fbs['позиции'].filter((p) => !p['в_каталоге']).length} без каталога</span></div>
        ${fbs['позиции'].slice(0, 5).map((p) => `<div class="order-row">
          <span>${esc(p['наименование'])}</span><b>1 шт</b></div>`).join('')}
        ${fbs['позиции'].length > 5 ? `<div class="hint">…и ещё ${fbs['позиции'].length - 5}</div>` : ''}
        <div class="order-actions"><a class="btn primary sm" href="#/wh/pick/fbs-all">Собрать заказ</a></div>
      </div>
    </div>` : ''}
    <div class="card">
      <div class="card-h"><h3>Заказы клиентов</h3><div class="spacer"></div>
        <span class="pill ${open.length ? 'orange' : 'green'}">${open.length} к сборке</span></div>
      <div class="card-b">
        ${open.length ? open.map((o) => `
          <div class="order-card">
            <div class="order-head">
              <b>№${esc(o['external_id'] || o['id'])} · ${esc(o['клиент'])}</b>
              ${o['fbs'] ? '<span class="pill blue">FBS</span>' : ''}
              <span class="muted">${esc(o['дата'])}</span>
              <button class="btn tiny" data-wh="cancel" data-id="${o['id']}">Отменить</button>
            </div>
            ${o['позиции'].map((pos) => {
              const left = num(pos['количество']) - num(pos['отгружено']);
              return `<div class="order-row ${left <= 0 ? 'done' : ''}">
                <span>${esc(pos['наименование'])}</span>
                <b>${nf(pos['количество'])} шт</b>
                <span class="muted">${left > 0 ? 'осталось ' + nf(left) : 'собрано'}</span>
              </div>`;
            }).join('')}
            <div class="order-actions">
              <a class="btn primary sm" href="#/wh/pick/${o['id']}">Собрать заказ</a>
            </div>
          </div>`).join('') : '<div class="empty">Новых заказов нет</div>'}
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Архив заказов</h3><div class="spacer"></div>
        <span class="hint">${archive.length} записей · заказы не удаляются</span></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>№</th><th>Дата</th><th>Клиент</th><th>Статус</th><th>Состав</th><th>Кто закрыл</th></tr></thead>
          <tbody>${archive.map((o) => `<tr>
            <td data-l="№">${o['id']}</td>
            <td data-l="Дата">${esc(o['дата'])}</td>
            <td data-l="Клиент">${esc(o['клиент'])}</td>
            <td data-l="Статус">${pill(o['статус'], o['статус'] === 'собран' ? 'green' : 'red')}</td>
            <td data-l="Состав">${o['позиции'].map((p) => esc(p['наименование']) + ' × ' + nf(p['количество'])).join('<br>')}</td>
            <td data-l="Кто">${esc(o['отменил'] || '')}${o['причина'] ? '<br><span class="muted">' + esc(o['причина']) + '</span>' : ''}</td>
          </tr>`).join('') || '<tr><td colspan="6" class="empty">Пока пусто</td></tr>'}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Отгружено в ${target}</h3><div class="spacer"></div><span class="hint">${rows.length} записей</span></div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr><th>Дата</th><th>Товар</th><th class="num">Кол-во</th><th>Заказ</th><th>Кто</th></tr></thead>
          <tbody>${rows.map((r) => `<tr>
            <td data-l="Дата">${esc(r['дата'] || '')}</td>
            <td data-l="Товар">${esc(r['наименование'] || '')}</td>
            <td data-l="Кол-во" class="num">${nf(r['количество'])}</td>
            <td data-l="Заказ">${esc(r['заказ'] || '—')}</td>
            <td data-l="Кто">${esc(r['кто'] || '')}</td>
          </tr>`).join('') || '<tr><td colspan="5" class="empty">Пока ничего не отгружали</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

// ---------- Журнал ----------
async function whLog() {
  const kind = WH.logKind || 'purchase';
  const labels = { purchase: 'Приобретение', address: 'адрес', 'ЖСК': 'паставка ЖСК', 'ККМ': 'паставка ККМ', 'ААТ': 'паставка ААТ' };
  const url = kind === 'purchase' ? '/api/wh/purchases'
    : kind === 'address' ? '/api/wh/address'
    : '/api/wh/shipments?получатель=' + encodeURIComponent(kind);
  const res = await api(url);
  const rows = res.data || [];
  return `
    <div class="card">
      <div class="card-h"><h3>Журнал операций</h3><div class="spacer"></div>
        <select class="input" id="wh-log-kind" style="width:210px">
          ${Object.entries(labels).map(([k, v]) => `<option value="${k}" ${k === kind ? 'selected' : ''}>${v}</option>`).join('')}
        </select></div>
      <div class="card-b" style="padding-top:12px">
        <button class="btn primary" data-wh="export">Записать в Excel сейчас</button>
        <span class="hint" style="margin-left:10px" id="wh-sync-line">запись в Excel пачкой раз в несколько минут</span>
      </div>
      <div id="sync-bar"></div>
      <div class="card" id="cabinets-card">
        <div class="card-h"><h3>Кабинеты Wildberries</h3><div class="spacer"></div>
          <span class="hint">токены хранятся только на этом Mac</span></div>
        <div class="card-b" id="cab-list"><span class="muted">загружаю…</span></div>
        <div class="card-b" id="cab-form" style="border-top:1px solid var(--line-2)">
          <div class="hint" style="margin-bottom:8px">
            Нажмите «Вставить токен» у нужного кабинета — поля заполнятся сами.
          </div>
          <div class="grid2">
            <div class="field"><label>Название кабинета</label>
              <input class="input" id="cab-name" placeholder="например ЖСК"></div>
            <div class="field"><label>Код <span class="muted">(внутренний, латиницей)</span></label>
              <input class="input" id="cab-id" placeholder="заполнится сам" autocomplete="off">
              <div class="hint" id="cab-id-hint">Нужен только внутри системы, к WB отношения не имеет.</div></div>
            <div class="field" style="grid-column:1/-1"><label>Токен Wildberries</label>
              <input class="input" id="cab-token" type="password" autocomplete="new-password"
                     placeholder="вставьте токен — он сохранится и больше не покажется"></div>
          </div>
          <button type="button" class="btn primary" onclick="cabSave()" style="margin-top:10px">Сохранить кабинет</button>
          <div class="hint" style="margin-top:8px">Токен нужен для FBS: заказы из кабинета подтягиваются автоматически.</div>
        </div>
      </div>
      <div class="card-b" id="negatives-box" style="padding-top:6px"></div>
      <div class="card-b" style="padding-top:6px">
        <div class="btn-row">
          <button class="btn" data-wh="verify">Сверить остатки</button>
          <span class="hint" style="margin-left:auto">файл · списано WB · на сайте</span>
        </div>
        <div id="verify-box" style="margin-top:10px"></div>
      </div>
      <div class="card-b" style="padding-top:12px">
        <div class="btn-row">
          <a class="btn primary" href="/api/export/workbook" download>Скачать Excel</a>
          <button class="btn" data-wh="backups">Показать резервные копии</button>
          <span class="hint" style="margin-left:auto">свежая копия рабочей книги, только чтение</span>
        </div>
        <div id="backup-list" style="margin-top:10px"></div>
      </div>
      <div class="card-b tight tablescroll">
        <table class="resp">
          <thead><tr>${Object.keys(rows[0] || { дата: 1 }).map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
          <tbody>${rows.map((r) => `<tr>${Object.keys(rows[0]).map((h) => `<td data-l="${esc(h)}">${esc(r[h])}</td>`).join('')}</tr>`).join('')
            || '<tr><td class="empty">Пусто</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}


// ---------- экран сборки заказа: слева штрихкод, справа количество ----------
const PICK = { order: null, sort: 'left', filter: '' };

function pickSortRows(rows) {
  const r = rows.slice();
  if (PICK.sort === 'name-asc') r.sort((a, b) => a.наименование.localeCompare(b.наименование, 'ru'));
  if (PICK.sort === 'name-desc') r.sort((a, b) => b.наименование.localeCompare(a.наименование, 'ru'));
  if (PICK.sort === 'qty-desc') r.sort((a, b) => b.осталось - a.осталось);
  if (PICK.sort === 'qty-asc') r.sort((a, b) => a.осталось - b.осталось);
  if (PICK.sort === 'left') r.sort((a, b) => (a.осталось > 0 ? 0 : 1) - (b.осталось > 0 ? 0 : 1));
  return r;
}

function pickRowsHtml() {
  const o = PICK.order;
  let positions = (o['позиции'] || []).slice();
  if (o['агрегат']) {
    // одинаковые товары собираем в одну строку с общим количеством
    const map = new Map();
    positions.forEach((p) => {
      const key = p['наименование'];
      if (!map.has(key)) map.set(key, { ...p, 'количество': 0 });
      map.get(key)['количество'] += 1;
    });
    positions = Array.from(map.values());
  }
  const rows = pickSortRows(positions.map((p) => ({
    наименование: p['наименование'],
    нужно: num(p['количество']),
    собрано: num(p['отгружено']),
    осталось: num(p['количество']) - num(p['отгружено']),
    qty: '',
  })));
  const f = PICK.filter.trim().toLowerCase();
  const shown = rows.filter((r) => !f || r.наименование.toLowerCase().includes(f));
  if (!shown.length) return '<div class="empty">Ничего не найдено</div>';
  return shown.map((r, i) => `
    <div class="pick-row ${r.осталось <= 0 ? 'done' : ''}" data-name="${esc(r.наименование)}">
      <input class="input pick-code" placeholder="штрихкод" autocomplete="off" autocapitalize="off"
             spellcheck="false" ${i === 0 ? 'autofocus' : ''}>
      <div class="pick-name">${esc(r.наименование)}</div>
      <input class="input pick-qty" type="number" min="0" inputmode="numeric"
             max="${r.осталось}" placeholder="0" ${r.осталось <= 0 ? 'disabled' : ''}>
      <div class="pick-meta">${r.осталось > 0 ? 'осталось ' + nf(r.осталось) : 'собрано'}</div>
    </div>`).join('');
}

async function pickPage(orderId) {
  if (String(orderId) === 'fbs-all') {
    const res = await api('/api/fbs/aggregate');
    const agg = res.data;
    if (!agg) return `<div class="card"><div class="empty">Новых позиций FBS нет</div></div>`;
    PICK.order = agg;
    PICK.filter = '';
    return `
      <div class="hero">
        <div><h1>Сборка FBS</h1>
          <div class="sub">${agg['позиции'].length} позиций · Wildberries</div>
          <div class="hint">Сканируйте товары подряд, внизу — одно подтверждение.</div></div>
        <div class="actions"><a class="btn" href="#/wh/out">← Поставка</a></div>
      </div>
      <div class="card pick-page">
        <div class="pick-list" id="pick-list">${pickRowsHtml()}</div>
        <div class="pick-ship-zone">
          <div class="hint" id="pick-total">Собрано: 0 шт</div>
          <button class="btn primary" id="pick-ship">Отправить в WB</button>
        </div>
      </div>`;
  }
  let orders = [];
  try { orders = (await api('/api/orders')).data || []; }
  catch (e) { orders = (SYNC.snap && SYNC.snap.orders) || []; }
  let fbs = null;
  try { fbs = (await api('/api/fbs/aggregate')).data; } catch (e) { fbs = null; }
  const order = orders.find((o) => String(o['id']) === String(orderId));
  if (!order) return `<div class="card"><div class="empty">Заказ не найден — вернитесь в поставку</div></div>`;
  PICK.order = order;
  PICK.filter = '';
  return `
    <div class="hero">
      <div><h1>Сборка №${esc(order['external_id'] || order['id'])} · ${esc(order['клиент'])}</h1>
        <div class="sub">${order['позиции'].length} позиций · ${esc(order['дата'])}</div></div>
      <div class="actions"><a class="btn" href="#/wh/out">← Поставка</a></div>
    </div>
    <div class="card pick-page">
      <div class="pick-tools">
        <input class="input" id="pick-filter" placeholder="Фильтр по товару">
        <select class="input" id="pick-sort">
          <option value="left" ${PICK.sort === 'left' ? 'selected' : ''}>Сначала несобранные</option>
          <option value="name-asc" ${PICK.sort === 'name-asc' ? 'selected' : ''}>Название А → Я</option>
          <option value="name-desc" ${PICK.sort === 'name-desc' ? 'selected' : ''}>Название Я → А</option>
          <option value="qty-desc" ${PICK.sort === 'qty-desc' ? 'selected' : ''}>Количество: больше → меньше</option>
          <option value="qty-asc" ${PICK.sort === 'qty-asc' ? 'selected' : ''}>Количество: меньше → больше</option>
        </select>
      </div>
      <div class="pick-list" id="pick-list">${pickRowsHtml()}</div>
      <div class="pick-ship-zone">
        <div class="hint" id="pick-total">Собрано: 0 шт</div>
        <button class="btn primary" id="pick-ship">${PICK.order && PICK.order['fbs'] ? 'Отправить в WB' : 'Отгрузить собранное'}</button>
      </div>
    </div>`;
}

function pickMark(row, state, text) {
  row.classList.remove('ok', 'bad', 'partial');
  if (state) row.classList.add(state);
  row.dataset.state = state || '';
  let hit = $('.pick-hit', row);
  if (!hit) {
    hit = document.createElement('div');
    hit.className = 'pick-hit';
    hit.appendChild(document.createTextNode(''));
    row.appendChild(hit);
  }
  hit.textContent = text || '';
  if (text) hit.style.display = ''; else hit.style.display = 'none';
}

function pickCheckQty(row) {
  const inp = $('.pick-qty', row);
  if (!inp) return true;
  const v = num(inp.value);
  const max = num(inp.max);
  if (v <= 0) { pickMark(row, '', ''); return true; }
  if (v > max) { pickMark(row, 'bad', 'Больше, чем нужно: макс ' + nf(max)); return false; }
  if (v === max) { pickMark(row, 'ok', '✓ ' + row.dataset.name + ' · ' + nf(max) + ' шт'); return true; }
  pickMark(row, 'partial', 'Частично: ' + nf(v) + ' из ' + nf(max));
  return false;
}

async function resolvePickCode(code) {
  const raw = String(code || '').trim();
  if (!raw) return null;
  try {
    const res = await api('/api/wh/find?q=' + encodeURIComponent(raw));
    if (res && res.data) return res.data['наименование'];
  } catch (e) { /* офлайн */ }
  const local = localFind(raw);
  return local ? local['наименование'] : null;
}

async function applyScan(code, input) {
  const rows = Array.from(document.querySelectorAll('.pick-row'));
  const name = await resolvePickCode(code);

  if (!name) {
    toast('Код не найден: ' + code, 'err');
    if (input) input.classList.add('bad');
    return;
  }
  const owner = rows.find((r) => r.dataset.name === name);
  if (!owner) {
    toast('«' + name.split('/').slice(1).join('/') + '» нет в этом заказе', 'err');
    if (input) input.classList.add('bad');
    return;
  }
  const qty = owner.querySelector('.pick-qty');
  qty.value = qty.max;
  pickCheckQty(owner);
  updatePickTotal();
  if (input) input.value = '';
  owner.scrollIntoView({ block: 'center', behavior: 'smooth' });

  // фокус на следующую строку, где ещё что-то осталось
  const idx = rows.indexOf(owner);
  let next = null;
  for (let k = idx + 1; k < rows.length; k++) {
    const q = rows[k].querySelector('.pick-qty');
    if (q && !q.disabled && num(q.value) <= 0) { next = rows[k]; break; }
  }
  if (!next) {
    for (let k = 0; k < idx; k++) {
      const q = rows[k].querySelector('.pick-qty');
      if (q && !q.disabled && num(q.value) <= 0) { next = rows[k]; break; }
    }
  }
  const target = next ? next.querySelector('.pick-code') : owner.querySelector('.pick-code');
  if (target) { target.focus(); target.select(); }
}

function updatePickTotal() {
  const list = $('#pick-list');
  if (!list) return;
  const inputs = $$('.pick-qty', list);
  const total = inputs.reduce((sum, inp) => sum + (num(inp.value) || 0), 0);
  const need = inputs.reduce((sum, inp) => sum + (num(inp.max) || 0), 0);
  const label = $('#pick-total');
  if (label) label.textContent = 'Собрано: ' + nf(total) + ' из ' + nf(need) + ' шт';
}

async function shipPicked() {
  const rowsAll = $$('.pick-row', $('#pick-list'));
  const badRow = rowsAll.find((r) => num($('.pick-qty', r).value) > num($('.pick-qty', r).max));
  if (badRow) { toast('Количество больше нужного — проверьте подсветку', 'err'); return; }
  const items = rowsAll.map((row) => ({
    'наименование': row.dataset.name,
    'количество': num($('.pick-qty', row).value),
    'проверка': row.dataset.state === 'ok' ? 'Nice✅' : 'Ошибка❌',
  })).filter((x) => x['количество'] > 0);
  if (!items.length) { toast('Укажите количество хотя бы по одной позиции', 'err'); return; }
  const btn = $('#pick-ship');
  btn.disabled = true;
  try {
    if (PICK.order && PICK.order['агрегат']) {
      const byName = {};
      (PICK.order['позиции'] || []).forEach((p) => {
        (byName[p['наименование']] = byName[p['наименование']] || []).push(p['item_id']);
      });
      const ids = [];
      rowsAll.forEach((row) => {
        const n = num($('.pick-qty', row).value);
        const pool = byName[row.dataset.name] || [];
        ids.push(...pool.slice(0, Math.max(0, n)));
        pool.splice(0, Math.max(0, n));
      });
      if (!ids.length) { toast('Ничего не собрано', 'err'); btn.disabled = false; return; }
      const r = await api('/api/wb/confirm-items', { method: 'POST', body: JSON.stringify({ items: ids }) });
      if (r['ошибки'] && r['ошибки'].length) {
        toast(`Ушло ${r['подтверждено']}, ошибок ${r['ошибки'].length}`, 'warn');
      } else {
        toast(`В сборку WB ушло позиций: ${r['подтверждено']}`, 'ok');
      }
      WH.meta = null;
      await go('wh', 'out');
      return;
    }
    if (PICK.order && PICK.order['fbs']) {
      const r = await api('/api/wb/confirm', { method: 'POST', body: JSON.stringify({ ids: [PICK.order['id']] }) });
      if (r['ошибки'] && r['ошибки'].length) throw new Error(r['ошибки'][0]['ошибка']);
      toast('Заказ ушёл в сборку WB', 'ok');
      WH.meta = null;
      await go('wh', 'out');
      return;
    }
    const res = await sendOrQueue('/api/orders/pick',
      { 'id': PICK.order['id'], 'позиции': items },
      'отгрузка_заказа', { 'id': PICK.order['id'], 'позиции': items }, 'сборка');
    if (!res.offline) toast('Собрано ' + res['принято'] + ' позиций · ' + nf(res['штук']) + ' шт', 'ok');
    WH.meta = null;
    await go('wh', 'out');
  } catch (e) {
    toast(e.message, 'err');
    btn.disabled = false;
  }
}

function bindPickPage() {
  const page = $('#page');
  if (!page) return;

  const sortEl = $('#pick-sort');
  if (sortEl) sortEl.addEventListener('change', (e) => {
    PICK.sort = e.target.value;
    $('#pick-list').innerHTML = pickRowsHtml();
    bindPickRows();
  });
  const filterEl = $('#pick-filter');
  if (filterEl) filterEl.addEventListener('input', (e) => {
    PICK.filter = e.target.value;
    $('#pick-list').innerHTML = pickRowsHtml();
    bindPickRows();
  });
  const shipEl = $('#pick-ship');
  if (shipEl) shipEl.addEventListener('click', shipPicked);
  bindPickRows();
}

function bindPickRows() {
  const list = $('#pick-list');
  if (!list) return;

  $$('.pick-code', list).forEach((inp) => {
    let timer = null;
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const c = inp.value.trim();
        if (c) applyScan(c, inp);
      }
    });
    inp.addEventListener('input', () => {
      inp.classList.remove('bad');
      clearTimeout(timer);
      const v = inp.value.trim();
      if (v.length >= 3) {
        timer = setTimeout(() => applyScan(v, inp), 150);
      }
    });
  });

  $$('.pick-qty', list).forEach((inp) => {
    inp.addEventListener('input', () => {
      pickCheckQty(inp.closest('.pick-row'));
      updatePickTotal();
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const row = inp.closest('.pick-row');
      const rows = Array.from(document.querySelectorAll('.pick-row'));
      const next = rows[rows.indexOf(row) + 1];
      const target = next ? next.querySelector('.pick-code') : inp;
      if (target) target.focus();
    });
  });

  updatePickTotal();
  const first = $('.pick-code', list);
  if (first) first.focus();
}

// ---------- события склада ----------
function bindFbs() {
  const page = $('#page');
  $$('[data-fbs="filter"]', page).forEach((b) => b.addEventListener('click', async () => {
    FBSPAGE.status = b.dataset.v;
    await go('fbs');
  }));
  $$('[data-fbs="sync"]', page).forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    try {
      const r = await api('/api/wb/sync', { method: 'POST' });
      const errs = (r['ошибки'] || []).map((e) => e['кабинет'] + ': ' + e['ошибка']).join('; ');
      const parts = [`новых ${r['создано']}`];
      if (r['отправлено']) parts.push(`в поставке ${r['отправлено']}`);
      if (r['собирается']) parts.push(`собирается ${r['собирается']}`);
      if (r['отменено']) parts.push(`отменено ${r['отменено']}`);
      const statsErr = (r['кабинеты'] || []).map((c) => c['статистика'] && c['статистика']['error']).filter(Boolean)[0];
      if (statsErr) parts.push('статистика: ' + statsErr);
      toast('WB: ' + parts.join(', ') + (errs ? ' · ' + errs : ''), errs ? 'warn' : 'ok');
      await go('fbs');
    } catch (e) { toast(e.message, 'err'); b.disabled = false; }
  }));
  $$('[data-fbs="confirm"]', page).forEach((b) => b.addEventListener('click', async () => {
    const ids = $$('.fbs-check').filter((c) => c.checked).map((c) => c.value);
    if (!ids.length) return toast('Отметьте заказы', 'err');
    b.disabled = true;
    try {
      const r = await api('/api/wb/confirm', { method: 'POST', body: JSON.stringify({ ids }) });
      if (r['ошибки'] && r['ошибки'].length) {
        toast(`Подтверждено ${r['подтверждено']}, ошибок ${r['ошибки'].length}`, 'warn');
      } else {
        toast(`Отправлено в сборку: ${r['подтверждено']}`, 'ok');
      }
      await go('fbs');
    } catch (e) { toast(e.message, 'err'); b.disabled = false; }
  }));
}

function bindWh() {
  const page = $('#page');

  // фильтры главной
  $$('.wh-f', page).forEach((sel) => sel.addEventListener('change', async () => {
    WH.ф[sel.dataset.f] = sel.value;
    if (sel.dataset.f === 'cat') { WH.ф.model = ''; WH.ф.color = ''; WH.ф.size = ''; }
    if (sel.dataset.f === 'model') { WH.ф.color = ''; WH.ф.size = ''; }
    if (sel.dataset.f === 'color') { WH.ф.size = ''; }
    await go('wh');
  }));
  $$('[data-wh="only"]', page).forEach((b) => b.addEventListener('click', async () => { WH.ф.only = true; await go('wh'); }));
  $$('[data-wh="all"]', page).forEach((b) => b.addEventListener('click', async () => { WH.ф.only = false; await go('wh'); }));

  // ---- приход: шаг 1 ----
  const st = () => (WH.in || (WH.in = { cat: '', model: '', color: '', supplier: '', batch: '', defect: 0, sizes: {} }));
  const catSel = $('#in-cat');
  if (catSel) catSel.addEventListener('change', async () => {
    const v = catSel.value; WH.in = { ...st(), cat: v, model: '', color: '', sizes: {} }; await go('wh', 'in');
  });
  const modelSel = $('#in-model');
  if (modelSel) modelSel.addEventListener('change', async () => {
    WH.in = { ...st(), model: modelSel.value, color: '', sizes: {} }; await go('wh', 'in');
  });
  const colorSel = $('#in-color');
  if (colorSel) colorSel.addEventListener('change', async () => {
    WH.in = { ...st(), color: colorSel.value, sizes: {} }; await go('wh', 'in');
  });
  const supSel = $('#in-supplier');
  if (supSel) supSel.addEventListener('change', () => { st().supplier = supSel.value; });
  const batchIn = $('#in-batch');
  if (batchIn) batchIn.addEventListener('input', () => { st().batch = batchIn.value; });
  const defectIn = $('#in-defect');
  if (defectIn) defectIn.addEventListener('input', () => { st().defect = num(defectIn.value); });

  $$('[data-wh="next"]', page).forEach((b) => b.addEventListener('click', async () => {
    const x = st();
    if (!x.cat || !x.model || !x.color) return toast('Выберите категорию, модель и цвет', 'err');
    if (!x.supplier) return toast('Выберите поставщика', 'err');
    await go('wh', 'in');
  }));
  $$('[data-wh="back"]', page).forEach((b) => b.addEventListener('click', async () => {
    WH.in = { ...st(), cat: '', model: '', color: '', sizes: {} };
    await go('wh', 'in');
  }));
  $$('input[data-size]', page).forEach((inp) => inp.addEventListener('input', () => {
    const x = st();
    const size = inp.dataset.size;
    const v = num(inp.value);
    if (v > 0) x.sizes[size] = v; else delete x.sizes[size];
    const total = Object.values(x.sizes).reduce((a, b2) => a + (num(b2) || 0), 0);
    const t = $('#in-total');
    if (t) t.textContent = nf(total);
  }));

  $$('[data-wh="accept"]', page).forEach((b) => b.addEventListener('click', async () => {
    const x = st();
    const позиции = Object.entries(x.sizes).map(([size, qty]) => ({
      'наименование': `${x.cat}/${x.model}/${x.color}/${size}`,
      'количество': num(qty),
    }));
    if (!позиции.length) return toast('Заполните количество хотя бы по одному размеру', 'err');
    b.disabled = true;
    try {
      const payload = { 'поставщик': x.supplier, 'партия': x.batch, 'неликвид': 0, 'позиции': позиции };
      const res = await sendOrQueue('/api/wh/receive_multi', payload, 'приход', payload, 'приход');
      if (!res.offline) toast(`Принято ${res['строк']} размеров · ${nf(res['штук'])} шт → в размещение`, 'ok');
      WH.in = { cat: '', model: '', color: '', supplier: x.supplier, batch: '', defect: 0, sizes: {} };
      WH.meta = null;
      await go('wh', 'in');
    } catch (e) { toast(e.message, 'err'); b.disabled = false; }
  }));

  // ---- адрес: живой поиск остатка ----
  const boxInput = $('#wh-box');
  const prodInput = $('#wh-prod');
  if (boxInput) boxInput.focus();
  if (boxInput) {
    const markBox = () => {
      const wrap = $('#wh-box-state');
      const v = boxInput.value.trim();
      if (!wrap) return;
      if (!v) { wrap.textContent = ''; wrap.className = 'wh-found'; return; }
      if (/^\d{8,14}$/.test(v)) {
        wrap.className = 'wh-found bad';
        wrap.textContent = 'Это штрихкод товара, а не адрес. Адрес выглядит как s/t1/e1/i1';
      } else {
        wrap.className = 'wh-found good';
        wrap.textContent = 'Адрес: ' + v + ' — теперь сканируйте товар';
      }
    };
    boxInput.addEventListener('input', markBox);
    boxInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); markBox(); prodInput && prodInput.focus(); }
    });
  }
  if (prodInput) {
    let timer = null;
    prodInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); lookupProd(); }
    });
    prodInput.addEventListener('input', () => {
      clearTimeout(timer);
      const v = prodInput.value.trim();
      if (v.length < 3) return;
      timer = setTimeout(lookupProd, 350);
    });
  }
  const qtyInput = $('#wh-qty');
  if (qtyInput) qtyInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doPlace(); } });
  $$('[data-wh="place"]', page).forEach((b) => b.addEventListener('click', doPlace));

  // ---- поставка ----
  const outProd = $('#wh-out-prod');
  if (outProd) {
    outProd.focus();
    let t2 = null;
    outProd.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lookupOut(); } });
    outProd.addEventListener('input', () => {
      clearTimeout(t2);
      if (outProd.value.trim().length < 3) return;
      t2 = setTimeout(lookupOut, 350);
    });
  }
  const outQty = $('#wh-out-qty');
  if (outQty) outQty.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doShip(); } });
  $$('[data-wh="target"]', page).forEach((b) => b.addEventListener('click', async () => {
    WH.outTarget = b.dataset.t;
    await go('wh', 'out');
  }));
  $$('[data-wh="ship"]', page).forEach((b) => b.addEventListener('click', doShip));
  $$('[data-wh="cancel"]', page).forEach((b) => b.addEventListener('click', async () => {
    if (!confirm('Отменить заказ №' + b.dataset.id + '? Он останется в архиве.')) return;
    try {
      await api('/api/orders/cancel', { method: 'POST', body: JSON.stringify({ id: num(b.dataset.id), причина: 'отменён складом' }) });
      toast('Заказ отменён и перенесён в архив', 'ok');
      await go('wh', 'out');
    } catch (e) { toast(e.message, 'err'); }
  }));

  $$('[data-wh="pick"]', page).forEach((b) => b.addEventListener('click', async () => {
    try {
      const payload = { 'id': num(b.dataset.id), 'наименование': b.dataset.name,
                        'количество': num(b.dataset.left) };
      const res = await sendOrQueue('/api/orders/ship', payload, 'отгрузка_заказа', payload, 'сборка');
      if (!res.offline) toast('Позиция собрана', 'ok');
      WH.meta = null;
      await go('wh', 'out');
    } catch (e) { toast(e.message, 'err'); }
  }));

  // ---- журнал ----
  $$('[data-wh="export"]', page).forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    try {
      const r = await api('/api/wh/export', { method: 'POST' });
      toast(`В Excel: приход ${r['приход']}, адрес ${r['адрес']}, отгрузки ${r['отгрузки']}`, 'ok');
      WH.meta = null;
      await go('wh', 'log');
    } catch (e) { toast(e.message, 'err'); }
    b.disabled = false;
  }));
  const logSel = $('#wh-log-kind');
  if (logSel) logSel.addEventListener('change', async () => { WH.logKind = logSel.value; await go('wh', 'log'); });

  loadAddresses();
  loadCabinets();

  const scanEl = $('#fbs-scan');
  if (scanEl) {
    scanEl.focus();
    scanEl.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const code = scanEl.value.trim();
      if (!code) return;
      try {
        const r = await api('/api/fbs/pick', { method: 'POST', body: JSON.stringify({ 'скан': code }) });
        if (r['предупреждение']) toast('Собран, но ' + r['предупреждение'], 'warn');
        else toast('Собран: ' + code, 'ok');
        scanEl.value = '';
        await loadFbsPick();
        scanEl.focus();
      } catch (err) { toast(err.message, 'err'); scanEl.select(); }
    });
  }

  $$('[data-wh="fbs-confirm"]', page).forEach((b) => b.addEventListener('click', async () => {
    const ids = FBSPAGE.pickedIds || [];
    if (!ids.length) return toast('Сначала соберите заказы сканером', 'err');
    const noStock = FBSPAGE.pickedNoStock || 0;
    const msg = `Отправить в сборку WB ${ids.length} собранных заказов?`
      + (noStock ? `\n\nВнимание: у ${noStock} заказов нет остатка на складе — они уйдут без списания.` : '');
    if (!confirm(msg)) return;
    b.disabled = true;
    try {
      const r = await api('/api/wb/confirm', { method: 'POST', body: JSON.stringify({ ids }) });
      toast(r['ошибки'] && r['ошибки'].length
        ? `Ушло ${r['подтверждено']}, ошибок ${r['ошибки'].length}`
        : `В сборку WB ушло: ${r['подтверждено']}`, r['ошибки'] && r['ошибки'].length ? 'warn' : 'ok');
      await loadFbsPick();
    } catch (e) { toast(e.message, 'err'); }
    b.disabled = false;
  }));
  bindCabForm();

  const syncLine = $('#wh-sync-line');
  if (syncLine) {
    const tick = async () => {
      if (!$('#wh-sync-line')) return;
      try {
        const st2 = (await api('/api/wh/sync_status')).data;
        const parts = [];
        if (st2['выполняется']) parts.push('записываю в Excel…');
        else if (st2['в_очереди'] && st2['следующая']) parts.push(`ждут записи: ${st2['в_очереди']} · запись в Excel в ${st2['следующая']}`);
        if (st2['последняя']) parts.push('последняя: ' + st2['последняя']);
        $('#wh-sync-line').textContent = parts.join(' · ')
          || `запись в Excel пачкой раз в ${st2['интервал_мин'] || 3} мин`;
      } catch (e) { /* тихо */ }
      setTimeout(tick, 4000);
    };
    tick();
  }
}

async function lookupProd() {
  const v = $('#wh-prod').value.trim();
  const box = $('#wh-found');
  if (!v) return;
  if (v === WH.lastQuery && box.innerHTML) return;
  WH.lastQuery = v;
  box.innerHTML = '<span class="muted">ищу…</span>';
  try {
    let res;
    try {
      res = await api('/api/wh/find?q=' + encodeURIComponent(v));
    } catch (e) {
      const hit = localFind(v);
      res = { data: hit, 'вариантов': hit ? 1 : 0, 'подсказки': hit ? [hit] : [] };
    }
    const it = res.data;
    if (!it) { box.innerHTML = '<span style="color:var(--red)">Товар не найден</span>'; return; }
    const more = (res['подсказки'] || []).slice(1);
    if (more.length) {
      box.innerHTML = `<div class="muted" style="margin-bottom:6px">Найдено ${res['вариантов']} вариантов — выберите:</div>` +
        (res['подсказки'] || []).map((p) => `<button class="btn sm" style="margin:3px" data-pick="${esc(p['наименование'])}">
          ${esc(p['наименование'])} · ${nf(p['остаток'])}</button>`).join('');
      $$('[data-pick]', box).forEach((b) => b.addEventListener('click', () => {
        $('#wh-prod').value = b.dataset.pick;
        WH.lastQuery = null;
        lookupProd();
      }));
      return;
    }
    if (!WH.foundName) WH.foundName = it['наименование'];
    box.innerHTML = `<b>${esc(it['наименование'])}</b>
      <div style="margin-top:6px;display:flex;gap:20px;flex-wrap:wrap">
        <span>на складе: <b>${nf(it['остаток'])} шт</b></span>
        <span>для размещения: <b style="color:var(--orange)">${nf(it['ожидает'] || 0)} шт</b></span>
      </div>`;
    const q = $('#wh-qty');
    if (q) { q.max = String(it['ожидает'] || 0); q.placeholder = 'до ' + nf(it['ожидает'] || 0); }
    q && q.focus();
  } catch (e) { toast(e.message, 'err'); }
}

async function doPlace() {
  const box = $('#wh-box').value.trim();
  const prod = $('#wh-prod').value.trim();
  const qty = num($('#wh-qty').value);
  if (!box) return toast('Сканируйте адрес (например s/t1/e1/i1)', 'err');
  if (/^\d{8,14}$/.test(box)) {
    return toast('В поле адреса попал штрихкод товара. Сканируйте адрес вида s/t1/e1/i1, а товар — во второе поле', 'err');
  }
  if (!prod) return toast('Сканируйте товар', 'err');
  if (!qty) return toast('Укажите количество', 'err');
  try {
    const res = await sendOrQueue('/api/wh/place',
      { 'коробка': box, 'наименование': prod, 'количество': qty },
      'адрес', { 'коробка': box, 'наименование': prod, 'количество': qty },
      'размещено');
    if (!res.offline) toast(`${res['коробка']}: ${res['товар']} × ${nf(qty)}`, 'ok');
    await go('wh', 'addr');
  } catch (e) { toast(e.message, 'err'); }
}

async function lookupOut() {
  const v = $('#wh-out-prod').value.trim();
  const box = $('#wh-out-found');
  if (!v) return;
  if (v === WH.lastOutQuery) return;
  WH.lastOutQuery = v;
  try {
    let res;
    try {
      res = await api('/api/wh/find?q=' + encodeURIComponent(v));
    } catch (e) {
      const hit = localFind(v);
      res = { data: hit };
    }
    const it = res.data;
    if (!it) { box.innerHTML = '<span style="color:var(--red)">Товар не найден</span>'; return; }
    box.innerHTML = `<b>${esc(it['наименование'])}</b>
      <div style="margin-top:6px;display:flex;gap:20px;flex-wrap:wrap">
        <span>на складе: <b>${nf(it['остаток'])} шт</b></span>
        <span class="muted">для размещения: ${nf(it['ожидает'] || 0)}</span>
      </div>`;
    $('#wh-out-qty').focus();
  } catch (e) { toast(e.message, 'err'); }
}

async function doShip() {
  const target = WH.outTarget || 'ЖСК';
  const prod = $('#wh-out-prod').value.trim();
  const qty = num($('#wh-out-qty').value);
  const order = $('#wh-out-order').value.trim();
  if (!prod) return toast('Сканируйте товар', 'err');
  if (!qty) return toast('Укажите количество', 'err');
  try {
    const payload = { 'получатель': target, 'наименование': prod, 'количество': qty, 'заказ': order };
    const res = await sendOrQueue('/api/wh/ship', payload, 'отгрузка', payload, 'отгружено');
    if (!res.offline) toast(`Отгружено в ${target} · остаток ${nf(res['остаток'])} шт`, 'ok');
    WH.meta = null;
    await go('wh', 'out');
  } catch (e) { toast(e.message, 'err'); }
}

async function loadNegatives() {
  const box = $('#negatives-box');
  if (!box) return;
  try {
    const res = await api('/api/wh/negatives');
    const rows = res.data || [];
    if (!rows.length) { box.innerHTML = ''; return; }
    const total = rows.reduce((s2, r) => s2 + num(r['пересорт']), 0);
    box.innerHTML = `<div class="notice" style="margin-bottom:8px">
        Пересорт: ${rows.length} позиций на ${nf(total)} шт — отгружено больше, чем размещено.
        Такой товар нельзя отгружать, пока не разберётесь с адресом.</div>
      <table class="resp"><thead><tr><th>Товар</th><th class="num">Остаток</th><th class="num">Пересорт</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td data-l="Товар">${esc(r['наименование'])}</td>
        <td data-l="Остаток" class="num" style="color:#d12e2e">${nf(r['остаток'])}</td>
        <td data-l="Пересорт" class="num">${nf(r['пересорт'])}</td>
      </tr>`).join('')}</tbody></table>`;
  } catch (e) { box.innerHTML = ''; }
}

const TRANSLIT = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i',
  й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
  у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '',
  э: 'e', ю: 'yu', я: 'ya', ' ': '-',
};

function slugify(text) {
  return String(text || '').toLowerCase().split('').map((ch) => TRANSLIT[ch] ?? ch)
    .join('').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

function bindCabForm() {
  const nameEl = $('#cab-name');
  const idEl = $('#cab-id');
  if (!nameEl || !idEl) return;
  let manual = false;
  idEl.addEventListener('input', () => { manual = idEl.value.trim().length > 0; });
  nameEl.addEventListener('input', () => {
    if (manual) return;
    idEl.value = slugify(nameEl.value);
  });
}

async function cabSave() {
  const idEl = $('#cab-id');
  const nameEl = $('#cab-name');
  const tokEl = $('#cab-token');
  const btn = event && event.target ? event.target : null;
  const id = (idEl ? idEl.value : '').trim().toLowerCase();
  const name = (nameEl ? nameEl.value : '').trim();
  const token = (tokEl ? tokEl.value : '').trim();
  if (!name) { toast('Укажите название кабинета', 'err'); return; }
  if (!id) { toast('Не заполнился код — введите название кабинета', 'err'); return; }
  if (token && token.split('.').length !== 3) {
    toast('Похоже, это не токен WB: настоящий выглядит как eyJhbGciOi… (три части через точку)', 'warn');
  }
  if (btn) { btn.disabled = true; btn.textContent = 'Сохраняю…'; }
  try {
    await api('/api/wb/cabinets', {
      method: 'POST',
      body: JSON.stringify({ id, name, token: token || undefined }),
    });
    toast(token ? 'Токен сохранён для «' + name + '»' : 'Кабинет сохранён', 'ok');
    if (tokEl) tokEl.value = '';
    await go('wh', 'log');
  } catch (e) {
    toast(e.message || 'Не удалось сохранить', 'err');
    if (btn) { btn.disabled = false; btn.textContent = 'Сохранить кабинет'; }
  }
}
window.cabSave = cabSave;

function cabName(id) {
  const map = { zhsk: 'ЖСК', kkm: 'ККМ', altyn: 'Алтын' };
  return map[id] || id || '';
}

async function loadFbsPick() {
  const box = $('#fbs-pick-list');
  if (!box) return;
  try {
    const res = await api('/api/fbs/pickable');
    const rows = res.data || [];
    const picked = rows.filter((r) => r.picked);
    const ready = rows.filter((r) => !r.picked && r.can_pick);
    const missing = rows.filter((r) => !r.picked && !r.can_pick);
    const line = (r, kind) => `<div class="order-row ${kind === 'missing' ? 'done' : ''}">
      <span>${esc(r['title'] || r['product_name'] || '')}
        <span class="muted"> · ${esc(cabName(r['cabinet_id']))} · ${esc(r['external_id'])}</span></span>
      <b>${kind === 'missing'
        ? (r['product_id'] ? '⚠ нет в наличии' : '⚠ нет в каталоге')
        : 'остаток ' + nf(r['stock'])}</b>
      ${kind === 'picked'
        ? '<span class="pill green">собран</span>'
        : `<button class="btn tiny ${kind === 'ready' ? 'primary' : ''}" data-fbs-pick="${esc(r['id'])}">Собрать</button>`}
    </div>`;
    const showAll = FBSPAGE.showMissing;
    const missingShown = showAll ? missing : missing.slice(0, 5);
    box.innerHTML = `
      ${picked.length ? `<div class="hint" style="margin:8px 0 4px">Собрано: ${picked.length}</div>${picked.map((r) => line(r, 'picked')).join('')}` : ''}
      ${ready.length ? `<div class="hint" style="margin:8px 0 4px">Можно собрать: ${ready.length}</div>${ready.map((r) => line(r, 'ready')).join('')}` : ''}
      ${missing.length ? `<div class="hint" style="margin:12px 0 4px">Нет в наличии — можно отправить с предупреждением: ${missing.length}</div>
        ${missingShown.map((r) => line(r, 'missing')).join('')}
        ${missing.length > 5 ? `<button class="btn sm" data-fbs-more="1" style="margin-top:6px">
          ${showAll ? 'Свернуть' : 'Показать все (' + missing.length + ')'}</button>` : ''}` : ''}
      ${!rows.length ? '<div class="empty">Новых заказов FBS нет</div>' : ''}`;
    $$('[data-fbs-more]', box).forEach((b) => b.addEventListener('click', async () => {
      FBSPAGE.showMissing = !FBSPAGE.showMissing;
      await loadFbsPick();
    }));
    $$('[data-fbs-pick]', box).forEach((b) => b.addEventListener('click', () => fbsPick(b.dataset.fbsPick)));
    FBSPAGE.pickedIds = picked.map((r) => r.id);
    FBSPAGE.pickedNoStock = picked.filter((r) => r.stock < 1).length;
  } catch (e) {
    box.innerHTML = '<div class="empty">Не удалось загрузить заказы</div>';
  }
}

async function fbsPick(id) {
  try {
    const r = await api('/api/fbs/pick', { method: 'POST', body: JSON.stringify({ id }) });
    if (r['предупреждение']) toast('Собран, но ' + r['предупреждение'], 'warn');
    else toast('Заказ собран', 'ok');
    await loadFbsPick();
  } catch (e) { toast(e.message, 'err'); }
}

async function loadCabinets() {
  const box = $('#cab-list');
  if (!box) return;
  try {
    const res = await api('/api/wb/cabinets');
    const rows = res.data || [];
    box.innerHTML = rows.length ? `<table class="resp">
      <thead><tr><th>Кабинет</th><th>Код</th><th>Токен</th><th>Статус</th><th></th></tr></thead>
      <tbody>${rows.map((c) => `<tr>
        <td data-l="Кабинет"><b>${esc(c['name'])}</b></td>
        <td data-l="Код"><span class="mono">${esc(c['id'])}</span></td>
        <td data-l="Токен">${c['token_set']
          ? `<span class="pill green">задан ${esc(c['token_hint'])}</span>`
          : '<span class="pill orange">не задан</span>'}</td>
        <td data-l="Статус">${c['active'] ? 'включён' : 'выключен'}</td>
        <td><button class="btn tiny ${c['token_set'] ? '' : 'primary'}" data-cab-edit="${esc(c['id'])}"
              data-cab-name="${esc(c['name'])}" data-cab-active="${c['active']}">${c['token_set'] ? 'Изменить' : 'Вставить токен'}</button></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">Кабинетов пока нет</div>';
    $$('[data-cab-edit]', box).forEach((b) => b.addEventListener('click', () => {
      const idEl = $('#cab-id');
      const nameEl = $('#cab-name');
      const tok = $('#cab-token');
      if (!idEl || !tok) return;
      idEl.value = b.dataset.cabEdit;
      idEl.readOnly = true;
      idEl.style.opacity = '.6';
      const hint = $('#cab-id-hint');
      if (hint) hint.textContent = 'Код уже задан — менять нельзя, иначе потеряются заказы кабинета.';
      nameEl.value = b.dataset.cabName;
      tok.value = '';
      const card = $('#cab-form');
      if (card) {
        card.classList.add('cab-active');
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      tok.focus();
      tok.placeholder = 'вставьте токен кабинета ' + b.dataset.cabName;
    }));
  } catch (e) {
    box.innerHTML = '<div class="empty">Не удалось загрузить кабинеты</div>';
  }
}

async function loadAddresses() {
  const box = $('#wh-addr-list');
  if (!box) return;
  try {
    const res = await api('/api/wh/address');
    const rows = res.data || [];
    box.innerHTML = rows.length ? `<table class="resp">
      <thead><tr><th>Дата</th><th>Коробка</th><th>Товар</th><th class="num">Кол-во</th></tr></thead>
      <tbody>${rows.slice(0, 25).map((r) => `<tr>
        <td data-l="Дата">${esc(r['дата'])}</td>
        <td data-l="Коробка"><b>${esc(r['коробка'])}</b></td>
        <td data-l="Товар">${esc(r['наименование'])}</td>
        <td data-l="Кол-во" class="num">${nf(r['количество'])}</td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">Пока пусто</div>';
  } catch (e) {
    box.innerHTML = '<div class="empty">Не удалось загрузить</div>';
  }
}

// ------------------------------------------------------------------ binding
// ---------- стеклянные выпадающие списки (панель поверх всего) ----------
let GSEL = { panel: null, sel: null, btn: null };

function gselPanel() {
  if (!GSEL.panel) {
    const p = document.createElement('div');
    p.className = 'gsel-panel gsel-float';
    document.body.appendChild(p);
    GSEL.panel = p;
  }
  return GSEL.panel;
}

function closeGsel() {
  if (GSEL.panel) {
    GSEL.panel.classList.remove('open');
    GSEL.panel.style.opacity = '0';
    GSEL.panel.style.pointerEvents = 'none';
    GSEL.panel.style.transform = 'translateY(-6px) scale(.985)';
  }
  if (GSEL.btn) GSEL.btn.classList.remove('open');
  GSEL.sel = null;
  GSEL.btn = null;
}

function openGsel(sel, btn) {
  const panel = gselPanel();
  const rect = btn.getBoundingClientRect();
  panel.innerHTML = Array.from(sel.options).map((o, i) =>
    `<button type="button" class="gsel-opt${i === sel.selectedIndex ? ' on' : ''}" data-i="${i}">${esc(o.textContent)}</button>`).join('');

  panel.style.width = rect.width + 'px';
  panel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)) + 'px';
  panel.style.top = '0px';
  panel.style.visibility = 'hidden';
  panel.classList.add('open');

  const h = panel.offsetHeight;
  const spaceBelow = window.innerHeight - rect.bottom - 10;
  const spaceAbove = rect.top - 10;
  const flip = h > spaceBelow && spaceAbove > spaceBelow;
  panel.style.top = (flip ? Math.max(8, rect.top - h - 8) : rect.bottom + 8) + 'px';
  panel.style.maxHeight = Math.max(160, Math.min(340, flip ? spaceAbove : spaceBelow)) + 'px';
  panel.style.visibility = '';
  panel.style.display = 'block';
  panel.style.opacity = '1';
  panel.style.pointerEvents = 'auto';
  panel.style.transform = 'none';

  btn.classList.add('open');
  GSEL.sel = sel;
  GSEL.btn = btn;
  GSEL.at = Date.now();
}

document.addEventListener('click', (e) => {
  if (GSEL.panel && GSEL.panel.contains(e.target)) return;
  if (GSEL.btn && GSEL.btn.contains(e.target)) return;
  closeGsel();
}, true);

document.addEventListener('click', (e) => {
  if (!GSEL.panel || !e.target.closest('.gsel-opt')) return;
  const b = e.target.closest('.gsel-opt');
  if (!GSEL.sel) return;
  const target = GSEL.sel;
  target.selectedIndex = Number(b.dataset.i);
  closeGsel();
  target.dispatchEvent(new Event('change', { bubbles: true }));
}, true);

window.addEventListener('scroll', (e) => {
  if (!GSEL.panel) return;
  if (GSEL.panel.contains(e.target)) return;
  if (Date.now() - (GSEL.at || 0) < 450) return;
  closeGsel();
}, true);
window.addEventListener('resize', closeGsel);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeGsel();
});

function enhanceSelects(scope) {
  $$('select', scope).forEach((sel) => {
    if (sel.dataset.glass) return;
    if (sel.closest('.gsel')) return;
    sel.dataset.glass = '1';

    const wrap = document.createElement('div');
    wrap.className = 'gsel';
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);
    sel.classList.add('gsel-native');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'gsel-btn';
    const label = document.createElement('span');
    label.className = 'gsel-label';
    btn.appendChild(label);
    wrap.appendChild(btn);

    const sync = () => {
      const opt = sel.options[sel.selectedIndex];
      label.textContent = opt ? opt.textContent : '';
      wrap.classList.toggle('disabled', sel.disabled);
      btn.disabled = sel.disabled;
    };
    sync();

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (sel.disabled) return;
      if (GSEL.sel === sel) { closeGsel(); return; }
      closeGsel();
      openGsel(sel, btn);
    });

    sel.addEventListener('change', sync);
  });
}

function bind(route, param) {
  const page = $('#page');

  $$('[data-act]', page).forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const fn = ACTIONS[el.dataset.act];
      if (fn) guard(Promise.resolve(fn(el.dataset.arg, el)));
    });
  });

  $$('.section-h', page).forEach((h) => {
    h.addEventListener('click', () => h.closest('.section').classList.toggle('open'));
  });

  $$('[data-period]', page).forEach((b) => {
    b.addEventListener('click', async () => {
      $$('[data-period]', page).forEach((x) => x.classList.remove('primary'));
      b.classList.add('primary');
      const q = b.dataset.period ? '?период=' + encodeURIComponent(b.dataset.period) : '';
      const { data } = await api('/api/payroll' + q);
      $('#payroll-table').innerHTML = payrollTable(data, STATE.caps['payroll.all']);
      const hint = $('#period-hint');
      if (hint) {
        hint.textContent = data['границы'][0]
          ? data['месяц'] + ' · ' + data['границы'][0] + ' — ' + data['границы'][1]
          : 'Весь месяц целиком';
      }
    });
  });

  if (route === 'shop') bindShop();
  if (route === 'wh' && /#\/wh\/pick\/[\w-]+/.test(location.hash)) { bindPickPage(); return; }
  if (route === 'wh') bindWh();
  if (route === 'fbs') bindFbs();
  bindSyncChip();
  bindSyncBar();
  syncPaint();

  $$('form[data-op]', page).forEach((form) => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const body = {
        'тип': form.dataset.op,
        'id_товара': num(fd.get('id_товара')),
        'количество': num(fd.get('количество')),
        'коробка': fd.get('коробка') || '',
        'откуда': fd.get('откуда') || '',
        'куда': fd.get('куда') || '',
        'контрагент': fd.get('контрагент') || '',
        'комментарий': fd.get('комментарий') || '',
      };
      try {
        const res = await api('/api/shop/ops', { method: 'POST', body: JSON.stringify(body) });
        toast(`${form.dataset.op}: остаток ${nf(res['остаток'])} шт`, 'ok');
        await go('shop', currentShopTab());
      } catch (err) { toast(err.message, 'err'); }
    });
  });

  const annForm = $('form[data-form="ann"]', page);
  if (annForm) {
    annForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await api('/api/announcements', {
          method: 'POST',
          body: JSON.stringify({ 'текст': annForm.elements['текст'].value }),
        });
        toast('Объявление опубликовано');
        await go('ann');
      } catch (err) { toast(err.message, 'err'); }
    });
  }
}

// ------------------------------------------------------------------ boot
function cacheSession(me) {
  try {
    localStorage.setItem('v2me', JSON.stringify({
      user: me.user, caps: me.caps, company: me.company,
      periods: me.periods || [], roles: me.roles || {},
    }));
  } catch (e) { /* ignore */ }
}

async function boot() {
  syncLoad();
  await loadBrand();
  let me = null;
  try {
    me = await api('/api/me');
    cacheSession(me);
  } catch (e) {
    const cached = lsGet('v2me', null);
    const cachedCanWh = !!(cached && cached.caps && cached.caps['wh.view']);
    if (!cached || !SYNC.snap || !cachedCanWh) throw e;   // клиенту офлайн нечего показывать
    me = cached;
    SYNC.online = false;
    toast('Офлайн-режим · данные из снимка', 'warn');
  }
  STATE.me = me.user;
  STATE.caps = me.caps;
  STATE.company = me.company;
  STATE.periods = me.periods || [];
  STATE.roles = me.roles;
  STATE.visible = Array.isArray(me.visible) ? me.visible : null;
  STATE.clientVisible = Array.isArray(me.client_visible) ? me.client_visible : [];
  if (SYNC.online && !SYNC.snap && STATE.caps && STATE.caps['wh.view']) syncNow(false);
  const hash = location.hash.replace(/^#\//, '') || 'dash';
  let [route, param] = hash.split('/');
  const allowed = visibleNav(STATE.me.роль).map((n) => n.id);
  const known = allowed.includes(route) || route === 'batch';
  if (!known) { await go(homeRoute(allowed)); return; }
  // клиент всегда попадает в магазин и не видит склад
  if (STATE.me.роль === 'client') {
    MODE.sklad = false;
    try { localStorage.removeItem('v2mode'); } catch (e) {}
    route = 'shop';
    param = undefined;
  } else if (!SYNC.online || MODE.sklad) {
    route = 'wh';
    param = undefined;
  }
  await go(route, param);
}

let LAST_HASH = '';
window.addEventListener('hashchange', () => {
  if (!STATE.me) return;
  const raw = location.hash || '#/dash';
  if (raw === LAST_HASH) return;
  LAST_HASH = raw;
  const hash = raw.replace(/^#\//, '') || 'dash';
  const [route, param] = hash.split('/');
  go(route, param);
});

window.addEventListener('DOMContentLoaded', () => {
  if (new URLSearchParams(location.search).get('add') === '1') { loadBrand().then(renderLogin); return; }
  boot().catch((e) => {
    if (!navigator.onLine || /Failed to fetch|NetworkError|Load failed/i.test(String(e && e.message))) {
      renderOfflineStart();
    } else {
      renderLogin();
    }
  });
});
