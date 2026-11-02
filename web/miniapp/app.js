/* Панель Telegram. Числа только из /api/mini/*. Пустого поля на экране нет: стоит «—». */
(function () {
  const DASH = "—";
  const tg = window.Telegram && window.Telegram.WebApp;
  const GRADS = [
    ["#4f8cff", "#7c5cff"], ["#22c1c3", "#2563eb"], ["#a855f7", "#ec4899"],
    ["#f59e0b", "#ef4444"], ["#10b981", "#0ea5e9"], ["#6366f1", "#06b6d4"], ["#f472b6", "#8b5cf6"],
  ];
  const KIND = {
    farm: { label: "Фармит", st: "st-g", c: "c-g" },
    online: { label: "Онлайн", st: "st-b", c: "c-b" },
    error: { label: "Ошибка", st: "st-r", c: "c-r" },
    off: { label: "Офлайн", st: "st-o", c: "c-o" },
  };
  const state = {
    gate: "",
    data: null,
    screen: "home",
    filter: "all",
    query: "",
    range: "day",
    account: null,
    accountKey: "",
    showPass: false,
    busy: false,
  };
  let toastTimer = 0;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function dash(value) {
    if (value === null || value === undefined) return DASH;
    const text = String(value).trim();
    return text ? text : DASH;
  }

  function ico(id) {
    return '<svg><use href="#' + id + '"/></svg>';
  }

  function kindOf(bot) {
    return KIND[bot.kind] || KIND.off;
  }

  function letter(bot) {
    const source = bot.login && bot.login !== DASH ? bot.login : (bot.bot || "?");
    return esc(String(source).trim().charAt(0).toUpperCase() || "?");
  }

  function grad(index) {
    const pair = GRADS[Math.abs(index) % GRADS.length];
    return "linear-gradient(140deg," + pair[0] + "," + pair[1] + ")";
  }

  function live() {
    return !state.gate && !!state.data;
  }

  function bots() {
    return (state.data && state.data.bots) || [];
  }

  function visibleBots() {
    const q = state.query.trim().toLowerCase();
    return bots().filter(function (bot) {
      if (state.filter === "farm" && bot.kind !== "farm") return false;
      if (state.filter === "online" && bot.kind !== "farm" && bot.kind !== "online") return false;
      if (state.filter === "error" && bot.kind !== "error") return false;
      if (!q) return true;
      return (bot.login + " " + bot.bot).toLowerCase().indexOf(q) !== -1;
    });
  }

  function countKind(filter) {
    return bots().filter(function (bot) {
      if (filter === "farm") return bot.kind === "farm";
      if (filter === "online") return bot.kind === "farm" || bot.kind === "online";
      if (filter === "error") return bot.kind === "error";
      return true;
    }).length;
  }

  function toast(text) {
    const el = document.getElementById("toast");
    el.textContent = text || DASH;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3600);
  }

  function ask(text) {
    return new Promise(function (resolve) {
      if (tg && typeof tg.showConfirm === "function") tg.showConfirm(text, resolve);
      else resolve(window.confirm(text));
    });
  }

  function gateText() {
    if (location.protocol !== "https:") {
      return "Нужен HTTPS. Впиши адрес в MINIAPP_URL и открой панель кнопкой в боте. Туннель сам не поднимается.";
    }
    if (!tg || !tg.initData) return "Открой панель кнопкой «Открыть панель» в боте.";
    return "";
  }

  function bootTg() {
    if (!tg) return;
    try { tg.ready(); tg.expand(); } catch (e) { /* старый клиент */ }
    try { tg.setHeaderColor("#06080f"); } catch (e) { /* нет метода */ }
    try { tg.setBackgroundColor("#06080f"); } catch (e) { /* нет метода */ }
    try { if (tg.disableVerticalSwipes) tg.disableVerticalSwipes(); } catch (e) { /* нет метода */ }
  }

  async function api(path, options) {
    const headers = {
      "Content-Type": "application/json",
      "X-Requested-With": "sfm",
      "X-Telegram-Init-Data": tg.initData,
    };
    const res = await fetch(path, Object.assign({ headers: headers }, options || {}));
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) throw new Error(data.error || "Ошибка");
    return data;
  }

  async function load() {
    if (state.gate) return;
    state.data = await api("/api/mini/state");
    const name = state.data.bot_username && state.data.bot_username !== DASH
      ? "@" + String(state.data.bot_username).replace(/^@/, "")
      : DASH;
    document.getElementById("foot").textContent = name;
  }

  async function openAccount(key) {
    if (!live()) return;
    if (!state.data.me.card) {
      toast("Нет прав на карточку");
      return;
    }
    state.screen = "acc";
    state.accountKey = key;
    state.account = null;
    state.showPass = false;
    render();
    try {
      const fresh = await api("/api/mini/account?key=" + encodeURIComponent(key));
      if (state.screen !== "acc" || state.accountKey !== key) return;
      state.account = fresh;
    } catch (e) {
      if (state.screen !== "acc" || state.accountKey !== key) return;
      toast(e.message || "Ошибка");
      state.screen = "bots";
    }
    render();
  }

  async function reloadAccount() {
    const key = state.accountKey;
    if (state.screen !== "acc" || !key || state.gate) return;
    const fresh = await api("/api/mini/account?key=" + encodeURIComponent(key));
    if (state.screen !== "acc" || state.accountKey !== key) return;
    state.showPass = false;
    state.account = fresh;
  }

  async function run(action, bot) {
    if (state.busy || state.gate) return;
    state.busy = true;
    render();
    try {
      const data = await api("/api/mini/action", {
        method: "POST",
        body: JSON.stringify({ action: action, bot: bot || "" }),
      });
      toast(data.message || "Готово");
      await load();
      await reloadAccount();
    } catch (e) {
      toast(e.message || "Ошибка");
    } finally {
      state.busy = false;
      render();
    }
  }

  function header(title, sub, left, right) {
    return '<div class="tg"><button type="button" class="iconbtn" data-act="' + left + '" aria-label="' +
      (left === "back" ? "Назад" : "Закрыть") + '">' + ico(left === "back" ? "back" : "x") +
      '</button><div class="t">' + esc(title) + "<small>" + esc(sub) + "</small></div>" +
      '<button type="button" class="iconbtn" data-act="' + right + '" aria-label="' +
      (right === "reload" ? "Обновить" : "Профиль") + '">' + ico(right === "reload" ? "refresh" : right === "range" ? "filter" : "more") +
      "</button></div>";
  }

  function homeHtml() {
    const d = state.data;
    const known = !!d;
    const running = known && d.asf && d.asf.running;
    const pill = !known ? "wait" : running ? "ok" : "off";
    const pillText = !known ? DASH : running ? "ASF запущен" : "ASF выключен";
    const version = known && d.asf && d.asf.version && d.asf.version !== DASH ? "ASF " + d.asf.version : DASH;
    const online = known ? d.online : DASH;
    const total = known ? d.total : DASH;
    const name = known ? dash(d.me.name) : DASH;
    const cardsSub = known && d.cards_bots !== DASH ? "в " + d.cards_bots + " ботах" : DASH;
    const can = live() && !state.busy;
    const manage = can && d.me.manage;
    const owner = can && d.me.owner;
    const proxy = known && d.proxies ? d.proxies.used + " из " + d.proxies.total + " назначено" : DASH;
    const fresh = known ? dash(d.import_new) : DASH;
    const updated = known && d.asf ? d.asf.updated : DASH;
    return header("Steam Farm", "мини-приложение", "close", "more") +
      '<div class="content"><div class="hero"><div class="logo">' + ico("flame") + "</div><div><h1 class=\"disp\">Steam Farm</h1><p>Привет, " +
      esc(name) + '</p></div><span class="pill ' + pill + '"><span class="dot"></span>' + esc(pillText) + "</span></div>" +
      '<div class="main"><div class="row" style="justify-content:space-between;position:relative;z-index:1"><span class="lbl">Ботов онлайн</span><span class="lbl mono">' +
      esc(version) + '</span></div><div class="big" style="position:relative;z-index:1">' + esc(online) + " <span>из " + esc(total) +
      '</span></div><div class="bar"><i></i></div><div class="barinfo"><span>Прогресс фарма карт</span><span class="mono">' +
      esc(known ? d.farm_progress : DASH) + "</span></div></div>" +
      '<div class="stats">' +
      stat("cards", "#7fb0ff", "Карт осталось", known ? d.cards_left : DASH, cardsSub) +
      stat("star", "var(--violet)", "Ср. уровень", known ? d.level_avg : DASH, known ? d.level_delta : DASH) +
      stat("drop", "var(--cyan)", "Дропы", known ? d.drops : DASH, known ? "в учёте · " + d.drops_delta : DASH) +
      stat("wallet", "var(--amber)", "Инвентарь", known ? d.inventory : DASH, known ? "доход " + d.income : DASH) +
      "</div>" +
      '<div class="sec"><h3>Быстрые действия</h3><button type="button" data-go="bots">Все →</button></div><div class="tiles">' +
      tile("play", "g", "start_all", "Запустить всё", known ? total + " ботов" : DASH, !manage) +
      tile("stop", "r", "pause_all", "Остановить", "пауза фарма", !manage) +
      tile("import", "b", "import", "Импорт из ASF", owner ? fresh + " новых" : DASH, !owner) +
      tile("globe", "v", "proxy", "Прокси", proxy, !owner) +
      '</div><div class="upd"><span class="dot"></span>Обновлено в ' + esc(updated) + "</div></div>";
  }

  function stat(icon, color, title, value, sub) {
    return '<div class="stat card"><div class="k"><svg style="stroke:' + color + '">' + ico(icon) + "</svg>" + esc(title) +
      '</div><div class="v">' + esc(dash(value)) + '</div><div class="s">' + esc(dash(sub)) + "</div></div>";
  }

  function tile(icon, tone, action, title, sub, disabled) {
    return '<button type="button" class="tile" data-act="' + action + '"' + (disabled ? " disabled" : "") + '><div class="ic ' + tone + '">' +
      ico(icon) + "</div><div><b>" + esc(title) + "</b><small>" + esc(sub) + "</small></div></button>";
  }

  function botsHtml() {
    const d = state.data;
    const online = d ? d.online : DASH;
    const total = d ? d.total : DASH;
    const rows = visibleBots();
    const chips = [
      ["all", "Все", countKind("all"), ""],
      ["farm", "Фармят", countKind("farm"), ""],
      ["online", "Онлайн", countKind("online"), ""],
      ["error", "Ошибка", countKind("error"), " warn"],
    ].map(function (item) {
      const on = state.filter === item[0] ? " on" : "";
      return '<button type="button" class="chip' + on + item[3] + '" data-filter="' + item[0] + '">' + item[1] +
        " <em>" + (d ? item[2] : DASH) + "</em></button>";
    }).join("");
    const list = rows.length ? rows.map(function (bot, i) {
      const meta = kindOf(bot);
      const cards = bot.cards && bot.cards !== DASH ? bot.cards + " карт" : DASH;
      const level = bot.level === null || bot.level === undefined ? "" : '<span class="lvl">' + esc(bot.level) + "</span>";
      const title = bot.login || bot.bot || DASH;
      return '<button type="button" class="bot" data-key="' + esc(bot.key) + '"><div class="av" style="background:' + grad(i) + '">' +
        letter(bot) + '<span class="sd ' + meta.st + '"></span></div><div class="mid"><b>' + esc(title) + " " + level +
        "</b><small>" + esc(bot.state || DASH) + " · " + esc(cards) + '</small></div><div class="rt"><b class="' + meta.c + '">' +
        esc(meta.label) + "</b><small class=\"mono\">" + esc(bot.bot || DASH) + "</small></div></button>";
    }).join("") : '<div class="empty card">' + (d ? "Никого не нашли" : "Нет данных") + "</div>";
    return header("Боты ASF", online + " онлайн · " + total + " всего", "close", "reload") +
      '<div class="content"><label class="search card">' + ico("search") +
      '<input id="q" type="search" placeholder="Поиск по логину…" value="' + esc(state.query) + '" autocomplete="off">' +
      '<span class="kbd" id="qcount">' + (d ? rows.length : DASH) + "</span></label><div class=\"chips\">" + chips +
      '</div><div class="list" id="botlist">' + list + "</div></div>";
  }

  function passCell(acc) {
    if (acc.password_locked) return '<span>скрыт</span>';
    if (!Object.prototype.hasOwnProperty.call(acc, "password")) return "<span>" + DASH + "</span>";
    if (!state.showPass) return '<span class="dots">••••••••</span><button type="button" class="eye" data-act="eye" aria-label="Показать пароль">' + ico("eye") + "</button>";
    return "<span>" + esc(acc.password ? acc.password : DASH) + '</span><button type="button" class="eye" data-act="eye" aria-label="Скрыть пароль">' + ico("eye") + "</button>";
  }

  function maTag(value) {
    if (value === "есть") return '<span class="tag g">maFile есть</span>';
    if (value === "нет") return '<span class="tag">maFile нет</span>';
    return "<span>" + esc(dash(value)) + "</span>";
  }

  function accHtml() {
    const acc = state.account;
    if (!acc) {
      return header("Аккаунт", "загрузка", "back", "reload") + '<div class="content"><div class="empty card">Загрузка…</div></div>';
    }
    const meta = kindOf(acc);
    const sub = "бот №" + (acc.index || DASH) + " из " + (acc.total || DASH);
    const level = acc.level === null || acc.level === undefined ? DASH : "LVL " + acc.level;
    const status = meta.label + (acc.cards && acc.cards !== DASH ? " · " + acc.cards + " карт" : "");
    const canAct = acc.manage && acc.bot && !state.busy;
    return header("Аккаунт", sub, "back", "reload") +
      '<div class="content"><div class="acc-head"><div class="acc-av" style="background:' + grad(acc.index || 0) + '">' + letter(acc) +
      '<span class="sd ' + meta.st + '"></span></div><h2>' + esc(acc.login || DASH) + '</h2><p><span class="pill farm"><span class="dot"></span>' +
      esc(status) + "</span></p></div>" +
      '<div class="kv card">' +
      line("user", "b", "Логин", "<span class=\"mono\">" + esc(dash(acc.login)) + "</span>") +
      line("key", "v", "Пароль", passCell(acc)) +
      line("star", "a", "Уровень Steam", '<span class="lvl" style="font-size:12px">' + esc(level) + "</span>") +
      line("id", "b", "SteamID", "<span class=\"mono\" style=\"font-size:12.5px\">" + esc(dash(acc.steam_id)) + "</span>") +
      line("award", "a", "Значки", "<span>" + esc(dash(acc.badges)) + "</span>") +
      line("globe", "v", "Прокси", "<span class=\"mono\" style=\"font-size:12.5px\">" + esc(dash(acc.proxy)) + "</span>") +
      line("shield", "g", "maFile", maTag(acc.mafile)) +
      "</div>" +
      '<div class="asf card"><h4>Настройки ASF <span class="mono">' + esc(dash(acc.file)) + "</span></h4><div class=\"asfgrid\">" +
      "<div>Enabled <b>" + esc(dash(acc.enabled)) + "</b></div><div>Фарм <b>" + esc(dash(acc.farming)) + "</b></div>" +
      "<div>Трейды <b>" + esc(dash(acc.trades)) + "</b></div><div>Карт осталось <b class=\"mono\">" + esc(dash(acc.cards)) + "</b></div>" +
      "</div></div><div class=\"btns\">" +
      '<button type="button" class="btn ghost" data-act="pause"' + (canAct ? "" : " disabled") + ">" + ico("pause") + "Пауза</button>" +
      '<button type="button" class="btn pri" data-act="start"' + (canAct ? "" : " disabled") + ">" + ico("play") + "Старт</button>" +
      '<button type="button" class="btn white" data-act="ipc">' + ico("ext") + "Открыть в ASF</button></div></div>";
  }

  function line(icon, tone, title, valueHtml) {
    return '<div class="line"><div class="ic ' + tone + '">' + ico(icon) + '</div><span class="k">' + esc(title) + '</span><span class="v">' + valueHtml + "</span></div>";
  }

  function dropsHtml() {
    const d = state.data;
    const day = state.range === "day";
    const left = day && d ? d.drops : DASH;
    const right = day && d ? d.income : DASH;
    const delta = day && d ? d.drops_delta : DASH;
    const title = { day: "Учёт", week: "Неделя", month: "Месяц" }[state.range];
    const rows = (d ? bots() : []).slice().sort(function (a, b) { return (b.drops || 0) - (a.drops || 0); });
    const list = !day
      ? '<div class="empty card">Разбивки по этому сроку нет</div>'
      : (rows.length ? rows.map(function (bot, i) {
        const who = bot.bot && bot.login && bot.bot.toLowerCase() !== String(bot.login).toLowerCase()
          ? bot.bot + " · " + (bot.state || DASH)
          : (bot.state || DASH);
        return '<div class="drop card"><div class="av" style="background:' + grad(i) + '">' + letter(bot) +
          '</div><div class="mid"><b>' + esc(bot.login || bot.bot || DASH) + "</b><small>" + esc(who) +
          '</small></div><div class="rt"><b class="mono">' + esc(bot.drops) + '</b><small class="mono">' + esc(bot.income) + "</small></div></div>";
      }).join("") : '<div class="empty card">Нет записей в учёте</div>');
    const seg = ["day", "week", "month"].map(function (id) {
      const label = { day: "День", week: "Неделя", month: "Месяц" }[id];
      return '<button type="button" data-range="' + id + '"' + (state.range === id ? ' class="on"' : "") + ">" + label + "</button>";
    }).join("");
    return header("Дропы", "учёт в программе", "close", "range") +
      '<div class="content"><div class="dsum main"><div><div class="lbl">' + esc(title) + '</div><div class="v">' + esc(dash(left)) +
      ' <span>шт</span></div><div class="s">' + esc(dash(delta)) + '</div></div><div><div class="lbl">Доход</div><div class="v">' +
      esc(dash(right)) + '</div><div class="s">без цены предметов</div></div></div><div class="seg card">' + seg +
      '</div><div class="day">' + esc(title) + '</div><div class="list">' + list + "</div></div>";
  }

  function meHtml() {
    const d = state.data;
    const me = d ? d.me : null;
    const name = me ? dash(me.name) : DASH;
    const role = me ? dash(me.role) : DASH;
    const user = me && me.username ? "@" + String(me.username).replace(/^@/, "") : DASH;
    const pass = me ? (me.owner ? "виден в карточке" : "скрыт") : DASH;
    const manage = me ? (me.manage ? "да" : "нет") : DASH;
    return header("Профиль", "кто открыл панель", "close", "reload") +
      '<div class="content"><div class="acc-head"><div class="acc-av">' + esc(name === DASH ? "?" : name.charAt(0).toUpperCase()) +
      '</div><h2>' + esc(name) + '</h2><p><span class="pill wait">' + esc(role) + "</span></p></div>" +
      '<div class="kv card">' +
      line("user", "b", "Telegram", "<span>" + esc(user) + "</span>") +
      line("bots", "v", "Бот", "<span>" + esc(document.getElementById("foot").textContent || DASH) + "</span>") +
      line("play", "g", "Управление", "<span>" + esc(manage) + "</span>") +
      line("key", "a", "Пароль", "<span>" + esc(pass) + "</span>") +
      '</div><p class="note" style="margin-top:12px">Цифры берутся с компьютера, где запущен менеджер. Чего нет в базе или в ASF, на экране «—».</p></div>';
  }

  function render() {
    const root = document.getElementById("screens");
    const focus = document.activeElement && document.activeElement.id === "q";
    const caret = focus ? document.activeElement.selectionStart : 0;
    const html = { home: homeHtml, bots: botsHtml, acc: accHtml, drops: dropsHtml, me: meHtml }[state.screen] || homeHtml;
    root.innerHTML = '<section class="screen active">' + html() + "</section>";
    const nav = state.screen === "acc" ? "bots" : state.screen;
    document.querySelectorAll("#nav button").forEach(function (btn) {
      btn.classList.toggle("on", btn.getAttribute("data-go") === nav);
    });
    if (focus) {
      const input = document.getElementById("q");
      if (input) {
        input.focus();
        try { input.setSelectionRange(caret, caret); } catch (e) { /* тип search */ }
      }
    }
  }

  async function onAction(action, bot) {
    if (action === "close") {
      if (tg && tg.close) tg.close();
      else toast("Закрытие есть в Telegram");
      return;
    }
    if (action === "back") {
      state.screen = "bots";
      state.account = null;
      state.showPass = false;
      render();
      return;
    }
    if (action === "more") {
      state.screen = "me";
      render();
      return;
    }
    if (action === "reload") {
      if (state.gate) return;
      state.busy = true;
      render();
      try {
        await load();
        await reloadAccount();
      } catch (e) {
        toast(e.message || "Ошибка");
      } finally {
        state.busy = false;
        render();
      }
      return;
    }
    if (action === "range") {
      state.range = state.range === "day" ? "week" : state.range === "week" ? "month" : "day";
      render();
      return;
    }
    if (action === "eye") {
      state.showPass = !state.showPass;
      render();
      return;
    }
    if (action === "proxy") {
      const p = state.data && state.data.proxies;
      toast(p ? "Назначено " + p.used + " из " + p.total + ". В конфиг ASF отсюда не пишем." : "Прокси видны только владельцу");
      return;
    }
    if (action === "ipc") {
      const local = state.account && state.account.ipc_local;
      toast(local ? "IPC ASF на компьютере с менеджером. С телефона его не открыть." : "Адрес IPC в панель не передаётся.");
      return;
    }
    if (action === "import") {
      if (!(await ask("Добавить ботов ASF в аккаунты на этом компьютере?"))) return;
      await run("import");
      return;
    }
    if (action === "start_all") {
      if (!(await ask("Запустить ASF и видимых ботов?"))) return;
      await run("start_all");
      return;
    }
    if (action === "pause_all") {
      if (!(await ask("Поставить фарм видимых ботов на паузу?"))) return;
      await run("pause_all");
      return;
    }
    if (action === "start" || action === "pause") {
      if (!state.account || !state.account.bot) return;
      await run(action, state.account.bot);
    }
  }

  document.getElementById("screens").addEventListener("click", function (event) {
    const key = event.target.closest("[data-key]");
    const go = event.target.closest("[data-go]");
    const filter = event.target.closest("[data-filter]");
    const range = event.target.closest("[data-range]");
    const act = event.target.closest("[data-act]");
    if (key && key.getAttribute("data-key")) {
      openAccount(key.getAttribute("data-key"));
      return;
    }
    if (go) {
      state.screen = go.getAttribute("data-go");
      state.account = null;
      state.showPass = false;
      render();
      return;
    }
    if (filter) {
      state.filter = filter.getAttribute("data-filter");
      render();
      return;
    }
    if (range) {
      state.range = range.getAttribute("data-range");
      render();
      return;
    }
    if (act) onAction(act.getAttribute("data-act"));
  });

  document.getElementById("nav").addEventListener("click", function (event) {
    const go = event.target.closest("[data-go]");
    if (!go) return;
    state.screen = go.getAttribute("data-go");
    state.account = null;
    state.showPass = false;
    render();
  });

  document.getElementById("screens").addEventListener("input", function (event) {
    if (event.target.id !== "q") return;
    state.query = event.target.value;
    const list = document.getElementById("botlist");
    const count = document.getElementById("qcount");
    if (!list) return;
    const rows = visibleBots();
    if (count) count.textContent = state.data ? String(rows.length) : DASH;
    list.innerHTML = rows.length ? rows.map(function (bot, i) {
      const meta = kindOf(bot);
      const cards = bot.cards && bot.cards !== DASH ? bot.cards + " карт" : DASH;
      const level = bot.level === null || bot.level === undefined ? "" : '<span class="lvl">' + esc(bot.level) + "</span>";
      return '<button type="button" class="bot" data-key="' + esc(bot.key) + '"><div class="av" style="background:' + grad(i) + '">' +
        letter(bot) + '<span class="sd ' + meta.st + '"></span></div><div class="mid"><b>' + esc(bot.login || bot.bot || DASH) +
        " " + level + "</b><small>" + esc(bot.state || DASH) + " · " + esc(cards) + '</small></div><div class="rt"><b class="' +
        meta.c + '">' + esc(meta.label) + '</b><small class="mono">' + esc(bot.bot || DASH) + "</small></div></button>";
    }).join("") : '<div class="empty card">Никого не нашли</div>';
  });

  bootTg();
  state.gate = gateText();
  const banner = document.getElementById("banner");
  if (state.gate) {
    banner.hidden = false;
    banner.textContent = state.gate;
    render();
  } else {
    banner.hidden = true;
    render();
    load().then(render).catch(function (e) {
      toast(e.message || "Нет данных");
      render();
    });
  }
})();
