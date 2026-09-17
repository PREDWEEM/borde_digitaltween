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
- termoinhibición con media móvil de cinco días y umbral 24 °C;
- choque hídrico de tres días, 45 mm, hasta JD 110;
- ET0 Hargreaves y balance hídrico superficial;
- tiempo térmico triangular 2–20–30 °C;
- objetivo de control 600 °Cd y límite 800 °Cd.

La asimilación y la persistencia son componentes nuevos y están aislados en
`predweem_twin/assimilation.py` y `predweem_twin/storage.py`.

