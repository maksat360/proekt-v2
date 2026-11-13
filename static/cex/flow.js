'use strict';

/* Модуль «Цех» · поток заказа: конструктор (карты: размеры, рулоны) → снабженец (сырьё) → закройщик. */

const FL = { design: { очередь: [], история: {} }, supply: { очередь: [], спецификации: {}, рулоны: [], статусы: [] },
  num: '', rows: [], models: {}, chars: {}, on: new Set(), bomModel: '', bomRows: [], supplyTab: 'orders', nomTab: 'goods', prod: null,
  nomSel: '', nomQ: '', mvFilter: '', mv: null, cps: null, cp: null, cpCat: '', cpQ: '' };

async function loadDesign() { FL.design = await api(`${API}/design`); }
async function loadSupply() {
  FL.supply = await api(`${API}/supply`);
  if (ST.view === 'nom') await loadCps();
}
async function loadCps() {
  try { FL.cps = await api(`${API}/nom/counterparties`); } catch (err) { FL.cps = { категории: [], контрагенты: [], ошибка: err.message }; }
}

function flHistoryHtml(list) {
  if (!list || !list.length) return '<div class="cx-hint">Изменений пока нет</div>';
  return `<div class="cx-scroll"><table class="cx-table">
    <thead><tr><th>Когда</th><th>Кто</th><th>Позиция</th><th class="num">Было</th><th class="num">Стало</th><th>Комментарий</th></tr></thead>
    <tbody>${list.slice().reverse().map((h) => `<tr><td>${esc(h.дата)}</td><td>${esc(h.кто)}</td>
      <td>${h.модель ? `${h.карта ? `карта ${esc(h.карта)} · ` : ''}${esc(h.модель)} · ${esc(h.цвет)} · ${esc(h.размер)}` : '<b>Все карты</b>'}</td>
      <td class="num">${esc(h.было)}</td><td class="num">${esc(h.стало)}</td><td>${esc(h.комментарий)}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

// у снабженца в очереди не заказ, а карта заказа
const flQKey = (o) => (o.карта_номер ? `${o.номер}|${o.карта_номер}` : o.номер);

function flQueue(list, act, empty) {
  if (!list.length) return `<div class="cx-card"><div class="cx-empty"><b>Очередь пуста</b>${empty}</div></div>`;
  return `<div class="cx-queue">${list.map((o) => `
    <div class="cx-qitem ${FL.num === flQKey(o) ? 'on' : ''}" data-act="${act}" data-num="${esc(flQKey(o))}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Заказ №${esc(o.номер)}${o.карта_номер ? ` · карта ${esc(o.карта_номер)}` : ''} ${o.карта_номер ? '' : statusPill(o.статус)}</div>
        <div class="cx-hint">${esc(o.клиент)} · ${o.карта_номер ? `${nf(o.штук)} шт по карте` : `${nf(o.позиций)} поз. · заказано ${nf(o.заказано)} шт`} · срок ${esc(o.срок || '—')}</div>
      </div>
      <div class="cx-qright"><button class="btn primary" data-act="${act}" data-num="${esc(flQKey(o))}">Открыть</button></div>
    </div>`).join('')}</div>`;
}

// ------------------------------------------------------------ конструктор
function designHtml() {
  const q = FL.design.очередь || [];
  const o = q.find((x) => x.номер === FL.num);
  return `<div class="cx-hero compact"><div><h1>Конструктор</h1>
      <div class="cx-sub">Производственные карты: модель, цвет, размеры, итоговое количество и характеристики. Готовые карты уходят снабженцу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    ${flQueue(q, 'fl-design-open', 'Новые заказы на пошив появятся здесь')}
    ${o ? designCardHtml(o) : ''}`;
}

const flKey = (m, c, z) => `${(m || '').trim()}|${(c || '').trim()}|${String(z || '').trim()}`;
// FL.rows — строки карт {карта, модель, цвет, размер, итог}; FL.models — модели в каждой карте;
// FL.chars — доп. характеристики модели в карте.
const flCards = () => Object.keys(FL.models).sort((a, b) => a - b);
const flQty = (card) => FL.rows.filter((r) => card == null || r.карта === card).reduce((s, r) => s + num(r.итог), 0);
const flOrder = () => (FL.design.очередь || []).find((x) => x.номер === FL.num);
const flBoss = (o) => o.в_заказе || o.позиции || [];  // заказ начальника — только подсказка
// карта уже передана дальше — у конструктора она только для просмотра
const flStage = (card) => ((flOrder() || {}).карты || {})[card] || 'у конструктора';
const flLocked = (card) => flStage(card) !== 'у конструктора';
const flMine = () => flCards().filter((c) => !flLocked(c));

// FL.on — включённые клетки «карта|модель|цвет|размер»: какие размеры кроятся по этой карте.
const flOnKey = (card, m, c, z) => `${card}|${m}|${c}|${z}`;
const flPlan = (o, m, c, z) => flBoss(o).filter((p) => flKey(p.модель, p.цвет, p.размер) === flKey(m, c, z))
  .reduce((t, p) => t + num(p.количество), 0);

// цвета и размеры модели: каталог «главный» + всё, что есть в заказе и в картах
function flSizesOf(o, model) {
  const v = (ST.refs.варианты || {})[model] || { цвета: [], размеры: [] };
  const own = (modelInfo(model) || {}).размеры || [];
  const colors = new Set(v.цвета);
  const sizes = new Set((own.length ? own : v.размеры).map(String));
  flBoss(o).filter((p) => p.модель === model).forEach((p) => { colors.add(p.цвет); sizes.add(String(p.размер)); });
  FL.on.forEach((k) => { const [, m, c, z] = k.split('|'); if (m === model) { colors.add(c); sizes.add(z); } });
  return { colors: [...colors].filter(Boolean),
    sizes: [...sizes].filter(Boolean).sort((x, y) => x.localeCompare(y, 'ru', { numeric: true })) };
}

function flModelHtml(o, card, model) {
  const { colors, sizes } = flSizesOf(o, model);
  const id = `${card}|${model}`;
  const on = (c, z) => FL.on.has(flOnKey(card, model, c, z));
  return `<div class="cc-sec" style="margin-top:10px">
    <div class="cc-sec-h"><b>${esc(model)}</b> <span class="cx-hint">${esc((modelInfo(model) || {}).категория || 'нет в каталоге')}</span></div>
    <div class="cx-gtools" style="padding-left:0">
      <input class="input" data-fl-chars="${esc(id)}" value="${esc(FL.chars[id] || '')}" placeholder="доп. характеристики: длина, посадка, детали кроя…" style="max-width:360px">
      <span class="cx-hint">Нажмите размер, чтобы включить или выключить. Серым — сколько примерно в заказе.</span>
    </div>
    <div class="cx-gwrap"><table class="cx-gtable fl-sztable">
      <thead><tr><th class="cx-gcolor">Цвет / размер</th>${sizes.map((z) => `<th>${esc(z)}</th>`).join('')}</tr></thead>
      <tbody>${colors.map((c) => `<tr><th class="cx-gcolor"><button type="button" class="fl-szrow" data-act="fl-szrow" data-card="${esc(card)}" data-model="${esc(model)}" data-color="${esc(c)}" title="Включить или выключить все размеры цвета">${esc(c)}</button></th>
        ${sizes.map((z) => { const q = flPlan(o, model, c, z); const v = on(c, z);
          return `<td><button type="button" class="fl-sz ${v ? 'on' : ''}" data-act="fl-sz" data-k="${esc(flOnKey(card, model, c, z))}"
            aria-pressed="${v}" aria-label="${esc(c)}, размер ${esc(z)}">${v ? '✓' : ''}${q ? `<i>${nf(q)}</i>` : ''}</button></td>`; }).join('')}</tr>`).join('')}</tbody>
    </table></div></div>`;
}

// рулоны карты: вид из номенклатуры (категория «рулоны») + цвет, сколько угодно строк
const flRollList = (list) => (list || []).length
  ? `<div class="cx-hint" style="margin-top:6px">Рулоны: ${list.map((r) => `<b>${esc(r.вид)}</b>${r.цвет ? ' · ' + esc(r.цвет) : ''} · ${nf(r.шт || 1)} шт`).join('; ')}</div>` : '';
// цвета карты: включённые в ней размеры; пока ничего не включено — все цвета её моделей
function flCardColors(c) {
  const on = [...new Set(flOnOf(c).map(([, , col]) => col))];
  if (on.length) return on;
  const o = flOrder();
  return [...new Set((FL.models[c] || []).flatMap((m) => flSizesOf(o, m).colors))];
}

function flRollsHtml(c) {
  const kinds = FL.design.виды_рулонов || [];
  const stock = FL.design.рулоны_склад || [];
  const colors = flCardColors(c);
  const low = (x) => String(x || '').toLowerCase();
  const kindOptions = (r) => {  // сначала рулоны, которые есть на складе в этом цвете
    const have = stock.filter((x) => r.цвет && low(x.цвет) === low(r.цвет));
    const haveKinds = have.map((x) => x.вид);
    const rest = [...new Set([...kinds, r.вид].filter((k) => k && !haveKinds.includes(k)))];
    const opt = (k, label) => `<option value="${esc(k)}" ${k === r.вид ? 'selected' : ''}>${esc(label)}</option>`;
    return (have.length ? `<optgroup label="Есть на складе в цвете «${esc(r.цвет)}»">${have.map((x) => opt(x.вид, `${x.вид} · ${nf(x.шт)} шт${x.вдм ? ' (ВДМ)' : ''}`)).join('')}</optgroup>` : '')
      + (rest.length ? `<optgroup label="${r.цвет ? 'Нет на складе в этом цвете' : 'Сначала выберите цвет'}">${rest.map((k) => opt(k, k)).join('')}</optgroup>` : '');
  };
  const rows = FL.rolls.map((r, i) => (r.карта !== c ? '' : `<div class="cx-btn-row" style="margin-top:6px">
      <select class="input" data-fl-roll="${i}|цвет" style="max-width:200px" aria-label="Цвет рулона"><option value="">цвет…</option>
        ${[...new Set([...colors, r.цвет].filter(Boolean))].map((x) => `<option ${x === r.цвет ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
      <select class="input" data-fl-roll="${i}|вид" style="max-width:260px" aria-label="Вид рулона"><option value="">вид рулона…</option>${kindOptions(r)}</select>
      <input class="input cx-mini" type="number" min="1" step="1" data-fl-roll="${i}|шт" value="${esc(r.шт || 1)}" aria-label="Сколько рулонов" title="Сколько рулонов"> <span class="cx-hint">шт</span>
      <button class="btn ghost" data-act="fl-roll-row-del" data-i="${i}" aria-label="Убрать рулон">✕</button></div>`)).join('');
  return `<div style="margin-top:12px"><b>Рулоны</b> <span class="cx-hint">${kinds.length ? 'цвет, затем вид — сверху те, что есть на складе в этом цвете; количество строк не ограничено' : 'в номенклатуре нет группы «рулоны» — добавьте её в снабжении'}</span>
    ${rows}
    <div class="cx-btn-row" style="margin-top:6px"><button class="btn" data-act="fl-roll-row-add" data-card="${esc(c)}">+ Рулон</button></div></div>`;
}

const flOnOf = (card) => [...FL.on].filter((k) => k.startsWith(card + '|')).map((k) => k.split('|'));
function flCardSummary(card) {  // «чёрный: 44, 46, 48 · серый: 44, 46»
  const by = {};
  flOnOf(card).forEach(([, m, c, z]) => { (by[`${m} ${c}`] = by[`${m} ${c}`] || []).push(z); });
  return Object.entries(by).map(([k, zs]) => `${esc(k)}: ${zs.sort((x, y) => x.localeCompare(y, 'ru', { numeric: true })).map(esc).join(', ')}`).join(' · ');
}

function designCardHtml(o) {
  const lockedHtml = (c) => `<div class="cx-card" style="margin-top:12px"><div class="cx-card-h"><h3>Карта ${esc(c)} ${statusPill(flStage(c))}</h3>
      <span class="cx-hint">передана, менять нельзя</span></div>
    <div class="cx-card-b"><div class="cx-hint">${flCardSummary(c) || 'размеров нет'}</div>
      ${flRollList(FL.rolls.filter((r) => r.карта === c))}</div></div>`;
  const cards = flCards().map((c) => flLocked(c) ? lockedHtml(c) : `<div class="cx-card" style="margin-top:12px"><div class="cx-card-h"><h3>Карта ${esc(c)}</h3>
      <span class="cx-hint">${nf(flOnOf(c).length)} размеров включено</span>
      ${flMine().length > 1 ? `<button class="btn ghost" data-act="fl-card-del" data-card="${esc(c)}" style="margin-left:auto">Удалить карту</button>` : ''}</div>
    <div class="cx-card-b">
      ${(FL.models[c] || []).map((m) => flModelHtml(o, c, m)).join('') || '<div class="cx-hint">В заказе нет моделей</div>'}
      ${flRollsHtml(c)}
      <div class="cx-btn-row" style="margin-top:10px">
        <button class="btn primary" data-act="fl-card-send" data-card="${esc(c)}" style="margin-left:auto">Передать карту ${esc(c)} снабженцу</button>
      </div>
    </div></div>`).join('');
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · технологические карты</h3>
      <span class="cx-hint">в заказе примерно ${nf(o.заказано)} шт · карт ${nf(flCards().length)}</span></div>
    <div class="cx-card-b">
      ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
      ${flCards().length > 1 ? `<div class="cx-hint">Карты: ${flCards().map((c) => `<b>№${esc(c)}</b> ${flLocked(c) ? '(передана)' : ''}`).join(' · ')}</div>` : ''}
      ${cards}
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn" data-act="fl-card-new">+ Создать новую карту</button></div>
      <div class="cx-field" style="margin-top:12px"><label>Комментарий к изменению</label>
        <input class="input" id="fl-note" placeholder="Например: рулоны подобраны по тону"></div>
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-design-save">Сохранить черновик</button>
        <button class="btn primary" data-act="fl-design-done">${flMine().length > 1 ? 'Передать все карты снабженцу' : 'Утвердить и передать снабженцу'}</button>
      </div>
      <div class="cx-hint" style="margin-top:8px">Конструктор включает в каждой карте нужные размеры и закрепляет рулоны. Количество в заказе примерное — точное вводит закройщик и только по включённым размерам этой карты.</div>
      <h4 style="margin:18px 0 8px">История изменений</h4>
      ${flHistoryHtml((FL.design.история || {})[o.номер])}
    </div></div>`;
}

function flOpenDesign(numStr) {
  const o = (FL.design.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  const draft = !o.карта_сохранена;  // ещё не сохраняли — карта 1 со всеми размерами из заказа
  const rows = draft ? flBoss(o).map((p) => ({ ...p, карта: '1' })) : (o.карта || []);
  FL.on = new Set(rows.map((r) => flOnKey(String(r.карта || '1'), r.модель, r.цвет, String(r.размер))));
  FL.rows = rows.map((r) => ({ карта: String(r.карта || '1'), модель: r.модель, цвет: r.цвет, размер: String(r.размер), итог: num(r.итог) }));
  FL.models = {}; FL.chars = {};
  FL.rolls = (o.рулоны || []).map((r) => ({ карта: String(r.карта), вид: r.вид, цвет: r.цвет, шт: r.шт || 1 }));
  const all = [...new Set(flBoss(o).map((p) => p.модель))];
  rows.forEach((r) => {
    const c = String(r.карта || '1');
    FL.models[c] = FL.models[c] || [];
    if (!FL.models[c].includes(r.модель)) FL.models[c].push(r.модель);
    if (r.характеристики) FL.chars[`${c}|${r.модель}`] = r.характеристики;
  });
  if (!flCards().length) FL.models['1'] = all;
  render();
}

// done — передать все свои карты; card — передать только эту карту
async function flSaveDesign(done, card) {
  const o = flOrder();
  // примерное количество из заказа делим между картами, где размер включён; точное впишет закройщик
  const lockedQty = {};
  FL.rows.filter((r) => flLocked(r.карта)).forEach((r) => { const k = flKey(r.модель, r.цвет, r.размер); lockedQty[k] = (lockedQty[k] || 0) + num(r.итог); });
  const byKey = {};
  [...FL.on].map((k) => k.split('|')).filter(([c]) => !flLocked(c)).forEach(([c, m, col, z]) => {
    (byKey[flKey(m, col, z)] = byKey[flKey(m, col, z)] || []).push({ карта: c, модель: m, цвет: col, размер: z });
  });
  const rows = [];
  Object.entries(byKey).forEach(([k, list]) => {
    const [m, col, z] = k.split('|');
    const left = Math.max(0, flPlan(o, m, col, z) - (lockedQty[k] || 0));
    list.sort((x, y) => num(x.карта) - num(y.карта)).forEach((r, i) => {
      rows.push({ ...r, итог: Math.floor(left / list.length) + (i < left % list.length ? 1 : 0),
        характеристики: FL.chars[`${r.карта}|${r.модель}`] || '' });
    });
  });
  if (!rows.length) return toast('Включите хотя бы один размер в карте', 'err');
  const body = { номер: FL.num, готово: done, передать: card ? [card] : [], комментарий: ($('#fl-note') || {}).value || '', позиции: rows,
    рулоны: FL.rolls.filter((r) => r.вид && !flLocked(r.карта)).map((r) => ({ ...r, шт: Math.max(1, Math.round(num(r.шт)) || 1) })) };
  if (done && !confirm('Передать снабженцу все карты? После этого их не поменять.')) return;
  if (card && !confirm(`Передать карту ${card} снабженцу? После этого её не поменять.`)) return;
  try {
    const res = await api(`${API}/design`, { method: 'POST', body: JSON.stringify(body) });
    await loadDesign();
    await refreshOrders();
    if ((FL.design.очередь || []).some((x) => x.номер === FL.num)) flOpenDesign(FL.num);
    else FL.num = '';
    render();
    toast(res.передано.length ? `Снабженцу передано: карта ${res.передано.join(', ')}` : 'Черновик сохранён', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// ------------------------------------------------------------- снабжение
function supplyHtml() {
  const t = FL.supplyTab;
  const sub = [['orders', `Карты ${nf((FL.supply.очередь || []).length)}`], ['moves', 'Склад сырья'], ['rolls', 'Рулоны']];
  return `<div class="cx-hero compact"><div><h1>Снабжение</h1>
      <div class="cx-sub">Склад сырья — остатки, приход и расход; рулоны. Товары, сырьё и спецификации — в разделе «Номенклатура». Когда сырьё по карте готово — карта уходит закройщику</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'moves' ? movesHtml() : t === 'rolls' ? rollsHtml() : supplyOrdersHtml()}`;
}

// ------------------------------------------------------------- номенклатура
function nomHtml() {
  const t = FL.nomTab;
  const sub = [['goods', `Товары ${nf((ST.refs.модели || []).length)}`], ['mats', 'Сырьё'], ['bom', 'Спецификации'],
    ['cps', `Контрагенты ${nf(((FL.cps || {}).контрагенты || []).length)}`]];
  return `<div class="cx-hero compact"><div><h1>Номенклатура</h1>
      <div class="cx-sub">Товары — модели готовой продукции и их размеры; сырьё — группы и позиции материалов; спецификации — расход сырья на артикул; контрагенты — поставщики, покупатели и свои компании и цеха</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'bom' ? bomHtml() : t === 'mats' ? materialsHtml() : t === 'cps' ? cpsHtml() : goodsHtml()}`;
}

// ------------------------------------------------------------- контрагенты
const flNewCp = (cat) => ({ id: '', название: '', категория: cat || 'Поставщики', телефон: '', комментарий: '' });
const flCpMatch = (c, q) => !q || `${c.название} ${c.телефон} ${c.комментарий}`.toLowerCase().includes(q);

function cpsHtml() {
  const data = FL.cps || { категории: [], контрагенты: [] };
  const all = data.контрагенты || [];
  const cats = [...new Set([...(data.категории || []), ...all.map((c) => c.категория)])];
  const p = FL.cp || (FL.cp = flNewCp(FL.cpCat));
  const q = FL.cpQ.trim().toLowerCase();
  const list = all.filter((c) => !FL.cpCat || c.категория === FL.cpCat);
  const groups = cats.filter((c) => !FL.cpCat || c === FL.cpCat)
    .map((cat) => [cat, list.filter((c) => c.категория === cat)]).filter(([, l]) => l.length);
  const count = (cat) => all.filter((c) => !cat || c.категория === cat).length;
  return `<datalist id="fl-cpcats">${cats.map((c) => `<option value="${esc(c)}">`).join('')}</datalist>
  ${data.ошибка ? `<div class="cx-notice warn">Справочник недоступен: ${esc(data.ошибка)}</div>` : ''}
  <div class="cx-grid">
    <div class="cx-card"><div class="cx-card-h"><h3>Контрагенты</h3><span class="cx-hint">${nf(all.length)} записей</span></div>
      <div class="cx-card-b">
        <div class="cx-seg" style="margin-bottom:10px">${[['', 'Все'], ...cats.map((c) => [c, c])].map(([v, l]) =>
          `<button class="${FL.cpCat === v ? 'on' : ''}" data-act="fl-cp-cat" data-cat="${esc(v)}">${esc(l)} ${nf(count(v))}</button>`).join('')}</div>
        <input class="input" id="fl-cpq" placeholder="Поиск: название, телефон, комментарий" value="${esc(FL.cpQ)}" style="margin-bottom:10px">
        ${groups.length ? `<div class="cx-scroll"><table class="cx-table">
          <thead><tr><th>Название</th><th>Телефон</th><th>Комментарий</th></tr></thead>
          ${groups.map(([cat, l]) => `<tbody><tr class="fl-cpgroup"><td colspan="3"><b>${esc(cat)}</b> <span class="cx-hint">${nf(l.length)}</span></td></tr>
            ${l.map((c) => `<tr class="fl-nomrow fl-cprow ${p.id === c.id ? 'on' : ''}" data-act="fl-cp-pick" data-id="${esc(c.id)}"
                data-q="${esc(`${c.название} ${c.телефон} ${c.комментарий}`.toLowerCase())}" style="cursor:pointer${flCpMatch(c, q) ? '' : ';display:none'}">
              <td><b>${esc(c.название)}</b></td><td>${esc(c.телефон)}</td><td class="cx-hint">${esc(c.комментарий)}</td></tr>`).join('')}</tbody>`).join('')}
        </table></div>` : '<div class="cx-hint">Пока никого нет — добавьте справа</div>'}
      </div></div>
    <div class="cx-side"><div class="cx-card"><div class="cx-card-h"><h3>${p.id ? esc(p.название) : 'Новый контрагент'}</h3>
        ${p.id ? '<button class="btn ghost" data-act="fl-cp-new">+ Новый</button>' : ''}</div>
      <div class="cx-card-b">
        <div class="cx-formgrid" style="grid-template-columns:1fr">
          <div class="cx-field"><label>Название</label><input class="input" data-fl-cp="название" value="${esc(p.название)}" placeholder="напр. Санжар ака"></div>
          <div class="cx-field"><label>Категория</label><input class="input" list="fl-cpcats" data-fl-cp="категория" value="${esc(p.категория)}" placeholder="выберите или впишите новую"></div>
          <div class="cx-field"><label>Телефон</label><input class="input" data-fl-cp="телефон" value="${esc(p.телефон)}" inputmode="tel"></div>
          <div class="cx-field"><label>Комментарий</label><input class="input" data-fl-cp="комментарий" value="${esc(p.комментарий)}"></div>
        </div>
        <div class="cx-btn-row" style="margin-top:12px">
          <button class="btn primary" data-act="fl-cp-save">${p.id ? 'Сохранить' : 'Добавить'}</button>
          ${p.id ? '<button class="btn ghost" data-act="fl-cp-del" style="color:var(--red)">Удалить</button>' : ''}
        </div>
      </div></div></div>
  </div>`;
}

async function flCpPost(body, okText) {
  try {
    const res = await api(`${API}/nom/counterparty`, { method: 'POST', body: JSON.stringify(body) });
    await loadCps();
    FL.cp = body.удалить ? flNewCp(FL.cpCat) : { ...res };
    toast(okText(res), 'ok');
    render();
  } catch (err) { toast(err.message, 'err'); }
}

const FL_LETTERS = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL', '5XL', '6XL'];
const flGridSeq = (grid) => (grid === 'буквенная' ? FL_LETTERS
  : ((ST.refs.размеры || []).find((b) => b.сетка === grid) || { размеры: [] }).размеры.map((x) => String(x.размер)));
// то же, что size_range на сервере: числовые через 2, остальные — по порядку сетки
function flSizeRange(grid, lo, hi) {
  lo = String(lo || '').trim(); hi = String(hi || '').trim();
  if (!lo || !hi) return [];
  if (grid === 'числовая') {
    const a = parseInt(lo, 10), b = parseInt(hi, 10);
    const out = [];
    if (a > 0 && a <= b) for (let x = a; x <= b; x += 2) out.push(String(x));
    return out;
  }
  const seq = flGridSeq(grid), up = seq.map((x) => x.toUpperCase());
  const i = up.indexOf(lo.toUpperCase()), j = up.indexOf(hi.toUpperCase());
  return i >= 0 && j >= i ? seq.slice(i, j + 1) : [];
}
const flNewProd = () => ({ категория: '', модель: '', название: '', сетка: 'числовая', от: '42', до: '64', цвета: [], изменить: false });
// полные наименования, которые появятся на складе: Категория/модель/цвет/размер (как на «главном»)
function flProdNames(p, sizes) {
  const cat = (p.категория || '').trim(), model = (p.модель || '').trim();
  if (!cat || !model || !p.цвета.length || !sizes.length) {
    return `<div class="cx-hint" style="margin-top:6px">Полное наименование: <b>Категория/модель/цвет/размер</b>, напр. «Брюки/477/чёрный/42» — появится здесь, когда заполните категорию, модель, цвета и размеры</div>`;
  }
  const names = p.цвета.flatMap((c) => sizes.map((z) => `${cat}/${model}/${c}/${z}`));
  return `<div class="cx-field" style="margin-top:10px"><label>Полные наименования <span class="cx-hint">${nf(names.length)} шт · так товар будет называться на складе</span></label>
    <div class="cx-scroll" style="max-height:220px;font-family:ui-monospace,monospace;font-size:13px;line-height:1.6">${names.map(esc).join('<br>')}</div></div>`;
}

// цвета модели: из справочника цветов + свои; по ним заводятся позиции склада (видны в «Приходе»)
function flProdColors(p) {
  const all = [...new Set([...(ST.refs.цвета || []).map((c) => c.цвет), ...p.цвета])].filter(Boolean);
  return `<div class="cx-field" style="margin-top:10px"><label>Цвета <span class="cx-hint">${nf(p.цвета.length)} выбрано</span></label>
    <div style="display:flex;flex-wrap:wrap;gap:6px;max-height:160px;overflow:auto">${all.map((c) => `<button type="button"
      class="rt-chip ${p.цвета.includes(c) ? 'on' : ''}" data-act="fl-prod-color" data-color="${esc(c)}">${esc(c)}</button>`).join('')}</div>
    <div style="display:flex;gap:6px;margin-top:6px"><input class="input" id="fl-prod-newcolor" placeholder="новый цвет, напр. молочный">
      <button type="button" class="btn ghost" data-act="fl-prod-addcolor">+ Цвет</button></div></div>`;
}

function goodsHtml() {
  const p = FL.prod || (FL.prod = flNewProd());
  const list = ST.refs.модели || [];
  const grids = [...new Set(['числовая', 'буквенная', ...(ST.refs.размеры || []).map((b) => b.сетка)])];
  const seq = p.сетка === 'числовая' ? [] : flGridSeq(p.сетка);
  const bound = (f) => (p.сетка === 'числовая'
    ? `<input class="input cx-mini" type="number" min="1" step="2" data-fl-prod="${f}" value="${esc(p[f])}">`
    : `<select class="input cx-mini" data-fl-prod="${f}">${flOpt('', p[f], '—')}${seq.map((z) => flOpt(z, p[f])).join('')}</select>`);
  const sizes = flSizeRange(p.сетка, p.от, p.до);
  return `<datalist id="fl-prodcats">${(ST.refs.категории || []).map((c) => `<option value="${esc(c)}">`).join('')}</datalist>
  <div class="cx-grid">
    <div class="cx-card"><div class="cx-card-h"><h3>Готовая продукция</h3><span class="cx-hint">${nf(list.length)} моделей</span></div>
      <div class="cx-card-b">${list.length ? `<div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Категория</th><th>Модель</th><th>Название</th><th>Размеры</th></tr></thead>
        <tbody>${list.map((m) => `<tr class="fl-nomrow ${p.изменить && p.модель === m.модель ? 'on' : ''}" data-act="fl-prod-pick" data-model="${esc(m.модель)}" style="cursor:pointer">
          <td>${esc(m.категория)}</td><td><b>${esc(m.модель)}</b></td><td>${esc(m.название)}</td>
          <td>${(m.размеры || []).length ? `${esc(m.от)}–${esc(m.до)} <span class="cx-hint">${esc(m.сетка)} · ${nf(m.размеры.length)} шт</span>`
            : `<span class="cx-hint">${esc(m.сетка)} · вся сетка</span>`}</td></tr>`).join('')}</tbody></table></div>`
        : '<div class="cx-hint">Моделей пока нет — добавьте первую справа</div>'}</div></div>
    <div class="cx-side"><div class="cx-card"><div class="cx-card-h"><h3>${p.изменить ? esc(p.модель) : 'Новый товар'}</h3>
        ${p.изменить ? '<button class="btn ghost" data-act="fl-prod-new">+ Новый</button>' : ''}</div>
      <div class="cx-card-b">
        <div class="cx-formgrid">
          <div class="cx-field"><label>Модель (артикул)</label><input class="input" data-fl-prod="модель" value="${esc(p.модель)}" ${p.изменить ? 'readonly title="Артикул уже в заказах — не меняется"' : ''} placeholder="напр. 265"></div>
          <div class="cx-field"><label>Название <span class="cx-hint" title="Понятное имя модели для списков и заказов. В полное наименование не входит">— для людей, в наименование не входит</span></label><input class="input" data-fl-prod="название" value="${esc(p.название)}" placeholder="напр. Худи оверсайз"></div>
          <div class="cx-field"><label>Категория</label><input class="input" list="fl-prodcats" data-fl-prod="категория" value="${esc(p.категория)}" placeholder="напр. Худи"></div>
          <div class="cx-field"><label>Размеры</label><select class="input" data-fl-prod="сетка">${grids.map((g) => flOpt(g, p.сетка, g === 'числовая' ? 'цифровые (42, 44…)' : g === 'буквенная' ? 'латинские (S, M, L…)' : g)).join('')}</select></div>
          <div class="cx-field"><label>От</label>${bound('от')}</div>
          <div class="cx-field"><label>До</label>${bound('до')}</div>
        </div>
        <div class="cx-hint" style="margin-top:10px">${sizes.length ? `Размеры: <b>${sizes.map(esc).join(', ')}</b> · ${nf(sizes.length)} шт`
          : 'Выберите размеры «от» и «до» — «от» не больше «до»'}</div>
        ${flProdColors(p)}
        <div class="cx-hint" style="margin-top:6px">${p.цвета.length && sizes.length
          ? `На складе появится ${nf(p.цвета.length * sizes.length)} позиций (${nf(p.цвета.length)} цв. × ${nf(sizes.length)} разм.) — их можно принимать в «Приходе»`
          : 'Без цветов товар не появится в «Приходе» склада'}</div>
        ${flProdNames(p, sizes)}
        <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-prod-save" ${sizes.length ? '' : 'disabled'}>${p.изменить ? 'Сохранить' : 'Добавить товар'}</button></div>
      </div></div></div>
  </div>`;
}

function supplyOrdersHtml() {
  const q = FL.supply.очередь || [];
  const o = q.find((x) => flQKey(x) === FL.num);
  return flQueue(q, 'fl-supply-open', 'Сюда попадают карты, которые конструктор передал снабженцу') + (o ? supplyCardHtml(o) : '');
}

function supplyCardHtml(o) {
  const card = (o.карта || []).map((c) => `<tr><td>${esc(c.карта)}</td><td>${esc(c.модель)}</td><td>${esc(c.цвет)}</td><td>${esc(c.размер)}</td>
    <td class="num">${nf(c.заказано)}</td><td class="num"><b>${nf(c.итог)}</b></td><td>${esc(c.характеристики)}</td></tr>`).join('');
  const mats = (o.сырьё || []).map((m, i) => `<tr>
      <td>${esc(m.материал)}</td><td>${esc(m.цвет)}</td><td class="num">${nf(m.нужно)} ${esc(m.ед)}</td>
      <td class="num ${m.есть ? '' : 'cx-neg'}">${nf(m.на_складе)}</td>
      <td class="num">${m.списано ? nf(m.списано) : '—'}</td>
      <td>${m.есть ? '<span class="cx-pill green">есть</span>' : '<span class="cx-pill red">нет</span>'}</td>
      <td><input class="input" data-fl-mat="${i}|комментарий" value="${esc(m.комментарий)}"></td>
    </tr>`).join('');
  const miss = o.без_спецификации || [];
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · карта ${esc(o.карта_номер)}</h3><span class="cx-hint">${nf(o.штук)} шт по карте</span></div>
    <div class="cx-card-b">
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Карта</th><th>Модель</th><th>Цвет</th><th>Размер</th><th class="num">Заказано</th><th class="num">Итог</th><th>Характеристики</th></tr></thead>
        <tbody>${card}</tbody></table></div>
      ${(o.рулоны || []).length ? `<h4 style="margin:18px 0 8px">Рулоны от конструктора</h4>
      <div class="cx-scroll"><table class="cx-table"><thead><tr><th>№</th><th>Вид</th><th>Цвет</th><th>Код (ВДМ) / сколько рулонов</th><th>Вес, кг — при передаче</th><th>Есть</th></tr></thead>
        <tbody>${o.рулоны.map((r, i) => `<tr><td>${i + 1}</td><td>${esc(r.вид)}${r.вдм ? ' <span class="cx-pill blue">ВДМ</span>' : ''}</td><td>${esc(r.цвет)}</td>
          ${r.вдм ? `<td><input class="input" data-fl-sroll="${i}|код" value="${esc(FL.supRolls[i].код)}" placeholder="код" style="max-width:160px"></td>
          <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-sroll="${i}|вес" value="${esc(FL.supRolls[i].вес || '')}" placeholder="кг"></td>
          <td>${!FL.supRolls[i].код ? '—' : r.есть && FL.supRolls[i].код === r.код ? '<span class="cx-pill green">есть</span>' : r.код === FL.supRolls[i].код ? '<span class="cx-pill red">нет</span>' : '<span class="cx-hint">сохраните</span>'}</td>`
          : `<td class="cx-hint">${nf(r.шт || 1)} шт · на складе ${nf(r.на_складе)}</td>
          <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-sroll="${i}|вес" value="${esc(FL.supRolls[i].вес || '')}" placeholder="кг" title="Сколько кг уходит закройщику"></td>
          <td>${r.есть ? '<span class="cx-pill green">есть</span>' : '<span class="cx-pill red">нет</span>'}</td>`}</tr>`).join('')}</tbody></table></div>` : ''}
      <h4 style="margin:18px 0 8px">Сырьё по спецификации <span class="cx-hint">без рулонов — их задаёт конструктор</span></h4>
      ${miss.length ? `<div class="cx-notice warn">Нет спецификации для: <b>${miss.map(esc).join(', ')}</b> — заполните во вкладке «Спецификации».</div>` : ''}
      ${mats ? `<div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Нужно</th><th class="num">На складе</th><th class="num">Списано</th><th>Есть</th><th>Комментарий</th></tr></thead>
        <tbody>${mats}</tbody></table></div>` : ''}
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-supply-save">Сохранить</button>
        <button class="btn primary" data-act="fl-supply-done">Сырьё готово — передать закройщику</button>
      </div>
    </div></div>`;
}

function flOpenSupply(numStr) {
  const o = (FL.supply.очередь || []).find((x) => flQKey(x) === numStr);
  if (!o) return;
  FL.num = numStr;
  FL.rows = (o.сырьё || []).map((m) => ({ ...m }));
  FL.supRolls = (o.рулоны || []).map((r) => ({ код: r.код || '', вес: r.вес || '' }));
  render();
}

async function flSaveSupply(done) {
  const [номер, карта] = FL.num.split('|');
  if (done && !confirm(`Передать карту ${карта} заказа №${номер} закройщику?\nСырьё по спецификации и рулоны карты спишутся в производство автоматически.`)) return;
  try {
    await api(`${API}/supply`, { method: 'POST', body: JSON.stringify({ номер, карта, готово: done, строки: FL.rows, рулоны: FL.supRolls }) });
    await loadSupply();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenSupply(FL.num);
    render();
    toast(done ? `Карта ${карта} передана закройщику` : 'Сохранено', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// размеры артикула — по каталогу «главный», иначе по размерной сетке модели
function flModelSizes(model) {
  const own = (modelInfo(model) || {}).размеры || [];
  if (own.length) return own.map(String);
  const v = (ST.refs.варианты || {})[model];
  return v && v.размеры.length ? v.размеры.map(String) : sizesFor(model).map((x) => String(x.размер));
}
const flMats = () => FL.supply.материалы || [];
const flCats = () => [...new Set(flMats().map((m) => m.категория))];

function bomHtml() {
  const all = FL.supply.спецификации || {};
  const models = (ST.refs.модели || []).map((m) => m.модель);
  Object.keys(all).forEach((m) => { if (!models.includes(m)) models.push(m); });
  const chips = models.map((m) => `<button class="rt-chip ${m === FL.bomModel ? 'on' : ''}" data-act="fl-bom-pick" data-model="${esc(m)}">${esc(m)}${all[m] ? ` · ${all[m].length}` : ''}</button>`).join('');
  const sizes = FL.bomModel ? flModelSizes(FL.bomModel) : [];
  const opt = (v, cur, label) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(label || v)}</option>`;
  const rows = FL.bomRows.map((r, i) => {
    const kinds = flMats().filter((m) => m.категория === r.категория && m.вид);
    const kindOpts = kinds.map((m) => opt(m.вид, r.материал)).join('')
      + (r.материал && !kinds.some((m) => m.вид === r.материал) ? opt(r.материал, r.материал, `${r.материал} (нет в справочнике)`) : '');
    return `<div class="cc-sec" style="margin-top:10px">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Категория</label><select class="input" data-fl-bom="${i}|категория">${opt('', r.категория, '— выберите —')}${flCats().map((c) => opt(c, r.категория)).join('')}</select></div>
        <div class="cx-field"><label>Вид</label><select class="input" data-fl-bom="${i}|материал">${opt('', r.материал, '— выберите —')}${kindOpts}</select></div>
        <div class="cx-field"><label>В цвет изделия</label><select class="input" data-fl-bom="${i}|цвет">${opt('', r.цвет, '1-й (основной)')}${opt('цвет 2', r.цвет, '2-й')}${opt('цвет 3', r.цвет, '3-й')}${r.цвет && !/^цвет \d$/.test(r.цвет) ? opt(r.цвет, r.цвет) : ''}</select></div>
        <div class="cx-field"><label>Расход на 1 шт, ${esc((flMatOf(r.материал) || {}).ед || r.ед || 'ед.')}</label><input class="input cx-mini" type="number" min="0" step="any" data-fl-bom="${i}|норма" value="${esc(r.норма || '')}"></div>
        <div class="cx-field" style="align-self:end"><button class="btn ghost" data-act="fl-bom-del" data-i="${i}">✕ убрать</button></div>
      </div>
      ${sizes.length ? `<div class="cx-hint" style="margin:8px 0 4px">Своя норма по размеру — если отличается от общей (пусто = общая)</div>
      <div class="cx-gwrap" style="max-height:none"><table class="cx-gtable"><thead><tr>${sizes.map((z) => `<th>${esc(z)}</th>`).join('')}</tr></thead>
        <tbody><tr>${sizes.map((z) => `<td><input class="cx-gin" type="number" min="0" step="any" data-fl-bomsize="${i}|${esc(z)}"
          value="${esc((r.по_размерам || {})[z] || '')}" placeholder="${esc(r.норма || '·')}"></td>`).join('')}</tr></tbody></table></div>` : ''}
      ${r.параметры ? `<div class="cx-hint" style="margin-top:6px">${esc(r.параметры)}</div>` : ''}
    </div>`;
  }).join('');
  return `<div class="cx-card"><div class="cx-card-h"><h3>Спецификация по артикулу</h3>
      <span class="cx-hint">материалы — из справочника «Материалы»</span></div>
    <div class="cx-card-b">
      <div class="cc-wait">${chips || '<span class="cx-hint">Справочник моделей пуст</span>'}</div>
      ${!flMats().length ? '<div class="cx-notice" style="margin-top:10px">Справочник материалов пуст — заведите категории и виды во вкладке «Материалы».</div>' : ''}
      ${FL.bomModel ? `
        <div class="cx-hint" style="margin-top:12px">Сколько уходит на 1 шт изделия (г, м, шт — по ед. позиции). Цвет материала = цвет изделия; у изделия в 2–3 цвета выберите, к какому цвету относится материал.</div>
        <div class="cx-hint" style="margin-top:6px"><b>${esc(FL.bomModel)}</b>${(modelInfo(FL.bomModel) || {}).категория ? ' · ' + esc(modelInfo(FL.bomModel).категория) : ''} · размеры: ${sizes.map(esc).join(', ') || '—'}</div>
        ${rows || '<div class="cx-hint" style="margin-top:8px">Материалов пока нет</div>'}
        <div class="cx-btn-row" style="margin-top:10px">
          <button class="btn" data-act="fl-bom-add">+ Материал</button>
          <button class="btn primary" data-act="fl-bom-save">Сохранить спецификацию ${esc(FL.bomModel)}</button>
        </div>` : '<div class="cx-hint" style="margin-top:10px">Выберите артикул</div>'}
    </div></div>`;
}

const flLow = (v) => String(v || '').toLowerCase();
const flMatOf = (kind) => flMats().find((m) => m.вид && flLow(m.вид) === flLow(kind));
const flSuppliers = () => [...new Set([...(ST.поставщики || []), ...flMats().map((m) => m.поставщик),
  ...(FL.supply.движения || []).map((m) => m.поставщик)].filter(Boolean))];
// где используется: спецификации артикулов, в которых есть позиция
function flUsedIn(kind) {
  const out = [];
  Object.entries(FL.supply.спецификации || {}).forEach(([model, lines]) => lines.forEach((b) => {
    if (flLow(b.материал) === flLow(kind)) out.push({ модель: model, ...b });
  }));
  return out;
}
const FL_UNITS = ['м', 'г', 'кг', 'шт'];
const flUnitSel = (attr, cur) => `<select class="input cx-mini" ${attr}>${FL_UNITS.map((u) => flOpt(u, cur)).join('')}${cur && !FL_UNITS.includes(cur) ? flOpt(cur, cur) : ''}</select>`;
const flOpt = (v, cur, label) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(label || v)}</option>`;
const flDatalists = () => `<datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
  <datalist id="fl-suppliers">${flSuppliers().map((c) => `<option value="${esc(c)}">`).join('')}</datalist>`;

function materialsHtml() {
  const q = flLow(FL.nomQ);
  const hit = (m) => !q || [m.вид, m.код, m.параметры, m.поставщик, m.категория].some((x) => flLow(x).includes(q));
  const blocks = flCats().map((c) => {
    const kinds = flMats().filter((m) => m.категория === c && m.вид);
    const shown = kinds.filter(hit);
    if (q && !shown.length && !flLow(c).includes(q)) return '';
    return `<div class="cc-sec" style="margin-top:10px">
      <div class="cc-sec-h"><b>📁 ${esc(c)}</b><span class="cx-hint">${nf(kinds.length)} поз.</span>
        <button class="btn ghost" data-act="fl-cat-ren" data-cat="${esc(c)}" aria-label="Переименовать группу ${esc(c)}">✎</button>
        ${kinds.length ? '' : `<button class="btn ghost" data-act="fl-mat-del" data-cat="${esc(c)}" data-kind="">✕ удалить группу</button>`}</div>
      ${shown.length ? `<div class="cx-scroll"><table class="cx-table"><thead><tr><th>Код</th><th>Наименование</th><th>Тип</th><th>Ед.</th></tr></thead><tbody>
        ${shown.map((m) => {
          return `<tr class="fl-nomrow ${flLow(FL.nomSel) === flLow(m.вид) ? 'on' : ''}" data-act="fl-nom-pick" data-kind="${esc(m.вид)}" style="cursor:pointer">
            <td class="cx-muted">${esc(m.код)}</td><td><b>${esc(m.вид)}</b>${m.параметры ? `<div class="cx-hint">${esc(m.параметры)}</div>` : ''}</td>
            <td>${esc(m.тип || '—')}</td>
            <td>${esc(m.ед)}</td></tr>`;
        }).join('')}</tbody></table></div>` : ''}
      <div class="cx-btn-row" style="margin-top:8px">
        <input class="input" data-fl-newkind="${esc(c)}" placeholder="новая позиция, напр. габардин 220" style="max-width:240px">
        ${flUnitSel(`data-fl-newunit="${esc(c)}"`, 'м')}
        <input class="input" data-fl-newparams="${esc(c)}" placeholder="параметры: ширина, граммаж, состав" style="max-width:260px">
        <button class="btn" data-act="fl-mat-add" data-cat="${esc(c)}">+ Позиция</button>
      </div></div>`;
  }).join('');
  return `${flDatalists()}<div class="cx-grid">
    <div class="cx-card"><div class="cx-card-h"><h3>Номенклатура</h3><span class="cx-hint">группы → виды товаров</span></div>
      <div class="cx-card-b">
        <div class="cx-btn-row">
          <input class="input" type="search" id="fl-nomq" placeholder="Поиск: название, код, параметры, поставщик" value="${esc(FL.nomQ)}" style="max-width:320px" data-nodirty>
          <input class="input" id="fl-newcat" placeholder="новая группа: ткань, фурнитура, нитки…" style="max-width:260px">
          <button class="btn primary" data-act="fl-cat-add">+ Группа</button>
        </div>
        ${blocks || '<div class="cx-hint" style="margin-top:10px">Групп пока нет</div>'}
      </div></div>
    <div class="cx-side">${nomCardHtml()}</div>
  </div>`;
}

function nomCardHtml() {
  const m = flMatOf(FL.nomSel);
  if (!m) return '<div class="cx-card"><div class="cx-empty"><b>Карточка позиции</b>Выберите позицию слева</div></div>';
  const used = flUsedIn(m.вид);
  return `<div class="cx-card"><div class="cx-card-h"><h3>${esc(m.вид)}</h3><span class="cx-hint">${esc(m.код)} · ${esc(m.категория)}</span></div>
    <div class="cx-card-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Наименование</label><input class="input" id="fl-n-вид" value="${esc(m.вид)}"></div>
        <div class="cx-field"><label>Группа</label><select class="input" id="fl-n-категория">${flCats().map((c) => flOpt(c, m.категория)).join('')}</select></div>
        <div class="cx-field"><label>Тип</label><select class="input" id="fl-n-тип">${flOpt('', m.тип, '—')}${(FL.supply.типы || []).map((t) => flOpt(t, m.тип)).join('')}</select></div>
        <div class="cx-field"><label>Ед.</label>${flUnitSel('id="fl-n-ед"', m.ед)}</div>
        <div class="cx-field"><label>Код</label><input class="input" id="fl-n-код" value="${esc(m.код)}"></div>
        <div class="cx-field"><label>Основной поставщик</label><input class="input" id="fl-n-поставщик" list="fl-suppliers" value="${esc(m.поставщик)}"></div>
        <div class="cx-field"><label>Цена закупки</label><input class="input cx-mini" type="number" min="0" step="any" id="fl-n-цена" value="${esc(m.цена || '')}"></div>
      </div>
      <div class="cx-field" style="margin-top:8px"><label>Параметры</label><input class="input" id="fl-n-параметры" value="${esc(m.параметры)}"></div>
      <div class="cx-btn-row" style="margin-top:10px">
        <button class="btn primary" data-act="fl-nom-save">Сохранить</button>
        <button class="btn ghost" data-act="fl-mat-del" data-cat="${esc(m.категория)}" data-kind="${esc(m.вид)}">✕</button>
      </div>

      <h4 style="margin:18px 0 6px">Где используется · ${nf(used.length)}</h4>
      ${used.length ? `<table class="cx-table cx-table-sm"><thead><tr><th>Артикул</th><th>Цвет</th><th class="num">Расход на 1 шт</th></tr></thead><tbody>
        ${used.map((u) => `<tr><td><a role="button" tabindex="0" style="cursor:pointer" data-act="fl-nom-bom" data-model="${esc(u.модель)}">${esc(u.модель)}</a></td>
          <td>${esc(/^цвет \d$/.test(u.цвет) ? u.цвет.replace('цвет ', '') + '-й цвет изделия' : (u.цвет || 'цвет изделия'))}</td>
          <td class="num">${u.норма ? `${nf(u.норма)} ${esc(u.ед)}` : '—'}${Object.keys(u.по_размерам || {}).length ? ' <span class="cx-hint">+ по размерам</span>' : ''}</td></tr>`).join('')}</tbody></table>`
        : '<div class="cx-hint">Ни в одной спецификации</div>'}

    </div></div>`;
}

const flNewMove = (doc = 'поступление', kind = '') => ({ документ: doc, поставщик: '', заказ: '', карта: '', комментарий: '',
  строки: [{ материал: kind, цвет: '', количество: '', цена: (flMatOf(kind) || {}).цена || '' }] });

function movesHtml() {
  const d = FL.mv || (FL.mv = flNewMove());
  const isIn = d.документ === 'поступление';
  const inv = d.документ === 'инвентаризация';
  const kinds = flCats().map((c) => `<optgroup label="${esc(c)}">${flMats().filter((m) => m.категория === c && m.вид)
    .map((m) => flOpt(m.вид, '', `${m.вид}${m.код ? ` · ${m.код}` : ''}`)).join('')}</optgroup>`).join('');
  const lines = d.строки.map((r, i) => {
    const m = flMatOf(r.материал);
    const have = (FL.supply.остатки || []).find((x) => flLow(x.материал) === flLow(r.материал) && flLow(x.цвет) === flLow(r.цвет));
    return `<tr>
      <td><select class="input" data-fl-mv="${i}|материал">${flOpt('', r.материал, '— позиция —')}${kinds.replace(`value="${esc(r.материал)}"`, `value="${esc(r.материал)}" selected`)}</select></td>
      <td><input class="input" data-fl-mv="${i}|цвет" list="fl-colors" value="${esc(r.цвет)}" placeholder="без цвета"></td>
      <td class="num cx-muted">${r.материал ? `${nf(have ? have.остаток : 0)} ${esc((m || {}).ед || '')}` : ''}</td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-mv="${i}|количество" value="${esc(r.количество)}"></td>
      ${isIn ? `<td><input class="input cx-mini" type="number" min="0" step="any" data-fl-mv="${i}|цена" value="${esc(r.цена)}"></td>` : ''}
      <td><button class="btn ghost" data-act="fl-mv-del" data-i="${i}">✕</button></td></tr>`;
  }).join('');
  const f = FL.mvFilter;
  const journal = (FL.supply.движения || []).filter((x) => !f || flLow(x.материал) === flLow(f));
  const stock = (FL.supply.остатки || []).filter((x) => x.остаток);
  const stockCard = `<div class="cx-card"><div class="cx-card-h"><h3>Остатки сырья</h3><span class="cx-hint">по позициям и цветам</span></div>
    <div class="cx-card-b">${stock.length ? `<div class="cx-scroll" style="max-height:320px"><table class="cx-table cx-table-sm"><thead><tr><th>Позиция</th><th>Цвет</th><th class="num">Остаток</th></tr></thead><tbody>
      ${stock.map((x) => `<tr><td>${esc(x.материал)}</td><td>${esc(x.цвет || '—')}</td><td class="num ${x.остаток < 0 ? 'cx-neg' : ''}"><b>${nf(x.остаток)}</b> ${esc((flMatOf(x.материал) || {}).ед || '')}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="cx-hint">Склад сырья пуст — проведите поступление ниже</div>'}</div></div>`;
  return `${flDatalists()}${stockCard}<div class="cx-card"><div class="cx-card-h"><h3>Новый документ</h3>
      <span class="cx-hint">${inv ? 'впишите фактический остаток — разница спишется или оприходуется' : 'остаток пересчитается сразу после проведения'}</span></div>
    <div class="cx-card-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Документ</label><select class="input" data-fl-mvh="документ">${(FL.supply.документы || []).map((x) => flOpt(x, d.документ)).join('')}</select></div>
        ${isIn || d.документ === 'возврат поставщику' ? `<div class="cx-field"><label>Поставщик</label><input class="input" data-fl-mvh="поставщик" list="fl-suppliers" value="${esc(d.поставщик)}"></div>` : ''}
        ${!inv ? `<div class="cx-field"><label>Заказ №</label><input class="input cx-mini" data-fl-mvh="заказ" inputmode="numeric" value="${esc(d.заказ)}"></div>
        <div class="cx-field"><label>Карта</label><input class="input cx-mini" data-fl-mvh="карта" inputmode="numeric" value="${esc(d.карта)}"></div>` : ''}
        <div class="cx-field"><label>Комментарий</label><input class="input" data-fl-mvh="комментарий" value="${esc(d.комментарий)}"></div>
      </div>
      <div class="cx-scroll" style="margin-top:12px"><table class="cx-table">
        <thead><tr><th>Позиция</th><th>Цвет</th><th class="num">Сейчас</th><th>${inv ? 'Факт' : 'Количество'}</th>${isIn ? '<th>Цена</th>' : ''}<th></th></tr></thead>
        <tbody>${lines}</tbody></table></div>
      <div class="cx-btn-row" style="margin-top:10px">
        <button class="btn" data-act="fl-mv-add">+ Строка</button>
        <button class="btn primary" data-act="fl-mv-post">Провести</button>
      </div>
    </div></div>
    <div class="cx-card" style="margin-top:14px"><div class="cx-card-h"><h3>Журнал движений</h3>
      <select class="input" id="fl-mvfilter" data-nodirty style="max-width:260px">${flOpt('', f, 'все позиции')}${flMats().filter((m) => m.вид).map((m) => flOpt(m.вид, f)).join('')}</select></div>
      <div class="cx-card-b"><div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Дата</th><th>Документ</th><th>Позиция</th><th>Цвет</th><th class="num">Кол-во</th><th class="num">Цена</th><th>Поставщик</th><th>Заказ</th><th>Кто</th><th>Комментарий</th><th></th></tr></thead>
        <tbody>${journal.slice(0, 300).map((x) => `<tr><td class="cx-muted">${esc(x.дата)}</td><td>${esc(x.документ)}</td>
          <td><a role="button" tabindex="0" style="cursor:pointer" data-act="fl-nom-pick" data-kind="${esc(x.материал)}">${esc(x.материал)}</a></td><td>${esc(x.цвет)}</td>
          <td class="num ${x.количество < 0 ? 'cx-neg' : ''}">${x.количество > 0 ? '+' : ''}${nf(x.количество)} ${esc(x.ед)}</td>
          <td class="num">${x.цена ? nf(x.цена) : ''}</td><td>${esc(x.поставщик)}</td>
          <td>${x.заказ ? `№${esc(x.заказ)}${x.карта ? ` · к.${esc(x.карта)}` : ''}` : ''}</td><td>${esc(x.кто)}</td><td>${esc(x.комментарий)}</td>
          <td>${x.id ? `<button class="btn ghost" data-act="fl-mv-undo" data-id="${x.id}" aria-label="Отменить строку">✕</button>` : ''}</td></tr>`).join('')
          || '<tr><td colspan="11" class="cx-empty">Движений пока нет</td></tr>'}</tbody></table></div></div></div>`;
}

function rollsHtml() {
  const list = FL.supply.рулоны || [];
  const got = FL.supply.приёмки_рулонов || [];
  const stock = (FL.supply.рулоны_склад || []).filter((x) => !x.вдм);
  const kinds = ((FL.supply.материалы || []).filter((m) => /рулон/i.test(m.категория) && m.вид && !/вдм/i.test(m.вид + ' ' + m.категория))).map((m) => m.вид);
  return `<div class="cx-card"><div class="cx-card-h"><h3>Приёмка рулонов</h3><span class="cx-hint">только штуками — одной строкой на всю партию; вес пишется при передаче закройщику</span></div>
    <div class="cx-card-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Вид рулона</label><select class="input" id="fl-rp-вид"><option value="">выберите…</option>${kinds.map((k) => `<option>${esc(k)}</option>`).join('')}</select></div>
        <div class="cx-field"><label>Цвет</label><input class="input" id="fl-rp-цвет" list="fl-colors"></div>
        <div class="cx-field"><label>Количество, шт *</label><input class="input" id="fl-rp-шт" type="number" min="1" step="1" inputmode="numeric" placeholder="например 10"></div>
        <div class="cx-field"><label>Поставщик</label><input class="input" id="fl-rp-поставщик"></div>
        <div class="cx-field"><label>Под заказ №</label><input class="input" id="fl-rp-заказ" inputmode="numeric"></div>
        <div class="cx-field"><label>Общий вес, кг</label><input class="input" id="fl-rp-кг" type="number" min="0" step="any" inputmode="decimal" placeholder="вся поставка"></div>
        <div class="cx-field"><label>Сумма, сом</label><input class="input" id="fl-rp-сумма" type="number" min="0" step="any" inputmode="decimal" placeholder="за всю поставку"></div>
      </div>
      <div class="cx-hint" style="margin-top:6px">Вес и сумма — для себестоимости: если заполнить, из них запишется поставка и цена за кг (сумма ÷ вес).</div>
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-rp-add">Принять рулоны</button></div>
      ${kinds.length ? '' : '<div class="cx-hint" style="margin-top:8px">В номенклатуре нет видов в группе «рулоны» — заведите их во вкладке «Номенклатура».</div>'}
      <h4 style="margin:16px 0 6px">На складе</h4>
      <div class="cx-hint">${stock.map((x) => `<b>${esc(x.вид)}</b> ${esc(x.цвет)} — ${nf(x.шт)} шт`).join(' · ') || 'Рулонов штуками пока нет'}</div>
      <div class="cx-scroll" style="margin-top:12px"><table class="cx-table">
        <thead><tr><th>Дата</th><th>Вид</th><th>Цвет</th><th class="num">Шт</th><th>Заказ</th><th>Поставщик</th><th>Принял</th></tr></thead>
        <tbody>${got.map((m) => `<tr><td>${esc(m.дата)}</td><td>${esc(m.материал)}</td><td>${esc(m.цвет)}</td><td class="num"><b>${nf(m.количество)}</b></td>
          <td>${esc(m.заказ)}</td><td>${esc(m.поставщик)}</td><td>${esc(m.кто)}</td></tr>`).join('')
          || '<tr><td colspan="7" class="cx-empty">Приёмок пока нет</td></tr>'}</tbody></table></div>
      <h4 style="margin:16px 0 6px">Поставки с ценой <span class="cx-hint">из них считается себестоимость ткани</span></h4>
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Дата</th><th>Вид</th><th>Цвет</th><th class="num">Рулонов</th><th class="num">кг</th><th class="num">Сумма</th><th class="num">сом/кг</th><th>Поставщик</th></tr></thead>
        <tbody>${(FL.supply.поставки || []).map((s) => `<tr><td>${esc(s["дата"])}</td><td>${esc(s["материал"])}</td><td>${esc(s["цвет"])}</td>
          <td class="num">${nf(s["рулонов"])}</td><td class="num">${nf(s["вес кг"])}</td><td class="num"><b>${nf(s["сумма"])}</b></td>
          <td class="num"><b>${nf(s["цена кг"])}</b></td><td>${esc(s["поставщик"])}</td></tr>`).join('')
          || '<tr><td colspan="8" class="cx-empty">Поставок с ценой пока нет — заполните вес и сумму при приёмке</td></tr>'}</tbody></table></div>
    </div></div>
  <div class="cx-card" style="margin-top:14px"><div class="cx-card-h"><h3>ВДМ — приёмка с кодом</h3><span class="cx-hint">каждый рулон ВДМ — со своим кодом</span></div>
    <div class="cx-card-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Код рулона</label><input class="input" id="fl-r-код"></div>
        <div class="cx-field"><label>Материал</label><input class="input" id="fl-r-материал"></div>
        <div class="cx-field"><label>Цвет</label><input class="input" id="fl-r-цвет" list="fl-colors"></div>
        <div class="cx-field"><label>Граммаж, г/м²</label><input class="input" id="fl-r-граммы" inputmode="decimal"></div>
        <div class="cx-field"><label>Вес, кг</label><input class="input" id="fl-r-вес" inputmode="decimal"></div>
        <div class="cx-field"><label>Под заказ №</label><input class="input" id="fl-r-заказ" inputmode="numeric"></div>
        <div class="cx-field"><label>Поставщик</label><input class="input" id="fl-r-поставщик"></div>
      </div>
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-roll-add">Внести рулон ВДМ</button></div>
      <div class="cx-scroll" style="margin-top:14px"><table class="cx-table">
        <thead><tr><th>Код</th><th>Дата</th><th>Материал</th><th>Цвет</th><th class="num">г/м²</th><th class="num">кг</th><th>Заказ</th><th>Поставщик</th><th>Внёс</th><th></th></tr></thead>
        <tbody>${list.map((r) => `<tr><td><b>${esc(r.код)}</b></td><td>${esc(r.дата)}</td><td>${esc(r.материал)}</td><td>${esc(r.цвет)}</td>
          <td class="num">${esc(r.граммы)}</td><td class="num">${esc(r.вес)}</td><td>${esc(r.заказ)}</td><td>${esc(r.поставщик)}</td><td>${esc(r.внёс)}</td>
          <td><button class="btn ghost" data-act="fl-roll-del" data-code="${esc(r.код)}" aria-label="Удалить рулон ${esc(r.код)}">✕</button></td></tr>`).join('')
          || '<tr><td colspan="10" class="cx-empty">Рулонов ВДМ пока нет</td></tr>'}</tbody></table></div>
    </div></div>`;
}

const FL_ROLL_FIELDS = ['код', 'материал', 'цвет', 'граммы', 'вес', 'заказ', 'поставщик'];

async function flPost(path, body, okText) {
  try {
    await api(`${API}${path}`, { method: 'POST', body: JSON.stringify(body) });
    await loadSupply();
    render();
    toast(okText, 'ok');
    return true;
  } catch (err) { toast(err.message, 'err'); return false; }
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="fl-"]');
  if (!el || !['design', 'supply', 'nom'].includes(ST.view)) return;
  ev.stopPropagation();
  const act = el.dataset.act;
  if (act === 'fl-design-open') return flOpenDesign(el.dataset.num);
  if (act === 'fl-supply-open') return flOpenSupply(el.dataset.num);
  if (act === 'fl-sz') {
    const k = el.dataset.k;
    if (FL.on.has(k)) FL.on.delete(k); else FL.on.add(k);
    return render();
  }
  if (act === 'fl-szrow') {  // весь цвет: если что-то включено — выключить, иначе включить все размеры
    const { card: c, model: m, color: col } = el.dataset;
    const { sizes } = flSizesOf(flOrder(), m);
    const keys = sizes.map((z) => flOnKey(c, m, col, z));
    const anyOn = keys.some((k) => FL.on.has(k));
    keys.forEach((k) => (anyOn ? FL.on.delete(k) : FL.on.add(k)));
    return render();
  }
  if (act === 'fl-card-new') {
    const next = String(Math.max(0, ...flCards().map(Number)) + 1);
    FL.models[next] = [...new Set(flBoss(flOrder()).map((p) => p.модель))];
    return render();
  }
  if (act === 'fl-card-del') {
    const c = el.dataset.card;
    if (flOnOf(c).length && !confirm(`Удалить карту ${c}?`)) return;
    delete FL.models[c];
    FL.on = new Set([...FL.on].filter((k) => !k.startsWith(c + '|')));
    FL.rolls = FL.rolls.filter((r) => r.карта !== c);
    return render();
  }
  if (act === 'fl-roll-row-add') { FL.rolls.push({ карта: el.dataset.card, вид: '', цвет: '', шт: 1 }); return render(); }
  if (act === 'fl-roll-row-del') { FL.rolls.splice(Number(el.dataset.i), 1); return render(); }
  if (act === 'fl-design-save' || act === 'fl-design-done') {
    el.disabled = true; await flSaveDesign(act === 'fl-design-done'); el.disabled = false; return;
  }
  if (act === 'fl-card-send') {
    el.disabled = true; await flSaveDesign(false, el.dataset.card); el.disabled = false; return;
  }
  if (act === 'fl-supply-save' || act === 'fl-supply-done') {
    el.disabled = true; await flSaveSupply(act === 'fl-supply-done'); el.disabled = false; return;
  }
  if (act === 'fl-sub') { if (ST.view === 'nom') FL.nomTab = el.dataset.tab; else FL.supplyTab = el.dataset.tab; FL.num = ''; return render(); }
  if (act === 'fl-prod-new') { FL.prod = flNewProd(); return render(); }
  if (act === 'fl-prod-color') {
    const c = el.dataset.color, list = FL.prod.цвета;
    FL.prod.цвета = list.includes(c) ? list.filter((x) => x !== c) : [...list, c];
    return render();
  }
  if (act === 'fl-prod-addcolor') {
    const inp = document.getElementById('fl-prod-newcolor');
    const c = (inp && inp.value || '').trim().replace(/\//g, '-');
    if (c && !FL.prod.цвета.some((x) => x.toLowerCase() === c.toLowerCase())) FL.prod.цвета = [...FL.prod.цвета, c];
    return render();
  }
  if (act === 'fl-cp-cat') { FL.cpCat = el.dataset.cat; if (!FL.cp || !FL.cp.id) FL.cp = flNewCp(FL.cpCat); return render(); }
  if (act === 'fl-cp-new') { FL.cp = flNewCp(FL.cpCat); return render(); }
  if (act === 'fl-cp-pick') {
    const c = ((FL.cps || {}).контрагенты || []).find((x) => x.id === el.dataset.id);
    if (c) FL.cp = { ...c };
    render();
    if (window.innerWidth < 1000) document.querySelector('.cx-side')?.scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (act === 'fl-cp-save') {
    el.disabled = true;
    const isNew = !FL.cp.id;
    await flCpPost({ ...FL.cp }, (r) => (isNew ? `«${r.название}» добавлен` : `«${r.название}» сохранён`));
    el.disabled = false;
    return;
  }
  if (act === 'fl-cp-del') {
    if (!confirm(`Удалить «${FL.cp.название}» из контрагентов?\nВ старых документах название останется.`)) return;
    el.disabled = true;
    await flCpPost({ id: FL.cp.id, удалить: true }, (r) => `«${r.удалён}» удалён`);
    return;
  }
  if (act === 'fl-prod-pick') {
    const m = (ST.refs.модели || []).find((x) => x.модель === el.dataset.model);
    if (m) FL.prod = { категория: m.категория, модель: m.модель, название: m.название, сетка: m.сетка, от: m.от, до: m.до, изменить: true,
      цвета: [...new Set([...(m.цвета || []), ...(((ST.refs.варианты || {})[m.модель] || {}).цвета || [])])] };
    render();
    if (window.innerWidth < 1000) document.querySelector('.cx-side')?.scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (act === 'fl-prod-save') {
    el.disabled = true;
    try {
      const res = await api(`${API}/nom/product`, { method: 'POST', body: JSON.stringify(FL.prod) });
      ST.refs = res.refs;
      toast((FL.prod.изменить ? `Модель ${res.модель} сохранена` : `Товар ${res.модель} добавлен`)
        + (res.позиций ? ` · на склад добавлено ${res.позиций} позиций` : ''), 'ok');
      FL.prod = flNewProd();
      render();
    } catch (err) { toast(err.message, 'err'); el.disabled = false; }
    return;
  }
  if (act === 'fl-bom-pick') {
    FL.bomModel = el.dataset.model;
    FL.bomRows = ((FL.supply.спецификации || {})[FL.bomModel] || []).map((r) => ({ ...r }));
    if (!FL.bomRows.length) FL.bomRows.push({ категория: '', материал: '', цвет: '', норма: '', ед: 'м', параметры: '', по_размерам: {} });
    return render();
  }
  if (act === 'fl-bom-add') { FL.bomRows.push({ категория: '', материал: '', цвет: '', норма: '', ед: 'м', параметры: '', по_размерам: {} }); return render(); }
  if (act === 'fl-cat-add') {
    const cat = (($('#fl-newcat') || {}).value || '').trim();
    if (!cat) return toast('Впишите группу', 'err');
    await flPost('/supply/material', { категория: cat }, `Группа «${cat}» добавлена`);
    return;
  }
  if (act === 'fl-mat-add') {
    const c = el.dataset.cat;
    const val = (a) => ((document.querySelector(`[${a}="${CSS.escape(c)}"]`) || {}).value || '').trim();
    const kind = val('data-fl-newkind');
    if (!kind) return toast('Впишите название позиции', 'err');
    if (await flPost('/supply/material', { категория: c, вид: kind, ед: val('data-fl-newunit'), параметры: val('data-fl-newparams') }, 'Позиция добавлена')) {
      FL.nomSel = kind; render();
    }
    return;
  }
  if (act === 'fl-mat-del') {
    const { cat, kind } = el.dataset;
    if (!confirm(kind ? `Удалить «${kind}» из «${cat}»?` : `Удалить группу «${cat}»?`)) return;
    if (await flPost('/supply/material', { категория: cat, вид: kind, удалить: true }, 'Удалено') && flLow(kind) === flLow(FL.nomSel)) {
      FL.nomSel = ''; render();
    }
    return;
  }
  if (act === 'fl-nom-pick') {
    ev.preventDefault();
    FL.nomSel = el.dataset.kind; FL.nomTab = 'mats';
    render();
    if (window.innerWidth < 1000) document.querySelector('.cx-side')?.scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (act === 'fl-nom-bom') {
    ev.preventDefault();
    FL.nomTab = 'bom'; FL.bomModel = el.dataset.model;
    FL.bomRows = ((FL.supply.спецификации || {})[FL.bomModel] || []).map((r) => ({ ...r }));
    return render();
  }
  if (act === 'fl-nom-save') {
    const m = flMatOf(FL.nomSel);
    const v = (f) => (($(`#fl-n-${f}`) || {}).value || '').trim();
    const вид = v('вид') || m.вид, категория = v('категория') || m.категория;
    if (вид !== m.вид || категория !== m.категория) {
      try {
        await api(`${API}/supply/rename`, { method: 'POST', body: JSON.stringify({ категория_было: m.категория, вид_было: m.вид, категория, вид }) });
      } catch (err) { return toast(err.message, 'err'); }
      FL.nomSel = вид;
    }
    await flPost('/supply/material', { категория, вид, тип: v('тип'), ед: v('ед'), код: v('код'),
      поставщик: v('поставщик'), цена: v('цена'), мин: m.мин, параметры: v('параметры') }, `«${m.вид}» сохранено`);
    return;
  }
  if (act === 'fl-cat-ren') {
    const old = el.dataset.cat;
    const name = (prompt(`Новое название группы «${old}»`, old) || '').trim();
    if (name && name !== old) await flPost('/supply/rename', { категория_было: old, категория: name }, `Группа «${name}»`);
    return;
  }
  if (act === 'fl-mv-undo') {
    if (!confirm('Отменить эту строку журнала? Остаток пересчитается.')) return;
    await flPost('/supply/move/delete', { id: el.dataset.id }, 'Строка отменена');
    return;
  }
  if (act === 'fl-roll-del') {
    if (!confirm(`Удалить рулон ${el.dataset.code}?`)) return;
    await flPost('/supply/roll/delete', { код: el.dataset.code }, 'Рулон удалён');
    return;
  }
  if (act === 'fl-mv-add') { FL.mv.строки.push({ материал: '', цвет: '', количество: '', цена: '' }); return render(); }
  if (act === 'fl-mv-del') { FL.mv.строки.splice(Number(el.dataset.i), 1); if (!FL.mv.строки.length) FL.mv = flNewMove(FL.mv.документ); return render(); }
  if (act === 'fl-mv-post') {
    const d = FL.mv;
    el.disabled = true;
    if (await flPost('/supply/move', d, `Проведено: ${d.документ}`)) FL.mv = flNewMove(d.документ);
    el.disabled = false;
    return render();
  }
  if (act === 'fl-bom-del') { FL.bomRows.splice(Number(el.dataset.i), 1); return render(); }
  if (act === 'fl-bom-save') {
    await flPost('/supply/bom', { модель: FL.bomModel, строки: FL.bomRows }, `Спецификация ${FL.bomModel} сохранена`);
    return;
  }
  if (act === 'fl-rp-add') {  // приёмка рулонов штуками: одна строка прихода на всю партию
    const v = (id) => (($(`#fl-rp-${id}`) || {}).value || '').trim();
    const qty = Math.round(Number(v('шт')));
    if (!v('вид')) return toast('Выберите вид рулона', 'err');
    if (!(qty > 0)) return toast('Укажите количество рулонов, шт', 'err');
    const kg = Number(v('кг'));
    const total = Number(v('сумма'));
    if ((v('кг') || v('сумма')) && !(kg > 0 && total > 0)) {
      return toast('Для поставки заполните и вес, и сумму (больше нуля) — или очистите оба поля', 'err');
    }
    const ok = await flPost('/supply/move', { документ: 'поступление', поставщик: v('поставщик'), заказ: v('заказ'),
      комментарий: 'приёмка рулонов штуками',
      строки: [{ материал: v('вид'), цвет: v('цвет'), количество: qty, ед: 'шт' }] },
      `Принято ${qty} шт: ${v('вид')} ${v('цвет')}`.trim());
    if (ok && kg > 0 && total > 0) {  // та же партия — поставкой с ценой для себестоимости
      try {
        const d = await api(`${API}/supplies`, { method: 'POST', body: JSON.stringify({
          материал: v('вид'), цвет: v('цвет'), рулонов: qty, вес: kg, сумма: total, поставщик: v('поставщик') }) });
        toast(`Поставка записана: ${nf(d["цена кг"])} сом/кг`, 'ok');
        await loadSupply();
        render();
      } catch (err) {
        toast(`Рулоны приняты, но поставка не записалась: ${err.message} — заполните лист «Поставки сырья» вручную`, 'err');
      }
    }
    if (ok) FL.supplyTab = 'rolls';
    return;
  }
  if (act === 'fl-roll-add') {
    const body = {};
    FL_ROLL_FIELDS.forEach((f) => { body[f] = ($(`#fl-r-${f}`) || {}).value || ''; });
    if (await flPost('/supply/roll', body, `Рулон ${body.код} внесён`)) FL.supplyTab = 'rolls';
  }
}, true);

document.addEventListener('input', (ev) => {
  const t = ev.target;
  if (t.dataset.flCp && FL.cp) { FL.cp[t.dataset.flCp] = t.value; return; }
  if (t.id === 'fl-cpq') {
    FL.cpQ = t.value;
    const q = t.value.trim().toLowerCase();
    document.querySelectorAll('.fl-cprow').forEach((r) => { r.style.display = !q || r.dataset.q.includes(q) ? '' : 'none'; });
    return;
  }
  const pick = (attr, list) => {
    const [i, f] = t.dataset[attr].split('|');
    list[Number(i)][f] = t.value;
  };
  if (t.dataset.flChars) FL.chars[t.dataset.flChars] = t.value;
  if (t.dataset.flProd && t.tagName === 'INPUT') FL.prod[t.dataset.flProd] = t.value;
  if (t.dataset.flRoll) {
    pick('flRoll', FL.rolls);
    if (t.dataset.flRoll.endsWith('|цвет')) render();  // виды рулонов зависят от цвета
  }
  if (t.dataset.flSroll) pick('flSroll', FL.supRolls);
  if (t.dataset.flMat) pick('flMat', FL.rows);
  if (t.dataset.flBom) pick('flBom', FL.bomRows);
  if (t.dataset.flMv) pick('flMv', FL.mv.строки);
  if (t.dataset.flMvh) FL.mv[t.dataset.flMvh] = t.value;
  if (t.id === 'fl-nomq') {
    FL.nomQ = t.value;
    const pos = t.selectionStart;
    render();
    const n = $('#fl-nomq'); if (n) { n.focus(); n.setSelectionRange(pos, pos); }
  }
  if (t.dataset.flBomsize) {
    const [i, z] = t.dataset.flBomsize.split('|');
    const r = FL.bomRows[Number(i)];
    r.по_размерам = { ...(r.по_размерам || {}) };
    if (num(t.value) > 0) r.по_размерам[z] = num(t.value); else delete r.по_размерам[z];
  }
});

// спецификация: категория меняет список видов, вид подставляет ед. и параметры из справочника
document.addEventListener('change', (ev) => {
  const t = ev.target;
  if (t.dataset.flProd) {  // тип размеров меняет поля «от/до»; размеры пересчитываются
    FL.prod[t.dataset.flProd] = t.value;
    if (t.dataset.flProd === 'сетка') Object.assign(FL.prod, t.value === 'числовая' ? { от: '42', до: '64' }
      : { от: flGridSeq(t.value)[0] || '', до: flGridSeq(t.value).slice(-1)[0] || '' });
    return render();
  }
  if (!['supply', 'nom'].includes(ST.view)) return;
  if (t.id === 'fl-mvfilter') { FL.mvFilter = t.value; return render(); }
  // документ меняет набор полей; позиция подставляет цену из карточки
  if (t.dataset.flMvh === 'документ') return render();
  if (t.dataset.flMv && t.tagName === 'SELECT') {
    const r = FL.mv.строки[Number(t.dataset.flMv.split('|')[0])];
    if (!r.цена) r.цена = (flMatOf(r.материал) || {}).цена || '';
    return render();
  }
  if (!t.dataset.flBom || t.tagName !== 'SELECT') return;
  const [i, f] = t.dataset.flBom.split('|');
  const r = FL.bomRows[Number(i)];
  r[f] = t.value;
  if (f === 'категория') r.материал = '';
  if (f === 'материал') {
    const m = flMats().find((x) => x.категория === r.категория && x.вид === r.материал);
    if (m) { r.ед = m.ед || r.ед; r.параметры = m.параметры; }
  }
  render();
});
