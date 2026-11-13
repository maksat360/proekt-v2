/* ============================================================
   JARVIS Intro — логика показа
   Показывается один раз за сессию (sessionStorage).
   Принудительный повтор: добавьте ?intro=1 к адресу страницы.
   Клик или любая клавиша — пропустить.
   ============================================================ */
(function () {
  "use strict";

  // Путь к логотипу: по умолчанию — logo.png рядом с этим скриптом.
  // Свой путь: <script>window.JARVIS_LOGO = "/static/logo.png"</script>
  var scriptSrc = document.currentScript && document.currentScript.src;
  var base = scriptSrc ? scriptSrc.slice(0, scriptSrc.lastIndexOf("/") + 1) : "";
  var LOGO_SRC = window.JARVIS_LOGO || base + "logo.png";

  var HOLD_MS = 2500;      // сколько держим интро после старта
  var FADE_MS = 420;       // длительность ухода (синхронно с CSS transition)

  var params = new URLSearchParams(location.search);
  var forced = params.get("intro") === "1";
  if (!forced && sessionStorage.getItem("jarvis-intro-seen")) return;
  sessionStorage.setItem("jarvis-intro-seen", "1");

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) HOLD_MS = 1200;

  // ---- Разметка ----
  var bootLines = [
    "JARVIS OS · link established",
    "загрузка модулей интерфейса <span class='ok'>[ok]</span>",
    "синхронизация данных <span class='ok'>[ok]</span>",
    "добро пожаловать"
  ];

  function ring(dash, extra) {
    return (
      '<svg viewBox="0 0 100 100" fill="none" aria-hidden="true">' +
      '<circle cx="50" cy="50" r="48.5" stroke="rgba(103,232,249,.28)" stroke-width=".6" stroke-dasharray="' + dash + '"/>' +
      (extra || "") +
      "</svg>"
    );
  }

  var ticks = "";
  for (var i = 0; i < 60; i++) {
    var a = (i * 6 * Math.PI) / 180;
    var long = i % 5 === 0;
    var r1 = long ? 45 : 46.5, r2 = 48.5;
    ticks +=
      '<line x1="' + (50 + r1 * Math.cos(a)).toFixed(2) + '" y1="' + (50 + r1 * Math.sin(a)).toFixed(2) +
      '" x2="' + (50 + r2 * Math.cos(a)).toFixed(2) + '" y2="' + (50 + r2 * Math.sin(a)).toFixed(2) +
      '" stroke="rgba(103,232,249,' + (long ? ".5" : ".22") + ')" stroke-width=".5"/>';
  }

  var el = document.createElement("div");
  el.className = "jarvis-intro";
  el.setAttribute("role", "presentation");
  el.innerHTML =
    '<div class="ji-corner ji-corner--tl"></div>' +
    '<div class="ji-corner ji-corner--tr"></div>' +
    '<div class="ji-corner ji-corner--bl"></div>' +
    '<div class="ji-corner ji-corner--br"></div>' +
    '<div class="jarvis-stage">' +
      '<div class="ji-ring ji-ring--outer">' + ring("1 3", ticks) + "</div>" +
      '<div class="ji-ring ji-ring--middle">' + ring("20 6 4 6") + "</div>" +
      '<div class="ji-ring ji-ring--inner">' + ring("8 4 2 4 2 4") + "</div>" +
      '<img class="ji-logo" src="' + LOGO_SRC + '" alt="">' +
      '<div class="ji-scan"></div>' +
      '<div class="ji-tag">Инициализация интерфейса</div>' +
    "</div>" +
    '<div class="ji-boot">' +
      bootLines.map(function (line, i) {
        var delay = reduced ? 0 : 120 + i * 140;
        return '<div class="ji-boot-line" style="animation-delay:' + delay + 'ms">&gt; ' + line + "</div>";
      }).join("") +
    "</div>" +
    '<div class="ji-skip">CLICK — ПРОПУСТИТЬ</div>';

  document.documentElement.style.overflow = "hidden";
  document.body.appendChild(el);

  // ---- Уход ----
  var done = false;
  function dismiss() {
    if (done) return;
    done = true;
    el.classList.add("is-leaving");
    document.documentElement.style.overflow = "";
    setTimeout(function () { el.remove(); }, FADE_MS + 60);
    window.removeEventListener("keydown", dismiss);
  }

  el.addEventListener("click", dismiss);
  window.addEventListener("keydown", dismiss);
  setTimeout(dismiss, HOLD_MS + FADE_MS);
})();
