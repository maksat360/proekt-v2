'use strict';

/* Модуль «Цех» · экран закройщика: номер партии → карта кроя → рулоны → разделы. */

const CC = { num: '', len: '', pattern: '', comment: '', rolls: [], secs: [], open: false };

function ccParty() { return (ST.cut.партии || []).find((p) => p.номер === CC.num); }

function ccReset(keepNum) {
  const n = keepNum ? CC.num : '';
  Object.assign(CC, { num: n, len: '', pattern: '', comment: '', rolls: [ccRoll()], secs: [{}], open: false });
}
function ccRoll() { return { код: '', граммы: '', цвет: '', вес: '' }; }

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
      <div><h1>Крой</h1><div class="cx-sub">Номер партии → карта кроя → рулоны → разделы</div></div>
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
  if (!p) return head + pickBlock;
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
  const rolls = CC.rolls.map((r, i) => `<tr>
      <td class="cc-i">${i + 1}</td>
      <td><input class="input" data-cc-roll="${i}|код" value="${esc(r.код)}" list="cc-stock" placeholder="выберите рулон"></td>
      <td><input class="input" data-cc-roll="${i}|граммы" value="${esc(r.граммы)}" readonly tabindex="-1" placeholder="—"></td>
      <td><input class="input" data-cc-roll="${i}|цвет" value="${esc(r.цвет)}" readonly tabindex="-1" placeholder="—"></td>
      <td><input class="input" data-cc-roll="${i}|вес" value="${esc(r.вес)}" inputmode="decimal" placeholder="кг"></td>
    </tr>`).join('');
  const secs = CC.secs.map((g, si) => `
    <div class="cc-sec">
      <div class="cc-sec-h"><b>Раздел ${si + 1}</b><span class="cx-hint" data-cc-sum="${si}">${nf(Object.values(g).reduce((a, b) => a + (Number(b) || 0), 0))} шт</span></div>
      <div class="cx-gwrap"><table class="cx-gtable">
        <thead><tr><th class="cx-gcolor">Цвет / размер</th>${sizes.map((z) => `<th>${esc(z)}</th>`).join('')}</tr></thead>
        <tbody>${colors.map((c) => `<tr><th class="cx-gcolor">${esc(c)}</th>${sizes.map((z) => {
          const k = `${c}|${z}`;
          if (!(k in left)) return '<td class="cc-na">—</td>';
          return `<td><input class="cx-gin" type="number" min="0" inputmode="numeric" data-cc-cell="${si}|${esc(k)}" value="${g[k] ? esc(g[k]) : ''}" placeholder="${left[k] - (used[k] || 0) + (Number(g[k]) || 0)}"></td>`;
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
        <datalist id="cc-stock">${(ST.cut.рулоны_склад || []).map((r) => `<option value="${esc(r.код)}">${esc([r.материал, r.цвет, r.вес && r.вес + ' кг'].filter(Boolean).join(' · '))}</option>`).join('')}</datalist>

        <div class="cc-step">2. Рулоны
          <label class="cc-count">сколько рулонов <input class="input" id="cc-nrolls" type="number" min="1" max="200" value="${CC.rolls.length}"></label></div>
        <div class="cx-hint" style="margin-bottom:6px">Рулоны вносит снабженец. Цвет и граммаж подставятся сами, вес можно поправить.</div>
        <div class="cc-rolls"><table>
          <thead><tr><th>№</th><th>Код рулона</th><th>Граммаж, г/м²</th><th>Цвет</th><th>Вес, кг</th></tr></thead>
          <tbody>${rolls}</tbody></table></div>

        <div class="cc-step">3. Разделы
          <label class="cc-count">сколько разделов <input class="input" id="cc-nsecs" type="number" min="1" max="40" value="${CC.secs.length}"></label></div>
        <div class="cx-hint" style="margin-bottom:8px">В каждом разделе — сколько штук по цвету и размеру. В пустой клетке серым — сколько ещё осталось по плану.</div>
        ${secs}
      </div>
      <div class="cx-gfoot">
        <span id="cc-total">Всего: <b>${nf(ccTotal())}</b> шт · ${nf(CC.secs.length)} разд. · ${nf(CC.rolls.length)} рул.</span>
        <button class="btn ghost" data-act="cc-clear">Очистить</button>
        <button class="btn primary" data-act="cc-save">Сохранить карту</button>
      </div>
    </div>`;
}

function ccHistoryHtml(p) {
  const cards = p.карты || [];
  if (!cards.length && !(p.настилы || []).length) return '';
  return `<div class="cx-card"><div class="cx-card-h"><h3>Уже раскроено</h3><span class="cx-hint">${nf(cards.length)} карт · ${nf((p.настилы || []).length)} разделов</span></div>
    <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px"><table class="cx-table">
      <thead><tr><th>Карта</th><th>Дата</th><th>Лекало</th><th class="num">Длина, м</th><th class="num">Рулонов</th><th class="num">Вес, кг</th><th>Разделы</th><th class="num">Шт</th></tr></thead>
      <tbody>${cards.map((c) => `<tr><td>№${esc(c.карта)}</td><td>${esc(c.дата)}</td><td>${esc(c.лекало || '—')}</td><td class="num">${esc(c.длина)}</td>
        <td class="num">${nf(c.рулонов)}</td><td class="num">${esc(c.вес)}</td><td>${esc(p.номер)}/${esc(c.настилы)}</td><td class="num">${nf(c.штук)}</td></tr>`).join('')
        || '<tr><td colspan="8" class="cx-empty">Раскроено старым способом, без карты</td></tr>'}</tbody>
    </table></div></div></div>`;
}

function ccRefreshTotals() {
  const t = document.getElementById('cc-total');
  if (t) t.innerHTML = `Всего: <b>${nf(ccTotal())}</b> шт · ${nf(CC.secs.length)} разд. · ${nf(CC.rolls.length)} рул.`;
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
    рулоны: CC.rolls,
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
    if (n !== CC.num && ccTotal() && !confirm('Введённые данные не сохранены. Открыть другую партию?')) return;
    CC.num = n; ccReset(true); render(); return;
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
  if (t.dataset.ccRoll) {
    const [i, f] = t.dataset.ccRoll.split('|');
    const roll = CC.rolls[Number(i)];
    roll[f] = t.value;
    const known = f === 'код' && (ST.cut.рулоны_склад || []).find((r) => r.код === t.value.trim());
    if (known) {  // подставляем данные снабженца в эту строку без перерисовки всей формы
      Object.assign(roll, { граммы: known.граммы, цвет: known.цвет, вес: roll.вес || known.вес });
      ['граммы', 'цвет', 'вес'].forEach((k) => {
        const inp = document.querySelector(`[data-cc-roll="${i}|${k}"]`);
        if (inp) inp.value = roll[k];
      });
    }
    ccRefreshTotals(); return;
  }
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
});

document.addEventListener('change', (ev) => {
  if (ST.view !== 'cut') return;
  const t = ev.target;
  if (t.id === 'cc-nrolls') {
    const n = Math.min(200, Math.max(1, Math.floor(Number(t.value) || 1)));
    while (CC.rolls.length < n) CC.rolls.push(ccRoll());
    if (CC.rolls.length > n) CC.rolls.length = n;
    render(); return;
  }
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
