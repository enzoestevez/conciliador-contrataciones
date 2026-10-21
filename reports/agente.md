# Informe del agente conciliador

267 avisos procesados · modelo `gemini-3.5-flash-lite`

> Corrida **reprocesada** desde `reports/traza.jsonl` el 2026-10-21 con el código del commit `3e388fd`, umbral 0.55. Las extracciones son las de la corrida original: no se volvió a llamar al modelo y el reproceso costó USD 0.00. Ver `src/reprocesar.py`.

## Qué decidió

| Decisión | Casos | | Qué significa |
|---|---:|---:|---|
| `sin_llave` | 126 | 47% | el aviso no declara UOC: no tramita por COMPR.AR |
| `aprobado` | 95 | 36% | emparejado y comparado |
| `sin_registro` | 35 | 13% | la llave no existe en el registro |
| `escalado` | 11 | 4% | candidato dudoso → revisión humana |

**40% de los avisos son verificables** contra el registro oficial. El resto no tiene contraparte legible por máquina: o el organismo no usa el sistema central de contrataciones, o el registro todavía no cargó el proceso.

## Cuánto cuesta operarlo

| | |
|---|---:|
| Costo total | USD 0.1970 |
| Costo por aviso | USD 0.000738 |
| Costo por 1.000 avisos | USD 0.74 |
| Tokens | 205,590 entrada · 54,147 salida |
| Latencia mediana | 3.3 s |
| Latencia p95 | 4.3 s |

## Discrepancias · sobre los 95 emparejados

Campos que **no** participan del emparejamiento, así que una diferencia
acá es un hallazgo y no un artefacto de cómo se eligió el candidato.

| Campo | Difiere | |
|---|---:|---:|
| `tipo_procedimiento` | 0 | 0% |
| `fecha_apertura` | 15 | 16% |
| `monto_estimado` | 0 | 0% |

## Datos que el Boletín omite y el registro publica

| Campo | Omitido | |
|---|---:|---:|
| `monto_estimado` | 95 | 100% |
| `fecha_apertura` | 14 | 15% |

No son discrepancias: es una brecha de cobertura entre dos
publicaciones del mismo Estado, y se reporta aparte a propósito.

## Confianza de emparejamiento

Mediana 1.00 · mínima 0.58 · casos con un único candidato: 69 de 95

## Evaluación de punta a punta

`cruzar.py` hizo el mismo emparejamiento partiendo del set etiquetado a mano
del proyecto 01. Comparar las dos corridas mide cuánto se degrada el sistema
completo cuando el extractor se equivoca — que no es lo mismo que la precisión
del extractor.

**La verdad de referencia no costó una etiqueta nueva: el proyecto 01 es el oráculo.**

| | Casos | |
|---|---:|---:|
| Misma decisión que con etiquetas perfectas | 114 | 99% |
| Decisión distinta | 1 | 1% |

Dónde se degrada:

- `36725-26` → escalado (agente) vs sin_llave (etiquetas)

De los 50 casos que ambos emparejaron, coincidieron en el **mismo proceso del registro en 50** (100%).

---

Generado por `src/informe.py` desde `reports/traza-reproceso.jsonl`.