# Agente conciliador de contrataciones públicas

> **Estado:** contrato de datos verificado · construyendo el agente
>
> **El número:** `COMPLETAR` discrepancias encontradas entre lo que el Estado
> publicó en el Boletín Oficial y lo que figura en su propio registro oficial,
> sobre `COMPLETAR` procesos cruzados. `COMPLETAR`% se resuelve solo;
> el resto escala con la discrepancia señalada. `COMPLETAR` USD por caso contra
> `COMPLETAR` USD de la revisión manual.

---

## El problema

El Estado argentino publica la misma contratación dos veces: como aviso en el
Boletín Oficial, redactado por el organismo, y como registro estructurado en
el portal de datos abiertos. Nadie verifica que digan lo mismo.

Un proveedor que se guía por el aviso y una auditoría que se guía por el
registro pueden estar mirando dos versiones distintas del mismo llamado.

## Qué hace

Un agente que, por cada aviso:

1. **Extrae** los campos del texto del aviso.
2. **Busca** el registro oficial correspondiente.
3. **Compara** campo por campo sobre valores normalizados.
4. **Decide**: si coinciden, aprueba y registra. Si no, escala señalando la
   discrepancia exacta y adjuntando las dos versiones.

Con traza de cada paso y cada llamada a herramienta, permisos acotados, tope de
gasto y un tablero de métricas operativas.

## La verdad de referencia no la genera un modelo

El registro oficial del Estado es la vara. Es público, está a escala y existe
independientemente de este proyecto. No hay etiquetado manual: eso es
deliberado, porque una verdad de referencia producida por un modelo sólo mide
el acuerdo entre dos modelos.

## El contrato de datos se verifica antes de construir

El estándar OCDS, que usa el portal argentino, **no define un campo de
expediente**: su identificador es `convocatoria_id`. El Boletín publica
`expediente` y `numero_procedimiento`. Que los dos lados se puedan unir es una
hipótesis, no un hecho.

`src/verificar_cruce.py` la pone a prueba antes de escribir una línea del
agente. Descubre el esquema del CSV solo, detecta columnas candidatas a llave
por la **forma** de sus valores y no por su nombre, prueba cada cruce y reporta
la tasa de coincidencia.

**El criterio de decisión quedó escrito antes de correr el script**, para que no
se pudiera mover el poste después de ver el resultado:

| Tasa de cruce | Decisión |
|---|---|
| ≥ 60% | el proyecto va |
| 30–60% | va, declarando la cobertura |
| < 30% | no hay cruce → plan B |

**Resultado (20/10/2026):**

```
39 / 51  = 76%   de los avisos que tramitan por COMPR.AR encuentran su registro
39 / 115 = 34%   del total etiquetado         -> el proyecto va, con cobertura declarada
 0 / 57  =  0%   del formato libre
```

El cruce se construye desde el aviso: `UOC` + `numero_procedimiento` + año
forman la llave `84/129-0362-LPU26`, que es el `Numero_Proceso` del registro.

**Un instrumento sin validar da un veredicto falso.** El primer cruce dio 9% y
casi descartamos el proyecto. El error era del verificador, no de los datos: el
formato dominante de `Numero_Proceso` es `340/1-0006-LPR17` —la UOC lleva
barra— y la expresión regular sólo aceptaba la forma sin barra, descartando el
59% de las 128.951 convocatorias. Corregido, el mismo cruce pasó de 9% a 34%.

**Plan B, diseñado de antemano.** El Boletín publica prórrogas, circulares
modificatorias y rectificaciones que referencian avisos anteriores: el corpus se
corrige a sí mismo y la edición posterior es la verdad. El agente pasaría a
mantener el estado vigente de cada proceso en el tiempo, sin cruces externos.

## Arquitectura

```
COMPLETAR cuando el cruce esté confirmado
```

## De dónde salen los datos

Ver [`docs/PROCEDENCIA.md`](docs/PROCEDENCIA.md). Resumen: los avisos y el set
etiquetado vienen del [proyecto 01](https://github.com/enzoestevez/eval-extraccion-licitaciones);
el registro oficial, de [datos.gob.ar](https://datos.gob.ar/dataset?tags=Contrataciones).

## Lo que no resuelve

- **El formato libre no tiene registro estructurado.** Universidades, BCRA,
  Banco Nación, Ministerio Público y banca multilateral publican en el Boletín
  pero no tramitan por COMPR.AR: **la mitad de los llamados publicados no tiene
  contraparte legible por máquina**. Para esos avisos no hay nada contra qué
  verificar, y es justo donde la extracción importa más.
- **El registro oficial llega hasta julio de 2026.** La edición del 3/8 del
  corpus no tiene contraparte cargada. El recurso declara última modificación el
  3/8/2026 y contiene datos hasta julio: el portal publica con retraso, y ese
  retraso es un hallazgo con nombre propio, no un defecto del proyecto.
- **Los datos de 2026 están incompletos.** 6.020 convocatorias cargadas contra
  ~15.000 por año en los ejercicios anteriores. Varias UOC tienen dos o tres
  procesos publicados cuando sus avisos referencian números de tres cifras.
- `COMPLETAR`

## Decisiones que tomé y por qué

- **El contrato de datos se verifica primero.** El cruce entre el Boletín y el
  registro oficial no está garantizado por ningún estándar, así que medirlo
  cuesta una hora y construir sobre un supuesto cuesta una semana.
- **La entrada se copia, no se referencia.** Un repo que necesita una carpeta
  hermana no versionada no se puede clonar ni reproducir. La copia va con su
  procedencia y su fecha.
- **El agente decide si mira el mismo proceso antes de comparar campos.** El
  cruce produce falsos positivos: en `36208-26` el aviso dice licitación pública
  de lácteos y el registro dice licitación privada de materiales de
  mantenimiento, con fecha de apertura anterior a la publicación del aviso. Eso
  no es una discrepancia, es un emparejamiento equivocado. Comparar campos sin
  una confianza de emparejamiento previa produce discrepancias inventadas.
  **Esta decisión salió de los datos de la verificación, no de un diseño previo.**
- **El monto no se cuenta como discrepancia cuando el aviso no lo trae.** Cero
  de 39 pares coinciden en `monto_estimado`, pero el motivo es que el aviso casi
  nunca lo publica y el registro siempre lo tiene: hay montos de 370 y 420
  millones de pesos ausentes del aviso publicado. Es una brecha de cobertura
  entre dos publicaciones del mismo Estado, y se reporta aparte.
- `COMPLETAR`
