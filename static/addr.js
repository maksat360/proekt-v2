/* Склад → Адрес: ячейки P (внутри) и N (снаружи), коробки K, мешки M. Одно поле сканера.
   Коробка → ячейка N: переставить целиком (тихо). Коробка → ячейка P: вскрыть, всё в ячейку.
   Мешок: показать, что в нём; ввели, сколько взяли → скан ячейки. Место → товар → кол-во: положить. */
'use strict';

// first — где «стоим» (ячейка/коробка/мешок); product+qty — товар, который кладём; confirm — ждём «вскрыть?»
const AD = { first: null, product: null, qty: 1, confirm: null };
const adBuzz = () => { try { navigator.vibrate && navigator.vibrate(30); } catch (e) { /* нет вибро */ } };
const AD_RX = /^(P\d*-\d{1,2}-\d{1,3}|N\d*-\d{1,2}-\d{1,3}|K-\d{1,6}|M-\d{1,6})$/;
// сканер в русской раскладке: З/Т/Л/Ь вместо P/N/K/M; похожие кириллические буквы
const AD_LAYOUT = { 'З': 'P', 'Т': 'N', 'Л': 'K', 'Ь': 'M', 'Р': 'P', 'Н': 'N', 'К': 'K', 'М': 'M' };
const adNorm = (v) => String(v || '').trim().toUpperCase().replace(/\s/g, '').replace(/[ЗТЛЬРНКМ]/g, (c) => AD_LAYOUT[c]);
const adCan = () => !!(STATE.caps && STATE.caps['wh.write']);
const adPost = (sub, body) => api('/api/wh/addr/' + sub, { method: 'POST', body: JSON.stringify(body) });
const adDownload = (qs) => { const a = document.createElement('a'); a.href = '/api/wh/addr/codes.xlsx?' + qs; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); };

// предупреждения по коробкам: вскрытые при сборке (положить внутрь) и заполненные, но не поставленные в ячейку
async function adOpenedHtml(link) {
  const get = (sub) => api('/api/wh/addr/' + sub).then((r) => r.data || []).catch(() => []);
  const [list, loose] = await Promise.all([get('opened'), get('unplaced')]);
  const where = link ? '<a href="#/wh/addr">Адрес</a>: ' : '';
  const short = (n) => n.split('/').slice(1).join(' ');
  return (list.length ? `<div class="notice ad-opened"><b>Вскрытые коробки — положите во внутреннюю ячейку</b>
    <div class="btn-row" style="margin:8px 0 4px">${list.map((o) => `<span class="pill orange">${esc(o['код'])}${o['где'] ? ' в ' + esc(o['где']) : ''} · ${nf(o['штук'])} шт</span>`).join('')}</div>
    <div class="hint">${where}сканируйте коробку, потом ячейку P — остаток перейдёт в ячейку, коробка освободится.</div></div>` : '')
    + (loose.length ? `<div class="notice ad-opened"><b>Коробки не поставлены в ячейку: ${nf(loose.length)}</b>
    <div class="btn-row" style="margin:8px 0 4px">${loose.map((o) => `<span class="pill orange" title="${esc(o['товары'].join(', '))}">${esc(o['код'])} · ${esc(o['товары'].length === 1 ? short(o['товары'][0]) : o['товары'].length + ' товара')} · ${nf(o['штук'])} шт</span>`).join('')}</div>
    <div class="hint">${where}сканируйте коробку, потом наружную ячейку N — иначе на сборке её не найти по адресу.</div></div>` : '');
}

async function whAddrPage(meta) {
  let sum = { стеллажи: [], коробки: {}, мешки: {} };
  let log = [];
  const view = AD.view || '';  // '' — сканер; racks / units / log / wait — служебное, за кнопками
  try { sum = (await api('/api/wh/addr/summary')).data; } catch (e) { /* таблиц ещё нет — покажем пусто */ }
  if (view === 'log') { try { log = (await api('/api/wh/addr/journal')).data || []; } catch (e) { log = []; } }
  const opened = view ? '' : await adOpenedHtml(false);  // все запросы — до таймера: иначе adMount сработает раньше, чем появится поле сканера
  AD.first = null; AD.product = null;
  if (!view) setTimeout(adMount, 0);
  const can = adCan();
  const box = sum['коробки'] || {};
  const bag = sum['мешки'] || {};
  const back = (title, hint) => `<div class="card-h"><button class="btn sm" data-ad-view="">← Сканер</button>
      <h3>${title}</h3><div class="spacer"></div>${hint ? `<span class="hint">${hint}</span>` : ''}</div>`;

  if (!view) {
    const tile = (v, title, sub) => `<button type="button" class="ad-tile" data-ad-view="${v}"><b>${title}</b><span>${sub}</span></button>`;
    return `${opened}
    <div class="card ad-main">
      <div class="card-b">
        <input class="input scan big" id="ad-scan" placeholder="сканируйте код" autocomplete="off" autocapitalize="characters">
        <div id="ad-ctx" class="ad-ctx"><span class="hint">Готов: сканируйте код</span></div>
        <div class="ad-how">
          <span><b>Место → товар</b> → кол-во — положить</span>
          <span><b>Коробка → ячейка N</b> — поставить</span>
          <span><b>Коробка → ячейка P</b> — вскрыть</span>
          <span><b>Мешок</b> → сколько взяли → ячейка</span>
        </div>
      </div>
    </div>
    <div class="ad-tiles">
      ${tile('racks', 'Стеллажи и ячейки', `${nf(sum['стеллажи'].length)} стеллажей · печать кодов`)}
      ${tile('units', 'Коробки и мешки', `коробок с товаром ${nf(box['с_товаром'] || 0)} из ${nf(box['всего'] || 0)} · мешков ${nf(bag['с_товаром'] || 0)}`)}
      ${tile('log', 'История', 'последние действия с адресами')}
      ${tile('wait', 'Размещение из ожидания', 'если приход был не «сразу на склад»')}
    </div>`;
  }

  if (view === 'racks') return `
    <div class="card">
      ${back('Стеллажи и ячейки', '')}
      <div class="card-b tight">
        <div class="btn-row" style="padding:12px 12px 0">
          <a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=P" download>Все ячейки внутри</a>
          <a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=N" download>Все снаружи</a></div>
        ${sum['стеллажи'].length ? `<table class="resp"><thead><tr><th>Стеллаж</th><th>Зона</th><th class="num">Этажей</th><th class="num">Ячеек</th><th class="num">Занято</th><th></th></tr></thead>
          <tbody>${sum['стеллажи'].map((g) => `<tr><td data-l="Стеллаж"><b>${esc(g['стеллаж'])}</b></td>
            <td data-l="Зона">${g['зона'] === 'P' ? 'внутри' : 'снаружи'}</td><td data-l="Этажей" class="num">${g['этажей']}</td>
            <td data-l="Ячеек" class="num">${g['ячеек']}</td><td data-l="Занято" class="num">${g['занято']}</td>
            <td><a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=${g['зона']}&стеллаж=${g['номер']}" download>Excel</a></td></tr>`).join('')}</tbody></table>`
          : '<div class="empty">Стеллажей пока нет</div>'}
        ${can ? `<div class="ad-unit" style="padding:12px"><b>Новый стеллаж</b>
          <div class="btn-row ad-rack">
          <select class="input" id="ad-zone" style="max-width:150px"><option value="P">P — внутри</option><option value="N">N — снаружи</option></select>
          <input class="input" type="number" min="1" id="ad-rack" placeholder="№ стеллажа" style="max-width:120px">
          <input class="input" type="number" min="1" id="ad-floors" placeholder="этажей" style="max-width:100px">
          <input class="input" type="number" min="1" id="ad-cells" placeholder="ячеек на этаже" style="max-width:140px">
          <button class="btn primary sm" data-ad="rack">Создать + Excel</button></div></div>` : ''}
      </div>
    </div>`;

  if (view === 'units') {
    const unit = (k, label, d) => `<div class="ad-unit"><b>${label}</b>
      <span class="hint">всего ${nf(d['всего'])}, с товаром ${nf(d['с_товаром'])}${d['последний'] ? ', последний ' + esc(d['последний']) : ''}</span>
      ${can ? `<div class="btn-row"><input class="input" type="number" min="1" max="500" id="ad-n-${k}" placeholder="сколько" style="max-width:110px">
        <button class="btn sm" data-ad-issue="${k}">Новые коды + Excel</button></div>` : ''}</div>`;
    return `
    <div class="card">
      ${back('Коробки и мешки', 'коды только новые — старые повторно не печатаются')}
      <div class="card-b">${unit('K', 'Коробки K', box)}${unit('M', 'Мешки M', bag)}
        ${can ? `<div class="ad-unit"><b>Потеряли этикетку</b><span class="hint">товар и место перейдут на новый код, старый спишется</span>
          <div class="btn-row"><input class="input" id="ad-old" placeholder="старый код (вручную)" style="max-width:170px">
          <input class="input" id="ad-new" placeholder="новая этикетка" style="max-width:170px">
          <button class="btn sm" data-ad="relabel">Перенести</button></div></div>` : ''}
      </div>
    </div>`;
  }

  if (view === 'log') return `
    <div class="card">
      ${back('История', 'последние 50 действий')}
      <div class="card-b tight">${log.length ? `<table class="resp"><thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Код</th><th>Детали</th></tr></thead>
        <tbody>${log.slice(0, 50).map((r) => `<tr><td data-l="Когда">${esc(String(r['когда']).slice(5, 16))}</td><td data-l="Кто">${esc(r['кто'])}</td>
          <td data-l="Что">${esc(r['что'])}</td><td data-l="Код"><b>${esc(r['код'])}</b></td>
          <td data-l="Детали" class="hint">${esc(Object.entries(r['данные'] || {}).map(([k, v]) => k + ': ' + v).join(', '))}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">Пока пусто</div>'}</div>
    </div>`;

  return `<div class="card">${back('Размещение из ожидания', 'только если приход был без «сразу на склад»')}</div>${whAddr(meta)}`;
}

const adItems = (list) => list.length
  ? `<table class="table ad-items"><tbody>${list.map((x) => `<tr><td>${esc(x['наименование'])}</td><td class="num"><b>${nf(x['количество'])}</b> шт</td></tr>`).join('')}</tbody></table>`
  : '<div class="hint">пусто</div>';

function adRender() {
  const box = $('#ad-ctx');
  if (!box) return;
  const f = AD.first;
  const main = $('.ad-main');
  if (main) main.classList.toggle('ad-in', !!f);
  const scan = $('#ad-scan');
  if (scan) scan.placeholder = !f ? 'сканируйте код' : AD.product ? 'тот же товар = +1' : 'сканируйте товар' + (f['тип'] === 'K' ? ' или ячейку' : '');
  if (!f) { box.innerHTML = '<span class="hint">Готов: сканируйте ячейку, коробку, мешок или товар</span>'; return; }
  if (AD.confirm) {
    const c = AD.confirm;
    const n = f['содержимое'].reduce((a, x) => a + num(x['количество']), 0);
    box.innerHTML = `<div class="ad-where warn"><span>Вскрыть коробку?</span><b>${esc(c.box)} → ${esc(c.cell)}</b></div>
      <div class="hint" style="margin:6px 0 10px">Всё содержимое коробки (${nf(n)} шт) перейдёт во внутреннюю ячейку ${esc(c.cell)}, коробка освободится.</div>
      <div class="btn-row"><button class="btn primary big" data-ad="open-yes">Вскрыть</button><button class="btn big" data-ad="open-no">Отмена</button></div>
      <div class="hint" style="margin-top:8px">Или отсканируйте ${esc(c.cell)} ещё раз — тоже вскрыть.</div>`;
    return;
  }
  const where = { P: 'Вы в ячейке', N: 'Наружная ячейка', K: 'Открыта коробка', M: 'Открыт мешок' }[f['тип']] || f['тип_название'];
  const next = { P: 'Сканируйте товар — положить сюда', N: 'Сканируйте коробку — поставить сюда',
    K: 'Сканируйте товар — положить в коробку, или ячейку — поставить коробку', M: 'Сканируйте товар — положить в мешок' }[f['тип']] || '';
  let body = '';
  if (f['тип'] === 'M' || f['тип'] === 'P') {
    // мешок (и ячейка): сколько взять — затем скан ячейки, куда кладём
    body = f['содержимое'].length ? `<table class="table ad-items"><thead><tr><th>Товар</th><th class="num">Есть</th><th class="num">Взял</th></tr></thead><tbody>
      ${f['содержимое'].map((x, i) => `<tr><td>${esc(x['наименование'])}</td><td class="num">${nf(x['количество'])}</td>
        <td class="num"><input class="input ad-take" type="number" min="0" max="${x['количество']}" data-i="${i}" style="width:80px" inputmode="numeric"></td></tr>`).join('')}
      </tbody></table><div class="hint">${f['тип'] === 'M' ? 'Введите, сколько взяли, и сканируйте ячейку' : 'Чтобы переложить — введите количество и сканируйте, куда'}. Товар — положить сюда.</div>
      ${adCan() ? '<div class="btn-row" style="margin-top:6px"><button class="btn sm" data-ad="out">Убрать в размещение</button><span class="hint">ошиблись при скане — вписанное количество снова будет без адреса</span></div>' : ''}`
      : '<div class="hint">Пусто. Сканируйте товар — положить сюда.</div>';
  } else if (f['тип'] === 'K') {
    // коробка: количество можно исправить (ошиблись при раскладке) — разница уходит/берётся «без адреса»
    body = `${f['где'] ? `<div class="hint">стоит в <b>${esc(f['где'])}</b></div>` : ''}${adCan() && f['содержимое'].length
      ? `<table class="table ad-items"><tbody>${f['содержимое'].map((x, i) => `<tr><td>${esc(x['наименование'])}</td>
          <td class="num"><input class="input ad-set" type="number" min="0" value="${x['количество']}" data-i="${i}" style="width:80px" inputmode="numeric"> шт</td></tr>`).join('')}
        </tbody></table><div class="btn-row" style="margin-top:6px"><button class="btn sm" data-ad="set">Сохранить количество</button>
        <span class="hint">меньше — лишнее снова без адреса; больше — возьмётся из без адреса</span></div>`
      : adItems(f['содержимое'])}
      `;
  } else if (f['тип'] === 'N') {
    body = f['коробки'].length ? `<div class="hint">Коробки: ${f['коробки'].map((b) => `<b>${esc(b['код'])}</b> (${nf(b['штук'])} шт)`).join(', ')}</div>`
      : '<div class="hint">Коробок нет</div>';
  }
  const pr = AD.product ? `<div class="ad-put">
      <div class="ad-put-name">${esc(AD.product)}</div>
      <div class="ad-qty-row"><button class="btn big" data-ad="minus" aria-label="меньше">−</button>
        <input class="input" id="ad-qty" type="number" min="1" value="${AD.qty}" inputmode="numeric">
        <button class="btn big" data-ad="plus" aria-label="больше">+</button></div>
      <button class="btn primary big" data-ad="put">Положить ${nf(AD.qty)} шт в ${esc(f['код'])}</button>
      <div class="hint">Тот же товар сканером — ещё +1. Другой товар — этот положится сам. Enter в поле сканера — положить.</div></div>` : '';
  box.innerHTML = `<div class="ad-where"><span>${esc(where)}</span><b>${esc(f['код'])}</b>
      <button class="btn ghost sm" data-ad="reset">Выйти (Esc)</button></div>
    ${!AD.product && next ? `<div class="ad-next">${esc(next)}</div>` : ''}${pr}${body}`;
}

function adFocus() { const s = $('#ad-scan'); if (s) { s.value = ''; s.focus(); } }
function adReset() { AD.first = null; AD.product = null; AD.qty = 1; AD.confirm = null; adRender(); adFocus(); }
async function adRefresh() { if (AD.first) AD.first = (await api('/api/wh/addr/state?код=' + encodeURIComponent(AD.first['код']))).data; }

async function adScan(raw) {
  const v = adNorm(raw);
  if (!v) return;
  if (AD_RX.test(v)) {
    if (AD.confirm) {  // ждали «вскрыть?»: та же ячейка — да, другой код — отмена и обычный скан
      const c = AD.confirm;
      AD.confirm = null;
      if (v === c.cell) return adBox(c.box, c.cell);
    }
    const st = (await api('/api/wh/addr/state?код=' + encodeURIComponent(v))).data;
    if (st['статус'] !== 'active') throw new Error(`Код ${v} списан${st['заменён_на'] ? ' — теперь ' + st['заменён_на'] : ''}`);
    if (AD.product) await adPut();  // товар не потеряется при скане следующего места
    const f = AD.first;
    AD.product = null;
    if (f && adCan()) {
      const [a, b] = [f['тип'], st['тип']];
      if (a === 'K' && b === 'P' && f['содержимое'].length) {  // вскрытие — только после подтверждения
        AD.confirm = { box: f['код'], cell: v };
        adBuzz(); adRender(); adFocus();
        return;
      }
      if (a === 'K' && 'PN'.includes(b)) return adBox(f['код'], v);
      if (a === 'N' && b === 'K') return adBox(v, f['код']);
      const takes = $$('.ad-take').map((inp) => ({ 'наименование': f['содержимое'][Number(inp.dataset.i)]['наименование'], 'количество': num(inp.value) }))
        .filter((x) => x['количество'] > 0);
      if (takes.length && 'PKM'.includes(b)) {
        const r = await adPost('move', { 'откуда': f['код'], 'куда': v, 'позиции': takes });
        toast(`${r['из']} → ${r['в']}: ${nf(r['штук'])} шт`, 'ok');
        AD.first = st;
        await adRefresh();
        adRender(); adFocus();
        return;
      }
    }
    AD.first = st;
    adBuzz(); adRender(); adFocus();
    return;
  }
  // не код — товар
  const res = await api('/api/wh/find?q=' + encodeURIComponent(String(raw).trim()));
  const it = res.data;
  if (!it) throw new Error('Товар не найден: ' + raw);
  const name = it['наименование'];
  if (AD.first && 'PKM'.includes(AD.first['тип']) && adCan()) {
    if (AD.confirm) { AD.confirm = null; }
    if (AD.product === name) { AD.qty += 1; adBuzz(); adRender(); adFocus(); return; }  // тот же товар — +1
    if (AD.product) await adPut();  // другой товар — предыдущий кладём
    AD.product = name; AD.qty = 1;
    adBuzz(); adRender(); adFocus();
    return;
  }
  const w = (await api('/api/wh/addr/where?товар=' + encodeURIComponent(name))).data;
  AD.first = null;
  $('#ad-ctx').innerHTML = `<div class="ad-head"><b>${esc(name)}</b><div class="spacer"></div><span class="hint">остаток ${nf(w['остаток'])} шт</span></div>
    ${w['адреса'].length ? `<table class="table ad-items"><tbody>${w['адреса'].map((a) => `<tr><td><b>${esc(a['код'])}</b>${a['где'] ? ' <span class="hint">в ' + esc(a['где']) + '</span>' : ''}</td>
      <td class="num">${nf(a['количество'])} шт</td></tr>`).join('')}</tbody></table>` : ''}
    <div class="hint">без адреса: <b>${nf(w['без_адреса'])}</b> шт</div>`;
  adFocus();
}

async function adBox(box, cell) {
  AD.confirm = null;
  const r = await adPost('box', { 'коробка': box, 'ячейка': cell });
  toast(r['действие'] === 'вскрыта' ? `${r['коробка']} вскрыта → ${r['ячейка']}: ${nf(r['штук'])} шт` : `${r['коробка']} → ${r['ячейка']}`, 'ok');
  AD.first = null; AD.product = null;
  adRender(); adFocus();
}

function adMount() {
  const s = $('#ad-scan');
  if (!s || s.dataset.bound) return;
  s.dataset.bound = '1';
  s.focus();
  s.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); adReset(); }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = s.value;
    s.value = '';
    if (!v.trim()) { if (AD.product) adPut(); return; }
    adScan(v).catch((err) => { toast(err.message, 'err'); adFocus(); });
  });
  if (AD.bound) return;  // общие обработчики — один раз на документ
  AD.bound = true;
  const page = document;
  page.addEventListener('input', (e) => {
    if (e.target.id !== 'ad-qty') return;
    AD.qty = Math.max(1, num(e.target.value) || 1);
    const b = $('[data-ad="put"]');
    if (b && AD.first) b.textContent = `Положить ${nf(AD.qty)} шт в ${AD.first['код']}`;
  });
  page.addEventListener('keydown', (e) => {
    if (e.target.id === 'ad-qty' && e.key === 'Enter') { e.preventDefault(); adPut(); }
    if (e.key === 'Escape' && e.target.closest('#ad-ctx')) adReset();
  });
  page.addEventListener('click', (e) => {
    const v = e.target.closest('[data-ad-view]');
    if (v) { AD.view = v.dataset.adView; redraw('wh', 'addr').then(() => window.scrollTo(0, 0)); return; }
    const b = e.target.closest('[data-ad],[data-ad-issue]');
    if (!b) return;
    const act = b.dataset.ad;
    const run = (p) => p.catch((err) => toast(err.message, 'err'));
    if (act === 'reset') adReset();
    if (act === 'plus' || act === 'minus') { AD.qty = Math.max(1, AD.qty + (act === 'plus' ? 1 : -1)); adRender(); adFocus(); }
    if (act === 'open-yes' && AD.confirm) run(adBox(AD.confirm.box, AD.confirm.cell));
    if (act === 'open-no') { AD.confirm = null; adRender(); adFocus(); }
    if (act === 'put') run(adPut());
    if (act === 'out') run((async () => {  // ошибочно положили — вернуть «без адреса»
      const f = AD.first;
      const items = [...document.querySelectorAll('.ad-take')]
        .map((inp) => ({ 'наименование': f['содержимое'][Number(inp.dataset.i)]['наименование'], 'количество': num(inp.value) }))
        .filter((x) => x['количество'] > 0);
      if (!items.length) { toast('Впишите в «Взял», сколько убрать', 'err'); return; }
      const r = await adPost('out', { 'код': f['код'], 'позиции': items });
      toast(`${r['код']}: убрано ${nf(r['штук'])} шт — снова в размещении`, 'ok');
      await adRefresh(); adRender(); adFocus();
    })());
    if (act === 'set') run((async () => {  // исправить количество в коробке
      const f = AD.first;
      const ch = $$('.ad-set').map((inp) => ({ x: f['содержимое'][Number(inp.dataset.i)], q: num(inp.value) }))
        .filter((c) => c.q !== c.x['количество']);
      if (!ch.length) { toast('Количество не изменилось', 'err'); return; }
      try {
        for (const c of ch) {
          await adPost('set', { 'код': f['код'], 'наименование': c.x['наименование'], 'количество': c.q });
          toast(`${f['код']}: ${c.x['наименование']} ${nf(c.x['количество'])} → ${nf(c.q)} шт`, 'ok');
        }
      } finally { await adRefresh(); adRender(); adFocus(); }
    })());
    if (act === 'rack') run((async () => {
      const zone = $('#ad-zone').value, rack = num($('#ad-rack').value);
      const r = await adPost('rack', { 'зона': zone, 'стеллаж': rack, 'этажей': num($('#ad-floors').value), 'ячеек': num($('#ad-cells').value) });
      toast(r['создано'] ? `Создано ${r['создано']} ячеек` : 'Такие ячейки уже есть — скачиваю Excel', 'ok');
      adDownload(`тип=${zone}&стеллаж=${rack}`);
      await go('wh', 'addr');
    })());
    if (b.dataset.adIssue) run((async () => {
      const k = b.dataset.adIssue;
      const r = await adPost('issue', { 'тип': k, 'количество': num($('#ad-n-' + k).value) });
      toast(`Выданы ${r['коды'][0]} … ${r['коды'][r['коды'].length - 1]}`, 'ok');
      adDownload(`тип=${k}&от=${r['коды'][0]}`);
      await go('wh', 'addr');
    })());
    if (act === 'relabel') run((async () => {
      const r = await adPost('relabel', { 'старый': adNorm($('#ad-old').value), 'новый': adNorm($('#ad-new').value) });
      toast(`${r['старый']} → ${r['новый']}${r['где'] ? ' (в ' + r['где'] + ')' : ''}`, 'ok');
      await go('wh', 'addr');
    })());
  });
}

async function adPut() {
  const q = Math.max(1, num(AD.qty) || 1);
  if (!AD.first || !AD.product) return;
  try {
    await adPost('put', { 'код': AD.first['код'], 'наименование': AD.product, 'количество': q });
    toast(`${AD.first['код']}: + ${nf(q)} шт · ${AD.product.split('/').slice(1).join(' ')}`, 'ok');
    adBuzz();
    AD.product = null; AD.qty = 1;
    await adRefresh();
    adRender(); adFocus();
  } catch (e) { toast(e.message, 'err'); }
}
