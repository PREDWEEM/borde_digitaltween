# PREDWEEM Digital Twin — Lolium Bordenave

Primera implementación funcional de un **gemelo digital agronómico** para la
dinámica de emergencia de *Lolium multiflorum* en Bordenave, Buenos Aires.

El proyecto deriva del modelo científico
[`PREDWEEM/LOLIUM_BOR2026`](https://github.com/PREDWEEM/LOLIUM_BOR2026), que se
mantiene intacto. Este repositorio agrega una capa independiente de estado,
asimilación de observaciones, persistencia por lote y simulación de escenarios.

## Visitas periódicas para reducir la hibernación

El workflow [mantener_activo.yml](.github/workflows/mantener_activo.yml) abre
[la aplicación de Bordenave](https://nhfm7pn5fzkd5shigp2vyh.streamlit.app/)
con Chromium cada cuatro horas: 00:29, 04:29, 08:29, 12:29, 16:29 y 20:29 UTC
(21:29, 01:29, 05:29, 09:29, 13:29 y 17:29 de Argentina).
También permite ejecución manual desde
**Actions → Mantener activo el gemelo Bordenave → Run workflow** y se ejecuta
al modificar el workflow o su script.

Cuando aparece **Yes, get this app back up!**, la tarea hace clic en el botón
y espera la apertura, con un límite total de cinco minutos. Comprueba el
encabezado de Bordenave, el indicador de emergencia, el panel principal y su
gráfico, incluso si están dentro de un iframe. Una respuesta HTTP 200 por sí
sola no cuenta como éxito. Si la app muestra una excepción o no termina de
cargar, la ejecución queda fallida; los avisos dependen de las preferencias
de notificaciones de GitHub Actions.

La tarea no requiere secretos ni modifica observaciones o parámetros del modelo.
Playwright se instala solamente en el ejecutor de Actions. Esto reduce el riesgo
de hibernación, pero **no garantiza disponibilidad continua**:
[Streamlit suspende las apps sin visitas durante 12 horas](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app#app-hibernation)
y [GitHub puede demorar tareas o desactivarlas tras 60 días sin actividad en un repositorio público](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
Si ocurre lo último, vuelva a habilitar el workflow desde Actions.

## Qué convierte esta versión en un gemelo digital

```mermaid
flowchart TD
    A["Meteo INTA / ECMWF / Open-Meteo"] --> B["PREDWEEM biofísico + ANN"]
    B --> C["Estado diario del lote"]
    D["Conteo de campo"] --> E["Asimilación secuencial"]
    C --> E
    E --> F["Estado actualizado"]
    F --> G["Pronóstico y riesgo 7 días"]
    F --> H["Escenarios lluvia / temperatura"]
```

El sistema mantiene explícitamente:

- emergencia acumulada y fracción remanente;
- humedad superficial estimada y factor hídrico;
- tiempo térmico desde el primer pico y límite operativo de 800 °Cd;
- termoinhibición, próxima cohorte y riesgo a siete días;
- observaciones, innovaciones y estados posteriores de cada asimilación;
- fuente meteorológica y parámetros utilizados.

## Asimilación de datos

Los conteos en plantas/m² se interpretan como el flujo ocurrido desde el
muestreo anterior. Para cada intervalo, el gemelo suma el flujo diario relativo
producido por PREDWEEM y lo compara con el flujo observado:

\[
Y_i = N \sum_{d=t_{i-1}+1}^{t_i} e_d
\]

donde `Y_i` es el flujo observado, `e_d` el flujo diario relativo y `N` el
potencial estacional latente. La aplicación estima `N` secuencialmente sin
tratar una serie parcial como si estuviera completa. Puede incorporarse un
potencial histórico previo del lote; el valor `0` activa la estimación
automática.

La corrección de cada flujo utiliza una ganancia escalar:

\[
K = \frac{P}{P + R}, \qquad x^+ = x^- + K(y-x^-)
\]

donde `P` y `R` son las varianzas del modelo y del flujo observado. Después de
cada corrección, la curva futura se reancla sobre la fracción aún no emergida.
Los archivos que ya contienen acumulados normalizados mantienen el método
escalar anterior como modo de compatibilidad. No se reentrena la ANN.

## Operación con meteorología parcial

El modo operativo supone que cada ejecución dispone de meteorología observada
hasta la fecha del estado y de un pronóstico para los siete días siguientes:

```text
1 de enero ───────── fecha del estado ───────── +7 días
       observado/provisional            pronóstico
```

La última fila no marcada como `Pronostico` define automáticamente la fecha del
estado. La aplicación recorta cualquier extensión posterior al séptimo día e
informa cuántos días de pronóstico están realmente disponibles.

La curva parcial no se normaliza por el total existente al final de esos siete
días. PREDWEEM utiliza como referencia el progreso acumulado mediano de las
campañas históricas seleccionadas, excluyendo 2010, 2015, Balcarce y San Pedro,
y ancla la escala en la
fecha del estado. De esta manera, el final del pronóstico no se interpreta como
100 % de la emergencia. Las temperaturas y precipitaciones pronosticadas
determinan el incremento de emergencia de los siete días siguientes. Los
conteos de campo actualizan posteriormente ese estado mediante la asimilación.

La referencia utiliza **nueve curvas**: 2008, 2009, 2011, 2012, 2013, 2014,
2023 y 2024 (archivos identificados sólo por año), y Tres Arroyos 2025.
No se atribuyen todas estas series a Bordenave. Balcarce 2025 y San Pedro 2025
se excluyen antes de calcular P10, mediana y P90. La selección se aplica tanto
a la aplicación y los escenarios como a la generación de la calibración 2026.
La interfaz y el perfil JSON registran los nombres utilizados y excluidos.
El clasificador original se conserva intacto; sus curvas excluidas no
intervienen en esta referencia estacional.

Sin siete días futuros, el sistema conserva el estado disponible y muestra una
advertencia de horizonte incompleto; no presupone que la campaña terminó.

## Funciones de la aplicación

- meteorología operativa INTA Bordenave + ECMWF;
- alternativa georreferenciada de Open-Meteo;
- carga de meteorología CSV/XLSX;
- cobertura del rastrojo constante o serie observada `FECHA + COBERTURA_PCT`;
- estado persistente por identificador de lote en SQLite;
- asimilación directa de conteos por intervalo con incertidumbre;
- carga masiva de observaciones CSV/XLS/XLSX en formato `FECHA + PLM2` o
  `FECHA + EMERGENCIA_ACUMULADA`;
- curva PREDWEEM base frente a estado Twin actualizado;
- banda amarilla de la ventana fenológica entre 600 y 800 °Cd desde el primer pico;
- escenarios contrafactuales de lluvia y temperatura;
- fechas d25, d50, d75 y d95;
- exportación CSV de la trayectoria completa y auditable.

## Calibración por sitio con observaciones 2026

La pestaña **Calibración por sitio** contiene las 33 fechas del archivo
`valida(3).xlsx`, hoja `Hoja1`, del 10/01 al 14/09/2026, asignadas a Bordenave
según la solicitud del autor. Se conservan las tres repeticiones y la media
original en `data/calibration/bordenave_2026_counts.csv`. El factor inferido
de conversión a m² es 4. El total registrado es **7041,33 plantas/m²** y no
se interpreta como el potencial estacional de una campaña terminada.

La capa externa aplica una transformación monótona al acumulado base:

\[
F_{local}=\operatorname{logistic}(a+b\operatorname{logit}(F_{base})).
\]

Se conservan los extremos 0 y 1, los días sin flujo, los pesos de la ANN,
el balance hídrico, la termoinhibición y el reloj de 600–800 °Cd. La corrección
puede modificar el progreso relativo y la distribución del flujo, pero no
crear una cohorte donde los filtros biofísicos bloquean la emergencia.

El ajuste compara las sumas del flujo entre fechas de conteo con los flujos
observados. Hay **32 intervalos utilizables**, incluido el de 14 días entre
el 1 y el 15 de junio. El archivo actualizado incorpora un registro de cero
el **10/01/2026**. Ese registro delimita el primer intervalo, de **23 días**,
hasta el 02/02/2026, cuyo conteo de **713,33 plantas/m²** participa ahora del
ajuste. No se infiere ausencia de emergencia antes del 10 de enero.
No se interpolan observaciones diarias. Se pondera por el error estándar de
las repeticiones con un piso común del 10 % del máximo flujo observado
(mínimo 1 planta/m²). El ajuste se regulariza hacia la identidad y se limita
a `a ∈ [-1.5, 1.5]` y `b ∈ [0.6, 1.6]`.

Cada curva se escala al **total de la ventana muestreada**, sin declarar que
esa ventana contiene el 100 % de la emergencia. La escala auxiliar sirve
para comparar los intervalos; **no se transfiere como potencial o densidad
a otro lote**. El potencial sigue siendo estimado por la asimilación existente.

### Uso en el gemelo

- Seleccionar **Localidad del lote: Bordenave** y **Usar calibración local 2026**.
- El perfil se aplica antes de la asimilación y también a los escenarios.
  El gráfico permite comparar base, calibración y estado actualizado.
- No se aplica a otra localidad ni a una fecha anterior al 14/09/2026.
  Los gráficos del año de ajuste son retrospectivos; el perfil fue preparado
  el 19/09/2026 y no se presenta como disponible en un pronóstico histórico real.
- Si se están asimilando conteos de la campaña 2026, se utiliza la base
  original para evitar reutilizar esa campaña como calibración y evidencia
  nueva. El perfil permanece guardado para campañas posteriores; sus conteos
  nuevos sí pueden asimilarse sobre la trayectoria calibrada.
- Los datos de referencia no sobrescriben SQLite ni se insertan automáticamente
  en los lotes. La pestaña permite descargarlos para cargarlos en Observaciones.
- La exportación incluye `EMERAC_BASE_SIN_CALIBRAR`, `EMERAC_CALIBRADA`,
  `EMERREL_CALIBRADA`, identificación del perfil, motivo y estado de aplicación.
- Un cambio de pesos, filtros o referencia histórica invalida la huella del
  perfil; se usa la base original hasta regenerar la calibración.

La capa admite campañas posteriores, pero la aplicación y su actualizador
mantienen el cierre meteorológico **01/10/2026**. Al abrir una nueva campaña
deberá configurarse su meteorología; este cambio no modifica ese cierre.

### Resultado y alcance

El ajuste inicial usa cobertura constante del **50 %** y Wmax **18,8 mm**,
que son los valores de la interfaz. El archivo de conteos no aporta cobertura,
manejo. La meteorología congelada contiene
250 días SIGA y 7 provisionales, hasta el 14/09/2026. Los cambios de cobertura
y Wmax en la interfaz siguen siendo posibles, pero no implican que el perfil
se haya validado bajo esas condiciones.

El perfil es **experimental, de una sola campaña incompleta**. El RMSE de
ajuste por intervalo pasa de **393,13 a 356,93 plantas/m²** sobre los datos
empleados para estimarlo. Ninguno de los dos parámetros del perfil final
alcanza los límites permitidos. Estos RMSE corresponden a 32 intervalos:
no son directamente comparables con los de la revisión anterior, que excluía
el conteo del 2 de febrero y ajustaba sobre 31 intervalos.

Se incluyen seis evaluaciones temporales: se ajusta sólo con datos hasta
cada corte y se evalúa el siguiente intervalo con meteorología
observada/provisional. Se conservan las seis fechas de corte de la revisión
anterior, registradas en `validation_cutoffs`, para que la incorporación de
una fecha inicial no cambie los intervalos evaluados. El RMSE conjunto pasa
de **147,97 a 106,59 plantas/m²**, pero sólo un intervalo mejora; la reducción
se concentra en ese intervalo.
No son pronósticos archivados ni validación en otra campaña. No se reduce
automáticamente la incertidumbre del gemelo ni se infiere precisión para 2027.
Estos diagnósticos se regeneraron tras excluir Balcarce y San Pedro de la
referencia. Los conteos, la meteorología fija, los cortes y los pesos neuronales
son los mismos. El perfil conserva offset 0,50 y slope 1,35, con una nueva
identidad y huella compatibles con la selección de nueve curvas.

### Reproducción

```bash
python scripts/calibrate_site.py
python -m pytest -q
```

El generador usa los CSV fijos de `data/calibration/`, conserva los hashes
del archivo original, observaciones, meteorología y modelo, y produce
`bordenave_2026.json`, `bordenave_2026_fit.csv` y `bordenave_2026_holdout.csv`.
No descarga datos ni reentrena la red. Para actualizar el perfil, incorporar
los nuevos conteos y su meteorología, revisar los supuestos y regenerarlo.
La identificación del perfil incluye una huella de sus datos y configuración,
por lo que cambia ante revisiones aunque la última fecha de conteo sea la misma.

## Cobertura variable del rastrojo

La interfaz permite seleccionar **Constante** o **Serie observada**. La serie
observada se carga por lote en CSV/XLS/XLSX con esta estructura:

| FECHA | COBERTURA_PCT |
|---|---:|
| 2026-03-01 | 82 |
| 2026-03-15 | 70 |

Los valores deben estar entre 0 y 100. El gemelo interpola linealmente entre
mediciones. Antes de la primera utiliza la cobertura de respaldo configurada en
la barra lateral y, después de la última, conserva el último valor observado.
La cobertura diaria actualiza `Ke_Suelo` y el balance hídrico que condiciona el
flujo de emergencia. También actualiza las temperaturas superficiales estimadas
mediante el modulador térmico, sin modificar las entradas originales de la ANN.
Las mediciones quedan guardadas de forma independiente para cada lote.

## Ejecución local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

En Windows PowerShell, active el entorno con `.venv\\Scripts\\Activate.ps1`.

## Pruebas

```bash
python -m pytest -q
```

Las pruebas verifican límites biofísicos, monotonía del estado asimilado,
trazabilidad de la corrección y aislamiento de escenarios futuros.

## Formato de observaciones de campo

La pestaña **Observaciones** acepta dos estructuras:

| Fecha | Valor | Interpretación |
|---|---:|---|
| `FECHA` | `PLM2` | Flujo de plantas/m² observado en cada intervalo de muestreo |
| `FECHA` | `EMERGENCIA_ACUMULADA` u `OBSERVADO` | Acumulado expresado entre 0–1 o 0–100 % |
| `Fecha` + `1`, `2`, `3` | `media(SR).m2` | Tres repeticiones por cuadrante y su media convertida a plantas/m² |

El mismo archivo puede incluir una columna opcional `COBERTURA_PCT` o
`cobertura`. Al confirmar la carga, la aplicación guarda simultáneamente los
flujos de emergencia y la serie de cobertura para el lote. La validación exige
valores de cobertura entre 0 y 100.

Para `PLM2`, la aplicación conserva cada flujo y su acumulado absoluto. El
potencial estacional combina el progreso estructural de PREDWEEM con el ajuste
de los flujos por intervalo. El ajuste recibe más peso cuando reproduce bien la
forma observada y menos peso cuando la correspondencia temporal es débil. Esto
evita convertir prematuramente una campaña incompleta en 100 % de emergencia.

Cuando el archivo contiene repeticiones, la aplicación comprueba que la media
sea consistente, infiere el factor de conversión del cuadrante a m² y calcula la
incertidumbre desde el error estándar del flujo. Se aplica un mínimo de 5 % para
incorporar variación espacial y de muestreo no representada por tres cuadrantes.

La incertidumbre de las repeticiones se calcula sobre el flujo de cada intervalo
y el potencial estacional mantiene su propia incertidumbre. La interfaz muestra
por separado el acumulado estimado en plantas/m², el potencial estacional y el
progreso relativo.

### Diagnóstico anterior del corte al 5 de abril

El siguiente diagnóstico corresponde a la referencia anterior, que incluía
Balcarce y San Pedro; no describe la versión actual de nueve curvas.
Con los datos Bordenave 2026 disponibles únicamente hasta el 30 de marzo, el
nuevo método utilizó nueve flujos, estimó un potencial de 7770 plantas/m² y un
estado actualizado de 75,3 %. El valor retrospectivo calculado al completar la
campaña fue 71,7 %. El RMSE acumulado posterior fue 2,2 puntos porcentuales a
30 días y 2,7 puntos a 60 días. Es un diagnóstico interno de una campaña, no
una validación prospectiva independiente.

## Alcance científico

Esta es una **versión MVP experimental** del gemelo digital. El motor base
mantiene la parametrización de Bordenave vK4.9.15. La capa de asimilación debe
validarse prospectivamente con observaciones independientes antes de usarse de
forma operativa. Los escenarios son contrafactuales y no constituyen una
recomendación automática de tratamiento.

PREDWEEM apoya decisiones; no reemplaza el monitoreo del lote, el diagnóstico
local ni el criterio del profesional responsable.

## Autoría

**PREDWEEM by Guillermo R. Chantre**

Consulte [COPYRIGHT.md](COPYRIGHT.md) para las condiciones de uso.
La correspondencia con el motor original se documenta en
[MODEL_PROVENANCE.md](MODEL_PROVENANCE.md).

## Cierre meteorológico de la campaña 2026

La serie operativa termina el **1 de octubre de 2026, inclusive**. El límite
se aplica a SIGA, al puente provisional, al pronóstico ECMWF, a la consulta
Open-Meteo y a los archivos cargados en la aplicación. Después del cierre,
las actualizaciones pueden completar o reemplazar datos provisionales por
observaciones hasta esa fecha, sin agregar días posteriores ni exigir
pronósticos futuros. La interfaz reduce el horizonte esperado al acercarse
al cierre. Las referencias históricas de emergencia mantienen su extensión.
