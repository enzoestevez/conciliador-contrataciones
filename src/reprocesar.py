"""Reprocesa una corrida del agente desde la traza, sin volver a llamar al modelo.

Uso:
    python src/reprocesar.py
    python src/reprocesar.py --umbral 0.7
    python src/informe.py --traza reports/traza-reproceso.jsonl

================================================================================
PARA QUE EXISTE

Un pipeline con modelo tiene dos mitades con propiedades opuestas:

    la llamada al modelo   cara, lenta, no deterministica, con cupo por minuto
    todo lo que sigue      gratis, instantaneo, deterministico

La traza guarda el campo `extraido`: exactamente lo que el modelo devolvio en
cada caso. Entonces cualquier bug en la mitad de abajo —normalizadores, pesos de
confianza, umbral, reglas de comparacion— se arregla y se vuelve a evaluar sobre
las MISMAS extracciones, gratis.

Esto no es teoria. La primera corrida de 115 casos reporto **cero discrepancias**
sobre 36 emparejados, con `fecha_apertura` "omitida por el Boletin" en el 100%.
El modelo habia extraido la fecha bien en 98 de 115 casos: el que la perdia era
`comun.n_fecha`, que no parseaba el formato con segundos (`2026-06-08T09:00:00`)
y devolvia None. Cero discrepancias no era "no encontre nada": era "no compare
nada".

Arreglar eso y volver a correr el agente completo costaba USD 0.08 y 8 minutos.
Reprocesar desde la traza costo **USD 0.00 y 2 segundos**.

================================================================================
QUE NO HACE

No toca `reports/traza.jsonl`. Esa es la traza de lo que el agente HIZO —un log
de auditoria— y reescribirla para que diga otra cosa es exactamente lo que un log
de auditoria no debe permitir. El reproceso va a un archivo nuevo, y queda a la
vista que es un reproceso y con que codigo.

Tampoco arregla una extraccion mala. Si el modelo leyo mal la UOC, eso sigue mal:
reprocesar no mejora los datos, solo vuelve a correr la logica.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agente  # noqa: E402
import comun  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "entrada"
REPORTES = RAIZ / "reports"

# Campos que describen la LLAMADA y no la decision: se copian tal cual, porque
# son hechos de lo que paso y el reproceso no los puede cambiar.
DE_LA_LLAMADA = ("aviso", "edicion", "formato", "momento", "modelo", "tokens_in",
                 "tokens_out", "latencia_ms", "costo_usd", "confianza_extraccion")


def commit_actual() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except Exception:  # noqa: BLE001
        return "?"


def main() -> None:
    ap = argparse.ArgumentParser(description="Reprocesa la traza sin llamar al modelo.")
    ap.add_argument("--traza", default=str(REPORTES / "traza.jsonl"))
    ap.add_argument("--salida", default=str(REPORTES / "traza-reproceso.jsonl"))
    ap.add_argument("--umbral", type=float, default=comun.UMBRAL)
    args = ap.parse_args()

    origen = Path(args.traza)
    if not origen.exists():
        sys.exit(f"No hay traza en {origen}. Corré src/agente.py primero.")

    # La última línea por aviso gana: el agente es reanudable y puede haber
    # reintentado un caso.
    casos = {}
    for linea in origen.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            r = json.loads(linea)
            casos[r["aviso"]] = r
    casos = list(casos.values())

    meta = {r["id"]: r for r in json.loads((ENTRADA / "indice_p01.json").read_text(encoding="utf-8"))}
    idx = comun.cargar_registro()
    print(f"traza:    {len(casos)} casos leídos de {origen.name}")
    print(f"código:   commit {commit_actual()} · umbral {args.umbral}\n")

    antes = Counter(c["decision"] for c in casos)
    salida, despues = [], Counter()
    cambios = []

    for c in casos:
        if not c.get("extraido"):
            # Un error de extracción no tiene nada que reprocesar: se arrastra
            # tal cual para no inventar un resultado que nunca existió.
            salida.append(c | {"reproceso": "sin extracción, se arrastra"})
            despues[c["decision"]] += 1
            continue

        base = {k: c[k] for k in DE_LA_LLAMADA if k in c}
        base["reproceso"] = {"cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "commit": commit_actual(), "umbral": args.umbral,
                             "decision_original": c["decision"]}
        nuevo = agente.decidir(base, c["extraido"], meta[c["aviso"]]["publicado_desde"],
                               idx, args.umbral)
        salida.append(nuevo)
        despues[nuevo["decision"]] += 1
        if nuevo["decision"] != c["decision"]:
            cambios.append((c["aviso"], c["decision"], nuevo["decision"]))

    destino = Path(args.salida)
    with destino.open("w", encoding="utf-8") as f:
        for r in salida:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("DECISIONES\n")
    print(f"  {'decisión':20} {'antes':>7} {'ahora':>7}")
    for d in sorted(set(antes) | set(despues)):
        print(f"  {d:20} {antes[d]:>7} {despues[d]:>7}")
    if cambios:
        print(f"\n  {len(cambios)} casos cambiaron de decisión:")
        for i, a, b in cambios[:10]:
            print(f"    {i}  {a} -> {b}")
    else:
        print("\n  Ninguna decisión cambió: el arreglo fue aguas abajo del emparejamiento.")

    ok = [c for c in salida if c["decision"] == "aprobado"]
    if ok:
        disc = Counter(x for c in ok for x in c.get("discrepancias", []))
        omit = Counter(x for c in ok for x in c.get("omitidos_por_el_boletin", []))
        print(f"\nSOBRE LOS {len(ok)} EMPAREJADOS\n")
        for campo in comun.COMPARABLES:
            print(f"  {campo:20} difiere en {disc[campo]:>3}  ({disc[campo]/len(ok):>4.0%})")
        print()
        for campo, v in omit.most_common():
            print(f"  {campo:20} omitido en {v:>3}  ({v/len(ok):>4.0%})")

    print(f"\nEscrito {destino.relative_to(RAIZ)} · costo del reproceso: USD 0.00")
    print(f"Informe:  python src/informe.py --traza {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
