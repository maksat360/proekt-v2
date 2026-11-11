'use strict';

/* Джарвис — помощник на сайте: приветствует по имени и отчеству, отвечает голосом и открывает
   разделы и вкладки, которые сотруднику и так видны (список кладёт страница в window.ASSIST_SECTIONS:
   [{id, label, href}]). Права проверяет сервер — помощник ничего сверх меню открыть не может.
   Голос и распознавание — на Маке (Yuri + Whisper), поэтому одинаково на всех устройствах.
   Окно: чат + голосовой режим с «живым» шаром, который дышит, слушает и говорит. */
(function () {
  const AS = { open: false, busy: false, talk: false, standby: false, goSleep: false, heardAt: 0, hist: [], rec: null, stream: null, audio: null,
    ctx: null, micAn: null, outAn: null, state: 'idle', raf: 0, level: 0 };
  // крошечный беззвучный wav: «разблокировать» звук на iPhone по первому нажатию
  const SILENT = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQIAAACAgA==';
  const STATE_TEXT = { idle: 'Нажмите на шар или скажите что-нибудь', listen: 'Слушаю…', think: 'Думаю…', speak: '' };
  const css = `
  #jv-btn{position:fixed;right:18px;bottom:18px;z-index:9000;width:56px;height:56px;border-radius:50%;border:0;padding:0;cursor:pointer;
    background:transparent;box-shadow:0 8px 26px rgba(95,246,255,.35)}
  #jv-btn .jv-mini{display:block;width:100%;height:100%;border-radius:50%}
  .jv-orbbg{background:radial-gradient(circle,#0b2a2e 0 34%,rgba(95,246,255,.15) 38%,transparent 46%,#5ff6ff 56%,rgba(95,246,255,.25) 60%,
      transparent 66%,rgba(95,246,255,.6) 72%,transparent 78%),#04090c;box-shadow:0 0 14px rgba(95,246,255,.45);
    filter:saturate(1.1)}
  #jv-panel{position:fixed;right:18px;bottom:86px;z-index:9000;width:min(370px,calc(100vw - 32px));height:min(520px,calc(100vh - 120px));
    display:flex;flex-direction:column;border-radius:20px;overflow:hidden;
    background:rgba(13,17,28,.96);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);color:#e9eefb;
    box-shadow:0 18px 50px rgba(0,0,0,.5),inset 0 0 0 1px rgba(255,255,255,.06);font:14px/1.45 system-ui,-apple-system,sans-serif;
    transform-origin:bottom right;animation:jvin .22s ease-out}
  @keyframes jvin{from{opacity:0;transform:scale(.92) translateY(8px)}}
  #jv-panel[hidden]{display:none}
  .jv-head{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.06)}
  .jv-head i{width:26px;height:26px;border-radius:50%;flex:none}
  .jv-head b{flex:1;font-weight:600}
  .jv-x{background:none;border:0;color:#8f9bb8;font-size:20px;cursor:pointer;line-height:1;padding:4px}
  #jv-standby{font-size:16px;border-radius:10px;padding:4px 7px;filter:grayscale(1);opacity:.7}
  #jv-standby.on{filter:none;opacity:1;background:rgba(95,246,255,.15);box-shadow:inset 0 0 0 1px rgba(95,246,255,.45)}
  #jv-btn.standby{animation:jvwait 2.4s ease-in-out infinite}
  @keyframes jvwait{50%{box-shadow:0 0 0 7px rgba(95,246,255,.12),0 8px 26px rgba(95,246,255,.35)}}
  #jv-log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px}
  .jv-msg{max-width:85%;padding:9px 12px;border-radius:16px;white-space:pre-wrap;animation:jvmsg .2s ease-out}
  @keyframes jvmsg{from{opacity:0;transform:translateY(4px)}}
  .jv-msg.bot{background:#1a2236;border-bottom-left-radius:6px;align-self:flex-start}
  .jv-model{display:block;margin-top:4px;font-size:10px;opacity:.45}
  .jv-replay{display:block;margin-top:6px;border:0;border-radius:12px;padding:5px 10px;cursor:pointer;
    background:#2a3656;color:#cfe0ff;font:inherit;font-size:13px}
  .jv-msg.me{background:#2f6bff;color:#fff;border-bottom-right-radius:6px;align-self:flex-end}
  .jv-dots{display:inline-flex;gap:4px}.jv-dots span{width:6px;height:6px;border-radius:50%;background:#8fb2ff;animation:jvdot 1s infinite}
  .jv-dots span:nth-child(2){animation-delay:.15s}.jv-dots span:nth-child(3){animation-delay:.3s}
  @keyframes jvdot{0%,80%,100%{opacity:.25;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}
  #jv-row{display:flex;gap:8px;padding:10px 12px 12px;border-top:1px solid rgba(255,255,255,.06)}
  #jv-row input{flex:1;min-width:0;border-radius:22px;border:1px solid #273350;background:#0a0f1c;color:#e9eefb;padding:10px 14px;font:inherit;outline:none}
  #jv-row input:focus{border-color:#4f7cff}
  .jv-ib{flex:none;width:40px;height:40px;border-radius:50%;border:0;cursor:pointer;color:#fff;font-size:16px;display:grid;place-items:center}
  .jv-ib.send{background:#2f6bff}.jv-ib.voice{background:#151d31}
  .jv-ib[disabled]{opacity:.45}
  #jv-hint{color:#7f8bab;font-size:12px;padding:0 14px 10px}
  #jv-hint a{color:#8fb2ff}
  #jv-voice{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:14px;
    background:radial-gradient(ellipse at 50% 40%,#06262b 0%,#03080b 70%);animation:jvfade .25s ease-out}
  #jv-panel.voice #jv-log,#jv-panel.voice #jv-row,#jv-panel.voice #jv-hint{display:none}
  @keyframes jvfade{from{opacity:0}}
  #jv-voice[hidden]{display:none}
  .jv-orbwrap{position:relative;width:min(220px,58vw);height:min(220px,58vw)}
  .jv-orb{display:block;width:100%;height:100%;cursor:pointer;border-radius:50%}

  .jv-state{font-size:16px;color:#c9d4f0;min-height:22px;text-align:center}
  .jv-cap{max-width:100%;text-align:center;color:#9aa7c7;min-height:40px;font-size:14px;overflow:hidden;
    display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
  .jv-ctrl{display:flex;gap:16px}
  .jv-cb{width:52px;height:52px;border-radius:50%;border:0;cursor:pointer;font-size:20px;color:#fff;background:#1b2440}
  .jv-cb.end{background:#e5484d}
  @media (max-width:760px){#jv-btn{bottom:84px}#jv-panel{bottom:150px;height:min(480px,calc(100vh - 200px))}}`;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sections = () => (window.ASSIST_SECTIONS || []).filter((s) => s && s.id && s.label);
  const canRecord = () => window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
    && !!window.MediaRecorder;
  const canBrowserSR = () => window.isSecureContext && !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  // окно, переписка и голосовой режим — в sessionStorage: переход в другой раздел их не сбрасывает
  function save() {
    try {
      const msgs = [...document.querySelectorAll('#jv-log .jv-msg:not(#jv-typing)')].slice(-40)
        .map((m) => [m.classList.contains('me') ? 'me' : 'bot', m.firstChild ? m.firstChild.textContent : '']);  // без кнопки «Прослушать»
      sessionStorage.setItem('jv-state', JSON.stringify({ open: AS.open, talk: AS.talk, standby: AS.standby, msgs, hist: AS.hist.slice(-8) }));
    } catch (e) { /* приватный режим — просто без памяти */ }
  }
  function restore() {
    let st = null;
    try { st = JSON.parse(sessionStorage.getItem('jv-state') || 'null'); } catch (e) { st = null; }
    if (!st) return;
    (st.msgs || []).forEach(([who, text]) => addMsg(who, text, true));
    AS.hist = st.hist || [];
    if (st.open) { AS.open = true; $('jv-panel').hidden = false; }
    if (st.standby) setTimeout(() => setStandby(true, true), 300);  // ждёт команду и на новой странице
    else if (st.talk) setTimeout(openVoice, 300);  // разговор продолжается на новой странице
  }

  // ---------------------------------------------------------------- чат
  function addMsg(who, text, quiet) {
    const log = $('jv-log');
    if (!log || !text) return null;
    const el = document.createElement('div');
    el.className = 'jv-msg ' + who;
    el.textContent = text;
    log.appendChild(el);
    while (log.children.length > 40) log.firstChild.remove();
    log.scrollTop = log.scrollHeight;
    if (!quiet) save();
    return el;
  }
  function typing(on) {
    const old = $('jv-typing');
    if (old) old.remove();
    if (!on) return;
    const el = addMsg('bot', ' ');
    if (el) { el.id = 'jv-typing'; el.innerHTML = '<span class="jv-dots"><span></span><span></span><span></span></span>'; }
  }
  function caption(text) { const c = $('jv-cap'); if (c) c.textContent = text || ''; }

  // ------------------------------------------------- состояние и шар
  function setState(st, text) {
    AS.state = st;
    const v = $('jv-voice');
    if (v) v.className = st;
    const s = $('jv-state');
    if (s) s.textContent = text != null ? text : STATE_TEXT[st];
  }
  function audioCtx() {
    AS.ctx = AS.ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (AS.ctx.state === 'suspended' && AS.ctx.resume) AS.ctx.resume();
    return AS.ctx;
  }
  function levelOf(an) {
    if (!an) return 0;
    const buf = new Uint8Array(an.fftSize);
    an.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i += 1) { const x = (buf[i] - 128) / 128; sum += x * x; }
    return Math.min(1, Math.sqrt(sum / buf.length) * 4);
  }
  // Голограмма: кольца из светящихся частиц, каркасная сфера и надпись. Реагирует на голос:
  // слушает — частицы дрожат от микрофона, говорит — кольца пульсируют, думает — всё вращается быстрее.
  const HOLO = { dots: [], seed: 0 };
  function holoInit() {
    for (let i = 0; i < 520; i += 1) {
      const ring = i % 3;  // 0 — внешнее толстое кольцо, 1 — тонкое, 2 — внутренний пояс
      HOLO.dots.push({ a: Math.random() * Math.PI * 2, ring, off: (Math.random() - 0.5) * (ring === 0 ? 0.07 : 0.03),
        sp: (0.02 + Math.random() * 0.05) * (Math.random() < 0.5 ? -1 : 1), tw: Math.random() * 6.28, sz: 0.5 + Math.random() * 1.3 });
    }
  }
  function drawHolo(c, t, lvl) {
    const ctx = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth;
    if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(w * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, w);
    const cx = w / 2;
    const R = w * 0.44;
    const fast = AS.state === 'think' ? 3.2 : 1;
    const pulse = 1 + lvl * 0.07;
    ctx.globalCompositeOperation = 'lighter';
    // мягкое свечение
    const g = ctx.createRadialGradient(cx, cx, R * 0.2, cx, cx, R * 1.1);
    g.addColorStop(0, `rgba(40,200,220,${0.10 + lvl * 0.25})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, w);
    // каркасная сфера: меридианы и параллели, вращается
    const rot = t * 0.35 * fast;
    const sr = R * 0.42 * pulse;
    ctx.strokeStyle = `rgba(95,246,255,${0.16 + lvl * 0.3})`;
    ctx.lineWidth = 0.7;
    for (let m = 0; m < 10; m += 1) {
      const ang = rot + (m * Math.PI) / 10;
      ctx.beginPath();
      ctx.ellipse(cx, cx, Math.abs(Math.cos(ang)) * sr, sr, 0, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let k = -3; k <= 3; k += 1) {
      const y = (k / 4) * sr;
      const rx = Math.sqrt(Math.max(0, sr * sr - y * y));
      ctx.beginPath();
      ctx.ellipse(cx, cx + y, rx, rx * 0.18, 0, 0, Math.PI * 2);
      ctx.stroke();
    }
    // кольца из частиц
    HOLO.dots.forEach((d) => {
      d.a += d.sp * 0.016 * fast;
      const base = d.ring === 0 ? R : d.ring === 1 ? R * 0.86 : R * 0.62;
      const jitter = (AS.state === 'listen' ? lvl * 0.07 : lvl * 0.035) * Math.sin(t * 9 + d.tw * 3);
      const r = base * pulse * (1 + d.off + jitter * (d.ring === 2 ? 0.5 : 1));
      const x = cx + Math.cos(d.a) * r;
      const y = cx + Math.sin(d.a) * r;
      const al = 0.35 + 0.45 * Math.abs(Math.sin(t * 1.5 + d.tw)) + lvl * 0.3;
      ctx.fillStyle = `rgba(110,250,255,${Math.min(1, al)})`;
      ctx.beginPath();
      ctx.arc(x, y, d.sz * (1 + lvl * 0.35), 0, Math.PI * 2);
      ctx.fill();
    });
    // штрихи-сегменты по внешнему кольцу (как у HUD)
    ctx.strokeStyle = `rgba(95,246,255,${0.35 + lvl * 0.4})`;
    ctx.lineWidth = 2;
    for (let i = 0; i < 6; i += 1) {
      const st = -t * 0.25 * fast + (i * Math.PI) / 3;
      ctx.beginPath();
      ctx.arc(cx, cx, R * 1.06 * pulse, st, st + 0.42);
      ctx.stroke();
    }
    // надпись
    ctx.globalCompositeOperation = 'source-over';
    ctx.save();
    ctx.translate(cx, cx);
    ctx.transform(1, 0, -0.18, 1, 0, 0);  // наклон, как у голограммы
    ctx.font = `800 ${Math.round(w * 0.135)}px system-ui,-apple-system,sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(95,246,255,.9)';
    ctx.shadowBlur = 14 + lvl * 20;
    ctx.fillStyle = `rgba(200,252,255,${0.82 + lvl * 0.18})`;
    ctx.fillText('JARVIS', 0, 0);
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 0.35;  // «помехи» голограммы
    ctx.fillStyle = '#5ff6ff';
    for (let i = 0; i < 4; i += 1) {
      const yy = ((t * 40 + i * 23) % (w * 0.16)) - w * 0.08;
      ctx.fillRect(-w * 0.3, yy, w * 0.6, 1);
    }
    ctx.restore();
  }
  function animate() {
    const orb = $('jv-orb');
    if (!orb || $('jv-voice').hidden || $('jv-panel').hidden) { AS.raf = 0; return; }
    if (!HOLO.dots.length) holoInit();
    // «уменьшить движение» в системе — голограмма почти неподвижна
    const t = performance.now() / (matchMedia('(prefers-reduced-motion: reduce)').matches ? 6000 : 1000);
    let target = 0.05 + Math.sin(t * 1.6) * 0.03;  // спокойное дыхание
    if (AS.state === 'listen') target = 0.08 + levelOf(AS.micAn) * 0.9;
    if (AS.state === 'speak') target = 0.12 + levelOf(AS.outAn) * 1.0;
    if (AS.state === 'think') target = 0.12 + Math.sin(t * 5) * 0.06;
    AS.level += (target - AS.level) * 0.22;
    drawHolo(orb, t, Math.min(1, Math.max(0, AS.level)));
    AS.raf = requestAnimationFrame(animate);
  }

  // ---------------------------------------------------------------- звук
  // Safari даёт звук только элементу, который уже играл по нажатию: зовём это в обработчике нажатия
  // («Войти», кнопки Джарвиса). Анализатор для шара подключаем, только когда AudioContext реально запущен —
  // иначе звук пошёл бы в «спящий» контекст и стал бы беззвучным.
  function unlockAudio() {
    const ctx = audioCtx();
    if (!AS.audio) AS.audio = new Audio();
    if (AS.audio.paused) {
      AS.audio.src = SILENT;
      AS.audio.play().catch(() => { /* без звука — останется текст и кнопка «Прослушать» */ });
    }
    const route = () => {
      if (AS.outAn || ctx.state !== 'running') return;
      try {  // уровень звука ответа — для шара
        const src = ctx.createMediaElementSource(AS.audio);
        AS.outAn = ctx.createAnalyser();
        AS.outAn.fftSize = 512;
        src.connect(AS.outAn);
        AS.outAn.connect(ctx.destination);
      } catch (e) { AS.outAn = null; }
    };
    if (ctx.state === 'running') route();
    else if (ctx.resume) ctx.resume().then(route).catch(() => { /* без анализатора */ });
  }
  window.assistUnlock = unlockAudio;

  // браузер не дал звук без нажатия — у фразы появляется кнопка «Прослушать»
  function offerReplay(text, audio) {
    const last = [...document.querySelectorAll('#jv-log .jv-msg.bot')].pop();
    if (!last || last.querySelector('.jv-replay')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'jv-replay';
    b.textContent = '🔊 Прослушать';
    b.addEventListener('click', () => { unlockAudio(); b.remove(); speak(text, audio); });
    last.appendChild(b);
  }

  function afterSpeak() {
    setState('idle');
    if (leave()) return;  // открываем другую страницу — разговор продолжится там
    if (AS.goSleep) { AS.goSleep = false; return sleep(); }
    if (AS.talk) setTimeout(listen, 300);
  }

  function speakBrowser(text) {  // запасной голос браузера — только если Мак не прислал звук
    try {
      if (!window.speechSynthesis || !text) return afterSpeak();
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'ru-RU';
      const ru = speechSynthesis.getVoices().filter((x) => /^ru/i.test(x.lang));
      const v = ru.find((x) => /yuri|юрий/i.test(x.name)) || ru[0];
      if (v) u.voice = v;
      u.onend = u.onerror = afterSpeak;
      speechSynthesis.speak(u);
    } catch (e) { afterSpeak(); }
  }

  function speak(text, audio) {
    setState('speak', '');
    caption(text);
    if (!audio) return speakBrowser(text);
    if (!AS.audio) AS.audio = new Audio();
    const el = AS.audio;
    el.onended = afterSpeak;
    el.onerror = afterSpeak;
    el.src = 'data:audio/mp4;base64,' + audio;
    el.play().catch(() => { offerReplay(text, audio); afterSpeak(); });  // Safari без нажатия молчит
  }

  function go(id) {
    const s = sections().find((x) => x.id === id);
    if (!s) return;
    const href = s.href || ('#/' + s.id);
    if (href.startsWith('#')) { location.hash = href; return; }
    if (href === location.pathname + location.search) return;
    AS.pendingHref = href;
    setTimeout(leave, 8000);  // на случай, если звук не доиграл
  }
  function leave() {
    if (!AS.pendingHref) return false;
    const href = AS.pendingHref;
    AS.pendingHref = '';
    save();
    location.href = href;
    return true;
  }

  async function ask(text) {
    text = (text || '').trim();
    if (AS.busy || !text) return;
    AS.busy = true;
    $('jv-send').disabled = true;
    addMsg('me', text);
    typing(true);
    setState('think');
    caption(text);
    try {
      const res = await fetch('/api/assistant', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ текст: text, разделы: sections().map((s) => ({ id: s.id, label: s.label })),
          история: AS.hist.slice(-8) }),
      });
      const data = (await res.json()).data || {};
      AS.hist.push({ role: 'user', content: text }, { role: 'assistant', content: data.ответ || '' });
      save();
      typing(false);
      const msg = addMsg('bot', data.ответ || '');
      if (msg && data.модель) {  // подпись, какая модель ответила: «gpt-oss-120b · облако» / «qwen3.5:4b · локально»
        const tag = document.createElement('span');
        tag.className = 'jv-model';
        tag.textContent = data.модель;
        msg.appendChild(tag);
      }
      AS.busy = false;
      speak(data.ответ || '', data.аудио || '');
      if (data.открыть) go(data.открыть);
    } catch (e) {
      typing(false);
      addMsg('bot', 'Связь прервалась, сэр. Попробуйте ещё раз.');
      AS.busy = false;
      setState('idle');
      if (AS.talk) setTimeout(listen, 800);
    } finally {
      $('jv-send').disabled = false;
    }
  }

  async function sendAudio(blob) {
    setState('think', 'Распознаю…');
    try {
      const r = await fetch('/api/assistant/stt', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
      const j = await r.json();
      const t = ((j && j.data) || {}).текст || '';
      if (!AS.talk) {  // спит: ждём имя, остальное — мимо ушей
        if (AS.standby && WAKE.test(t)) return wake(t);
        if (AS.standby) setTimeout(listen, 200);
        return;
      }
      if (t) {
        $('jv-in').value = '';
        AS.heardAt = Date.now();
        if (AS.standby && SLEEP.test(t)) AS.goSleep = true;  // ответит и уснёт
        return ask(t);
      }
      setState('idle', j && j.ok === false ? 'Распознавание на сервере недоступно' : 'Не расслышал, повторите');
    } catch (e) { if (AS.talk) setState('idle', 'Не расслышал, повторите'); }
    if (AS.talk || AS.standby) setTimeout(listen, 700);
  }

  // ------------------------------------------- режим ожидания: «Джарвис» будит, «спи» — усыпляет
  const WAKE = /д?ж[ае]рв[иы][сз]|jarvis|джарви\b/i;
  // целые слова: «спичек», «спит» не усыпляют (\b в JS не работает с кириллицей)
  const SLEEP = /(^|[\s,.!?])(спи|засыпай|отбой|свободен|можешь идти|отдыхай|до свидания|пока,?\s*джарвис)(?=$|[\s,.!?])/i;

  function wake(text) {
    AS.heardAt = Date.now();
    showVoice();
    ask(text);  // «проснись, Джарвис, папочка вернулся» — ответит сам, по-человечески
  }

  function sleep() {  // обратно в ожидание: окно разговора прячем, микрофон ждёт имя
    AS.talk = false;
    const v = $('jv-voice');
    if (v) v.hidden = true;
    const pn = $('jv-panel');
    if (pn) pn.classList.remove('voice');
    setState('idle');
    save();
    if (AS.standby) setTimeout(listen, 400);
  }

  function setStandby(on, restored) {
    AS.standby = on;
    const b = $('jv-standby');
    if (b) { b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }
    $('jv-btn').classList.toggle('standby', on);
    save();
    if (!on) { stopTalk(true); return; }
    if (!restored) addMsg('bot', 'Буду ждать, сэр. Скажите «Джарвис», когда понадоблюсь.');
    if (AS.talk) return;
    if (audioCtx().state === 'running') { listen(); return; }
    // после перезагрузки страницы браузер ждёт любое нажатие, прежде чем дать микрофону «уши»
    $('jv-btn').title = 'Нажмите где угодно на странице — Джарвис снова будет ждать команду';
    const resume = () => { document.removeEventListener('pointerdown', resume, true); unlockAudio();
      audioCtx().resume().then(() => { $('jv-btn').title = 'Джарвис'; if (AS.standby && !AS.talk) listen(); }); };
    document.addEventListener('pointerdown', resume, true);
  }

  // Запись до паузы: говорите — после ~1 с тишины запись уходит на Мак (Whisper)
  async function listen() {
    if (AS.busy || AS.rec) return;
    if (canRecord() && audioCtx().state !== 'running') {
      if (AS.talk) setState('idle', 'Нажмите на шар — продолжим разговор');
      return;
    }
    if (AS.talk && AS.standby && AS.heardAt && Date.now() - AS.heardAt > 40000) return sleep();
    if (!canRecord()) return canBrowserSR() ? listenBrowser() : setState('idle', 'Голос — только по https');
    try {
      if (!AS.stream) AS.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) { AS.standby = false; stopTalk(true); addMsg('bot', 'Браузер не дал микрофон, сэр.'); return; }
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((t) => MediaRecorder.isTypeSupported(t)) || '';
    const rec = AS.rec = new MediaRecorder(AS.stream, mime ? { mimeType: mime } : {});
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const ctx = audioCtx();
    const src = ctx.createMediaStreamSource(AS.stream);
    const an = AS.micAn = ctx.createAnalyser();
    an.fftSize = 1024;
    src.connect(an);
    const start = Date.now();
    let spoke = false;
    let quiet = start;
    if (AS.talk) { setState('listen'); caption(''); }
    const timer = setInterval(() => {
      const now = Date.now();
      if (levelOf(an) > 0.12) { spoke = true; quiet = now; }
      if ((spoke && now - quiet > 1100) || now - start > 15000 || (!spoke && now - start > (AS.talk ? 8000 : 20000))) {
        if (rec.state !== 'inactive') rec.stop();
      }
    }, 100);
    rec.onstop = () => {
      clearInterval(timer);
      src.disconnect();
      AS.micAn = null;
      AS.rec = null;
      if (rec.cancelled) return;
      if (!spoke) { if (AS.talk || AS.standby) setTimeout(listen, 200); else setState('idle'); return; }
      sendAudio(new Blob(chunks, { type: rec.mimeType || mime || 'audio/webm' }));
    };
    rec.start(250);
  }

  function listenBrowser() {  // если записывать нельзя — распознавание самого браузера
    const R = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new R();
    r.lang = 'ru-RU';
    r.interimResults = true;
    let heard = '';
    setState('listen');
    r.onresult = (e) => { heard = [...e.results].map((x) => x[0].transcript).join(' '); caption(heard); };
    r.onend = () => {
      if (heard.trim() && !AS.talk) { if (AS.standby && WAKE.test(heard)) wake(heard); else if (AS.standby) setTimeout(listen, 300); return; }
      if (heard.trim()) ask(heard); else if (AS.talk || AS.standby) setTimeout(listen, 300); else setState('idle');
    };
    r.onerror = (e) => { if (e.error === 'not-allowed') { AS.standby = false; stopTalk(true); addMsg('bot', 'Браузер не дал микрофон, сэр.'); } };
    try { r.start(); } catch (e) { /* уже слушает */ }
  }

  // ------------------------------------------------- голосовой режим
  function showVoice() {
    AS.talk = true;
    AS.open = true;
    $('jv-panel').hidden = false;
    $('jv-panel').classList.add('voice');
    $('jv-voice').hidden = false;
    save();
    if (!AS.raf) AS.raf = requestAnimationFrame(animate);
  }

  function openVoice() {
    unlockAudio();
    audioCtx();
    if (AS.rec) { AS.rec.cancelled = true; try { AS.rec.stop(); } catch (e) { /* уже остановлен */ } AS.rec = null; }
    showVoice();
    AS.heardAt = Date.now();
    if (AS.audio) { try { AS.audio.pause(); } catch (e) { /* не играл */ } }
    listen();
  }

  function stopTalk(full) {
    if (AS.standby && !full) {  // ожидание включено — не выключаем микрофон, просто засыпаем
      if (AS.rec) { AS.rec.cancelled = true; try { AS.rec.stop(); } catch (e) { /* уже остановлен */ } AS.rec = null; }
      if (AS.audio) { try { AS.audio.pause(); } catch (e) { /* не играл */ } }
      return sleep();
    }
    AS.talk = false;
    if (AS.rec) { AS.rec.cancelled = true; try { AS.rec.stop(); } catch (e) { /* уже остановлен */ } }
    if (AS.stream) { AS.stream.getTracks().forEach((t) => t.stop()); AS.stream = null; }  // гасим значок микрофона
    if (AS.audio) { try { AS.audio.pause(); } catch (e) { /* не играл */ } }
    try { speechSynthesis.cancel(); } catch (e) { /* без голоса */ }
    const v = $('jv-voice');
    if (v) v.hidden = true;
    const pn = $('jv-panel');
    if (pn) pn.classList.remove('voice');
    setState('idle');
    save();
  }

  function build() {
    const st = document.createElement('style');
    st.textContent = css;
    document.head.appendChild(st);
    const mic = canRecord() || canBrowserSR();
    document.body.insertAdjacentHTML('beforeend', `
      <button id="jv-btn" type="button" aria-label="Джарвис — помощник" title="Джарвис"><span class="jv-mini jv-orbbg"></span></button>
      <div id="jv-panel" hidden role="dialog" aria-label="Джарвис">
        <div class="jv-head"><i class="jv-orbbg"></i><b>Джарвис</b>
          <button class="jv-x" id="jv-standby" aria-pressed="false" title="Ждать команду «Джарвис» (микрофон всегда включён)">👂</button>
          <button class="jv-x" id="jv-close" aria-label="Закрыть">×</button></div>
        <div id="jv-log" aria-live="polite"></div>
        <div id="jv-voice" hidden aria-label="Голосовой разговор с Джарвисом">
          <div class="jv-orbwrap"><canvas class="jv-orb" id="jv-orb" title="Нажмите, чтобы говорить" aria-label="Джарвис"></canvas></div>
          <div class="jv-state" id="jv-state"></div>
          <div class="jv-cap" id="jv-cap"></div>
          <div class="jv-ctrl"><button class="jv-cb" id="jv-chat" aria-label="К переписке" title="Переписка">💬</button>
            <button class="jv-cb end" id="jv-end" aria-label="Закончить разговор" title="Закончить">✕</button></div>
        </div>
        <form id="jv-row">
          <input id="jv-in" autocomplete="off" placeholder="Спросите или скажите «открой приход»">
          ${mic ? '<button type="button" class="jv-ib voice" id="jv-mic" aria-label="Голосовой режим" title="Голосовой режим">🎙</button>' : ''}
          <button class="jv-ib send" id="jv-send" type="submit" aria-label="Отправить">↑</button>
        </form>
        ${mic ? '' : '<div id="jv-hint">Голос работает по https: <a href="/ca">поставить сертификат</a>. Здесь пишите текстом.</div>'}
      </div>`);
    const toggle = () => {
      unlockAudio();
      AS.open = !AS.open;
      $('jv-panel').hidden = !AS.open;
      if (!AS.open && AS.talk) stopTalk();
      if (AS.open && !AS.talk) $('jv-in').focus();
      save();
    };
    $('jv-btn').addEventListener('click', toggle);
    $('jv-close').addEventListener('click', toggle);
    $('jv-row').addEventListener('submit', (e) => { e.preventDefault(); unlockAudio(); ask($('jv-in').value); $('jv-in').value = ''; });
    if ($('jv-mic')) $('jv-mic').addEventListener('click', openVoice);
    $('jv-end').addEventListener('click', () => stopTalk());
    $('jv-standby').addEventListener('click', () => { unlockAudio(); setStandby(!AS.standby); });
    $('jv-chat').addEventListener('click', () => stopTalk());
    $('jv-orb').addEventListener('click', async () => {  // нажали на шар — перебить и слушать
      if (AS.audio) { try { AS.audio.pause(); } catch (e) { /* не играл */ } }
      const ctx = audioCtx();
      if (ctx.state !== 'running') { try { await ctx.resume(); } catch (e) { /* остаётся текст */ } }
      if (AS.audio) { AS.audio.src = SILENT; AS.audio.play().catch(() => { /* без звука */ }); }
      if (AS.state !== 'listen' && !AS.busy) listen();
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('jv-voice').hidden) stopTalk(); });
    restore();
  }

  // другой человек на этом устройстве — его переписку и приветствие не показываем следующему
  window.assistForget = function () {
    try { sessionStorage.removeItem('jv-state'); sessionStorage.removeItem('jv-hello'); } catch (e) { /* приватный режим */ }
    AS.hist = [];
    const log = $('jv-log');
    if (log) log.innerHTML = '';
  };

  // выход: Джарвис прощается по имени и отчеству, потом страница выходит (не дольше 5 с)
  window.assistBye = async function () {
    if (!$('jv-btn')) return;
    AS.standby = false;  // вышел — микрофон больше не слушает
    stopTalk(true);
    unlockAudio();
    try {
      const d = ((await fetch('/api/assistant/bye', { credentials: 'same-origin' }).then((r) => r.json())) || {}).data || {};
      AS.open = true;
      $('jv-panel').hidden = false;
      addMsg('bot', d.текст || '', true);
      if (d.аудио) {
        await new Promise((done) => {
          const el = AS.audio;
          el.onended = done;
          el.onerror = done;
          el.src = 'data:audio/mp4;base64,' + d.аудио;
          el.play().catch(done);
          setTimeout(done, 5000);
        });
      }
    } catch (e) { /* без прощания — просто выходим */ }
    window.assistForget();
    AS.open = false;
    $('jv-panel').hidden = true;
    $('jv-btn').hidden = true;
  };

  // страница зовёт после входа и при смене меню; приветствие — раз на вход этого сотрудника
  window.assistMount = async function () {
    if (!$('jv-btn')) build();
    try {
      const res = await fetch('/api/assistant/hello', { credentials: 'same-origin' });
      if (res.status === 401) { $('jv-btn').hidden = true; $('jv-panel').hidden = true; AS.standby = false; stopTalk(true); return; }
      const text = ((await res.json()).data || {}).текст || '';
      $('jv-btn').hidden = false;
      let last = '';
      try { last = sessionStorage.getItem('jv-hello') || ''; } catch (e) { /* приватный режим */ }
      const who = text.replace(/^[^,]+,\s*/, '');  // без «Добрый вечер» — одно приветствие на человека
      if (last === who) return;
      try { sessionStorage.setItem('jv-hello', who); } catch (e) { /* приватный режим */ }
      AS.open = true;
      $('jv-panel').hidden = false;
      addMsg('bot', text);
      const voiced = await fetch('/api/assistant/hello?голос=1', { credentials: 'same-origin' }).then((r) => r.json()).catch(() => ({}));
      speak(text, ((voiced && voiced.data) || {}).аудио || '');
    } catch (e) { /* сервер недоступен — кнопка просто не нужна */ }
  };
}());
