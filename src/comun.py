"""Nucleo compartido: normalizadores, indice del registro, llave y confianza.

Esto existe para que `cruzar.py` (el analisis) y `agente.py` (el sistema) usen
EXACTAMENTE la misma logica. Si cada uno tuviera su copia, los numeros del
agente y los del analisis divergirian con el primer cambio, y nadie se daria
cuenta hasta que alguien los compare en una entrevista.

Contenido:
    n_texto, n_monto, n_fecha, n_uoc, palabras   normalizadores por tipo
    cargar_registro()                            indice del CSV de COMPR.AR
    llave()                                      UOC + numero + año
    confianza()                                  ¿es el mismo proceso?
    comparar()                                   campo por campo, ya emparejado
    COMPARABLES                                  que se puede reportar y que no
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "data" / "registro"

UMBRAL = 0.55

# SEÑALES DE EMPAREJAMIENTO. Deciden si es el mismo proceso.
# Un campo usado para emparejar NO puede reportarse despues como hallazgo: si se
# elige al candidato que mejor coincide en un campo, ese campo va a coincidir por
# construccion. La primera version de cruzar.py usaba `tipo_procedimiento` en el
# puntaje y despues reportaba 0% de discrepancia en tipo. Era circular.
PESOS = {"objeto": 0.55, "cronologia": 0.30, "unicidad": 0.15}

# CAMPOS COMPARABLES. No participan del emparejamiento, asi que una diferencia
# aca es un hallazgo real.
#
# `fecha_apertura` entra con una aclaracion: la señal de cronologia usa la
# apertura DEL REGISTRO contra la fecha de PUBLICACION del aviso, y nunca toca la
# apertura extraida. Son cantidades distintas: hay acoplamiento debil, no
# circularidad, y queda declarado.
COMPARABLES = ("tipo_procedimiento", "fecha_apertura", "monto_estimado")


# --------------------------------------------------------------- normalizadores


def _sin_tildes(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def n_texto(v) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", _sin_tildes(v).lower()).strip(" .,;:-")
    return s or None


def n_uoc(v) -> str:
    """84/077 y 84/77 son la misma UOC.

    Descarta los segmentos no numericos. El modelo a veces arrastra texto del
    aviso —`47/Dpto` en vez de `47`— y eso rompia la llave y perdia el caso.
    Descartarlo no es adivinar: en las 128.951 filas del registro, los segmentos
    de UOC son numericos en el 100% de los casos (medido, ver docs/). Un
    segmento no numerico no puede corresponder a ninguna UOC real.

    Si no queda ningun segmento numerico se devuelve el valor normalizado tal
    cual, para que falle el emparejamiento en vez de emparejar con algo raro.
    """
    partes = [x.strip() for x in re.split(r"[/\-]", str(v).strip()) if x.strip()]
    numericos = [x for x in partes if x.isdigit()]

    # Un segmento TODO ceros es una subunidad que el registro no usa: el Boletin
    # escribe `UOC: 392/000` donde el registro escribe `392`. Medido: de las
    # 128.951 UOC del registro, CERO tienen un segmento todo ceros, asi que
    # conservarlo garantiza no emparejar nunca. Se descarta por la derecha y
    # siempre queda al menos un segmento.
    while len(numericos) > 1 and numericos[-1].strip("0") == "":
        numericos.pop()

    if numericos:
        return "/".join(x.lstrip("0") or "0" for x in numericos)
    return "/".join(x.lstrip("0") or "0" for x in partes) or str(v).strip()


# Monedas distintas del peso que el Boletin declara explicitamente. Un monto en
# otra moneda NO es comparable contra la cifra del registro, y tratarlo como
# numero INVENTA una discrepancia: `USD 2.797` contra `2797.00` del registro
# parecen la misma cifra y no lo son.
RX_OTRA_MONEDA = re.compile(r"\b(usd|u\$s|u\$d|dolar|dólar|euro|eur)\b", re.I)


def n_monto(v) -> float | None:
    """El registro escribe 1,735,400.00 (coma de miles). El aviso, 1.735.400,00.

    Regla argentina: la coma es decimal y el punto separa miles. La version
    anterior aplicaba eso solo cuando habia coma; con un punto solo lo tomaba
    siempre como decimal, y leyo `2.797` como 2,8 en vez de 2797. Ahora un punto
    seguido de EXACTAMENTE tres digitos finales se trata como separador de miles,
    que es como se escribe en castellano.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)

    if RX_OTRA_MONEDA.search(str(v)):
        return None  # ver `comparar()`: queda como no_comparable, no como cero

    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    elif "." in s and len(s.rsplit(".", 1)[-1]) == 3:
        s = s.replace(".", "")  # 2.797 y 1.735.400 son miles, no decimales
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def n_fecha(v) -> str | None:
    """Solo la FECHA, sin hora, venga como venga.

    La version anterior listaba formatos completos, uno de ellos
    `%Y-%m-%dT%H:%M`, sin segundos. El modelo devolvio `2026-06-08T09:00:00`,
    strptime fallo con los cuatro formatos y la funcion devolvio None. Resultado:
    `fecha_apertura` quedo "omitida por el Boletin" en el 100% de los casos
    emparejados y las discrepancias bajaron a CERO — justo el hallazgo central
    del proyecto. Cero discrepancias no era "no encontre nada": era "no compare
    nada".

    El set etiquetado a mano NO tiene segundos, asi que `cruzar.py` nunca toco el
    bug: se expone solo cuando el extractor es un modelo. Un test contra los
    datos perfectos lo habria dado por bueno.

    (Y es el mismo bug que el proyecto 01 ya habia arreglado en su
    `normalizar.py`. Compartir el normalizador entre el analisis y el agente no
    alcanzo: tambien hay que compartirlo entre proyectos.)

    Ahora la hora se descarta ANTES de parsear, en vez de enumerar formatos de
    hora que siempre van a quedar incompletos: se corta en el primer espacio o
    en la T, y lo que queda tiene que ser una fecha.
    """
    if not v:
        return None
    crudo = re.split(r"[ T]", str(v).strip())[0].strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(crudo, f).date().isoformat()
        except ValueError:
            continue
    return None


def palabras(s) -> set[str]:
    """Palabras de 4+ letras. Saca articulos y preposiciones sin lista negra."""
    return set(re.findall(r"[a-z0-9]{4,}", str(s))) if s else set()


# --------------------------------------------------------------- registro

RX_PROCESO = re.compile(r"^(.+?)-(\d+)-([A-Z]+)(\d{2})$")
# El Boletin escribe la UOC de varias formas y los dos puntos NO son fijos:
#   `UOC: 84/129`   `UOC 118-00`   `UOC:392/000`
# La version anterior exigia los dos puntos y perdia el caso entero: el aviso
# quedaba como "no tramita por COMPR.AR" cuando en realidad si declaraba su UOC.
# Confundir "no tiene" con "no lo supe leer" es el peor error de los dos, porque
# se cuenta como un hallazgo sobre el Estado y es un bug propio.
RX_UOC_TEXTO = re.compile(r"\bUOC\s*:?\s*(\d+(?:[/\-]\d+)*)", re.I)
RX_NUMERO = re.compile(r"^\s*0*(\d+)\s*/\s*(\d{2,4})\s*$")


def cargar_registro(verboso: bool = True) -> dict[tuple, list[dict]]:
    """Indice del registro de COMPR.AR por (UOC, numero, año de dos digitos).

    Ojo: la llave NO es unica. El mismo UOC + numero + año puede existir como
    licitacion publica y como privada (`84/12-0325-LPU26` y `...-LPR26`), porque
    el codigo de tipo queda fuera de la llave: el aviso no siempre lo declara de
    forma que se pueda mapear. Son 111.452 llaves para 128.951 convocatorias.
    Por eso elegir entre candidatos es parte del problema, no un detalle.
    """
    archivos = sorted(REGISTRO.glob("*onvocatorias*.csv"))
    if not archivos:
        sys.exit(f"No encontré el CSV de convocatorias en {REGISTRO}")

    idx: dict[tuple, list[dict]] = {}
    leidas = indexadas = 0
    for ruta in archivos:
        with ruta.open(encoding="utf-8", errors="replace") as f:
            for fila in csv.DictReader(f):
                leidas += 1
                m = RX_PROCESO.match((fila.get("Numero_Proceso") or "").strip())
                if not m:
                    continue
                indexadas += 1
                uoc, num, _tipo, aa = m.groups()
                idx.setdefault((n_uoc(uoc), num.lstrip("0") or "0", aa), []).append(fila)

    if verboso:
        print(f"registro: {leidas:,} convocatorias leídas · {indexadas:,} indexadas "
              f"({indexadas/leidas:.0%}) · {len(idx):,} llaves")
        if indexadas / leidas < 0.95:
            print("  ! Se descarta más del 5%. Revisá RX_PROCESO antes de confiar en el resultado.")
    return idx


def llave(uoc, numero_procedimiento) -> tuple | None:
    """(UOC, numero, año) desde los valores extraidos. None si no se puede armar.

    Acepta DOS formas, porque el aviso usa las dos y el extractor devuelve la
    que ve:

        0197/2026            el numero del aviso -> necesita la UOC aparte
        38/12-0197-LPU26     el numero completo del registro -> ya la trae

    La segunda se rechazaba por no tener la forma `NN/AAAA`, y asi se perdian
    casos donde el modelo habia contestado BIEN: devolvio mas informacion que la
    pedida, no menos. Dos de los tres casos verificables que el agente perdio en
    la primera corrida eran exactamente esto.

    La leccion es de diseño, no de prompt: cuando la salida de un modelo entra a
    una funcion, conviene aceptar las formas validas que el modelo puede elegir,
    en vez de exigir la unica que uno tenia en la cabeza al escribir el regex.
    Apretar el prompt tambien servia, pero cuesta una corrida entera verificarlo
    y esto cuesta cero.
    """
    s = str(numero_procedimiento or "").strip()

    # Forma completa: la UOC viene adentro y manda sobre el parametro `uoc`,
    # porque es el identificador que usa el registro.
    m = RX_PROCESO.match(s)
    if m:
        u, num, _tipo, aa = m.groups()
        return (n_uoc(u), num.lstrip("0") or "0", aa)

    if not uoc:
        return None
    m = RX_NUMERO.match(s)
    if not m:
        return None
    return (n_uoc(uoc), m.group(1), m.group(2)[-2:])


def uoc_del_texto(texto: str) -> str | None:
    """La UOC tal como la declara el aviso. Fuente de verdad para la llave."""
    m = RX_UOC_TEXTO.search(texto)
    return m.group(1) if m else None


# --------------------------------------------------------------- confianza


def confianza(datos: dict, fila: dict, n_candidatos: int, publicado_desde) -> tuple[float, dict]:
    """¿Este candidato es el mismo proceso que el aviso?

    Tres señales independientes, ninguna suficiente sola. El puntaje se
    renormaliza por los pesos de las señales disponibles, asi que un aviso al
    que le falta una señal no queda penalizado por esa ausencia.
    """
    señales: dict[str, float | None] = {}

    # El objeto es texto libre que dos sistemas distintos escribieron para la
    # misma compra: la señal mas fuerte que hay.
    pa = palabras(n_texto(datos.get("objeto")))
    pr = palabras(n_texto(fila.get("Objeto_del_Proceso"))) | palabras(n_texto(fila.get("Nombre_del_Proceso")))
    señales["objeto"] = len(pa & pr) / len(pa) if pa and pr else None

    # Un llamado no se abre antes de anunciarse. Esta señal atrapo el caso
    # 36208-26, donde la llave emparejaba con un proceso de abril y el aviso
    # se habia publicado en junio.
    pub = n_fecha(publicado_desde)
    ap = n_fecha(fila.get("Fecha_de_Apertura"))
    if pub and ap:
        señales["cronologia"] = 1.0 if ap >= pub else 0.0

    # Una llave que devuelve un solo candidato vale mas que una que devuelve cinco.
    señales["unicidad"] = 1.0 if n_candidatos == 1 else max(0.0, 1.0 - 0.3 * (n_candidatos - 1))

    usadas = {k: v for k, v in señales.items() if v is not None}
    peso = sum(PESOS[k] for k in usadas) or 1.0
    return round(sum(v * PESOS[k] for k, v in usadas.items()) / peso, 3), señales


def elegir(datos: dict, candidatos: list[dict], publicado_desde) -> tuple[dict, float, dict]:
    """El mejor candidato con su confianza. Asume candidatos no vacio."""
    puntuados = [(confianza(datos, f, len(candidatos), publicado_desde), f) for f in candidatos]
    (conf, señales), fila = max(puntuados, key=lambda t: t[0][0])
    return fila, conf, señales


# --------------------------------------------------------------- comparacion

# VOCABULARIO DEL REGISTRO. Lista cerrada, contada sobre las 128.951 filas:
#   Contratacion Directa 61.248 · Licitacion Privada 45.446 · Licitacion Publica
#   20.292 · Subasta 1.097 · Concurso Privado 425 · Concurso Publico 340
# El Boletin, en cambio, escribe texto libre: `Subasta Publica`, `Licitacion de
# Obra Publica`, `Concurso Privado BCYL0100-2026`. Que los dos sistemas le pongan
# nombres distintos a la misma figura legal es una diferencia de VOCABULARIO, no
# una diferencia en los datos, y reportarla como discrepancia es un falso
# positivo. El mapa va del vocabulario abierto al cerrado, nunca al revés.
CANONICO = {
    "subasta publica": "subasta",
    "licitacion de obra publica": "licitacion publica",
    "licitacion en curso": None,          # no dice de que tipo: no comparable
}


def n_tipo(v) -> str | None:
    """Tipo de procedimiento llevado al vocabulario del registro.

    Solo colapsa sinonimos declarados arriba y recorta la basura pegada al
    nombre (`Concurso Privado BCYL0100-2026` -> `concurso privado`). Nunca
    convierte una figura en otra: publica y privada siguen siendo distintas,
    porque esa diferencia SI es un hallazgo.
    """
    t = n_texto(v)
    if t is None:
        return None
    if t in CANONICO:
        return CANONICO[t]
    for base in ("contratacion directa", "licitacion privada", "licitacion publica",
                 "concurso privado", "concurso publico", "subasta"):
        if t.startswith(base):
            return base
    return t


CAMPOS = (
    ("tipo_procedimiento", "Tipo_de_Procedimiento", n_tipo),
    ("objeto", "Objeto_del_Proceso", n_texto),
    ("fecha_apertura", "Fecha_de_Apertura", n_fecha),
    ("monto_estimado", "Monto_Estimado", n_monto),
)
UMBRAL_OBJETO = 0.6


def comparar(datos: dict, fila: dict) -> list[dict]:
    """Campo por campo, ya decidido que es el mismo proceso.

    Cuatro estados, y la distincion importa:
        coincide            las dos publicaciones dicen lo mismo
        no_comparable       el aviso trae un valor que no esta en la misma
                            escala que el del registro (otra moneda, tipo sin
                            especificar): no se puede comparar y no se inventa
        difiere             DISCREPANCIA (solo reportable si esta en COMPARABLES)
        solo_en_registro    el Boletin omite un dato que el registro publica
        solo_en_aviso       al reves
        ambos_vacios        ninguno lo trae
    """
    salida = []
    for campo, col, norm in CAMPOS:
        x, y = norm(datos.get(campo)), norm(fila.get(col))
        # El aviso trae un valor que NO se puede poner en la misma escala que el
        # del registro: monto en otra moneda, tipo que no dice de que tipo. No es
        # una omision del Boletin ni una discrepancia: es una comparacion que no
        # se puede hacer, y decirlo es mas honesto que elegir una de las dos.
        if x is None and datos.get(campo) not in (None, "") and y is not None:
            estado = "no_comparable"
        elif x is None and y is None:
            estado = "ambos_vacios"
        elif x is None:
            estado = "solo_en_registro"
        elif y is None:
            estado = "solo_en_aviso"
        elif campo == "objeto":
            pa = palabras(x)
            s = len(pa & palabras(y)) / max(len(pa), 1)
            estado = "coincide" if s >= UMBRAL_OBJETO else "difiere"
        else:
            estado = "coincide" if x == y else "difiere"
        salida.append({"campo": campo, "estado": estado, "aviso": x, "registro": y,
                       "reportable": campo in COMPARABLES})
    return salida
