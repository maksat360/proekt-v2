'use strict';

/* Модуль «Цех» · простой экран швеи: выбрать раздел → большой секундомер → «Закончить». */

let SEW_TIMER = null;

function sewClock(iso) {
  const start = new Date(iso).getTime();
  const sec = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (x) => String(x).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
}

function sewTick() {
  const el = document.getElementById('sew-clock');
  if (!el) { clearInterval(SEW_TIMER); SEW_TIMER = null; return; }
  el.textContent = sewClock(el.dataset.start);
}

// Операция выбирается в «Работаю как»: выбрана производственная роль — видны только её задачи.
// Это только фильтр экрана — взятое и сданное по каждой операции хранится как раньше.
function sewStage() { const r = asRole(); return isProd(r) ? r : ''; }

function sewHtml() {
  const w = ST.work || {};
  const mine = w.мои || [];
  const cards = w.партии || [];
  const t = w.итог || {};
  const cur = mine[0];

  const timer = cur ? `
    <div class="sew-timer" role="dialog" aria-label="Работа идёт">
      <div class="sew-t-top">
        <div class="sew-t-stage">${esc(cur.этап_название)}</div>
        <div class="sew-t-what">Раздел ${esc(cur.партия)}/${esc(cur.настил)} · ${nf(cur.количество)} шт</div>
      </div>
      <div class="sew-t-clock" id="sew-clock" data-start="${esc(cur.начало_iso)}">${sewClock(cur.начало_iso)}</div>
      <div class="sew-t-hint">Начато ${esc(cur.начало)}${mine.length > 1 ? ` · ещё в работе: ${nf(mine.length - 1)}` : ''}</div>
      <div class="sew-t-btns">
        <button class="sew-btn cancel" data-act="sew-cancel" data-id="${cur.id}">Отменить</button>
        <button class="sew-btn finish" data-act="sew-finish" data-id="${cur.id}" data-qty="${cur.количество}">Закончить</button>
      </div>
    </div>` : '';

  const blocks = cards.map((c) => {
    const items = [];
    const only = sewStage();
    (c.настилы || []).forEach((l) => l.задачи.forEach((tk) => { if (!only || tk.этап === only) items.push({ l, tk }); }));
    if (!items.length) return '';
    return `
      <div class="sew-party">
        <div class="sew-party-h"><b>Партия №${esc(c.номер)}</b><span>${esc(c.категория)} ${esc(c.модель)}</span></div>
        ${items.map(({ l, tk }) => {
          const done = tk.статус === 'готово';
          const why = done ? 'сдано' : (tk.статус === 'в работе' ? 'в работе'
            : (tk.статус === 'ждёт' ? 'ждёт предыдущий этап' : (tk.можно ? '' : 'после предыдущего раздела')));
          return `<div class="sew-item ${tk.можно ? 'go' : 'off'} ${done ? 'done' : ''}">
            <div class="sew-item-main">
              <div class="sew-item-n">Раздел ${esc(c.номер)}/${esc(l.настил)}</div>
              <div class="sew-item-s">${esc(tk.название)} · ${nf(tk.можно ? tk.доступно : l.шт)} шт${why ? ` · <i>${why}</i>` : ''}</div>
            </div>
            ${tk.можно ? `<button class="sew-take" data-act="sew-take" data-stage="${esc(tk.этап)}" data-num="${esc(c.номер)}" data-nas="${esc(l.настил)}" data-qty="${tk.доступно}">Принять</button>` : ''}
          </div>`;
        }).join('')}
      </div>`;
  }).join('');

  if (cur && !SEW_TIMER) setTimeout(() => { SEW_TIMER = setInterval(sewTick, 1000); }, 0);
  if (!cur && SEW_TIMER) { clearInterval(SEW_TIMER); SEW_TIMER = null; }

  return `
    ${timer}
    <div class="sew-head">
      <div><div class="sew-hi">${esc(((ST.user || {}).фио || '').split(' ')[0] || 'Моя работа')}</div>
        <div class="sew-today">Сегодня: <b>${nf(t.сегодня_шт || 0)}</b> шт · <b>${nf(t.сегодня_сумма || 0)}</b> сом</div></div>
      <button class="btn" data-act="refresh">Обновить</button>
    </div>
    ${blocks || `<div class="sew-empty"><b>Работы пока нет</b>Технолог ещё не закрепил за вами разделы. Нажмите «Обновить» позже.</div>`}`;
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="sew-"]');
  if (!el) return;
  const act = el.dataset.act;
  el.disabled = true;
  try {
    if (act === 'sew-take') {
      await api(`${API}/work/take`, { method: 'POST', body: JSON.stringify({
        этап: el.dataset.stage, партия: el.dataset.num, настил: el.dataset.nas, количество: Number(el.dataset.qty), как_швея: true }) });
    }
    if (act === 'sew-finish') {
      await api(`${API}/work/done`, { method: 'POST', body: JSON.stringify({ id: Number(el.dataset.id), количество: Number(el.dataset.qty) }) });
      toast('Готово — сдано', 'ok');
    }
    if (act === 'sew-cancel') {
      if (!confirm('Отменить работу? Раздел вернётся в очередь, оплаты не будет.')) { el.disabled = false; return; }
      await api(`${API}/work/cancel`, { method: 'POST', body: JSON.stringify({ id: Number(el.dataset.id) }) });
      toast('Отменено', '');
    }
    await loadWork();
    render();
  } catch (err) {
    el.disabled = false;
    toast(err.message, 'err');
  }
});
