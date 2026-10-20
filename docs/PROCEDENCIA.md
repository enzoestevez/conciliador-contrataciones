# Procedencia de los datos de entrada

Todo lo que está en `data/` vino de algún lado y tiene fecha. Sin esto el
proyecto no se puede reproducir ni auditar.

## `data/entrada/` — del proyecto 01

| Archivo | Qué es | Origen | Tomado el |
|---|---|---|---|
| `etiquetas_p01.jsonl` | 115 avisos etiquetados a mano contra un protocolo escrito | [eval-extraccion-licitaciones](https://github.com/enzoestevez/eval-extraccion-licitaciones) | 20/10/2026 |
| `indice_p01.json` | Metadatos de los 296 avisos: rubro, tipo, formato, ediciones | mismo repo | 20/10/2026 |
| `avisos/*.txt` | Un archivo por aviso, cortado del boletín diario | mismo repo | 20/10/2026 |

Los avisos salen de 5 ediciones de la Tercera Sección del Boletín Oficial de la
República Argentina: **1/6, 19/6, 1/7, 20/7 y 3/8 de 2026**. Fechas espaciadas a
propósito: los avisos se republican varios días seguidos, y con ediciones
consecutivas el 38% del corpus eran duplicados.

**Por qué se copian en vez de leerlos de la carpeta de al lado.** Un repo que
necesita otra carpeta no versionada no se puede clonar y reproducir. Copiarlos
con su procedencia escrita cuesta nada y hace que este repo se verifique solo.

## `data/registro/` — del Estado

Registro oficial de contrataciones, descargado de
[datos.gob.ar](https://datos.gob.ar/dataset?tags=Contrataciones).

| Dataset | Organismo | Última modificación |
|---|---|---|
| Sistema de Contrataciones Electrónicas | Oficina Nacional de Contrataciones (JGM) | 20/10/2026 |

No se versiona: es pesado, es público y se vuelve a bajar. Lo que sí se versiona
es el resultado del cruce.

**Completar al bajarlo:** nombre exacto del recurso, URL, fecha de descarga,
filas y columnas.
