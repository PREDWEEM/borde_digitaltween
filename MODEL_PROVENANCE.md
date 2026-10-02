# Proveniencia del motor científico

La capa biofísica y los activos neuronales se separaron del repositorio
`PREDWEEM/LOLIUM_BOR2026` en el commit:

`317168f516130cfd1e6dee7f0b5c5d198bd08219`

El repositorio fuente no fue modificado. Los hashes SHA-256 permiten verificar
que los pesos y el clasificador copiados no fueron alterados:

| Activo | SHA-256 |
|---|---|
| `models/IW.npy` | `8614f90cd5f1337ae746690e474587b6fb22cf81652e694573cbfe4573f406d5` |
| `models/LW.npy` | `13cb012d7f4fe8e9e8399b31226e160ed60690cd4fb225a2de40375d250eb97b` |
| `models/bias_IW.npy` | `69423ba136a4caad97bed6b3aae2e7a387d87851a32eb5b2ab8de74dbcae3788` |
| `models/bias_out.npy` | `53451c25cc92da6bff25404a1e47815e38dfe58f7d83bb87c2d471298ec8a12d` |
| `models/modelo_clusters_k3.pkl` | `29f0508543bdda4b2520038c678a9df80ff9be555e0c15d5fa1f4da16a499d30` |

La extracción conserva:

- entradas ANN: día juliano, TMAX aire, TMIN aire y precipitación;
- latencia hasta JD 15;
- primer pico válido `EMERREL > 0,20`;
- termoinhibición con media móvil de cinco días y umbral 24 °C (original; v2: 26 °C);
- choque hídrico de tres días, 45 mm, hasta JD 110 (original; v2: 60 mm, piso 0,5);
- ET0 Hargreaves y balance hídrico superficial;
- tiempo térmico triangular 2–20–30 °C;
- objetivo de control 600 °Cd y límite 800 °Cd.

La asimilación y la persistencia son componentes nuevos y están aislados en
`predweem_twin/assimilation.py` y `predweem_twin/storage.py`.

## Selección histórica de Bordenave

Por indicación del usuario, la normalización estacional excluye las curvas
`emererel2025 balcarce.xlsx` y `emrel sp 2025 san pedro.xlsx`, además de 2010 y
2015. El filtro por localidad ignora mayúsculas y espacios repetidos y se
aplica antes de acumular las curvas y calcular sus percentiles. Los nombres
son obligatorios para impedir que una referencia sin identificación omita
silenciosamente las exclusiones.

Quedan nueve curvas: 2008, 2009, 2011, 2012, 2013, 2014, 2023, 2024 y
`test -emerel tresas 2025.xlsx`. Los primeros ocho archivos sólo identifican
el año y no permiten atribuir aquí su localidad. El clasificador y la ANN
no se modifican; esta selección afecta exclusivamente la referencia
estacional del gemelo y las operaciones que dependen de ella.

Aplicación, escenarios y generador de calibración utilizan la misma selección.
El perfil `data/calibration/bordenave_2026.json` registra campañas incluidas,
excluidas y cantidad. Se regeneran perfil y diagnósticos con los mismos datos
2026 y cortes, porque el fingerprint incluye `predweem_twin/seasonal.py`.
No se modifica el mecanismo de anclaje a la mediana histórica en esta revisión.

## Reglas v2 (validación 2008–2026)

Cambios respecto del motor original, validados contra los conteos de campo con la
métrica de **masa mal ubicada** (diferencia de variación total entre la
distribución observada y la modelada de la emergencia entre conteos):

| Regla | Original | v2 |
|---|---|---|
| Termoinhibición (media de 5 días) | 24 °C | **26 °C** |
| Umbral de choque hídrico (3 días) | 45 mm | **60 mm** |
| Piso del choque hídrico | 1,0 | **0,5** |
| Techo desde el 15/04 | no existía en este repositorio | **25 % del máximo previo, τ=40 d, I=0,75** |
| Condición del techo | siempre | **sólo si hubo ≥1 día con flujo ≥0,5 antes del 15/04** |

La condición evita recortar los años de emergencia tardía (en Bordenave 2010 y
2015, más del 80 % de la emergencia ocurrió después del 10/04).

Evidencia (Bordenave 2026 + 2008–2015 (9 campañas)): masa mal ubicada media 45,4 % → 38,4 %. En las 14 campañas
disponibles (Tres Arroyos, Lartigau, Bordenave 2026 y Bordenave 2008–2015) el
promedio bajó de 43,8 % a ~33 %; el error medio de la curva acumulada, de 7,4 a
5,6 puntos porcentuales; y el tamaño de los tres pulsos mayores pasó de 0,61 a
0,96 del observado (mediana). Límites: pocas campañas, parte del clima de
2026 proviene de pronósticos archivados, y los parámetros se eligieron en parte
con las mismas campañas. El efecto del piso y del umbral del choque hídrico no
es estable entre años; Bordenave 2010 sigue mal ubicada (65 %). No se evaluó la
magnitud absoluta (plantas por m²).

**Interruptor de retorno:** `ModelParameters.legacy()` devuelve los valores
anteriores (por ejemplo, `run_predweem(weather, model, ModelParameters.legacy())`).
El perfil de calibración se recalcula porque la huella del modelo incluye
`core.py`; el perfil anterior queda invalidado por diseño.
