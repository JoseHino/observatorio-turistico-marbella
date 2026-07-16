#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recolector: viajeros y pernoctaciones por pais de residencia en Marbella.

Fuente: visor Big Data de Turismo Costa del Sol (Power BI embebido sobre el
microdato de la Encuesta de Ocupacion Hotelera del INE, con el desglose por
pais x municipio que el INE no publica en su web).

    https://www.costadelsolmalaga.org/bigdata/com1_tc-357990/viajeros-pernoctaciones?mun=29069

No hay API publica documentada. El visor genera un token de embed efimero en
cada carga de pagina; con el se consulta el endpoint semantico de Power BI.
El endpoint solo admite peticiones con origen app.powerbi.com, por lo que NO
puede llamarse desde el navegador (CORS): de ahi que este script vuelque los
datos a un JSON que el HTML embebe.

Salida: data/paises_marbella.json
"""

import json
import re
import sys
import urllib.request
import urllib.error
import uuid
from pathlib import Path

VISOR = "https://visor.bigdata.costadelsolmalaga.org/informe?id=viajeros-pernoctaciones&mun=29069"
CLUSTER = "https://wabi-europe-north-b-redirect.analysis.windows.net"
DATASET = "52f1245b-8ea2-447f-9347-fa42240bbd8f"
REPORT = "3b8e1dc6-c922-442d-b058-7346a71844d1"
MODEL_ID = 12913946
ENTITY = "Viajeros y Pernoctaciones"

TERRITORIO = "Marbella"
TIPOS = ["Hoteles", "Apartamentos"]
INDICADORES = ["Viajeros", "Pernoctaciones"]

# El desglose por pais de la fuente NO es fiable antes de 2019: 2016-2017 estan
# incompletos (~60% del extranjero sin asignar a mercado) y TODO 2018 esta
# corrupto (Reino Unido colapsa a ~200/mes y Aleman/Japon aparecen inflados,
# con la suma de mercados superando al total de extranjeros). Desde 2019-01 la
# suma de mercados reconcilia al 100% con el agregado "Extranjero". Se recorta
# ahi. El split Espana/Extranjero si es valido desde 2005, pero eso ya lo cubre
# la grafica EOH+OAT del observatorio; aqui solo interesa el desglose por pais.
MIN_MES = "2019-01"

# Agregados y mercado nacional: no son paises emisores extranjeros. Se conservan
# en los datos (para totales y cuota) pero se excluyen del ranking de emisores.
AGREGADOS = {
    "España", "Espana",
    "Total", "Extranjero", "Resto de Europa", "Resto de la UE", "Resto del mundo",
    "Resto de America", "Resto de Asia", "Resto America Central y Sur",
    "Union Europea (sin Espana)", "UE27_2020 sin Espana", "America (sin EEUU)",
    "Otros paises europeos", "Paises africanos", "Resto de América",
    "Resto América Central y Sur", "Unión Europea (sin España)",
    "UE27_2020 sin España", "América (sin EEUU)", "Otros países europeos",
    "Países africanos",
}


def get_token():
    """El token de embed caduca; se regenera en cada carga del visor."""
    req = urllib.request.Request(VISOR, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    m = re.search(r"accessToken:\s*'([^']+)'", html)
    if not m:
        raise RuntimeError("No se encontro accessToken en el visor: ¿cambio la pagina?")
    return m.group(1)


def _col(prop):
    return {"Column": {"Expression": {"SourceRef": {"Source": "v"}}, "Property": prop}}


def eq(prop, value):
    lit = f"'{value}'" if isinstance(value, str) else f"{value}L"
    return {"Condition": {"In": {"Expressions": [_col(prop)],
                                 "Values": [[{"Literal": {"Value": lit}}]]}}}


def query(token, props, aggs=(), where=None, top=30000):
    select = []
    for i, p in enumerate(props):
        if p in aggs:
            select.append({"Aggregation": {"Expression": _col(p), "Function": 0}, "Name": f"c{i}"})
        else:
            select.append(dict(_col(p), Name=f"c{i}"))
    q = {"Version": 2, "From": [{"Name": "v", "Entity": ENTITY, "Type": 0}], "Select": select}
    if where:
        q["Where"] = where
    body = {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": q,
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                    "DataReduction": {"DataVolume": 4, "Primary": {"Window": {"Count": top}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": DATASET, "Sources": [{"ReportId": REPORT}]},
        }],
        "cancelQueries": [],
        "modelId": MODEL_ID,
    }
    headers = {
        "Authorization": f"EmbedToken {token}",
        "Content-Type": "application/json;charset=UTF-8",
        # El endpoint rechaza cualquier origen que no sea el del visor de Power BI.
        "Origin": "https://app.powerbi.com",
        "Referer": "https://app.powerbi.com/",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
    }
    req = urllib.request.Request(f"{CLUSTER}/explore/querydata?synchronous=true",
                                 data=json.dumps(body).encode(), headers=headers)
    resp = json.load(urllib.request.urlopen(req, timeout=180))
    return resp["results"][0]["result"]["data"]["dsr"]


def parse(dsr):
    """Decodifica DM0: descriptor S (G=grupo/M=medida, DN=diccionario),
    ValueDicts, bitmask R (repite valor de la fila anterior) y Ø (nulo)."""
    ds = dsr["DS"][0]
    dicts = ds.get("ValueDicts", {})
    rows_in = ds["PH"][0]["DM0"]
    if not rows_in:
        return []
    meta = rows_in[0]["S"]
    n = len(meta)
    out, prev = [], [None] * n
    for r in rows_in:
        row = [None] * n
        ci = 0
        rep, nul = r.get("R", 0), r.get("Ø", 0)
        for i in range(n):
            if nul >> i & 1:
                row[i] = None
            elif rep >> i & 1:
                row[i] = prev[i]
            else:
                v = r["C"][ci] if "C" in r and ci < len(r["C"]) else None
                ci += 1
                dn = meta[i].get("DN")
                if dn and isinstance(v, int) and v < len(dicts.get(dn, [])):
                    v = dicts[dn][v]
                row[i] = v
        out.append(row)
        prev = row
    return out


def serie(token, tipo, indicador):
    """Devuelve {mercado: {'AAAA-MM': valor}} para un tipo de alojamiento e indicador."""
    where = [eq("06. Territorio", TERRITORIO), eq("09. Tipo de Alojamientos", tipo),
             eq("12. Indicador", indicador)]
    rows = parse(query(token,
                       ["02. Año", "03. Mes Número", "11. Mercado Emisor", "13. Valor"],
                       aggs={"13. Valor"}, where=where))
    salida = {}
    for anyo, mes, mercado, valor in rows:
        if anyo is None or mes is None or valor is None:
            continue
        # El mercado nulo es el residente en Espana (columna "21. Mercados" = Nacional).
        nombre = mercado if mercado else "España"
        salida.setdefault(nombre, {})[f"{int(anyo)}-{int(mes):02d}"] = valor
    return salida


INICIO = "// <<<CDS_PAIS_INICIO>>>"
FIN = "// <<<CDS_PAIS_FIN>>>"


def inyectar(html_path, payload):
    """Reescribe el bloque de datos embebido del HTML entre los marcadores.

    Se embebe en vez de servir un .json aparte para que el observatorio siga
    funcionando abierto como fichero local (file:// bloquea fetch de vecinos).
    """
    html = html_path.read_text(encoding="utf-8")
    i, j = html.find(INICIO), html.find(FIN)
    if i == -1 or j == -1:
        raise RuntimeError(f"Marcadores {INICIO}/{FIN} no encontrados en {html_path}")
    bloque = f"{INICIO}\nconst CDS_PAIS = {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))};\n{FIN}"
    html_path.write_text(html[:i] + bloque + html[j + len(FIN):], encoding="utf-8")
    return len(bloque)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    destino = Path(args[0]) if args else Path("data/paises_marbella.json")
    html = next((Path(a.split("=", 1)[1]) for a in sys.argv[1:]
                 if a.startswith("--html=")), None)

    token = get_token()
    print("Token de embed obtenido.")

    datos = {}
    for tipo in TIPOS:
        for ind in INDICADORES:
            s = serie(token, tipo, ind)
            if not s:
                print(f"  {tipo}/{ind}: sin datos")
                continue
            datos.setdefault(tipo, {})[ind] = s
            meses = {m for v in s.values() for m in v}
            print(f"  {tipo}/{ind}: {len(s)} mercados, {len(meses)} meses")

    if not datos:
        raise RuntimeError("No se obtuvo ningun dato: la API interna pudo cambiar.")

    meses_todos = sorted({m for t in datos.values() for i in t.values()
                          for v in i.values() for m in v})
    meses = [m for m in meses_todos if m >= MIN_MES]
    recortados = len(meses_todos) - len(meses)
    if recortados:
        print(f"  (recortados {recortados} meses previos a {MIN_MES}: "
              f"desglose por país no fiable en la fuente)")
    mercados = sorted({k for t in datos.values() for i in t.values() for k in i})
    paises = [m for m in mercados if m not in AGREGADOS and m != "Total"]

    # Arrays alineados al indice de meses: pesa ~3 veces menos que repetir la
    # clave "AAAA-MM" en cada uno de los ~30.000 valores.
    compacto = {t: {i: {k: [v.get(m) for m in meses] for k, v in s.items()}
                    for i, s in ind.items()} for t, ind in datos.items()}

    salida = {
        "meta": {
            "fuente": "Turismo Costa del Sol · Big Data (microdato EOH del INE)",
            "url": "https://www.costadelsolmalaga.org/bigdata/com1_tc-357990/viajeros-pernoctaciones?mun=29069",
            "territorio": TERRITORIO,
            "desde": meses[0],
            "hasta": meses[-1],
            "paises": paises,
            "agregados": [m for m in mercados if m in AGREGADOS or m == "Total"],
        },
        "meses": meses,
        "datos": compacto,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    print(f"\nOK -> {destino}  ({destino.stat().st_size/1024:.0f} KB)")
    print(f"Rango {meses[0]} a {meses[-1]} · {len(paises)} paises · {len(mercados)} mercados")

    if html:
        n = inyectar(html, salida)
        print(f"OK -> bloque embebido en {html.name}  ({n/1024:.0f} KB)")


if __name__ == "__main__":
    main()
