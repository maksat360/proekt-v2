'use strict';

/* Модуль «Цех» · вкладка «Распределение»: технолог закрепляет настил × этап за швеёй. */

const AS = { data: null, party: null, draft: {}, dirty: false, fix: {}, fixOpen: false };

async function loadAssign() {
  AS.data = await api(`${API}/assign`);
  const list = AS.data.партии || [];
  if (!list.find((p) => p.номер === AS.party)) AS.party = list.length ? list[0].номер : null;
  if (!AS.dirty) asReset();
}

function asParty() { return ((AS.data && AS.data.партии) || []).find((p) => p.номер === AS.party); }

function asReset() {
  const p = asParty();
  AS.draft = {};
  if (p) Object.entries(p.ячейки).forEach(([k, c]) => { AS.draft[k] = c.логин || ''; });
  AS.dirty = false;
}

function asConfirmLeave() {
  return (!AS.dirty && !Object.keys(AS.fix).length) || confirm('Распределение не сохранено. Выбросить изменения?');
}

function asPeopleOptions(code, value) {
  const people = (AS.data && AS.data.люди) || [];
  // закрепить можно только за тем, у кого есть доступ к этапу (сервер проверяет так же)
  const can = people.filter((x) => x.этапы.includes(code));
  const opt = (x) => `<option value="${esc(x.логин)}" ${x.логин === value ? 'selected' : ''}>${esc(x.ФИО)}</option>`;
  const stale = value && !can.find((x) => x.логин === value)
    ? `<option value="${esc(value)}" selected disabled>${esc((people.find((x) => x.логин === value) || {}).ФИО || value)} — нет доступа к этапу</option>` : '';
  return `<option value="">— никто —</option>${stale}
    ${can.length ? can.map(opt).join('') : '<option value="" disabled>Этап никому не назначен</option>'}`;
}

function assignHtml() {
  if (!AS.data) return '<div class="cx-loading"><span class="cx-spin"></span> Загружаем партии…</div>';
  const list = AS.data.партии || [];
  const p = asParty();
  const chips = list.map((x) => `
    <button class="rt-chip ${x.номер === AS.party ? 'on' : ''}" data-act="as-party" data-num="${esc(x.номер)}">
      №${esc(x.номер)} · ${esc(x.модель)} ${x.не_распределено ? `<span class="as-badge">${nf(x.не_распределено)}</span>` : '<span>✓</span>'}
    </button>`).join('');
  if (!p) {
    return `${asHero()}<div class="cx-card"><div class="cx-empty"><b>Нет партий после кроя</b>Партия появится, когда закройщик внесёт первый настил</div></div>`;
  }
  const free = Object.values(AS.draft).filter((v) => !v).length;
  const head = p.этапы.map((st) => `<th>
      <div class="as-st">${esc(st.название)}</div>
      <select class="input as-all" data-as-all="${esc(st.код)}" title="Назначить на все настилы">
        <option value="">все настилы →</option>${asPeopleOptions(st.код, '').replace('<option value="">— никто —</option>', '')}
      </select></th>`).join('');
  const rows = p.настилы.map((n) => `<tr>
      <th class="as-n">Настил ${esc(p.номер)}/${esc(n.настил)}<span>${nf(n.шт)} шт</span></th>
      ${p.этапы.map((st) => {
        const key = `${n.настил}|${st.код}`;
        const cell = p.ячейки[key] || {};
        const v = AS.draft[key] || '';
        const busy = cell.в_работе > 0;
        return `<td class="${v ? '' : 'as-free'} ${v !== (cell.логин || '') ? 'as-changed' : ''}">
          <select class="input as-cell" data-as-cell="${esc(key)}" ${busy ? 'disabled title="Работа уже взята"' : ''}>${asPeopleOptions(st.код, v)}</select>
          ${cell.сдано || cell.в_работе ? `<div class="as-prog">сдано ${nf(cell.сдано)}${cell.в_работе ? ` · в работе ${nf(cell.в_работе)}` : ''}</div>` : ''}
        </td>`;
      }).join('')}
    </tr>`).join('');
  return `
    ${asHero()}
    <div class="rt-chips" style="margin-bottom:14px">${chips}</div>
    <div class="cx-card">
      <div class="cx-card-h"><h3>Партия №${esc(p.номер)} · ${esc(p.модель)}</h3>
        ${AS.dirty ? '<span class="cx-pill orange">не сохранено</span>' : ''}
        <span class="cx-hint">${esc(p.клиент)} · срок ${esc(p.срок || '—')} · раскроено ${nf(p.раскроено)} из ${nf(p.план)}${p.остаток_крой ? ' · крой ещё идёт' : ''}</span></div>
      ${asCutHtml(p)}
      ${asLabelsHtml(p)}
      <div class="rt-tools">
        <span class="cx-hint">${free ? `Не закреплено: <b>${nf(free)}</b> — эту работу никто не увидит` : 'Всё распределено'}</span>
        <span class="rt-sp"></span>
        <button class="btn ghost" data-act="as-cancel" ${AS.dirty ? '' : 'disabled'}>Отменить</button>
        <button class="btn primary" data-act="as-save" ${AS.dirty ? '' : 'disabled'}>Сохранить</button>
      </div>
      <div class="as-wrap"><table class="as-table">
        <thead><tr><th class="as-n">Настил</th>${head}</tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div>`;
}

// крой партии: что сдал закройщик, технолог может исправить факт
function asCutHtml(p) {
  const changed = Object.keys(AS.fix).length;
  const body = AS.fixOpen ? `<div class="as-cut-b">
      ${p.настилы.map((n) => `<div class="as-cut-n"><b>Настил ${esc(p.номер)}/${esc(n.настил)}</b> <span class="cx-hint">${esc(n.закройщик || '')}</span>
        <table><thead><tr><th>Цвет</th><th>Размер</th><th class="num">План</th><th class="num">Факт</th></tr></thead><tbody>
        ${n.строки.map((r) => {
          const key = `${n.настил}|${r.цвет}|${r.размер}`;
          const v = key in AS.fix ? AS.fix[key] : r.факт;
          return `<tr class="${key in AS.fix ? 'as-changed' : ''}"><td>${esc(r.цвет)}</td><td>${esc(r.размер)}</td><td class="num">${nf(r.план)}</td>
            <td class="num"><input class="input as-fix" type="number" min="0" value="${v}" data-fix="${esc(key)}" data-orig="${r.факт}"></td></tr>`;
        }).join('')}</tbody></table></div>`).join('')}
      <div class="rt-tools" style="padding:8px 0 0">
        <span class="cx-hint">Исправление записывается в лист «крой» с пометкой «исправил …, было N». От него считаются работа, упаковка и этикетки.</span>
        <span class="rt-sp"></span>
        <button class="btn ghost" data-act="as-fix-cancel" ${changed ? '' : 'disabled'}>Отменить</button>
        <button class="btn primary" data-act="as-fix-save" ${changed ? '' : 'disabled'}>Сохранить исправления${changed ? ` (${changed})` : ''}</button>
      </div></div>` : '';
  return `<div class="as-labels as-cut">
      <span>Крой: <b>${nf(p.раскроено)}</b> шт из ${nf(p.план)} по плану · настилов ${nf(p.настилы.length)}${changed ? ' · <span class="cx-warn">есть неcохранённые исправления</span>' : ''}</span>
      <span class="rt-sp"></span>
      <button class="btn" data-act="as-fix-toggle">${AS.fixOpen ? 'Свернуть' : 'Проверить и исправить крой'}</button>
      ${body}
    </div>`;
}

async function asFixSave() {
  const p = asParty();
  if (!p) return;
  const строки = Object.entries(AS.fix).map(([k, факт]) => {
    const [настил, цвет, размер] = k.split('|');
    return { настил, цвет, размер, факт };
  });
  try {
    const res = await api(`${API}/cut/fix`, { method: 'POST', body: JSON.stringify({ партия: p.номер, строки }) });
    AS.fix = {};
    const keep = AS.dirty ? { ...AS.draft } : null;
    await loadAssign();
    if (keep) { AS.draft = keep; AS.dirty = true; }
    render();
    const lab = (asParty() || {}).этикетки || {};
    toast(`Исправлено строк: ${nf(res.изменено)}${lab.сгенерировано ? '. Сгенерируйте этикетки заново' : ''}`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

function asLabelsHtml(p) {
  const l = p.этикетки || {};
  const status = !l.сгенерировано
    ? `Этикетки изделий ещё не сгенерированы${p.остаток_крой ? ' · крой ещё идёт, можно сгенерировать сейчас и обновить позже' : ''}`
    : `Этикетки: <b>${nf(l.всего)}</b> шт · ${esc(l.дата)} · ${esc(l.кто)}${l.устарели ? ' · <span class="cx-warn">крой изменился — сгенерируйте заново</span>' : ''}`;
  return `<div class="as-labels">
      <span>${status}</span>
      <span class="rt-sp"></span>
      <button class="btn ${l.сгенерировано && !l.устарели ? 'ghost' : 'primary'}" data-act="as-gen">${l.сгенерировано ? 'Сгенерировать заново' : 'Сгенерировать этикетки'}</button>
      ${l.сгенерировано ? `<a class="btn" href="/cex/items?партия=${encodeURIComponent(p.номер)}" target="_blank">Печать этикеток</a>` : ''}
    </div>`;
}

async function asGenerate() {
  const p = asParty();
  if (!p) return;
  if ((p.этикетки || {}).сгенерировано && !confirm('Пересоздать этикетки партии по текущему крою?')) return;
  try {
    const res = await api(`${API}/items/generate`, { method: 'POST', body: JSON.stringify({ партия: p.номер }) });
    const keep = AS.dirty ? { ...AS.draft } : null;
    await loadAssign();
    if (keep) { AS.draft = keep; AS.dirty = true; }
    render();
    toast(`Сгенерировано ${nf(res.этикеток)} этикеток (${nf(res.строк)} позиций)`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

function asHero() {
  return `<div class="cx-hero compact">
      <div><h1>Распределение</h1>
        <div class="cx-sub">После кроя закрепите каждый настил на каждом этапе за швеёй. Швея видит только своё и берёт настилы по порядку.</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="as-reload">Обновить</button></div>
    </div>`;
}

async function asSave() {
  const p = asParty();
  if (!p) return;
  const changes = Object.entries(AS.draft)
    .filter(([k, v]) => v !== ((p.ячейки[k] || {}).логин || ''))
    .map(([k, v]) => { const [настил, этап] = k.split('|'); return { настил, этап, логин: v }; });
  if (!changes.length) { AS.dirty = false; render(); return; }
  try {
    const res = await api(`${API}/assign`, { method: 'POST', body: JSON.stringify({ партия: p.номер, назначения: changes }) });
    AS.dirty = false;
    await loadAssign();
    render();
    toast(`Сохранено: ${nf(res.изменено)} назначений`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="as-"]');
  if (!el || ST.view !== 'assign') return;
  const act = el.dataset.act;
  if (act === 'as-party') {
    if (el.dataset.num === AS.party || !asConfirmLeave()) return;
    if (Object.keys(AS.fix).length && !confirm('Исправления кроя не сохранены. Выбросить?')) return;
    AS.party = el.dataset.num; AS.dirty = false; AS.fix = {}; asReset(); render(); return;
  }
  if (act === 'as-reload') {
    if (!asConfirmLeave()) return;
    AS.dirty = false;
    try { await loadAssign(); render(); toast('Обновлено', 'ok'); } catch (err) { toast(err.message, 'err'); }
    return;
  }
  if (act === 'as-cancel') { asReset(); render(); return; }
  if (act === 'as-save') { await asSave(); }
  if (act === 'as-gen') { await asGenerate(); }
  if (act === 'as-fix-toggle') { AS.fixOpen = !AS.fixOpen; render(); return; }
  if (act === 'as-fix-cancel') { AS.fix = {}; render(); return; }
  if (act === 'as-fix-save') { await asFixSave(); }
});

document.addEventListener('change', (ev) => {
  if (ST.view !== 'assign') return;
  const t = ev.target;
  if (t.dataset.fix) {
    const v = Math.max(0, Math.floor(Number(t.value) || 0));
    if (v === Number(t.dataset.orig)) delete AS.fix[t.dataset.fix]; else AS.fix[t.dataset.fix] = v;
    render(); return;
  }
  if (t.dataset.asCell) {
    AS.draft[t.dataset.asCell] = t.value; AS.dirty = true; render(); return;
  }
  if (t.dataset.asAll) {
    const code = t.dataset.asAll;
    const p = asParty();
    if (!t.value || !p) return;
    p.настилы.forEach((n) => {
      const key = `${n.настил}|${code}`;
      if (!((p.ячейки[key] || {}).в_работе > 0)) AS.draft[key] = t.value;
    });
    AS.dirty = true; render();
  }
});
