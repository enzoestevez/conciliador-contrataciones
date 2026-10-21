# Agente conciliador de contrataciones públicas

> **Estado:** `completado · validado contra verdad de referencia humana`
>
> **Los dos números.** De los llamados que el Estado argentino publica en el
> Boletín Oficial, **el 90% de los que tramitan por COMPR.AR se puede verificar
> contra el registro oficial** — siempre que el registro los haya cargado. Y de
> los verificados, **uno de cada seis publica una fecha de apertura distinta de
> la del registro.**
>
> **Costo de auditar un aviso: USD 0,00074.** Un humano haciendo lo mismo cuesta
> USD 0,058 y tarda 113 segundos (medido en el
> [proyecto 01](https://github.com/enzoestevez/eval-extraccion-licitaciones)).
>
> 267 llamados de 5 ediciones · 128.951 convocatorias del registro oficial ·
> cero fallas de extracción.

---

## El problema

El Estado argentino publica la misma contratación dos veces: como aviso en el
Boletín Oficial, redactado por el organismo, y como registro estructurado en el
portal de datos abiertos. Nadie verifica que digan lo mismo.

Un proveedor que se guía por el aviso y una auditoría que se guía por el
registro pueden estar mirando dos versiones distintas del mismo llamado.

## Qué hace

Por cada aviso del Boletín, el agente:

1. **Extrae** nueve campos del texto con un modelo.
2. **Arma la llave** y busca el proceso correspondiente en el registro oficial.
3. **Decide si es el mismo proceso** antes de comparar nada, con tres señales
   independientes y un umbral explícito. Por debajo del umbral, escala a
   revisión humana en vez de inventar un hallazgo.
4. **Compara** sólo los campos que no se usaron para emparejar, y distingue
   cuatro resultados: coincide, discrepa, el Boletín lo omite, o no es
   comparable.

Con traza de cada paso, log de auditoría, permisos verificables, tope de gasto
comprobado **antes** de cada llamada, reintentos sobre errores transitorios y
reanudación.

## La verdad de referencia no la genera un modelo

Dos varas, ninguna producida por un modelo:

- **El registro oficial del Estado** (128.951 convocatorias de COMPR.AR) es la
  vara del hallazgo. Es pública, está a escala y existe independientemente de
  este proyecto.
- **El set de 115 avisos etiquetado a mano del proyecto 01**, con el techo del
  experimento medido por doble ciego, es la vara del *sistema*. Permite medir
  cuánto se degrada el pipeline completo cuando el extractor se equivoca.

**La verdad de referencia del proyecto 02 no costó una etiqueta nueva: el
proyecto 01 es el oráculo del 02.**

---

## El contrato de datos se verifica antes de construir

El estándar OCDS, que usa el portal argentino, **no define un campo de
expediente**: su identificador es `convocatoria_id`. El Boletín publica
`expediente` y `numero_procedimiento`. Que los dos lados se puedan unir era una
hipótesis, no un hecho.

`src/verificar_cruce.py` la puso a prueba antes de escribir una línea del
agente. Descubre el esquema del CSV solo, detecta columnas candidatas a llave
por la **forma** de sus valores y no por su nombre, prueba cada cruce y reporta
la tasa.

**El criterio de decisión quedó escrito antes de correr el script**, para que no
se pudiera mover el poste después de ver el resultado:

| Tasa de cruce | Decisión |
|---|---|
| ≥ 60% | el proyecto va |
| 30–60% | va, declarando la cobertura |
| < 30% | no hay cruce → plan B |

Resultado: **el proyecto va, con la cobertura declarada.** El plan B (agente de
estado temporal, apoyado en que el propio Boletín publica prórrogas y
rectificaciones que corrigen avisos anteriores) quedó diseñado y sin usar.

**Un instrumento sin validar da un veredicto falso.** El primer cruce dio 9% y
casi descartamos el proyecto. El error era del verificador, no de los datos: el
formato dominante de `Numero_Proceso` es `340/1-0006-LPR17` —la UOC lleva
barra— y la expresión regular sólo aceptaba la forma sin barra, descartando el
59% de las 128.951 convocatorias.

---

## Resultados · corpus completo

`python src/agente.py` sobre los **267 llamados** del corpus, y
`src/reprocesar.py` para que los 267 queden evaluados con la misma versión del
código:

| | | |
|---|---:|---|
| **Emparejado y comparado** | **95 · 36%** | verificado |
| Dudoso → revisión humana | 11 · 4% | el sistema no decide solo |
| Con llave, sin registro cargado | 35 · 13% | el portal publica con retraso |
| Sin UOC en el aviso | 126 · 47% | el organismo no tramita por COMPR.AR: **no existe registro estructurado** |

### El formato decide, y la fecha de publicación también

| Formato del aviso | Llamados | Verificados | |
|---|---:|---:|---:|
| COMPR.AR | 143 | **94** | **66%** |
| Libre | 124 | 1 | 1% |

Ese 66% esconde lo más interesante del proyecto. Partido por edición del
boletín:

| Edición | Avisos COMPR.AR | Verificados | Sin registro | Tasa |
|---|---:|---:|---:|---:|
| 01/06/2026 | 29 | 25 | 2 | 86% |
| 19/06/2026 | 24 | 19 | 0 | 79% |
| 01/07/2026 | 15 | 14 | 0 | 93% |
| 20/07/2026 | 34 | 34 | 0 | **100%** |
| **03/08/2026** | **41** | **2** | **30** | **5%** |

**El método funciona entre el 79% y el 100% en toda edición que el registro
alcanzó. Excluyendo la del 3 de agosto: 92 de 102, el 90%.** La del 3 de agosto
se derrumba porque el portal de datos abiertos tiene datos hasta julio.

Y eso convierte el retraso de publicación en un hallazgo con número propio:
**a dos meses y medio de publicada esa edición, el 73% de sus procesos todavía
no estaba cargado en el portal de datos abiertos del Estado.** No es un defecto
del proyecto: es un dato sobre la transparencia del sistema, y hay que separarlo
del 47% de organismos que simplemente no usan COMPR.AR.

La misma frontera por formato aparece en el proyecto 01, midiendo otra cosa: ahí
el techo humano de extracción era 98,7% en COMPR.AR y 72,7% en formato libre.
Dos proyectos, dos métodos, la misma grieta estructural.

### Las discrepancias

Campos que **no** participan del emparejamiento, así que una diferencia acá es
un hallazgo y no un artefacto de cómo se eligió el candidato:

| Campo | Difiere | Lectura |
|---|---:|---|
| `tipo_procedimiento` | 0 / 95 | coinciden siempre |
| `monto_estimado` | 0 / 95 | nunca difieren… porque el aviso nunca lo trae |
| **`fecha_apertura`** | **15 / 95 · 16%** | **la fecha publicada no es la del registro** |

Los quince corrimientos, en días:

```
-16, +3, +6, +8, +10, +11, +12, +14, +15, +15, +17, +18, +18, +19, +20
```

**Catorce hacia adelante y uno hacia atrás.** Mediana +14, media +11,3.

Los catorce hacia adelante son **prórrogas** que el registro refleja y el aviso
publicado no: el acto de apertura se movió y la publicación con validez jurídica
quedó vieja.

El que va hacia atrás (`53176-26`, −16 días) **es el peor de los quince para un
oferente.** El aviso se publica el 31/07 anunciando apertura el 19/08; el
registro dice que abrió el 03/08. Una prórroga te da más tiempo del que creías.
Esto te lo quita: te preparás para el 19 y el acto ya pasó. El emparejamiento es
sólido —objeto idéntico, candidato único, confianza 1,0— así que no es un error
de cruce.

**Y acá hay una lección de método que vale más que el número.** Sobre los 50
avisos del subconjunto etiquetado, los diez corrimientos iban *todos* hacia
adelante, y este README afirmaba "nunca hacia atrás". Con los 95 del corpus
completo apareció el caso contrario. **La muestra chica sostenía una afirmación
más fuerte que la que sostienen los datos completos.** Para eso sirve agrandar
la muestra, y la afirmación se corrigió en lugar de defenderse.

### La brecha de cobertura, que no es lo mismo

| Campo | El aviso lo omite y el registro lo tiene |
|---|---:|
| `monto_estimado` | **95 de 95 · 100%** |
| `fecha_apertura` | 14 de 95 · 15% |

El registro publica montos de cientos de millones de pesos que el aviso no trae.
Quien lee el Boletín no puede saber el presupuesto del llamado; quien lee el
portal de datos abiertos, sí. Son dos publicaciones del mismo Estado con
distinto nivel de transparencia, **y se reporta aparte de las discrepancias a
propósito**: mezclarlas infla el hallazgo con algo que no es un error de nadie.

---

## El agente contra la verdad de referencia humana

Acá está lo que casi ningún proyecto con modelo mide. Sobre los 115 avisos con
etiqueta manual, `src/cruzar.py` hizo el mismo emparejamiento partiendo de las
etiquetas; el agente lo hizo extrayendo por su cuenta. Comparar las dos corridas
mide **cuánto se degrada el sistema completo cuando el extractor se equivoca** —
que no es lo mismo que la precisión del extractor.

| | |
|---|---:|
| Misma decisión que con etiquetas perfectas | **114 / 115 · 99%** |
| Mismo proceso del registro elegido | **50 / 50 · 100%** |
| Mismas discrepancias de fecha detectadas | **10 / 10** |
| Falsos positivos | **0** |

**El único caso distinto es el agente escalando a revisión humana** un aviso que
las etiquetas daban por perdido: confianza 0,539 contra un umbral de 0,55. No es
una degradación, es la conducta segura — y se informa como tal en vez de
esconderse dentro del 99%.

**Por qué esta métrica y no la precisión de extracción.** La misma precisión
produce degradaciones muy distintas según en qué campo caiga el error. Un error
en `objeto` baja la confianza y el caso sigue; un error en
`numero_procedimiento` rompe la llave y tira el caso entero. Eso no lo mide
ningún eval de extracción, y es lo único que le importa a quien opera el
sistema.

### Costo de operarlo

Sobre los 267 llamados:

| | |
|---|---:|
| Costo total | **USD 0,1970** |
| Costo por aviso | **USD 0,000738** |
| Costo por 1.000 avisos | USD 0,74 |
| Tokens | 205.590 entrada · 54.147 salida |
| Latencia mediana / p95 | 3,3 s / 4,3 s |
| **Fallas de extracción** | **0 de 267** |

Contra la línea de base humana medida en el proyecto 01 —113 s y USD 0,058 por
documento, con el costo humano anclado al salario mínimo legal—: **28× más
rápido y 79× más barato.** El modelo (`gemini-3.5-flash-lite`) no se eligió acá:
es la conclusión medida del proyecto 01, donde el modelo cinco veces más caro no
justificó su precio.

Las cero fallas en 267 llamadas no son suerte: el cupo gratuito de Google son 15
llamadas por minuto y la corrida lo tocó varias veces. Los reintentos con espera
exponencial sobre errores transitorios recuperaron todas.

---

## Lo que esto le enseñó al proyecto 01

**El modelo encontró un error en el set de oro etiquetado a mano.** El aviso
`44538-26` estaba etiquetado con apertura `3/07/2026`; el texto dice
`13/07/2026`. Un typo. Eso hacía que el análisis reportara una prórroga de +10
días que no existía.

Encontrado uno, hay que preguntarse cuántos más hay. Los avisos emparejados se
auditaron con un lector determinista del bloque `Acto de Apertura` —ninguna
llamada a modelo, costo cero—:

| | |
|---|---:|
| Con bloque legible | 29 |
| Etiquetas mal | **1** |
| Extracciones del modelo mal | **0 de 29** |
| Sin bloque (formato libre): no auditables | 21 |

La corrección está registrada en
[`docs/CORRECCIONES.md`](https://github.com/enzoestevez/eval-extraccion-licitaciones/blob/main/docs/CORRECCIONES.md)
del proyecto 01, con la regla explícita: **una etiqueta se corrige sólo si el
texto del documento la contradice, nunca porque un modelo diga otra cosa.** El
modelo no es la fuente de verdad; lo que puede hacer, y acá hizo, es señalar
dónde mirar.

**El techo de 85,7% del proyecto 01 no se corrigió.** Ese número mide
consistencia humana, y este typo es justamente una de las inconsistencias que el
doble ciego existía para detectar. Sacarlo sería hacer trampa con la medición: el
techo es bajo, en parte, precisamente porque un humano cansado escribe `3/07`
donde dice `13/07`.

---

## Cómo se encontraron seis bugs sin gastar una llamada

La primera corrida reportó **cero discrepancias** y `fecha_apertura` "omitida por
el Boletín" en el **100%** de los casos emparejados.

Un número demasiado limpio no es un hallazgo, es una pista. **Cero discrepancias
no era "no encontré nada": era "no comparé nada".** Tirando de ese hilo
aparecieron seis bugs, los seis en el código propio y ninguno en el modelo:

| | Bug | Efecto |
|---|---|---|
| 1 | `n_fecha` no parseaba `2026-06-08T09:00:00` (con segundos) | el campo del hallazgo central quedaba en `None`. **El modelo había extraído la fecha bien en 98 de 115** |
| 2 | `llave()` exigía `NN/AAAA` y rechazaba `38/12-0197-LPU26` | el modelo contestaba **bien** y devolvía **más** información que la pedida |
| 3 | `n_uoc` conservaba `UOC: 392/000` como `392/0` | de las 128.951 UOC del registro, **cero** tienen un segmento todo ceros: conservarlo garantizaba no emparejar nunca |
| 4 | `RX_UOC_TEXTO` exigía los dos puntos y no veía `UOC 118-00` | confundir "no tiene UOC" con "no la supe leer" se contaba como hallazgo sobre el Estado, y era un bug propio |
| 5 | `n_monto` leía `2.797` como 2,8 | en castellano el punto separa miles |
| 6 | `tipo_procedimiento` comparaba vocabularios distintos | el registro usa una lista cerrada de 6 valores, el Boletín escribe texto libre: `Subasta Pública` contra `Subasta` se reportaba como discrepancia |

**Resultado de los seis arreglos, sobre los 115 etiquetados:**

| | antes | después |
|---|---:|---:|
| Verificable | 39 / 115 · 34% | **50 / 115 · 43%** |
| "El registro no lo cargó" | 12 | **3** |
| `fecha_apertura` difiere | 7 · 18% | **10 · 20%** |
| Falsos positivos | 2 | **0** |

Lo que yo contaba como "el Estado no cargó el proceso" era, en nueve casos, mi
código no sabiendo leer una UOC.

### El diseño que hizo esto gratis

Un pipeline con modelo tiene dos mitades con propiedades opuestas:

```
la llamada al modelo   cara · lenta · no determinista · con cupo por minuto
todo lo que sigue      gratis · instantánea · determinista
```

La traza guarda el campo `extraido`: exactamente lo que el modelo devolvió en
cada caso. `src/reprocesar.py` vuelve a correr la mitad determinista sobre esas
extracciones, con el código actual. **Los seis arreglos se verificaron a USD 0,00
cada uno**, cuando volver a correr el agente completo costaba USD 0,20 y media
hora por intento.

Por eso `procesar()` está partido en `extraer()` y `decidir()`: **la frontera
entre lo caro y lo reproducible está en una sola línea, a propósito.**

Y resolvió un problema que no habíamos previsto: los primeros 115 casos se
corrieron con la lógica vieja y los 152 restantes con la arreglada. Informar
sobre esa traza habría mezclado dos versiones del código en un mismo número —
la clase de error que nadie detecta hasta que alguien lo compara en una
entrevista. `reprocesar.py` dejó los 267 evaluados con la misma versión, sin
pagar una llamada.

`reprocesar.py` **no toca** `reports/traza.jsonl`. Esa es la traza de lo que el
agente hizo —un log de auditoría— y reescribirla para que diga otra cosa es
exactamente lo que un log de auditoría no debe permitir. El reproceso va a un
archivo nuevo y anota con qué commit y qué umbral se corrió.

---

## Arquitectura

```
aviso del Boletín (texto)
   │
   ├─ src/agente.py ── extraer() ──► modelo ──► 9 campos + confianza
   │       │                          └─ reintentos sobre 429/503/timeout
   │       │                          └─ tope de gasto ANTES de la llamada
   │       │                          └─ corte en seco si fallan 3 seguidos
   │       │
   │       └─ decidir() ─── la mitad determinista, reproducible gratis
   │             │
   │             ├─ llave:  UOC + numero + año  ->  84/129-0362-LPU26
   │             │     acepta también el número completo del registro
   │             │
   │             ├─ candidatos (la llave NO es única:
   │             │   111.452 llaves para 128.951 convocatorias)
   │             │
   │             ├─ CONFIANZA ¿es el mismo proceso?
   │             │     objeto 0,55 · cronología 0,30 · unicidad 0,15
   │             │     < 0,55 -> revisión humana, no se compara nada
   │             │
   │             └─ COMPARACIÓN sólo de campos no usados para emparejar
   │                   coincide | difiere | omitido por el Boletín | no comparable
   │
   ├─ reports/traza.jsonl       log de auditoría, append-only, con `extraido`
   ├─ reports/auditoria.jsonl   una línea por decisión
   │
   ├─ src/reprocesar.py ──► traza-reproceso.jsonl   (USD 0,00)
   └─ src/informe.py ─────► reports/agente.md

src/comun.py es el núcleo compartido: normalizadores, índice del registro,
llave, confianza y comparación. El análisis (cruzar.py) y el sistema
(agente.py) usan EXACTAMENTE la misma lógica — cero funciones duplicadas.
Si cada uno tuviera su copia, sus números divergirían con el primer cambio y
nadie se daría cuenta hasta que alguien los comparara.
```

## Cómo correrlo

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
echo "GOOGLE_API_KEY=..." > .env

python src/verificar_cruce.py data/registro/convocatorias.csv data/entrada/etiquetas_p01.jsonl
python src/cruzar.py                           # el análisis: el oráculo
python src/agente.py                           # el sistema, sobre los 267
python src/reprocesar.py                       # recalcula sin llamar al modelo
python src/informe.py --traza reports/traza-reproceso.jsonl
```

## De dónde salen los datos

Ver [`docs/PROCEDENCIA.md`](docs/PROCEDENCIA.md). Los avisos y el set etiquetado
vienen del [proyecto 01](https://github.com/enzoestevez/eval-extraccion-licitaciones);
el registro oficial, de [datos.gob.ar](https://datos.gob.ar/dataset?tags=Contrataciones).

---

## Lo que no resuelve

- **El 47% de los avisos no tiene contraparte.** Universidades, BCRA, Banco
  Nación, Ministerio Público y banca multilateral publican en el Boletín pero no
  tramitan por COMPR.AR: **para casi la mitad de los llamados no hay nada contra
  qué verificar**, y es justo donde la extracción importa más.
- **El 13% tiene llave pero el registro no cargó el proceso**, y está
  concentrado en una sola edición (30 de 35 son del 3/8). Eso hace que el 36%
  global subestime lo que el método puede hacer y a la vez mida algo real sobre
  el portal. Los dos números se informan separados y ninguno reemplaza al otro.
- **Los avisos de formato libre entre los emparejados no se pudieron auditar
  contra el texto**: no tienen un bloque `Acto de Apertura` legible por regla
  determinista. Declarado, no resuelto.
- **El corpus son 267 llamados de 5 ediciones de 2026.** Suficiente para medir
  degradación y cobertura por formato, corto para afirmar una tasa nacional. El
  16% de discrepancias es un orden de magnitud, no una cifra.
- **La asimetría de dirección es el resultado más frágil.** Con 50 casos daba
  10 de 10 hacia adelante; con 95 dio 14 de 15. La tendencia a prórroga se
  sostiene, el "nunca hacia atrás" no.
- **La confianza de emparejamiento usa `fecha_apertura` del registro contra la
  fecha de publicación del aviso**, y después se reporta `fecha_apertura` como
  hallazgo. Son cantidades distintas —nunca se toca la apertura extraída— así
  que hay acoplamiento débil, no circularidad. Queda declarado en lugar de
  escondido.

## Decisiones que tomé y por qué

- **El contrato de datos se verifica primero.** El cruce no está garantizado por
  ningún estándar: medirlo cuesta una hora, construir sobre un supuesto cuesta
  una semana.
- **La entrada se copia, no se referencia.** Un repo que necesita una carpeta
  hermana no versionada no se puede clonar ni reproducir. La copia va con su
  procedencia y su fecha.
- **El agente decide si mira el mismo proceso antes de comparar campos.** En
  `36208-26` el aviso dice licitación pública de lácteos y el registro dice
  licitación privada de materiales de mantenimiento, con apertura **anterior** a
  la publicación del aviso. Eso no es una discrepancia, es un emparejamiento
  equivocado. Comparar sin una confianza previa **inventa hallazgos**, y un
  sistema que inventa hallazgos es peor que uno que no encuentra ninguno. Esta
  decisión salió de los datos de la verificación, no de un diseño previo.
- **Un campo usado para emparejar no se puede reportar como hallazgo.** La
  primera versión usaba `tipo_procedimiento` en el puntaje de confianza y
  después reportaba 0% de discrepancia en tipo. Era circular por construcción.
  Está fuera de los pesos, y el código marca cada campo como `reportable` o no.
- **El monto no se cuenta como discrepancia cuando el aviso no lo trae**, y un
  monto en otra moneda no se compara en absoluto: `USD 2.797` contra `2797,00`
  del registro parecen la misma cifra y no lo son. Ese caso se marca
  `no_comparable` en vez de elegir una de las dos interpretaciones.
- **Un número sospechosamente limpio se investiga antes de reportarlo.** Cero
  discrepancias sobre 36 casos era un bug propio, no un hallazgo. Es la decisión
  de método que más valor produjo en todo el proyecto.
- **La cobertura se parte por edición antes de reportar un promedio.** El 66% de
  los avisos COMPR.AR esconde cuatro ediciones entre 79% y 100% y una en 5%.
  Promediar eso habría ocultado tanto la capacidad del método como el retraso
  del portal.
- **El modelo no se eligió acá.** `gemini-3.5-flash-lite` es la conclusión
  medida del proyecto 01. Y la versión está fijada en `requirements.txt`: una
  corrida de benchmark no se compara contra un `latest` que cambia abajo de los
  pies.
- **Los errores que afectan a todos los casos no se registran por caso.** La
  primera corrida escribió el mismo error cinco veces por un paquete que
  faltaba. Ahora el control previo chequea clave y paquete una vez antes del
  bucle, y el corte en seco aborta si fallan tres seguidos sin ningún éxito.
