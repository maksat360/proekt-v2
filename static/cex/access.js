'use strict';

/* Модуль «Цех» · вкладка «Сотрудники и роли».
   Роль — одна сущность: служебные (Технолог, Складчик…) и производственные (Оверлок, Карман…).
   Разрешения (что человеку доступно в системе) настраиваются отдельно от ролей.
   Кнопки скрываются по разрешениям, но решает всегда сервер. Работает поверх cex.js. */

const AC = { data: null, person: null, role: null, q: '', sub: 'people', newRole: false };

async function loadAccess() {
  AC.data = await api(`${API}/access`);
  const people = AC.data.люди || [];
  if (!people.find((p) => p.логин === AC.person)) AC.person = (people[0] || {}).логин || null;
  const roles = AC.data.роли || [];
  if (!roles.find((r) => r.код === AC.role)) AC.role = (roles.find((r) => r.вид === 'производственная') || roles[0] || {}).код || null;
}

function acCan(code) { return !!((AC.data && AC.data.мои_права) || {})[code]; }
function acPerson(login) { return ((AC.data && AC.data.люди) || []).find((p) => p.логин === login); }
function acRole(code) { return ((AC.data && AC.data.роли) || []).find((r) => r.код === code); }
function acRoleName(r) { return ((AC.data && AC.data.роли_названия) || {})[r] || r; }
function acLocked() { return AC.data.закрытая_роль; }

function acGroups() {
  const out = [];
  ((AC.data && AC.data.каталог) || []).forEach((c) => {
    let g = out.find((x) => x.name === c.группа);
    if (!g) { g = { name: c.группа, items: [] }; out.push(g); }
    g.items.push(c);
  });
  return out;
}

// важные разрешения — переспрашиваем перед изменением
const AC_IMPORTANT = new Set(['perms.roles', 'perms.users', 'staff.delete', 'stages.delete', 'stages.assign', 'staff.add', 'staff.edit']);

function acSwitch(attrs, on, disabled, label) {
  return `<label class="ac-switch ${disabled ? 'off' : ''}">
    <input type="checkbox" ${attrs} ${on ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="${esc(label)}">
    <span class="ac-track"><span class="ac-knob"></span></span></label>`;
}

function acLogVal(v) {
  if (v === true) return 'да';
  if (v === false) return 'нет';
  return esc(v === undefined || v === null || v === '' ? '—' : v);
}

function accessHtml() {
  if (!AC.data) return '<div class="cx-loading"><span class="cx-spin"></span> Загружаем…</div>';
  const subs = [['people', 'Сотрудники'], ['roles', 'Роли']];
  if (AC.data.журнал) subs.push(['log', 'Журнал']);
  const add = AC.sub === 'people' && acCan('staff.add') ? '<button class="btn primary" data-act="ac-new-person">+ Сотрудник</button>'
    : (AC.sub === 'roles' && acCan('stages.create') ? '<button class="btn primary" data-act="ac-role-new">+ Производственная роль</button>' : '');
  const body = AC.sub === 'roles' ? acRolesHtml() : (AC.sub === 'log' ? acLogHtml() : acPeopleHtml());
  return `<div class="cx-hero compact"><div><h1>Сотрудники и роли</h1>
      <div class="cx-sub">Роль — что человек делает (Технолог, Оверлок, Карман…). Разрешения — что ему доступно в системе. Одному человеку можно дать несколько ролей.</div></div>
      <div class="cx-hero-actions">${add}<button class="btn" data-act="ac-refresh">Обновить</button></div></div>
    <div class="cx-tabs">${subs.map(([id, l]) => `<button class="cx-tab ${AC.sub === id ? 'on' : ''}" data-act="ac-sub" data-sub="${id}">${l}</button>`).join('')}</div>
    ${body}`;
}

// ------------------------------------------------------------ сотрудники
function acPeopleHtml() {
  const q = AC.q.trim().toLowerCase();
  const people = (AC.data.люди || []).filter((p) => !q || p.ФИО.toLowerCase().includes(q) || p.логин.toLowerCase().includes(q));
  const list = people.map((p) => `
    <button class="ac-row ${p.логин === AC.person ? 'on' : ''} ${p.активен ? '' : 'dim'}" data-act="ac-person" data-login="${esc(p.логин)}">
      <span class="ac-row-main"><b>${esc(p.ФИО)}</b><span class="cx-hint">${esc(p.роли.map(acRoleName).join(', ') || '—')}${p.активен ? '' : ' · отключён'}</span></span>
      <span class="ac-count" title="Ролей">${nf(p.роли.length)}</span>
    </button>`).join('');
  return `<div class="ac-split">
      <div class="cx-card ac-list">
        <div class="cx-card-b"><input class="input" id="ac-q" placeholder="Поиск по имени или логину" value="${esc(AC.q)}"></div>
        <div class="ac-rows">${list || '<div class="cx-empty" style="padding:16px">Никого не нашли</div>'}</div>
      </div>
      <div>${acCardHtml(acPerson(AC.person))}</div>
    </div>`;
}

function acRoleChips(p, can) {
  const group = (kind) => (AC.data.роли || []).filter((r) => r.вид === kind && r.код !== acLocked() && r.код !== 'client')
    .filter((r) => !r.отключён || p.роли.includes(r.код))
    .map((r) => {
      const on = p.роли.includes(r.код);
      const main = r.код === p.роль;
      // отключённую роль можно только снять; основную меняют полем «Основная роль»
      const ok = can && !main && (on || !r.отключён);
      return `<label class="ac-chip ${on ? 'on' : ''} ${ok ? '' : 'ro'}" ${main ? 'title="Основная роль"' : ''}>
        <input type="checkbox" data-ac-person-role="${esc(p.логин)}" data-code="${esc(r.код)}" ${on ? 'checked' : ''} ${ok ? '' : 'disabled'}>
        ${esc(r.название)}${main ? ' · основная' : ''}${r.отключён ? ' · отключена' : ''}</label>`;
    }).join('');
  return `<div class="ac-group-h">Производственные — к каким операциям есть доступ</div>
    <div class="ac-chips">${group('производственная') || '<span class="cx-hint">Производственных ролей нет — создайте во вкладке «Роли»</span>'}</div>
    <div class="ac-group-h" style="margin-top:12px">Служебные</div>
    <div class="ac-chips">${group('служебная')}</div>`;
}

function acCardHtml(p) {
  if (!p) return '<div class="cx-card"><div class="cx-empty"><b>Выберите сотрудника</b>Слева список цеха</div></div>';
  const me = p.логин === AC.data.я;
  const adminLocked = p.роль === acLocked() && (ST.user || {}).роль !== acLocked();
  const canEdit = acCan('staff.edit') && !me && !adminLocked;
  const canRoles = acCan('stages.assign') && !me && !adminLocked;
  const mains = (AC.data.роли || []).filter((r) => !r.отключён || r.код === p.роль);
  return `
    <div class="cx-card">
      <div class="cx-card-h"><h3>${esc(p.ФИО)}</h3>
        <span class="cx-pill blue">${esc(p.роль_название)}</span>
        ${p.активен ? '' : '<span class="cx-pill red">отключён</span>'}
        ${me ? '<span class="cx-pill grey">это вы</span>' : ''}</div>
      <div class="cx-card-b">
        <div class="cx-formgrid ac-form">
          <div class="cx-field"><label>Логин</label><div><code>${esc(p.логин)}</code> · цех ${esc(p.цех || '—')}</div></div>
          <div class="cx-field"><label>ФИО</label><input class="input" id="ac-fio" value="${esc(p.ФИО)}" ${canEdit ? '' : 'disabled'}></div>
          <div class="cx-field"><label>Основная роль</label><select class="input" id="ac-role" ${canRoles ? '' : 'disabled'}>
            ${mains.map((r) => `<option value="${esc(r.код)}" ${r.код === p.роль ? 'selected' : ''}>${esc(r.название)}</option>`).join('')}</select></div>
          <div class="cx-field"><label>Новый пароль</label><input class="input" id="ac-pass" type="password" autocomplete="new-password" placeholder="не менять" ${canEdit ? '' : 'disabled'}></div>
        </div>
        ${me ? '<div class="cx-hint">Свои роли, пароль и разрешения здесь менять нельзя — это делает другой администратор.</div>' : ''}
        ${adminLocked ? '<div class="cx-hint">Карточку начальника меняет только начальник.</div>' : ''}
        <div class="cx-btn-row" style="margin-top:12px">
          ${canEdit || canRoles ? `<button class="btn primary" data-act="ac-save-person" data-login="${esc(p.логин)}">Сохранить</button>` : ''}
          ${!me && !adminLocked && (p.активен ? acCan('staff.delete') : acCan('staff.edit'))
            ? `<button class="btn ghost ${p.активен ? 'danger' : ''}" data-act="ac-toggle-active" data-login="${esc(p.логин)}" data-on="${p.активен ? 0 : 1}">${p.активен ? 'Отключить' : 'Включить снова'}</button>` : ''}
        </div>
      </div>
    </div>
    ${p.роль !== acLocked() ? `<div class="cx-card">
      <div class="cx-card-h"><h3>Роли</h3><span class="cx-hint">${nf(p.роли.length)}</span></div>
      <div class="cx-card-b">
        ${acRoleChips(p, canRoles)}
        <div class="cx-hint" style="margin-top:10px">${canRoles ? 'Галочка сохраняется сразу. С несколькими ролями человек выбирает в цехе «Работаю как» — например, Оверлок или Карман.' : 'Назначать роли может сотрудник с разрешением «Назначение и снятие ролей у сотрудников».'}</div>
      </div></div>` : ''}
    ${p.права ? acPersonPerms(p, me || adminLocked) : ''}`;
}

function acPersonPerms(p, locked) {
  const can = acCan('perms.users') && !locked;
  const extra = Object.entries(p.права).filter(([, v]) => v.индивидуально);
  const groups = acGroups().map((g) => `
    <div class="ac-group"><div class="ac-group-h">${esc(g.name)}</div>
      ${g.items.map((c) => {
        const v = p.права[c.код] || {};
        const mine = acCan(c.код);
        return `<div class="ac-perm ${v.индивидуально ? 'own' : ''}">
          <div class="ac-perm-main"><span>${esc(c.название)}</span>
            ${v.индивидуально ? `<span class="cx-pill orange">лично: ${v.значение ? 'выдано' : 'забрано'}</span>
              ${can && mine ? `<button class="btn ghost ac-mini" data-act="ac-user-reset" data-login="${esc(p.логин)}" data-code="${esc(c.код)}">как у ролей</button>` : ''}` : ''}
          </div>
          ${acSwitch(`data-ac-user-perm="${esc(p.логин)}" data-code="${esc(c.код)}"`, v.значение, !can || !mine, c.название)}
        </div>`;
      }).join('')}
    </div>`).join('');
  return `<details class="cx-card ac-perms" ${extra.length ? 'open' : ''}>
    <summary class="cx-card-h"><h3>Разрешения</h3>
      <span class="cx-hint">по ролям${extra.length ? ` · личных настроек: ${nf(extra.length)}` : ''}</span></summary>
    <div class="cx-card-b">
      <div class="cx-hint" style="margin-bottom:10px">Разрешения складываются из всех ролей человека. Личная настройка меняет только его —
        так, например, технологу можно дать управление сотрудниками и ролями, а потом забрать.
        ${can ? 'Выдать или забрать можно только то, что есть у вас самих.' : ''}</div>
      ${groups}
    </div></details>`;
}

function acNewPersonModal() {
  const roles = (AC.data.роли || []).filter((r) => !r.отключён);
  const opt = (kind) => roles.filter((r) => r.вид === kind).map((r) => `<option value="${esc(r.код)}">${esc(r.название)}</option>`).join('');
  const modal = $('#cx-modal');
  modal.innerHTML = `<div class="cx-modal-box">
    <div class="cx-modal-h"><h3>Новый сотрудник</h3><button class="btn cx-close" data-act="close-modal">Закрыть</button></div>
    <div class="cx-modal-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>ФИО</label><input class="input" id="ac-n-fio" autocomplete="off"></div>
        <div class="cx-field"><label>Логин для входа</label><input class="input" id="ac-n-login" autocomplete="off" placeholder="например, aliya"></div>
        <div class="cx-field"><label>Основная роль</label><select class="input" id="ac-n-role">
          <optgroup label="Производственные">${opt('производственная')}</optgroup>
          <optgroup label="Служебные">${opt('служебная')}</optgroup></select></div>
        <div class="cx-field"><label>Пароль</label><input class="input" id="ac-n-pass" type="password" autocomplete="new-password"></div>
      </div>
      <div class="cx-hint" style="margin-top:8px">Сотрудник попадёт в лист «сотрудники» рабочей книги и сразу сможет войти. Остальные роли отметите в его карточке.</div>
      <div class="cx-btn-row" style="margin-top:16px"><button class="btn primary" data-act="ac-create-person">Добавить</button></div>
    </div></div>`;
  modal.hidden = false;
  $('#ac-n-fio').focus();
}

// ------------------------------------------------------------ роли
function acRolesHtml() {
  const roles = AC.data.роли || [];
  const cur = acRole(AC.role) || roles[0];
  if (!cur) return '<div class="cx-card"><div class="cx-empty"><b>Ролей нет</b></div></div>';
  const chips = (kind) => roles.filter((r) => r.вид === kind).map((r) => `<button class="rt-chip ${r.код === cur.код ? 'on' : ''}" data-act="ac-role" data-role="${esc(r.код)}">
    ${esc(r.название)}${r.отключён ? ' · отключена' : ''} <span>${nf(r.люди.length)}</span></button>`).join('');
  const form = AC.newRole ? `<div class="cx-card"><div class="cx-card-h"><h3>Новая производственная роль</h3></div><div class="cx-card-b">
    <div class="cx-formgrid ac-form">
      <div class="cx-field"><label>Название</label><input class="input" id="ac-nr-name" placeholder="например, Петля"></div>
      <div class="cx-field"><label>Код</label><input class="input" id="ac-nr-code" placeholder="ПЕТЛЯ" maxlength="12"></div>
      <div class="cx-field"><label>Ставка, сом/шт</label><input class="input" id="ac-nr-rate" type="number" min="0" step="0.5" value="0"></div>
    </div>
    <div class="cx-hint">Код — коротко заглавными, по нему роль хранится в Excel и в маршрутах. Потом выдайте роль людям и добавьте её в маршрут.</div>
    <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="ac-role-create">Создать</button>
      <button class="btn ghost" data-act="ac-role-cancel">Отмена</button></div></div></div>` : '';
  return `${form}
    <div class="ac-group-h">Производственные роли — операции маршрута</div>
    <div class="ac-rolechips">${chips('производственная') || '<span class="cx-hint">Пока нет</span>'}</div>
    <div class="ac-group-h">Служебные роли</div>
    <div class="ac-rolechips">${chips('служебная')}</div>
    <div class="ac-split">
      <div>${acRoleSettings(cur)}${acRolePerms(cur)}</div>
      <div>${acRolePeople(cur)}</div>
    </div>`;
}

function acRoleSettings(r) {
  if (r.вид !== 'производственная') {
    return `<div class="cx-card"><div class="cx-card-h"><h3>${esc(r.название)}</h3><span class="cx-pill grey">служебная</span></div>
      <div class="cx-card-b"><div class="cx-hint">За служебной ролью стоят свои экраны, поэтому её нельзя удалить или переименовать. Её разрешения настраиваются ниже.</div></div></div>`;
  }
  const can = acCan('stages.edit');
  return `<div class="cx-card"><div class="cx-card-h"><h3>${esc(r.название)}</h3>
      <span class="cx-pill blue">производственная · ${esc(r.код)}</span>${r.отключён ? '<span class="cx-pill grey">отключена</span>' : ''}</div>
    <div class="cx-card-b">
      <div class="cx-formgrid ac-form">
        <div class="cx-field"><label>Название</label><input class="input" id="ac-r-name" value="${esc(r.название)}" ${can ? '' : 'disabled'}></div>
        <div class="cx-field"><label>Ставка, сом/шт</label><input class="input" id="ac-r-rate" type="number" min="0" step="0.5" value="${esc(r.ставка)}" ${can ? '' : 'disabled'}></div>
        <div class="cx-field"><label>Порядок</label><input class="input" id="ac-r-order" type="number" value="${esc(r.порядок)}" ${can ? '' : 'disabled'}></div>
      </div>
      <div class="cx-btn-row" style="margin-top:10px">
        ${can ? `<button class="btn primary" data-act="ac-role-save" data-code="${esc(r.код)}">Сохранить</button>
          <button class="btn ghost" data-act="ac-role-toggle" data-code="${esc(r.код)}" data-off="${r.отключён ? 0 : 1}">${r.отключён ? 'Включить' : 'Отключить'}</button>` : ''}
        ${acCan('stages.delete') ? `<button class="btn ghost danger" data-act="ac-role-del" data-code="${esc(r.код)}" ${r.используется ? 'disabled' : ''}>Удалить</button>` : ''}
      </div>
      ${r.используется ? `<div class="cx-hint" style="margin-top:6px">Используется (${esc(r.используется)}) — удалить нельзя, чтобы не потерять историю. Можно отключить: начатые партии её пройдут, но новым людям и в новые маршруты её не добавить.</div>` : ''}
    </div></div>`;
}

function acRolePerms(r) {
  if (!r.права) return '';
  const locked = r.код === acLocked();
  const own = r.код === (ST.user || {}).роль;
  const can = acCan('perms.roles') && !locked && !own;
  const groups = acGroups().map((g) => {
    const on = g.items.filter((c) => r.права[c.код]).length;
    return `<div class="ac-group"><div class="ac-group-h">${esc(g.name)} <span class="cx-hint">${nf(on)} из ${nf(g.items.length)}</span></div>
      ${g.items.map((c) => `<div class="ac-perm"><div class="ac-perm-main"><span>${esc(c.название)}</span></div>
        ${acSwitch(`data-ac-role-perm="${esc(r.код)}" data-code="${esc(c.код)}"`, r.права[c.код], !can || !acCan(c.код), c.название)}</div>`).join('')}
    </div>`;
  }).join('');
  return `<details class="cx-card" style="margin-top:14px" ${r.вид === 'служебная' ? 'open' : ''}>
    <summary class="cx-card-h"><h3>Разрешения роли</h3>
      ${locked ? '<span class="cx-pill grey">все разрешения всегда</span>' : ''}${own && !locked ? '<span class="cx-pill grey">ваша роль — менять нельзя</span>' : ''}</summary>
    <div class="cx-card-b">${groups}</div></details>`;
}

function acRolePeople(r) {
  const can = acCan('stages.assign') && r.код !== acLocked();
  const people = (AC.data.люди || []).filter((p) => p.активен && p.роль !== 'client' && p.роль !== acLocked());
  return `<div class="cx-card"><div class="cx-card-h"><h3>У кого есть роль</h3><span class="cx-hint">${nf(r.люди.length)}</span></div>
    <div class="cx-card-b"><div class="ac-chips">${people.map((p) => {
      const on = p.роли.includes(r.код);
      const main = p.роль === r.код;
      // отключённую роль можно только снять
      const ok = can && !main && p.логин !== AC.data.я && (on || !r.отключён);
      return `<label class="ac-chip ${on ? 'on' : ''} ${ok ? '' : 'ro'}">
        <input type="checkbox" data-ac-person-role="${esc(p.логин)}" data-code="${esc(r.код)}" ${on ? 'checked' : ''} ${ok ? '' : 'disabled'}>
        ${esc(p.ФИО)}${main ? ' · основная' : ''}</label>`;
    }).join('') || '<span class="cx-hint">Сотрудников нет</span>'}</div>
    ${r.отключён ? '<div class="cx-hint" style="margin-top:8px">Роль отключена — её можно только снять.</div>' : ''}</div></div>`;
}

function acLogHtml() {
  const log = (AC.data.журнал || []).map((e) => `<tr><td>${esc(e.дата)}</td><td>${esc(e.кто_фио || e.кто)}</td>
    <td>${esc(e.действие)}${e.право_название ? ': ' + esc(e.право_название) : ''}</td><td>${esc(e.кому)}</td>
    <td>${acLogVal(e.было)} → ${acLogVal(e.стало)}</td></tr>`).join('');
  return `<div class="cx-card"><div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px">
    <table class="cx-table cx-table-sm"><thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Кому</th><th>Было → стало</th></tr></thead>
    <tbody>${log || '<tr><td colspan="5" class="cx-empty">Пока пусто</td></tr>'}</tbody></table></div></div></div>`;
}

// ------------------------------------------------------------ действия
async function acPost(path, body, okText) {
  const res = await api(`${API}/access${path}`, { method: 'POST', body: JSON.stringify(body) });
  await loadAccess();
  render();
  if (okText) toast(okText, 'ok');
  return res;
}

async function acToggle(el) {
  const code = el.dataset.code;
  const want = el.checked;
  try {
    if (el.dataset.acPersonRole !== undefined) {
      const login = el.dataset.acPersonRole;
      await acPost('/roles', { логин: login, роль: code, можно: want },
        `${(acPerson(login) || {}).ФИО || login}: ${want ? '+' : '−'} ${acRoleName(code)}`);
      return;
    }
    const label = ((AC.data.каталог || []).find((c) => c.код === code) || {}).название || code;
    if (AC_IMPORTANT.has(code) && !confirm(`${want ? 'Выдать' : 'Забрать'} разрешение «${label}»?`)) { el.checked = !want; return; }
    if (el.dataset.acRolePerm !== undefined) {
      await acPost('/role', { роль: el.dataset.acRolePerm, право: code, значение: want },
        `${acRoleName(el.dataset.acRolePerm)}: ${want ? 'выдано' : 'забрано'} «${label}»`);
    } else if (el.dataset.acUserPerm !== undefined) {
      const login = el.dataset.acUserPerm;
      await acPost('/user', { логин: login, право: code, значение: want },
        `${(acPerson(login) || {}).ФИО || login}: ${want ? 'выдано' : 'забрано'} «${label}»`);
    }
  } catch (err) { el.checked = !want; toast(err.message, 'err'); }
}

document.addEventListener('change', (ev) => {
  const el = ev.target;
  if (!el || el.type !== 'checkbox') return;
  if (el.dataset.acPersonRole !== undefined || el.dataset.acRolePerm !== undefined || el.dataset.acUserPerm !== undefined) acToggle(el);
});

document.addEventListener('input', (ev) => {
  const t = ev.target;
  if (t && t.id === 'ac-q') {
    AC.q = t.value;
    const pos = t.selectionStart;
    render();
    const box = $('#ac-q');
    if (box) { box.focus(); box.setSelectionRange(pos, pos); }
  }
  // код новой роли подсказываем из названия, пока его не правили руками
  if (t && t.id === 'ac-nr-name') {
    const code = $('#ac-nr-code');
    if (code && !code.dataset.touched) code.value = t.value.toUpperCase().replace(/[^A-ZА-ЯЁ0-9]/g, '').slice(0, 12);
  }
  if (t && t.id === 'ac-nr-code') t.dataset.touched = '1';
});

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || !el.dataset.act.startsWith('ac-')) return;
  const act = el.dataset.act;
  try {
    if (act === 'ac-refresh') { await loadAccess(); render(); toast('Обновлено', 'ok'); }
    if (act === 'ac-sub') { AC.sub = el.dataset.sub; render(); }
    if (act === 'ac-person') {
      AC.person = el.dataset.login;
      render();
      if (window.innerWidth <= 860) { const card = document.querySelector('.ac-split > div:last-child'); if (card) card.scrollIntoView({ behavior: 'smooth' }); }
    }
    if (act === 'ac-role') { AC.role = el.dataset.role; render(); }
    if (act === 'ac-new-person') acNewPersonModal();
    if (act === 'ac-create-person') {
      const body = { ФИО: $('#ac-n-fio').value.trim(), логин: $('#ac-n-login').value.trim(),
        роль: $('#ac-n-role').value, пароль: $('#ac-n-pass').value };
      await acPost('/account', body, `Добавлен: ${body.ФИО}`);
      AC.person = body.логин; closeModal(); render();
    }
    if (act === 'ac-save-person') {
      const p = acPerson(el.dataset.login);
      const body = { логин: p.логин, ФИО: $('#ac-fio').value.trim(), роль: $('#ac-role').value };
      const pass = $('#ac-pass').value;
      if (pass) body.пароль = pass;
      if (body.роль !== p.роль && !confirm(`Сменить основную роль «${p.роль_название}» → «${acRoleName(body.роль)}»?`)) return;
      await acPost('/account', body, 'Сохранено');
    }
    if (act === 'ac-toggle-active') {
      const p = acPerson(el.dataset.login);
      const on = el.dataset.on === '1';
      if (!confirm(on ? `Включить ${p.ФИО}? Он снова сможет войти.` : `Отключить ${p.ФИО}? Он не сможет войти. Данные останутся.`)) return;
      await acPost('/account', { логин: p.логин, активен: on }, on ? 'Включён' : 'Отключён');
    }
    if (act === 'ac-user-reset') {
      await acPost('/user', { логин: el.dataset.login, право: el.dataset.code, значение: null }, 'Как у ролей');
    }
    if (act === 'ac-role-new') { AC.newRole = true; AC.sub = 'roles'; render(); $('#ac-nr-name').focus(); }
    if (act === 'ac-role-cancel') { AC.newRole = false; render(); }
    if (act === 'ac-role-create') {
      const body = { название: $('#ac-nr-name').value.trim(), код: $('#ac-nr-code').value.trim().toUpperCase(),
        ставка: $('#ac-nr-rate').value };
      await acPost('/stage', body, `Роль «${body.название}» создана`);
      AC.newRole = false; AC.role = body.код; render();
    }
    if (act === 'ac-role-save') {
      await acPost('/stage', { код: el.dataset.code, название: $('#ac-r-name').value.trim(),
        ставка: $('#ac-r-rate').value, порядок: $('#ac-r-order').value }, 'Роль сохранена');
    }
    if (act === 'ac-role-toggle') {
      const r = acRole(el.dataset.code);
      const off = el.dataset.off === '1';
      if (off && !confirm(`Отключить роль «${r.название}»? Начатые партии её пройдут, но новым людям и в новые маршруты её не добавить.`)) return;
      await acPost('/stage/toggle', { код: r.код, отключён: off }, off ? 'Роль отключена' : 'Роль включена');
    }
    if (act === 'ac-role-del') {
      const r = acRole(el.dataset.code);
      if (!confirm(`Удалить роль «${r.название}»? Она пропадёт у всех сотрудников.`)) return;
      await acPost('/stage/delete', { код: r.код }, 'Роль удалена');
      AC.role = null; await loadAccess(); render();
    }
  } catch (err) { toast(err.message, 'err'); }
});
