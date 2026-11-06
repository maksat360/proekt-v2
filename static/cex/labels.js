'use strict';

const params = new URLSearchParams(location.search);
const party = params.get('партия') || params.get('party') || '';
const box = params.get('коробка') || params.get('box') || '';

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v) => Number(v || 0).toLocaleString('ru-RU');

function labelHtml(l) {
  return `
    <div class="label">
      <div class="top">
        <div class="brand">${esc(l.бренд)}</div>
        <div class="party">партия ${esc(l.партия)}</div>
      </div>
      <div>
        <div class="model">${esc(l.категория)} ${esc(l.модель)}</div>
        <div class="color">${esc(l.цвет)}</div>
      </div>
      <div class="mid">
        <div class="size">${esc(l.размер)}</div>
        <div class="qty">${nf(l.количество)} <small>шт</small></div>
      </div>
      <div class="foot">
        <span>коробка ${esc(l.коробка)}</span>
        <span>${esc(l.дата)}</span>
      </div>
    </div>`;
}

async function load() {
  const url = `/api/cex/labels?партия=${encodeURIComponent(party)}&коробка=${encodeURIComponent(box)}`;
  const res = await fetch(url, { credentials: 'same-origin' });
  if (res.status === 401) { location.href = '/'; return; }
  const data = await res.json();
  if (!data.ok) {
    document.getElementById('sheet').innerHTML = `<div style="padding:20px;color:#b3261e">${esc(data.error || 'Ошибка')}</div>`;
    return;
  }
  const labels = data.data.этикетки || [];
  document.getElementById('lbl-title').textContent = party ? `Этикетки · партия ${party}` : 'Этикетки';
  document.getElementById('lbl-count').textContent = `${labels.length} шт`;
  document.getElementById('sheet').innerHTML = labels.length
    ? labels.map(labelHtml).join('')
    : '<div style="padding:20px;color:#6b7280">Этикеток нет — сначала упакуйте коробку</div>';
}

function setRoll(on) {
  document.body.classList.toggle('roll', on);
  let st = document.getElementById('roll-style');
  if (on && !st) {
    st = document.createElement('style');
    st.id = 'roll-style';
    st.textContent = '@media print { @page { size: 58mm 40mm; margin: 0; } }';
    document.head.appendChild(st);
  } else if (!on && st) {
    st.remove();
  }
  try { localStorage.setItem('cx_label_roll', on ? '1' : ''); } catch (e) {}
}

document.getElementById('btn-print').addEventListener('click', () => window.print());
document.getElementById('f-roll').addEventListener('change', (e) => setRoll(e.target.checked));

try {
  if (localStorage.getItem('cx_label_roll')) {
    document.getElementById('f-roll').checked = true;
    setRoll(true);
  }
} catch (e) {}

load().then(() => {
  if (params.get('print') === '1') setTimeout(() => window.print(), 400);
});
