# Tabla E2 vs E3 · corrida `ab-e2-e3-maquina-jj`

Máquina: 12th Gen Intel(R) Core(TM) i5-12450HX · 23.7 GB · Docker 29.8.0. Mismo cliente que el E2 (`medicion/medir.py`, 200 ejecuciones + 20 de calentamiento, `force_custom_plan`), plataforma detenida, 5 rondas intercaladas E2 → E3. Valores en ms; E2 hoy y E3 final son medianas entre rondas (rango entre corchetes).

| Consulta | Escenario | Métrica | E2 informe | Meta E3 (−10 %) | E2 hoy [rango] | E3 final [rango] | E3 vs E2 informe | E3 vs E2 hoy | Cumple meta | Mejora atribuible |
|---|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|
| Q1 proveedor + contrato | caliente | p50 | 0,52 | 0,468 | 0,77 [0,69–0,96] | **0,81** [0,72–1,52] | 55,2 % | 5,1 % | NO | dentro del ruido |
| Q1 proveedor + contrato | caliente | p95 | 0,70 | 0,630 | 1,16 [0,96–1,71] | **1,20** [1,09–1,89] | 71,8 % | 4,0 % | NO | dentro del ruido |
| Q1 proveedor + contrato | caliente | p99 | 1,05 | 0,945 | 1,39 [1,15–2,64] | **1,52** [1,29–2,15] | 44,9 % | 9,7 % | NO | dentro del ruido |
| Q1 proveedor + contrato | frio | p50 | 0,53 | 0,477 | 0,89 [0,70–0,93] | **0,75** [0,70–0,98] | 42,3 % | -15,0 % | NO | solo en mediana |
| Q1 proveedor + contrato | frio | p95 | 0,60 | 0,540 | 1,28 [1,17–1,76] | **1,14** [1,13–1,85] | 89,7 % | -10,8 % | NO | solo en mediana |
| Q1 proveedor + contrato | frio | p99 | 0,69 | 0,621 | 1,70 [1,28–2,01] | **1,37** [1,24–2,00] | 98,8 % | -19,2 % | NO | solo en mediana |
| Q2 precio de 20 SKU | caliente | p50 | 0,54 | 0,486 | 0,90 [0,81–1,79] | **0,91** [0,76–1,31] | 69,2 % | 1,5 % | NO | dentro del ruido |
| Q2 precio de 20 SKU | caliente | p95 | 0,64 | 0,576 | 1,39 [1,04–2,47] | **1,34** [1,27–2,09] | 109,4 % | -3,2 % | NO | dentro del ruido |
| Q2 precio de 20 SKU | caliente | p99 | 0,74 | 0,666 | 1,54 [1,22–3,92] | **1,50** [1,41–2,91] | 103,4 % | -2,6 % | NO | dentro del ruido |
| Q2 precio de 20 SKU | frio | p50 | 0,54 | 0,486 | 0,88 [0,80–1,17] | **0,90** [0,77–1,07] | 67,2 % | 2,6 % | NO | dentro del ruido |
| Q2 precio de 20 SKU | frio | p95 | 0,66 | 0,594 | 1,24 [1,10–1,73] | **1,41** [1,25–1,58] | 114,0 % | 13,8 % | NO | dentro del ruido |
| Q2 precio de 20 SKU | frio | p99 | 0,78 | 0,702 | 1,49 [1,33–2,14] | **1,59** [1,36–1,93] | 103,8 % | 6,6 % | NO | dentro del ruido |
| Q3 franjas con cupo | caliente | p50 | 0,53 | 0,477 | 0,78 [0,73–0,87] | **0,85** [0,67–1,06] | 60,9 % | 8,7 % | NO | dentro del ruido |
| Q3 franjas con cupo | caliente | p95 | 0,81 | 0,729 | 1,02 [1,00–1,08] | **1,06** [1,05–1,31] | 30,8 % | 3,6 % | NO | dentro del ruido |
| Q3 franjas con cupo | caliente | p99 | 0,98 | 0,882 | 1,11 [1,09–1,12] | **1,25** [1,12–1,42] | 27,5 % | 12,6 % | NO | dentro del ruido |
| Q3 franjas con cupo | frio | p50 | 0,54 | 0,486 | 0,76 [0,73–1,32] | **0,81** [0,70–0,95] | 49,4 % | 6,4 % | NO | dentro del ruido |
| Q3 franjas con cupo | frio | p95 | 0,97 | 0,873 | 1,11 [1,09–2,19] | **1,17** [1,08–1,53] | 20,6 % | 5,2 % | NO | dentro del ruido |
| Q3 franjas con cupo | frio | p99 | 1,89 | 1,701 | 1,27 [1,16–2,42] | **1,36** [1,26–1,72] | -28,1 % | 6,9 % | SÍ | dentro del ruido |
| Q4 OTIF y fill rate | caliente | p50 | 1,15 | 1,035 | 1,72 [1,63–1,79] | **1,17** [1,00–1,47] | 1,5 % | -32,2 % | NO | SÍ |
| Q4 OTIF y fill rate | caliente | p95 | 11,17 | 10,053 | 15,70 [15,36–16,25] | **2,76** [2,49–3,33] | -75,3 % | -82,4 % | SÍ | SÍ |
| Q4 OTIF y fill rate | caliente | p99 | 11,48 | 10,332 | 18,04 [16,48–24,05] | **3,08** [2,73–7,51] | -73,2 % | -82,9 % | SÍ | SÍ |
| Q4 OTIF y fill rate | frio | p50 | 1,14 | 1,026 | 1,18 [1,12–1,56] | **0,98** [0,86–2,21] | -14,4 % | -17,5 % | SÍ | solo en mediana |
| Q4 OTIF y fill rate | frio | p95 | 1,75 | 1,575 | 1,59 [1,56–2,87] | **1,47** [1,09–8,76] | -15,8 % | -7,3 % | SÍ | dentro del ruido |
| Q4 OTIF y fill rate | frio | p99 | 2,13 | 1,917 | 1,73 [1,67–10,37] | **1,71** [1,29–20,20] | -19,8 % | -1,0 % | SÍ | dentro del ruido |
| Q5 últimas 50 órdenes | pagina1 | p50 | 0,69 | 0,621 | 0,98 [0,85–1,02] | **0,82** [0,75–1,23] | 19,5 % | -15,6 % | NO | solo en mediana |
| Q5 últimas 50 órdenes | pagina1 | p95 | 0,77 | 0,693 | 1,38 [1,26–1,47] | **1,23** [1,01–2,04] | 59,2 % | -10,8 % | NO | solo en mediana |
| Q5 últimas 50 órdenes | pagina1 | p99 | 0,98 | 0,882 | 1,62 [1,42–1,66] | **1,38** [1,11–5,35] | 40,5 % | -14,9 % | NO | solo en mediana |
| Q5 últimas 50 órdenes | offset5000 | p50 | 2,23 | 2,007 | 5,70 [5,47–6,06] | **1,57** [1,28–1,64] | -29,5 % | -72,4 % | SÍ | SÍ |
| Q5 últimas 50 órdenes | offset5000 | p95 | 2,67 | 2,403 | 7,83 [6,48–8,39] | **1,98** [1,73–2,77] | -25,9 % | -74,8 % | SÍ | SÍ |
| Q5 últimas 50 órdenes | offset5000 | p99 | 3,04 | 2,736 | 9,51 [6,87–10,67] | **2,13** [1,85–3,08] | -29,9 % | -77,6 % | SÍ | SÍ |
| Q5 últimas 50 órdenes | keyset | p50 | 0,63 | 0,567 | 1,09 [0,90–1,44] | **1,06** [1,00–1,43] | 67,6 % | -3,1 % | NO | dentro del ruido |
| Q5 últimas 50 órdenes | keyset | p95 | 0,85 | 0,765 | 1,41 [1,25–2,19] | **1,54** [1,33–1,81] | 80,9 % | 8,8 % | NO | dentro del ruido |
| Q5 últimas 50 órdenes | keyset | p99 | 1,11 | 0,999 | 1,55 [1,36–2,53] | **1,75** [1,51–2,16] | 57,4 % | 12,6 % | NO | dentro del ruido |

**Resumen:** 9 de 33 métricas cumplen la meta frente al informe del E2; 6 tienen una mejora atribuible al sistema (≥ 10 % frente al estado E2 medido hoy y sin solape entre rondas).
