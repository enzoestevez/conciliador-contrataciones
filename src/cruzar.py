"""Analisis del cruce: cuanto de lo que publica el Estado se puede verificar.

Uso:
    python src/cruzar.py                      # todos los avisos etiquetados
    python src/cruzar.py --umbral 0.5         # mueve el corte de confianza
    python src/cruzar.py --id 35365-26        # uno puntual, con el detalle

Deja reports/cruce.jsonl (una linea por aviso) y un resumen en pantalla.

================================================================================
QUE ES ESTO Y QUE NO ES

Esto es el ANALISIS, no el sistema. Parte del set etiquetado a mano del proyecto
01 —datos perfectos— para responder una sola pregunta: **¿el cruce entre el
Boletin Oficial y el registro oficial existe?**

El agente (`src/agente.py`) hace lo mismo pero extrayendo con modelo. Comparar
las dos corridas mide cuanto se degrada el sistema cuando el extractor se
equivoca, y para eso esta corrida tiene que seguir existiendo: **es el oraculo.**

Los dos usan `src/comun.py`. Si cada uno tuviera su copia de los normalizadores
y de la confianza, los numeros divergirian con el primer cambio y nadie se
daria cuenta.

================================================================================
POR QUE NO ES UN JOIN

La llave existe —el aviso trae `UOC: 84/129` y `Licitacion Publica 0362/2026`, y
el registro llama a eso `84/129-0362-LPU26`— pero NO es unica: son 111.452
llaves para 128.951 convocatorias, porque el codigo de tipo (LPU, LPR) queda
afuera. Elegir entre candidatos es parte del problema.

Caso real, aviso 36208-26:

    aviso    -> Licitacion Publica · adquisicion de lacteos y panificados
    registro -> Licitacion Privada · adquisicion de materiales de mantenimiento
    registro -> apertura 13/04/2026, ANTERIOR a la publicacion del aviso

Eso no es una discrepancia: son dos procesos distintos. Comparar campos sin
preguntarse antes si es el mismo proceso **inventa hallazgos**, y un sistema que
inventa hallazgos es peor que uno que no encuentra ninguno.

Las tres señales que deciden si es el mismo proceso, con sus pesos y el por que
de cada una, estan en `comun.py`. **No se repiten aca a proposito:** la version
anterior de este archivo tenia su propia copia de la logica y su propia copia de
la explicacion, y las dos se desactualizaron —el docstring seguia describiendo
pesos (tipo 0.20, cronologia 0.25) que el codigo ya no usaba.

El umbral por defecto es 0.55 y es una DECISION, no un descubrimiento: por
encima se compara, por debajo se escala a revision humana. Moverlo con --umbral
y mirar como cambia el recuento es parte del analisis, no un detalle.

================================================================================
LO QUE NO SE CUENTA COMO DISCREPANCIA

`monto_estimado` cuando el aviso no lo trae. Sobre los pares verificados, cero
coincidian — pero el motivo no es que difieran: el Boletin casi nunca publica el
monto y el registro siempre lo tiene. Hay montos de cientos de millones de pesos
que existen en un sistema del Estado y no en el otro. Eso es una brecha de
cobertura, no un error de nadie, y se reporta en su propia seccion.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comun  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "entrada"
REPORTES = RAIZ / "reports"


def cargar_avisos() -> list[dict]:
    et = [json.loads(l) for l in (ENTRADA / "etiquetas_p01.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    meta = {r["id"]: r for r in json.loads((ENTRADA / "indice_p01.json").read_text(encoding="utf-8"))}
    for a in et:
        m = meta[a["id"]]
        a["_meta"] = m
        a["_texto"] = (ENTRADA / "avisos" / m["txt"]).read_text(encoding="utf-8")
    return et


def main() -> None:
    ap = argparse.ArgumentParser(description="¿Cuánto de lo publicado se puede verificar?")
    ap.add_argument("--umbral", type=float, default=comun.UMBRAL)
    ap.add_argument("--id", help="un aviso puntual, con el detalle")
    args = ap.parse_args()

    idx = comun.cargar_registro()
    avisos = cargar_avisos()
    print(f"avisos:   {len(avisos)} etiquetados\n")

    salida: list[dict] = []
    resumen = Counter()
    disc = Counter()
    omit = Counter()

    for a in sorted(avisos, key=lambda x: x["id"]):
        if args.id and a["id"] != args.id:
            continue
        reg = {"aviso": a["id"], "formato": a["_meta"]["formato"], "edicion": a["_meta"]["edicion"]}

        # La UOC sale del texto del aviso: el esquema del proyecto 01 no la tiene,
        # porque ese proyecto medía extracción y no necesitaba identificar.
        k = comun.llave(comun.uoc_del_texto(a["_texto"]), a["datos"].get("numero_procedimiento"))

        if not k:
            reg |= {"resultado": "sin_llave",
                    "motivo": "el aviso no declara UOC: no tramita por COMPR.AR"}
        else:
            reg["llave"] = "-".join(k)
            cands = idx.get(k, [])
            if not cands:
                reg["resultado"] = "sin_candidato"
            else:
                fila, conf, señales = comun.elegir(a["datos"], cands, a["_meta"]["publicado_desde"])
                reg |= {"proceso": fila["Numero_Proceso"], "candidatos": len(cands),
                        "confianza": conf, "señales": señales}
                if conf < args.umbral:
                    reg["resultado"] = "baja_confianza"
                else:
                    reg["resultado"] = "emparejado"
                    reg["comparacion"] = comun.comparar(a["datos"], fila)
                    for c in reg["comparacion"]:
                        if c["estado"] == "difiere":
                            disc[c["campo"]] += 1
                        elif c["estado"] == "solo_en_registro":
                            omit[c["campo"]] += 1

        resumen[reg["resultado"]] += 1
        salida.append(reg)

    if args.id:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
        return

    REPORTES.mkdir(exist_ok=True)
    with (REPORTES / "cruce.jsonl").open("w", encoding="utf-8") as f:
        for r in salida:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(salida)
    etiquetas = {
        "sin_llave": "sin UOC en el aviso (no usa COMPR.AR)",
        "sin_candidato": "con llave, sin registro cargado",
        "baja_confianza": "candidato dudoso -> revisión humana",
        "emparejado": "emparejado con confianza",
    }
    print(f"EMPAREJAMIENTO · umbral de confianza {args.umbral}\n")
    for k_ in ("sin_llave", "sin_candidato", "baja_confianza", "emparejado"):
        v = resumen[k_]
        print(f"  {v:>4} / {n}  {v/n:>5.0%}   {etiquetas[k_]}")

    e = resumen["emparejado"]
    if e:
        print(f"\nDISCREPANCIAS REALES sobre los {e} emparejados")
        print("  (campos que NO participan del emparejamiento)\n")
        for c in comun.COMPARABLES:
            print(f"  {c:20} difiere en {disc[c]:>3}  ({disc[c]/e:>4.0%})")
        print("\n  Campos usados para emparejar, no reportables como hallazgo:")
        for c, _, _ in comun.CAMPOS:
            if c not in comun.COMPARABLES:
                print(f"    {c:18} difiere en {disc[c]:>3}  (circular: se eligió el candidato que mejor coincide)")
        print("\nDATOS QUE EL BOLETIN OMITE y el registro sí publica\n")
        for c, _, _ in comun.CAMPOS:
            if omit[c]:
                print(f"  {c:20} {omit[c]:>3} de {e}  ({omit[c]/e:>4.0%})")
        print(
            "\n  Esto último no son discrepancias: es una brecha de cobertura entre dos\n"
            "  publicaciones del mismo Estado. Se reporta aparte a propósito."
        )
    print(f"\nEscrito reports/cruce.jsonl")


if __name__ == "__main__":
    main()
