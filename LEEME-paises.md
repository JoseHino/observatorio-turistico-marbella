# Desglose por país — Observatorio Turístico de Marbella

Añade a la pestaña **Origen & Gasto** el país de residencia real de los
viajeros alojados en Marbella, por tipo de alojamiento (hoteles y apartamentos),
con viajeros y pernoctaciones. Es el cruce **país × municipio** que el INE **no**
publica en su web (solo da España / Extranjero a nivel municipal).

## De dónde salen los datos

Del visor Big Data de **Turismo Costa del Sol**:

    https://www.costadelsolmalaga.org/bigdata/com1_tc-357990/viajeros-pernoctaciones?mun=29069

Es un informe **Power BI** montado sobre el **microdato de la Encuesta de
Ocupación Hotelera del INE**, con el desglose por país. Los totales coinciden al
100 % con la API del INE (verificado: 714.526 viajeros de hotel en 2024, idéntico).

No hay API pública documentada: el visor genera un token temporal en cada carga y
con él se consulta el endpoint semántico de Power BI. **Ese endpoint no admite
CORS** (solo acepta peticiones desde `app.powerbi.com`), por lo que **no se puede
leer en vivo desde el navegador**. Por eso los datos se **embeben** en el HTML.

## Cómo refrescar los datos

Con Python (solo librería estándar, sin dependencias):

```bash
python "fetch_paises_cds.py" "data/paises_marbella.json" --html="Observatorio Turístico Marbella.html"
```

Esto:
1. descarga la serie completa desde Turismo Costa del Sol,
2. la guarda en `data/paises_marbella.json`,
3. y reescribe el bloque de datos embebido del HTML (entre los marcadores
   `// <<<CDS_PAIS_INICIO>>>` y `// <<<CDS_PAIS_FIN>>>`).

## Refresco automático (GitHub Actions)

El workflow `.github/workflows/actualizar-paises.yml` lo hace solo el día 8 de
cada mes y hace commit del HTML actualizado. Requiere que esta carpeta sea un
repositorio de GitHub. Pasos una sola vez:

1. Crear un repo en GitHub (p. ej. `observatorio-turistico-marbella`).
2. Desde esta carpeta:
   ```bash
   git init
   git add .
   git commit -m "Observatorio turístico de Marbella"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/observatorio-turistico-marbella.git
   git push -u origin main
   ```
3. En el repo, Settings → Actions → General → "Workflow permissions" →
   **Read and write permissions**.
4. (Opcional) Settings → Pages → servir desde `main` para publicarlo online.

## Nota sobre el rango temporal

El desglose **por país** se muestra **desde enero de 2019**. La fuente tiene datos
etiquetados por mercado desde 2016, pero **2016-2017 están incompletos** (parte del
extranjero sin asignar a país) y **2018 está corrupto en origen** (Reino Unido
aparece hundido y Alemania/Japón inflados; la suma de países supera al total). A
partir de 2019 la suma por país reconcilia al 100 % con el agregado "Extranjero".
El corte está en la constante `MIN_MES` de `fetch_paises_cds.py`.

El split agregado España/Extranjero sí es fiable desde 2005, pero eso ya lo cubre
la gráfica EOH+OAT del propio observatorio.
