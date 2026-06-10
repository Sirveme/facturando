/* ============================================================================
   importadores.js — interacciones de la landing /importadores
   Sin librerías. Solo: (1) reveal al scroll, (2) FOMO honesto, (3) modal Premium
   en flujo normal. Vanilla JS, consistente con el proyecto.
   ============================================================================ */
(function () {
  "use strict";

  // Habilita los estilos de reveal solo si hay JS (sin JS, todo se ve igual).
  document.documentElement.classList.add("js");

  /* ──────────────────────────────────────────────────────────────────────────
     EDITABLE POR EL CLIENTE — eventos del FOMO (esquina inferior izquierda).
     REGLAS: hechos VERACES y ANONIMIZADOS. Atemporales (no "hace 2 min" si no es
     exacto). Para agregar/editar: añade objetos { ico, html } a esta lista.
     'html' admite <b>…</b> para resaltar. NO inventar nombres de empresas reales.
     ────────────────────────────────────────────────────────────────────────── */
  var FOMO_EVENTS = [
    { ico: "📦", html: "Una <b>importadora de Lima</b> inició su prueba." },
    { ico: "🏪", html: "Una <b>ferretería de Áncash</b> consultó por WhatsApp." },
    { ico: "🚚", html: "Un <b>comercio mayorista</b> emitió sus guías de remisión." },
    { ico: "🧾", html: "Una <b>empresa</b> emite a diario, aceptada por SUNAT." },
    { ico: "🧮", html: "Un <b>importador</b> conectó facturas, guías e inventario." }
  ];

  // Cada cuánto rota / cuánto se ve cada aviso (ms). Lenta y no intrusiva.
  var FOMO_FIRST_DELAY = 4000;   // espera inicial
  var FOMO_VISIBLE     = 6000;   // tiempo visible
  var FOMO_GAP         = 9000;   // pausa entre avisos

  /* ── 1 · REVEAL AL SCROLL (IntersectionObserver) ───────────────────────────*/
  function initReveal() {
    var els = document.querySelectorAll(".ld-reveal");
    if (!els.length) return;

    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("is-visible");
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.12 });

    els.forEach(function (el) { io.observe(el); });
  }

  /* ── 2 · MODAL PREMIUM (en flujo normal, no position:fixed) ─────────────────*/
  function initModal() {
    document.addEventListener("click", function (ev) {
      var opener = ev.target.closest("[data-ld-open]");
      if (opener) {
        var m = document.getElementById(opener.getAttribute("data-ld-open"));
        if (m) {
          m.classList.add("is-open");
          opener.setAttribute("aria-expanded", "true");
          // Lleva el modal a la vista suavemente (vive en el flujo del documento).
          if (m.scrollIntoView) m.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        return;
      }
      var closer = ev.target.closest("[data-ld-close]");
      if (closer) {
        var id = closer.getAttribute("data-ld-close");
        var panel = document.getElementById(id);
        if (panel) panel.classList.remove("is-open");
        var trigger = document.querySelector('[data-ld-open="' + id + '"]');
        if (trigger) {
          trigger.setAttribute("aria-expanded", "false");
          trigger.focus();
        }
      }
    });

    // Cerrar con Escape el modal abierto.
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      document.querySelectorAll(".ld-modal-inline.is-open").forEach(function (panel) {
        panel.classList.remove("is-open");
        var trigger = document.querySelector('[data-ld-open="' + panel.id + '"]');
        if (trigger) trigger.setAttribute("aria-expanded", "false");
      });
    });
  }

  /* ── 3 · FOMO (notificaciones flotantes honestas) ──────────────────────────*/
  function initFomo() {
    var box = document.getElementById("ld-fomo");
    if (!box || !FOMO_EVENTS.length) return;

    var i = 0, dismissed = false, timer = null;

    function render(ev) {
      box.innerHTML =
        '<span class="ld-fomo-av">' + ev.ico + "</span>" +
        '<span class="ld-fomo-txt">' + ev.html + "</span>" +
        '<button class="ld-fomo-x" type="button" aria-label="Cerrar aviso">&times;</button>';
      box.querySelector(".ld-fomo-x").addEventListener("click", function () {
        dismissed = true;
        box.classList.remove("is-show");
        if (timer) clearTimeout(timer);
      });
    }

    function cycle() {
      if (dismissed) return;
      render(FOMO_EVENTS[i % FOMO_EVENTS.length]);
      i++;
      box.classList.add("is-show");
      timer = setTimeout(function () {
        box.classList.remove("is-show");
        timer = setTimeout(cycle, FOMO_GAP);
      }, FOMO_VISIBLE);
    }

    timer = setTimeout(cycle, FOMO_FIRST_DELAY);
  }

  function init() {
    initReveal();
    initModal();
    initFomo();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
