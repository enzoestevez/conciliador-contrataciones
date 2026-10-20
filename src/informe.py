"""Informe del agente: metricas operativas y evaluacion de punta a punta.

Uso:
    python src/informe.py

Lee reports/traza.jsonl y escribe reports/agente.md.

================================================================================
DOS COSAS DISTINTAS, Y LA SEGUNDA ES LA QUE VALE

**Metricas operativas.** Que decidio el agente, cuanto costo, cuanto tardo.
Es lo que le importa a quien lo pone en produccion.

**Evaluacion de punta a punta.** Lo interesante: el agente extrae por su cuenta,
y `cruzar.py` ya hizo el mismo emparejamiento partiendo del set etiquetado a
mano del proyecto 01. Comparar las dos corridas mide **cuanto se degrada el
sistema completo cuando el extractor comete errores**.

Eso no es la precision del extractor. Es otra cosa y es mas util: un error en
`numero_procedimiento` rompe la llave y tira el caso entero, mientras que un
error en `objeto` solo baja la confianza. **La misma precision de extraccion
produce degradaciones muy distintas segun en que campo caiga el error.**

Y la verdad de referencia para esto no costo una sola etiqueta nueva: el
proyecto 01 es el oraculo del proyecto 02.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REPORTES = RAIZ / "reports"
TRAZA = REPORTES / "traza.jsonl"
CRUCE = REPORTES / "cruce.jsonl"
ENTRADA = RAIZ / "data" / "entrada"

ETIQUETAS = {
    "aprobado": "emparejado y comparado",
    "escalado": "candidato dudoso → revisión humana",
    "sin_llave": "el aviso no declara UOC: no tramita por COMPR.AR",
    "sin_registro": "la llave no existe en el registro",
    "error_extraccion": "falló la llamada al modelo",
}


def leer(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def pct(a: int, b: int) -> str:
    return f"{a/b:.0%}" if b else "—"


def main() -> None:
    traza = leer(TRAZA)
    if not traza:
        sys.exit(f"No hay traza en {TRAZA}. Corré src/agente.py primero.")

    # Una línea por aviso: la última gana (el agente es reanudable).
    casos = {c["aviso"]: c for c in traza}
    casos = list(casos.values())
    n = len(casos)
    dec = Counter(c["decision"] for c in casos)
    ok = [c for c in casos if c["decision"] == "aprobado"]

    L: list[str] = ["# Informe del agente conciliador\n"]
    L.append(f"{n} avisos procesados · modelo `{casos[0].get('modelo','?')}`\n")

    # ------------------------------------------------------------ decisiones
    L.append("## Qué decidió\n")
    L.append("| Decisión | Casos | | Qué significa |")
    L.append("|---|---:|---:|---|")
    for d, _ in dec.most_common():
        L.append(f"| `{d}` | {dec[d]} | {pct(dec[d], n)} | {ETIQUETAS.get(d, '')} |")
    L.append("")

    verificables = dec["aprobado"] + dec["escalado"]
    L.append(
        f"**{pct(verificables, n)} de los avisos son verificables** contra el registro oficial. "
        f"El resto no tiene contraparte legible por máquina: o el organismo no usa el sistema "
        f"central de contrataciones, o el registro todavía no cargó el proceso.\n"
    )

    # ------------------------------------------------------------ costo
    tin = sum(c.get("tokens_in", 0) for c in casos)
    tout = sum(c.get("tokens_out", 0) for c in casos)
    gasto = sum(c.get("costo_usd", 0) for c in casos)
    lat = sorted(c.get("latencia_ms", 0) for c in casos if c.get("latencia_ms"))

    L.append("## Cuánto cuesta operarlo\n")
    L.append("| | |")
    L.append("|---|---:|")
    L.append(f"| Costo total | USD {gasto:.4f} |")
    L.append(f"| Costo por aviso | USD {gasto/n:.6f} |")
    L.append(f"| Costo por 1.000 avisos | USD {gasto/n*1000:.2f} |")
    L.append(f"| Tokens | {tin:,} entrada · {tout:,} salida |")
    if lat:
        L.append(f"| Latencia mediana | {lat[len(lat)//2]/1000:.1f} s |")
        L.append(f"| Latencia p95 | {lat[min(int(len(lat)*0.95), len(lat)-1)]/1000:.1f} s |")
    L.append("")

    # ------------------------------------------------------------ hallazgos
    if ok:
        disc = Counter(x for c in ok for x in c.get("discrepancias", []))
        omit = Counter(x for c in ok for x in c.get("omitidos_por_el_boletin", []))
        L.append(f"## Discrepancias · sobre los {len(ok)} emparejados\n")
        L.append("Campos que **no** participan del emparejamiento, así que una diferencia")
        L.append("acá es un hallazgo y no un artefacto de cómo se eligió el candidato.\n")
        L.append("| Campo | Difiere | |")
        L.append("|---|---:|---:|")
        for c in ("tipo_procedimiento", "fecha_apertura", "monto_estimado"):
            L.append(f"| `{c}` | {disc[c]} | {pct(disc[c], len(ok))} |")
        L.append("")
        if omit:
            L.append("## Datos que el Boletín omite y el registro publica\n")
            L.append("| Campo | Omitido | |")
            L.append("|---|---:|---:|")
            for c, v in omit.most_common():
                L.append(f"| `{c}` | {v} | {pct(v, len(ok))} |")
            L.append("\nNo son discrepancias: es una brecha de cobertura entre dos")
            L.append("publicaciones del mismo Estado, y se reporta aparte a propósito.\n")

        confs = [c["confianza_emparejamiento"] for c in ok if c.get("confianza_emparejamiento") is not None]
        if confs:
            L.append("## Confianza de emparejamiento\n")
            L.append(f"Mediana {st.median(confs):.2f} · mínima {min(confs):.2f} · "
                     f"casos con un único candidato: {sum(1 for c in ok if c.get('candidatos')==1)} de {len(ok)}\n")

    # ------------------------------------------------------- evaluación e2e
    cruce = {c["aviso"]: c for c in leer(CRUCE)}
    comunes = [c for c in casos if c["aviso"] in cruce]
    if comunes:
        L.append("## Evaluación de punta a punta\n")
        L.append("`cruzar.py` hizo el mismo emparejamiento partiendo del set etiquetado a mano")
        L.append("del proyecto 01. Comparar las dos corridas mide cuánto se degrada el sistema")
        L.append("completo cuando el extractor se equivoca — que no es lo mismo que la precisión")
        L.append("del extractor.\n")
        L.append("**La verdad de referencia no costó una etiqueta nueva: el proyecto 01 es el oráculo.**\n")

        igual = dist = 0
        rotos: list[tuple[str, str, str]] = []
        for c in comunes:
            ref = cruce[c["aviso"]]
            a, b = c["decision"], ref.get("resultado")
            equiv = {"aprobado": "emparejado", "escalado": "baja_confianza",
                     "sin_llave": "sin_llave", "sin_registro": "sin_candidato"}
            if equiv.get(a) == b:
                igual += 1
            else:
                dist += 1
                if len(rotos) < 8:
                    rotos.append((c["aviso"], f"{a} (agente)", f"{b} (etiquetas)"))
        L.append(f"| | Casos | |")
        L.append("|---|---:|---:|")
        L.append(f"| Misma decisión que con etiquetas perfectas | {igual} | {pct(igual, len(comunes))} |")
        L.append(f"| Decisión distinta | {dist} | {pct(dist, len(comunes))} |")
        L.append("")
        if rotos:
            L.append("Dónde se degrada:\n")
            for i, x, y in rotos:
                L.append(f"- `{i}` → {x} vs {y}")
            L.append("")

        # ¿emparejó con el MISMO proceso?
        pares = [(c, cruce[c["aviso"]]) for c in comunes
                 if c.get("proceso") and cruce[c["aviso"]].get("proceso")]
        if pares:
            mismo = sum(1 for c, r in pares if c["proceso"] == r["proceso"])
            L.append(f"De los {len(pares)} casos que ambos emparejaron, coincidieron en el "
                     f"**mismo proceso del registro en {mismo}** ({pct(mismo, len(pares))}).\n")

    L.append("---\n")
    L.append("Generado por `src/informe.py` desde `reports/traza.jsonl`.")

    salida = REPORTES / "agente.md"
    salida.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:40]))
    print(f"\n… escrito completo en reports/agente.md")


if __name__ == "__main__":
    main()
