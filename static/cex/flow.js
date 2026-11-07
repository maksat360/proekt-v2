'use strict';

/* Модуль «Цех» · поток заказа: конструктор (производственная карта) → снабженец (сырьё) → технолог. */

const FL = { design: { очередь: [], история: {} }, supply: { очередь: [], спецификации: {}, рулоны: [], статусы: [] },
  num: '', rows: [], models: {}, chars: {}, allColors: {}, bomModel: '', bomRows: [], supplyTab: 'orders' };

async function loadDesign() { FL.design = await api(`${API}/design`); }
async function loadSupply() { FL.supply = await api(`${API}/supply`); }

function flHistoryHtml(list) {
  if (!list || !list.length) return '<div class="cx-hint">Изменений пока нет</div>';
  return `<div class="cx-scroll"><table class="cx-table">
    <thead><tr><th>Когда</th><th>Кто</th><th>Позиция</th><th class="num">Было</th><th class="num">Стало</th><th>Комментарий</th></tr></thead>
    <tbody>${list.slice().reverse().map((h) => `<tr><td>${esc(h.дата)}</td><td>${esc(h.кто)}</td>
      <td>${h.модель ? `${h.карта ? `карта ${esc(h.карта)} · ` : ''}${esc(h.модель)} · ${esc(h.цвет)} · ${esc(h.размер)}` : '<b>Все карты</b>'}</td>
      <td class="num">${esc(h.было)}</td><td class="num">${esc(h.стало)}</td><td>${esc(h.комментарий)}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

function flQueue(list, act, empty) {
  if (!list.length) return `<div class="cx-card"><div class="cx-empty"><b>Очередь пуста</b>${empty}</div></div>`;
  return `<div class="cx-queue">${list.map((o) => `
    <div class="cx-qitem ${FL.num === o.номер ? 'on' : ''}" data-act="${act}" data-num="${esc(o.номер)}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Заказ №${esc(o.номер)} ${statusPill(o.статус)}</div>
        <div class="cx-hint">${esc(o.клиент)} · ${nf(o.позиций)} поз. · заказано ${nf(o.заказано)} шт · срок ${esc(o.срок || '—')}</div>
      </div>
      <div class="cx-qright"><button class="btn primary" data-act="${act}" data-num="${esc(o.номер)}">Открыть</button></div>
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
// FL.chars — доп. характеристики модели в карте; FL.allColors — «показать все цвета/размеры».
const flCards = () => Object.keys(FL.models).sort((a, b) => a - b);
const flQty = (card) => FL.rows.filter((r) => card == null || r.карта === card).reduce((s, r) => s + num(r.итог), 0);
const flOrder = () => (FL.design.очередь || []).find((x) => x.номер === FL.num);

// Заказ начальника — только ориентир: показываем отклонение, ничего не запрещаем
function flDevHtml(o) {
  const got = {};
  FL.rows.forEach((r) => { const k = flKey(r.модель, r.цвет, r.размер); got[k] = (got[k] || 0) + num(r.итог); });
  const lines = (o.позиции || []).map((p) => {
    const k = flKey(p.модель, p.цвет, p.размер);
    const have = got[k] || 0; delete got[k];
    return { name: `${p.модель} · ${p.цвет} · ${p.размер}`, want: num(p.количество), have };
  });
  Object.entries(got).forEach(([k, have]) => { if (have) lines.push({ name: k.split('|').join(' · '), want: 0, have }); });
  const dev = (d) => (d > 0 ? `<b style="color:var(--orange,#e8a33d)">+${nf(d)}</b>` : d < 0 ? `<b style="color:var(--red,#e5534b)">${nf(d)}</b>` : '0');
  const want = lines.reduce((s, l) => s + l.want, 0);
  const have = lines.reduce((s, l) => s + l.have, 0);
  return `<table class="cx-table"><thead><tr><th>Позиция</th><th class="num">Заказано</th><th class="num">В картах</th><th class="num">Отклонение</th></tr></thead>
    <tbody>${lines.map((l) => `<tr><td>${esc(l.name)}${l.want ? '' : ' <span class="cx-hint">нет в заказе</span>'}</td>
      <td class="num">${nf(l.want)}</td><td class="num">${nf(l.have)}</td><td class="num">${dev(l.have - l.want)}</td></tr>`).join('')}
    <tr><td><b>Всего</b></td><td class="num"><b>${nf(want)}</b></td><td class="num"><b>${nf(have)}</b></td><td class="num">${dev(have - want)}</td></tr></tbody></table>`;
}

// цвета и размеры модели — как в «Новом заказе» (каталог «главный»), плюс всё, что уже есть в заказе и картах
function flGrid(o, card, model) {
  const v = (ST.refs.варианты || {})[model];
  const all = !v || !v.цвета.length || FL.allColors[`${card}|${model}`];
  const grid = sizesFor(model).map((x) => x.размер);
  const colors = new Set(v && v.цвета.length ? v.цвета : []);
  const sizes = new Set(v && v.размеры.length && !all ? v.размеры : grid);
  if (all) (ST.refs.цвета || []).forEach((c) => colors.add(c.цвет));
  [...(o.позиции || []), ...FL.rows].filter((r) => r.модель === model).forEach((r) => { colors.add(r.цвет); sizes.add(String(r.размер)); });
  const order = Object.fromEntries(grid.map((x, i) => [String(x), i]));
  return { colors: [...colors].filter(Boolean),
    sizes: [...sizes].filter(Boolean).sort((a, b) => (order[a] ?? 999) - (order[b] ?? 999) || String(a).localeCompare(String(b), 'ru', { numeric: true })),
    own: !!(v && v.цвета.length) };
}

// подсказка в клетке: сколько заказал начальник минус то, что уже разложено по другим картам
function flHint(o, card, model, color, size) {
  const k = flKey(model, color, size);
  const want = (o.позиции || []).filter((p) => flKey(p.модель, p.цвет, p.размер) === k).reduce((s, p) => s + num(p.количество), 0);
  const other = FL.rows.filter((r) => r.карта !== card && flKey(r.модель, r.цвет, r.размер) === k).reduce((s, r) => s + num(r.итог), 0);
  return Math.max(0, want - other);
}

function flModelHtml(o, card, model) {
  const { colors, sizes, own } = flGrid(o, card, model);
  const cell = (c, z) => FL.rows.find((r) => r.карта === card && flKey(r.модель, r.цвет, r.размер) === flKey(model, c, z));
  const sum = FL.rows.filter((r) => r.карта === card && r.модель === model).reduce((s, r) => s + num(r.итог), 0);
  const id = `${card}|${model}`;
  return `<div class="cc-sec" style="margin-top:10px">
    <div class="cc-sec-h"><b>${esc(model)}</b> <span class="cx-hint">${esc((modelInfo(model) || {}).категория || 'нет в каталоге')}</span>
      <span class="cx-hint" data-fl-msum="${esc(id)}">${nf(sum)} шт</span>
      <button class="btn ghost" data-act="fl-fill" data-card="${esc(card)}" data-model="${esc(model)}" title="Вписать числа начальника в пустые клетки">как в заказе</button>
      <button class="btn ghost" data-act="fl-model-del" data-card="${esc(card)}" data-model="${esc(model)}" title="Убрать модель из карты">✕</button></div>
    <div class="cx-gtools" style="padding-left:0">
      <input class="input" data-fl-chars="${esc(id)}" value="${esc(FL.chars[id] || '')}" placeholder="доп. характеристики: длина, посадка, детали кроя…" style="max-width:360px">
      ${own ? `<label class="cx-gall"><input type="checkbox" data-act="fl-allcolors" data-id="${esc(id)}" ${FL.allColors[id] ? 'checked' : ''}> новый цвет / размер (показать все)</label>` : ''}
      <span class="cx-hint">Серым — подсказка из заказа начальника. Пустые клетки в карту не попадут.</span>
    </div>
    <div class="cx-gwrap"><table class="cx-gtable">
      <thead><tr><th class="cx-gcolor">Цвет / размер</th>${sizes.map((z) => `<th>${esc(z)}</th>`).join('')}</tr></thead>
      <tbody>${colors.map((c) => `<tr><th class="cx-gcolor">${esc(c)}</th>${sizes.map((z) => {
        const r = cell(c, z);
        const h = flHint(o, card, model, c, z);
        return `<td><input class="cx-gin" type="number" min="0" step="1" inputmode="numeric" data-fl-cell="${esc(card)}|${esc(model)}|${esc(c)}|${esc(z)}"
          value="${r && num(r.итог) ? esc(r.итог) : ''}" placeholder="${h || '·'}" aria-label="${esc(c)}, размер ${esc(z)}"></td>`;
      }).join('')}</tr>`).join('')}</tbody>
    </table></div></div>`;
}

function designCardHtml(o) {
  const models = (ST.refs.модели || []);
  const cards = flCards().map((c) => `<div class="cx-card" style="margin-top:12px"><div class="cx-card-h"><h3>Карта ${esc(c)}</h3>
      <span class="cx-hint"><b data-fl-card-total="${esc(c)}">${nf(flQty(c))}</b> шт · станет отдельной партией</span></div>
    <div class="cx-card-b">
      ${(FL.models[c] || []).map((m) => flModelHtml(o, c, m)).join('') || '<div class="cx-hint">Добавьте модель в карту</div>'}
      <div class="cx-btn-row" style="margin-top:10px">
        <input class="input" data-fl-newmodel="${esc(c)}" list="fl-models" placeholder="модель (артикул)" style="max-width:220px">
        <button class="btn" data-act="fl-model-add" data-card="${esc(c)}">+ Модель</button>
        ${flCards().length > 1 ? `<button class="btn ghost" data-act="fl-card-del" data-card="${esc(c)}">Удалить карту</button>` : ''}
      </div>
    </div></div>`).join('');
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · производственные карты</h3>
      <span class="cx-hint">в заказе ${nf(o.заказано)} шт · в картах <b id="fl-total">${nf(flQty())}</b> шт</span></div>
    <div class="cx-card-b">
      ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
      <h4 style="margin:0 0 8px">Заказ начальника и карты</h4>
      <div class="cx-scroll" id="fl-dev">${flDevHtml(o)}</div>
      <datalist id="fl-models">${models.map((m) => `<option value="${esc(m.модель)}">${esc(m.название)}</option>`).join('')}</datalist>
      ${cards}
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn" data-act="fl-card-add">+ Карта</button></div>
      <div class="cx-field" style="margin-top:12px"><label>Комментарий к изменению</label>
        <input class="input" id="fl-note" placeholder="Например: по 46 размеру не хватает ткани"></div>
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-design-save">Сохранить черновик</button>
        <button class="btn primary" data-act="fl-design-done">Утвердить и передать снабженцу</button>
      </div>
      <div class="cx-hint" style="margin-top:8px">Заказ начальника — только подсказка: конструктор вписывает своё количество, больше или меньше, любые модели, цвета и размеры. Каждая карта у технолога становится отдельной партией. Все изменения записываются в историю.</div>
      <h4 style="margin:18px 0 8px">История изменений</h4>
      ${flHistoryHtml((FL.design.история || {})[o.номер])}
    </div></div>`;
}

function flOpenDesign(numStr) {
  const o = (FL.design.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  // карту ещё не сохраняли — клетки пустые, числа начальника видны серыми подсказками
  const draft = !o.карта_сохранена;
  FL.rows = draft ? [] : (o.карта || []).filter((r) => num(r.итог) > 0)
    .map((r) => ({ карта: String(r.карта || '1'), модель: r.модель, цвет: r.цвет, размер: String(r.размер), итог: num(r.итог) }));
  FL.models = {}; FL.chars = {}; FL.allColors = {};
  (draft ? (o.позиции || []).map((p) => ({ ...p, карта: '1' })) : (o.карта || [])).forEach((r) => {
    const c = String(r.карта || '1');
    FL.models[c] = FL.models[c] || [];
    if (!FL.models[c].includes(r.модель)) FL.models[c].push(r.модель);
    if (r.характеристики) FL.chars[`${c}|${r.модель}`] = r.характеристики;
  });
  if (!flCards().length) FL.models['1'] = [];
  render();
}

function flRefreshDesign() {
  const o = flOrder();
  if (!o) return;
  const total = document.getElementById('fl-total');
  if (total) total.textContent = nf(flQty());
  document.querySelectorAll('[data-fl-card-total]').forEach((b) => { b.textContent = nf(flQty(b.dataset.flCardTotal)); });
  document.querySelectorAll('[data-fl-msum]').forEach((b) => {
    const [c, ...m] = b.dataset.flMsum.split('|');
    b.textContent = `${nf(FL.rows.filter((r) => r.карта === c && r.модель === m.join('|')).reduce((s, r) => s + num(r.итог), 0))} шт`;
  });
  document.querySelectorAll('[data-fl-cell]').forEach((el) => {  // подсказки других карт меняются вместе с этой
    const [c, m, col, z] = el.dataset.flCell.split('|');
    el.placeholder = flHint(o, c, m, col, z) || '·';
  });
  const dev = document.getElementById('fl-dev');
  if (dev) dev.innerHTML = flDevHtml(o);
}

function flSetCell(card, model, color, size, qty) {
  const k = flKey(model, color, size);
  const i = FL.rows.findIndex((r) => r.карта === card && flKey(r.модель, r.цвет, r.размер) === k);
  if (qty > 0 && i >= 0) FL.rows[i].итог = qty;
  else if (qty > 0) FL.rows.push({ карта: card, модель: model, цвет: color, размер: size, итог: qty });
  else if (i >= 0) FL.rows.splice(i, 1);
}

async function flSaveDesign(done) {
  const rows = FL.rows.filter((r) => num(r.итог) > 0)
    .map((r) => ({ ...r, характеристики: FL.chars[`${r.карта}|${r.модель}`] || '' }));
  if (!rows.length) return toast('Карты пустые — впишите количество', 'err');
  const body = { номер: FL.num, готово: done, комментарий: ($('#fl-note') || {}).value || '', позиции: rows };
  if (done && !confirm('Утвердить карты и передать заказ снабженцу? После этого карты не поменять.')) return;
  try {
    const res = await api(`${API}/design`, { method: 'POST', body: JSON.stringify(body) });
    await loadDesign();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenDesign(FL.num);
    render();
    toast(done ? `Заказ №${res.номер} передан снабженцу · ${nf(res.штук)} шт` : 'Черновик карт сохранён', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// ------------------------------------------------------------- снабжение
function supplyHtml() {
  const t = FL.supplyTab;
  const sub = [['orders', `Заказы ${nf((FL.supply.очередь || []).length)}`], ['bom', 'Спецификации'], ['mats', 'Материалы'], ['rolls', 'Рулоны']];
  return `<div class="cx-hero compact"><div><h1>Снабжение</h1>
      <div class="cx-sub">Сырьё по спецификациям артикулов, поступившие рулоны. Когда сырьё готово — заказ уходит технологу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'bom' ? bomHtml() : t === 'mats' ? materialsHtml() : t === 'rolls' ? rollsHtml() : supplyOrdersHtml()}`;
}

function supplyOrdersHtml() {
  const q = FL.supply.очередь || [];
  const o = q.find((x) => x.номер === FL.num);
  return flQueue(q, 'fl-supply-open', 'Сюда попадают заказы с утверждённой картой конструктора') + (o ? supplyCardHtml(o) : '');
}

function supplyCardHtml(o) {
  const card = (o.карта || []).map((c) => `<tr><td>${esc(c.карта)}</td><td>${esc(c.модель)}</td><td>${esc(c.цвет)}</td><td>${esc(c.размер)}</td>
    <td class="num">${nf(c.заказано)}</td><td class="num"><b>${nf(c.итог)}</b></td><td>${esc(c.характеристики)}</td></tr>`).join('');
  const sts = FL.supply.статусы || [];
  const mats = (o.сырьё || []).map((m, i) => `<tr>
      <td>${esc(m.материал)}</td><td>${esc(m.цвет)}</td><td class="num">${nf(m.нужно)} ${esc(m.ед)}</td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-mat="${i}|есть" value="${esc(m.есть || '')}"></td>
      <td><select class="input" data-fl-mat="${i}|статус"><option value="">—</option>${sts.map((s) => `<option ${m.статус === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></td>
      <td><input class="input" data-fl-mat="${i}|комментарий" value="${esc(m.комментарий)}"></td>
    </tr>`).join('');
  const miss = o.без_спецификации || [];
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · карта конструктора</h3><span class="cx-hint">${nf(o.штук)} шт по карте</span></div>
    <div class="cx-card-b">
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Карта</th><th>Модель</th><th>Цвет</th><th>Размер</th><th class="num">Заказано</th><th class="num">Итог</th><th>Характеристики</th></tr></thead>
        <tbody>${card}</tbody></table></div>
      <h4 style="margin:18px 0 8px">Сырьё по спецификации</h4>
      ${miss.length ? `<div class="cx-notice warn">Нет спецификации для: <b>${miss.map(esc).join(', ')}</b> — заполните во вкладке «Спецификации».</div>` : ''}
      ${mats ? `<div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Нужно</th><th>Есть / заказано</th><th>Статус</th><th>Комментарий</th></tr></thead>
        <tbody>${mats}</tbody></table></div>` : ''}
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-supply-save">Сохранить</button>
        <button class="btn primary" data-act="fl-supply-done">Сырьё готово — передать технологу</button>
      </div>
    </div></div>`;
}

function flOpenSupply(numStr) {
  const o = (FL.supply.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  FL.rows = (o.сырьё || []).map((m) => ({ ...m }));
  render();
}

async function flSaveSupply(done) {
  if (done && !confirm('Передать заказ технологу?')) return;
  try {
    await api(`${API}/supply`, { method: 'POST', body: JSON.stringify({ номер: FL.num, готово: done, строки: FL.rows }) });
    await loadSupply();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenSupply(FL.num);
    render();
    toast(done ? 'Заказ передан технологу' : 'Сохранено', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// размеры артикула — по каталогу «главный», иначе по размерной сетке модели
function flModelSizes(model) {
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
        <div class="cx-field"><label>Цвет</label><input class="input" data-fl-bom="${i}|цвет" value="${esc(r.цвет)}" placeholder="пусто = в цвет изделия" list="fl-colors"></div>
        <div class="cx-field"><label>Ед.</label><input class="input cx-mini" data-fl-bom="${i}|ед" value="${esc(r.ед || 'м')}"></div>
        <div class="cx-field"><label>Норма на 1 шт (все размеры)</label><input class="input cx-mini" type="number" min="0" step="any" data-fl-bom="${i}|норма" value="${esc(r.норма || '')}"></div>
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
        <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
        <div class="cx-hint" style="margin-top:12px"><b>${esc(FL.bomModel)}</b>${(modelInfo(FL.bomModel) || {}).категория ? ' · ' + esc(modelInfo(FL.bomModel).категория) : ''} · размеры: ${sizes.map(esc).join(', ') || '—'}</div>
        ${rows || '<div class="cx-hint" style="margin-top:8px">Материалов пока нет</div>'}
        <div class="cx-btn-row" style="margin-top:10px">
          <button class="btn" data-act="fl-bom-add">+ Материал</button>
          <button class="btn primary" data-act="fl-bom-save">Сохранить спецификацию ${esc(FL.bomModel)}</button>
        </div>` : '<div class="cx-hint" style="margin-top:10px">Выберите артикул</div>'}
    </div></div>`;
}

function materialsHtml() {
  const blocks = flCats().map((c) => {
    const kinds = flMats().filter((m) => m.категория === c && m.вид);
    return `<div class="cc-sec" style="margin-top:10px">
      <div class="cc-sec-h"><b>${esc(c)}</b><span class="cx-hint">${nf(kinds.length)} вид.</span>
        ${kinds.length ? '' : `<button class="btn ghost" data-act="fl-mat-del" data-cat="${esc(c)}" data-kind="">✕ удалить категорию</button>`}</div>
      ${kinds.length ? `<table class="cx-table"><thead><tr><th>Вид</th><th>Ед.</th><th>Параметры</th><th></th></tr></thead><tbody>
        ${kinds.map((m) => `<tr><td>${esc(m.вид)}</td><td>${esc(m.ед)}</td><td>${esc(m.параметры)}</td>
          <td><button class="btn ghost" data-act="fl-mat-del" data-cat="${esc(c)}" data-kind="${esc(m.вид)}">✕</button></td></tr>`).join('')}</tbody></table>` : ''}
      <div class="cx-btn-row" style="margin-top:8px">
        <input class="input" data-fl-newkind="${esc(c)}" placeholder="новый вид, напр. габардин 220" style="max-width:240px">
        <input class="input cx-mini" data-fl-newunit="${esc(c)}" placeholder="ед." value="м">
        <input class="input" data-fl-newparams="${esc(c)}" placeholder="параметры: ширина, граммаж, состав" style="max-width:260px">
        <button class="btn" data-act="fl-mat-add" data-cat="${esc(c)}">+ Вид</button>
      </div></div>`;
  }).join('');
  return `<div class="cx-card"><div class="cx-card-h"><h3>Справочник материалов</h3><span class="cx-hint">категории и виды внутри них</span></div>
    <div class="cx-card-b">
      <div class="cx-btn-row">
        <input class="input" id="fl-newcat" placeholder="новая категория: рулон, карман, нитки…" style="max-width:280px">
        <button class="btn primary" data-act="fl-cat-add">+ Категория</button>
      </div>
      ${blocks || '<div class="cx-hint" style="margin-top:10px">Категорий пока нет</div>'}
    </div></div>`;
}

function rollsHtml() {
  const list = FL.supply.рулоны || [];
  return `<div class="cx-card"><div class="cx-card-h"><h3>Поступили рулоны</h3><span class="cx-hint">закройщик выбирает рулон из этого списка</span></div>
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
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-roll-add">Внести рулон</button></div>
      <div class="cx-scroll" style="margin-top:14px"><table class="cx-table">
        <thead><tr><th>Код</th><th>Дата</th><th>Материал</th><th>Цвет</th><th class="num">г/м²</th><th class="num">кг</th><th>Заказ</th><th>Поставщик</th><th>Внёс</th></tr></thead>
        <tbody>${list.map((r) => `<tr><td><b>${esc(r.код)}</b></td><td>${esc(r.дата)}</td><td>${esc(r.материал)}</td><td>${esc(r.цвет)}</td>
          <td class="num">${esc(r.граммы)}</td><td class="num">${esc(r.вес)}</td><td>${esc(r.заказ)}</td><td>${esc(r.поставщик)}</td><td>${esc(r.внёс)}</td></tr>`).join('')
          || '<tr><td colspan="9" class="cx-empty">Рулонов пока нет</td></tr>'}</tbody></table></div>
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
  if (!el || !['design', 'supply'].includes(ST.view)) return;
  ev.stopPropagation();
  const act = el.dataset.act;
  if (act === 'fl-design-open') return flOpenDesign(el.dataset.num);
  if (act === 'fl-supply-open') return flOpenSupply(el.dataset.num);
  if (act === 'fl-card-add') {
    FL.models[String(Math.max(0, ...flCards().map(Number)) + 1)] = [];
    return render();
  }
  if (act === 'fl-card-del') {
    const c = el.dataset.card;
    if (FL.rows.some((r) => r.карта === c) && !confirm(`Удалить карту ${c} со всем количеством?`)) return;
    delete FL.models[c]; FL.rows = FL.rows.filter((r) => r.карта !== c);
    return render();
  }
  if (act === 'fl-model-add') {
    const c = el.dataset.card;
    const inp = document.querySelector(`[data-fl-newmodel="${CSS.escape(c)}"]`);
    const m = ((inp && inp.value) || '').trim();
    if (!m) return toast('Впишите модель', 'err');
    if (!(FL.models[c] || []).includes(m)) FL.models[c].push(m);
    return render();
  }
  if (act === 'fl-model-del') {
    const { card: c, model: m } = el.dataset;
    if (FL.rows.some((r) => r.карта === c && r.модель === m) && !confirm(`Убрать ${m} из карты ${c}?`)) return;
    FL.models[c] = FL.models[c].filter((x) => x !== m);
    FL.rows = FL.rows.filter((r) => !(r.карта === c && r.модель === m));
    return render();
  }
  if (act === 'fl-fill') {
    const { card: c, model: m } = el.dataset;
    const o = flOrder();
    const { colors, sizes } = flGrid(o, c, m);
    colors.forEach((col) => sizes.forEach((z) => {
      if (!FL.rows.some((r) => r.карта === c && flKey(r.модель, r.цвет, r.размер) === flKey(m, col, z))) {
        const h = flHint(o, c, m, col, z);
        if (h) flSetCell(c, m, col, z, h);
      }
    }));
    return render();
  }
  if (act === 'fl-allcolors') { FL.allColors[el.dataset.id] = el.checked; return render(); }
  if (act === 'fl-design-save' || act === 'fl-design-done') {
    el.disabled = true; await flSaveDesign(act === 'fl-design-done'); el.disabled = false; return;
  }
  if (act === 'fl-supply-save' || act === 'fl-supply-done') {
    el.disabled = true; await flSaveSupply(act === 'fl-supply-done'); el.disabled = false; return;
  }
  if (act === 'fl-sub') { FL.supplyTab = el.dataset.tab; FL.num = ''; return render(); }
  if (act === 'fl-bom-pick') {
    FL.bomModel = el.dataset.model;
    FL.bomRows = ((FL.supply.спецификации || {})[FL.bomModel] || []).map((r) => ({ ...r }));
    if (!FL.bomRows.length) FL.bomRows.push({ категория: '', материал: '', цвет: '', норма: '', ед: 'м', параметры: '', по_размерам: {} });
    return render();
  }
  if (act === 'fl-bom-add') { FL.bomRows.push({ категория: '', материал: '', цвет: '', норма: '', ед: 'м', параметры: '', по_размерам: {} }); return render(); }
  if (act === 'fl-cat-add') {
    const cat = (($('#fl-newcat') || {}).value || '').trim();
    if (!cat) return toast('Впишите категорию', 'err');
    await flPost('/supply/material', { категория: cat }, `Категория «${cat}» добавлена`);
    return;
  }
  if (act === 'fl-mat-add') {
    const c = el.dataset.cat;
    const val = (a) => ((document.querySelector(`[${a}="${CSS.escape(c)}"]`) || {}).value || '').trim();
    if (!val('data-fl-newkind')) return toast('Впишите вид', 'err');
    await flPost('/supply/material', { категория: c, вид: val('data-fl-newkind'), ед: val('data-fl-newunit'), параметры: val('data-fl-newparams') }, 'Вид добавлен');
    return;
  }
  if (act === 'fl-mat-del') {
    const { cat, kind } = el.dataset;
    if (!confirm(kind ? `Удалить «${kind}» из «${cat}»?` : `Удалить категорию «${cat}»?`)) return;
    await flPost('/supply/material', { категория: cat, вид: kind, удалить: true }, 'Удалено');
    return;
  }
  if (act === 'fl-bom-del') { FL.bomRows.splice(Number(el.dataset.i), 1); return render(); }
  if (act === 'fl-bom-save') {
    await flPost('/supply/bom', { модель: FL.bomModel, строки: FL.bomRows }, `Спецификация ${FL.bomModel} сохранена`);
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
  const pick = (attr, list) => {
    const [i, f] = t.dataset[attr].split('|');
    list[Number(i)][f] = t.value;
  };
  if (t.dataset.flCell) {
    const [c, m, col, z] = t.dataset.flCell.split('|');
    flSetCell(c, m, col, z, Math.max(0, Math.floor(Number(t.value) || 0)));
    flRefreshDesign();
  }
  if (t.dataset.flChars) FL.chars[t.dataset.flChars] = t.value;
  if (t.dataset.flMat) pick('flMat', FL.rows);
  if (t.dataset.flBom) pick('flBom', FL.bomRows);
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
  if (ST.view !== 'supply' || !t.dataset.flBom || t.tagName !== 'SELECT') return;
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
