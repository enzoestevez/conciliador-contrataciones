"""Emparejador: vincula cada aviso del Boletin con su proceso en el registro oficial.

Uso:
    python src/cruzar.py                      # todos los avisos etiquetados
    python src/cruzar.py --umbral 0.5         # mueve el corte de confianza
    python src/cruzar.py --id 35365-26        # uno puntual, con el detalle

Deja reports/cruce.jsonl (una linea por aviso) y un resumen en pantalla.

================================================================================
POR QUE ESTO NO ES UN JOIN

La llave existe: el aviso trae `UOC: 84/129` y `Licitación Pública 0362/2026`,
y el registro llama a eso `84/129-0362-LPU26`. Armarla es tres lineas.

El problema es que la llave **produce falsos positivos**. Caso real del corpus,
aviso 36208-26:

    aviso    -> Licitación Pública · adquisición de lácteos y panificados
    registro -> Licitación Privada · adquisición de materiales de mantenimiento
    registro -> fecha de apertura 13/04/2026, ANTERIOR a la publicación del aviso

Eso no es una discrepancia entre dos publicaciones del Estado: es que estamos
mirando dos procesos distintos. Si se comparan los campos sin preguntarse antes
si es el mismo proceso, el sistema **inventa discrepancias** — y un sistema que
inventa hallazgos es peor que uno que no encuentra ninguno.

De ahi el diseño: **primero la confianza de emparejamiento, despues la
comparacion de campos.** Esta decision salio de los datos de la verificacion,
no de un diseño previo.

================================================================================
COMO SE CALCULA LA CONFIANZA

Cuatro senales independientes, cada una con su peso. Ninguna alcanza sola:

  objeto (0.45)      Palabras en comun entre el objeto del aviso y el del
                     registro. Es la senal mas fuerte porque es texto libre que
                     dos sistemas distintos escribieron para la misma compra.

  tipo (0.20)        Coincide el tipo de procedimiento. Publica contra privada
                     es una senal fuerte de que no es el mismo proceso.

  cronologia (0.25)  La fecha de apertura del registro no puede ser anterior a
                     la publicacion del aviso. Un llamado no se abre antes de
                     anunciarse. Es la senal que atrapo el caso 36208-26.

  unicidad (0.10)    Si la llave devuelve un solo candidato, vale mas que si
                     devuelve cinco.

El umbral por defecto es 0.55 y es una DECISION, no un descubrimiento: por
encima se compara, por debajo se escala a revision humana. Moverlo con --umbral
y mirar como cambia el recuento es parte del analisis, no un detalle.

================================================================================
LO QUE NO SE CUENTA COMO DISCREPANCIA

`monto_estimado` cuando el aviso no lo trae. Sobre los pares verificados, cero
coincidian — pero el motivo no es que difieran: el Boletin casi nunca publica el
monto y el registro siempre lo tiene. Hay montos de cientos de millones de pesos
ausentes del aviso publicado. Eso es una **brecha de cobertura entre dos
publicaciones del mismo Estado**, y se reporta en su propia categoria.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "entrada"
REGISTRO = RAIZ / "data" / "registro"
REPORTES = RAIZ / "reports"

UMBRAL = 0.55

# SEÑALES DE EMPAREJAMIENTO. Sirven para decidir si es el mismo proceso.
# Un campo usado para emparejar NO puede reportarse despues como hallazgo:
# si elijo al candidato que mejor coincide en un campo, ese campo va a coincidir
# por construccion. Ver COMPARABLES abajo.
PESOS = {"objeto": 0.55, "cronologia": 0.30, "unicidad": 0.15}

# CAMPOS COMPARABLES. No participan del emparejamiento, asi que una diferencia
# aca es un hallazgo real: dos publicaciones del mismo Estado que no coinciden.
#
# `fecha_apertura` entra aca con una aclaracion. La señal de cronologia usa la
# apertura DEL REGISTRO contra la fecha de PUBLICACION del aviso, y nunca toca la
# fecha de apertura etiquetada. Son dos cantidades distintas, asi que no hay
# circularidad: hay acoplamiento debil, y queda declarado.
COMPARABLES = ("tipo_procedimiento", "fecha_apertura", "monto_estimado")

# --------------------------------------------------------------- normalizadores


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def n_texto(v) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", _sin_tildes(v).lower()).strip(" .,;:-")
    return s or None


def n_uoc(v) -> str:
    return "/".join(x.lstrip("0") or "0" for x in str(v).strip().split("/"))


def n_monto(v) -> float | None:
    """El registro escribe 1,735,400.00 (coma de miles). El aviso, 1.735.400,00."""
    if v is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
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


def palabras(s: str | None) -> set[str]:
    if not s:
        return set()
    return {p for p in re.findall(r"[a-z0-9]{4,}", s)}


# --------------------------------------------------------------- carga

RX_PROCESO = re.compile(r"^(.+?)-(\d+)-([A-Z]+)(\d{2})$")
RX_UOC = re.compile(r"UOC\s*:\s*([\d/]+)", re.I)
RX_NUM = re.compile(r"^\s*0*(\d+)\s*/\s*(\d{2,4})\s*$")


def cargar_registro() -> dict[tuple, list[dict]]:
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
    print(f"registro: {leidas:,} convocatorias leídas · {indexadas:,} indexadas "
          f"({indexadas/leidas:.0%}) · {len(idx):,} llaves")
    if indexadas / leidas < 0.95:
        print("  ! Se está descartando más del 5%. Revisá RX_PROCESO antes de confiar en el resultado.")
    return idx


def cargar_avisos() -> list[dict]:
    et = [json.loads(l) for l in (ENTRADA / "etiquetas_p01.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    meta = {r["id"]: r for r in json.loads((ENTRADA / "indice_p01.json").read_text(encoding="utf-8"))}
    for a in et:
        m = meta[a["id"]]
        a["_meta"] = m
        a["_texto"] = (ENTRADA / "avisos" / m["txt"]).read_text(encoding="utf-8")
    return et


# --------------------------------------------------------------- confianza


def llave_del_aviso(a: dict) -> tuple | None:
    mu = RX_UOC.search(a["_texto"])
    mn = RX_NUM.match(str(a["datos"].get("numero_procedimiento") or ""))
    if not mu or not mn:
        return None
    return (n_uoc(mu.group(1)), mn.group(1), mn.group(2)[-2:])


def confianza(a: dict, fila: dict, n_candidatos: int) -> tuple[float, dict]:
    señales: dict[str, float | None] = {}

    pa = palabras(n_texto(a["datos"].get("objeto")))
    pr = palabras(n_texto(fila.get("Objeto_del_Proceso"))) | palabras(n_texto(fila.get("Nombre_del_Proceso")))
    señales["objeto"] = len(pa & pr) / len(pa) if pa and pr else None

    # Un llamado no se abre antes de anunciarse.
    pub_aviso = a["_meta"]["publicado_desde"]
    ap_registro = n_fecha(fila.get("Fecha_de_Apertura"))
    pub = n_fecha(pub_aviso)
    if pub and ap_registro:
        señales["cronologia"] = 1.0 if ap_registro >= pub else 0.0

    señales["unicidad"] = 1.0 if n_candidatos == 1 else max(0.0, 1.0 - 0.3 * (n_candidatos - 1))

    usados = {k: v for k, v in señales.items() if v is not None}
    peso = sum(PESOS[k] for k in usados) or 1.0
    return round(sum(v * PESOS[k] for k, v in usados.items()) / peso, 3), señales


# --------------------------------------------------------------- comparacion

CAMPOS = (
    ("tipo_procedimiento", "Tipo_de_Procedimiento", n_texto),
    ("objeto", "Objeto_del_Proceso", n_texto),
    ("fecha_apertura", "Fecha_de_Apertura", n_fecha),
    ("monto_estimado", "Monto_Estimado", n_monto),
)


def comparar(a: dict, fila: dict) -> list[dict]:
    salida = []
    for campo, col, norm in CAMPOS:
        x, y = norm(a["datos"].get(campo)), norm(fila.get(col))
        if x is None and y is None:
            estado = "ambos_vacios"
        elif x is None:
            estado = "solo_en_registro"      # el Boletín omitió el dato
        elif y is None:
            estado = "solo_en_aviso"
        elif campo == "objeto":
            pa, pr = palabras(str(x)), palabras(str(y))
            s = len(pa & pr) / max(len(pa), 1)
            estado = "coincide" if s >= 0.6 else "difiere"
        else:
            estado = "coincide" if x == y else "difiere"
        salida.append({"campo": campo, "estado": estado, "aviso": x, "registro": y})
    return salida


# --------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description="Empareja avisos con el registro oficial.")
    ap.add_argument("--umbral", type=float, default=UMBRAL)
    ap.add_argument("--id", help="un aviso puntual, con el detalle")
    args = ap.parse_args()

    idx = cargar_registro()
    avisos = cargar_avisos()
    print(f"avisos:   {len(avisos)} etiquetados\n")

    salida, resumen = [], {"sin_llave": 0, "sin_candidato": 0, "baja_confianza": 0, "emparejado": 0}
    disc = {c: 0 for c, _, _ in CAMPOS}
    solo_registro = {c: 0 for c, _, _ in CAMPOS}

    for a in sorted(avisos, key=lambda x: x["id"]):
        if args.id and a["id"] != args.id:
            continue
        reg = {"aviso": a["id"], "formato": a["_meta"]["formato"], "edicion": a["_meta"]["edicion"]}
        k = llave_del_aviso(a)
        if not k:
            reg["resultado"] = "sin_llave"
            reg["motivo"] = "el aviso no declara UOC: no tramita por COMPR.AR"
            resumen["sin_llave"] += 1
        else:
            cands = idx.get(k, [])
            if not cands:
                reg |= {"resultado": "sin_candidato", "llave": "-".join(k)}
                resumen["sin_candidato"] += 1
            else:
                puntuados = [(confianza(a, f, len(cands)), f) for f in cands]
                (conf, señales), fila = max(puntuados, key=lambda t: t[0][0])
                reg |= {"llave": "-".join(k), "proceso": fila["Numero_Proceso"],
                        "confianza": conf, "señales": señales, "candidatos": len(cands)}
                if conf < args.umbral:
                    reg["resultado"] = "baja_confianza"
                    resumen["baja_confianza"] += 1
                else:
                    reg["resultado"] = "emparejado"
                    reg["comparacion"] = comparar(a, fila)
                    resumen["emparejado"] += 1
                    for c in reg["comparacion"]:
                        if c["estado"] == "difiere":
                            disc[c["campo"]] += 1
                        elif c["estado"] == "solo_en_registro":
                            solo_registro[c["campo"]] += 1
        salida.append(reg)

    if args.id:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
        return

    REPORTES.mkdir(exist_ok=True)
    with (REPORTES / "cruce.jsonl").open("w", encoding="utf-8") as f:
        for r in salida:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(salida)
    print(f"EMPAREJAMIENTO · umbral de confianza {args.umbral}\n")
    etiquetas = {
        "sin_llave": "sin UOC en el aviso (no usa COMPR.AR)",
        "sin_candidato": "con llave, sin registro cargado",
        "baja_confianza": "candidato dudoso -> revisión humana",
        "emparejado": "emparejado con confianza",
    }
    for k, v in resumen.items():
        print(f"  {v:>4} / {n}  {v/n:>5.0%}   {etiquetas[k]}")

    if resumen["emparejado"]:
        e = resumen["emparejado"]
        print(f"\nDISCREPANCIAS REALES sobre los {e} emparejados")
        print("  (campos que NO participan del emparejamiento)\n")
        for c in COMPARABLES:
            print(f"  {c:20} difiere en {disc[c]:>3}  ({disc[c]/e:>4.0%})")
        print("\n  Campos usados para emparejar, no reportables como hallazgo:")
        for c, _, _ in CAMPOS:
            if c not in COMPARABLES:
                print(f"    {c:18} difiere en {disc[c]:>3}  (circular: se eligió el candidato que mejor coincide)")
        print(f"\nDATOS QUE EL BOLETIN OMITE y el registro sí publica\n")
        for c, _, _ in CAMPOS:
            if solo_registro[c]:
                print(f"  {c:20} {solo_registro[c]:>3} de {e}  ({solo_registro[c]/e:>4.0%})")
        print(
            "\n  Esto último no son discrepancias: es una brecha de cobertura entre dos\n"
            "  publicaciones del mismo Estado. Se reporta aparte a propósito."
        )
    print(f"\nEscrito reports/cruce.jsonl")


if __name__ == "__main__":
    main()
