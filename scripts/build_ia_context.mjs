// Paquete de datos para los informes con Claude (informe técnico mensual y
// nota de prensa). Genera data/ia/contexto-AAAA-MM.md para los últimos meses
// publicados por el INE y data/ia/meses.json con la lista.
//
// Se construye aquí, en GitHub Actions, y no en el navegador: el Worker que
// llama a Claude solo acepta estos ficheros del repositorio, así nadie puede
// mandarle cifras inventadas para que salgan en un informe público.
//
// Uso: node scripts/build_ia_context.mjs [carpeta_salida]   (Node 20, sin dependencias)

import { mkdir, writeFile, readFile } from "node:fs/promises";

const OUT = process.argv[2] || "data/ia";
const N_MESES = 12;

// Mismas series que el observatorio (ALL_SERIES en el HTML).
const SERIES = {
    eoh_pernoc_esp: "EOT2761", eoh_pernoc_ext: "EOT2762", eoh_viaj_esp: "EOT2759", eoh_viaj_ext: "EOT2760",
    eoh_ocup_plz: "EOT3152", eoh_ocup_hab: "EOT3224", eoh_ocup_finde: "EOT11622", eoh_estancia: "EOT2936",
    eoh_establec: "EOT3008", eoh_plazas: "EOT3080", eoh_habitac: "EOT24609", eoh_personal: "EOT3296",
    eoap_pernoc_esp: "EOT9425", eoap_pernoc_ext: "EOT9426", eoap_viaj_esp: "EOT9423", eoap_viaj_ext: "EOT9424",
    eoap_ocup_plz: "EOT9850", eoap_ocup_apt: "EOT9851", eoap_ocup_finde: "EOT15385", eoap_estancia: "EOT9705",
    eoap_apartam: "EOT9849", eoap_plazas: "EOT9848", eoap_personal: "EOT9852",
    irsh_adr: "EOT43542", irsh_revpar: "EOT43946",
    oat_aloj_tot: "OAT1808", oat_pernoc_tot: "OAT2042", oat_pernoc_esp: "OAT2003", oat_pernoc_ext: "OAT1964",
    oat_estancia_tot: "OAT1925",
};

// tipo: "flujo" (sumable: % y acumulado del año) · "tasa" (variación en p.p.) · "nivel" (solo %)
const BLOQUES = [
    { titulo: "Hoteles · INE, Encuesta de Ocupación Hotelera (EOH)", filas: [
        ["Pernoctaciones totales",                    ["eoh_pernoc_esp", "eoh_pernoc_ext"], "flujo"],
        ["Pernoctaciones · residentes en España",     ["eoh_pernoc_esp"], "flujo"],
        ["Pernoctaciones · residentes en el extranjero", ["eoh_pernoc_ext"], "flujo"],
        ["Viajeros totales",                          ["eoh_viaj_esp", "eoh_viaj_ext"], "flujo"],
        ["Viajeros · residentes en España",           ["eoh_viaj_esp"], "flujo"],
        ["Viajeros · residentes en el extranjero",    ["eoh_viaj_ext"], "flujo"],
        ["Ocupación por plazas (%)",                  ["eoh_ocup_plz"], "tasa"],
        ["Ocupación por habitaciones (%)",            ["eoh_ocup_hab"], "tasa"],
        ["Ocupación por plazas en fin de semana (%)", ["eoh_ocup_finde"], "tasa"],
        ["Estancia media (días)",                     ["eoh_estancia"], "nivel"],
        ["Establecimientos abiertos",                 ["eoh_establec"], "nivel"],
        ["Plazas estimadas",                          ["eoh_plazas"], "nivel"],
        ["Habitaciones estimadas",                    ["eoh_habitac"], "nivel"],
        ["Personal empleado",                         ["eoh_personal"], "nivel"],
    ]},
    { titulo: "Rentabilidad hotelera · INE, Índice de Rentabilidad del Sector Hotelero (IRSH)", filas: [
        ["ADR · tarifa media diaria (€)",             ["irsh_adr"], "nivel"],
        ["RevPAR · ingreso por habitación disponible (€)", ["irsh_revpar"], "nivel"],
    ]},
    { titulo: "Apartamentos turísticos · INE, Encuesta de Ocupación en Apartamentos (EOAP)", filas: [
        ["Pernoctaciones totales",                    ["eoap_pernoc_esp", "eoap_pernoc_ext"], "flujo"],
        ["Pernoctaciones · residentes en España",     ["eoap_pernoc_esp"], "flujo"],
        ["Pernoctaciones · residentes en el extranjero", ["eoap_pernoc_ext"], "flujo"],
        ["Viajeros totales",                          ["eoap_viaj_esp", "eoap_viaj_ext"], "flujo"],
        ["Ocupación por plazas (%)",                  ["eoap_ocup_plz"], "tasa"],
        ["Ocupación por apartamentos (%)",            ["eoap_ocup_apt"], "tasa"],
        ["Ocupación por apartamentos en fin de semana (%)", ["eoap_ocup_finde"], "tasa"],
        ["Estancia media (días)",                     ["eoap_estancia"], "nivel"],
        ["Apartamentos estimados",                    ["eoap_apartam"], "nivel"],
        ["Plazas estimadas",                          ["eoap_plazas"], "nivel"],
        ["Personal empleado",                         ["eoap_personal"], "nivel"],
    ]},
    { titulo: "Plataformas digitales · INE, Ocupación en Alojamientos Turísticos (OAT, experimental: Airbnb, Booking, Vrbo…)", filas: [
        ["Alojamientos ocupados · total",             ["oat_aloj_tot"], "flujo"],
        ["Pernoctaciones · total",                    ["oat_pernoc_tot"], "flujo"],
        ["Pernoctaciones · residentes en España",     ["oat_pernoc_esp"], "flujo"],
        ["Pernoctaciones · residentes en el extranjero", ["oat_pernoc_ext"], "flujo"],
        ["Estancia media · total (días)",             ["oat_estancia_tot"], "nivel"],
    ]},
];

const CDS_AGREGADOS = new Set([
    "Total", "Extranjero", "España", "Resto de Europa", "Resto de la UE",
    "Resto del mundo", "Resto de América", "Resto de Asia",
    "Resto América Central y Sur", "Unión Europea (sin España)",
    "UE27_2020 sin España", "América (sin EEUU)", "Otros países europeos",
    "Países africanos",
]);

const MESES_LARGOS = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
const fmt  = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2, useGrouping: "always" });
const fmt0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0, useGrouping: "always" });
const pad = n => String(n).padStart(2, "0");
const shift = (ym, n) => { const [y, m] = ym.split("-").map(Number); const t = y * 12 + (m - 1) + n; return `${Math.floor(t / 12)}-${pad(t % 12 + 1)}`; };
const label = ym => { const [y, m] = ym.split("-").map(Number); return `${MESES_LARGOS[m - 1]} ${y}`; };
const pct = (a, b) => (a == null || b == null || b === 0) ? null : (a - b) / b * 100;
const signed = (d, unit) => d == null ? "n/d" : `${d >= 0 ? "+" : "−"}${fmt.format(Math.abs(d))}${unit}`;

async function getJSON(url, tries = 3) {
    for (let i = 1; ; i++) {
        try {
            const r = await fetch(url);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return await r.json();
        } catch (e) {
            if (i >= tries) throw new Error(`${url}: ${e.message}`);
            await new Promise(res => setTimeout(res, 3000 * i));
        }
    }
}

// Mes por Anyo + Periodo, no por Fecha: Fecha es la medianoche española en
// milisegundos y en un runner UTC cae en el último día del mes anterior.
async function loadINE() {
    const out = {};
    for (const [k, cod] of Object.entries(SERIES)) {
        const j = await getJSON(`https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/${cod}?nult=${N_MESES + 26}&det=2`);
        out[k] = new Map((j.Data || []).filter(d => d.Valor != null).map(d => {
            const tipo = typeof d.TipoDato === "object" && d.TipoDato ? d.TipoDato.Id : d.FK_TipoDato;
            return [`${d.Anyo}-${pad(d.Periodo?.Valor ?? d.FK_Periodo)}`, { valor: d.Valor, provisional: tipo === 2 || tipo === 3 }];
        }));
    }
    return out;
}

function fila(ine, nombre, keys, tipo, ref) {
    const val = ym => {
        let v = 0, prov = false;
        for (const k of keys) {
            const p = ine[k]?.get(ym);
            if (!p) return null;
            v += p.valor; prov = prov || p.provisional;
        }
        return { v, prov };
    };
    // Si la serie aún no ha publicado el mes de referencia, se usa su último mes.
    let mes = ref;
    for (let i = 0; i < 6 && !val(mes); i++) mes = shift(mes, -1);
    const act = val(mes);
    if (!act) return `| ${nombre} | sin datos | | | | | | | | |`;
    const ant = val(shift(mes, -12)), prev = val(shift(mes, -1));
    const unit = tipo === "tasa" ? " p.p." : " %";
    const dif = (a, b) => !a || !b ? null : (tipo === "tasa" ? a.v - b.v : pct(a.v, b.v));
    let acum = ["", "", ""];
    if (tipo === "flujo") {
        const [y, m] = mes.split("-").map(Number);
        let a = 0, b = 0, ok = true;
        for (let i = 1; i <= m; i++) {
            const pa = val(`${y}-${pad(i)}`), pb = val(`${y - 1}-${pad(i)}`);
            if (!pa || !pb) { ok = false; break; }
            a += pa.v; b += pb.v;
        }
        if (ok) acum = [fmt0.format(a), fmt0.format(b), signed(pct(a, b), " %")];
    }
    const f = x => x ? fmt.format(x.v) : "n/d";
    const mesTxt = label(mes) + (mes !== ref ? " (último publicado)" : "") + (act.prov ? " · provisional" : "");
    return `| ${nombre} | ${mesTxt} | ${f(act)} | ${f(ant)} | **${signed(dif(act, ant), unit)}** | ${f(prev)} | ${signed(dif(act, prev), unit)} | ${acum.join(" | ")} |`;
}

function tablasINE(ine, ref) {
    const head = "| Indicador | Mes | Valor | Mismo mes año anterior | Var. interanual | Mes anterior | Var. mensual | Acumulado del año | Acumulado año anterior | Var. acumulada |\n|---|---|---|---|---|---|---|---|---|---|";
    return BLOQUES.map(b => `### ${b.titulo}\n${head}\n${b.filas.map(([l, k, t]) => fila(ine, l, k, t, ref)).join("\n")}`).join("\n\n");
}

function tablaPaises(cds, ref) {
    const mes = (cds?.meses || []).filter(m => m <= ref).at(-1);
    if (!mes) return "### Mercados de origen\nSin datos para el periodo.";
    const i = cds.meses.indexOf(mes), j = cds.meses.indexOf(shift(mes, -12));
    const out = [`### Mercados de origen por país de residencia · Turismo Costa del Sol, Big Data (microdato EOH/EOAP del INE) · ${label(mes)}${mes !== ref ? " (último mes disponible en esta fuente)" : ""}`];
    for (const tipo of ["Hoteles", "Apartamentos"]) {
        const V = cds.datos?.[tipo]?.Viajeros || {}, P = cds.datos?.[tipo]?.Pernoctaciones || {};
        const totP = P.Total?.[i];
        const mercados = Object.keys(P).filter(k => !CDS_AGREGADOS.has(k) || k === "España" || k === "Extranjero")
            .filter(k => P[k]?.[i] != null)
            .sort((a, b) => (P[b][i] || 0) - (P[a][i] || 0)).slice(0, 14);
        out.push(`\n**${tipo}**\n| Mercado | Viajeros | Var. interanual viajeros | Pernoctaciones | Var. interanual pernoctaciones | Cuota de pernoctaciones |\n|---|---|---|---|---|---|`);
        for (const k of mercados) {
            const v = V[k]?.[i], va = j >= 0 ? V[k]?.[j] : null, p = P[k][i], pa = j >= 0 ? P[k]?.[j] : null;
            out.push(`| ${k} | ${v == null ? "n/d" : fmt0.format(v)} | ${signed(pct(v, va), " %")} | ${fmt0.format(p)} | ${signed(pct(p, pa), " %")} | ${totP ? fmt.format(p / totP * 100) + " %" : "n/d"} |`);
        }
    }
    return out.join("\n");
}

// Aeropuerto: data/aena_agp.json (Action actualizar-aena.yml, informes y notas de prensa de AENA).
function tablaAeropuerto(aena, ref) {
    const t = "### Conectividad aérea · AENA, aeropuerto de Málaga-Costa del Sol";
    if (!aena?.meses) return `${t}\nNo se pudo cargar data/aena_agp.json.`;
    const r = aena.meses[ref];
    if (!r) return `${t}\nAENA aún no ha publicado ${label(ref)}. No se incluye en el análisis del mes.`;
    const ra = aena.meses[shift(ref, -12)], m = +ref.slice(5);
    const out = [
        `${t} · ${label(ref)} (datos ${r.estado === "definitivo" ? "definitivos" : "provisionales"}; llegadas y salidas)`,
        `Pasajeros del mes: ${fmt0.format(r.pax)}; mismo mes del año anterior: ${ra ? fmt0.format(ra.pax) : "n/d"} (${signed(r.pax_var * 100, " %")}).`,
        `Operaciones (aterrizajes y despegues) del mes: ${fmt0.format(r.ops)} (${signed(r.ops_var * 100, " %")} interanual).`,
        `Acumulado enero–${MESES_LARGOS[m - 1]}: ${fmt0.format(r.acum_pax)} pasajeros (${signed(r.acum_pax_var * 100, " %")}) y ${fmt0.format(r.acum_ops)} operaciones (${signed(r.acum_ops_var * 100, " %")}).`,
    ];
    const n = aena.notas?.[ref];
    if (n?.paises?.length) {
        const na = aena.notas[shift(ref, -12)];
        const comp = na?.tipo === n.tipo && na.paises?.length;
        const periodo = n.tipo === "acumulado" ? `acumulado enero–${MESES_LARGOS[m - 1]}` : "del mes";
        out.push(`Primeros mercados internacionales citados por AENA en su nota de prensa (pasajeros en vuelos con cada país, ${periodo}; AENA solo cita estos ${n.paises.length}):`,
            "| País | Pasajeros | Mismo periodo año anterior | Var. interanual |\n|---|---|---|---|",
            ...n.paises.map(p => {
                const va = comp ? na.paises.find(q => q.pais === p.pais)?.pax : null;
                return `| ${p.pais} | ${fmt0.format(p.pax)} | ${va ? fmt0.format(va) : "n/d"} | ${signed(pct(p.pax, va), " %")} |`;
            }));
    } else {
        out.push("AENA no ha publicado reparto por países para este mes.");
    }
    return out.join("\n");
}

function tablaRTA(snap, ref) {
    if (!snap) return "### Viviendas con fines turísticos (RTA)\nNo se pudo cargar el volcado.";
    const recs = snap.records || [], porMes = {};
    let plazas = 0;
    recs.forEach(x => {
        const ym = (x.registration_date || x.activity_start_date || "").slice(0, 7);
        if (/^\d{4}-\d{2}$/.test(ym)) porMes[ym] = (porMes[ym] || 0) + 1;
        plazas += parseInt(x.tot_gen_places, 10) || 0;
    });
    const [y, m] = ref.split("-").map(Number);
    let a = 0, b = 0;
    for (let k = 1; k <= m; k++) { a += porMes[`${y}-${pad(k)}`] || 0; b += porMes[`${y - 1}-${pad(k)}`] || 0; }
    const v = porMes[ref] || 0, va = porMes[shift(ref, -12)] || 0;
    return [
        "### Viviendas con fines turísticos · Registro de Turismo de Andalucía (RTA, volcado OpenRTA)",
        `Altas inscritas en ${label(ref)}: ${fmt0.format(v)}; mismo mes del año anterior: ${fmt0.format(va)} (${signed(pct(v, va), " %")}).`,
        `Altas acumuladas enero–${MESES_LARGOS[m - 1]} ${y}: ${fmt0.format(a)} frente a ${fmt0.format(b)} en ${y - 1} (${signed(pct(a, b), " %")}).`,
        `Parque inscrito a fecha del volcado (${snap.fetched_at || "s/f"}): ${fmt0.format(recs.length)} VUT y ${fmt0.format(plazas)} plazas. Es la foto actual, no la del mes de referencia; el registro no refleja bajas con fecha.`,
    ].join("\n");
}

const readLocal = async path => { try { return JSON.parse(await readFile(path, "utf8")); } catch { return null; } };

const ine = await loadINE();
const meses = [...ine.eoh_pernoc_esp.keys()].sort().reverse()
    .filter(m => ine.eoh_pernoc_esp.has(shift(m, -12))).slice(0, N_MESES);
if (!meses.length) throw new Error("El INE no ha devuelto la EOH: no se genera nada.");

const cds  = await readLocal("data/paises_marbella.json");
const snap = await readLocal("data/rta_vut_marbella.json");
const aero = await readLocal("data/aena_agp.json");

await mkdir(OUT, { recursive: true });
for (const ref of meses) {
    const md = [
        `MES DE REFERENCIA: ${label(ref)}. Comparación principal: ${label(shift(ref, -12))}.`,
        "Fuente: Observatorio Turístico de Marbella (punto turístico de Marbella del INE).",
        tablasINE(ine, ref),
        tablaPaises(cds, ref),
        tablaAeropuerto(aero, ref),
        tablaRTA(snap, ref),
    ].join("\n\n") + "\n";
    await writeFile(`${OUT}/contexto-${ref}.md`, md);
}
await writeFile(`${OUT}/meses.json`, JSON.stringify({ meses }, null, 1) + "\n");
console.log(`Contextos generados: ${meses.join(", ")}`);
