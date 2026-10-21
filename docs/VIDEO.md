# Video de 90 segundos

Guion para grabar en pantalla. **Sin música, sin intro animada, sin decir "hola
soy Enzo y hoy les traigo".** Quien mira esto tiene 90 segundos y quiere saber
si sabés medir.

Grabar con la terminal y el repo a la vista. Hablado, no leído.

---

## 0:00 – 0:15 · El problema, en una frase

> "El Estado argentino publica cada licitación dos veces: como aviso en el
> Boletín Oficial y como registro estructurado en el portal de datos abiertos.
> Nadie verifica que digan lo mismo. Construí un agente que lo verifica."

**En pantalla:** el aviso del Boletín a la izquierda, la fila del registro a la
derecha, con la fecha de apertura distinta resaltada.

## 0:15 – 0:35 · El número, y el que no esperaban

> "De 115 avisos, sólo 50 se pueden verificar: el 43%. La mitad de los
> organismos no tramita por el sistema central, así que no hay nada contra qué
> comparar. Y de los 50 que sí: **uno de cada cinco publica una fecha de
> apertura que el registro oficial ya movió.** Diez casos, todos hacia
> adelante, hasta 41 días. Son prórrogas que un sistema del Estado refleja y el
> otro no."

**En pantalla:** `python src/cruzar.py` corriendo, y la tabla de los diez
corrimientos.

## 0:35 – 0:55 · Por qué le pueden creer

> "La vara no la generó un modelo. El registro oficial es la vara del hallazgo,
> y un set de 115 avisos que etiqueté a mano en mi proyecto anterior es la vara
> del sistema. Comparando las dos corridas: el agente toma la misma decisión
> que con etiquetas perfectas en 114 de 115 casos, elige el mismo proceso del
> registro en 50 de 50, y encuentra las mismas diez discrepancias sin un solo
> falso positivo. Cuesta siete diezmilésimas de dólar por aviso."

**En pantalla:** la tabla de evaluación de punta a punta del README.

## 0:55 – 1:20 · Lo que de verdad hay que contar

> "Pero el número que importa es otro. La primera corrida me dio **cero
> discrepancias**. Me pareció demasiado limpio, y lo fui a mirar: no era que no
> encontrara nada, era que **no comparaba nada**. Mi normalizador de fechas no
> leía el formato con segundos que devolvía el modelo. El modelo había
> extraído la fecha bien en 98 de 115 casos; el bug era mío.
>
> Tirando de ese hilo encontré seis bugs, los seis míos. La cobertura pasó del
> 34% al 43% y los falsos positivos de dos a cero. Y ninguno costó una llamada
> nueva: la traza guarda la extracción cruda, así que la mitad determinista del
> pipeline se vuelve a correr gratis. Seis arreglos verificados a cero dólares."

**En pantalla:** `python src/reprocesar.py` corriendo, con el
`costo del reproceso: USD 0.00` al final.

## 1:20 – 1:30 · El cierre

> "Y el modelo encontró un error en mi propio set de oro: yo había tipeado 3 de
> julio donde el aviso dice 13. Lo corregí con la regla escrita de que una
> etiqueta se corrige sólo si el **texto** la contradice, nunca porque un modelo
> diga otra cosa. Está en un commit con fecha. El repo está acá."

**En pantalla:** `docs/CORRECCIONES.md` del proyecto 01, y el link del repo.

---

## Lo que NO va en el video

- Decir "inteligencia artificial" más de una vez.
- Mostrar código línea por línea. Nadie lo lee en un video.
- Esconder el 54% que no se puede verificar. **Es la mitad del hallazgo**, y
  decirlo es lo que separa una medición de un folleto.
- Prometer que esto está en producción. No lo está, y el estado del README dice
  `completado · validado contra verdad de referencia humana`, que es verdad.

## Si hay que recortar a 60 segundos

Se corta la sección 0:35–0:55 (la validación contra el oráculo) y se deja en
una frase dentro del cierre. **Lo que nunca se corta es 0:55–1:20**: el bug
propio encontrado por sospechar de un número limpio es lo único que no se puede
fingir, y es lo que están buscando.
