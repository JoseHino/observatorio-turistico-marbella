// Genera data/rta_vut_marbella.json a partir del volcado completo de OpenRTA.
// Uso: node build_rta_snapshot.mjs <dataset-openrta.json> <salida.json>
// El volcado es un array JSON de ~174k objetos planos (~323 MB); se parsea en
// streaming (control de profundidad + estado de string) para no cargarlo entero.
import { createReadStream, writeFileSync } from "node:fs";

const [,, INPUT, OUTPUT] = process.argv;
if (!INPUT || !OUTPUT) { console.error("uso: node build_rta_snapshot.mjs <in> <out>"); process.exit(1); }

// Normaliza "19970214" | "1997-02-14" → "1997-02-14"
const normDate = d => {
    if (!d) return null;
    const s = String(d).replaceAll("-", "");
    if (!/^\d{8}$/.test(s)) return null;
    return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
};

const records = [];
let total = 0;

function handleRecord(obj) {
    total++;
    if (obj.municipalities !== "MARBELLA") return;
    if (obj.objects_type_id !== "Vivienda de uso turístico") return;
    records.push({
        id: obj.id,
        registration_date: normDate(obj.registration_date),
        activity_start_date: normDate(obj.activity_start_date),
        tot_gen_places: obj.tot_gen_places ?? null,
        tot_gen_ua: obj.tot_gen_ua ?? null,
        locality: obj.locality ?? null,
        coord_x: obj.coord_x ?? null,
        coord_y: obj.coord_y ?? null,
        // Ficha individual (mapa-vut): campos publicados como open data en el RTA
        registration_code: obj.registration_code ?? null,
        name: obj.name ?? null,
        establishment_address: obj.establishment_address ?? null,
        postal_code: obj.postal_code ?? null,
        catastral_ref: obj.catastral_ref ?? null,
        group: obj.group ?? null, // "Completa" | "Por habitaciones"
    });
}

const stream = createReadStream(INPUT, { encoding: "utf8", highWaterMark: 1 << 20 });
let depth = 0, inStr = false, esc = false, buf = "";

stream.on("data", chunk => {
    for (let i = 0; i < chunk.length; i++) {
        const c = chunk[i];
        if (depth >= 1) buf += c;
        if (inStr) {
            if (esc) esc = false;
            else if (c === "\\") esc = true;
            else if (c === '"') inStr = false;
            continue;
        }
        if (c === '"') { inStr = true; continue; }
        if (c === "{") { if (depth === 0) buf = "{"; depth++; }
        else if (c === "}") {
            depth--;
            if (depth === 0) { handleRecord(JSON.parse(buf)); buf = ""; }
        }
    }
});

stream.on("end", () => {
    // stock vivo primero no aplica: guardamos todo el histórico ordenado por fecha de alta
    records.sort((a, b) => String(a.registration_date).localeCompare(String(b.registration_date)));
    const out = {
        fetched_at: new Date().toISOString().slice(0, 10),
        source: "https://datos.juntadeandalucia.es/api/v0/openrta/all (volcado oficial diario)",
        filter: "municipalities=MARBELLA · objects_type_id='Vivienda de uso turístico'",
        total: records.length,
        records,
    };
    writeFileSync(OUTPUT, JSON.stringify(out));
    console.log(`dataset: ${total} registros totales · Marbella VUT: ${records.length} · → ${OUTPUT}`);
});
stream.on("error", e => { console.error(e); process.exit(1); });
