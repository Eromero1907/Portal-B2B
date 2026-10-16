# Guía de capturas de Grafana (una por corrida representativa)
Abrir cada enlace en el navegador (Grafana en http://localhost:3000, tablero `portal-b2b`), esperar a que carguen los paneles y capturar **p99/p95 por ruta, tasa de errores, reparto por instancia, pool/colas** con la ventana completa de la corrida. Guardar como `Entrega 3/evidencia/<ID>/capturas/<config>.png`.
Si un enlace muestra *No data*: Prometheus no conserva esa ventana (se recreó el volumen) → anotarlo y usar `solicitudes.csv`/`recursos.csv` como evidencia; no inventar la captura.

| Exp. | Corrida | Hora local (Bogotá) | Falla (hora local) | Enlace |
|---|---|---|---|---|
| A1 | sin_r1 | 00:50:20–00:57:47 | 00:52:01–00:56:52 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792129820000&to=1792130297000 |
| A1 | con_r1 | 01:05:20–01:12:48 | 01:07:02–01:11:54 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792130720000&to=1792131198000 |
| A2 | sin_r1 | 01:58:13–02:05:42 | 01:59:55–02:04:47 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792133893000&to=1792134372000 |
| A2 | con_r2 | 02:20:49–02:28:18 | 02:22:32–02:27:24 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792135249000&to=1792135728000 |
| B1 | sin_r1 | 08:43:54–08:49:38 | 08:46:39–08:47:24 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792158234000&to=1792158608000 |
| B1 | con_r1 | 09:17:41–09:23:26 | 09:20:26–09:21:12 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792160261000&to=1792160636000 |
| B2 | sin-lock0_r3 | 13:50:54–13:56:41 | 13:51:11–13:52:10 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792176654000&to=1792177031000 |
| B2 | con-lock0_r6 | 15:49:38–15:55:28 | 15:49:58–15:50:57 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792183778000&to=1792184158000 |
| C1 | sin-cpu010_r1 | 13:25:30–13:33:16 | 13:27:16–13:32:16 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792175130000&to=1792175626000 |
| C1 | con-cpu010_r1 | 13:33:26–13:41:15 | 13:35:14–13:40:14 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792175606000&to=1792176105000 |
| C2 | sin_r1 | 08:26:54–08:43:41 | 08:28:40–08:33:38 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792157214000&to=1792158251000 |
| C2 | con_r1 | 09:09:30–09:17:29 | 09:11:16–09:16:14 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792159770000&to=1792160279000 |
| D1 | sin_r1 | 08:15:06–08:20:50 | 08:17:52–08:18:52 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792156506000&to=1792156880000 |
| D1 | con_r1 | 08:57:42–09:03:27 | 09:00:28–09:01:28 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792159062000&to=1792159437000 |
| D2 | sin_r1 | 01:28:07–01:35:35 | 01:29:48–01:34:40 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792132087000&to=1792132565000 |
| D2 | con_r1 | 01:35:38–01:43:08 | 01:37:22–01:42:13 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792132538000&to=1792133018000 |
| D2 | con-umbral70_r4 | 14:22:46–14:30:37 | 14:24:36–14:29:35 | http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&timezone=browser&refresh=&from=1792178566000&to=1792179067000 |
