'use strict';

/* Модуль «Цех» · поток заказа: конструктор (производственная карта) → снабженец (сырьё) → технолог. */

const FL = { design: { очередь: [], история: {} }, supply: { очередь: [], спецификации: {}, рулоны: [], статусы: [] },
  num: '', rows: [], bomModel: '', bomRows: [], supplyTab: 'orders' };

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
const flCards = () => [...new Set(FL.rows.map((r) => String(r.карта || '1')))].sort((a, b) => a - b);

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

function designCardHtml(o) {
  const row = (r, i) => `<tr>
      <td><input class="input" data-fl-row="${i}|модель" value="${esc(r.модель)}" list="fl-models"></td>
      <td><input class="input" data-fl-row="${i}|цвет" value="${esc(r.цвет)}" list="fl-colors"></td>
      <td><input class="input cx-mini" data-fl-row="${i}|размер" value="${esc(r.размер)}"></td>
      <td><input class="input cx-mini" type="number" min="0" data-fl-row="${i}|итог" value="${esc(r.итог)}"></td>
      <td><input class="input" data-fl-row="${i}|характеристики" value="${esc(r.характеристики)}" placeholder="длина, посадка, детали кроя…"></td>
      <td><button class="btn ghost" data-act="fl-row-del" data-i="${i}" title="Убрать строку">✕</button></td>
    </tr>`;
  const cards = flCards().map((c) => {
    const items = FL.rows.map((r, i) => [r, i]).filter(([r]) => String(r.карта || '1') === c);
    return `<div class="cx-card" style="margin-top:12px"><div class="cx-card-h"><h3>Карта ${esc(c)}</h3>
        <span class="cx-hint"><b data-fl-card-total="${esc(c)}">${nf(items.reduce((s, [r]) => s + num(r.итог), 0))}</b> шт · станет отдельной партией</span></div>
      <div class="cx-card-b"><div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Модель</th><th>Цвет</th><th>Размер</th><th>Итог, шт</th><th>Доп. характеристики</th><th></th></tr></thead>
        <tbody>${items.map(([r, i]) => row(r, i)).join('')}</tbody></table></div>
        <div class="cx-btn-row" style="margin-top:10px"><button class="btn" data-act="fl-row-add" data-card="${esc(c)}">+ Строка</button></div>
      </div></div>`;
  }).join('');
  const total = FL.rows.reduce((s, r) => s + num(r.итог), 0);
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · производственные карты</h3>
      <span class="cx-hint">в заказе ${nf(o.заказано)} шт · в картах <b id="fl-total">${nf(total)}</b> шт</span></div>
    <div class="cx-card-b">
      ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
      <h4 style="margin:0 0 8px">Заказ начальника и карты</h4>
      <div class="cx-scroll" id="fl-dev">${flDevHtml(o)}</div>
      <datalist id="fl-models">${(ST.refs.модели || []).map((m) => `<option value="${esc(m.модель)}">${esc(m.название)}</option>`).join('')}</datalist>
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      ${cards}
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn" data-act="fl-card-add">+ Карта</button></div>
      <div class="cx-field" style="margin-top:12px"><label>Комментарий к изменению</label>
        <input class="input" id="fl-note" placeholder="Например: по 46 размеру не хватает ткани"></div>
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-design-save">Сохранить черновик</button>
        <button class="btn primary" data-act="fl-design-done">Утвердить и передать снабженцу</button>
      </div>
      <div class="cx-hint" style="margin-top:8px">Заказ — ориентир: итог может быть больше или меньше, артикулы, цвета и размеры — любые. Каждая карта у технолога становится отдельной партией. Все изменения записываются в историю.</div>
      <h4 style="margin:18px 0 8px">История изменений</h4>
      ${flHistoryHtml((FL.design.история || {})[o.номер])}
    </div></div>`;
}

function flOpenDesign(numStr) {
  const o = (FL.design.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  FL.rows = (o.карта || []).map((r) => ({ ...r }));
  render();
}

async function flSaveDesign(done) {
  const body = { номер: FL.num, готово: done, комментарий: ($('#fl-note') || {}).value || '', позиции: FL.rows };
  if (done && !confirm('Утвердить карту и передать заказ снабженцу? После этого карту не поменять.')) return;
  try {
    const res = await api(`${API}/design`, { method: 'POST', body: JSON.stringify(body) });
    await loadDesign();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenDesign(FL.num);
    render();
    toast(done ? `Заказ №${res.номер} передан снабженцу · ${nf(res.штук)} шт` : 'Черновик карты сохранён', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// ------------------------------------------------------------- снабжение
function supplyHtml() {
  const t = FL.supplyTab;
  const sub = [['orders', `Заказы ${nf((FL.supply.очередь || []).length)}`], ['bom', 'Спецификации'], ['rolls', 'Рулоны']];
  return `<div class="cx-hero compact"><div><h1>Снабжение</h1>
      <div class="cx-sub">Сырьё по спецификациям артикулов, поступившие рулоны. Когда сырьё готово — заказ уходит технологу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'bom' ? bomHtml() : t === 'rolls' ? rollsHtml() : supplyOrdersHtml()}`;
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

function bomHtml() {
  const all = FL.supply.спецификации || {};
  const models = (ST.refs.модели || []).map((m) => m.модель);
  Object.keys(all).forEach((m) => { if (!models.includes(m)) models.push(m); });
  const chips = models.map((m) => `<button class="rt-chip ${m === FL.bomModel ? 'on' : ''}" data-act="fl-bom-pick" data-model="${esc(m)}">${esc(m)}${all[m] ? ` · ${all[m].length}` : ''}</button>`).join('');
  const rows = FL.bomRows.map((r, i) => `<tr>
      <td><input class="input" data-fl-bom="${i}|материал" value="${esc(r.материал)}" placeholder="ткань, нитки, молния…"></td>
      <td><input class="input" data-fl-bom="${i}|цвет" value="${esc(r.цвет)}" placeholder="пусто = в цвет изделия" list="fl-colors"></td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-bom="${i}|норма" value="${esc(r.норма)}"></td>
      <td><input class="input cx-mini" data-fl-bom="${i}|ед" value="${esc(r.ед || 'м')}"></td>
      <td><input class="input" data-fl-bom="${i}|параметры" value="${esc(r.параметры)}" placeholder="ширина, состав…"></td>
      <td><button class="btn ghost" data-act="fl-bom-del" data-i="${i}">✕</button></td></tr>`).join('');
  return `<div class="cx-card"><div class="cx-card-h"><h3>Спецификация материалов (BOM) по артикулу</h3></div>
    <div class="cx-card-b">
      <div class="cc-wait">${chips || '<span class="cx-hint">Справочник моделей пуст</span>'}</div>
      ${FL.bomModel ? `
        <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
        <div class="cx-scroll" style="margin-top:12px"><table class="cx-table">
          <thead><tr><th>Сырьё / материал</th><th>Цвет</th><th>Норма на 1 шт</th><th>Ед.</th><th>Доп. параметры</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <div class="cx-btn-row" style="margin-top:10px">
          <button class="btn" data-act="fl-bom-add">+ Материал</button>
          <button class="btn primary" data-act="fl-bom-save">Сохранить спецификацию ${esc(FL.bomModel)}</button>
        </div>` : '<div class="cx-hint" style="margin-top:10px">Выберите артикул</div>'}
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
  if (act === 'fl-row-add') {
    const card = el.dataset.card || '1';
    const last = FL.rows.filter((r) => String(r.карта || '1') === card).pop() || {};
    const at = FL.rows.lastIndexOf(last) + 1 || FL.rows.length;
    FL.rows.splice(at, 0, { карта: card, модель: last.модель || '', цвет: last.цвет || '', размер: '', итог: 0, характеристики: '' });
    return render();
  }
  if (act === 'fl-card-add') {
    const next = String(Math.max(0, ...flCards().map(Number)) + 1);
    FL.rows.push({ карта: next, модель: '', цвет: '', размер: '', итог: 0, характеристики: '' });
    return render();
  }
  if (act === 'fl-row-del') { FL.rows.splice(Number(el.dataset.i), 1); return render(); }
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
    if (!FL.bomRows.length) FL.bomRows.push({ материал: '', цвет: '', норма: '', ед: 'м', параметры: '' });
    return render();
  }
  if (act === 'fl-bom-add') { FL.bomRows.push({ материал: '', цвет: '', норма: '', ед: 'м', параметры: '' }); return render(); }
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
  if (t.dataset.flRow) {
    pick('flRow', FL.rows);
    const total = document.getElementById('fl-total');
    if (total) total.textContent = nf(FL.rows.reduce((s, r) => s + num(r.итог), 0));
    document.querySelectorAll('[data-fl-card-total]').forEach((b) => {
      b.textContent = nf(FL.rows.filter((r) => String(r.карта || '1') === b.dataset.flCardTotal).reduce((s, r) => s + num(r.итог), 0));
    });
    const o = (FL.design.очередь || []).find((x) => x.номер === FL.num);
    const dev = document.getElementById('fl-dev');
    if (o && dev) dev.innerHTML = flDevHtml(o);
  }
  if (t.dataset.flMat) pick('flMat', FL.rows);
  if (t.dataset.flBom) pick('flBom', FL.bomRows);
});
