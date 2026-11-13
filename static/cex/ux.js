'use strict';

/* Модуль «Цех» · несохранённые изменения и плавная смена экранов.
   Человек что-то вписал и не сохранил → при уходе (вкладка, другой заказ, «Портал», смена роли,
   закрытие страницы) спрашиваем: остаться или уйти без сохранения. Успешное сохранение снимает метку. */

const UX = { dirty: false, pass: false, view: null };

// вкладки маршрутов и распределения спрашивают сами (свои флаги RT.dirty / AS.dirty)
const uxOwnGuard = () => (typeof rtIsView === 'function' && rtIsView(ST.view)) || ST.view === 'assign';

// поля, которые ничего не меняют: поиск, фильтры, выбор месяца, номер партии, «работаю как»
function uxCounts(el) {
  if (!el || !el.closest('#cx-main') || el.closest('[data-nodirty]')) return false;
  if (!/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return false;
  if (['checkbox', 'radio', 'search', 'month'].includes(el.type)) return false;
  if (['cc-num', 'cx-asrole'].includes(el.id)) return false;
  return !/^(Поиск|Найти)/.test(el.placeholder || '');
}

function uxSetDirty(on) {
  UX.dirty = on;
  document.body.classList.toggle('ux-dirty', on);
  if (!on) document.querySelectorAll('.ux-changed').forEach((x) => x.classList.remove('ux-changed'));
}
function uxClean() { uxSetDirty(false); }

['input', 'change'].forEach((type) => document.addEventListener(type, (ev) => {
  if (uxOwnGuard() || !uxCounts(ev.target)) return;
  ev.target.classList.add('ux-changed');
  if (!UX.dirty) uxSetDirty(true);
}, true));

// окно в стиле системного: «Остаться» — главное действие, Esc и клик мимо — тоже «остаться»
function uxAsk({ title, text, stay = 'Остаться', leave = 'Не сохранять' }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'ux-sheet-wrap';
    wrap.innerHTML = `<div class="ux-sheet" role="alertdialog" aria-modal="true" aria-labelledby="ux-t" aria-describedby="ux-d">
        <div class="ux-sheet-ico" aria-hidden="true">!</div>
        <h3 id="ux-t">${esc(title)}</h3>
        <p id="ux-d">${esc(text)}</p>
        <div class="ux-sheet-btns">
          <button class="btn primary" data-ux="stay">${esc(stay)}</button>
          <button class="btn ux-danger" data-ux="leave">${esc(leave)}</button>
        </div>
      </div>`;
    const prev = document.activeElement;
    const done = (leaveIt) => {
      wrap.classList.add('out');
      document.removeEventListener('keydown', onKey, true);
      setTimeout(() => { wrap.remove(); if (!leaveIt && prev && prev.focus) prev.focus(); }, 180);
      resolve(leaveIt);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); done(false); }
      if (e.key === 'Tab') {  // фокус не уходит из окна
        const b = [...wrap.querySelectorAll('button')];
        const i = b.indexOf(document.activeElement);
        e.preventDefault();
        b[(i + (e.shiftKey ? b.length - 1 : 1)) % b.length].focus();
      }
    };
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('[data-ux]');
      if (b) done(b.dataset.ux === 'leave');
      else if (e.target === wrap) done(false);
    });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(wrap);
    wrap.querySelector('[data-ux="stay"]').focus();
  });
}

const uxLeaveText = { title: 'Уйти без сохранения?', text: 'Вы что-то вписали и не сохранили. Если уйти сейчас, эти данные пропадут.' };

// куда можно уйти со страницы: вкладки, другой заказ/карта/партия, «Портал» и прочие ссылки
const UX_NAV = '[data-act="tab"], [data-act="fl-design-open"], [data-act="fl-supply-open"], [data-act="fl-sub"], '
  + '[data-act="fl-nom-pick"], [data-act="fl-nom-bom"], '
  + '[data-act="cc-pick"], [data-act="cc-open"], a[href]';

document.addEventListener('click', async (ev) => {
  if (UX.pass || !UX.dirty || uxOwnGuard()) return;
  const el = ev.target.closest(UX_NAV);
  if (!el || el.closest('.ux-sheet-wrap')) return;
  if (el.matches('[data-act="tab"]') && el.dataset.tab === ST.view) return;  // та же вкладка
  if (el.closest('.on') && !el.matches('a[href]')) return;                  // уже открытый заказ
  ev.preventDefault();
  ev.stopImmediatePropagation();
  if (!(await uxAsk(uxLeaveText))) return;
  uxClean();
  if (el.matches('a[href]')) { location.href = el.href; return; }
  UX.pass = true;
  try { el.click(); } finally { UX.pass = false; }
}, true);

// «Работаю как …» тоже меняет экран
let uxRole = '';
document.addEventListener('focusin', (ev) => { if (ev.target.id === 'cx-asrole') uxRole = ev.target.value; }, true);
document.addEventListener('change', async (ev) => {
  const sel = ev.target;
  if (sel.id !== 'cx-asrole' || UX.pass || !UX.dirty || uxOwnGuard()) return;
  ev.stopImmediatePropagation();
  const want = sel.value;
  sel.value = uxRole || sel.value;
  if (!(await uxAsk(uxLeaveText))) return;
  uxClean();
  sel.value = want;
  UX.pass = true;
  try { sel.dispatchEvent(new Event('change', { bubbles: true })); } finally { UX.pass = false; }
}, true);

// закрытие вкладки браузера или перезагрузка — системное окно браузера
window.addEventListener('beforeunload', (ev) => {
  if (UX.dirty && !uxOwnGuard()) { ev.preventDefault(); ev.returnValue = ''; }
});

// плавное появление экрана — только при смене вкладки, не при каждом обновлении
const uxRender = render;
render = function renderWithMotion(...args) {  // eslint-disable-line no-global-assign
  const changed = UX.view !== null && UX.view !== ST.view;
  if (changed) uxClean();  // ушли с экрана (через окно или без правок) — старая метка не нужна
  UX.view = ST.view;
  const out = uxRender.apply(this, args);
  if (changed) {
    const main = document.getElementById('cx-main');
    main.classList.remove('cx-enter');
    void main.offsetWidth;  // перезапуск анимации
    main.classList.add('cx-enter');
    clearTimeout(UX.t);
    UX.t = setTimeout(() => main.classList.remove('cx-enter'), 700);  // дальше обновления без анимации
  }
  return out;
};
// метка «Не сохранено» в шапке
document.querySelector('.cx-top-title')?.insertAdjacentHTML('afterend',
  '<span class="ux-badge" role="status" aria-live="polite"><i></i>Не сохранено</span>');
