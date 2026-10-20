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
    """84/077 y 84/77 son la misma UOC."""
    return "/".join(x.lstrip("0") or "0" for x in str(v).strip().split("/"))


def n_monto(v) -> float | None:
    """El registro escribe 1,735,400.00 (coma de miles). El aviso, 1.735.400,00."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def n_fecha(v) -> str | None:
    if not v:
        return None
    crudo = str(v).split(" ")[0].strip()
    for f in ("%d/%m/%Y", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d-%m-%Y"):
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
RX_UOC_TEXTO = re.compile(r"UOC\s*:\s*([\d/]+)", re.I)
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
        print(f"registro: {leidas:,} convocatorias · {indexadas:,} indexadas "
              f"({indexadas/leidas:.0%}) · {len(idx):,} llaves")
        if indexadas / leidas < 0.95:
            print("  ! Se descarta más del 5%. Revisá RX_PROCESO antes de confiar en el resultado.")
    return idx


def llave(uoc, numero_procedimiento) -> tuple | None:
    """(UOC, numero, año) desde los valores extraidos. None si falta alguno."""
    if not uoc:
        return None
    m = RX_NUMERO.match(str(numero_procedimiento or ""))
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

CAMPOS = (
    ("tipo_procedimiento", "Tipo_de_Procedimiento", n_texto),
    ("objeto", "Objeto_del_Proceso", n_texto),
    ("fecha_apertura", "Fecha_de_Apertura", n_fecha),
    ("monto_estimado", "Monto_Estimado", n_monto),
)
UMBRAL_OBJETO = 0.6


def comparar(datos: dict, fila: dict) -> list[dict]:
    """Campo por campo, ya decidido que es el mismo proceso.

    Cuatro estados, y la distincion importa:
        coincide            las dos publicaciones dicen lo mismo
        difiere             DISCREPANCIA (solo reportable si esta en COMPARABLES)
        solo_en_registro    el Boletin omite un dato que el registro publica
        solo_en_aviso       al reves
        ambos_vacios        ninguno lo trae
    """
    salida = []
    for campo, col, norm in CAMPOS:
        x, y = norm(datos.get(campo)), norm(fila.get(col))
        if x is None and y is None:
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
