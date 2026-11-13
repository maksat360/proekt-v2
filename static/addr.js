/* Склад → Адрес: ячейки P (внутри) и N (снаружи), коробки K, мешки M. Одно поле сканера.
   Коробка → ячейка N: переставить целиком (тихо). Коробка → ячейка P: вскрыть, всё в ячейку.
   Мешок: показать, что в нём; ввели, сколько взяли → скан ячейки. Место → товар → кол-во: положить. */
'use strict';

const AD = { first: null, product: null };
const AD_RX = /^(P\d*-\d{1,2}-\d{1,3}|N\d*-\d{1,2}-\d{1,3}|K-\d{1,6}|M-\d{1,6})$/;
// сканер в русской раскладке: З/Т/Л/Ь вместо P/N/K/M; похожие кириллические буквы
const AD_LAYOUT = { 'З': 'P', 'Т': 'N', 'Л': 'K', 'Ь': 'M', 'Р': 'P', 'Н': 'N', 'К': 'K', 'М': 'M' };
const adNorm = (v) => String(v || '').trim().toUpperCase().replace(/\s/g, '').replace(/[ЗТЛЬРНКМ]/g, (c) => AD_LAYOUT[c]);
const adCan = () => !!(STATE.caps && STATE.caps['wh.write']);
const adPost = (sub, body) => api('/api/wh/addr/' + sub, { method: 'POST', body: JSON.stringify(body) });
const adDownload = (qs) => { const a = document.createElement('a'); a.href = '/api/wh/addr/codes.xlsx?' + qs; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); };

async function whAddrPage(meta) {
  let sum = { стеллажи: [], коробки: {}, мешки: {} };
  let log = [];
  try { sum = (await api('/api/wh/addr/summary')).data; } catch (e) { /* таблиц ещё нет — покажем пусто */ }
  try { log = (await api('/api/wh/addr/journal')).data || []; } catch (e) { log = []; }
  AD.first = null; AD.product = null;
  setTimeout(adMount, 0);
  const can = adCan();
  const unit = (k, label, d) => `<div class="ad-unit"><b>${label}</b>
      <span class="hint">всего ${nf(d['всего'])}, с товаром ${nf(d['с_товаром'])}${d['последний'] ? ', последний ' + esc(d['последний']) : ''}</span>
      ${can ? `<div class="btn-row"><input class="input" type="number" min="1" max="500" id="ad-n-${k}" placeholder="сколько" style="max-width:110px">
        <button class="btn sm" data-ad-issue="${k}">Новые коды + Excel</button></div>` : ''}</div>`;
  return `
    <div class="card">
      <div class="card-h"><h3>Сканер</h3><div class="spacer"></div><span class="hint">ячейка, коробка, мешок или товар</span></div>
      <div class="card-b">
        <input class="input scan big" id="ad-scan" placeholder="сканируйте код" autocomplete="off" autocapitalize="characters">
        <div id="ad-ctx" class="ad-ctx"><span class="hint">Коробка → ячейка снаружи: переставить. Коробка → ячейка внутри: вскрыть.
          Мешок → сколько взяли → ячейка. Ячейка/коробка/мешок → товар → количество: положить. Товар без места — покажу, где лежит.</span></div>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Стеллажи</h3><div class="spacer"></div>
        <a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=P" download>Все ячейки внутри</a>
        <a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=N" download>Все снаружи</a></div>
      <div class="card-b tight">
        ${sum['стеллажи'].length ? `<table class="resp"><thead><tr><th>Стеллаж</th><th>Зона</th><th class="num">Этажей</th><th class="num">Ячеек</th><th class="num">Занято</th><th></th></tr></thead>
          <tbody>${sum['стеллажи'].map((g) => `<tr><td data-l="Стеллаж"><b>${esc(g['стеллаж'])}</b></td>
            <td data-l="Зона">${g['зона'] === 'P' ? 'внутри' : 'снаружи'}</td><td data-l="Этажей" class="num">${g['этажей']}</td>
            <td data-l="Ячеек" class="num">${g['ячеек']}</td><td data-l="Занято" class="num">${g['занято']}</td>
            <td><a class="btn sm" href="/api/wh/addr/codes.xlsx?тип=${g['зона']}&стеллаж=${g['номер']}" download>Excel</a></td></tr>`).join('')}</tbody></table>`
          : '<div class="empty">Стеллажей пока нет</div>'}
        ${can ? `<div class="btn-row ad-rack" style="padding:12px">
          <select class="input" id="ad-zone" style="max-width:150px"><option value="P">P — внутри</option><option value="N">N — снаружи</option></select>
          <input class="input" type="number" min="1" id="ad-rack" placeholder="№ стеллажа" style="max-width:120px">
          <input class="input" type="number" min="1" id="ad-floors" placeholder="этажей" style="max-width:100px">
          <input class="input" type="number" min="1" id="ad-cells" placeholder="ячеек на этаже" style="max-width:140px">
          <button class="btn primary sm" data-ad="rack">Создать + Excel</button></div>` : ''}
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Коробки и мешки</h3><div class="spacer"></div><span class="hint">коды только новые — старые повторно не печатаются</span></div>
      <div class="card-b">${unit('K', 'Коробки K', sum['коробки'] || {})}${unit('M', 'Мешки M', sum['мешки'] || {})}
        ${can ? `<div class="ad-unit"><b>Потеряли этикетку</b><span class="hint">товар и место перейдут на новый код, старый спишется</span>
          <div class="btn-row"><input class="input" id="ad-old" placeholder="старый код (вручную)" style="max-width:170px">
          <input class="input" id="ad-new" placeholder="новая этикетка" style="max-width:170px">
          <button class="btn sm" data-ad="relabel">Перенести</button></div></div>` : ''}
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Последние действия</h3></div>
      <div class="card-b tight">${log.length ? `<table class="resp"><thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Код</th><th>Детали</th></tr></thead>
        <tbody>${log.slice(0, 25).map((r) => `<tr><td data-l="Когда">${esc(String(r['когда']).slice(5, 16))}</td><td data-l="Кто">${esc(r['кто'])}</td>
          <td data-l="Что">${esc(r['что'])}</td><td data-l="Код"><b>${esc(r['код'])}</b></td>
          <td data-l="Детали" class="hint">${esc(Object.entries(r['данные'] || {}).map(([k, v]) => k + ': ' + v).join(', '))}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">Пока пусто</div>'}</div>
    </div>
    <details class="card"><summary class="card-h" style="cursor:pointer"><h3>Размещение из ожидания</h3>
      <span class="hint">только если приход был без «сразу на склад»</span></summary>${whAddr(meta)}</details>`;
}

const adItems = (list) => list.length
  ? `<table class="table ad-items"><tbody>${list.map((x) => `<tr><td>${esc(x['наименование'])}</td><td class="num"><b>${nf(x['количество'])}</b> шт</td></tr>`).join('')}</tbody></table>`
  : '<div class="hint">пусто</div>';

function adRender() {
  const box = $('#ad-ctx');
  if (!box) return;
  const f = AD.first;
  if (!f) { box.innerHTML = '<span class="hint">Готов: сканируйте код</span>'; return; }
  let body = '';
  if (f['тип'] === 'M' || f['тип'] === 'P') {
    // мешок (и ячейка): сколько взять — затем скан ячейки, куда кладём
    body = f['содержимое'].length ? `<table class="table ad-items"><thead><tr><th>Товар</th><th class="num">Есть</th><th class="num">Взял</th></tr></thead><tbody>
      ${f['содержимое'].map((x, i) => `<tr><td>${esc(x['наименование'])}</td><td class="num">${nf(x['количество'])}</td>
        <td class="num"><input class="input ad-take" type="number" min="0" max="${x['количество']}" data-i="${i}" style="width:80px" inputmode="numeric"></td></tr>`).join('')}
      </tbody></table><div class="hint">${f['тип'] === 'M' ? 'Введите, сколько взяли, и сканируйте ячейку' : 'Чтобы переложить — введите количество и сканируйте, куда'}. Товар — положить сюда.</div>`
      : '<div class="hint">Пусто. Сканируйте товар — положить сюда.</div>';
  } else if (f['тип'] === 'K') {
    body = `${f['где'] ? `<div class="hint">стоит в <b>${esc(f['где'])}</b></div>` : ''}${adItems(f['содержимое'])}
      <div class="hint">Сканируйте ячейку (или товар — добавить в коробку)</div>`;
  } else if (f['тип'] === 'N') {
    body = f['коробки'].length ? `<div class="hint">Коробки: ${f['коробки'].map((b) => `<b>${esc(b['код'])}</b> (${nf(b['штук'])} шт)`).join(', ')}</div>`
      : '<div class="hint">Коробок нет</div>';
    body += '<div class="hint">Сканируйте коробку — поставить сюда</div>';
  }
  const pr = AD.product ? `<div class="ad-put"><b>${esc(AD.product)}</b> → ${esc(f['код'])}
      <input class="input scan" id="ad-qty" type="number" min="1" value="1" inputmode="numeric" style="width:90px">
      <button class="btn primary sm" data-ad="put">Положить</button></div>` : '';
  box.innerHTML = `<div class="ad-head"><b class="ad-code">${esc(f['код'])}</b> <span class="pill grey">${esc(f['тип_название'])}</span>
    <div class="spacer"></div><button class="btn ghost sm" data-ad="reset">Сброс (Esc)</button></div>${body}${pr}`;
  if (AD.product) { const q = $('#ad-qty'); q.focus(); q.select(); }
}

function adFocus() { const s = $('#ad-scan'); if (s) { s.value = ''; s.focus(); } }
function adReset() { AD.first = null; AD.product = null; adRender(); adFocus(); }
async function adRefresh() { if (AD.first) AD.first = (await api('/api/wh/addr/state?код=' + encodeURIComponent(AD.first['код']))).data; }

async function adScan(raw) {
  const v = adNorm(raw);
  if (!v) return;
  if (AD_RX.test(v)) {
    const st = (await api('/api/wh/addr/state?код=' + encodeURIComponent(v))).data;
    if (st['статус'] !== 'active') throw new Error(`Код ${v} списан${st['заменён_на'] ? ' — теперь ' + st['заменён_на'] : ''}`);
    const f = AD.first;
    AD.product = null;
    if (f && adCan()) {
      const [a, b] = [f['тип'], st['тип']];
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
    adRender(); adFocus();
    return;
  }
  // не код — товар
  const res = await api('/api/wh/find?q=' + encodeURIComponent(String(raw).trim()));
  const it = res.data;
  if (!it) throw new Error('Товар не найден: ' + raw);
  const name = it['наименование'];
  if (AD.first && 'PKM'.includes(AD.first['тип']) && adCan()) { AD.product = name; adRender(); return; }
  const w = (await api('/api/wh/addr/where?товар=' + encodeURIComponent(name))).data;
  AD.first = null;
  $('#ad-ctx').innerHTML = `<div class="ad-head"><b>${esc(name)}</b><div class="spacer"></div><span class="hint">остаток ${nf(w['остаток'])} шт</span></div>
    ${w['адреса'].length ? `<table class="table ad-items"><tbody>${w['адреса'].map((a) => `<tr><td><b>${esc(a['код'])}</b>${a['где'] ? ' <span class="hint">в ' + esc(a['где']) + '</span>' : ''}</td>
      <td class="num">${nf(a['количество'])} шт</td></tr>`).join('')}</tbody></table>` : ''}
    <div class="hint">без адреса: <b>${nf(w['без_адреса'])}</b> шт</div>`;
  adFocus();
}

async function adBox(box, cell) {
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
    adScan(v).catch((err) => { toast(err.message, 'err'); adFocus(); });
  });
  if (AD.bound) return;  // общие обработчики — один раз на документ
  AD.bound = true;
  const page = document;
  page.addEventListener('keydown', (e) => {
    if (e.target.id === 'ad-qty' && e.key === 'Enter') { e.preventDefault(); adPut(); }
    if (e.key === 'Escape' && e.target.closest('#ad-ctx')) adReset();
  });
  page.addEventListener('click', (e) => {
    const b = e.target.closest('[data-ad],[data-ad-issue]');
    if (!b) return;
    const act = b.dataset.ad;
    const run = (p) => p.catch((err) => toast(err.message, 'err'));
    if (act === 'reset') adReset();
    if (act === 'put') run(adPut());
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
  const q = num(($('#ad-qty') || {}).value);
  if (!AD.first || !AD.product) return;
  try {
    await adPost('put', { 'код': AD.first['код'], 'наименование': AD.product, 'количество': q });
    toast(`${AD.first['код']}: + ${nf(q)} шт`, 'ok');
    AD.product = null;
    await adRefresh();
    adRender(); adFocus();
  } catch (e) { toast(e.message, 'err'); }
}
