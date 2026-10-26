"""Aeropuerto de Málaga-Costa del Sol (AGP) desde AENA -> data/aena_agp.json

Dos fuentes, las dos públicas y sin CORS (por eso se descargan aquí y no en
el navegador):

1. Informes mensuales de AENA (Excel), con todos los aeropuertos de la red:
   https://www.aena.es/es/estadisticas/informes-mensuales.html?anio=AAAA
   De cada mes se saca la fila de Málaga: pasajeros, operaciones y su
   variación interanual, del mes y acumulado del año. Hay desde 2015 (.xls
   hasta ~2022, .xlsx después). Diciembre acumulado = total anual.

2. Nota de prensa mensual del aeropuerto (PDF), que es lo único reciente con
   reparto por países (Eurostat avia_par_es está parado en dic-2024):
   https://www.aena.es/doc/detalleprensa/AAMMDD-agp-estadisticas-<mes>.pdf
   La fecha del nombre es la de publicación (entre el día 1 y el 28 del mes
   siguiente), así que se prueba día a día. Trae los 4-8 primeros mercados
   internacionales con sus pasajeros; unas veces del mes y otras del
   acumulado del año ("en los seis primeros meses"), y se guarda cuál es.

Uso:  python scripts/fetch_aena_agp.py [data/aena_agp.json]
Requiere: pip install openpyxl xlrd pypdf
"""
import datetime as dt
import html
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

import openpyxl
import pypdf
import xlrd

OUT = sys.argv[1] if len(sys.argv) > 1 else "data/aena_agp.json"
BASE = "https://www.aena.es"
UA = {"User-Agent": "Mozilla/5.0 (observatorio-turistico-marbella)"}
PRIMER_ANIO = 2015
NOTAS_DESDE = "2024-01"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

sys.stdout.reconfigure(encoding="utf-8")


def get(url, intentos=3):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, ""
            if i == intentos - 1:
                raise
        except Exception:
            if i == intentos - 1:
                raise
        time.sleep(2 * (i + 1))


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def mes_siguiente(ym):
    y, m = map(int, ym.split("-"))
    return f"{y + (m == 12)}-{1 if m == 12 else m + 1:02d}"


# ── 1. Excel mensuales ────────────────────────────────────────────────────
def enlaces_anio(anio):
    """[(blob_id, tipo)] de la página del año; el tipo (PDF/XLS) va en el texto
    que sigue a cada enlace."""
    b, _ = get(f"{BASE}/es/estadisticas/informes-mensuales.html?anio={anio}")
    s = b.decode("utf-8", "replace")
    trozos = re.split(r'<a[^>]+href="([^"]*blobwhere=\d+[^"]*)"', s)
    out = []
    for i in range(1, len(trozos), 2):
        blob = re.search(r"blobwhere=(\d+)", html.unescape(trozos[i])).group(1)
        texto = re.sub(r"<[^>]+>", " ", trozos[i + 1])
        if re.search(r"\bXLSX?\b", texto):
            out.append(blob)
    return out


def hojas(binario):
    """Lista de (nombre, filas) para .xls o .xlsx."""
    if binario[:2] == b"PK":
        wb = openpyxl.load_workbook(io.BytesIO(binario), data_only=True, read_only=True)
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb]
    if binario[:4] == b"\xd0\xcf\x11\xe0":
        wb = xlrd.open_workbook(file_contents=binario)
        return [(ws.name, [ws.row_values(i) for i in range(ws.nrows)]) for ws in wb.sheets()]
    return []


def fila_malaga(filas):
    """Málaga sale una vez en cada bloque (pasajeros, operaciones, mercancía),
    cada uno ordenado por su propio ranking: el orden por columna dice cuál es cuál."""
    hits = []
    for r in filas:
        for j, c in enumerate(r):
            if isinstance(c, str) and "MALAGA" in sin_tildes(c):
                # Valor y % van detrás del nombre; en los .xls antiguos hay
                # columnas vacías por medio.
                sig = [x for x in r[j + 1:j + 6] if x not in (None, "")]
                nums = [x for x in sig[:2] if isinstance(x, (int, float))]
                if len(nums) == 2:
                    hits.append((j, int(round(nums[0])), float(nums[1])))
    hits.sort()
    if len(hits) < 2:
        return None
    return {"pax": hits[0][1], "pax_var": round(hits[0][2], 4),
            "ops": hits[1][1], "ops_var": round(hits[1][2], 4)}


def periodo(filas):
    cab = " ".join(str(c) for r in filas[:8] for c in r if c not in (None, ""))
    m = re.search(r"(" + "|".join(MESES) + r")\s+(?:de\s+)?(\d{4})", sin_tildes(cab).lower())
    estado = "definitivo" if "DEFINITIVO" in sin_tildes(cab) else "provisional"
    return (f"{m.group(2)}-{MESES.index(m.group(1)) + 1:02d}" if m else None), estado


def leer_excel(binario):
    mes, acum, ym, estado = None, None, None, None
    for nombre, filas in hojas(binario):
        n = sin_tildes(nombre)
        if "MOZART" in n:
            continue
        ym_h, est_h = periodo(filas)
        dato = fila_malaga(filas)
        if not dato or not ym_h:
            continue
        es_acum = "ACUM" in n or "ENERO-" in n or "ACUMULADO" in sin_tildes(" ".join(str(c) for r in filas[:8] for c in r if c))
        if es_acum:
            acum = dato
        else:
            mes = dato
        ym, estado = ym_h, est_h
    if not (mes and ym):
        return None, None
    rec = dict(mes, estado=estado)
    if acum:
        rec.update(acum_pax=acum["pax"], acum_pax_var=acum["pax_var"],
                   acum_ops=acum["ops"], acum_ops_var=acum["ops_var"])
    return ym, rec


# ── 2. Notas de prensa ────────────────────────────────────────────────────
PAISES = {
    "BRITANICO": "Reino Unido", "REINO UNIDO": "Reino Unido", "ALEMAN": "Alemania", "ALEMANIA": "Alemania",
    "HOLANDES": "Países Bajos", "HOLANDA": "Países Bajos", "PAISES BAJOS": "Países Bajos", "NEERLANDES": "Países Bajos",
    "ITALIANO": "Italia", "ITALIA": "Italia", "FRANCES": "Francia", "FRANCIA": "Francia",
    "IRLANDES": "Irlanda", "IRLANDA": "Irlanda", "BELGA": "Bélgica", "BELGICA": "Bélgica",
    "POLACO": "Polonia", "POLONIA": "Polonia", "SUIZO": "Suiza", "SUIZA": "Suiza",
    "DANES": "Dinamarca", "DINAMARCA": "Dinamarca", "SUECO": "Suecia", "SUECIA": "Suecia",
    "NORUEGO": "Noruega", "NORUEGA": "Noruega", "PORTUGUES": "Portugal", "PORTUGAL": "Portugal",
    "MARROQUI": "Marruecos", "MARRUECOS": "Marruecos", "ESTADOUNIDENSE": "Estados Unidos",
    "ESTADOS UNIDOS": "Estados Unidos", "AUSTRIACO": "Austria", "AUSTRIA": "Austria",
    "FINLANDES": "Finlandia", "FINLANDIA": "Finlandia", "CHECO": "República Checa",
    "REPUBLICA CHECA": "República Checa", "HUNGARO": "Hungría", "HUNGRIA": "Hungría",
    "LUXEMBURGUES": "Luxemburgo", "LUXEMBURGO": "Luxemburgo", "ISRAELI": "Israel", "ISRAEL": "Israel",
    "CANADIENSE": "Canadá", "CANADA": "Canadá", "TURCO": "Turquía", "TURQUIA": "Turquía",
}
ORDINALES = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
             "nueve": 9, "diez": 10, "once": 11, "doce": 12}


def texto_pdf(binario):
    t = " ".join(" ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(binario)).pages).split())
    return re.sub(r"(\d)\. (\d{3})\b", r"\1.\2", t)  # erratas como «165. 082»


def mercados(texto):
    """Primeros mercados internacionales del párrafo «los mercados con mayor demanda…»."""
    i = texto.find("mercados con mayor demanda")
    if i < 0:
        i = texto.find("principales mercados")
    if i < 0:
        return None
    j = texto.find("fueron", i)
    if j < 0:
        return None
    intro = texto[i:j]
    fin = texto.find("). ", j)
    tramo = texto[j + 6:fin + 1 if fin > 0 else j + 700]
    paises = []
    for nombre, cifra in re.findall(r"([A-Za-zÁÉÍÓÚáéíóúÑñü][A-Za-zÁÉÍÓÚáéíóúÑñü ]*?)\s*\((\d{1,3}(?:\.\d{3})+|\d+)", tramo):
        palabras = sin_tildes(nombre).split()
        canon = None
        for k in (3, 2, 1):  # «la República Checa», «con algo más de distancia, el alemán»
            if len(palabras) >= k and " ".join(palabras[-k:]) in PAISES:
                canon = PAISES[" ".join(palabras[-k:])]
                break
        if canon:
            paises.append({"pais": canon, "pax": int(cifra.replace(".", ""))})
    if not paises:
        return None
    m = re.search(r"(\w+) primeros meses", intro)
    periodos = {"trimestre": 3, "cuatrimestre": 4, "semestre": 6}
    p = re.search(r"primer (trimestre|cuatrimestre|semestre)", intro)
    if m or p or re.search(r"lo que va de|acumulad|de enero a", intro):
        n = ORDINALES.get(m.group(1).lower()) if m else periodos[p.group(1)] if p else None
        return {"tipo": "acumulado", "meses": n, "paises": paises}
    return {"tipo": "mes", "paises": paises}


def buscar_nota(ym):
    y, m = map(int, ym.split("-"))
    pub = mes_siguiente(ym)
    py, pm = map(int, pub.split("-"))
    for d in range(1, 29):
        url = f"{BASE}/doc/detalleprensa/{py % 100:02d}{pm:02d}{d:02d}-agp-estadisticas-{MESES[m - 1]}.pdf"
        try:
            b, ct = get(url)
        except Exception as e:
            print(f"  aviso {url}: {e}")
            continue
        if b and b[:4] == b"%PDF":
            return url, b
    return None, None


# ── Principal ─────────────────────────────────────────────────────────────
def main():
    try:
        datos = json.load(open(OUT, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        datos = {}
    meses = datos.get("meses", {})
    notas = datos.get("notas", {})
    hoy = dt.date.today()

    # Excel: años incompletos + siempre los dos últimos (los provisionales
    # pasan a definitivos y AENA sustituye el fichero).
    for anio in range(PRIMER_ANIO, hoy.year + 1):
        completos = sum(f"{anio}-{m:02d}" in meses for m in range(1, 13))
        if completos == 12 and anio < hoy.year - 1:
            continue
        try:
            blobs = enlaces_anio(anio)
        except Exception as e:
            print(f"{anio}: no se pudo leer la página ({e})")
            continue
        conocidos = {v.get("blob") for v in meses.values()}
        for blob in blobs:
            if blob in conocidos:
                continue
            b, _ = get(f"{BASE}/sites/Satellite?blobcol=urldata&blobkey=id&blobtable=MungoBlobs&blobwhere={blob}&ssbinary=true")
            if not b:
                continue
            try:
                ym, rec = leer_excel(b)
            except Exception as e:
                print(f"  blob {blob}: {e}")
                continue
            if ym:
                rec["blob"] = blob
                meses[ym] = rec
                print(f"  {ym}: {rec['pax']:>10,} pax  {rec['ops']:>7,} ops  ({rec['estado']})")

    # Notas de prensa: meses con Excel y sin nota buscada con éxito. Las no
    # encontradas se reintentan solo durante los tres meses siguientes.
    limite = (hoy.replace(day=1) - dt.timedelta(days=90)).strftime("%Y-%m")
    for ym in sorted(meses):
        if ym < NOTAS_DESDE or (ym in notas and (notas[ym].get("url") or ym < limite)):
            continue
        url, b = buscar_nota(ym)
        if not url:
            notas[ym] = {"url": None, "buscado": hoy.isoformat()}
            print(f"  nota {ym}: no encontrada")
            continue
        try:
            mk = mercados(texto_pdf(b))
        except Exception as e:
            print(f"  nota {ym}: error al leer el PDF ({e})")
            mk = None
        # Red de seguridad: si los mercados suman más que todo el mes, son acumulados
        # aunque la redacción no lo diga de una forma que se haya previsto.
        if mk and mk["tipo"] == "mes" and sum(p["pax"] for p in mk["paises"]) > meses[ym]["pax"]:
            mk.update(tipo="acumulado", meses=int(ym[5:]))
        notas[ym] = {"url": url, **(mk or {"tipo": None, "paises": []})}
        print(f"  nota {ym}: {url.rsplit('/', 1)[-1]} · {mk['tipo'] if mk else 'sin mercados'} · "
              f"{', '.join(p['pais'] for p in (mk or {}).get('paises', []))}")

    # Totales anuales: diciembre acumulado; el año en curso, acumulado parcial.
    anual = {}
    for ym, r in sorted(meses.items()):
        if "acum_pax" not in r:
            continue
        y, m = ym.split("-")
        anual[y] = {"pax": r["acum_pax"], "pax_var": r["acum_pax_var"], "ops": r["acum_ops"],
                    "ops_var": r["acum_ops_var"], "hasta": ym, "completo": m == "12"}

    datos = {
        "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fuente": "AENA · Informes mensuales de tráfico y notas de prensa del Aeropuerto de Málaga-Costa del Sol",
        "ultimo_mes": max(meses) if meses else None,
        "meses": dict(sorted(meses.items())),
        "anual": anual,
        "notas": dict(sorted(notas.items())),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    print(f"OK · {len(meses)} meses · último {datos['ultimo_mes']} · "
          f"{sum(1 for n in notas.values() if n.get('paises'))} notas con mercados")


if __name__ == "__main__":
    main()
