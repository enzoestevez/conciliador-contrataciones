"""Verificador del contrato de datos: ¿se puede cruzar el Boletín con el registro oficial?

Uso:
    python verificar_cruce.py registro.csv ../p01/data/gold/etiquetas.jsonl

Esto se corre ANTES de escribir una línea del agente. Si el cruce no existe,
el proyecto cambia de diseño hoy y no en la semana 3.

--------------------------------------------------------------------------------
EL PROBLEMA

El Boletín Oficial publica el aviso en texto y trae `expediente`
(EX-2026-44441162- -APN-LYC#DNV) y `numero_procedimiento` (0023/2026).
El registro oficial se publica bajo el estándar OCDS, que **no define un campo
de expediente**: su identificador es `convocatoria_id`.

Entonces no se sabe de antemano si los dos lados se pueden unir. Este script lo
mide en vez de suponerlo.

--------------------------------------------------------------------------------
COMO LO AVERIGUA SIN CONOCER EL ESQUEMA

1. Lee el CSV y describe cada columna: tipo, valores únicos, ejemplos.
2. Detecta columnas CANDIDATAS a llave por la FORMA de sus valores, no por el
   nombre: expedientes (EX-AAAA-NNNNNNNN...), números de procedimiento (NN/AAAA),
   identificadores OCDS.
3. Para cada candidata, intenta el cruce contra los avisos etiquetados y reporta
   la tasa de coincidencia, sobre valores normalizados.
4. En los pares que sí cruzaron, compara campo por campo. Esa es la vista previa
   del resultado del proyecto: dónde el aviso publicado y el registro oficial
   dicen cosas distintas.

--------------------------------------------------------------------------------
EL CRITERIO DE DECISION, ESCRITO ANTES DE VER EL RESULTADO

    >= 60% de los avisos encuentran su registro  ->  el proyecto va
    30% a 60%                                    ->  va, declarando la cobertura
    < 30%                                        ->  no hay cruce, plan B

Dejarlo escrito antes de correr el script es lo que impide mover el poste
después para que el resultado dé lo que uno quería.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# ----------------------------------------------------------------- normalizadores


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_codigo(v) -> str | None:
    """Sólo alfanuméricos en minúscula. EX-2026-123- -APN-X#Y -> ex2026123apnxy"""
    if v is None:
        return None
    s = re.sub(r"[^a-z0-9]", "", sin_tildes(str(v)).lower())
    return s or None


def norm_texto(v) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", sin_tildes(str(v)).lower()).strip(" .,;:-")
    return s or None


# ----------------------------------------------------------------- formas de llave

FORMAS = {
    "expediente": re.compile(r"^\s*EX[PT]?[-\s]?\d{4}[-\s]?\d{6,}", re.I),
    "procedimiento": re.compile(r"^\s*\d{1,6}\s*/\s*\d{2,4}\s*$"),
    "ocds": re.compile(r"^ocds-", re.I),
    "cuit": re.compile(r"^\d{2}-?\d{8}-?\d$"),
}


def describir(filas: list[dict], columnas: list[str]) -> dict[str, dict]:
    """Perfil de cada columna: llenado, unicidad, forma predominante, ejemplos."""
    perfil = {}
    n = len(filas)
    for col in columnas:
        valores = [f.get(col) for f in filas]
        no_vacios = [v for v in valores if v not in (None, "")]
        formas = Counter()
        for v in no_vacios[:2000]:
            for nombre, rx in FORMAS.items():
                if rx.match(str(v)):
                    formas[nombre] += 1
                    break
            else:
                formas["otro"] += 1
        perfil[col] = {
            "llenado": len(no_vacios) / n if n else 0,
            "unicos": len({str(v) for v in no_vacios}),
            "forma": formas.most_common(1)[0][0] if formas else "vacio",
            "forma_pct": (formas.most_common(1)[0][1] / len(no_vacios)) if no_vacios else 0,
            "ejemplos": [str(v)[:60] for v in no_vacios[:3]],
        }
    return perfil


# ----------------------------------------------------------------- cruce


def probar_cruce(filas, col, avisos, campo_aviso, normalizador):
    """Devuelve (coincidencias, total, pares) para una columna candidata."""
    indice: dict[str, list[dict]] = {}
    for f in filas:
        k = normalizador(f.get(col))
        if k:
            indice.setdefault(k, []).append(f)

    pares, hits = [], 0
    for a in avisos:
        k = normalizador(a["datos"].get(campo_aviso))
        if not k:
            continue
        if k in indice:
            hits += 1
            pares.append((a, indice[k][0]))
    con_valor = sum(1 for a in avisos if normalizador(a["datos"].get(campo_aviso)))
    return hits, con_valor, pares


def main() -> None:
    ap = argparse.ArgumentParser(description="¿Existe el cruce Boletín <-> registro oficial?")
    ap.add_argument("csv_registro", help="CSV bajado de datos.gob.ar")
    ap.add_argument("etiquetas", help="data/gold/etiquetas.jsonl del proyecto 01")
    ap.add_argument("--delimitador", default=None, help="por defecto se detecta solo")
    ap.add_argument("--max-filas", type=int, default=200_000)
    args = ap.parse_args()

    texto = Path(args.csv_registro).read_text(encoding="utf-8", errors="replace")
    delim = args.delimitador or csv.Sniffer().sniff(texto[:8000], delimiters=",;\t|").delimiter
    filas = list(csv.DictReader(texto.splitlines(), delimiter=delim))[: args.max_filas]
    if not filas:
        sys.exit("El CSV salió vacío. Revisá el archivo.")
    columnas = list(filas[0].keys())

    avisos = [json.loads(l) for l in Path(args.etiquetas).read_text(encoding="utf-8").splitlines() if l.strip()]

    print(f"REGISTRO OFICIAL · {len(filas):,} filas · {len(columnas)} columnas · delimitador {delim!r}")
    print(f"AVISOS ETIQUETADOS · {len(avisos)}\n")

    # --- perfil de columnas -------------------------------------------------
    perfil = describir(filas, columnas)
    print("COLUMNAS (ordenadas por utilidad como llave)\n")
    print(f"  {'columna':38} {'llenado':>8} {'únicos':>8}  forma")
    orden = sorted(
        columnas,
        key=lambda c: (perfil[c]["forma"] == "otro", -perfil[c]["llenado"], -perfil[c]["unicos"]),
    )
    for c in orden:
        p = perfil[c]
        marca = "*" if p["forma"] != "otro" and p["forma_pct"] > 0.5 else " "
        print(f" {marca}{c[:38]:38} {p['llenado']:>7.0%} {p['unicos']:>8,}  {p['forma']}")
        if marca == "*":
            print(f"   {'':38} {'':>8} {'':>8}  ej: {', '.join(p['ejemplos'])}")

    candidatas = [c for c in columnas if perfil[c]["forma"] != "otro" and perfil[c]["forma_pct"] > 0.5]
    if not candidatas:
        print("\nNinguna columna tiene forma de llave. Mirá el listado y pasame la salida.")
        return

    # --- probar cruces ------------------------------------------------------
    print(f"\n{'='*70}\nCRUCES PROBADOS\n{'='*70}\n")
    mejor = None
    for col in candidatas:
        forma = perfil[col]["forma"]
        campo = {"expediente": "expediente", "procedimiento": "numero_procedimiento"}.get(forma)
        if not campo:
            continue
        hits, total, pares = probar_cruce(filas, col, avisos, campo, norm_codigo)
        if not total:
            continue
        tasa = hits / total
        print(f"  {col}  ×  aviso.{campo}")
        print(f"     {hits}/{total} avisos encontraron su registro  ->  {tasa:.0%}")
        if mejor is None or tasa > mejor[0]:
            mejor = (tasa, col, campo, pares)
        print()

    if not mejor:
        print("No se pudo probar ningún cruce. Pasame la salida de arriba.")
        return

    tasa, col, campo, pares = mejor
    print(f"{'='*70}")
    veredicto = ("EL PROYECTO VA" if tasa >= 0.60 else
                 "VA, DECLARANDO LA COBERTURA" if tasa >= 0.30 else
                 "NO HAY CRUCE -> PLAN B")
    print(f"MEJOR CRUCE: {col} × aviso.{campo} = {tasa:.0%}   ->   {veredicto}")
    print(f"{'='*70}\n")

    # --- vista previa del resultado del proyecto ---------------------------
    if pares:
        print(f"VISTA PREVIA · dónde difieren los {len(pares)} pares que cruzaron\n")
        cols_texto = [c for c in columnas if perfil[c]["llenado"] > 0.5][:40]
        for campo_aviso in ("organismo", "objeto"):
            mejores = []
            for c in cols_texto:
                puntajes = []
                for a, f in pares:
                    x, y = norm_texto(a["datos"].get(campo_aviso)), norm_texto(f.get(c))
                    if x and y:
                        comun = len(set(x.split()) & set(y.split()))
                        puntajes.append(comun / max(len(set(x.split())), 1))
                if puntajes:
                    mejores.append((sum(puntajes) / len(puntajes), c))
            mejores.sort(reverse=True)
            if mejores:
                p, c = mejores[0]
                print(f"  aviso.{campo_aviso:10} se parece más a  {c}  ({p:.0%} de palabras en común)")
        print(
            "\n  Esas equivalencias son las que el agente va a comparar. Donde no\n"
            "  coincidan, hay una discrepancia entre lo publicado y el registro\n"
            "  oficial: ese es el resultado vendible del proyecto."
        )


if __name__ == "__main__":
    main()
