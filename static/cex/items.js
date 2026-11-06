'use strict';

/* Печать этикеток изделий партии: одна этикетка на штуку, DataMatrix + наименование. */
const params = new URLSearchParams(location.search);
const party = params.get('партия') || '';
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v) => Number(v || 0).toLocaleString('ru-RU');
const PREVIEW = 60; // сколько этикеток рисовать на экране (печатаются все)
let DATA = null;
const pick = {};   // наименование → сколько печатать

function total() { return Object.values(pick).reduce((a, b) => a + (Number(b) || 0), 0); }

function labelHtml(r) {
  return `<div class="lbl"><div class="dm">${r.svg}</div><div class="nm">${esc(r.наименование)}</div></div>`;
}

// длинное наименование уменьшаем, пока не влезет в свою половину этикетки
function fitNames() {
  const seen = new Map();
  document.querySelectorAll('.lbl .nm').forEach((el) => {
    const key = el.textContent;
    if (seen.has(key)) { el.style.fontSize = seen.get(key); return; }
    let pt = 10.5;
    el.style.fontSize = `${pt}pt`;
    while ((el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1) && pt > 5.5) {
      pt -= 0.5;
      el.style.fontSize = `${pt}pt`;
    }
    seen.set(key, el.style.fontSize);
  });
}

function drawSheet(forPrint) {
  const out = [];
  let shown = 0;
  for (const r of DATA.строки) {
    const n = Math.max(0, Math.floor(Number(pick[r.наименование]) || 0));
    for (let i = 0; i < n; i += 1) {
      if (!forPrint && shown >= PREVIEW) break;
      out.push(labelHtml(r));
      shown += 1;
    }
  }
  const all = total();
  document.getElementById('sheet').innerHTML = out.join('')
    + (!forPrint && all > shown ? `<div class="more">На экране показаны первые ${nf(shown)}, напечатаются все ${nf(all)}</div>` : '');
  fitNames();
  document.getElementById('t-count').textContent = `${nf(all)} этикеток`;
  document.getElementById('btn-print').disabled = !all;
}

function drawPick() {
  const rows = DATA.строки.map((r) => `<tr>
      <td>${esc(r.наименование)}</td><td class="n">${nf(r.количество)}</td>
      <td class="n"><input type="number" min="0" max="99999" value="${pick[r.наименование]}" data-name="${esc(r.наименование)}"></td>
    </tr>`).join('');
  document.getElementById('pick').innerHTML = `
    <div class="note">Партия №${esc(DATA.партия)} · ${esc(DATA.модель)} · сгенерировано ${esc(DATA.дата)} (${esc(DATA.кто)}).
      Сколько печатать — можно уменьшить, например для одного настила.
      ${DATA.устарели ? '<br><span class="warn">Крой изменился после генерации — сгенерируйте этикетки заново во вкладке «Распределение».</span>' : ''}</div>
    <table><thead><tr><th>Наименование</th><th class="n">По крою</th><th class="n">Печатать</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function load() {
  const res = await fetch(`/api/cex/items?партия=${encodeURIComponent(party)}&svg=1`, { credentials: 'same-origin' });
  if (res.status === 401) { location.href = '/'; return; }
  const data = await res.json();
  if (!data.ok) {
    document.getElementById('sheet').innerHTML = `<div class="more" style="color:#b3261e">${esc(data.error || 'Ошибка')}</div>`;
    return;
  }
  DATA = data.data;
  const { ш, в } = DATA.мм;
  document.documentElement.style.setProperty('--w', `${ш}mm`);
  document.documentElement.style.setProperty('--h', `${в}mm`);
  document.getElementById('page-size').textContent = `@media print { @page { size: ${ш}mm ${в}mm; margin: 0; } }`;
  document.getElementById('t-title').textContent = `Этикетки изделий · партия ${DATA.партия}`;
  DATA.строки.forEach((r) => { pick[r.наименование] = r.количество; });
  drawPick();
  drawSheet(false);
}

document.addEventListener('input', (e) => {
  if (!e.target.dataset.name) return;
  pick[e.target.dataset.name] = Math.max(0, Math.floor(Number(e.target.value) || 0));
  drawSheet(false);
});

document.getElementById('btn-print').addEventListener('click', () => {
  drawSheet(true);
  setTimeout(() => { window.print(); drawSheet(false); }, 50);
});

load();
