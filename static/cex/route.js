'use strict';

/* Модуль «Цех» · вкладка «Маршрут»: визуальный редактор цепочки процессов.
   Работает поверх cex.js (ST, api, esc, nf, toast, render). */

// три вкладки — три вида маршрута на одном редакторе
const RT_VIEWS = { route: 'шв', route_ord: 'заказ', route_fin: 'гп' };
function rtIsView(v) { return Object.prototype.hasOwnProperty.call(RT_VIEWS, v || ST.view); }

const RT = {
  kind: 'шв',          // вид маршрута: шв | заказ | гп
  data: null,          // ответ /routes
  mode: 'tpl',         // 'tpl' — шаблон, 'party' — партия
  key: 'Основной',     // имя шаблона или № партии
  draft: null,         // [{код, после[], склад_гп, кто, активен}]
  name: '',            // имя шаблона в черновике
  dirty: false,
  sel: null,           // выбранный этап
  drag: null,
};

const RT_W = 176, RT_H = 70, RT_GX = 64, RT_GY = 22, RT_PAD = 24;

async function loadRoutes() {
  const kind = RT_VIEWS[ST.view] || RT.kind;
  if (kind !== RT.kind) {  // другая вкладка — свой черновик
    Object.assign(RT, { kind, data: null, mode: 'tpl', key: 'Основной', draft: null, dirty: false, sel: null });
  }
  RT.data = await api(`${API}/routes?вид=${encodeURIComponent(RT.kind)}`);
  if (!RT.dirty) rtOpen(RT.mode, RT.key, true);
}

function rtSource(mode, key) {
  const d = RT.data || {};
  if (mode === 'party') return (d.партии || []).find((p) => String(p.номер) === String(key));
  return (d.шаблоны || []).find((t) => t.имя === key);
}

function rtOpen(mode, key, quiet) {
  let src = rtSource(mode, key);
  if (!src) { mode = 'tpl'; key = 'Основной'; src = rtSource(mode, key) || (RT.data.шаблоны || [])[0]; }
  if (!src) { RT.draft = []; RT.mode = 'tpl'; RT.key = 'Основной'; RT.name = 'Основной'; return; }
  RT.mode = mode;
  RT.key = mode === 'tpl' ? src.имя : String(src.номер);
  RT.name = mode === 'tpl' ? src.имя : src.шаблон;
  RT.draft = (src.этапы || []).map((s) => ({
    код: s.код, после: [...(s.после || [])], склад_гп: !!s.склад_гп, кто: s.кто || '',
    активен: s.активен !== false,
  }));
  RT.dirty = false;
  if (!quiet) RT.sel = null;
}

function rtOp(code) {
  return ((RT.data && RT.data.операции) || []).find((o) => o.код === code);
}
function rtTitle(code) { const o = rtOp(code); return o ? o.название : code; }
function rtStart() { return (RT.data && RT.data.старт) || 'РАСКР'; }
function rtCan() { return !!(RT.data && RT.data.можно); }
function rtActive() { return (RT.draft || []).filter((s) => s.активен); }

// ---------------------------------------------------------- проверка
function rtCheck() {
  const errors = [], warns = [];
  const act = rtActive();
  const codes = act.map((s) => s.код);
  const set = new Set(codes);
  if (!act.length) errors.push('В маршруте нет ни одного этапа');
  codes.forEach((c, i) => { if (codes.indexOf(c) !== i) errors.push(`Этап ${c} указан дважды`); });
  act.forEach((s) => s.после.forEach((d) => {
    if (d === s.код) errors.push(`${s.код} не может идти после самого себя`);
    else if (!set.has(d) && d !== rtStart()) errors.push(`${s.код} ждёт этап ${d}, которого нет в маршруте`);
  }));
  const placed = new Set();
  let changed = true;
  while (changed) {
    changed = false;
    act.forEach((s) => {
      if (placed.has(s.код)) return;
      if (s.после.filter((d) => set.has(d) && d !== s.код).every((d) => placed.has(d))) { placed.add(s.код); changed = true; }
    });
  }
  const loop = codes.filter((c) => !placed.has(c));
  if (loop.length) errors.push(`Замкнутый круг: ${loop.join(' → ')} — эти этапы ждут друг друга и никогда не начнутся`);
  const finals = rtFinals();
  if (finals.length > 1 && !loop.length) warns.push(`Несколько последних этапов: ${finals.join(', ')}. Партия будет готова, когда закончатся все.`);
  const noRate = codes.filter((c) => !rtOp(c));
  if (noRate.length) warns.push(`Нет ставки в листе «расценки»: ${noRate.join(', ')} — швея получит 0 сом/шт`);
  return { errors: [...new Set(errors)], warns };
}

function rtFinals() {
  const act = rtActive();
  const used = new Set(act.flatMap((s) => s.после));
  return act.filter((s) => !used.has(s.код)).map((s) => s.код);
}

// ---------------------------------------------------------- раскладка
function rtLayout() {
  const act = rtActive();
  const set = new Set(act.map((s) => s.код));
  const level = {};
  const deps = (s) => s.после.filter((d) => set.has(d) && d !== s.код);
  const lvl = (code, seen = new Set()) => {
    if (level[code] !== undefined) return level[code];
    if (seen.has(code)) return 0; // цикл
    seen.add(code);
    const s = act.find((x) => x.код === code);
    const ds = s ? deps(s) : [];
    const v = ds.length ? 1 + Math.max(...ds.map((d) => lvl(d, seen))) : 1;
    level[code] = v;
    return v;
  };
  act.forEach((s) => lvl(s.код));
  const cols = [];
  act.forEach((s) => { (cols[level[s.код]] = cols[level[s.код]] || []).push(s.код); });
  cols[0] = [rtStart()];
  // упорядочить колонку по среднему положению предшественников — меньше пересечений
  const rowOf = { [rtStart()]: 0 };
  for (let c = 1; c < cols.length; c++) {
    const col = cols[c] || [];
    const order = act.map((s) => s.код);
    col.sort((a, b) => {
      const ma = rtBary(a, rowOf, act), mb = rtBary(b, rowOf, act);
      return ma - mb || order.indexOf(a) - order.indexOf(b);
    });
    col.forEach((code, i) => { rowOf[code] = i; });
    cols[c] = col;
  }
  const maxRows = Math.max(1, ...cols.map((c) => (c || []).length));
  const H = RT_PAD * 2 + maxRows * RT_H + (maxRows - 1) * RT_GY;
  const pos = {};
  cols.forEach((col, c) => {
    if (!col) return;
    const colH = col.length * RT_H + (col.length - 1) * RT_GY;
    const top = (H - colH) / 2;
    col.forEach((code, i) => {
      pos[code] = { x: RT_PAD + c * (RT_W + RT_GX), y: top + i * (RT_H + RT_GY) };
    });
  });
  const W = RT_PAD * 2 + cols.length * RT_W + (cols.length - 1) * RT_GX;
  return { pos, W: Math.max(W, 320), H, cols };
}

function rtBary(code, rowOf, act) {
  const s = act.find((x) => x.код === code);
  const ds = (s ? s.после : []).filter((d) => rowOf[d] !== undefined);
  if (!ds.length) return 0;
  return ds.reduce((a, d) => a + rowOf[d], 0) / ds.length;
}

// ---------------------------------------------------------- отрисовка
function routeHtml() {
  if (!RT.data) return '<div class="cx-loading"><span class="cx-spin"></span> Загружаем маршруты…</div>';
  const d = RT.data;
  const can = rtCan();
  const chk = rtCheck();
  const party = RT.mode === 'party' ? rtSource('party', RT.key) : null;
  const tpl = RT.mode === 'tpl' ? rtSource('tpl', RT.key) : null;

  const tplChips = (d.шаблоны || []).map((t) => `
    <button class="rt-chip ${RT.mode === 'tpl' && RT.key === t.имя ? 'on' : ''}" data-act="rt-open" data-mode="tpl" data-key="${esc(t.имя)}">
      ${esc(t.имя)} <span>${nf(t.этапы.filter((s) => s.активен).length)}</span>
    </button>`).join('');
  const partyOpts = (d.партии || []).map((p) => `
    <option value="${esc(p.номер)}" ${RT.mode === 'party' && RT.key === String(p.номер) ? 'selected' : ''}>
      №${esc(p.номер)} · ${esc(p.модель)} · ${esc(p.статус)}</option>`).join('');

  const subtitle = party
    ? `Партия №${esc(party.номер)} · ${esc(party.модель)} · ${esc(party.клиент)} — своя копия маршрута${party.своя ? '' : ' (пока берётся из шаблона «' + esc(party.шаблон) + '»)'}`
    : 'Шаблон: какие процессы и в каком порядке. Партия получает копию при приёмке заказа.';

  return `
    <div class="cx-hero compact">
      <div><h1>${esc(d.название || 'Маршрут')}</h1>
        <div class="cx-sub">Маршрут — цепочка ролей. Перетащите роль на другую — поменять местами, поставить после или параллельно. Стрелка = «ждёт, пока закончится».</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="rt-reload">Обновить</button></div>
    </div>

    <div class="rt-bar">
      <div class="rt-chips">${tplChips}
        ${can ? '<button class="rt-chip add" data-act="rt-new">+ Шаблон</button>' : ''}
      </div>
      ${(d.партии || []).length ? `<label class="rt-party">Партия в работе
        <select class="input" id="rt-party-sel"><option value="">— выбрать —</option>${partyOpts}</select></label>` : ''}
    </div>

    <div class="cx-card rt-card">
      <div class="cx-card-h">
        <h3>${party ? 'Партия №' + esc(party.номер) : esc(RT.name)}</h3>
        ${RT.dirty ? '<span class="cx-pill orange">не сохранено</span>' : ''}
        <span class="cx-hint">${subtitle}</span>
      </div>
      <div class="rt-tools">
        ${can ? `<button class="btn" data-act="rt-add">+ Роль</button>
        ${RT.mode === 'tpl' ? `<button class="btn ghost" data-act="rt-copy">Копировать шаблон</button>
          ${RT.key !== 'Основной' ? '<button class="btn ghost" data-act="rt-rename">Переименовать</button><button class="btn ghost danger" data-act="rt-delete">Удалить шаблон</button>' : ''}` : `
          <button class="btn ghost" data-act="rt-reset">Взять из шаблона…</button>`}
        <span class="rt-sp"></span>
        <button class="btn ghost" data-act="rt-cancel" ${RT.dirty ? '' : 'disabled'}>Отменить</button>
        <button class="btn primary" data-act="rt-save" ${RT.dirty && !chk.errors.length ? '' : 'disabled'}>Сохранить</button>` : '<span class="cx-hint">Просмотр. Менять маршрут может технолог или начальник.</span>'}
      </div>
      ${chk.errors.length || chk.warns.length ? `<div class="rt-msgs">
        ${chk.errors.map((e) => `<div class="rt-msg err">${esc(e)}</div>`).join('')}
        ${chk.warns.map((e) => `<div class="rt-msg warn">${esc(e)}</div>`).join('')}
      </div>` : ''}
      <div class="rt-body">
        <div class="rt-canvas-wrap">${rtCanvas(party)}</div>
        <div class="rt-side">${rtSide(party)}</div>
      </div>
    </div>

    ${RT.kind === 'заказ' ? rtWaitingHtml() : ''}
    ${rtRolesHtml()}
    ${tpl ? rtModelsHtml(tpl) : ''}
    ${rtTableHtml()}`;
}

function rtCanvas(party) {
  const { pos, W, H } = rtLayout();
  const act = rtActive();
  const finals = new Set(rtFinals());
  const start = rtStart();
  const edges = [];
  act.forEach((s) => {
    const deps = s.после.length ? s.после : [start];
    deps.forEach((d) => {
      const a = pos[d], b = pos[s.код];
      if (!a || !b) return;
      const x1 = a.x + RT_W, y1 = a.y + RT_H / 2, x2 = b.x, y2 = b.y + RT_H / 2;
      const mx = (x1 + x2) / 2;
      const back = x2 <= x1;
      const path = back
        ? `M${x1},${y1} C${x1 + 60},${y1 - 80} ${x2 - 60},${y2 - 80} ${x2},${y2}`
        : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
      const hot = RT.sel && (RT.sel === s.код || RT.sel === d);
      edges.push(`<path d="${path}" class="rt-edge ${back ? 'bad' : ''} ${hot ? 'hot' : ''}" marker-end="url(#rt-arrow${hot ? '-hot' : ''})"/>`);
    });
  });
  const total = party ? Number(party.раскроено || 0) : 0;
  const nodes = act.map((s) => {
    const p = pos[s.код];
    if (!p) return '';
    const op = rtOp(s.код);
    let prog = '';
    if (party && RT.kind === 'заказ') {
      const st = (party.шаги || {})[s.код] || {};
      prog = `<div class="rt-meta">${st.выполнено ? '✓ выполнено' + (st.кто ? ' · ' + esc(st.кто) : '') : 'ждёт отметки'}</div>`;
    } else if (party) {
      const done = Number((party.сдано || {})[s.код] || 0);
      const busy = Number((party.в_работе || {})[s.код] || 0);
      const pct = total ? Math.min(100, Math.round(100 * done / total)) : 0;
      prog = `<div class="rt-prog"><i style="width:${pct}%"></i></div>
        <div class="rt-meta">${nf(done)} / ${nf(total)} шт${busy ? ` · в работе ${nf(busy)}` : ''}</div>`;
    } else {
      prog = `<div class="rt-meta">${op ? nf(op.ставка) + ' сом/шт' : 'нет ставки'}${s.кто ? ' · ' + esc(s.кто) : ''}</div>`;
    }
    return `<div class="rt-node ${RT.sel === s.код ? 'sel' : ''} ${finals.has(s.код) ? 'final' : ''} ${op ? '' : 'norate'}"
        data-node="${esc(s.код)}" style="left:${p.x}px;top:${p.y}px;width:${RT_W}px;height:${RT_H}px">
      <div class="rt-name">${esc(rtTitle(s.код))}${s.склад_гп ? ' <b class="rt-tag">ГП</b>' : ''}</div>
      <div class="rt-code">${esc(s.код)}${finals.has(s.код) ? ' · финал' : ''}</div>
      ${prog}
    </div>`;
  }).join('');
  const sp = pos[start];
  const startNode = sp ? `<div class="rt-node start" style="left:${sp.x}px;top:${sp.y}px;width:${RT_W}px;height:${RT_H}px">
      <div class="rt-name">${esc(RT.data.старт_название || 'Крой')}</div><div class="rt-code">старт</div>
      ${party && RT.kind === 'шв' ? `<div class="rt-meta">раскроено ${nf(party.раскроено)} из ${nf(party.план)}</div>` : '<div class="rt-meta">отсюда всё начинается</div>'}
    </div>` : '';
  return `<div class="rt-canvas" style="width:${W}px;height:${H}px">
    <svg class="rt-svg" width="${W}" height="${H}">
      <defs>
        <marker id="rt-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="rt-ah"/></marker>
        <marker id="rt-arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="rt-ah hot"/></marker>
      </defs>
      ${edges.join('')}
    </svg>
    ${startNode}${nodes}
  </div>`;
}

function rtSide(party) {
  const can = rtCan();
  const s = (RT.draft || []).find((x) => x.код === RT.sel);
  const off = (RT.draft || []).filter((x) => !x.активен);
  const offHtml = off.length ? `<div class="rt-off"><div class="cx-hint">Выключенные этапы</div>
    ${off.map((x) => `<button class="rt-chip" data-act="rt-on" data-code="${esc(x.код)}" ${can ? '' : 'disabled'}>${esc(rtTitle(x.код))} ↺</button>`).join('')}</div>` : '';
  if (!s) {
    return `<div class="rt-help">
      <b>Как пользоваться</b>
      <ol>
        <li>Нажмите на этап — справа появятся его настройки.</li>
        <li>Перетащите этап на другой: <i>поменять местами</i>, <i>поставить после</i> или <i>параллельно</i>.</li>
        <li>«После каких этапов» — галочки. Пусто = ${esc(RT.data.пусто || 'сразу после кроя')}.</li>
        <li>Этапы в одной колонке идут одновременно.</li>
      </ol>
      ${party ? '<p class="cx-hint">Правка здесь меняет только эту партию. Шаблон и другие партии не меняются.</p>' : '<p class="cx-hint">Партии, которые уже в работе, сохранили свою копию — правка шаблона их не тронет.</p>'}
    </div>${offHtml}`;
  }
  const others = rtActive().filter((x) => x.код !== s.код);
  // отключённый этап остаётся там, где уже стоит, но новым не выбирается
  const ops = (RT.data.операции || []).filter((o) => o.код !== rtStart() && (!o.отключён || o.код === s.код));
  const dis = can ? '' : 'disabled';
  return `
    <div class="rt-form">
      <div class="cx-field"><label>Роль (операция)</label>
        <select class="input" id="rt-code" ${dis}>
          ${ops.map((o) => `<option value="${esc(o.код)}" ${o.код === s.код ? 'selected' : ''}>${esc(o.название)} (${esc(o.код)})</option>`).join('')}
          ${rtOp(s.код) ? '' : `<option value="${esc(s.код)}" selected>${esc(s.код)} — такой роли нет</option>`}
        </select>
      </div>
      <div class="cx-field"><label>После каких этапов</label>
        <div class="rt-deps">
          ${others.length ? others.map((o) => `<label class="rt-check"><input type="checkbox" data-dep="${esc(o.код)}" ${s.после.includes(o.код) ? 'checked' : ''} ${dis}> ${esc(rtTitle(o.код))}</label>`).join('') : '<span class="cx-hint">Других этапов нет</span>'}
        </div>
        <div class="cx-hint">${s.после.filter((d) => d !== rtStart()).length ? 'Начнётся, когда закончатся все отмеченные' : 'Ничего не отмечено — начнётся ' + esc(RT.data.пусто || 'сразу после кроя')}</div>
      </div>
      ${RT.kind === 'шв' ? `<label class="rt-check"><input type="checkbox" id="rt-gp" ${s.склад_гп ? 'checked' : ''} ${dis}> После этапа — на склад ГП</label>` : ''}
      ${rtPeopleForStage(s.код)}
      ${can ? `<div class="rt-actions">
        <button class="btn" data-act="rt-add-after">+ Роль после</button>
        <button class="btn" data-act="rt-add-par">+ Параллельно</button>
        <button class="btn ghost" data-act="rt-off">Выключить</button>
        <button class="btn ghost danger" data-act="rt-del">Убрать из маршрута</button>
      </div>` : ''}
      <button class="btn ghost" data-act="rt-unsel">Готово</button>
    </div>${offHtml}`;
}

// ---------------------------------------------------------- роли сотрудников
function rtPeople() { return (RT.data && RT.data.сотрудники) || []; }

function rtPeopleForStage(code) {
  const people = rtPeople();
  const can = rtCan();
  if (!people.length) return '';
  const who = people.filter((p) => p.этапы.includes(code));
  return `<div class="cx-field"><label>У кого есть эта роль</label>
    <div class="rt-deps">${people.map((p) => `<label class="rt-check">
      <input type="checkbox" data-role-login="${esc(p.логин)}" data-role-code="${esc(code)}" ${p.этапы.includes(code) ? 'checked' : ''} ${can ? '' : 'disabled'}>
      ${esc(p.ФИО)}${p.этапы.length ? '' : ' <span class="cx-hint">· ролей нет</span>'}</label>`).join('')}</div>
    <div class="cx-hint">${who.length ? `Умеют: ${nf(who.length)}. Сохраняется сразу.` : 'Пока никто. Сохраняется сразу.'}</div></div>`;
}

function rtRoleCodes() {
  const seen = new Set();
  const out = [];
  const add = (c) => { if (c && c !== rtStart() && !seen.has(c)) { seen.add(c); out.push(c); } };
  (RT.data.шаблоны || []).forEach((t) => t.этапы.forEach((s) => add(s.код)));
  rtPeople().forEach((p) => p.этапы.forEach(add));
  return out;
}

function rtRolesHtml() {
  const people = rtPeople();
  const codes = rtRoleCodes();
  const can = rtCan();
  if (!people.length || !codes.length) return '';
  const head = codes.map((c) => `<th class="rt-rc" title="${esc(c)}">${esc(rtTitle(c))}</th>`).join('');
  const rows = people.map((p) => `<tr>
    <td class="rt-rp"><b>${esc(p.ФИО)}</b><div class="cx-cell-sub">${esc(p.логин)} · ${p.этапы.length ? nf(p.этапы.length) + ' ' + rtWord(p.этапы.length) : 'ролей нет — работы нет'}</div></td>
    ${codes.map((c) => `<td class="rt-rc"><input type="checkbox" data-role-login="${esc(p.логин)}" data-role-code="${esc(c)}"
      ${p.этапы.includes(c) ? 'checked' : ''} ${can ? '' : 'disabled'} aria-label="${esc(p.ФИО)} — ${esc(rtTitle(c))}"></td>`).join('')}
  </tr>`).join('');
  return `<div class="cx-card">
    <div class="cx-card-h"><h3>Кто какие роли выполняет</h3><span class="cx-hint">производственная роль — доступ к операции: человек берёт работу только по своим ролям</span></div>
    <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px;max-height:460px">
      <table class="cx-table rt-roles"><thead><tr><th>Сотрудник</th>${head}</tr></thead><tbody>${rows}</tbody></table>
    </div></div></div>`;
}

function rtWord(n) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return 'роль';
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'роли';
  return 'ролей';
}

async function rtToggleRole(el) {
  const login = el.dataset.roleLogin, code = el.dataset.roleCode;
  try {
    const res = await api(`${API}/staff/roles`, { method: 'POST', body: JSON.stringify({ логин: login, этап: code, можно: el.checked }) });
    const p = (RT.data.сотрудники || []).find((x) => x.логин === login);
    if (p) p.этапы = res.этапы;
    render();
    toast(`${p ? p.ФИО : login}: ${el.checked ? '+' : '−'} ${rtTitle(code)}`, 'ok');
  } catch (err) { el.checked = !el.checked; toast(err.message, 'err'); }
}

// маршрут заказа: партии, у которых не все шаги отмечены — без этого крой не начнётся
function rtWaitingHtml() {
  const list = (RT.data && RT.data.ожидают) || [];
  const rows = list.map((p) => `<div class="cx-qitem">
      <div class="cx-qmain"><div class="cx-qtitle">Партия №${esc(p.номер)} <span class="cx-hint">${esc(p.модель)} · ${esc(p.клиент)}</span></div>
        <div class="rt-steps">${p.шаги.map((st) => `<span class="rt-step ${st.выполнено ? 'done' : ''}">
          ${st.выполнено ? '✓' : '○'} ${esc(st.название)}${st.выполнено && st.кто ? ` <span class="cx-hint">${esc(st.кто)}, ${esc(st.когда)}</span>` : ''}
          ${st.можно ? `<button class="btn primary ac-mini" data-act="rt-step" data-on="1" data-num="${esc(p.номер)}" data-code="${esc(st.код)}">Выполнено</button>` : ''}
          ${st.выполнено && rtCan() && !p.раскроено ? `<button class="btn ghost ac-mini" data-act="rt-step" data-on="0" data-num="${esc(p.номер)}" data-code="${esc(st.код)}">снять</button>` : ''}
          ${!st.выполнено && !st.готов ? '<span class="cx-hint">после предыдущих</span>' : ''}</span>`).join('')}</div>
      </div></div>`).join('');
  return `<div class="cx-card"><div class="cx-card-h"><h3>Ждут шагов заказа</h3><span class="cx-hint">пока шаги не отмечены, партию не кроят</span></div>
    <div class="cx-card-b">${rows || '<div class="cx-empty" style="padding:14px"><b>Все шаги выполнены</b>Партии с невыполненными шагами появятся здесь</div>'}</div></div>`;
}

function rtModelsHtml(tpl) {
  const d = RT.data;
  const can = rtCan();
  const names = (d.шаблоны || []).map((t) => t.имя);
  const rows = (d.модели || []).map((m) => `<tr>
    <td>${esc(m.модель)}</td><td>${esc(m.название)}</td><td>${esc(m.категория)}</td>
    <td><select class="input rt-bind" data-model="${esc(m.модель)}" ${can ? '' : 'disabled'}>
      ${names.map((n) => `<option ${n === m.шаблон ? 'selected' : ''}>${esc(n)}</option>`).join('')}
    </select></td></tr>`).join('');
  return `<div class="cx-card">
    <div class="cx-card-h"><h3>Какая модель по какому маршруту</h3><span class="cx-hint">на «${esc(tpl.имя)}»: ${nf(tpl.модели.length)}</span></div>
    <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px;max-height:340px">
      <table class="cx-table"><thead><tr><th>Модель</th><th>Название</th><th>Категория</th><th>Маршрут</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" class="cx-empty">Моделей нет</td></tr>'}</tbody></table>
    </div></div></div>`;
}

function rtTableHtml() {
  const rows = (RT.draft || []).map((s) => `<tr class="${s.активен ? '' : 'rt-dim'}">
    <td>${esc(s.код)}</td><td>${esc(s.после.join(';'))}</td><td>${s.склад_гп ? 1 : 0}</td><td>${esc(s.кто)}</td><td>${s.активен ? 1 : 0}</td></tr>`).join('');
  const sheet = RT.mode === 'party' ? '«Маршрут партии»' : '«Маршрут»';
  return `<details class="cx-card rt-xl"><summary class="cx-card-h"><h3>Как это лежит в Excel</h3><span class="cx-hint">лист ${sheet}</span></summary>
    <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px">
      <table class="cx-table"><thead><tr><th>этап</th><th>после каких этапов</th><th>на склад ГП</th><th>кто может</th><th>активен</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div></details>`;
}

// ---------------------------------------------------------- правки графа
function rtTouch() {
  // «после кроя» лишнее, если этап и так ждёт другие этапы
  (RT.draft || []).forEach((s) => {
    if (s.после.length > 1 && s.после.includes(rtStart())) s.после = s.после.filter((d) => d !== rtStart());
  });
  RT.dirty = true;
  render();
}
function rtFind(code) { return (RT.draft || []).find((x) => x.код === code); }
function rtFreeCode(base) {
  const used = new Set((RT.draft || []).map((s) => s.код));
  const free = (RT.data.операции || []).find((o) => !used.has(o.код) && o.код !== rtStart() && !o.отключён);
  if (free && !base) return free.код;
  let i = 1, c = base || 'ЭТАП';
  while (used.has(c)) c = `${base || 'ЭТАП'}${++i}`;
  return c;
}

// убрать этап из цепочки: его последователи наследуют его предшественников
function rtDetach(code) {
  const s = rtFind(code);
  (RT.draft || []).forEach((x) => {
    if (x.код === code || !x.после.includes(code)) return;
    const next = x.после.filter((d) => d !== code);
    s.после.forEach((d) => { if (!next.includes(d) && d !== x.код) next.push(d); });
    x.после = next;
  });
  s.после = [];
}

// поставить code сразу после target: кто ждал target — теперь ждёт code
function rtInsertAfter(code, target) {
  rtDetach(code);
  (RT.draft || []).forEach((x) => {
    if (x.код !== code && x.активен && x.после.includes(target)) {
      x.после = x.после.map((d) => (d === target ? code : d));
    }
  });
  rtFind(code).после = target === rtStart() ? [] : [target];
}

// параллельно с target: те же предшественники, и последователи ждут обоих
function rtParallel(code, target) {
  rtDetach(code);
  const t = rtFind(target);
  rtFind(code).после = [...t.после];
  (RT.draft || []).forEach((x) => {
    if (x.код !== code && x.после.includes(target) && !x.после.includes(code)) x.после.push(code);
  });
}

// поменять местами: структура остаётся, меняются процессы в клетках
function rtSwap(a, b) {
  const sa = rtFind(a), sb = rtFind(b);
  const swap = (d) => (d === a ? b : d === b ? a : d);
  (RT.draft || []).forEach((x) => { x.после = x.после.map(swap); });
  const pa = sa.после; sa.после = sb.после; sb.после = pa;
  [sa.склад_гп, sb.склад_гп] = [sb.склад_гп, sa.склад_гп];
  sa.после = sa.после.filter((d) => d !== a);
  sb.после = sb.после.filter((d) => d !== b);
}

function rtRename(oldCode, newCode) {
  (RT.draft || []).forEach((x) => {
    if (x.код === oldCode) x.код = newCode;
    x.после = x.после.map((d) => (d === oldCode ? newCode : d));
  });
  RT.sel = newCode;
}

function rtAdd(after, parallel) {
  const code = rtFreeCode();
  const item = { код: code, после: [], склад_гп: false, кто: '', активен: true };
  RT.draft.push(item);
  if (parallel && after) rtParallel(code, after);
  else if (after) rtInsertAfter(code, after);
  else {
    const fin = rtFinals().filter((c) => c !== code);
    item.после = fin;
  }
  RT.sel = code;
  rtTouch();
}

// ---------------------------------------------------------- сервер
async function rtSave() {
  const chk = rtCheck();
  if (chk.errors.length) { toast(chk.errors[0], 'err'); return; }
  const body = {
    этапы: RT.draft.map((s) => ({ код: s.код, после: s.после, склад_гп: s.склад_гп, кто: s.кто, активен: s.активен })),
  };
  body.вид = RT.kind;
  if (RT.mode === 'party') { body.партия = RT.key; body.шаблон = RT.name; }
  else { body.шаблон = RT.name; body.старое_имя = RT.key; }
  try {
    const res = await api(`${API}/routes/save`, { method: 'POST', body: JSON.stringify(body) });
    RT.dirty = false;
    if (RT.mode === 'tpl') RT.key = res.шаблон;
    await loadRoutes();
    render();
    const w = res.предупреждения || [];
    toast(w.length ? 'Сохранено. ' + w[0] : 'Маршрут сохранён в Excel', w.length ? '' : 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

function rtConfirmLeave() {
  return !RT.dirty || confirm('Изменения в маршруте не сохранены. Выбросить их?');
}

function rtDropMenu(code, target, x, y) {
  rtCloseMenu();
  const t = target === rtStart();
  const menu = document.createElement('div');
  menu.className = 'rt-menu';
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.innerHTML = `
    <div class="rt-menu-h">«${esc(rtTitle(code))}» → «${esc(t ? 'Крой' : rtTitle(target))}»</div>
    ${t ? '' : `<button data-rt-drop="swap">Поменять местами</button>`}
    <button data-rt-drop="after">Поставить после</button>
    ${t ? '' : `<button data-rt-drop="par">Поставить параллельно</button>`}
    <button data-rt-drop="x" class="muted">Отмена</button>`;
  document.body.appendChild(menu);
  menu.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-rt-drop]');
    if (!b) return;
    const kind = b.dataset.rtDrop;
    rtCloseMenu();
    if (kind === 'swap') rtSwap(code, target);
    if (kind === 'after') rtInsertAfter(code, target);
    if (kind === 'par') rtParallel(code, target);
    if (kind !== 'x') { RT.sel = code; rtTouch(); }
  });
}
function rtCloseMenu() { document.querySelectorAll('.rt-menu').forEach((m) => m.remove()); }

// ---------------------------------------------------------- события
document.addEventListener('click', async (ev) => {
  if (RT.drag && RT.drag.moved) return; // клик сразу после перетаскивания — не считаем
  if (!ev.target.closest('.rt-menu')) rtCloseMenu();
  const el = ev.target.closest('[data-act^="rt-"]');
  const node = ev.target.closest('.rt-node[data-node]');
  if (!el && node && rtIsView()) {
    RT.sel = node.dataset.node; render(); return;
  }
  if (!el) return;
  const act = el.dataset.act;
  const can = rtCan();
  if (act === 'rt-open') {
    if (!rtConfirmLeave()) return;
    rtOpen(el.dataset.mode, el.dataset.key); render(); return;
  }
  if (act === 'rt-step') {
    const on = el.dataset.on === '1';
    if (!on && !confirm('Снять отметку о выполнении шага?')) return;
    try {
      await api(`${API}/routes/step`, { method: 'POST', body: JSON.stringify({ партия: el.dataset.num, шаг: el.dataset.code, выполнено: on }) });
      await loadRoutes(); render(); toast(on ? 'Шаг отмечен выполненным' : 'Отметка снята', 'ok');
    } catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (act === 'rt-reload') {
    if (!rtConfirmLeave()) return;
    RT.dirty = false;
    try { await loadRoutes(); render(); toast('Обновлено из Excel', 'ok'); } catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (!can) return;
  if (act === 'rt-add') { rtAdd(RT.sel, false); return; }
  if (act === 'rt-add-after') { rtAdd(RT.sel, false); return; }
  if (act === 'rt-add-par') { rtAdd(RT.sel, true); return; }
  if (act === 'rt-unsel') { RT.sel = null; render(); return; }
  if (act === 'rt-del') {
    rtDetach(RT.sel);
    RT.draft = RT.draft.filter((x) => x.код !== RT.sel);
    RT.sel = null; rtTouch(); return;
  }
  if (act === 'rt-off') {
    rtDetach(RT.sel);
    rtFind(RT.sel).активен = false;
    RT.sel = null; rtTouch(); return;
  }
  if (act === 'rt-on') {
    const s = rtFind(el.dataset.code);
    s.активен = true;
    s.после = rtFinals().filter((c) => c !== s.код);
    RT.sel = s.код; rtTouch(); return;
  }
  if (act === 'rt-cancel') { rtOpen(RT.mode, RT.key); render(); return; }
  if (act === 'rt-save') { await rtSave(); return; }
  if (act === 'rt-new' || act === 'rt-copy') {
    if (!rtConfirmLeave()) return;
    const name = (prompt(act === 'rt-new' ? 'Название нового шаблона (например, «Худи»):' : 'Название копии:', '') || '').trim();
    if (!name) return;
    if ((RT.data.шаблоны || []).some((t) => t.имя === name)) { toast('Такой шаблон уже есть', 'err'); return; }
    if (act === 'rt-new') {
      RT.draft = [{ код: rtFreeCode(), после: [], склад_гп: false, кто: '', активен: true }];
    }
    RT.mode = 'tpl'; RT.key = name; RT.name = name; RT.sel = null;
    RT.dirty = false;
    await rtSave();
    return;
  }
  if (act === 'rt-rename') {
    const name = (prompt('Новое название шаблона:', RT.name) || '').trim();
    if (!name || name === RT.name) return;
    RT.name = name; RT.dirty = true;
    await rtSave();
    return;
  }
  if (act === 'rt-delete') {
    if (!confirm(`Удалить шаблон «${RT.key}»? Модели вернутся на «Основной». Партии в работе сохранят свою копию.`)) return;
    try {
      await api(`${API}/routes/delete`, { method: 'POST', body: JSON.stringify({ шаблон: RT.key, вид: RT.kind }) });
      RT.dirty = false; RT.mode = 'tpl'; RT.key = 'Основной';
      await loadRoutes(); render(); toast('Шаблон удалён', 'ok');
    } catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (act === 'rt-reset') {
    const names = (RT.data.шаблоны || []).map((t) => t.имя);
    const name = (prompt(`Скопировать в партию маршрут из шаблона:\n${names.join(', ')}`, RT.name) || '').trim();
    const t = rtSource('tpl', name);
    if (!t) { if (name) toast('Нет такого шаблона', 'err'); return; }
    RT.draft = t.этапы.filter((s) => s.активен).map((s) => ({ код: s.код, после: [...s.после], склад_гп: s.склад_гп, кто: s.кто, активен: true }));
    RT.name = t.имя; RT.sel = null; rtTouch();
  }
});

document.addEventListener('change', async (ev) => {
  if (!rtIsView()) return;
  const t = ev.target;
  if (t.id === 'rt-party-sel') {
    if (!t.value) return;
    if (!rtConfirmLeave()) { render(); return; }
    rtOpen('party', t.value); render(); return;
  }
  if (t.dataset.roleLogin) { await rtToggleRole(t); return; }
  if (t.classList.contains('rt-bind')) {
    try {
      await api(`${API}/routes/bind`, { method: 'POST', body: JSON.stringify({ модель: t.dataset.model, шаблон: t.value, вид: RT.kind }) });
      const keep = RT.dirty ? RT.draft : null;
      RT.data = await api(`${API}/routes?вид=${encodeURIComponent(RT.kind)}`);
      if (keep) RT.draft = keep;
      render();
      toast(`Модель ${t.dataset.model} → «${t.value}»`, 'ok');
    } catch (err) { toast(err.message, 'err'); }
    return;
  }
  const s = rtFind(RT.sel);
  if (!s) return;
  if (t.id === 'rt-code') {
    let code = t.value;
    if (code !== s.код && rtFind(code)) { toast(`Этап ${code} уже есть в маршруте`, 'err'); render(); return; }
    rtRename(s.код, code); rtTouch(); return;
  }
  if (t.dataset.dep) {
    const d = t.dataset.dep;
    s.после = t.checked ? [...s.после, d] : s.после.filter((x) => x !== d);
    rtTouch(); return;
  }
  if (t.id === 'rt-gp') { s.склад_гп = t.checked; rtTouch(); return; }
  if (t.id === 'rt-who') { s.кто = t.value.trim(); rtTouch(); }
});

// перетаскивание этапов (мышь и палец)
document.addEventListener('pointerdown', (ev) => {
  if (!rtIsView() || !rtCan() || ev.button > 0) return;
  const node = ev.target.closest('.rt-node[data-node]');
  if (!node) return;
  RT.drag = { code: node.dataset.node, x: ev.clientX, y: ev.clientY, moved: false, ghost: null, node };
});
document.addEventListener('pointermove', (ev) => {
  const d = RT.drag;
  if (!d) return;
  if (!d.moved && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < 6) return;
  if (!d.moved) {
    d.moved = true;
    d.ghost = d.node.cloneNode(true);
    d.ghost.classList.add('rt-ghost');
    d.ghost.style.left = '0'; d.ghost.style.top = '0';
    document.body.appendChild(d.ghost);
    d.node.classList.add('rt-dragging');
  }
  ev.preventDefault();
  d.ghost.style.transform = `translate(${ev.clientX - RT_W / 2}px, ${ev.clientY - RT_H / 2}px)`;
  document.querySelectorAll('.rt-node.over').forEach((n) => n.classList.remove('over'));
  d.ghost.style.display = 'none';
  const under = document.elementFromPoint(ev.clientX, ev.clientY);
  d.ghost.style.display = '';
  const target = under && under.closest('.rt-node');
  if (target && target !== d.node) target.classList.add('over');
});
document.addEventListener('pointerup', (ev) => {
  const d = RT.drag;
  if (!d) return;
  if (d.ghost) d.ghost.remove();
  d.node.classList.remove('rt-dragging');
  document.querySelectorAll('.rt-node.over').forEach((n) => n.classList.remove('over'));
  if (d.moved) {
    const under = document.elementFromPoint(ev.clientX, ev.clientY);
    const target = under && under.closest('.rt-node');
    if (target && target !== d.node) {
      const code = target.dataset.node || rtStart();
      rtDropMenu(d.code, code, Math.min(ev.clientX, innerWidth - 240), Math.min(ev.clientY, innerHeight - 200));
    }
  }
  setTimeout(() => { RT.drag = null; }, 0);
});

window.addEventListener('beforeunload', (ev) => {
  if (RT.dirty) { ev.preventDefault(); ev.returnValue = ''; }
});
