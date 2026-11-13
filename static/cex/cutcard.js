'use strict';

/* Модуль «Цех» · экран закройщика: номер партии → карта кроя → разделы. Рулоны ведёт снабженец. */

const CC = { num: '', len: '', pattern: '', comment: '', secs: [], back: [], open: false };

function ccParty() { return (ST.cut.партии || []).find((p) => p.номер === CC.num); }

function ccReset(keepNum) {
  const n = keepNum ? CC.num : '';
  Object.assign(CC, { num: n, len: '', pattern: '', comment: '', secs: [{}], back: [], open: false });
}

function ccColors(p) { return [...new Set(p.строки.map((r) => r.цвет))]; }
function ccSizes(p) {
  const s = [...new Set(p.строки.map((r) => r.размер))];
  return s.sort((a, b) => String(a).localeCompare(String(b), 'ru', { numeric: true }));
}
function ccLeft(p) {
  const left = {};
  p.строки.forEach((r) => { left[`${r.цвет}|${r.размер}`] = r.остаток; });
  return left;
}
function ccUsed() {
  const used = {};
  CC.secs.forEach((g) => Object.entries(g).forEach(([k, v]) => { used[k] = (used[k] || 0) + (Number(v) || 0); }));
  return used;
}
function ccTotal() { return Object.values(ccUsed()).reduce((a, b) => a + b, 0); }

function cutCardHtml() {
  const list = (ST.cut.партии || []);
  const waiting = list.filter((p) => p.остаток > 0);
  const p = ccParty();
  const head = `<div class="cx-hero compact">
      <div><h1>Крой</h1><div class="cx-sub">Номер партии → карта кроя → разделы</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div>
    </div>`;
  const pickBlock = `
    <div class="cx-card"><div class="cx-card-b" style="padding-top:18px">
      <div class="cc-num">
        <input class="input" id="cc-num" inputmode="numeric" placeholder="Номер партии" value="${esc(CC.num)}" autocomplete="off">
        <button class="btn primary" data-act="cc-open">Открыть</button>
      </div>
      ${waiting.length ? `<div class="cc-wait">Ждут кроя: ${waiting.map((x) => `<button class="rt-chip ${x.номер === CC.num ? 'on' : ''}" data-act="cc-pick" data-num="${esc(x.номер)}">№${esc(x.номер)} · ${esc(x.модель)} · ${(x.ждёт_шагов || []).length ? '⏳ шаги заказа' : 'осталось ' + nf(x.остаток)}</button>`).join('')}</div>`
        : '<div class="cx-hint" style="margin-top:10px">Партий, ожидающих крой, нет</div>'}
    </div></div>`;
  if (!p) return head + ccReturnsHtml() + cutQueueHtml() + pickBlock;
  // маршрут заказа: пока его шаги не отмечены, кроить нельзя (сервер проверяет так же)
  if ((p.ждёт_шагов || []).length) {
    return head + pickBlock + `<div class="cx-notice warn">Партию №${esc(p.номер)} пока нельзя кроить: не выполнены шаги маршрута заказа —
      <b>${p.ждёт_шагов.map(esc).join(', ')}</b>. Их отмечают во вкладке «Маршрут заказа».</div>` + ccHistoryHtml(p);
  }
  return head + pickBlock + ccFormHtml(p) + ccHistoryHtml(p);
}

function ccFormHtml(p) {
  const colors = ccColors(p);
  const sizes = ccSizes(p);
  const left = ccLeft(p);
  const used = ccUsed();
  const pats = ST.cut.лекала || [];
  const secs = CC.secs.map((g, si) => `
    <div class="cc-sec">
      <div class="cc-sec-h"><b>Раздел ${si + 1}</b><span class="cx-hint" data-cc-sum="${si}">${nf(Object.values(g).reduce((a, b) => a + (Number(b) || 0), 0))} шт</span></div>
      <div class="cx-gwrap"><table class="cx-gtable">
        <thead><tr><th class="cx-gcolor">Цвет / размер</th>${sizes.map((z) => `<th>${esc(z)}</th>`).join('')}</tr></thead>
        <tbody>${colors.map((c) => `<tr><th class="cx-gcolor">${esc(c)}</th>${sizes.map((z) => {
          const k = `${c}|${z}`;
          if (!(k in left)) return '<td class="cc-na">—</td>';
          return `<td><input class="cx-gin" type="number" min="0" inputmode="numeric" data-cc-cell="${si}|${esc(k)}" value="${g[k] ? esc(g[k]) : ''}" placeholder="${Math.max(0, left[k] - (used[k] || 0) + (Number(g[k]) || 0))}"></td>`;
        }).join('')}</tr>`).join('')}</tbody>
      </table></div>
    </div>`).join('');
  return `
    <div class="cx-card">
      <div class="cx-card-h"><h3>Партия №${esc(p.номер)} · ${esc(p.категория)} ${esc(p.модель)}</h3>
        <span class="cx-hint">план ${nf(p.план)} · раскроено ${nf(p.раскроено)} · осталось ${nf(p.остаток)}</span></div>
      <div class="cx-card-b">
        <div class="cc-step">1. Карта кроя</div>
        <div class="cx-formgrid">
          <div class="cx-field"><label>Лекало</label>
            <input class="input" id="cc-pattern" list="cc-patterns" value="${esc(CC.pattern)}" placeholder="${pats.length ? 'выберите' : 'лист «Лекала» пуст'}">
            <datalist id="cc-patterns">${pats.map((x) => `<option value="${esc(x.код)}">${esc(x.название)}${x.длина ? ' · ' + esc(x.длина) + ' м' : ''}</option>`).join('')}</datalist></div>
          <div class="cx-field"><label>Длина настила, м</label>
            <input class="input" id="cc-len" inputmode="decimal" value="${esc(CC.len)}" placeholder="например 12,5"></div>
          <div class="cx-field"><label>Комментарий</label>
            <input class="input" id="cc-comment" value="${esc(CC.comment)}"></div>
        </div>
        ${(p.рулоны_карты || []).length ? `<div class="cx-hint" style="margin-bottom:8px">Рулоны по карте конструктора: ${p.рулоны_карты.map((r) => `<b>${esc(r.вид)}</b>${r.цвет ? ' · ' + esc(r.цвет) : ''}${r.код ? ` · №${esc(r.код)}` : ''}${r.вес ? ` · ${nf(r.вес)} кг` : ''}`).join('; ')}</div>` : ''}
        <div class="cc-step">2. Разделы
          <label class="cc-count">сколько разделов <input class="input" id="cc-nsecs" type="number" min="1" max="40" value="${CC.secs.length}"></label></div>
        <div class="cx-hint" style="margin-bottom:8px">В каждом разделе — сколько штук по цвету и размеру. В пустой клетке серым — сколько ещё осталось по плану. План — подсказка: можно вписать больше, если раскроили больше.</div>
        ${secs}
        <div class="cc-step">3. Возврат в снабжение <span class="cx-hint">остатки и обрезки — отдельным видом сырья</span></div>
        <datalist id="cc-mats">${(ST.cut.материалы || []).map((m) => `<option value="${esc(m.вид)}">${esc(m.категория)}${m.ед ? ' · ' + esc(m.ед) : ''}</option>`).join('')}</datalist>
        ${CC.back.map((b, i) => `<div class="cx-btn-row" style="margin-top:6px">
          <input class="input" list="cc-mats" data-cc-back="${i}|материал" value="${esc(b.материал)}" placeholder="вид сырья" style="max-width:220px">
          <input class="input" data-cc-back="${i}|цвет" value="${esc(b.цвет)}" placeholder="цвет" style="max-width:150px">
          <input class="input" type="number" min="0" step="any" data-cc-back="${i}|количество" value="${esc(b.количество)}" placeholder="кол-во" style="max-width:110px">
          <span class="cx-hint">${esc(((ST.cut.материалы || []).find((m) => m.вид === b.материал) || {}).ед || '')}</span>
          <button class="btn ghost" data-act="cc-back-del" data-i="${i}" aria-label="Убрать строку">✕</button></div>`).join('')}
        <div class="cx-btn-row" style="margin-top:6px"><button class="btn" data-act="cc-back-add">+ Возврат</button></div>
      </div>
      <div class="cx-gfoot">
        <span id="cc-total">Всего: <b>${nf(ccTotal())}</b> шт · ${nf(CC.secs.length)} разд.</span>
        <button class="btn ghost" data-act="cc-clear">Очистить</button>
        <button class="btn primary" data-act="cc-save">Сохранить карту</button>
      </div>
    </div>`;
}

// технолог вернул карту кроя: исправить количество и снова сдать на приёмку
function ccReturnsHtml() {
  const list = ST.cut.возвраты || [];
  if (!list.length) return '';
  return list.map((g) => `<div class="cx-card" style="margin-bottom:12px;border-color:var(--red,#e5534b)">
    <div class="cx-card-h"><h3>Возврат: партия №${esc(g.партия)} · карта кроя ${esc(g.карта || '—')}</h3>
      <span class="cx-hint">Технолог: «${esc(g.замечание)}»</span></div>
    <div class="cx-card-b"><div class="cx-scroll"><table class="cx-table"><thead><tr><th>Раздел</th><th>Цвет</th><th>Размер</th><th class="num">Раскроено</th></tr></thead>
      <tbody>${g.строки.map((r) => `<tr><td>${esc(g.партия)}/${esc(r.настил)}</td><td>${esc(r.цвет)}</td><td>${esc(r.размер)}</td>
        <td style="width:96px"><input class="input cx-mini" type="number" min="0" value="${esc(r.факт)}" data-cc-ret="${esc(g.партия)}|${esc(g.карта)}" data-row="${esc(r.настил)}|${esc(r.цвет)}|${esc(r.размер)}"></td></tr>`).join('')}</tbody></table></div>
      <div class="cx-btn-row" style="margin-top:10px"><button class="btn primary" data-act="cc-resubmit" data-k="${esc(g.партия)}|${esc(g.карта)}" style="margin-left:auto">Исправил — сдать на приёмку</button></div>
    </div></div>`).join('');
}

function ccHistoryHtml(p) {
  const cards = p.карты || [];
  if (!cards.length && !(p.настилы || []).length) return '';
  return `<div class="cx-card"><div class="cx-card-h"><h3>Уже раскроено</h3><span class="cx-hint">${nf(cards.length)} карт · ${nf((p.настилы || []).length)} разделов</span></div>
    <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px"><table class="cx-table">
      <thead><tr><th>Карта</th><th>Дата</th><th>Лекало</th><th class="num">Длина, м</th><th>Разделы</th><th class="num">Шт</th></tr></thead>
      <tbody>${cards.map((c) => `<tr><td>№${esc(c.карта)}</td><td>${esc(c.дата)}</td><td>${esc(c.лекало || '—')}</td><td class="num">${esc(c.длина)}</td><td>${esc(p.номер)}/${esc(c.настилы)}</td><td class="num">${nf(c.штук)}</td></tr>`).join('')
        || '<tr><td colspan="6" class="cx-empty">Раскроено старым способом, без карты</td></tr>'}</tbody>
    </table></div></div></div>`;
}

function ccRefreshTotals() {
  const t = document.getElementById('cc-total');
  if (t) t.innerHTML = `Всего: <b>${nf(ccTotal())}</b> шт · ${nf(CC.secs.length)} разд.`;
  CC.secs.forEach((g, si) => {
    const el = document.querySelector(`[data-cc-sum="${si}"]`);
    if (el) el.textContent = `${nf(Object.values(g).reduce((a, b) => a + (Number(b) || 0), 0))} шт`;
  });
}

async function ccSave() {
  const p = ccParty();
  if (!p) return;
  if (!CC.len) return toast('Укажите длину настила', 'err');
  const body = {
    партия: p.номер, лекало: CC.pattern, длина: CC.len, комментарий: CC.comment,
    возврат: CC.back.filter((b) => b.материал),
    разделы: CC.secs.map((g) => ({ позиции: Object.entries(g).filter(([, v]) => Number(v) > 0)
      .map(([k, v]) => { const [цвет, размер] = k.split('|'); return { цвет, размер, факт: Number(v) }; }) })),
  };
  try {
    const res = await api(`${API}/cut/card`, { method: 'POST', body: JSON.stringify(body) });
    ccReset(true);
    await loadCut();
    render();
    toast(`Карта №${res.карта}: разделы ${res.настилы}, ${nf(res.штук)} шт · ${nf(res.сумма)} сом`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="cc-"]');
  if (!el || ST.view !== 'cut') return;
  const act = el.dataset.act;
  if (act === 'cc-pick' || act === 'cc-open') {
    const n = act === 'cc-pick' ? el.dataset.num : (document.getElementById('cc-num').value || '').trim();
    if (!(ST.cut.партии || []).find((x) => x.номер === n)) return toast(`Партии №${n} нет`, 'err');
    CC.num = n; ccReset(true); render(); return;
  }
  if (act === 'cc-back-add') { CC.back.push({ материал: '', цвет: '', количество: '' }); render(); return; }
  if (act === 'cc-back-del') { CC.back.splice(Number(el.dataset.i), 1); render(); return; }
  if (act === 'cc-resubmit') {
    const k = el.dataset.k;
    const [партия, карта] = k.split('|');
    const строки = [...document.querySelectorAll(`[data-cc-ret="${CSS.escape(k)}"]`)].map((i) => {
      const [настил, цвет, размер] = i.dataset.row.split('|');
      return { настил, цвет, размер, факт: Math.max(0, Math.round(Number(i.value) || 0)) };
    });
    try {
      await api(`${API}/cut/resubmit`, { method: 'POST', body: JSON.stringify({ партия, карта, строки }) });
      await loadCut(); render(); toast('Снова на приёмке у технолога', 'ok');
    } catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (act === 'cc-clear') { if (confirm('Очистить форму?')) { ccReset(true); render(); } return; }
  if (act === 'cc-save') { el.disabled = true; await ccSave(); el.disabled = false; }
});

document.addEventListener('keydown', (ev) => {
  if (ST.view === 'cut' && ev.key === 'Enter' && ev.target.id === 'cc-num') {
    ev.preventDefault();
    document.querySelector('[data-act="cc-open"]').click();
  }
});

document.addEventListener('input', (ev) => {
  if (ST.view !== 'cut') return;
  const t = ev.target;
  if (t.dataset.ccCell) {
    const [si, ...rest] = t.dataset.ccCell.split('|');
    const k = rest.join('|');
    const v = Math.max(0, Math.floor(Number(t.value) || 0));
    if (v) CC.secs[Number(si)][k] = v; else delete CC.secs[Number(si)][k];
    ccRefreshTotals(); return;
  }
  if (t.id === 'cc-len') CC.len = t.value;
  if (t.id === 'cc-pattern') CC.pattern = t.value;
  if (t.id === 'cc-comment') CC.comment = t.value;
  if (t.dataset.ccBack) { const [i, f] = t.dataset.ccBack.split('|'); CC.back[Number(i)][f] = t.value; }
});

document.addEventListener('change', (ev) => {
  if (ST.view !== 'cut') return;
  const t = ev.target;
  if (t.id === 'cc-nsecs') {
    const n = Math.min(40, Math.max(1, Math.floor(Number(t.value) || 1)));
    if (n < CC.secs.length && CC.secs.slice(n).some((g) => Object.keys(g).length)
        && !confirm('В убираемых разделах есть количество. Убрать?')) { t.value = CC.secs.length; return; }
    while (CC.secs.length < n) CC.secs.push({});
    if (CC.secs.length > n) CC.secs.length = n;
    render();
  }
});

ccReset(false);
