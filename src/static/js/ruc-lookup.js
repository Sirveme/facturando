/* ============================================================
   Lookup RUC/DNI unificado (zGuia-12)
   Disparo AUTOMÁTICO al completar los dígitos (sin lupa), debounce 250ms,
   guard anti-repetición, marca persistente en el campo número y acción
   "reintentar" inline ante error de red.

   Uso:
     RucLookup.attach({
       input:      <input del número>,
       getTipo:    () => '6' | '1' | '4' | ...,   // 6=RUC, 1=DNI
       status:     <span host para ✓ / ● / reintentar>   (opcional),
       tipoSelect: <select de tipo doc>           (opcional, limpia al cambiar),
       onResult:   (datos|null, {baja, notFound, tipo}) => {}
     });
   Endpoints: GET /api/ruc/{n}  ·  GET /api/dni/{n}  (auth del dashboard).
   ============================================================ */
(function () {
  'use strict';

  var EXPECTED = { '6': 11, '1': 8 };   // largo exacto por tipo de documento

  function attach(opts) {
    var input = opts.input;
    if (!input) return;
    var getTipo = opts.getTipo || function () { return '6'; };
    var onResult = opts.onResult || function () {};
    var status = opts.status || null;
    var lastQueried = null;
    var timer = null;

    function mark(state, title) {
      input.classList.remove('ruc-ok', 'ruc-warn', 'ruc-invalid');
      if (state) input.classList.add(state);
      if (title) input.setAttribute('title', title); else input.removeAttribute('title');
    }
    function setStatus(html) { if (status) status.innerHTML = html || ''; }
    function badge(cls, glyph, title) {
      var t = title ? ' title="' + String(title).replace(/"/g, '&quot;') + '"' : '';
      return '<span class="ruc-badge ruc-badge--' + cls + '"' + t + '>' + glyph + '</span>';
    }

    function run(tipo, numero) {
      setStatus('<span class="ruc-spin" aria-label="Consultando"></span>');
      var ep = (tipo === '6') ? ('/api/ruc/' + numero) : ('/api/dni/' + numero);
      fetch(ep).then(function (r) { return r.json(); }).then(function (res) {
        if (res && res.exito && res.datos) {
          var d = res.datos;
          var baja = (tipo === '6' && d.habilitado === false);
          if (baja) {
            var t = 'Estado: ' + (d.estado || '—') + ' · Condición: ' + (d.condicion || '—');
            mark('ruc-warn', t);
            setStatus(badge('warn', '●', t));
          } else {
            mark('ruc-ok', 'Documento validado');
            setStatus(badge('ok', '✓', 'Validado'));
          }
          onResult(d, { baja: baja, tipo: tipo });
        } else {
          var msg = (res && res.mensaje) || 'No encontrado';
          mark('ruc-invalid', msg);
          setStatus(badge('warn', '!', msg));
          onResult(null, { notFound: true, tipo: tipo });
        }
      }).catch(function () {
        // Solo error de RED: ofrecer reintento inline + toast.
        setStatus('<a href="#" class="ruc-retry">⚠ reintentar</a>');
        if (status) {
          var a = status.querySelector('.ruc-retry');
          if (a) a.addEventListener('click', function (ev) { ev.preventDefault(); run(tipo, numero); });
        }
        if (window.toast) toast.error('Error de red', 'No se pudo consultar el documento.');
      });
    }

    input.addEventListener('input', function () {
      var tipo = getTipo();
      var exp = EXPECTED[tipo];
      var raw = (input.value || '').trim();
      clearTimeout(timer);

      // Tipo sin lookup (CE/otros) o campo vacío → limpiar marcas.
      if (!exp || raw === '') { mark(null, null); setStatus(''); lastQueried = null; return; }
      // No numérico o excede el largo esperado → inválido suave, no consultar.
      if (/\D/.test(raw) || raw.length > exp) {
        mark('ruc-invalid', 'Use solo dígitos (' + exp + ')');
        setStatus(''); lastQueried = null; return;
      }
      // Aún incompleto → sin marca.
      if (raw.length < exp) { mark(null, null); setStatus(''); lastQueried = null; return; }
      // Exactamente `exp` dígitos numéricos.
      if (raw === lastQueried) return;     // guard: no re-consultar el mismo número
      lastQueried = raw;
      timer = setTimeout(function () { run(tipo, raw); }, 250);
    });

    if (opts.tipoSelect) {
      opts.tipoSelect.addEventListener('change', function () {
        lastQueried = null; mark(null, null); setStatus('');
      });
    }
  }

  window.RucLookup = { attach: attach };
})();
