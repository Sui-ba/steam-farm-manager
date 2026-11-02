const $ = s => document.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag); let val;
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'value') val = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, '');
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : String(c));
  if (val !== undefined) e.value = val;
  return e;
};
const S = { accounts: [], proxies: [], stats: {}, settings: {}, tab: 'Дашборд', q: '', sa: null, sp: null, sb: null, asf: null, sel: new Set(), cards: [], wt: 'Чек-лист', cs: new Set() };
S.hosts = new Set(JSON.parse(localStorage.getItem('hosts') || '[]')); S.per = +localStorage.getItem('per') || 15; S.activity = [];
const MODES = [['Авто', 'auto'], ['Светлая', 'light'], ['Тёмная', 'dark']];
const mode = () => localStorage.getItem('theme') || 'auto';

async function api(path, body) {
  const r = await fetch('/api/' + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'sfm' }, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}
function toast(t, bad) { const e = h('div', { class: 'toast' + (bad ? ' bad' : ''), role: 'status' }, t); document.body.append(e); setTimeout(() => e.remove(), 4500); }
const act = async fn => { try { await fn(); } catch (e) { toast(e.message, true); } };
const load = async () => { Object.assign(S, await api('state')); S.cards = (await api('cards')).cards; S.activity = (await api('activity')).items; render(); };
const money = n => '$' + Number(n || 0).toFixed(2);

function applyTheme() {
  const dark = mode() === 'dark' || (mode() === 'auto' && matchMedia('(prefers-color-scheme:dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
matchMedia('(prefers-color-scheme:dark)').addEventListener('change', applyTheme);

const btn = (label, kind, fn) => h('button', { type: 'button', class: 'btn ' + kind, onclick: fn }, label);
const fld = (label, el) => h('label', { class: 'f' }, h('span', { class: 'm' }, label), el);
function modal(title, content, actions) {
  const d = $('#dlg');
  d.replaceChildren(h('div', { class: 'dg' }, h('h2', {}, title), content, h('div', { class: 'r end' }, actions.map(([l, k, fn]) => btn(l, k, fn)))));
  d.showModal();
}
const closeM = () => $('#dlg').close();

function table(heads, items, sel, cells, pick, edit) {
  return h('div', { class: 'card tbl' }, h('table', {}, h('thead', {}, h('tr', {}, heads.map(x => h('th', {}, x)))),
    h('tbody', {}, items.map(it => h('tr', { class: it.id === sel ? 'sel' : '', onclick: () => pick(it.id), ondblclick: () => edit(it) }, cells(it).map(c => h('td', {}, c)))))));
}
const dotCls = s => s === 'онлайн' ? 'ok' : (s.includes('пауза') || s === 'запускается') ? 'warn' : '';
function asfBadge(short) {
  const a = S.asf;
  return h('span', { class: 'r m' }, h('span', { class: 'dot ' + (a && a.ipc ? 'ok' : a && a.running ? 'warn' : '') }),
    !a ? '…' : a.ipc ? (short ? 'Запущен' : 'Запущен · IPC ' + a.base) : a.running ? 'Запущен, IPC недоступен' : 'Остановлен');
}

const aqIn = h('input', { class: 'in search', placeholder: 'Поиск по ботам…', 'aria-label': 'Поиск ботов', oninput: () => { S.aq = aqIn.value; render(); aqIn.focus(); } });
const mainSel = () => h('select', { class: 'sel', 'aria-label': 'Главный аккаунт', onchange: e => act(async () => { await api('main', { id: +e.target.value }); await load(); }) }, h('option', { value: '' }, '— не выбран —'), S.accounts.map(a => h('option', { value: a.id, selected: !!a.is_main }, a.login)));
const qIn = h('input', { class: 'in search', placeholder: 'Поиск по логину, ID, почте', 'aria-label': 'Поиск', oninput: () => { S.q = qIn.value; render(); qIn.focus(); } });
const cmdIn = h('input', { class: 'in', style: 'flex:1', placeholder: 'Команда ASF, например: status ASF', 'aria-label': 'Команда ASF', onkeydown: e => e.key === 'Enter' && sendCmd() });
const con = h('pre', { class: 'con' });
const log = t => { con.textContent += t.trim() + '\n'; con.scrollTop = con.scrollHeight; };
const sendCmd = () => act(async () => {
  const v = cmdIn.value.trim(); if (!v) return; cmdIn.value = ''; log('> ' + v);
  log((await api('asf/command', { command: v })).result);
});

const IC = { home: 'M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z', users: 'M16 20v-1a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v1M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M20 20v-1a4 4 0 0 0-3-3.9', bot: 'M5 8h14v11H5zM12 4v4M9 13h.01M15 13h.01M9 16h6', globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18', flame: 'M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9', award: 'M12 14a5 5 0 1 0 0-10 5 5 0 0 0 0 10M8.5 13.5L7 21l5-3 5 3-1.5-7.5', cards: 'M7 4h10a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1M10 9h4', send: 'M22 2L11 13M22 2l-7 20-4-9-9-4z', chart: 'M4 19V5M4 19h16M8 16l3-4 3 2 4-7', key: 'M15 7a4 4 0 1 1-3 6.5L4 21v-3h3v-3h3', user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21a8 8 0 0 1 16 0', lock: 'M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3', box: 'M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10', coin: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v10M9.5 9.5h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4', bolt: 'M13 2L4 14h7l-1 8 9-12h-7z', pause: 'M8 5v14M16 5v14', play: 'M7 4l13 8-13 8z', stop: 'M6 6h12v12H6z', power: 'M12 3v9M6.3 7a8 8 0 1 0 11.4 0', pulse: 'M3 12h4l3-8 4 16 3-8h4', shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', plus: 'M12 5v14M5 12h14', x: 'M6 6l12 12M18 6L6 18', check: 'M5 12l5 5 9-10' };
const ico = n => { const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), p = document.createElementNS(NS, 'path'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true'); p.setAttribute('d', IC[n] || IC.bolt); s.append(p); return s; };
const PRESETS = [
  { id: 'pause', name: 'Пауза', desc: 'Приостановить фарм', action: 'Pause', color: '#ff9f0a', icon: 'pause' },
  { id: 'resume', name: 'Продолжить', desc: 'Продолжить фарм карточек', action: 'Resume', color: '#30d158', icon: 'play' },
  { id: 'start', name: 'Запустить', desc: 'Включить бота', action: 'Start', color: '#0a84ff', icon: 'power' },
  { id: 'stop', name: 'Остановить', desc: 'Выключить бота', action: 'Stop', color: '#ff453a', icon: 'stop', confirm: true },
  { id: 'hours', name: 'Фарм часов', desc: 'Накрутка часов в игре', command: 'play {bots} {ask:AppID игры (730 — CS2)}', color: '#0a84ff', icon: 'play' },
  { id: 'games', name: 'Добавить игры', desc: 'Бесплатные игры в библиотеку', command: 'addlicense {bots} {ask:AppID или sub/ID}', color: '#bf5af2', icon: 'plus' },
  { id: 'redeem', name: 'Ключ / код', desc: 'Ключ игры или код пополнения', command: 'redeem {bots} {ask:Ключ или код}', color: '#ff9f0a', icon: 'key' },
  { id: 'nick', name: 'Сменить ник', desc: 'Никнейм профиля', command: 'nickname {bot} {ask:Новый ник}', color: '#32ade6', icon: 'user' },
  { id: 'privacy', name: 'Приватность', desc: 'Настройки профиля', command: 'privacy {bots} {ask:Настройки (например Public или Private)}', color: '#ff453a', icon: 'lock' },
  { id: 'points', name: 'Баланс поинтов', desc: 'Steam Points', command: 'points {bots}', color: '#ffd60a', icon: 'coin' },
  { id: 'inv', name: 'Инвентарь', desc: 'Сводка по инвентарю', command: 'inventory {bots}', color: '#bf5af2', icon: 'box' },
  { id: 'give', name: 'Передать главному', desc: 'Предметы на главный', transfer: true, confirm: true, color: '#ff9f0a', icon: 'send' },
  { id: 'trades', name: 'Трейды', desc: 'Подтвердить обмены', command: '2faok {bots}', color: '#ff375f', icon: 'cards' },
  { id: 'status', name: 'Статус', desc: 'Состояние в консоль', command: 'status {bots}', color: '#bf5af2', icon: 'pulse' },
  { id: '2fa', name: 'Код 2FA', desc: 'Код Steam Guard', command: '2fa {bots}', color: '#64d2ff', icon: 'shield' },
  { id: 'bal', name: 'Баланс и лвл', desc: 'Обновить в таблице', refresh: true, color: '#32ade6', icon: 'coin' }];
const COLORS = ['#0a84ff', '#30d158', '#ff9f0a', '#ff453a', '#bf5af2', '#64d2ff'];
const farming = b => /^\d+$/.test(b.cards) && +b.cards > 0;
const activity = b => b.state === 'онлайн' ? (farming(b) ? 'Фармит карточки' : 'Онлайн, ждёт') : b.state.includes('пауза') ? 'На паузе' : b.state === 'запускается' ? 'Запускается' : 'Остановлен';
const tone = b => b.state === 'онлайн' ? (farming(b) ? 'farm' : 'ok') : b.state.includes('пауза') ? 'pause' : b.state === 'запускается' ? 'boot' : 'off';
const accOf = b => S.accounts.find(a => a.login.toLowerCase() === (b.login || '').toLowerCase());
const wl = b => { const a = accOf(b); return a && (a.balance || a.level != null) ? h('span', { class: 'wl' }, (a.balance || '—') + ' · ур. ' + (a.level ?? '—')) : null; };
function botTile(b) {
  const on = S.sel.has(b.name);
  return h('button', { type: 'button', class: `tile ${tone(b)}${on ? ' on' : ''}`, 'aria-pressed': String(on), onclick: () => { on ? S.sel.delete(b.name) : S.sel.add(b.name); render(); } },
    h('span', { class: 'chk' }, on ? ico('check') : null), h('span', { class: 'av' }, (b.name.split(/[_\-\s]/).pop() || b.name)[0].toUpperCase()), h('b', {}, b.name), h('span', { class: 'm' }, b.login || '—'),
    h('span', { class: 'chip' }, activity(b)), h('span', { class: 'cn' }, h('i', {}, b.cards), ' карточек осталось'), wl(b), h('span', { class: 'm' }, b.proxy || 'без прокси'));
}
function asfCard() {
  const bots = S.asf ? S.asf.bots : [], n = (...k) => bots.filter(b => k.includes(tone(b))).length;
  const on = n('farm', 'ok', 'boot'), pa = n('pause'), off = bots.length - on - pa;
  return h('div', { class: 'card pad asfc' }, h('div', { class: 'r sb', style: 'width:100%' }, h('h2', { style: 'margin:0' }, 'ArchiSteamFarm'), asfBadge(true)),
    h('div', { class: 'trio' }, [['онлайн', on, 'ok'], ['на паузе', pa, 'pause'], ['офлайн', off, 'off']].map(([l, v, c]) => h('div', { class: 'mini ' + c }, h('b', {}, v), h('span', {}, l)))),
    h('div', { class: 'stack' }, [[on, 'ok'], [pa, 'pause'], [off, 'off']].map(([v, c]) => h('i', { class: c, style: `flex:${v}` }))),
    h('code', { class: 'ipc' }, 'IPC ' + (S.asf ? S.asf.base : '—')), btn('Открыть ASF', 'p', () => { S.tab = 'ASF'; render(); }));
}
function actionsDlg(names) {
  const run = c => act(async () => {
    if (c.confirm && !confirm(`${c.name}: ${names.length} акк.?`)) return;
    if (c.refresh) { const u = await api('refresh', { bots: names }); closeM(); toast(`Обновлено: ${u.updated} из ${u.bots}`); await load(); return; }
    let cmd = c.command;
    if (c.transfer) {
      const m = S.accounts.find(x => x.is_main), mb = m && (S.asf ? S.asf.bots : []).find(b => (b.login || '').toLowerCase() === m.login.toLowerCase());
      if (!mb) throw new Error('Выбери главный аккаунт, он должен быть в ASF'); cmd = 'transfer {bots} ' + mb.name; names = names.filter(n => n !== mb.name);
      if (!names.length) throw new Error('Кроме главного никого не выбрано');
    }
    for (const m of [...(cmd || '').matchAll(/\{ask:([^}]+)\}/g)]) { const v = prompt(m[1]); if (v === null) return; cmd = cmd.replace(m[0], v.trim()); }
    const r = await api('asf/run', { bots: names, action: c.action, command: cmd });
    S.activity = (await api('activity')).items;
    closeM(); log(`> ${c.name}: ${names.join(', ')}`); log(r.result); toast(`${c.name}: готово (${names.length})`); setTimeout(pollAsf, 1200);
  });
  const tile = (c, custom) => h('div', { class: 'act', style: `--c:${c.color}` },
    h('button', { type: 'button', class: 'actb', onclick: () => run(c) }, h('span', { class: 'ai' }, ico(c.icon)), h('b', {}, c.name), h('span', { class: 'm' }, c.desc || c.command)),
    custom && h('button', { type: 'button', class: 'rm', 'aria-label': 'Удалить карточку', onclick: () => confirm(`Удалить карточку «${c.name}»?`) && act(async () => { S.cards = S.cards.filter(x => x.id !== c.id); await api('cards', { cards: S.cards }); actionsDlg(names); }) }, ico('x')));
  modal(`Действия · ${names.length} акк.`, h('div', { class: 'acts' }, PRESETS.map(c => tile(c)), S.cards.map(c => tile({ ...c, icon: 'bolt' }, true)),
    h('button', { type: 'button', class: 'act new', onclick: () => cardDlg(names) }, ico('plus'), h('b', {}, 'Своя карточка'), h('span', { class: 'm' }, 'Своя команда ASF'))), [['Закрыть', '', closeM]]);
}
function cardDlg(names) {
  const nm = h('input', { class: 'in', placeholder: 'Например: CS2 на 10 минут', maxlength: 40 }), cmd = h('input', { class: 'in', placeholder: 'play {bots} 730' }), cf = h('input', { type: 'checkbox' });
  const cols = COLORS.map((c, i) => h('label', { class: 'sw' }, h('input', { type: 'radio', name: 'col', value: c, checked: i === 0 }), h('span', { style: `background:${c}` })));
  modal('Новая карточка', h('div', { class: 'col' }, fld('Название', nm), fld('Команда ASF', cmd),
    h('div', { class: 'm' }, '{bots} — все выбранные через запятую, {bot} — команда отдельно для каждого, {ask:Вопрос} — спросить значение при запуске.'), h('div', { class: 'r' }, cols), h('label', { class: 'r' }, cf, 'Спрашивать подтверждение')),
    [['Назад', '', () => actionsDlg(names)], ['Создать', 'p', () => act(async () => {
      if (!nm.value.trim() || !cmd.value.trim()) throw new Error('Нужны название и команда');
      S.cards.push({ id: Date.now().toString(36), name: nm.value.trim(), command: cmd.value.trim(), color: cols.map(l => l.firstChild).find(r => r.checked).value, confirm: cf.checked });
      await api('cards', { cards: S.cards }); actionsDlg(names);
    })]]);
}

const views = {
  'Дашборд'() {
    const bots = S.asf ? S.asf.bots : [], on = bots.filter(b => b.state.startsWith('онлайн')).length, farm = bots.filter(b => tone(b) === 'farm').length;
    const sums = {}; S.accounts.forEach(a => { const m = (a.balance || '').match(/([\d.]+)\s*([A-Z]{3})/); if (m) sums[m[2]] = (sums[m[2]] || 0) + +m[1]; });
    const wallet = Object.entries(sums).map(([c, v]) => v.toFixed(2) + ' ' + c).join(' · ') || '—';
    const lv = S.accounts.filter(a => a.level != null), avg = lv.length ? (lv.reduce((s, a) => s + a.level, 0) / lv.length).toFixed(1) : '—';
    const row = (l, v) => h('div', { class: 'ev' }, h('span', { class: 'm' }, l), h('b', {}, v));
    return h('div', { class: 'col' }, h('h1', {}, 'Дашборд'),
      h('div', { class: 'cards c4' }, [['Аккаунтов', S.accounts.length, ''], ['Онлайн', on, 'ok'], ['Фармят', farm, 'ok'], ['Баланс кошельков', wallet, 'sm']].map(([l, v, c]) => h('div', { class: 'card stat' }, h('div', { class: 'm' }, l), h('div', { class: 'num ' + c }, v)))),
      h('div', { class: 'two' },
        h('div', { class: 'card pad' }, h('h2', {}, 'Активность'), S.activity.length ? S.activity.slice(0, 7).map(x => h('div', { class: 'ev' }, h('span', {}, x.text), h('span', { class: 'm' }, x.t))) : h('div', { class: 'm' }, 'Пока пусто: действия из вкладки ASF появятся здесь')),
        h('div', { class: 'col' }, h('div', { class: 'card pad' }, h('h2', {}, 'Метрики'), row('Средний уровень', avg), row('С праймом', S.stats.prime_count || 0), row('Настроено', S.stats.configured_count || 0), row('Потрачено', money(S.stats.total_spent)), row('Доход', money(S.accounts.reduce((s, a) => s + (+a.income || 0), 0))), row('Дроп, шт.', S.accounts.reduce((s, a) => s + (+a.drops || 0), 0))), asfCard())));
  },
  'Аккаунты'() {
    const q = S.q.toLowerCase(), px = id => { const p = S.proxies.find(p => p.id === id); return p ? `${p.host}:${p.port}` : '—'; };
    const rows = S.accounts.filter(a => !q || `${a.login} ${a.steam_id} ${a.email}`.toLowerCase().includes(q));
    const cur = () => S.accounts.find(a => a.id === S.sa), need = fn => () => cur() ? fn(cur()) : toast('Сначала выбери аккаунт в таблице', true);
    const tick = v => v ? '✓' : '—';
    return h('div', { class: 'col' }, h('div', { class: 'r sb' }, h('h1', {}, 'Аккаунты'), qIn),
      h('div', { class: 'r' }, btn('Добавить', 'p', () => accountForm()), btn('Редактировать', '', need(accountForm)),
        btn('Удалить', 'd', need(a => confirm(`Удалить аккаунт «${a.login}»?`) && act(async () => { await api('account/delete', { id: a.id }); S.sa = null; await load(); }))),
        btn('Войти в браузере', '', need(a => act(async () => { await api('login', { id: a.id }); }))),
        btn('Главный ★', '', need(a => act(async () => { await api('main', { id: a.id }); await load(); }))),
        btn('Обновить баланс и лвл', '', () => act(async () => { const r = await api('refresh', {}); toast(`Обновлено: ${r.updated} из ${r.bots}`); await load(); })),
        h('span', { style: 'flex:1' }), btn('Импорт', '', () => exchangeDlg('accounts', 'import')), btn('Экспорт', '', () => exchangeDlg('accounts', 'export')),
        btn('Раздать прокси', '', assign), btn('Пути', '', settingsDlg)),
      h('div', { id: 'ls', class: 'm st' }),
      table(['ID', 'Логин', 'Баланс', 'Лвл', 'Настроен', 'Прайм', 'Без огр.', 'Потрачено', 'Почта', 'Прокси'], rows, S.sa,
        a => [a.id, (a.is_main ? '★ ' : '') + a.login, a.balance || '—', a.level ?? '—', tick(a.configured), tick(a.prime_bought), tick(a.restriction_lifted), money(a.spent), a.email || '—', px(a.proxy_id)],
        id => { S.sa = id; render(); }, accountForm));
  },
  'Прокси'() {
    const cur = () => S.proxies.find(p => p.id === S.sp), need = fn => () => cur() ? fn(cur()) : toast('Сначала выбери прокси в таблице', true);
    return h('div', { class: 'col' }, h('h1', {}, 'Прокси'), h('div', { class: 'cards c3' }, [['Всего', S.proxies.length], ['Используется', new Set(S.accounts.map(a => a.proxy_id).filter(Boolean)).size], ['Акк. на прокси', S.accounts.filter(a => a.proxy_id).length]].map(([l, v]) => h('div', { class: 'card stat' }, h('div', { class: 'm' }, l), h('div', { class: 'num' }, v)))),
      h('div', { class: 'r' }, btn('Добавить', 'p', () => proxyForm()), btn('Редактировать', '', need(proxyForm)),
        btn('Удалить', 'd', need(p => confirm(`Удалить прокси ${p.host}:${p.port}?`) && act(async () => { await api('proxy/delete', { id: p.id }); S.sp = null; await load(); }))),
        h('span', { style: 'flex:1' }), btn('Импорт', '', () => exchangeDlg('proxies', 'import')), btn('Экспорт', '', () => exchangeDlg('proxies', 'export')), btn('Раздать 1:1', '', assign), btn('В конфиг ASF', '', () => act(async () => {
          const r = await api('proxies/push', {});
          toast(`В ASF: обновлено ${r.updated.length}, без изменений ${r.skipped.length}` + (r.missing.length ? `\nНет бота: ${r.missing.slice(0, 5).join(', ')}` : ''));
        }))),
      table(['ID', 'Протокол', 'Хост', 'Порт', 'Логин', 'Акк.', 'Заметки'], S.proxies, S.sp,
        p => [p.id, p.protocol || 'http', p.host, p.port, p.username || '—', S.accounts.filter(a => a.proxy_id === p.id).length, p.notes || '—'], id => { S.sp = id; render(); }, proxyForm));
  },
  'ASF'() {
    const a = S.asf, bots = a ? a.bots : [], q = (S.aq || '').toLowerCase(), f = S.af || 'Все', on = s => s.startsWith('онлайн');
    const shown = bots.filter(b => (!q || (b.name + ' ' + (b.login || '')).toLowerCase().includes(q)) && (f === 'Все' || (f === 'Онлайн' && on(b.state)) || (f === 'Пауза' && b.state.includes('пауза')) || (f === 'Офлайн' && !on(b.state))));
    const names = bots.map(b => b.name).filter(n => S.sel.has(n)), conn = bots.filter(b => on(b.state)).length;
    const go = p => act(async () => { toast((await api(p, {})).message); setTimeout(pollAsf, 1500); });
    return h('div', { class: 'col' },
      h('div', { class: 'r sb' }, h('div', {}, h('h1', {}, 'Боты ASF'), h('div', { class: 'm' }, `${bots.length} ботов`)),
        h('div', { class: 'r' }, asfBadge(true), btn('Запустить', 'p', () => go('asf/start')), btn('Стоп', 'd', () => confirm('Остановить ArchiSteamFarm?') && go('asf/stop')), a ? h('a', { class: 'btn', href: a.base, target: '_blank', rel: 'noopener' }, 'IPC') : null, btn('Папка', '', settingsDlg))),
      h('div', { class: 'card pad r sb', style: 'flex-direction:row;align-items:center;padding:14px 20px' }, h('div', { class: 'r' }, h('b', {}, '★ Главный'), mainSel()), h('span', { class: 'm' }, 'Сюда передаются предметы')),
      h('div', { class: 'card pad', style: 'padding:14px 20px;gap:0;display:block' }, h('div', { class: 'r sb' }, h('span', {}, `${conn} / ${bots.length} подключено`), h('span', { class: 'm' }, `${bots.length - conn} офлайн`)), h('div', { class: 'trk' }, h('i', { style: `width:${bots.length ? conn * 100 / bots.length : 0}%` }))),
      h('div', { class: 'r' }, aqIn, h('select', { class: 'sel', 'aria-label': 'Фильтр', onchange: e => { S.af = e.target.value; render(); } }, ['Все', 'Онлайн', 'Пауза', 'Офлайн'].map(x => h('option', { value: x, selected: x === f }, x))),
        btn('Выбрать все', '', () => { S.sel = new Set(shown.map(b => b.name)); render(); }), btn('Снять', '', () => { S.sel.clear(); render(); })),
      shown.length ? h('div', { class: 'tiles' }, shown.map(botTile)) : h('div', { class: 'card pad m' }, S.asf ? 'Ботов нет или фильтр ничего не нашёл.' : 'Загрузка…'),
      h('div', { class: 'card pad col' }, h('div', { class: 'r' }, cmdIn, btn('Отправить', 'p', sendCmd)), con),
      h('div', { class: 'card abar' }, h('span', { class: names.length ? '' : 'm' }, names.length ? `Выбрано: ${names.length}` : 'Выберите аккаунты для действий'),
        h('button', { type: 'button', class: 'btn p big', disabled: !names.length, onclick: () => actionsDlg(names) }, ico('bolt'), 'Действия' + (names.length ? ' · ' + names.length : ''))));
  },
};

const out = h('pre', { class: 'con' });
const WARM = { 'Чек-лист': [['profile', 'Профиль заполнен'], ['avatar', 'Аватар и ник'], ['privacy', 'Приватность'], ['games', 'Игры в библиотеке'], ['hours', 'Часы в игре'], ['@prime_bought', 'Куплен прайм'], ['@restriction_lifted', 'Снято ограничение']],
  'Значок сообщества': [['b1', 'Вступить в группу'], ['b2', 'Оставить комментарий'], ['b3', 'Добавить друга'], ['b4', 'Написать обзор']] };
Object.assign(views, {
  'Прогрев'() {
    const all = JSON.parse(localStorage.getItem('warmSteps') || 'null') || WARM, list = all[S.wt] || [], save = () => { localStorage.setItem('warmSteps', JSON.stringify(all)); render(); };
    const done = (a, id) => id[0] === '@' ? !!a[id.slice(1)] : !!JSON.parse(a.warm || '{}')[id];
    const pct = a => list.length ? Math.round(list.filter(([id]) => done(a, id)).length * 100 / list.length) : 0;
    const toggle = (a, id, v) => act(async () => {
      let fields; if (id[0] === '@') fields = { [id.slice(1)]: v ? 1 : 0 }; else { const w = JSON.parse(a.warm || '{}'); w[id] = v; fields = { warm: JSON.stringify(w) }; }
      await api('fields', { id: a.id, fields }); await load();
    });
    return h('div', { class: 'col' }, h('div', { class: 'r sb' }, h('h1', {}, 'Прогрев'), h('nav', { class: 'seg' }, Object.keys(all).map(t => h('button', { class: t === S.wt ? 'on' : '', onclick: () => { S.wt = t; render(); } }, t)))),
      h('div', { class: 'm' }, 'Отмечай шаги по аккаунтам. Часы в игре: вкладка ASF → Действия → «CS2 часы». Шаги можно добавлять и убирать.'),
      h('div', { class: 'card tbl warm' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Аккаунт'), h('th', {}, 'Готово'), list.map(([id, t]) => h('th', {}, t, id.startsWith('x_') ? h('button', { class: 'rm2', 'aria-label': 'Убрать шаг', onclick: () => { all[S.wt] = list.filter(s => s[0] !== id); save(); } }, '×') : null)))),
        h('tbody', {}, S.accounts.map(a => h('tr', {}, h('td', {}, (a.is_main ? '★ ' : '') + a.login), h('td', {}, h('div', { class: 'r', style: 'flex-wrap:nowrap' }, h('div', { class: 'trk', style: 'width:80px;margin:0' }, h('i', { style: `width:${pct(a)}%` })), h('span', { class: 'm' }, pct(a) + '%'))), list.map(([id, t]) => h('td', {}, h('input', { type: 'checkbox', checked: done(a, id), 'aria-label': t, onchange: e => toggle(a, id, e.target.checked) })))))))),
      h('div', { class: 'r' }, btn('+ Шаг', '', () => { const t = (prompt('Название шага') || '').trim(); if (t) { all[S.wt] = [...list, ['x_' + Date.now().toString(36), t]]; save(); } })));
  },
  'Цикл'() {
    const steps = (JSON.parse(localStorage.getItem('warmSteps') || 'null') || WARM)['Чек-лист'] || [];
    const ready = a => { const mark = id => id[0] === '@' ? !!a[id.slice(1)] : !!JSON.parse(a.warm || '{}')[id]; return steps.length ? Math.round(steps.filter(([id]) => mark(id)).length * 100 / steps.length) : 0; };
    const stage = a => !a.restriction_lifted ? 'ограничение' : ready(a) < 100 ? 'прогрев' : (+a.drops || 0) > (+a.sent_main || 0) ? 'есть дроп' : 'готов';
    const tone = s => s === 'готов' ? 'ok' : s === 'ограничение' ? '' : 'warn';
    const sum = (k) => S.accounts.reduce((s, a) => s + (+a[k] || 0), 0);
    const rows = [...S.accounts].sort((a, b) => (+b.income || 0) - (+a.income || 0));
    return h('div', { class: 'col' },
      h('div', {}, h('h1', {}, 'Цикл'), h('div', { class: 'm' }, 'Учёт ранга, дропа, дохода и отправки на главный. Цифры вводишь в карточке аккаунта. Игровой бот сюда не входит.')),
      h('div', { class: 'cards c4' }, [['Доход', money(sum('income')), 'ok'], ['Реинвест', money(sum('reinvest')), ''], ['Дроп, шт.', sum('drops'), ''], ['Отправлено', sum('sent_main'), '']].map(([l, v, c]) => h('div', { class: 'card stat' }, h('div', { class: 'm' }, l), h('div', { class: 'num ' + c }, v)))),
      table(['Логин', 'Статус', 'Прогрев', 'Ранг', 'Опыт', 'Дроп', 'Доход', 'На главный', 'Реинвест'], rows, S.sa,
        a => [(a.is_main ? '★ ' : '') + a.login, h('span', {}, h('span', { class: 'dot ' + tone(stage(a)) }), stage(a)), ready(a) + '%', a.rank || '—', a.xp ?? '—', a.drops ?? 0, money(a.income), a.sent_main ?? 0, money(a.reinvest)],
        id => { S.sa = id; render(); }, accountForm));
  },
  'Карточки'() {
    const bots = S.asf ? S.asf.bots : [], main = S.accounts.find(a => a.is_main), mb = main && bots.find(b => (b.login || '').toLowerCase() === main.login.toLowerCase());
    const src = bots.filter(b => !mb || b.name !== mb.name), pick = src.map(b => b.name).filter(n => S.cs.has(n));
    const run = (cmd, ask) => act(async () => {
      if (!pick.length) throw new Error('Отметь аккаунты в таблице');
      if (ask && !confirm(ask)) return; out.textContent = 'Выполняю…'; out.textContent = (await api('asf/run', { bots: pick, command: cmd })).result;
    });
    const tgl = n => { S.cs.has(n) ? S.cs.delete(n) : S.cs.add(n); render(); };
    return h('div', { class: 'col' }, h('h1', {}, 'Карточки'),
      h('div', { class: 'card pad r sb' }, h('div', { class: 'r' }, h('b', {}, 'Главный аккаунт'), h('select', { class: 'sel', 'aria-label': 'Главный аккаунт', onchange: e => act(async () => { await api('main', { id: +e.target.value }); await load(); }) },
          h('option', { value: '' }, '— не выбран —'), S.accounts.map(a => h('option', { value: a.id, selected: !!a.is_main }, a.login)))),
        h('span', { class: 'm' }, !main ? 'Выбери, куда передавать предметы' : mb ? `Бот в ASF: ${mb.name}` : 'Бот этого аккаунта не найден в ASF')),
      h('div', { class: 'r sb' }, h('div', { class: 'r' }, btn('Выбрать всех', '', () => { S.cs = new Set(src.map(b => b.name)); render(); }), btn('Снять выбор', '', () => { S.cs.clear(); render(); }), h('span', { class: 'm' }, `Выбрано: ${pick.length} из ${src.length}`)),
        h('div', { class: 'r' }, btn('Проверить инвентарь', '', () => run('inventory {bots}')),
          h('button', { type: 'button', class: 'btn p', onclick: () => mb ? run(`transfer {bots} ${mb.name}`, `Передать предметы с ${pick.length} акк. на ${mb.name}?`) : toast('Сначала выбери главный аккаунт, он должен быть в ASF', true) }, 'Передать главному'))),
      h('div', { class: 'card tbl' }, h('table', {}, h('thead', {}, h('tr', {}, ['', 'Бот', 'Статус', 'Баланс', 'Лвл', 'Карточек'].map(x => h('th', {}, x)))),
        h('tbody', {}, src.map(b => { const a = accOf(b); return h('tr', { onclick: () => tgl(b.name) }, h('td', {}, h('input', { type: 'checkbox', checked: S.cs.has(b.name), 'aria-label': b.name, onclick: e => e.stopPropagation(), onchange: () => tgl(b.name) })),
          h('td', {}, b.name), h('td', {}, h('span', { class: 'dot ' + dotCls(b.state) }), b.state), h('td', {}, a && a.balance || '—'), h('td', {}, a && a.level != null ? a.level : '—'), h('td', {}, b.cards)); })))),
      out);
  },
});

Object.assign(views, {
  'Бейджи'() {
    const hosts = S.accounts.filter(a => S.hosts.has(a.id)), workers = S.accounts.filter(a => !S.hosts.has(a.id)), n = Math.max(1, S.per | 0);
    const plan = hosts.map(() => []); if (hosts.length) workers.forEach((w, i) => plan[Math.floor(i / n) % hosts.length].push(w));
    const save = () => { localStorage.setItem('hosts', JSON.stringify([...S.hosts])); localStorage.setItem('per', S.per); render(); };
    const per = h('input', { class: 'in', type: 'number', min: 1, value: S.per, style: 'width:80px', 'aria-label': 'Аккаунтов на хост', onchange: e => { S.per = Math.max(1, +e.target.value || 1); save(); } });
    return h('div', { class: 'col' }, h('div', {}, h('h1', {}, 'Бейджи'), h('div', { class: 'm' }, 'Community Leader: план ротации хостов для друзей и комментариев')),
      h('div', { class: 'card pad col' }, h('h2', { style: 'margin:0' }, 'Хосты для друзей'),
        h('div', { class: 'r' }, S.accounts.map(a => h('button', { type: 'button', class: 'cp' + (S.hosts.has(a.id) ? ' on' : ''), 'aria-pressed': String(S.hosts.has(a.id)), onclick: () => { S.hosts.has(a.id) ? S.hosts.delete(a.id) : S.hosts.add(a.id); save(); } }, a.login))),
        h('div', { class: 'r' }, h('span', { class: 'm' }, 'Аккаунтов на хост'), per)),
      hosts.length ? h('div', { class: 'tiles' }, hosts.map((x, i) => h('div', { class: 'card pad col' }, h('b', {}, `${x.login} · ${plan[i].length} акк.`), h('div', { class: 'r' }, plan[i].map(w => h('span', { class: 'chip' }, w.login)))))) : h('div', { class: 'card pad m' }, 'Выбери хотя бы одного хоста: он принимает заявки в друзья от рабочих аккаунтов.'),
      h('div', { class: 'card pad m' }, 'Часть шагов значка требует друга в Steam. Steam ограничивает число заявок в сутки, поэтому хостов несколько: каждый берёт N аккаунтов подряд, затем очередь идёт по кругу. Приложение строит только план, заявки отправляй сам.'));
  },
});
const loadTg = async () => { S.tg = await api('tg'); render(); };
const copyTxt = t => navigator.clipboard ? navigator.clipboard.writeText(t).then(() => toast('Скопировано'), () => toast(t)) : toast(t);
const TGS = { view: 'Просмотр', balance: 'Баланс', manage: 'Управление', transfer: 'Передача' };
function inviteDlg(inv) {
  modal('Приглашение', h('div', { class: 'col' }, h('div', { class: 'm' }, 'Отправь ссылку человеку. Она одноразовая и действует 24 часа: по ней он откроет бота и привяжется.'),
    h('input', { class: 'in', readonly: true, value: inv.link, 'aria-label': 'Ссылка', onfocus: e => e.target.select() }), h('div', { class: 'm' }, 'Или пусть отправит боту: /start ' + inv.code)),
    [['Закрыть', '', closeM], ['Копировать ссылку', 'p', () => copyTxt(inv.link)]]);
}
function empDlg(e = {}) {
  const t = S.tg, sel = new Set(e.accounts === '*' || !e.key ? [] : e.accounts || []);
  const all = h('input', { type: 'checkbox', checked: !e.key || e.accounts === '*' }), nm = h('input', { class: 'in', value: e.name || '', placeholder: 'Имя сотрудника', 'aria-label': 'Имя' });
  const pf = {}, pr = Object.entries(t.perms).map(([k, l]) => { pf[k] = h('input', { type: 'checkbox', checked: !!(e.perms && e.perms[k]) }); return h('label', { class: 'r' }, pf[k], l); });
  const chips = h('div', { class: 'r' }), draw = () => chips.replaceChildren(...t.logins.map(l => h('button', { type: 'button', class: 'cp' + (sel.has(l) ? ' on' : ''), 'aria-pressed': String(sel.has(l)), onclick: () => { sel.has(l) ? sel.delete(l) : sel.add(l); all.checked = false; draw(); } }, l)));
  draw();
  modal(e.key ? 'Сотрудник' : 'Новый сотрудник', h('div', { class: 'col' }, fld('Имя', nm), h('b', {}, 'Что может'), h('div', { class: 'col' }, pr), h('b', {}, 'Какие аккаунты'), h('label', { class: 'r' }, all, 'Все аккаунты'), chips,
    h('div', { class: 'm' }, 'Пароли, почты и maFiles сотруднику недоступны. Владелец видит уведомление о каждом его действии.')),
    [['Отмена', '', closeM], ['Сохранить', 'p', () => act(async () => {
      const r = await api('tg/employee', { key: e.key, name: nm.value, perms: Object.fromEntries(Object.entries(pf).map(([k, i]) => [k, i.checked])), accounts: all.checked ? '*' : [...sel] });
      if (!e.key) { const inv = await api('tg/invite', { role: 'employee', emp: r.key }); await loadTg(); return inviteDlg(inv); }
      closeM(); await loadTg();
    })]]);
}
Object.assign(views, {
  'Telegram'() {
    const t = S.tg; if (!t) return h('div', { class: 'card pad m' }, 'Загрузка…');
    const tok = h('input', { class: 'in', style: 'flex:1', type: 'password', autocomplete: 'off', placeholder: 'Токен бота от @BotFather', 'aria-label': 'Токен бота' });
    const bot = !t.token_set ? h('div', { class: 'col' }, h('div', { class: 'm' }, 'Создай бота у @BotFather и вставь токен. Токен хранится только на этом компьютере (telegram.json).'), h('div', { class: 'r' }, tok, btn('Подключить', 'p', () => act(async () => { S.tg = await api('tg/token', { token: tok.value }); toast('Бот подключён'); render(); }))))
      : h('div', { class: 'r sb' }, h('div', { class: 'r' }, h('span', { class: 'dot ' + (t.running && !t.error ? 'ok' : 'warn') }), h('b', {}, '@' + (t.username || '…')), h('span', { class: 'm' }, t.error ? 'Ошибка: ' + t.error : t.running ? 'Работает' : 'Остановлен')),
        h('div', { class: 'r' }, btn('Тест', '', () => act(async () => { await api('tg/test', {}); toast('Отправлено владельцу'); })), btn('Отключить', 'd', () => confirm('Отключить бота? Привязки сохранятся.') && act(async () => { S.tg = await api('tg/token', { token: '' }); render(); }))));
    const owner = h('div', { class: 'r sb' }, h('div', { class: 'r' }, h('b', {}, 'Владелец'), h('span', { class: 'm' }, t.owner ? `${t.owner.name} · ${t.owner.id}` : 'не привязан')),
      h('div', { class: 'r' }, btn(t.owner ? 'Привязать заново' : 'Привязать меня', 'p', () => act(async () => inviteDlg(await api('tg/invite', { role: 'owner' })))), t.owner ? btn('Отвязать', 'd', () => confirm('Отвязать владельца?') && act(async () => { await api('tg/unlink', {}); await loadTg(); })) : null));
    return h('div', { class: 'col' }, h('div', {}, h('h1', {}, 'Telegram'), h('div', { class: 'm' }, 'Бот для владельца и сотрудников: статус, баланс и управление прямо в Telegram')),
      h('div', { class: 'card pad col' }, h('h2', { style: 'margin:0' }, 'Бот'), bot, t.token_set ? owner : null),
      h('div', { class: 'r sb' }, h('h2', { style: 'margin:0' }, 'Сотрудники'), btn('+ Сотрудник', 'p', () => empDlg())),
      t.employees.length ? table(['Имя', 'Статус', 'Права', 'Аккаунты', ''], t.employees, '', e => [e.name,
        h('span', {}, h('span', { class: 'dot ' + (e.id ? 'ok' : 'warn') }), e.id ? 'привязан' + (e.tg ? ' @' + e.tg : '') : 'ждёт привязки'),
        h('span', { class: 'r', style: 'flex-wrap:nowrap' }, Object.keys(t.perms).filter(k => e.perms[k]).map(k => h('span', { class: 'chip' }, TGS[k]))), e.accounts === '*' ? 'все' : e.accounts.length + ' акк.',
        h('span', { class: 'r', style: 'flex-wrap:nowrap' }, btn('Изменить', '', () => empDlg(e)), e.id ? null : btn('Ссылка', '', () => act(async () => inviteDlg(await api('tg/invite', { role: 'employee', emp: e.key })))),
          btn('Удалить', 'd', () => confirm(`Удалить сотрудника «${e.name}»?`) && act(async () => { await api('tg/employee/delete', { key: e.key }); await loadTg(); })))], () => {}, empDlg)
        : h('div', { class: 'card pad m' }, 'Сотрудников пока нет. Добавь человека, задай права и аккаунты, отправь ему ссылку.'),
      h('div', { class: 'card pad m' }, 'Сотрудник видит и меняет только отмеченные аккаунты. Пароли, почты и maFiles в Telegram не отправляются, а владелец получает уведомление о каждом действии сотрудника.'));
  },
});
const assign = () => confirm('Назначить по одному прокси на аккаунт по порядку добавления?\nТекущие назначения будут перезаписаны.') && act(async () => {
  const r = await api('assign', {}); toast(`Назначено: ${r.assigned}\nБез прокси: ${r.left}`); await load();
});

function accountForm(a = {}) {
  const f = {};
  const inp = (k, l, t = 'text') => (f[k] = h('input', { class: 'in', type: t, step: t === 'number' ? 'any' : null, value: a[k] ?? '' }), fld(l, f[k]));
  const chk = (k, l) => (f[k] = h('input', { type: 'checkbox', checked: !!a[k] }), h('label', { class: 'r' }, f[k], l));
  f.proxy_id = h('select', { class: 'in' }, h('option', { value: '' }, '— не назначен —'), S.proxies.map(p => h('option', { value: p.id }, `#${p.id} ${p.host}:${p.port}`)));
  f.proxy_id.value = a.proxy_id ?? '';
  modal(a.id ? 'Редактировать аккаунт' : 'Новый аккаунт',
    h('div', { class: 'grid2' }, inp('steam_id', 'Steam ID'), inp('login', 'Логин *'), inp('password', 'Пароль'), inp('rcode', 'Rcode'), inp('friend_code', 'Код дружбы'), inp('first_ko', 'Первый Ko'),
      inp('email', 'Почта'), inp('email_password', 'Пароль почты'), inp('spent', 'Потрачено ($)', 'number'), inp('balance', 'Баланс (например 12.50 USD)'), inp('level', 'Уровень Steam', 'number'),
      inp('rank', 'Ранг'), inp('xp', 'Опыт', 'number'), inp('drops', 'Дроп, шт.', 'number'), inp('income', 'Доход ($)', 'number'), inp('sent_main', 'Отправлено на главный', 'number'), inp('reinvest', 'Реинвест ($)', 'number'), inp('notes', 'Заметки'),
      h('div', { class: 'col' }, chk('configured', 'Настроен'), chk('restriction_lifted', 'Снято ограничение'), chk('prime_bought', 'Куплен прайм')), fld('Прокси', f.proxy_id)),
    [['Отмена', '', closeM], ['Сохранить', 'p', () => act(async () => {
      const d = { id: a.id }; for (const [k, e] of Object.entries(f)) d[k] = e.type === 'checkbox' ? e.checked : e.value;
      d.proxy_id = d.proxy_id ? +d.proxy_id : null; await api('account', d); closeM(); await load();
    })]]);
}
function proxyForm(p = {}) {
  const f = {};
  f.protocol = h('select', { class: 'in' }, ['http', 'https', 'socks5', 'socks4'].map(x => h('option', { value: x }, x))); f.protocol.value = p.protocol || 'http';
  const inp = (k, l) => (f[k] = h('input', { class: 'in', value: p[k] ?? '' }), fld(l, f[k]));
  modal(p.id ? 'Редактировать прокси' : 'Новый прокси', h('div', { class: 'grid2' }, fld('Протокол', f.protocol), inp('host', 'Хост *'), inp('port', 'Порт *'), inp('username', 'Логин'), inp('password', 'Пароль'), inp('notes', 'Заметки')),
    [['Отмена', '', closeM], ['Сохранить', 'p', () => act(async () => {
      const d = { id: p.id }; for (const [k, e] of Object.entries(f)) d[k] = e.value; await api('proxy', d); closeM(); await load();
    })]]);
}
const download = async url => {
  const r = await fetch(url); if (!r.ok) throw new Error((await r.json()).error);
  const name = (r.headers.get('Content-Disposition') || '').split('filename=')[1] || 'export';
  const a = h('a', { href: URL.createObjectURL(await r.blob()), download: name }); document.body.append(a); a.click(); a.remove();
};
async function exchangeDlg(kind, how) {
  const T = (await api('templates'))[kind];
  const sel = h('select', { class: 'in' }, T.map(([n, f]) => h('option', { value: f }, n)));
  const fmt = h('input', { class: 'in', value: T[0][1], 'aria-label': 'Формат строки' });
  sel.onchange = () => { if (sel.value) fmt.value = sel.value; };
  const head = [fld('Шаблон', sel), fld('Формат строки (можно поправить)', fmt)];
  if (how === 'export') return modal('Экспорт', h('div', { class: 'col' }, head), [['Закрыть', '', closeM],
    ['Excel', 'p', () => act(() => download(`/api/export?kind=${kind}&type=xlsx`))], ['TXT', 'p', () => act(() => download(`/api/export?kind=${kind}&type=txt&fmt=${encodeURIComponent(fmt.value)}`))]]);
  const ta = h('textarea', { class: 'in', placeholder: 'Одна запись на строку. Строки с # пропускаются.', 'aria-label': 'Данные' });
  const file = h('input', { type: 'file', accept: '.txt', onchange: async () => { ta.value = await file.files[0].text(); } });
  modal('Импорт', h('div', { class: 'col' }, head, ta, file), [['Закрыть', '', closeM], ['Импорт', 'p', () => act(async () => {
    const r = await api('import', { kind, fmt: fmt.value, text: ta.value }); toast(r.text); closeM(); await load();
  })]]);
}
function settingsDlg() {
  const m = h('input', { class: 'in', value: S.settings.mafiles_dir || '' }), s = h('input', { class: 'in', value: S.settings.asf_dir || '' });
  modal('Пути', h('div', { class: 'col' }, fld('Папка maFiles (Nebula / SDA)', m), fld('Папка ArchiSteamFarm (с ArchiSteamFarm.exe)', s)),
    [['Отмена', '', closeM], ['Сохранить', 'p', () => act(async () => { await api('settings', { mafiles_dir: m.value, asf_dir: s.value }); closeM(); await load(); pollAsf(); })]]);
}

const NAV = [['Основное', [['Дашборд', 'home', 'Дашборд'], ['Аккаунты', 'users', 'Аккаунты'], ['Цикл', 'chart', 'Цикл'], ['ASF', 'bot', 'Боты ASF'], ['Прокси', 'globe', 'Прокси']]],
  ['Автоматизация', [['Прогрев', 'flame', 'Прогрев'], ['Бейджи', 'award', 'Бейджи'], ['Карточки', 'cards', 'Карточки']]], ['Команда', [['Telegram', 'send', 'Telegram']]]];
function render() {
  applyTheme();
  $('#tabs').replaceChildren(...NAV.map(([g, items]) => h('div', {}, h('div', { class: 'nt' }, g), items.map(([t, i, l]) => h('button', { class: 'ni' + (t === S.tab ? ' on' : ''), 'aria-current': t === S.tab ? 'page' : null, onclick: () => { S.tab = t; render(); pollAsf(); if (t === 'Telegram') act(loadTg); } }, ico(i), l)))));
  $('#themes').replaceChildren(...MODES.map(([l, m]) => h('button', { class: mode() === m ? 'on' : '', onclick: () => { localStorage.setItem('theme', m); render(); } }, l)));
  $('#view').replaceChildren(views[S.tab]());
}
async function pollAsf() {
  if (!['ASF', 'Дашборд', 'Карточки'].includes(S.tab)) return;
  let n; try { n = await api('asf'); } catch { return; }
  const changed = JSON.stringify(n) !== JSON.stringify(S.asf); S.asf = n;
  if (changed) render();
}
setInterval(pollAsf, 6000);
setInterval(async () => {
  const el = $('#ls'); if (!el) return;
  try { const d = await api('login-status'); el.textContent = d.text; el.className = 'm st ' + d.kind; } catch {}
}, 1500);
load().then(pollAsf).catch(e => toast(e.message, true));
