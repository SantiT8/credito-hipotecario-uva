/*
 * Motor de elegibilidad del dashboard: réplica en JavaScript de src/affordability.py (función evaluar)
 * y de la regla única de formato de números (src/formato.py).
 * La paridad con Python se verifica con tools/test_paridad.py.
 */
(function (raiz) {
  "use strict";

  // ---------------------------------------------------------------------------
  // Formato (es-AR): < 1 millón → "146 mil"; ≥ 1 millón → "1,4 millones"
  // ---------------------------------------------------------------------------
  function num(x, decimales) {
    var d = decimales || 0;
    var partes = Math.abs(x).toFixed(d).split(".");
    var entero = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (x < 0 && Number(partes.join(".")) !== 0 ? "−" : "") + entero + (d ? "," + partes[1] : "");
  }
  function redondear1(x) { return Math.round(x * 10) / 10; }
  function escala(x, divisor, singular, plural) {
    var v = redondear1(x / divisor);
    if (v === Math.trunc(v)) return num(v, 0) + " " + (Math.abs(v) === 1 ? singular : plural);
    return num(v, 1) + " " + plural;
  }
  function fmtCantidad(x) {
    var a = Math.abs(x);
    if (a < 1000) return num(Math.round(x), 0);
    if (Math.round(a / 1e3) < 1000) return num(Math.round(x / 1e3), 0) + " mil";
    if (redondear1(a / 1e6) < 1000) return escala(x, 1e6, "millón", "millones");
    if (redondear1(a / 1e9) < 1000) return escala(x, 1e9, "mil millones", "mil millones");
    return escala(x, 1e12, "billón", "billones");
  }
  function fmtMonto(x, moneda, exacto) {
    return (moneda || "$") + " " + (exacto ? num(Math.round(x), 0) : fmtCantidad(x));
  }
  function fmtPct(x, decimales) { return num(x, decimales === undefined ? 1 : decimales) + "%"; }
  function fmtDecimal(x, decimales) { return num(x, decimales === undefined ? 1 : decimales); }

  // ---------------------------------------------------------------------------
  // Cálculo
  // ---------------------------------------------------------------------------
  var ETAPAS = ["Inquilinos", "Pagan la cuota", "Juntan el anticipo", "Ingreso demostrable", "Cumplen la edad"];
  var GBA = "Partidos del GBA";

  function factorCuota(tna, plazo) {
    var r = tna / 12, n = plazo * 12;
    return r === 0 ? 1 / n : r / (1 - Math.pow(1 + r, -n));
  }
  function m2PorHogar(miembros) { return miembros <= 2 ? 45 : (miembros <= 4 ? 60 : 75); }

  /*
   * datos: dashboard_data.json · p: parámetros del producto
   * { tna, plazo_anios, ltv, tope_cuota_ingreso, gastos_compra, tope_prestamo_uva, meses_ingreso_anticipo,
   *   edad_max_fin_credito, acepta_independientes, factor_precio, m2_fijo (null = referencia) }
   * Devuelve totales por zona (CABA, GBA Norte/Oeste/Sur, Gran Córdoba) y el total.
   */
  function evaluar(datos, p) {
    var m = datos.mercado, campos = datos.hogares_campos, filas = datos.hogares;
    var iM = campos.indexOf("mercado"), iMi = campos.indexOf("miembros"), iF = campos.indexOf("formal"),
        iI = campos.indexOf("independiente"), iE = campos.indexOf("edad_jefe"), iY = campos.indexOf("ingreso_ago26"),
        iW = campos.indexOf("peso");
    var f = factorCuota(p.tna, p.plazo_anios), tope = p.tope_prestamo_uva * m.uva, fp = p.factor_precio || 1;
    var acumulado = {};
    function sumar(zona, w, etapa) {
      var z = acumulado[zona] || (acumulado[zona] = [0, 0, 0, 0, 0]);
      for (var k = 0; k <= etapa; k++) z[k] += w;
    }
    function una(zona, usdM2, miembros, formal, indep, edad, ingreso, w) {
      var m2 = (p.m2_fijo === null || p.m2_fijo === undefined) ? m2PorHogar(miembros) : p.m2_fijo;
      var precioArs = usdM2 * m2 * fp * m.tc;
      var prestamo = Math.min(p.ltv * precioArs, tope);
      var cuota = prestamo * f;
      var efectivo = (precioArs - prestamo) + p.gastos_compra * precioArs;
      var pasaCuota = ingreso > 0 && (cuota / ingreso) <= p.tope_cuota_ingreso;
      var pasaAnticipo = ingreso > 0 && (efectivo / ingreso) <= p.meses_ingreso_anticipo;
      var pasaFormal = p.acepta_independientes ? (formal || indep) : formal;
      var pasaEdad = (edad + p.plazo_anios) <= p.edad_max_fin_credito;
      var etapa = !pasaCuota ? 0 : (!pasaAnticipo ? 1 : (!pasaFormal ? 2 : (!pasaEdad ? 3 : 4)));
      sumar(zona, w, etapa);
    }
    var partidos = m.gba_partidos;
    for (var i = 0; i < filas.length; i++) {
      var h = filas[i], mercado = m.nombres[h[iM]];
      var formal = h[iF] === 1, indep = h[iI] === 1;
      if (mercado === GBA) {
        for (var j = 0; j < partidos.length; j++) {
          var pt = partidos[j];
          una("GBA " + pt.corredor, pt.usd_m2, h[iMi], formal, indep, h[iE], h[iY], h[iW] * pt.peso_gba);
        }
      } else {
        una(mercado, m.usd_m2[mercado], h[iMi], formal, indep, h[iE], h[iY], h[iW]);
      }
    }
    var total = [0, 0, 0, 0, 0];
    Object.keys(acumulado).forEach(function (z) { for (var k = 0; k < 5; k++) total[k] += acumulado[z][k]; });
    acumulado["Total"] = total;
    var gba = [0, 0, 0, 0, 0];
    ["GBA Norte", "GBA Oeste", "GBA Sur"].forEach(function (z) {
      if (acumulado[z]) for (var k = 0; k < 5; k++) gba[k] += acumulado[z][k];
    });
    acumulado["Partidos del GBA"] = gba;
    return acumulado;
  }

  function resumen(etapas) {
    return { inquilinos: etapas[0], elegibles: etapas[4], pct: etapas[0] ? 100 * etapas[4] / etapas[0] : 0, etapas: etapas };
  }

  var Motor = {
    ETAPAS: ETAPAS, GBA: GBA, factorCuota: factorCuota, m2PorHogar: m2PorHogar, evaluar: evaluar, resumen: resumen,
    fmtCantidad: fmtCantidad, fmtMonto: fmtMonto, fmtPct: fmtPct, fmtDecimal: fmtDecimal, num: num
  };
  if (typeof module !== "undefined" && module.exports) module.exports = Motor;
  else raiz.Motor = Motor;
})(this);
