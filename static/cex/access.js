'use strict';

/* Модуль «Цех» · вкладки «Сотрудники», «Этапы», «Роли и права».
   Права системы (что человек может делать) и этапы (что он шьёт) — две независимые вещи.
   Кнопки скрываются по правам, но решает всегда сервер. Работает поверх cex.js. */

const AC = { data: null, person: null, role: 'technologist', q: '', stageOpen: null, newStage: false };

async function loadAccess() {
  AC.data = await api(`${API}/access`);
  const people = AC.data.люди || [];
  if (!people.find((p) => p.логин === AC.person)) AC.person = (people[0] || {}).логин || null;
}

function acCan(code) { return !!((AC.data && AC.data.мои_права) || {})[code]; }
function acPerson(login) { return ((AC.data && AC.data.люди) || []).find((p) => p.логин === login); }
function acStage(code) { return ((AC.data && AC.data.этапы) || []).find((s) => s.код === code); }
function acRoleName(r) { return ((AC.data && AC.data.роли_названия) || {})[r] || r; }

function acGroups() {
  const out = [];
  ((AC.data && AC.data.каталог) || []).forEach((c) => {
    let g = out.find((x) => x.name === c.группа);
    if (!g) { g = { name: c.группа, items: [] }; out.push(g); }
    g.items.push(c);
  });
  return out;
}

// важные права — переспрашиваем перед изменением
const AC_IMPORTANT = new Set(['perms.roles', 'perms.users', 'staff.delete', 'stages.delete', 'staff.add', 'staff.edit']);

function acSwitch(attrs, on, disabled, label) {
  return `<label class="ac-switch ${disabled ? 'off' : ''}">
    <input type="checkbox" ${attrs} ${on ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="${esc(label)}">
    <span class="ac-track"><span class="ac-knob"></span></span></label>`;
}

function acHero(title, sub, actions) {
  return `<div class="cx-hero compact"><div><h1>${title}</h1><div class="cx-sub">${sub}</div></div>
    <div class="cx-hero-actions">${actions || ''}<button class="btn" data-act="ac-refresh">Обновить</button></div></div>`;
}

function accessHtml(view) {
  if (!AC.data) return '<div class="cx-loading"><span class="cx-spin"></span> Загружаем…</div>';
  if (view === 'stages') return acStagesHtml();
  if (view === 'access') return acRolesHtml();
  return acStaffHtml();
}

// ------------------------------------------------------------ сотрудники
function acStaffHtml() {
  const q = AC.q.trim().toLowerCase();
  const people = (AC.data.люди || []).filter((p) => !q || p.ФИО.toLowerCase().includes(q) || p.логин.toLowerCase().includes(q));
  const list = people.map((p) => `
    <button class="ac-row ${p.логин === AC.person ? 'on' : ''} ${p.активен ? '' : 'dim'}" data-act="ac-person" data-login="${esc(p.логин)}">
      <span class="ac-row-main"><b>${esc(p.ФИО)}</b><span class="cx-hint">${esc(p.роль_название)}${p.активен ? '' : ' · отключён'}</span></span>
      <span class="ac-count" title="Этапов">${p.этапы.length ? nf(p.этапы.length) : '—'}</span>
    </button>`).join('');
  const add = acCan('staff.add') ? '<button class="btn primary" data-act="ac-new-person">+ Сотрудник</button>' : '';
  return `${acHero('Сотрудники', 'Карточка: роль, производственные этапы и личные права', add)}
    <div class="ac-split">
      <div class="cx-card ac-list">
        <div class="cx-card-b"><input class="input" id="ac-q" placeholder="Поиск по имени или логину" value="${esc(AC.q)}"></div>
        <div class="ac-rows">${list || '<div class="cx-empty" style="padding:16px">Никого не нашли</div>'}</div>
      </div>
      <div>${acCardHtml(acPerson(AC.person))}</div>
    </div>`;
}

function acCardHtml(p) {
  if (!p) return '<div class="cx-card"><div class="cx-empty"><b>Выберите сотрудника</b>Слева список цеха</div></div>';
  const me = p.логин === AC.data.я;
  const adminLocked = p.роль === AC.data.закрытая_роль && (ST.user || {}).роль !== AC.data.закрытая_роль;
  const canEdit = acCan('staff.edit') && !me && !adminLocked;
  const roles = Object.entries(AC.data.роли_названия || {});
  const stages = AC.data.этапы || [];
  const canStages = acCan('stages.assign');
  const stageChips = stages.map((s) => {
    const on = p.этапы.includes(s.код);
    return `<label class="ac-chip ${on ? 'on' : ''} ${canStages ? '' : 'ro'}">
      <input type="checkbox" data-ac-stage-person="${esc(p.логин)}" data-code="${esc(s.код)}" ${on ? 'checked' : ''} ${canStages ? '' : 'disabled'}>
      ${esc(s.название)}</label>`;
  }).join('');
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
          <div class="cx-field"><label>Роль</label><select class="input" id="ac-role" ${canEdit ? '' : 'disabled'}>
            ${roles.map(([k, v]) => `<option value="${k}" ${k === p.роль ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
          <div class="cx-field"><label>Новый пароль</label><input class="input" id="ac-pass" type="password" autocomplete="new-password" placeholder="не менять" ${canEdit ? '' : 'disabled'}></div>
        </div>
        ${p.роль !== AC.data.закрытая_роль ? `<div class="cx-field" style="margin-top:12px"><label>Дополнительные роли</label>
          <div class="ac-chips">${roles.filter(([k]) => k !== p.роль && k !== AC.data.закрытая_роль && k !== 'client').map(([k, v]) => {
            const on = (p.доп_роли || []).includes(k);
            return `<label class="ac-chip ${on ? 'on' : ''} ${canEdit ? '' : 'ro'}">
              <input type="checkbox" data-ac-extra-role="${esc(p.логин)}" data-code="${esc(k)}" ${on ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>${esc(v)}</label>`;
          }).join('')}</div>
          <div class="cx-hint" style="margin-top:6px">Если человек делает несколько работ — отметьте их. Права складываются, в цехе он выбирает «Работаю как». Сохраняется сразу.</div></div>` : ''}
        ${me ? '<div class="cx-hint">Свою роль, пароль и права здесь менять нельзя — это делает другой администратор.</div>' : ''}
        ${adminLocked ? '<div class="cx-hint">Карточку начальника (администратора) меняет только начальник.</div>' : ''}
        <div class="cx-btn-row" style="margin-top:12px">
          ${canEdit ? `<button class="btn primary" data-act="ac-save-person" data-login="${esc(p.логин)}">Сохранить</button>` : ''}
          ${!me && !adminLocked && (p.активен ? acCan('staff.delete') : acCan('staff.edit'))
            ? `<button class="btn ghost ${p.активен ? 'danger' : ''}" data-act="ac-toggle-active" data-login="${esc(p.логин)}" data-on="${p.активен ? 0 : 1}">${p.активен ? 'Отключить' : 'Включить снова'}</button>` : ''}
        </div>
      </div>
    </div>
    <div class="cx-card">
      <div class="cx-card-h"><h3>Производственные этапы</h3><span class="cx-hint">${p.этапы.length ? `${nf(p.этапы.length)} из ${nf(stages.length)}` : 'не назначены — работы на этапах нет'}</span></div>
      <div class="cx-card-b">
        <div class="ac-chips">${stageChips || '<span class="cx-hint">Этапов пока нет</span>'}</div>
        <div class="cx-hint" style="margin-top:8px">${canStages ? 'Отметьте все этапы, которые человек выполняет. Каждый сохраняется сразу и не влияет на остальные.' : 'Назначать этапы может сотрудник с правом «Назначение этапов сотрудникам».'}</div>
      </div>
    </div>
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
              ${can && mine ? `<button class="btn ghost ac-mini" data-act="ac-user-reset" data-login="${esc(p.логин)}" data-code="${esc(c.код)}">как у роли</button>` : ''}` : ''}
          </div>
          ${acSwitch(`data-ac-user-perm="${esc(p.логин)}" data-code="${esc(c.код)}"`, v.значение, !can || !mine, c.название)}
        </div>`;
      }).join('')}
    </div>`).join('');
  return `<details class="cx-card ac-perms" ${extra.length ? 'open' : ''}>
    <summary class="cx-card-h"><h3>Права в системе</h3>
      <span class="cx-hint">по роли «${esc(p.роль_название)}»${extra.length ? ` · личных настроек: ${nf(extra.length)}` : ''}</span></summary>
    <div class="cx-card-b">
      <div class="cx-hint" style="margin-bottom:10px">Личная настройка меняет права только этого человека. Остальные с ролью «${esc(p.роль_название)}» не затрагиваются.
        ${can ? 'Выдать или забрать можно только то право, которое есть у вас самих.' : ''}</div>
      ${groups}
    </div></details>`;
}

function acNewPersonModal() {
  const roles = Object.entries(AC.data.роли_названия || {});
  const modal = $('#cx-modal');
  modal.innerHTML = `<div class="cx-modal-box">
    <div class="cx-modal-h"><h3>Новый сотрудник</h3><button class="btn cx-close" data-act="close-modal">Закрыть</button></div>
    <div class="cx-modal-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>ФИО</label><input class="input" id="ac-n-fio" autocomplete="off"></div>
        <div class="cx-field"><label>Логин для входа</label><input class="input" id="ac-n-login" autocomplete="off" placeholder="например, aliya"></div>
        <div class="cx-field"><label>Роль</label><select class="input" id="ac-n-role">
          ${roles.map(([k, v]) => `<option value="${k}" ${k === 'user' ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
        <div class="cx-field"><label>Пароль</label><input class="input" id="ac-n-pass" type="password" autocomplete="new-password"></div>
      </div>
      <div class="cx-hint" style="margin-top:8px">Сотрудник попадёт в лист «сотрудники» рабочей книги и сразу сможет войти. Этапы назначите в его карточке.</div>
      <div class="cx-btn-row" style="margin-top:16px"><button class="btn primary" data-act="ac-create-person">Добавить</button></div>
    </div></div>`;
  modal.hidden = false;
  $('#ac-n-fio').focus();
}

// ------------------------------------------------------------ этапы
function acStagesHtml() {
  const stages = AC.data.этапы || [];
  const people = (AC.data.люди || []).filter((p) => p.активен && p.роль !== 'client');
  const canAssign = acCan('stages.assign');
  const cards = stages.map((s) => {
    const open = AC.stageOpen === s.код;
    const who = s.люди.map((l) => (acPerson(l) || { ФИО: l }).ФИО);
    return `<div class="cx-card ac-stage ${open ? 'open' : ''}">
      <button class="ac-stage-h" data-act="ac-stage-open" data-code="${esc(s.код)}" aria-expanded="${open}">
        <span class="ac-arrow" aria-hidden="true"></span>
        <span class="ac-stage-title"><b>${esc(s.название)}</b><span class="cx-hint">${esc(s.код)} · ${nf(s.ставка)} сом/шт</span></span>
        <span class="ac-stage-who">${who.length ? `${nf(who.length)} чел.` : '<span class="cx-warn">никого</span>'}</span>
      </button>
      <div class="ac-collapse"><div class="ac-collapse-in"><div class="cx-card-b">
        ${acCan('stages.edit') ? `<div class="cx-formgrid ac-form">
          <div class="cx-field"><label>Название</label><input class="input" id="ac-s-name-${esc(s.код)}" value="${esc(s.название)}"></div>
          <div class="cx-field"><label>Ставка, сом/шт</label><input class="input" id="ac-s-rate-${esc(s.код)}" type="number" min="0" step="0.5" value="${esc(s.ставка)}"></div>
          <div class="cx-field"><label>Порядок</label><input class="input" id="ac-s-order-${esc(s.код)}" type="number" value="${esc(s.порядок)}"></div>
        </div>
        <div class="cx-btn-row" style="margin:10px 0 14px">
          <button class="btn primary" data-act="ac-stage-save" data-code="${esc(s.код)}">Сохранить</button>
          ${acCan('stages.delete') ? `<button class="btn ghost danger" data-act="ac-stage-del" data-code="${esc(s.код)}" ${s.используется ? `disabled title="Используется: ${esc(s.используется)}"` : ''}>Удалить</button>` : ''}
          ${s.используется ? `<span class="cx-hint">используется: ${esc(s.используется)} — удалить нельзя</span>` : ''}
        </div>` : ''}
        <div class="cx-field"><label>Кто выполняет этот этап</label>
          <div class="ac-chips">${people.map((p) => {
            const on = s.люди.includes(p.логин);
            return `<label class="ac-chip ${on ? 'on' : ''} ${canAssign ? '' : 'ro'}">
              <input type="checkbox" data-ac-stage-person="${esc(p.логин)}" data-code="${esc(s.код)}" ${on ? 'checked' : ''} ${canAssign ? '' : 'disabled'}>
              ${esc(p.ФИО)}</label>`;
          }).join('') || '<span class="cx-hint">Сотрудников нет</span>'}</div>
        </div>
      </div></div></div>
    </div>`;
  }).join('');
  const add = acCan('stages.create') ? '<button class="btn primary" data-act="ac-stage-new">+ Этап</button>' : '';
  const form = AC.newStage ? `<div class="cx-card"><div class="cx-card-h"><h3>Новый этап</h3></div><div class="cx-card-b">
    <div class="cx-formgrid ac-form">
      <div class="cx-field"><label>Название</label><input class="input" id="ac-ns-name" placeholder="например, Петля"></div>
      <div class="cx-field"><label>Код</label><input class="input" id="ac-ns-code" placeholder="ПЕТЛЯ" maxlength="12"></div>
      <div class="cx-field"><label>Ставка, сом/шт</label><input class="input" id="ac-ns-rate" type="number" min="0" step="0.5" value="0"></div>
    </div>
    <div class="cx-hint">Код — коротко заглавными, по нему этап хранится в Excel. Чтобы этап появился в работе, добавьте его в маршрут.</div>
    <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="ac-stage-create">Создать</button>
      <button class="btn ghost" data-act="ac-stage-cancel">Отмена</button></div></div></div>` : '';
  return `${acHero('Производственные этапы', 'Каждый этап — отдельный доступ. Человек видит и берёт работу только на своих этапах', add)}
    ${form}${cards || '<div class="cx-card"><div class="cx-empty"><b>Этапов нет</b>Создайте первый этап</div></div>'}`;
}

// ------------------------------------------------------------ роли
function acRolesHtml() {
  const roles = AC.data.роли || [];
  if (!roles.length) return `${acHero('Роли и права', '')}<div class="cx-card"><div class="cx-empty"><b>Нет доступа</b>Права настраивает администратор</div></div>`;
  const cur = roles.find((r) => r.код === AC.role) || roles[0];
  AC.role = cur.код;
  const locked = cur.код === AC.data.закрытая_роль;
  const own = cur.код === (ST.user || {}).роль;
  const can = acCan('perms.roles') && !locked && !own;
  const chips = roles.map((r) => `<button class="rt-chip ${r.код === cur.код ? 'on' : ''}" data-act="ac-role" data-role="${esc(r.код)}">
    ${esc(r.название)} <span>${nf(r.люди.length)}</span></button>`).join('');
  const groups = acGroups().map((g) => {
    const on = g.items.filter((c) => cur.права[c.код]).length;
    return `<div class="ac-group"><div class="ac-group-h">${esc(g.name)} <span class="cx-hint">${nf(on)} из ${nf(g.items.length)}</span></div>
      ${g.items.map((c) => `<div class="ac-perm"><div class="ac-perm-main"><span>${esc(c.название)}</span></div>
        ${acSwitch(`data-ac-role-perm="${esc(cur.код)}" data-code="${esc(c.код)}"`, cur.права[c.код], !can || !acCan(c.код), c.название)}</div>`).join('')}
    </div>`;
  }).join('');
  const people = cur.люди.map((l) => acPerson(l)).filter(Boolean);
  const log = (AC.data.журнал || []).map((e) => `<tr><td>${esc(e.дата)}</td><td>${esc(e.кто_фио || e.кто)}</td>
    <td>${esc(e.действие)}${e.право_название ? ': ' + esc(e.право_название) : ''}</td><td>${esc(e.кому)}</td>
    <td>${acLogVal(e.было)} → ${acLogVal(e.стало)}</td></tr>`).join('');
  return `${acHero('Роли и права', 'Права роли — стандарт для всех с этой ролью. Отдельному сотруднику права меняются в его карточке')}
    <div class="ac-rolechips">${chips}</div>
    <div class="ac-split">
      <div class="cx-card">
        <div class="cx-card-h"><h3>${esc(cur.название)}</h3>
          ${locked ? '<span class="cx-pill grey">все права всегда — не настраивается</span>' : ''}
          ${own && !locked ? '<span class="cx-pill grey">ваша роль — менять нельзя</span>' : ''}</div>
        <div class="cx-card-b">${groups}</div>
      </div>
      <div>
        <div class="cx-card"><div class="cx-card-h"><h3>С этой ролью</h3><span class="cx-hint">${nf(people.length)}</span></div>
          <div class="cx-card-b">${people.map((p) => `<button class="ac-row ${p.активен ? '' : 'dim'}" data-act="ac-open-person" data-login="${esc(p.логин)}">
            <span class="ac-row-main"><b>${esc(p.ФИО)}</b><span class="cx-hint">${esc(p.логин)}${Object.values(p.права || {}).some((v) => v.индивидуально) ? ' · есть личные права' : ''}</span></span></button>`).join('')
            || '<span class="cx-hint">Никого</span>'}</div></div>
        <details class="cx-card"><summary class="cx-card-h"><h3>Журнал изменений</h3><span class="cx-hint">${nf((AC.data.журнал || []).length)}</span></summary>
          <div class="cx-card-b" style="padding-bottom:0"><div class="cx-scroll" style="margin:0 -18px;max-height:420px">
            <table class="cx-table cx-table-sm"><thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Кому</th><th>Было → стало</th></tr></thead>
            <tbody>${log || '<tr><td colspan="5" class="cx-empty">Пока пусто</td></tr>'}</tbody></table></div></div></details>
      </div>
    </div>`;
}

function acLogVal(v) {
  if (v === true) return 'да';
  if (v === false) return 'нет';
  return esc(v === undefined || v === null || v === '' ? '—' : v);
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
  const label = ((AC.data.каталог || []).find((c) => c.код === code) || {}).название || code;
  const want = el.checked;
  try {
    if (el.dataset.acStagePerson !== undefined) {
      const login = el.dataset.acStagePerson;
      await api(`${API}/staff/roles`, { method: 'POST', body: JSON.stringify({ логин: login, этап: code, можно: want }) });
      await loadAccess(); render();
      toast(`${(acPerson(login) || {}).ФИО || login}: ${want ? '+' : '−'} ${(acStage(code) || {}).название || code}`, 'ok');
      return;
    }
    if (el.dataset.acExtraRole !== undefined) {
      const login = el.dataset.acExtraRole;
      const cur = (acPerson(login) || {}).доп_роли || [];
      const next = want ? [...cur, code] : cur.filter((r) => r !== code);
      await acPost('/roles', { логин: login, роли: next },
        `${(acPerson(login) || {}).ФИО || login}: ${want ? '+' : '−'} ${acRoleName(code)}`);
      return;
    }
    if (AC_IMPORTANT.has(code) && !confirm(`${want ? 'Выдать' : 'Забрать'} право «${label}»?`)) { el.checked = !want; return; }
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
  if (el.dataset.acStagePerson !== undefined || el.dataset.acExtraRole !== undefined || el.dataset.acRolePerm !== undefined || el.dataset.acUserPerm !== undefined) acToggle(el);
});

document.addEventListener('input', (ev) => {
  if (ev.target && ev.target.id === 'ac-q') {
    AC.q = ev.target.value;
    const pos = ev.target.selectionStart;
    render();
    const box = $('#ac-q');
    if (box) { box.focus(); box.setSelectionRange(pos, pos); }
  }
});

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || !el.dataset.act.startsWith('ac-')) return;
  const act = el.dataset.act;
  try {
    if (act === 'ac-refresh') { await loadAccess(); render(); toast('Обновлено', 'ok'); }
    if (act === 'ac-person') {
      AC.person = el.dataset.login;
      render();
      if (window.innerWidth <= 860) { const card = document.querySelector('.ac-split > div:last-child'); if (card) card.scrollIntoView({ behavior: 'smooth' }); }
    }
    if (act === 'ac-open-person') { AC.person = el.dataset.login; ST.view = 'staff'; render(); window.scrollTo(0, 0); }
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
      if (body.роль !== p.роль && !confirm(`Сменить роль «${p.роль_название}» → «${acRoleName(body.роль)}»? Права изменятся по новой роли.`)) return;
      await acPost('/account', body, 'Сохранено');
    }
    if (act === 'ac-toggle-active') {
      const p = acPerson(el.dataset.login);
      const on = el.dataset.on === '1';
      if (!confirm(on ? `Включить ${p.ФИО}? Он снова сможет войти.` : `Отключить ${p.ФИО}? Он не сможет войти. Данные останутся.`)) return;
      await acPost('/account', { логин: p.логин, активен: on }, on ? 'Включён' : 'Отключён');
    }
    if (act === 'ac-user-reset') {
      await acPost('/user', { логин: el.dataset.login, право: el.dataset.code, значение: null }, 'Как у роли');
    }
    if (act === 'ac-stage-open') {  // без перерисовки — плавно раскрывается
      AC.stageOpen = AC.stageOpen === el.dataset.code ? null : el.dataset.code;
      document.querySelectorAll('.ac-stage').forEach((c) => {
        const h = c.querySelector('.ac-stage-h');
        const on = h && h.dataset.code === AC.stageOpen;
        c.classList.toggle('open', on);
        if (h) h.setAttribute('aria-expanded', String(on));
      });
    }
    if (act === 'ac-stage-new') { AC.newStage = true; render(); $('#ac-ns-name').focus(); }
    if (act === 'ac-stage-cancel') { AC.newStage = false; render(); }
    if (act === 'ac-stage-create') {
      const body = { название: $('#ac-ns-name').value.trim(), код: $('#ac-ns-code').value.trim().toUpperCase(),
        ставка: $('#ac-ns-rate').value };
      await acPost('/stage', body, `Этап «${body.название}» создан`);
      AC.newStage = false; AC.stageOpen = body.код; render();
    }
    if (act === 'ac-stage-save') {
      const c = el.dataset.code;
      await acPost('/stage', { код: c, название: $(`#ac-s-name-${CSS.escape(c)}`).value.trim(),
        ставка: $(`#ac-s-rate-${CSS.escape(c)}`).value, порядок: $(`#ac-s-order-${CSS.escape(c)}`).value }, 'Этап сохранён');
    }
    if (act === 'ac-stage-del') {
      const s = acStage(el.dataset.code);
      if (!confirm(`Удалить этап «${s.название}»? Он пропадёт у всех сотрудников.`)) return;
      await acPost('/stage/delete', { код: s.код }, 'Этап удалён');
    }
  } catch (err) { toast(err.message, 'err'); }
});

document.addEventListener('input', (ev) => {
  // код нового этапа подсказываем из названия, пока его не правили руками
  if (ev.target && ev.target.id === 'ac-ns-name') {
    const code = $('#ac-ns-code');
    if (code && !code.dataset.touched) code.value = ev.target.value.toUpperCase().replace(/[^A-ZА-ЯЁ0-9]/g, '').slice(0, 12);
  }
  if (ev.target && ev.target.id === 'ac-ns-code') ev.target.dataset.touched = '1';
});
