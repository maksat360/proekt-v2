'use strict';

/* Модуль «Цех» · заказ на пошив. Без фреймворков: состояние + шаблоны. */

const API = '/api/cex';

const ST = {
  user: null,
  права: {},
  refs: { категории: [], модели: [], цвета: [], размеры: [] },
  заказы: [],
  клиенты: [],
  источник: '',
  view: 'new',
  tech: { очередь: [], отклонённые: [], статистика: {}, журнал: [] },
  cut: { партии: [], ставка: 15, партия: null },
  work: { этапы: [], очередь: [], мои: [], все: [], итог: {} },
  pack: { партии: [], партия: null },
  payroll: { месяц: '', люди: [], итого: {}, закрыто: 0, только_своё: false },
  sum: { кпі: {}, этапы: [], недостачи: [], артикулы: [], выработка: [] },
  cart: [],
  lastOrder: null,
  form: { источник: 'свой цех', поставщик: '', срок: '', комментарий: '', категория: '', модель: '', цвет: '', размер: '', количество: 1 },
  grid: {},        // «цвет|размер» → количество для выбранной модели
  gridFilter: '',
  поставщики: [],
};

// ------------------------------------------------------------- утилиты
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v) => Number(v || 0).toLocaleString('ru-RU');
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

function toast(message, kind = '') {
  const box = $('#cx-toast');
  box.textContent = message;
  box.className = 'cx-toast ' + kind;
  box.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { box.hidden = true; }, 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) {
    location.href = '/';
    throw new Error('Нужно войти заново');
  }
  let data = null;
  try { data = await res.json(); } catch (err) { data = null; }
  if (!res.ok || !data || data.ok === false) {
    throw new Error((data && data.error) || 'Не получилось выполнить запрос');
  }
  return data.data;
}

// --------------------------------------------------------------- данные
async function boot() {
  const data = await api(`${API}/bootstrap`);
  ST.user = data.user;
  ST.права = data.права || {};
  ST.refs = data.refs || ST.refs;
  ST.заказы = data.заказы || [];
  ST.клиенты = data.клиенты || [];
  ST.поставщики = data.поставщики || [];
  ST.источник = data.источник || '';
  renderUser();
  const want = new URLSearchParams(location.search).get('view');
  const allowed = {
    new: ST.права.создать, tech: ST.права.принимать, cut: ST.права.кроить,
    design: ST.права.карта, supply: ST.права.снабжение,
    work: ST.права.работать, pack: ST.права.упаковывать,
    payroll: ST.права.зарплата || ST.права.работать, sum: ST.права.зарплата,
    route: ST.права.маршрут, route_ord: ST.права.маршрут, route_fin: ST.права.маршрут, assign: ST.права.принимать,
    staff: ST.права.сотрудники || ST.права.этапы || ST.права.права,
  };
  if (want && allowed[want]) ST.view = want;
  if (!ST.права.создать && !want) {
    ST.view = ST.права.карта ? 'design' : ST.права.снабжение ? 'supply' : ST.права.принимать ? 'tech'
      : (ST.права.кроить ? 'cut'
        : (ST.права.упаковывать ? 'pack'
          : (ST.права.работать ? 'work' : (ST.права.зарплата ? 'payroll' : 'list'))));
  }
  if (multiRole()) {
    const only = asTabs();
    ST.workMode = isProd(asRole()) ? 'mine' : 'all';
    if (only && !want) ST.view = only[0];
    if (only && !only.includes(ST.view)) ST.view = only[0];
  }
  if (ST.view === 'tech') await loadTech();
  if (ST.view === 'design') await loadDesign();
  if (ST.view === 'supply') await loadSupply();
  if (ST.view === 'cut') await loadCut();
  if (ST.view === 'work') await loadWork();
  if (ST.view === 'pack') await loadPack();
  if (ST.view === 'payroll') await loadPayroll();
  if (ST.view === 'sum') await loadSummary();
  if (rtIsView(ST.view)) await loadRoutes();
  if (ST.view === 'assign') await loadAssign();
  if (ST.view === 'staff') await loadAccess();
  render();
}

async function loadSummary() {
  ST.sum = await api(`${API}/summary`);
}

async function loadPayroll(month) {
  const m = month || ST.payroll.месяц || new Date().toISOString().slice(0, 7);
  ST.payroll = await api(`${API}/payroll?месяц=${encodeURIComponent(m)}`);
}

async function loadPack() {
  const data = await api(`${API}/pack`);
  ST.pack = { ...data, партия: ST.pack.партия };
}

async function loadWork() {
  const mine = ST.workMode === 'mine' && !!ST.права.вся_работа;
  ST.work = await api(`${API}/work${mine ? '?режим=моя' : ''}`);
}

async function loadCut() {
  const data = await api(`${API}/cut`);
  ST.cut = { ...data, партия: ST.cut.партия };
}

async function loadTech() {
  const data = await api(`${API}/tech`);
  ST.tech = data;
}

async function refreshOrders() {
  const data = await api(`${API}/orders`);
  ST.заказы = data.заказы || data || [];
}

function modelsFor(category) {
  return (ST.refs.модели || []).filter((m) => !category || m.категория === category);
}

function sizesFor(model) {
  const item = (ST.refs.модели || []).find((m) => m.модель === model);
  const grid = (item && item.сетка) || 'числовая';
  const block = (ST.refs.размеры || []).find((r) => r.сетка === grid)
    || (ST.refs.размеры || [])[0];
  return (block && block.размеры) || [];
}

function modelInfo(model) {
  return (ST.refs.модели || []).find((m) => m.модель === model) || null;
}

function cartQty() {
  return ST.cart.reduce((s, i) => s + num(i.количество), 0);
}

// --------------------------------------------------------------- шапка
// «Работаю как»: человек с несколькими ролями выбирает, чем сейчас занят —
// видит только вкладки этой работы. Производственная роль (Оверлок, Карман…) — это
// и есть выбор операции: на экране работы остаются только её задачи.
const AS_ROLES = {
  all: { label: 'Все мои работы', tabs: null },
  admin: { label: 'Начальник', tabs: null },
  manager: { label: 'Менеджер', tabs: ['new', 'list', 'tech', 'payroll', 'sum', 'staff'] },
  designer: { label: 'Конструктор', tabs: ['design', 'list'] },
  supply: { label: 'Снабженец', tabs: ['supply', 'list'] },
  storekeeper: { label: 'Складчик', tabs: ['new', 'list'] },
  technologist: { label: 'Технолог', tabs: ['tech', 'assign', 'route_ord', 'route', 'route_fin', 'work', 'list', 'staff'] },
  cutter: { label: 'Закройщик', tabs: ['cut'] },
  packer: { label: 'Упаковщик', tabs: ['pack'] },
  accountant: { label: 'Бухгалтер', tabs: ['payroll', 'sum'] },
};

function isProd(r) { return ((ST.user || {}).производственные || []).includes(r); }
function asDef(k) {
  return AS_ROLES[k] || (isProd(k) ? { label: roleLabel(k), tabs: ['work', 'payroll'] } : null);
}
function isChief() { return ['admin', 'manager'].includes((ST.user || {}).роль); }
function myRoles() { return (ST.user || {}).роли || [(ST.user || {}).роль]; }
function multiRole() { return isChief() || myRoles().length > 1; }
// варианты «Работаю как»: начальнику — служебные роли и свои операции, остальным — «все мои работы» и свои роли
function asOptions() {
  const own = myRoles().filter((r) => asDef(r) && r !== 'all');
  if (!isChief()) return ['all', ...own];
  return [...Object.keys(AS_ROLES).filter((k) => k !== 'all'), ...own.filter((r) => !AS_ROLES[r])];
}

function asRole() {
  if (!multiRole()) return (ST.user || {}).роль;
  try {
    const v = localStorage.getItem(`cx_as_${(ST.user || {}).логин}`);
    if (v && asOptions().includes(v)) return v;
  } catch (e) { /* нет хранилища */ }
  return isChief() ? (ST.user || {}).роль : 'all';
}

function asTabs() { const r = asDef(asRole()); return r ? r.tabs : null; }

async function setAsRole(role) {
  try { localStorage.setItem(`cx_as_${(ST.user || {}).логин}`, role); } catch (e) { /* нет хранилища */ }
  ST.workMode = isProd(role) ? 'mine' : 'all';
  const tabs = asTabs();
  if (tabs && !tabs.includes(ST.view)) ST.view = tabs[0];
  await loadView(ST.view);
  renderUser();
  render();
}

async function loadView(v) {
  try {
    if (v === 'tech') await loadTech();
    if (v === 'design') await loadDesign();
    if (v === 'supply') await loadSupply();
    if (v === 'cut') await loadCut();
    if (v === 'work') await loadWork();
    if (v === 'pack') await loadPack();
    if (v === 'payroll') await loadPayroll();
    if (v === 'sum') await loadSummary();
    if (rtIsView(v)) await loadRoutes();
    if (v === 'assign') await loadAssign();
    if (v === 'staff') await loadAccess();
  } catch (err) { toast(err.message, 'err'); }
}

function renderUser() {
  const u = ST.user || {};
  if (!u.фио) { $('#cx-user').innerHTML = ''; return; }
  const cur = asRole();
  const roleBox = multiRole() ? `
    <label class="cx-asrole" title="Чем вы сейчас заняты — видны только нужные вкладки">
      <span>Работаю как</span>
      <select id="cx-asrole">${asOptions().map((k) =>
        `<option value="${esc(k)}" ${k === cur ? 'selected' : ''}>${esc(asDef(k).label)}${isChief() && k === u.роль ? ' (все вкладки)' : ''}</option>`).join('')}</select>
    </label>` : `<span class="cx-pill grey cx-asrole-fixed">${esc(roleLabel(u.роль))}</span>`;
  $('#cx-user').innerHTML = `${roleBox}
    <button class="v2acc-anchor" id="cx-acc" data-v2acc-anchor title="Аккаунты">
      <span class="avatar">${esc(window.V2Acc ? window.V2Acc.initials(u.фио) : '')}</span><span class="v2acc-name">${esc(u.фио)}</span>
      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 6l4 4 4-4"/></svg>
    </button>`;
}

function cxBeforeLeave() {
  if (rtIsView(ST.view) && typeof rtConfirmLeave === 'function' && !rtConfirmLeave()) return false;
  if (ST.view === 'assign' && typeof asConfirmLeave === 'function' && !asConfirmLeave()) return false;
  return true;
}

function roleLabel(role) {
  return ((ST.user || {}).роли_названия || {})[role] || role || '';
}

// -------------------------------------------------------------- каркас
function render() {
  const main = $('#cx-main');
  const totalOrders = ST.заказы.length;
  const totalPositions = ST.заказы.reduce((s, o) => s + num(o.позиций), 0);
  const totalUnits = ST.заказы.reduce((s, o) => s + num(o.штук), 0);
  const waiting = ST.заказы.filter((o) => o.статус === 'у технолога').length;

  const topTitle = $('#cx-top-title') || document.querySelector('.cx-top-title');
  if (topTitle) {
    topTitle.textContent = ({ work: 'Работа', cut: 'Крой', tech: 'Приёмка', design: 'Конструктор', supply: 'Снабжение',
      pack: 'Упаковка', payroll: 'Зарплата', sum: 'Сводка', route: 'Швейный маршрут', route_ord: 'Маршрут заказа', route_fin: 'Маршрут ГП', assign: 'Распределение',
      staff: 'Сотрудники и роли' })[ST.view] || 'Заказ на пошив';
  }
  const insideParty = ST.view === 'cut' && ST.cut.партия;
  const insideParty2 = ST.view === 'pack' && ST.pack.партия;
  const ownHeader = insideParty || insideParty2 || ['work', 'cut', 'tech', 'design', 'supply', 'pack', 'payroll', 'sum', 'route', 'route_ord', 'route_fin', 'assign', 'staff'].includes(ST.view);
  main.innerHTML = `
    ${ownHeader ? '' : `<div class="cx-hero">
      <div>
        <h1>Заказ на пошив</h1>
        <div class="cx-sub">Свой цех или поставщик, модель, количество по цветам и размерам — всё попадает в лист «Заказ на цех»</div>
      </div>
      <div class="cx-hero-actions">
        <button class="btn" data-act="refresh">Обновить</button>
      </div>
    </div>

    <div class="cx-kpis">
      <div class="cx-kpi"><div class="k">Заказов</div><div class="v">${nf(totalOrders)}</div><div class="m">оформлено всего</div></div>
      <div class="cx-kpi"><div class="k">Позиций</div><div class="v">${nf(totalPositions)}</div><div class="m">строк модель + цвет + размер</div></div>
      <div class="cx-kpi"><div class="k">Изделий</div><div class="v">${nf(totalUnits)}</div><div class="m">${nf(waiting)} ждут технолога · ${nf(ST.заказы.filter((o) => o.статус === 'у конструктора').length)} у конструктора</div></div>
    </div>`}

    ${ST.view === 'list' && !ST.права.создать && !ST.права.принимать ? `<div class="cx-notice">Заказы оформляет начальник. Здесь вы увидите заказы, когда они поступят в цех — приёмка появится следующим модулем.</div>` : ''}
    ${tabsHtml(totalOrders)}

    <div id="cx-view">${viewHtml()}</div>

    <div class="cx-foot">
      Данные пишутся прямо в <code>${esc(shortPath(ST.источник))}</code>. Поправили цифру в Excel — приложение увидит при следующем открытии экрана.
    </div>`;
}

function shortPath(path) {
  if (!path) return 'рабочую книгу';
  const parts = String(path).split('/');
  return parts.slice(-2).join('/');
}

function viewHtml() {
  if (ST.view === 'success' && ST.lastOrder) return successHtml();
  if (ST.view === 'tech') return techHtml();
  if (ST.view === 'design') return designHtml();
  if (ST.view === 'supply') return supplyHtml();
  if (ST.view === 'cut') return cutCardHtml();
  if (ST.view === 'work') return workHtml();
  if (ST.view === 'pack') return packHtml();
  if (ST.view === 'payroll') return payrollHtml();
  if (ST.view === 'sum') return summaryHtml();
  if (rtIsView(ST.view)) return routeHtml();
  if (ST.view === 'assign') return assignHtml();
  if (ST.view === 'staff') return accessHtml();
  if (ST.view === 'list') return listHtml();
  return newHtml();
}

// ------------------------------------------------------- новый заказ
function newHtml() {
  const f = ST.form;
  const cats = ST.refs.категории || [];
  const models = modelsFor(f.категория);
  const { colors, sizes, own } = modelVariants(f.модель);
  const info = modelInfo(f.модель);

  return `
  <div class="cx-grid">
    <div>
      <div class="cx-card">
        <div class="cx-card-h"><h3>От кого и когда</h3></div>
        <div class="cx-card-b">
          <div class="cx-formgrid">
            <div class="cx-field" style="grid-column: span 2">
              <label>От кого заказываем</label>
              <div class="cx-seg">
                <button type="button" class="${f.источник === 'свой цех' ? 'on' : ''}" data-act="source" data-v="свой цех">Свой цех</button>
                <button type="button" class="${f.источник === 'поставщик' ? 'on' : ''}" data-act="source" data-v="поставщик">Поставщик / надомник</button>
              </div>
              ${f.источник === 'поставщик' ? `
              <input class="input" id="cx-supplier" list="cx-suppliers" placeholder="Имя поставщика или надомника"
                     value="${esc(f.поставщик)}" data-field="поставщик" autocomplete="off" style="margin-top:8px">
              <datalist id="cx-suppliers">${(ST.поставщики || []).map((c) => `<option value="${esc(c)}">`).join('')}</datalist>
              <div class="cx-hint">Заказ пойдёт мимо технолога и кроя: ждём поставку, потом приёмка на склад.</div>`
              : '<div class="cx-hint">Заказ уйдёт конструктору → снабженцу → технологу → крой.</div>'}
            </div>
            <div class="cx-field">
              <label for="cx-due">Срок</label>
              <input class="input" id="cx-due" type="date" value="${esc(f.срок)}" data-field="срок">
            </div>
          </div>
          <div class="cx-field" style="margin-top:12px">
            <label for="cx-comment">Комментарий к заказу</label>
            <input class="input" id="cx-comment" placeholder="Ткань, фурнитура, пожелания" value="${esc(f.комментарий)}" data-field="комментарий">
          </div>
        </div>
      </div>

      <div class="cx-card">
        <div class="cx-card-h"><h3>Позиции</h3><span class="cx-hint">модель → количество по цветам и размерам</span></div>
        <div class="cx-card-b">
          <div class="cx-formgrid">
            <div class="cx-field">
              <label for="cx-cat">Категория</label>
              <select class="input" id="cx-cat" data-field="категория">
                <option value="">Все категории</option>
                ${cats.map((c) => `<option value="${esc(c)}" ${c === f.категория ? 'selected' : ''}>${esc(c)}</option>`).join('')}
              </select>
            </div>
            <div class="cx-field" style="grid-column: span 2">
              <label for="cx-model">Модель</label>
              <select class="input" id="cx-model" data-field="модель" ${models.length ? '' : 'disabled'}>
                <option value="">${models.length ? 'Выберите модель' : 'Сначала категорию'}</option>
                ${models.map((m) => `<option value="${esc(m.модель)}" ${m.модель === f.модель ? 'selected' : ''}>${esc(m.модель)}${m.название && m.название !== m.модель ? ' · ' + esc(m.название) : ''}</option>`).join('')}
              </select>
            </div>
          </div>
          ${info ? `<div class="cx-hint" style="margin-top:10px">Сетка размеров: ${info.сетка === 'буквенная' ? 'буквенная (S, M, L…)' : 'числовая (42, 44…)'}${info.цена ? ' · цена ' + esc(info.цена) + ' сом' : ''}</div>` : ''}
        </div>
        ${f.модель ? gridHtml(colors, sizes, own) : ''}
      </div>
    </div>

    <div class="cx-side">
      ${cartHtml()}
    </div>
  </div>`;
}

// цвета и размеры конкретной модели — из каталога «главный»
function modelVariants(model) {
  if (!model) return { colors: [], sizes: [], own: false };
  const v = (ST.refs.варианты || {})[model];
  const allColors = ST.refs.цвета || [];
  const grid = sizesFor(model);
  if (!v || !v.цвета.length) return { colors: allColors, sizes: grid, own: false };
  const tone = Object.fromEntries(allColors.map((c) => [c.цвет, c.тон]));
  let colors = v.цвета.map((c) => ({ цвет: c, тон: tone[c] || '' }));
  if (ST.gridAllColors) colors = colors.concat(allColors.filter((c) => !v.цвета.includes(c.цвет)));
  const order = Object.fromEntries(grid.map((x, i) => [x.размер, i]));
  const sizes = v.размеры.slice()
    .sort((a, b) => (order[a] ?? 999) - (order[b] ?? 999) || String(a).localeCompare(String(b), 'ru', { numeric: true }))
    .map((r) => ({ размер: r }));
  return { colors, sizes, own: true };
}

// таблица «цвет × размер»: пустые клетки пропускаются
function gridKey(color, size) { return `${color}|${size}`; }

function gridTotals() {
  let qty = 0, pos = 0;
  Object.values(ST.grid).forEach((v) => { const n = Math.round(num(v)); if (n > 0) { qty += n; pos += 1; } });
  return { qty, pos };
}

function gridHtml(colors, sizes, own) {
  if (!sizes.length) return '<div class="cx-card-b"><div class="cx-notice">У модели нет размерной сетки</div></div>';
  if (!colors.length) return '<div class="cx-card-b"><div class="cx-notice">Справочник цветов пуст</div></div>';
  const q = (ST.gridFilter || '').trim().toLowerCase();
  const rows = colors.map((c) => {
    const hide = q && !c.цвет.toLowerCase().includes(q) && !String(c.тон || '').toLowerCase().includes(q);
    const rowSum = sizes.reduce((a, s) => a + Math.max(0, Math.round(num(ST.grid[gridKey(c.цвет, s.размер)]))), 0);
    return `<tr data-grid-row="${esc(c.цвет)}" ${hide ? 'hidden' : ''} class="${rowSum ? 'filled' : ''}">
      <th class="cx-gcolor">${esc(c.цвет)}${c.тон ? `<span>${esc(c.тон)}</span>` : ''}</th>
      ${sizes.map((s) => {
        const v = ST.grid[gridKey(c.цвет, s.размер)];
        return `<td><input class="cx-gin" type="number" min="0" step="1" inputmode="numeric"
          data-grid="${esc(gridKey(c.цвет, s.размер))}" value="${v ? esc(v) : ''}" placeholder="·"
          aria-label="${esc(c.цвет)}, размер ${esc(s.размер)}"></td>`;
      }).join('')}
      <td class="cx-gsum" data-grid-sum="${esc(c.цвет)}">${rowSum ? nf(rowSum) : ''}</td>
    </tr>`;
  }).join('');
  const t = gridTotals();
  return `
    <div class="cx-gtools">
      <input class="input" id="cx-gfilter" placeholder="Найти цвет" value="${esc(ST.gridFilter)}" autocomplete="off">
      <span class="cx-hint">${own ? `У модели ${nf((ST.refs.варианты[ST.form.модель] || {}).цвета.length)} цв. и ${nf(sizes.length)} разм. по каталогу. ` : 'Модели нет в каталоге «главный» — показаны все цвета. '}Пустые клетки не попадут в заказ.</span>
      ${own ? `<label class="cx-gall"><input type="checkbox" data-act="grid-all" ${ST.gridAllColors ? 'checked' : ''}> новый цвет (показать все)</label>` : ''}
    </div>
    <div class="cx-gwrap">
      <table class="cx-gtable">
        <thead><tr><th class="cx-gcolor">Цвет / размер</th>${sizes.map((s) => `<th>${esc(s.размер)}</th>`).join('')}<th>Σ</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="cx-gfoot">
      <span id="cx-gtotal">${t.pos ? `${nf(t.pos)} поз. · <b>${nf(t.qty)}</b> шт` : 'Ничего не заполнено'}</span>
      <button class="btn ghost" data-act="grid-clear" ${t.pos ? '' : 'disabled'}>Очистить</button>
      <button class="btn primary" data-act="grid-add" id="cx-gadd" ${t.pos ? '' : 'disabled'}>Добавить в заказ</button>
    </div>`;
}

function gridRefresh(color) {
  const t = gridTotals();
  const tot = $('#cx-gtotal');
  if (tot) tot.innerHTML = t.pos ? `${nf(t.pos)} поз. · <b>${nf(t.qty)}</b> шт` : 'Ничего не заполнено';
  const add = $('#cx-gadd');
  if (add) add.disabled = !t.pos;
  const clr = document.querySelector('[data-act="grid-clear"]');
  if (clr) clr.disabled = !t.pos;
  if (color != null) {
    let sum = 0;
    Object.entries(ST.grid).forEach(([k, v]) => { if (k.split('|')[0] === color) sum += Math.max(0, Math.round(num(v))); });
    const cell = document.querySelector(`[data-grid-sum="${CSS.escape(color)}"]`);
    if (cell) cell.textContent = sum ? nf(sum) : '';
    const row = document.querySelector(`[data-grid-row="${CSS.escape(color)}"]`);
    if (row) row.classList.toggle('filled', sum > 0);
  }
}

function addFromGrid() {
  const f = ST.form;
  if (!f.модель) return toast('Выберите модель', 'err');
  const cat = f.категория || (modelInfo(f.модель) || {}).категория || '';
  let pos = 0, qty = 0;
  Object.entries(ST.grid).forEach(([k, v]) => {
    const n = Math.round(num(v));
    if (n <= 0) return;
    const [цвет, размер] = k.split('|');
    const same = ST.cart.find((i) => i.модель === f.модель && i.цвет === цвет && i.размер === размер);
    if (same) same.количество = num(same.количество) + n;
    else ST.cart.push({ категория: cat, модель: f.модель, цвет, размер, количество: n });
    pos += 1; qty += n;
  });
  if (!pos) return toast('Впишите количество хотя бы в одну клетку', 'err');
  ST.grid = {};
  render();
  toast(`В заказ добавлено: ${f.модель} — ${pos} поз., ${qty} шт`, 'ok');
}

function cartHtml() {
  const rows = ST.cart.map((item, i) => `
    <tr>
      <td>
        <div class="cx-cell-main">${esc(item.модель)}</div>
        <div class="cx-cell-sub">${esc(item.категория)} · ${esc(item.цвет)}</div>
      </td>
      <td>${esc(item.размер)}</td>
      <td class="num">${nf(item.количество)}</td>
      <td style="width:36px"><button class="cx-del" data-act="del" data-i="${i}" title="Убрать">×</button></td>
    </tr>`).join('');

  return `
    <div class="cx-card" id="cx-cart">
      <div class="cx-card-h"><h3>Состав заказа</h3><span class="cx-hint">${nf(ST.cart.length)} поз.</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        ${ST.cart.length ? `
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Изделие</th><th>Разм.</th><th class="num">Шт</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>` : `
        <div class="cx-empty"><b>Пока пусто</b>Выберите модель, впишите количество по цветам и размерам и нажмите «Добавить в заказ»</div>`}
      </div>
      <div class="cx-total">
        <span class="t">Итого</span>
        <span class="v">${nf(cartQty())}</span>
        <span class="u">шт</span>
      </div>
      <div class="cx-card-b" style="padding-top:14px">
        <button class="btn primary" style="width:100%" id="cx-submit" data-act="submit" ${ST.cart.length ? '' : 'disabled'}>
          ${ST.form.источник === 'поставщик' ? 'Оформить заказ поставщику' : 'Оформить и передать конструктору'}
        </button>
      </div>
    </div>`;
}

// -------------------------------------------------------------- список
function statusPill(status) {
  const s = status || '—';
  const kind = ['у технолога', 'у конструктора', 'у снабженца'].includes(s) ? 'orange'
    : s === 'принят' ? 'green'
      : s === 'отклонён' ? 'red'
        : s === 'новый' ? 'blue' : 'grey';
  return `<span class="cx-pill ${kind}">${esc(s)}</span>`;
}

function listHtml() {
  if (!ST.заказы.length) {
    return `<div class="cx-card"><div class="cx-empty"><b>Заказов пока нет</b>Первый заказ появится здесь и в Excel</div></div>`;
  }
  const rows = ST.заказы.map((o) => `
    <tr data-act="open" data-num="${esc(o.номер)}" style="cursor:pointer">
      <td><div class="cx-cell-main">№${esc(o.номер)}</div><div class="cx-cell-sub">${esc(o.дата)}</div></td>
      <td>${esc(o.клиент)}</td>
      <td class="num">${nf(o.позиций)}</td>
      <td class="num">${nf(o.штук)}</td>
      <td>${esc(o.срок || '—')}</td>
      <td>${statusPill(o.статус)}</td>
      <td>${esc(o.создал || '—')}</td>
    </tr>`).join('');

  return `
    <div class="cx-card">
      <div class="cx-card-h"><h3>Все заказы</h3><span class="cx-hint">${nf(ST.заказы.length)} записей · нажмите на строку</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Заказ</th><th>Клиент</th><th class="num">Поз.</th><th class="num">Шт</th><th>Срок</th><th>Статус</th><th>Создал</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

function successHtml() {
  const o = ST.lastOrder;
  return `
    <div class="cx-card">
      <div class="cx-success">
        <div class="mark">✓</div>
        <h2>Заказ №${esc(o.номер)} оформлен</h2>
        <p>${esc(o.клиент || '')} · ${nf(o.штук)} шт · записан в лист «Заказ на цех» ${o.источник === 'поставщик' ? 'и ждёт поставки' : 'и передан конструктору'}</p>
        <div class="cx-btn-row" style="justify-content:center">
          <button class="btn primary" data-act="tab" data-tab="new">Ещё заказ</button>
          <button class="btn" data-act="tab" data-tab="list">К списку</button>
        </div>
      </div>
    </div>`;
}

// ----------------------------------------------------------------- модал
function openOrder(numStr) {
  const o = ST.заказы.find((x) => String(x.номер) === String(numStr));
  if (!o) return;
  const rows = o.позиции.map((p) => `
    <tr>
      <td><div class="cx-cell-main">${esc(p.модель)}</div><div class="cx-cell-sub">${esc(p.категория)}</div></td>
      <td>${esc(p.цвет)}</td>
      <td>${esc(p.размер)}</td>
      <td class="num">${nf(p.количество)}</td>
    </tr>`).join('');
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h">
        <h3>Заказ №${esc(o.номер)}</h3>
        ${statusPill(o.статус)}
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-formgrid" style="margin-bottom:14px">
          <div class="cx-field"><label>Клиент</label><div>${esc(o.клиент)}</div></div>
          <div class="cx-field"><label>Срок</label><div>${esc(o.срок || '—')}</div></div>
          <div class="cx-field"><label>Создал</label><div>${esc(o.создал || '—')} · ${esc(o.дата)}</div></div>
        </div>
        ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
        <div class="cx-scroll">
          <table class="cx-table">
            <thead><tr><th>Модель</th><th>Цвет</th><th>Размер</th><th class="num">Шт</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="cx-total" style="margin:14px -20px -20px">
          <span class="t">Всего</span><span class="v">${nf(o.штук)}</span><span class="u">шт</span>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

function closeModal() {
  const modal = $('#cx-modal');
  modal.hidden = true;
  modal.innerHTML = '';
}

// --------------------------------------------------------- приёмка (модуль 2)
function tabsHtml(totalOrders) {
  const tabs = [];
  if (ST.права.создать) tabs.push(['new', 'Новый заказ']);
  const inStatus = (s) => ST.заказы.filter((o) => o.статус === s).length;
  if (ST.права.карта) { const n = inStatus('у конструктора'); tabs.push(['design', 'Конструктор' + (n ? ' ' + n : '')]); }
  if (ST.права.снабжение) { const n = inStatus('у снабженца'); tabs.push(['supply', 'Снабжение' + (n ? ' ' + n : '')]); }
  if (ST.права.принимать) {
    const n = (ST.tech.очередь || []).length;
    tabs.push(['tech', 'Приёмка' + (n ? ' ' + n : '')]);
  }
  if (ST.права.кроить) {
    const n = (ST.cut.партии || []).filter((p) => p.остаток > 0).length;
    tabs.push(['cut', 'Крой' + (n ? ' ' + n : '')]);
  }
  if (ST.права.работать) {
    const n = (ST.work.мои || []).length;
    tabs.push(['work', 'Работа' + (n ? ' ' + n : '')]);
  }
  if (ST.права.упаковывать) {
    const n = (ST.pack.партии || []).filter((p) => p.остаток > 0).length;
    tabs.push(['pack', 'Упаковка' + (n ? ' ' + n : '')]);
  }
  if (ST.права.зарплата || ST.права.работать) tabs.push(['payroll', 'Зарплата']);
  if (ST.права.зарплата) tabs.push(['sum', 'Сводка']);
  if (ST.права.принимать) tabs.push(['assign', 'Распределение']);
  if (ST.права.маршрут) {
    tabs.push(['route_ord', 'Маршрут заказа'], ['route', 'Швейный маршрут'], ['route_fin', 'Маршрут ГП']);
  }
  // одна вкладка управления — только у тех, кому выдано хоть одно разрешение на управление
  if (ST.права.сотрудники || ST.права.этапы || ST.права.права) tabs.push(['staff', 'Сотрудники и роли']);
  if (ST.права.создать || ST.права.принимать || ST.права.карта || ST.права.снабжение) tabs.push(['list', 'Заказы ' + nf(totalOrders)]);
  const only = asTabs();
  // вкладки доступа видны по правам, а не по роли: личное право открывает их любому
  const byRight = ['staff'];
  const shown = only ? tabs.filter(([id]) => only.includes(id) || byRight.includes(id)) : tabs.slice();
  tabs.length = 0; tabs.push(...shown);
  if (tabs.length < 2) return '';
  const active = ST.view === 'success' ? 'new' : ST.view;
  return `<div class="cx-tabs">${tabs.map(([id, label]) =>
    `<button class="cx-tab ${active === id ? 'on' : ''}" data-act="tab" data-tab="${id}">${label}</button>`).join('')}</div>`;
}

function techHtml() {
  const q = ST.tech.очередь || [];
  const rej = ST.tech.отклонённые || [];
  const st = ST.tech.статистика || {};
  const isAdmin = ST.user && ST.user.роль === 'admin';

  const cards = q.map((o) => `
    <div class="cx-qitem" data-act="open-tech" data-num="${esc(o.номер)}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Заказ №${esc(o.номер)} <span class="cx-pill orange">${esc(o.статус)}</span></div>
        <div class="cx-hint">${esc(o.клиент)} · ${nf(o.позиций)} поз. · ${nf(o.штук)} шт · срок ${esc(o.срок || '—')}</div>
      </div>
      <div class="cx-qright">
        <div class="cx-qsum">${nf(o.остаток)}<span> шт ждут решения</span></div>
        <button class="btn primary" data-act="open-tech" data-num="${esc(o.номер)}">Проверить</button>
      </div>
    </div>`).join('');

  const rejected = rej.map((o) => `
    <tr>
      <td><div class="cx-cell-main">№${esc(o.номер)}</div><div class="cx-cell-sub">${esc(o.дата)}</div></td>
      <td>${esc(o.клиент)}</td>
      <td class="num">${nf(o.штук)}</td>
      <td>${esc(o.причина || '—')}</td>
      <td style="text-align:right">
        ${isAdmin ? `<button class="btn" data-act="decide-return" data-num="${esc(o.номер)}">Вернуть в работу</button>` : ''}
      </td>
    </tr>`).join('');

  return `
    <div class="cx-hero compact">
      <div><h1>Приёмка</h1>
        <div class="cx-sub">Заказы ждут решения: проверить сырьё и загрузку, принять или отклонить</div></div>
    </div>
    <div class="cx-notice">
      Свободных швей: <b>${nf(st.свободно)}</b> из ${nf(st.швей)} · проверьте сырьё и загрузку, затем примите заказ или отклоните.
    </div>

    ${q.length ? `<div class="cx-queue">${cards}</div>` : `
      <div class="cx-card"><div class="cx-empty"><b>Очередь пуста</b>Новые заказы появятся здесь сразу после оформления</div></div>`}

    ${rej.length ? `
      <div class="cx-card" style="margin-top:14px">
        <div class="cx-card-h"><h3>Отклонённые</h3><span class="cx-hint">${nf(rej.length)}</span></div>
        <div class="cx-card-b" style="padding-bottom:0">
          <div class="cx-scroll" style="margin:0 -18px">
            <table class="cx-table">
              <thead><tr><th>Заказ</th><th>Клиент</th><th class="num">Шт</th><th>Причина</th><th></th></tr></thead>
              <tbody>${rejected}</tbody>
            </table>
          </div>
        </div>
      </div>` : ''}`;
}

function openTech(numStr) {
  const o = ST.заказы.find((x) => String(x.номер) === String(numStr));
  if (!o) return toast('Заказ не найден — обновите список', 'err');
  const rows = o.позиции.map((p, i) => `
    <tr>
      <td><div class="cx-cell-main">${esc(p.модель)}</div><div class="cx-cell-sub">${esc(p.характеристики || p.категория)}</div></td>
      <td>${esc(p.цвет)}</td>
      <td>${esc(p.размер)}</td>
      ${o.по_карте ? `<td class="num">${nf(p.заказано)}</td>` : ''}
      <td class="num">${nf(p.количество)}</td>
      <td class="num">${nf(p.принято)}</td>
      <td class="num">${nf(p.остаток)}</td>
      <td style="width:96px">
        ${p.остаток > 0
    ? `<input class="input cx-mini" type="number" min="0" max="${p.остаток}" value="${p.остаток}" data-accept="${i}">`
    : '<span class="cx-pill green">принято</span>'}
      </td>
    </tr>`).join('');

  const st = ST.tech.статистика || {};
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box wide">
      <div class="cx-modal-h">
        <h3>Заказ №${esc(o.номер)}</h3>
        ${statusPill(o.статус)}
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-formgrid" style="margin-bottom:12px">
          <div class="cx-field"><label>Клиент</label><div>${esc(o.клиент)}</div></div>
          <div class="cx-field"><label>Срок</label><div>${esc(o.срок || '—')}</div></div>
          <div class="cx-field"><label>Оформлен</label><div>${esc(o.дата)} · ${esc(o.создал || '')}</div></div>
        </div>
        ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}

        <div class="cx-scroll">
          <table class="cx-table">
            <thead><tr><th>Модель</th><th>Цвет</th><th>Размер</th>${o.по_карте ? '<th class="num">В заказе</th><th class="num">По карте</th>' : '<th class="num">Заказано</th>'}<th class="num">Принято</th><th class="num">Остаток</th><th>Принять</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>

        ${techFlowHtml(o.номер)}
        <div class="cx-decide">
          <div class="cx-field">
            <label>Сырьё</label>
            <select class="input" id="cx-mat">
              <option value="хватает">Хватает</option>
              <option value="не хватает">Не хватает</option>
            </select>
          </div>
          <div class="cx-field">
            <label>Свободных швей</label>
            <input class="input" id="cx-free" type="number" min="0" value="${num(st.свободно) || 0}">
          </div>
          <div class="cx-field" style="grid-column: span 2">
            <label>Комментарий</label>
            <input class="input" id="cx-tech-note" placeholder="Например: ткань придёт 27-го">
          </div>
          <div class="cx-field" style="grid-column: span 2">
            <label>Причина отказа</label>
            <input class="input" id="cx-reason" placeholder="Необязательно">
          </div>
        </div>

        <div class="cx-btn-row" style="margin-top:16px">
          <button class="btn primary" data-act="decide-accept" data-num="${esc(o.номер)}">Принять и создать партию</button>
          <button class="btn" data-act="decide-reject" data-num="${esc(o.номер)}">Отклонить</button>
        </div>
        <div class="cx-hint" style="margin-top:8px">Партия получит следующий номер и статус «крой» — её увидит закройщик.</div>
      </div>
    </div>`;
  modal.hidden = false;
}

// что подготовил снабженец и как конструктор менял количество
function techFlowHtml(numStr) {
  const mats = (ST.tech.сырьё || {})[numStr] || [];
  const hist = (ST.tech.история || {})[numStr] || [];
  if (!mats.length && !hist.length) return '';
  return `${mats.length ? `<h4 style="margin:16px 0 8px">Сырьё от снабженца</h4><div class="cx-scroll"><table class="cx-table">
      <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Нужно</th><th class="num">Есть</th><th>Статус</th><th>Комментарий</th></tr></thead>
      <tbody>${mats.map((m) => `<tr><td>${esc(m.материал)}</td><td>${esc(m.цвет)}</td><td class="num">${nf(m.нужно)} ${esc(m.ед)}</td>
        <td class="num">${nf(m.есть)}</td><td>${esc(m.статус || '—')}</td><td>${esc(m.комментарий)}</td></tr>`).join('')}</tbody></table></div>` : ''}
    ${hist.length ? `<details style="margin-top:12px"><summary>История карты конструктора · ${nf(hist.length)}</summary>${flHistoryHtml(hist)}</details>` : ''}`;
}

async function submitDecision(kind, numStr) {
  const o = ST.заказы.find((x) => String(x.номер) === String(numStr));
  if (!o) return;
  const body = {
    номер: String(numStr),
    решение: kind,
    сырьё: ($('#cx-mat') || {}).value || '',
    свободных_швей: Number(($('#cx-free') || {}).value || 0),
    причина: ($('#cx-reason') || {}).value || '',
    комментарий: ($('#cx-tech-note') || {}).value || '',
    позиции: [],
  };
  if (kind === 'принять') {
    document.querySelectorAll('[data-accept]').forEach((el) => {
      const i = Number(el.dataset.accept);
      const p = o.позиции[i];
      const qty = Math.max(0, Math.min(Number(el.value || 0), p.остаток));
      if (qty > 0) body.позиции.push({ модель: p.модель, цвет: p.цвет, размер: p.размер, количество: qty });
    });
    if (!body.позиции.length) return toast('Укажите, сколько принять', 'err');
  }
  try {
    const res = await api(`${API}/tech/decision`, { method: 'POST', body: JSON.stringify(body) });
    closeModal();
    await refreshOrders();
    await loadTech();
    render();
    if (kind === 'принять') toast(`Партия №${res.партия} создана · ${nf(res.штук)} шт`, 'ok');
    else if (kind === 'вернуть') toast('Заказ возвращён в работу', 'ok');
    else toast('Заказ отклонён', 'ok');
  } catch (err) {
    toast(err.message, 'err');
  }
}

// ------------------------------------------------------------- крой (модуль 3)
function cutHtml() {
  if (ST.cut.партия) return cutPartyHtml();
  const list = (ST.cut.партии || []);
  const waiting = list.filter((p) => p.остаток > 0);
  const done = list.filter((p) => p.остаток <= 0);

  const card = (p) => `
    <div class="cx-qitem" data-act="open-party" data-num="${esc(p.номер)}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Партия №${esc(p.номер)} <span class="cx-pill ${p.статус === 'крой' ? 'orange' : 'blue'}">${esc(p.статус)}</span></div>
        <div class="cx-hint">${esc(p.клиент)} · ${esc(p.категория)} ${esc(p.модель)} · план ${nf(p.план)} шт · срок ${esc(p.срок || '—')}</div>
      </div>
      <div class="cx-qright">
        <div class="cx-qsum">${nf(p.остаток)}<span>осталось раскроить</span></div>
        <button class="btn primary" data-act="open-party" data-num="${esc(p.номер)}">${p.остаток > 0 ? 'Кроить' : 'Открыть'}</button>
      </div>
    </div>`;

  return `
    <div class="cx-hero compact">
      <div><h1>Крой</h1>
        <div class="cx-sub">Партии после технолога: настилы, факт и недостача</div></div>
    </div>
    <div class="cx-notice">Партия приходит сюда после технолога. Факт может отличаться от плана — так и должно быть, недостача останется видна.</div>
    ${waiting.length ? `<div class="cx-queue">${waiting.map(card).join('')}</div>` : `
      <div class="cx-card"><div class="cx-empty"><b>Нет партий в крое</b>Партии появятся, когда технолог примет заказ</div></div>`}
    ${done.length ? `
      <div class="cx-card" style="margin-top:14px">
        <div class="cx-card-h"><h3>Раскроено</h3><span class="cx-hint">${nf(done.length)}</span></div>
        <div class="cx-card-b" style="padding-bottom:0">
          <div class="cx-scroll" style="margin:0 -18px">
            <table class="cx-table">
              <thead><tr><th>Партия</th><th>Клиент</th><th>Модель</th><th class="num">План</th><th class="num">Факт</th><th>Статус</th></tr></thead>
              <tbody>${done.map((p) => `<tr data-act="open-party" data-num="${esc(p.номер)}" style="cursor:pointer">
                <td>№${esc(p.номер)}</td><td>${esc(p.клиент)}</td><td>${esc(p.модель)}</td>
                <td class="num">${nf(p.план)}</td><td class="num">${nf(p.раскроено)}</td>
                <td>${statusPill(p.статус)}</td></tr>`).join('')}</tbody>
            </table>
          </div>
        </div>
      </div>` : ''}`;
}

function cutPartyHtml() {
  const p = (ST.cut.партии || []).find((x) => x.номер === ST.cut.партия);
  if (!p) return `<div class="cx-card"><div class="cx-empty"><b>Партия не найдена</b>Обновите страницу</div></div>`;

  const rows = p.строки.map((r) => `
    <tr>
      <td>${esc(r.цвет)}</td>
      <td>${esc(r.размер)}</td>
      <td class="num">${nf(r.план)}</td>
      <td class="num">${nf(r.раскроено)}</td>
      <td class="num ${r.остаток ? '' : 'cx-muted'}">${nf(r.остаток)}</td>
    </tr>`).join('');

  const настилы = p.настилы.map((n) => `
    <div class="cx-cut-block">
      <div class="cx-cut-head">
        <b>Настил ${esc(n.номер)}</b>
        <span class="cx-hint">${esc(n.дата)} · ${esc(n.закройщик)}</span>
        <span class="cx-cut-sum">${nf(n.шт)} шт</span>
      </div>
      <table class="cx-table cx-table-sm">
        <tbody>${n.строки.map((r) => `<tr>
          <td>${esc(r.цвет)}</td><td>${esc(r.размер)}</td>
          <td class="num">план ${nf(r.план)}</td><td class="num">факт ${nf(r.факт)}</td>
        </tr>`).join('')}</tbody>
      </table>
    </div>`).join('');

  return `
    <div class="cx-backline"><button class="btn ghost" data-act="cut-back">← Все партии</button></div>
    <div class="cx-hero compact">
      <div>
        <h1>Партия №${esc(p.номер)}</h1>
        <div class="cx-sub">${esc(p.клиент)} · ${esc(p.категория)} ${esc(p.модель)} · срок ${esc(p.срок || '—')} · ${statusPill(p.статус)}</div>
      </div>
      <div class="cx-hero-actions">
        <button class="btn primary" data-act="new-cut" ${p.остаток > 0 ? '' : 'disabled'}>Добавить настил</button>
      </div>
    </div>

    <div class="cx-kpis">
      <div class="cx-kpi"><div class="k">План</div><div class="v">${nf(p.план)}</div><div class="m">шт по партии</div></div>
      <div class="cx-kpi"><div class="k">Раскроено</div><div class="v">${nf(p.раскроено)}</div><div class="m">${nf(p.прогресс)}% партии</div></div>
      <div class="cx-kpi"><div class="k">Осталось</div><div class="v">${nf(p.остаток)}</div><div class="m">шт раскроить</div></div>
    </div>

    <div class="cx-grid">
      <div>
        <div class="cx-card">
          <div class="cx-card-h"><h3>План по цвету и размеру</h3><span class="cx-hint">${nf(p.строки.length)} строк</span></div>
          <div class="cx-card-b" style="padding-bottom:0">
            <div class="cx-scroll" style="margin:0 -18px">
              <table class="cx-table">
                <thead><tr><th>Цвет</th><th>Размер</th><th class="num">План</th><th class="num">Раскроено</th><th class="num">Остаток</th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div class="cx-side">
        <div class="cx-card">
          <div class="cx-card-h"><h3>Настилы</h3><span class="cx-hint">${nf(p.настилы.length)}</span></div>
          <div class="cx-card-b">
            ${настилы || '<div class="cx-empty" style="padding:14px"><b>Пока не кроили</b>Начните с «Добавить настил»</div>'}
          </div>
        </div>
      </div>
    </div>`;
}

function openCutModal() {
  const p = (ST.cut.партии || []).find((x) => x.номер === ST.cut.партия);
  if (!p) return;
  const next = (p.настилы.reduce((m, n) => Math.max(m, _intSafe(n.настил)), 0)) + 1;
  const rows = p.строки.filter((r) => r.остаток > 0).map((r, i) => `
    <tr>
      <td>${esc(r.цвет)}</td>
      <td>${esc(r.размер)}</td>
      <td class="num">${nf(r.остаток)}</td>
      <td style="width:96px"><input class="input cx-mini" type="number" min="0" max="${r.остаток}"
        value="${r.остаток}" data-cut="i" data-color="${esc(r.цвет)}" data-size="${esc(r.размер)}"></td>
    </tr>`).join('');

  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box wide">
      <div class="cx-modal-h">
        <h3>Настил ${esc(p.номер)}/${esc(next)}</h3>
        <span class="cx-pill orange">крой</span>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-scroll">
          <table class="cx-table">
            <thead><tr><th>Цвет</th><th>Размер</th><th class="num">Остаток</th><th>Раскроить</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="cx-decide">
          <div class="cx-field"><label>Комментарий</label>
            <input class="input" id="cx-cut-note" placeholder="Например: один брак по 44-му"></div>
          <div class="cx-field"><label>Начисление за раскрой</label>
            <div class="cx-cut-total"><span id="cx-cut-qty">0</span> шт × <span id="cx-cut-rate">${nf(ST.cut.ставка)}</span> сом = <b id="cx-cut-sum">0</b> сом</div></div>
        </div>
        <div class="cx-btn-row" style="margin-top:16px">
          <button class="btn primary" data-act="save-cut">Сохранить настил</button>
        </div>
        <div class="cx-hint" style="margin-top:8px">Факт меньше плана — норма: остаток уйдёт в следующий настил, разница останется в отчёте.</div>
      </div>
    </div>`;
  modal.hidden = false;
  recalcCut();

  document.querySelectorAll('[data-cut]').forEach((el) => {
    el.addEventListener('input', recalcCut);
  });
}

function _intSafe(v) { return parseInt(String(v || 0), 10) || 0; }

function recalcCut() {
  let qty = 0;
  document.querySelectorAll('[data-cut]').forEach((el) => {
    const max = _intSafe(el.max);
    let v = _intSafe(el.value);
    if (v < 0) v = 0;
    if (v > max) v = max;
    qty += v;
  });
  const rate = Number(ST.cut.ставка || 0);
  const q = $('#cx-cut-qty'), s = $('#cx-cut-sum');
  if (q) q.textContent = nf(qty);
  if (s) s.textContent = nf(Math.round(qty * rate));
}

async function saveCut() {
  const p = (ST.cut.партии || []).find((x) => x.номер === ST.cut.партия);
  if (!p) return;
  const позиции = [];
  document.querySelectorAll('[data-cut]').forEach((el) => {
    const qty = _intSafe(el.value);
    if (qty > 0) позиции.push({ цвет: el.dataset.color, размер: el.dataset.size, факт: qty });
  });
  if (!позиции.length) return toast('Укажите, сколько раскроено', 'err');
  try {
    const res = await api(`${API}/cut`, {
      method: 'POST',
      body: JSON.stringify({
        партия: p.номер,
        позиции,
        комментарий: ($('#cx-cut-note') || {}).value || '',
      }),
    });
    closeModal();
    await loadCut();
    render();
    toast(`Настил ${res.настил}: ${nf(res.штук)} шт · ${nf(res.сумма)} сом`, 'ok');
  } catch (err) {
    toast(err.message, 'err');
  }
}

// ------------------------------------------------------------ швеи (модуль 4)
function isBoss() {  // возвращать и сдавать чужую работу — право «cex.boss»
  return !!ST.права.чужая_работа;
}

function workTaskPill(t) {
  if (t.статус === 'можно' && !t.можно) return '<span class="cx-pill grey">по очереди</span>';
  const kind = { можно: 'green', 'в работе': 'blue', готово: 'grey', ждёт: 'orange' }[t.статус] || 'grey';
  const text = { можно: 'можно брать', 'в работе': 'в работе', готово: 'готово', ждёт: 'ждёт пред. этап' }[t.статус] || t.статус;
  return `<span class="cx-pill ${kind}">${text}</span>`;
}

function workModeSwitch() {
  return `<div class="cx-seg cx-workmode">
      <button type="button" class="${ST.workMode === 'mine' ? '' : 'on'}" data-act="work-mode" data-mode="all">Работа цеха</button>
      <button type="button" class="${ST.workMode === 'mine' ? 'on' : ''}" data-act="work-mode" data-mode="mine">Моя работа (как швея)</button>
    </div>`;
}

// Партия (родитель) → её настилы (дочерние). По умолчанию свёрнута; если настилов нет —
// ни стрелки, ни пустого списка. Раскрытые партии помним до перезагрузки страницы.
ST.ptOpen = ST.ptOpen || new Set();

function nastilWord(n) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return 'настил';
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'настила';
  return 'настилов';
}

function partyAccordion({ num, title, sub, total, count, badge, body }) {
  const has = count > 0;
  const open = has && ST.ptOpen.has(String(num));
  const head = `<span class="${has ? 'ac-arrow' : 'pt-no-arrow'}" aria-hidden="true"></span>
      <span class="pt-title"><b>${title}</b><span class="cx-hint">${sub}</span>${badge ? `<span>${badge}</span>` : ''}</span>
      <span class="pt-total"><b>${nf(total)}</b><span>шт${has ? ` · ${nf(count)} ${nastilWord(count)}` : ''}</span></span>`;
  return `<div class="cx-card cx-party pt-party ${open ? 'open' : ''}">
    ${has ? `<button class="pt-head" data-act="pt-toggle" data-num="${esc(num)}" aria-expanded="${open}">${head}</button>`
      : `<div class="pt-head static">${head}</div>`}
    ${has ? `<div class="ac-collapse"><div class="ac-collapse-in"><div class="pt-kids">${body}</div></div></div>` : ''}
  </div>`;
}

function ptToggle(el) {
  const num = String(el.dataset.num);
  const box = el.closest('.pt-party');
  const open = !ST.ptOpen.has(num);
  if (open) ST.ptOpen.add(num); else ST.ptOpen.delete(num);
  if (box && box.classList.contains('pt-party')) {   // без перерисовки — чтобы анимация была плавной
    box.classList.toggle('open', open);
    el.setAttribute('aria-expanded', String(open));
    return;
  }
  render();
}

function workHtml() {
  const lead = !!ST.права.вся_работа;
  if (!lead) return sewHtml();
  if (ST.workMode === 'mine') return (isProd(asRole()) ? '' : workModeSwitch()) + sewHtml();
  const w = ST.work || {};
  const mine = w.мои || [];
  const cards = w.партии || [];
  const all = w.все || [];
  const t = w.итог || {};
  const boss = !!ST.права.вся_работа;

  const mineRows = mine.map((m) => `
    <div class="cx-qitem cx-qwork">
      <div class="cx-qmain">
        <div class="cx-qtitle">Настил ${esc(m.партия)}/${esc(m.настил)} <span class="cx-pill blue">${esc(m.этап_название)}</span></div>
        <div class="cx-hint">взято ${esc(m.начало)}${boss && m.ФИО ? ' · ' + esc(m.ФИО) : ''}</div>
      </div>
      <div class="cx-qright">
        <div class="cx-qsum">${nf(m.количество)}<span>шт в работе</span></div>
        <button class="btn primary" data-act="work-done" data-id="${m.id}" data-qty="${m.количество}">Сдать</button>
      </div>
    </div>`).join('');

  const partyCards = cards.map((c) => {
    const kids = (c.настилы || []).filter((l) => l.задачи.length);
    const lines = kids.map((l) => `
      <div class="cx-nrow ${l.готов ? 'done' : ''}">
        <div class="cx-nhead"><span class="pt-kid-tag">${esc(l.номер)}</span><b>Настил ${esc(l.номер)}</b><span>${nf(l.шт)} шт</span>${l.готов ? '<span class="cx-pill grey">прошёл маршрут</span>' : ''}</div>
        <div class="cx-ntasks">
          ${l.задачи.map((tk) => `
            <div class="cx-ntask ${tk.можно ? 'go' : ''}">
              <div class="cx-ntask-main">
                <div class="cx-ntask-name">${esc(tk.название)} ${workTaskPill(tk)}</div>
                <div class="cx-hint">${boss ? (tk.кто ? esc(tk.ФИО) : '<span class="cx-warn">не распределено</span>') + ' · ' : ''}сдано ${nf(tk.сдано)} из ${nf(l.шт)}${tk.в_работе ? ' · в работе ' + nf(tk.в_работе) : ''} · ${nf(tk.ставка)} сом/шт</div>
              </div>
              ${tk.можно ? `<button class="btn primary" data-act="work-take" data-stage="${esc(tk.этап)}" data-num="${esc(c.номер)}"
                  data-nas="${esc(l.настил)}" data-max="${tk.доступно}">Взять ${nf(tk.доступно)}</button>`
                : (tk.статус === 'можно' ? '<span class="cx-hint">после предыдущего настила</span>' : '')}
            </div>`).join('')}
        </div>
      </div>`).join('');
    const ready = kids.reduce((n, l) => n + l.задачи.filter((t) => t.можно).length, 0);
    return partyAccordion({
      num: c.номер,
      title: `Партия №${esc(c.номер)}`,
      sub: `${esc(c.категория)} ${esc(c.модель)} · ${esc(c.клиент)} · срок ${esc(c.срок || '—')}${c.остаток_крой ? ` · докроить ${nf(c.остаток_крой)}` : ''}`,
      total: c.раскроено,
      count: kids.length,
      badge: ready ? `<span class="cx-pill green">можно взять: ${nf(ready)}</span>` : '',
      body: lines,
    });
  }).join('');

  const allRows = boss ? `
    <div class="cx-card" style="margin-top:14px">
      <div class="cx-card-h"><h3>Сейчас в работе</h3><span class="cx-hint">${nf(all.length)}</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Кто</th><th>Настил</th><th>Этап</th><th class="num">Шт</th><th>Взял</th><th></th></tr></thead>
            <tbody>${all.length ? all.map((m) => `<tr>
              <td>${esc(m.ФИО || m.логин)}</td>
              <td>${esc(m.партия)}/${esc(m.настил)}</td>
              <td>${esc(m.этап_название)}</td>
              <td class="num">${nf(m.количество)}</td>
              <td>${esc(m.начало)}</td>
              <td style="text-align:right">${isBoss() ? `<button class="btn" data-act="work-cancel" data-id="${m.id}">Вернуть</button>` : ''}</td>
            </tr>`).join('') : '<tr><td colspan="6" class="cx-empty" style="padding:18px">Никто ничего не взял</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>` : '';

  return `
    <div class="cx-hero compact">
      <div><h1>${boss ? 'Работа цеха' : 'Моя работа'}</h1>
        <div class="cx-sub">${boss ? 'Партии по настилам: кто закреплён, сколько сдано, что ждёт' : 'Здесь только ваша работа. Настилы берутся по порядку: сначала меньший номер'}</div>
        ${boss ? '' : `<div class="cx-roles">${(w.мои_этапы || []).length
          ? 'Ваши роли: ' + w.мои_этапы.map((x) => `<span class="cx-pill blue">${esc(x.название)}</span>`).join(' ')
          : '<span class="cx-hint">Производственные роли вам не назначены.</span>'}</div>`}</div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div>
    </div>
    <div class="cx-kpis">
      <div class="cx-kpi"><div class="k">${boss ? 'Сдано сегодня мной' : 'Моя смена'}</div><div class="v">${nf(t.сегодня_шт || 0)}</div><div class="m">шт сдано сегодня</div></div>
      <div class="cx-kpi"><div class="k">Заработано</div><div class="v">${nf(t.сегодня_сумма || 0)}</div><div class="m">сом за сегодня</div></div>
      <div class="cx-kpi"><div class="k">В работе</div><div class="v">${nf(boss ? all.length : mine.length)}</div><div class="m">${boss ? 'задач у всех' : 'задач у меня'}</div></div>
    </div>
    ${workModeSwitch()}
    ${boss && w.не_распределено ? `<div class="cx-notice warn">Не распределено задач: ${nf(w.не_распределено)}. Их никто не видит. <button class="btn" data-act="tab" data-tab="assign">Распределить</button></div>` : ''}

    <div class="cx-card">
      <div class="cx-card-h"><h3>У меня в работе</h3><span class="cx-hint">${nf(mine.length)}</span></div>
      <div class="cx-card-b">
        ${mineRows || '<div class="cx-empty" style="padding:16px"><b>Пока ничего</b>Возьмите работу из партии ниже</div>'}
      </div>
    </div>

    ${partyCards || `<div class="cx-card"><div class="cx-empty"><b>${boss ? 'Нет партий после кроя' : 'Для вас пока нет работы'}</b>${boss ? 'Партия появится здесь, когда закройщик внесёт настил' : 'Технолог ещё не закрепил за вами настилы'}</div></div>`}
    ${allRows}`;
}

function openTakeModal(stage, num, max, nas) {
  const q = (ST.work.очередь || []).find((x) => x.этап === stage && x.партия === num && x.настил === nas) || {};
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h">
        <h3>Взять работу</h3>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-formgrid">
          <div class="cx-field"><label>Настил</label><div>${esc(num)}/${esc(nas)} · ${esc(q.модель || '')}</div></div>
          <div class="cx-field"><label>Этап</label><div>${esc(q.этап_название || stage)}</div></div>
          <div class="cx-field"><label>Ставка</label><div>${nf(q.ставка)} сом/шт</div></div>
        </div>
        <div class="cx-field" style="margin-top:14px; max-width:220px">
          <label>Сколько беру, шт</label>
          <input class="input" id="cx-take-qty" type="number" min="1" max="${max}" value="${max}">
        </div>
        <div class="cx-btn-row" style="margin-top:16px">
          <button class="btn primary" data-act="work-take-save" data-stage="${esc(stage)}"
            data-num="${esc(num)}" data-nas="${esc(nas)}" data-max="${max}">Взять в работу</button>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

function openDoneModal(id, qty) {
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h">
        <h3>Сдать работу</h3>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-field" style="max-width:220px">
          <label>Сколько сдаю, шт</label>
          <input class="input" id="cx-done-qty" type="number" min="1" max="${qty}" value="${qty}">
        </div>
        <div class="cx-hint" style="margin-top:8px">Если не всё получилось — укажите меньше, остаток вернётся в очередь.</div>
        <div class="cx-btn-row" style="margin-top:16px">
          <button class="btn primary" data-act="work-done-save" data-id="${id}" data-max="${qty}">Сдать</button>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

async function takeWork(stage, num, max, nas) {
  const qty = Math.min(_intSafe($('#cx-take-qty').value), _intSafe(max));
  if (qty <= 0) return toast('Укажите количество', 'err');
  try {
    await api(`${API}/work/take`, { method: 'POST', body: JSON.stringify({ этап: stage, партия: num, настил: nas, количество: qty }) });
    closeModal();
    await loadWork();
    render();
    toast(`Взято ${nf(qty)} шт`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

async function finishWork(id, max) {
  const qty = Math.min(_intSafe($('#cx-done-qty').value), _intSafe(max));
  if (qty <= 0) return toast('Укажите количество', 'err');
  try {
    const res = await api(`${API}/work/done`, { method: 'POST', body: JSON.stringify({ id: Number(id), количество: qty }) });
    closeModal();
    await loadWork();
    render();
    toast(`Сдано ${nf(qty)} шт · ${nf(res.сумма)} сом`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

async function cancelWork(id) {
  try {
    await api(`${API}/work/cancel`, { method: 'POST', body: JSON.stringify({ id: Number(id) }) });
    await loadWork();
    render();
    toast('Работа возвращена в очередь', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// -------------------------------------------------------- упаковка (модуль 5)
function packHtml() {
  if (ST.pack.партия) return packPartyHtml();
  const list = (ST.pack.партии || []);
  const waiting = list.filter((p) => p.остаток > 0);
  const done = list.filter((p) => p.остаток <= 0);

  const card = (p) => `
    <div class="cx-qitem" data-act="open-pack" data-num="${esc(p.номер)}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Партия №${esc(p.номер)} <span class="cx-pill ${p.остаток > 0 ? 'orange' : 'green'}">${esc(p.статус)}</span></div>
        <div class="cx-hint">${esc(p.клиент)} · ${esc(p.категория)} ${esc(p.модель)} · факт ${nf(p.факт)} шт · коробок ${nf(p.коробки.length)}</div>
      </div>
      <div class="cx-qright">
        <div class="cx-qsum">${nf(p.готово_к_упаковке || 0)}<span>готово к упаковке · всего осталось ${nf(p.остаток)}</span></div>
        <button class="btn primary" data-act="open-pack" data-num="${esc(p.номер)}">${p.готово_к_упаковке > 0 ? 'Упаковать' : 'Открыть'}</button>
      </div>
    </div>`;

  return `
    <div class="cx-hero compact">
      <div><h1>Упаковка</h1>
        <div class="cx-sub">Упаковываем по настилам, не дожидаясь всей партии: доступно то, что прошло весь маршрут</div></div>
    </div>
    ${waiting.length ? `<div class="cx-queue">${waiting.map(card).join('')}</div>` : `
      <div class="cx-card"><div class="cx-empty"><b>Нечего упаковывать</b>Партии появятся, когда швеи закроют последний этап</div></div>`}
    ${done.length ? `
      <div class="cx-card" style="margin-top:14px">
        <div class="cx-card-h"><h3>Упаковано</h3><span class="cx-hint">${nf(done.length)}</span></div>
        <div class="cx-card-b" style="padding-bottom:0">
          <div class="cx-scroll" style="margin:0 -18px">
            <table class="cx-table">
              <thead><tr><th>Партия</th><th>Клиент</th><th>Модель</th><th class="num">Шт</th><th class="num">Коробок</th><th></th></tr></thead>
              <tbody>${done.map((p) => `<tr>
                <td>№${esc(p.номер)}</td><td>${esc(p.клиент)}</td><td>${esc(p.модель)}</td>
                <td class="num">${nf(p.упаковано)}</td><td class="num">${nf(p.коробки.length)}</td>
                <td style="text-align:right"><button class="btn" data-act="open-pack" data-num="${esc(p.номер)}">Открыть</button></td>
              </tr>`).join('')}</tbody>
            </table>
          </div>
        </div>
      </div>` : ''}`;
}

function packPartyHtml() {
  const p = (ST.pack.партии || []).find((x) => x.номер === ST.pack.партия);
  if (!p) return `<div class="cx-card"><div class="cx-empty"><b>Партия не найдена</b>Обновите страницу</div></div>`;

  const rows = p.строки.map((r) => `
    <tr>
      <td>${esc(r.цвет)}</td><td>${esc(r.размер)}</td>
      <td class="num">${nf(r.факт)}</td><td class="num">${nf(r.упаковано)}</td>
      <td class="num ${r.остаток ? '' : 'cx-muted'}">${nf(r.остаток)}</td>
    </tr>`).join('');

  const boxes = (p.коробки || []).map((b) => `
    <div class="cx-box-row">
      <div><b>Коробка ${esc(b)}</b><div class="cx-hint">партия ${esc(p.номер)}</div></div>
      <button class="btn" data-act="print-box" data-num="${esc(p.номер)}" data-box="${esc(b)}">Печатать этикетки</button>
    </div>`).join('');

  return `
    <div class="cx-backline"><button class="btn ghost" data-act="pack-back">← Все партии</button></div>
    <div class="cx-hero compact">
      <div>
        <h1>Партия №${esc(p.номер)}</h1>
        <div class="cx-sub">${esc(p.клиент)} · ${esc(p.категория)} ${esc(p.модель)} · ${statusPill(p.статус)}</div>
      </div>
      <div class="cx-hero-actions">
        <a class="btn" style="text-decoration:none" href="/cex/items?партия=${encodeURIComponent(p.номер)}" target="_blank">Этикетки изделий</a>
        <button class="btn primary" data-act="new-pack" ${p.готово_к_упаковке > 0 ? '' : 'disabled'}>Упаковать в коробку</button>
      </div>
    </div>

    <div class="cx-kpis">
      <div class="cx-kpi"><div class="k">Готово к упаковке</div><div class="v">${nf(p.готово_к_упаковке || 0)}</div><div class="m">шт из готовых настилов · раскроено ${nf(p.факт)}</div></div>
      <div class="cx-kpi"><div class="k">Упаковано</div><div class="v">${nf(p.упаковано)}</div><div class="m">в ${nf(p.коробки.length)} коробках</div></div>
      <div class="cx-kpi"><div class="k">Осталось</div><div class="v">${nf(p.остаток)}</div><div class="m">шт упаковать</div></div>
    </div>

    <div class="cx-grid">
      <div>
        <div class="cx-card">
          <div class="cx-card-h"><h3>Что упаковываем</h3><span class="cx-hint">${nf(p.строки.length)} строк</span></div>
          <div class="cx-card-b" style="padding-bottom:8px"><div class="cx-nchips">${(p.настилы || []).map((n) => `<span class="cx-pill ${n.готов ? 'green' : 'grey'}">настил ${esc(p.номер)}/${esc(n.настил)} · ${nf(n.шт)} шт · ${n.готов ? 'готов' : 'в цехе'}</span>`).join(' ')}</div></div>
          <div class="cx-card-b" style="padding-bottom:0">
            <div class="cx-scroll" style="margin:0 -18px">
              <table class="cx-table">
                <thead><tr><th>Цвет</th><th>Размер</th><th class="num">Готово</th><th class="num">Упаковано</th><th class="num">Можно упаковать</th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div class="cx-side">
        <div class="cx-card">
          <div class="cx-card-h"><h3>Коробки</h3><span class="cx-hint">${nf(p.коробки.length)}</span></div>
          <div class="cx-card-b">
            ${boxes || '<div class="cx-empty" style="padding:14px"><b>Пока пусто</b>Соберите первую коробку</div>'}
          </div>
        </div>
      </div>
    </div>`;
}

function openPackModal() {
  const p = (ST.pack.партии || []).find((x) => x.номер === ST.pack.партия);
  if (!p) return;
  const rows = p.строки.filter((r) => r.остаток > 0).map((r) => `
    <tr>
      <td>${esc(r.цвет)}</td><td>${esc(r.размер)}</td>
      <td class="num">${nf(r.остаток)}</td>
      <td style="width:96px"><input class="input cx-mini" type="number" min="0" max="${r.остаток}"
        value="${r.остаток}" data-pack data-color="${esc(r.цвет)}" data-size="${esc(r.размер)}"></td>
    </tr>`).join('');

  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box wide">
      <div class="cx-modal-h">
        <h3>Коробка · партия ${esc(p.номер)}</h3>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button>
      </div>
      <div class="cx-modal-b">
        <div class="cx-field" style="max-width:200px">
          <label>Номер коробки</label>
          <input class="input" id="cx-box" value="${esc(p.коробка_следующая)}">
        </div>
        <div class="cx-scroll" style="margin-top:14px">
          <table class="cx-table">
            <thead><tr><th>Цвет</th><th>Размер</th><th class="num">Остаток</th><th>В коробку</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="cx-cut-total" style="margin-top:10px">
          В коробке: <b id="cx-pack-qty">0</b> шт · этикеток: <b id="cx-pack-lbl">0</b>
        </div>
        <div class="cx-btn-row" style="margin-top:12px">
          <button class="btn primary" data-act="save-pack">Собрать коробку</button>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
  recalcPack();
  document.querySelectorAll('[data-pack]').forEach((el) => el.addEventListener('input', recalcPack));
}

function recalcPack() {
  let qty = 0, labels = 0;
  document.querySelectorAll('[data-pack]').forEach((el) => {
    let v = _intSafe(el.value);
    const max = _intSafe(el.max);
    if (v > max) v = max;
    if (v < 0) v = 0;
    qty += v;
    if (v > 0) labels += 1;
  });
  const q = $('#cx-pack-qty'), l = $('#cx-pack-lbl');
  if (q) q.textContent = nf(qty);
  if (l) l.textContent = nf(labels);
}

async function savePack() {
  const p = (ST.pack.партии || []).find((x) => x.номер === ST.pack.партия);
  if (!p) return;
  const позиции = [];
  document.querySelectorAll('[data-pack]').forEach((el) => {
    const qty = _intSafe(el.value);
    if (qty > 0) позиции.push({ цвет: el.dataset.color, размер: el.dataset.size, количество: qty });
  });
  if (!позиции.length) return toast('Укажите, что кладём в коробку', 'err');
  try {
    const res = await api(`${API}/pack`, {
      method: 'POST',
      body: JSON.stringify({ партия: p.номер, коробка: ($('#cx-box') || {}).value || '', позиции }),
    });
    await loadPack();
    const num = p.номер, box = res.коробка;
    closeModal();
    render();
    showPrintModal(num, box, res);
  } catch (err) { toast(err.message, 'err'); }
}

function showPrintModal(num, box, res) {
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h"><h3>Коробка ${esc(box)} собрана</h3>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button></div>
      <div class="cx-modal-b" style="text-align:center; padding-bottom:24px">
        <div class="cx-success" style="padding:18px 0 6px">
          <div class="mark">✓</div>
          <h2>${nf(res.штук)} шт · ${nf(res.этикеток)} этикеток</h2>
          <p>Партия №${esc(num)} · коробка ${esc(box)}</p>
        </div>
        <div class="cx-btn-row" style="justify-content:center">
          <button class="btn primary" data-act="print-box" data-num="${esc(num)}" data-box="${esc(box)}">Печатать этикетки</button>
          <button class="btn" data-act="close-modal">Готово</button>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

function printLabels(num, box) {
  const url = `/cex/labels?партия=${encodeURIComponent(num)}&коробка=${encodeURIComponent(box)}&print=1`;
  window.open(url, '_blank');
}

// -------------------------------------------------------- зарплата (модуль 6)
function money(v) {
  return Number(v || 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 });
}

function payrollHtml() {
  const p = ST.payroll || {};
  const people = p.люди || [];
  const t = p.итого || {};
  const boss = ST.права.зарплата;

  const rows = people.map((x) => `
    <tr data-act="pay-row" data-login="${esc(x.логин)}" style="cursor:pointer">
      <td><div class="cx-cell-main">${esc(x.ФИО)}</div><div class="cx-cell-sub">${esc(x.должность || x.логин)}</div></td>
      <td>${esc(x.тип)}</td>
      <td class="num">${x.ставка ? nf(x.ставка) : '—'}</td>
      <td>${esc(x.периодичность)}</td>
      <td class="num">${nf(x.шт)}</td>
      <td class="num"><b>${money(x['к выплате'])}</b></td>
      <td style="text-align:right">${boss ? `<button class="btn" data-act="edit-card" data-login="${esc(x.логин)}">Изменить</button>` : ''}</td>
    </tr>`).join('');

  return `
    <div class="cx-hero compact">
      <div><h1>${boss ? 'Зарплата' : 'Мой заработок'}</h1>
        <div class="cx-sub">Сдельно по этапам, оклад и смены — по договору каждого сотрудника</div></div>
      <div class="cx-hero-actions">
        <input class="input" type="month" id="cx-pay-month" value="${esc(p.месяц || '')}" style="width:160px">
      </div>
    </div>

    <div class="cx-kpis">
      <div class="cx-kpi"><div class="k">К выплате</div><div class="v">${money(t['к выплате'] || 0)}</div><div class="m">сом за месяц</div></div>
      <div class="cx-kpi"><div class="k">Сотрудников</div><div class="v">${nf(t.людей || 0)}</div><div class="m">в расчёте</div></div>
      <div class="cx-kpi"><div class="k">Изделий</div><div class="v">${nf(t.шт || 0)}</div><div class="m">шт по сдельному</div></div>
    </div>

    ${boss ? `<div class="cx-notice">Сдельно: ${money(t.сдельно)} · оклад: ${money(t.оклад)} · смены: ${money(t.смены)}${p.закрыто ? ` · в ведомости ${nf(p.закрыто)} строк` : ''}</div>` : ''}

    <div class="cx-card">
      <div class="cx-card-h"><h3>${boss ? 'Начисления' : 'Мои начисления'}</h3>
        <span class="cx-hint">${nf(people.length)} · нажмите на строку для деталей</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Сотрудник</th><th>Тип</th><th class="num">Ставка</th><th>Периодичность</th><th class="num">Шт</th><th class="num">К выплате</th><th></th></tr></thead>
            <tbody>${rows || '<tr><td colspan="7" class="cx-empty" style="padding:20px">За этот месяц начислений нет</td></tr>'}</tbody>
          </table>
        </div>
      </div>
      ${boss ? `<div class="cx-card-b" style="padding-top:14px">
        <div class="cx-btn-row">
          <button class="btn primary" data-act="close-payroll">Начислить за месяц</button>
          <span class="cx-hint" style="align-self:center">запишет ведомость в лист «Зарплата»</span>
        </div>
      </div>` : ''}
    </div>`;
}

function openPayRow(login) {
  const person = (ST.payroll.люди || []).find((x) => x.логин === login);
  if (!person) return;
  const periods = person.периоды.map((q) => `
    <tr><td>${esc(q.название)}</td><td class="num">${nf(q.шт)}</td>
      <td class="num">${money(q['к выплате'])}</td></tr>`).join('');
  const articles = (person.артикулы || []).map((a) => `
    <tr><td>${esc(a.модель)}</td><td class="num">${nf(a.шт)}</td><td class="num">${money(a.сумма)}</td></tr>`).join('');
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h"><h3>${esc(person.ФИО)}</h3>
        <span class="cx-pill grey">${esc(person.тип)}</span>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button></div>
      <div class="cx-modal-b">
        <div class="cx-formgrid" style="margin-bottom:14px">
          <div class="cx-field"><label>Периодичность</label><div>${esc(person.периодичность)}</div></div>
          <div class="cx-field"><label>Ставка</label><div>${person.ставка ? nf(person.ставка) + ' сом' : '—'}</div></div>
          <div class="cx-field"><label>Доп. роли</label><div>${esc(person.этап || '—')}</div></div>
        </div>
        <h4 style="margin:6px 0 4px; font-size:13px">По периодам</h4>
        <table class="cx-table"><thead><tr><th>Период</th><th class="num">Шт</th><th class="num">Сумма</th></tr></thead>
          <tbody>${periods}</tbody></table>
        <h4 style="margin:16px 0 4px; font-size:13px">По артикулам</h4>
        <table class="cx-table"><thead><tr><th>Модель</th><th class="num">Шт</th><th class="num">Сумма</th></tr></thead>
          <tbody>${articles || '<tr><td colspan="3" class="cx-empty">Сдельных работ нет</td></tr>'}</tbody></table>
        <div class="cx-total" style="margin:14px -20px -20px">
          <span class="t">К выплате</span><span class="v">${money(person['к выплате'])}</span><span class="u">сом</span>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

function openCard(login) {
  const person = (ST.payroll.люди || []).find((x) => x.логин === login);
  if (!person) return;
  const types = ['сдельная', 'оклад', 'посменная'];
  const per = ['месяц', '3 раза', 'неделя'];
  const modal = $('#cx-modal');
  modal.innerHTML = `
    <div class="cx-modal-box">
      <div class="cx-modal-h"><h3>Оплата · ${esc(person.ФИО)}</h3>
        <button class="btn cx-close" data-act="close-modal">Закрыть</button></div>
      <div class="cx-modal-b">
        <div class="cx-formgrid">
          <div class="cx-field"><label>Тип оплаты</label>
            <select class="input" id="cx-card-type">
              ${types.map((t) => `<option ${t === person.тип ? 'selected' : ''}>${t}</option>`).join('')}
            </select></div>
          <div class="cx-field"><label>Ставка, сом</label>
            <input class="input" id="cx-card-rate" type="number" min="0" value="${person.ставка || 0}"></div>
          <div class="cx-field"><label>Периодичность</label>
            <select class="input" id="cx-card-per">
              ${per.map((t) => `<option ${t === person.периодичность ? 'selected' : ''}>${t}</option>`).join('')}
            </select></div>
          <div class="cx-field" style="grid-column: span 2"><label>Этапы (роли)</label>
            <div class="cx-hint" style="padding-top:8px">${esc(person.этап || 'дополнительных ролей нет')}. Роли выдают во вкладке «Сотрудники и роли».</div></div>
        </div>
        <div class="cx-hint" style="margin-top:10px">Сдельная — по выдачам, оклад — ставка в месяц, посменная — ставка за смену из листа «Смены».</div>
        <div class="cx-btn-row" style="margin-top:16px">
          <button class="btn primary" data-act="save-card" data-login="${esc(login)}">Сохранить</button>
        </div>
      </div>
    </div>`;
  modal.hidden = false;
}

async function saveCard(login) {
  try {
    await api(`${API}/staff/card`, {
      method: 'POST',
      body: JSON.stringify({
        логин: login,
        'тип оплаты': ($('#cx-card-type') || {}).value,
        ставка: _intSafe(($('#cx-card-rate') || {}).value),
        периодичность: ($('#cx-card-per') || {}).value,
      }),
    });
    closeModal();
    await loadPayroll(ST.payroll.месяц);
    render();
    toast('Карточка сохранена', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

async function closePayroll() {
  try {
    const res = await api(`${API}/payroll/close`, {
      method: 'POST', body: JSON.stringify({ месяц: ST.payroll.месяц }),
    });
    await loadPayroll(ST.payroll.месяц);
    render();
    toast(`Начислено строк: ${res.начислено}`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// ---------------------------------------------------------- сводка (модуль 7)
function summaryHtml() {
  const s = ST.sum || {};
  const k = s.кпі || {};
  const stages = s.этапы || [];
  const maxStage = Math.max(1, ...stages.map((x) => x.ждёт));
  const days = s.выработка || [];
  const maxDay = Math.max(1, ...days.map((d) => d.шт));

  const bars = stages.map((x) => `
    <div class="cx-bar-row">
      <div class="cx-bar-name">${esc(x.название)}</div>
      <div class="cx-bar-track"><div class="cx-bar-fill" style="width:${Math.round(100 * x.ждёт / maxStage)}%"></div></div>
      <div class="cx-bar-val">${nf(x.ждёт)} <span>шт · ${nf(x.партий)} парт.</span></div>
    </div>`).join('');

  const chart = days.map((d) => `
    <div class="cx-day">
      <div class="cx-day-bar" style="height:${Math.max(4, Math.round(90 * d.шт / maxDay))}%"></div>
      <div class="cx-day-lbl">${esc(d.дата)}</div>
      <div class="cx-day-val">${d.шт ? nf(d.шт) : ''}</div>
    </div>`).join('');

  const shortages = (s.недостачи || []).map((x) => `
    <tr><td>№${esc(x.партия)}</td><td>${esc(x.модель)}</td><td>${esc(x.клиент)}</td>
      <td class="num">${nf(x.план)}</td><td class="num">${nf(x.факт)}</td>
      <td class="num cx-neg">−${nf(x.недостача)}</td></tr>`).join('');

  const articles = (s.артикулы || []).map((x) => `
    <tr><td><div class="cx-cell-main">${esc(x.модель)}</div><div class="cx-cell-sub">${esc(x.категория)}</div></td>
      <td class="num">${nf(x.партий)}</td><td class="num">${nf(x.план)}</td>
      <td class="num">${nf(x.раскроено)}</td><td class="num">${nf(x.упаковано)}</td>
      <td class="num ${x.недостача ? 'cx-neg' : ''}">${x.недостача ? '−' + nf(x.недостача) : '—'}</td>
      <td class="num">${money(x.сумма)}</td></tr>`).join('');

  return `
    <div class="cx-hero compact">
      <div><h1>Сводка</h1>
        <div class="cx-sub">Незавершённое производство, выработка, недостачи и артикулы</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh-sum">Обновить</button></div>
    </div>

    <div class="cx-kpis cx-kpis-6">
      <div class="cx-kpi"><div class="k">В работе</div><div class="v">${nf(k.заказов_в_работе || 0)}</div><div class="m">партий в цеху</div></div>
      <div class="cx-kpi"><div class="k">Ждут технолога</div><div class="v">${nf(k.ждут_технолога || 0)}</div><div class="m">заказов</div></div>
      <div class="cx-kpi"><div class="k">Раскроено</div><div class="v">${nf(k.раскроено || 0)}</div><div class="m">из ${nf(k.план || 0)} по плану</div></div>
      <div class="cx-kpi"><div class="k">В производстве</div><div class="v">${nf(k.в_производстве || 0)}</div><div class="m">шт ждут этапов</div></div>
      <div class="cx-kpi"><div class="k">Упаковано</div><div class="v">${nf(k.упаковано || 0)}</div><div class="m">шт</div></div>
      <div class="cx-kpi"><div class="k">Недостача</div><div class="v ${k.недостача ? 'cx-neg' : ''}">${nf(k.недостача || 0)}</div><div class="m">шт по крою</div></div>
    </div>

    <div class="cx-grid">
      <div>
        <div class="cx-card">
          <div class="cx-card-h"><h3>Незавершённое производство</h3><span class="cx-hint">по этапам маршрута</span></div>
          <div class="cx-card-b">
            ${bars || '<div class="cx-empty">Этапы не настроены</div>'}
          </div>
        </div>
      </div>
      <div class="cx-side">
        <div class="cx-card">
          <div class="cx-card-h"><h3>Выработка</h3><span class="cx-hint">7 дней</span></div>
          <div class="cx-card-b">
            <div class="cx-days">${chart}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="cx-card">
      <div class="cx-card-h"><h3>Недостача по крою</h3><span class="cx-hint">${nf((s.недостачи || []).length)} партий</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Партия</th><th>Модель</th><th>Клиент</th><th class="num">План</th><th class="num">Факт</th><th class="num">Минус</th></tr></thead>
            <tbody>${shortages || '<tr><td colspan="6" class="cx-empty" style="padding:18px">Недостач нет</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="cx-card">
      <div class="cx-card-h"><h3>По артикулам</h3><span class="cx-hint">${nf((s.артикулы || []).length)} моделей</span></div>
      <div class="cx-card-b" style="padding-bottom:0">
        <div class="cx-scroll" style="margin:0 -18px">
          <table class="cx-table">
            <thead><tr><th>Модель</th><th class="num">Партий</th><th class="num">План</th><th class="num">Раскроено</th><th class="num">Упаковано</th><th class="num">Недостача</th><th class="num">Сумма сделки</th></tr></thead>
            <tbody>${articles || '<tr><td colspan="7" class="cx-empty" style="padding:18px">Пока нет партий</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

// ------------------------------------------------------------- действия
function addFromForm() {
  const f = ST.form;
  if (!f.категория) return toast('Выберите категорию', 'err');
  if (!f.модель) return toast('Выберите модель', 'err');
  if (!f.цвет) return toast('Выберите цвет', 'err');
  if (!f.размер) return toast('Выберите размер', 'err');
  const qty = Math.max(1, Math.round(num(f.количество)));
  const same = ST.cart.find((i) => i.модель === f.модель && i.цвет === f.цвет && i.размер === f.размер);
  if (same) same.количество = num(same.количество) + qty;
  else ST.cart.push({ категория: f.категория, модель: f.модель, цвет: f.цвет, размер: f.размер, количество: qty });
  f.количество = 1;
  render();
  toast(`Добавлено: ${f.модель}, ${f.цвет}, ${f.размер} — ${qty} шт`, 'ok');
}

async function submitOrder() {
  if (!ST.cart.length) return toast('Добавьте хотя бы одну позицию', 'err');
  const fromSupplier = ST.form.источник === 'поставщик';
  if (fromSupplier && !ST.form.поставщик.trim()) return toast('Укажите поставщика или надомника', 'err');
  if (Object.values(ST.grid).some((v) => Math.round(num(v)) > 0)
      && !confirm('В таблице остались заполненные клетки, которые не добавлены в заказ. Оформить без них?')) return;
  const btn = $('#cx-submit');
  if (btn) btn.disabled = true;
  try {
    const res = await api(`${API}/orders`, {
      method: 'POST',
      body: JSON.stringify({
        источник: ST.form.источник,
        поставщик: fromSupplier ? ST.form.поставщик.trim() : '',
        срок: ST.form.срок,
        комментарий: ST.form.комментарий,
        позиции: ST.cart,
      }),
    });
    ST.lastOrder = { ...res, клиент: fromSupplier ? ST.form.поставщик.trim() : 'Свой цех', штук: cartQty(), источник: ST.form.источник };
    if (fromSupplier && !ST.поставщики.includes(ST.form.поставщик.trim())) ST.поставщики.push(ST.form.поставщик.trim());
    ST.cart = [];
    ST.form = { ...ST.form, комментарий: '', количество: 1 };
    await refreshOrders();
    ST.view = 'success';
    render();
    toast(`Заказ №${res.номер} записан в Excel`, 'ok');
  } catch (err) {
    toast(err.message, 'err');
    if (btn) btn.disabled = false;
  }
}

// --------------------------------------------------------------- события
document.addEventListener('click', (ev) => {
  const a = ev.target.closest('#cx-acc');
  if (a && window.V2Acc) window.V2Acc.open(a, { after: '/cex/', beforeLeave: cxBeforeLeave });
});
document.addEventListener('change', (ev) => {
  if (ev.target && ev.target.id === 'cx-asrole') setAsRole(ev.target.value);
});

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;

  if (act === 'pt-toggle') { ptToggle(el); return; }

  if (act === 'tab') {
    if (rtIsView(ST.view) && el.dataset.tab !== ST.view && !rtConfirmLeave()) return;
    if (ST.view === 'assign' && el.dataset.tab !== 'assign' && !asConfirmLeave()) return;
    ST.view = el.dataset.tab;
    if (rtIsView(ST.view)) {
      try { await loadRoutes(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'assign') {
      try { await loadAssign(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'staff') {
      try { await loadAccess(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'tech') {
      try { await loadTech(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'design' || ST.view === 'supply') {
      FL.num = '';  // у конструктора и снабженца свой открытый заказ
      try { await (ST.view === 'design' ? loadDesign() : loadSupply()); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'cut') {
      try { await loadCut(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'work') {
      try { await loadWork(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'pack') {
      try { await loadPack(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'payroll') {
      try { await loadPayroll(); } catch (err) { toast(err.message, 'err'); }
    }
    if (ST.view === 'sum') {
      try { await loadSummary(); } catch (err) { toast(err.message, 'err'); }
    }
    render();
    return;
  }
  if (act === 'add') { addFromForm(); return; }
  if (act === 'work-mode') {
    ST.workMode = el.dataset.mode;
    try { await loadWork(); } catch (err) { toast(err.message, 'err'); }
    render(); return;
  }
  if (act === 'source') { ST.form.источник = el.dataset.v; render(); return; }
  if (act === 'grid-add') { addFromGrid(); return; }
  if (act === 'grid-clear') { ST.grid = {}; render(); return; }
  if (act === 'grid-all') { ST.gridAllColors = el.checked; render(); return; }
  if (act === 'del') {
    ST.cart.splice(Number(el.dataset.i), 1);
    render();
    return;
  }
  if (act === 'submit') { await submitOrder(); return; }
  if (act === 'open') { openOrder(el.dataset.num); return; }
  if (act === 'open-tech') { openTech(el.dataset.num); return; }
  if (act === 'refresh-sum') {
    try { await loadSummary(); render(); toast('Сводка обновлена', 'ok'); }
    catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (act === 'pay-row') { openPayRow(el.dataset.login); return; }
  if (act === 'edit-card') { ev.stopPropagation(); openCard(el.dataset.login); return; }
  if (act === 'save-card') { await saveCard(el.dataset.login); return; }
  if (act === 'close-payroll') { await closePayroll(); return; }
  if (act === 'open-pack') { ST.pack.партия = el.dataset.num; render(); return; }
  if (act === 'pack-back') { ST.pack.партия = null; render(); return; }
  if (act === 'new-pack') { openPackModal(); return; }
  if (act === 'save-pack') { await savePack(); return; }
  if (act === 'print-box') { printLabels(el.dataset.num, el.dataset.box); return; }
  if (act === 'work-take') {
    openTakeModal(el.dataset.stage, el.dataset.num, Number(el.dataset.max), el.dataset.nas); return;
  }
  if (act === 'work-take-save') {
    await takeWork(el.dataset.stage, el.dataset.num, Number(el.dataset.max), el.dataset.nas); return;
  }
  if (act === 'work-done') {
    openDoneModal(el.dataset.id, Number(el.dataset.qty)); return;
  }
  if (act === 'work-done-save') {
    await finishWork(el.dataset.id, Number(el.dataset.max)); return;
  }
  if (act === 'work-cancel') { await cancelWork(el.dataset.id); return; }
  if (act === 'open-party') {
    ST.cut.партия = el.dataset.num; render(); return;
  }
  if (act === 'cut-back') { ST.cut.партия = null; render(); return; }
  if (act === 'new-cut') { openCutModal(); return; }
  if (act === 'save-cut') { await saveCut(); return; }
  if (act === 'decide-accept') { await submitDecision('принять', el.dataset.num); return; }
  if (act === 'decide-reject') { await submitDecision('отклонить', el.dataset.num); return; }
  if (act === 'decide-return') { await submitDecision('вернуть', el.dataset.num); return; }
  if (act === 'close-modal') { closeModal(); return; }
  if (act === 'refresh') {
    try {
      await refreshOrders();
      if (ST.view === 'work') await loadWork();
      if (ST.view === 'pack') await loadPack();
      if (ST.view === 'cut') await loadCut();
      if (ST.view === 'tech') await loadTech();
      if (ST.view === 'design') await loadDesign();
      if (ST.view === 'supply') await loadSupply();
      render();
      toast('Обновлено из Excel', 'ok');
    } catch (err) { toast(err.message, 'err'); }
    return;
  }
});

document.addEventListener('change', async (ev) => {
  if (ev.target && ev.target.id === 'cx-pay-month') {
    try { await loadPayroll(ev.target.value); render(); }
    catch (err) { toast(err.message, 'err'); }
    return;
  }
  const el = ev.target.closest('[data-field]');
  if (!el) return;
  const field = el.dataset.field;
  ST.form[field] = el.value;

  if (field === 'категория') {
    ST.form.модель = '';
    ST.form.размер = '';
    render();
  } else if (field === 'модель') {
    ST.form.размер = '';
    if (Object.values(ST.grid).some((v) => Math.round(num(v)) > 0)
        && !confirm('В таблице есть заполненные клетки другой модели. Сбросить их?')) {
      el.value = ST.form.модель = ST._lastModel || '';
      return;
    }
    ST.grid = {};
    ST.gridAllColors = false;
    ST._lastModel = ST.form.модель;
    render();
  }
});

document.addEventListener('input', (ev) => {
  const g = ev.target.closest('[data-grid]');
  if (g) {
    const v = Math.max(0, Math.round(num(g.value)));
    if (v > 0) ST.grid[g.dataset.grid] = v; else delete ST.grid[g.dataset.grid];
    gridRefresh(g.dataset.grid.split('|')[0]);
    return;
  }
  if (ev.target.id === 'cx-gfilter') {
    ST.gridFilter = ev.target.value;
    const q = ST.gridFilter.trim().toLowerCase();
    document.querySelectorAll('[data-grid-row]').forEach((tr) => {
      const name = tr.dataset.gridRow.toLowerCase();
      const tone = (tr.querySelector('.cx-gcolor span') || {}).textContent || '';
      tr.hidden = !!q && !name.includes(q) && !tone.toLowerCase().includes(q);
    });
    return;
  }
  const el = ev.target.closest('[data-field]');
  if (!el) return;
  ST.form[el.dataset.field] = el.value;
});

document.addEventListener('keydown', (ev) => {
  // Enter в таблице — на строку ниже (следующий видимый цвет), как в Excel
  const g = ev.target.closest && ev.target.closest('[data-grid]');
  if (g && ev.key === 'Enter' && !ev.metaKey && !ev.ctrlKey) {
    ev.preventDefault();
    const col = g.closest('td').cellIndex;
    let tr = g.closest('tr').nextElementSibling;
    while (tr && tr.hidden) tr = tr.nextElementSibling;
    const next = tr && tr.cells[col] && tr.cells[col].querySelector('input');
    if (next) { next.focus(); next.select(); }
    return;
  }
  if (ev.key === 'Escape') closeModal();
  if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) submitOrder();
});

$('#cx-modal').addEventListener('click', (ev) => {
  if (ev.target.id === 'cx-modal') closeModal();
});

boot().catch((err) => {
  $('#cx-main').innerHTML = `<div class="cx-notice err">${esc(err.message)}</div>`;
});
