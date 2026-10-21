"""El agente: lee el aviso, extrae con modelo, busca su registro y decide.

Uso:
    python src/agente.py --limite 10            # prueba corta
    python src/agente.py                        # todo el corpus
    python src/agente.py --presupuesto 0.50     # tope de gasto en USD
    python src/agente.py --umbral 0.55          # corte de confianza

Deja tres archivos, y los tres importan por separado:
    reports/traza.jsonl       una linea por caso: tokens, costo, latencia, señales
    reports/auditoria.jsonl   solo las decisiones, append-only, con su evidencia
    reports/agente.md         el resumen operativo

================================================================================
QUE HACE, EN ORDEN

    1. EXTRAE del texto del aviso, con modelo y salida forzada por esquema.
    2. ARMA LA LLAVE con la UOC y el numero de procedimiento que extrajo.
    3. BUSCA candidatos en el registro oficial de COMPR.AR.
    4. PUNTUA la confianza de emparejamiento: ¿es el mismo proceso?
    5. DECIDE:
         sin_llave        el aviso no declara UOC -> no tramita por COMPR.AR
         sin_registro     la llave no existe en el registro
         escalado         candidato por debajo del umbral -> revision humana
         aprobado         emparejado y comparado

Nada irreversible sin aprobacion humana: el agente **no escribe en el registro
ni en el corpus**. Su unico efecto es dejar su propia traza. Ver PERMISOS.

================================================================================
EL ESQUEMA DE EXTRACCION ES EL DEL PROYECTO 01, MAS LA UOC

El proyecto 01 extraia ocho campos. Aca hace falta un noveno, la UOC, porque es
la mitad de la llave del registro (`84/129-0362-LPU26`). Es una extension
deliberada y no una correccion: el 01 medía extraccion, el 02 necesita
identificar. Distinto proposito, distinto contrato.

Del 01 tambien viene la DECISION de que modelo usar. Ese proyecto comparo cinco
variantes para responder una pregunta —donde se justifica pagar por un modelo—
y este consume la respuesta. **Los dos proyectos se conectan por una conclusion,
no por codigo compartido.**

================================================================================
PERMISOS Y TOPE DE GASTO

El agente corre con permisos acotados y verificables, no declarativos:

    lectura   data/entrada/   (avisos)      data/registro/  (CSV oficial)
    escritura reports/        y nada mas

`_permitir_escritura()` lo hace cumplir: cualquier ruta fuera de reports/ aborta
el proceso. Un permiso que solo esta escrito en el README no es un permiso.

El tope de gasto se evalua ANTES de cada llamada, con el costo estimado del
proximo caso. Si no entra, el agente se detiene y deja constancia de cuantos
casos quedaron sin procesar: preferimos una corrida incompleta y declarada a una
completa y sin presupuesto.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comun  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "entrada"
REPORTES = RAIZ / "reports"
ENV = RAIZ / ".env"

MODELO = "gemini-3.5-flash-lite"       # conclusión del proyecto 01
USD_IN, USD_OUT = 0.30, 2.50           # por millón de tokens, consultado 20/10/2026
PRESUPUESTO = 1.00                     # USD
TOKENS_EST = (800, 260)                # estimación para el control previo de gasto
CORTE_EN_SECO = 3                      # errores seguidos sin ningún éxito -> abortar


# --------------------------------------------------------------- permisos


def _permitir_escritura(p: Path) -> Path:
    """El agente sólo puede escribir dentro de reports/. Se hace cumplir."""
    p = p.resolve()
    if REPORTES.resolve() not in p.parents and p != REPORTES.resolve():
        sys.exit(f"PERMISO DENEGADO · el agente no puede escribir en {p}")
    return p


def cargar_env() -> None:
    if not ENV.exists():
        return
    for linea in ENV.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# --------------------------------------------------------------- esquema

CAMPOS = (
    ("uoc", "STRING", "Unidad Operativa de Contrataciones, como figura tras 'UOC:'. Formato NN/NN."),
    ("organismo", "STRING", "Repartición contratante, tal como figura en el aviso."),
    ("expediente", "STRING", "Número de expediente o actuación, completo."),
    ("tipo_procedimiento", "STRING", "Licitación Pública, Contratación Directa, etc. SIN el número."),
    ("numero_procedimiento", "STRING", "Número del llamado, habitualmente NN/AAAA."),
    ("objeto", "STRING", "Objeto de la contratación, en las palabras del aviso, sin resumir."),
    ("monto_estimado", "NUMBER", "Presupuesto oficial o monto estimado, en pesos. null si no figura."),
    ("fecha_apertura", "STRING", "Fecha y hora de apertura de ofertas, en ISO 8601."),
    ("valor_pliego", "NUMBER", "Valor del pliego. 0 si es gratuito, null si no se menciona."),
)

PROMPT = """\
Extraes datos de avisos de contratacion publica del Boletin Oficial argentino.

Reglas:
- Si un dato no figura explicitamente en el texto, devolve null. Nunca lo deduzcas.
- `uoc` es el numero que sigue a "UOC:", con su barra. Si el aviso no dice UOC,
  devolve null: significa que el organismo no tramita por el sistema central.
- `tipo_procedimiento` NO lleva el numero. "Licitacion Publica 0023/2026" es
  "Licitacion Publica"; el 0023/2026 va en `numero_procedimiento`.
- El expediente y el numero de procedimiento son cosas distintas. El expediente
  identifica la actuacion (suele empezar con EX-); el numero identifica el llamado.
- Los montos van como numero, sin simbolo ni separadores de miles.
- Las fechas en ISO 8601. La apertura es el acto de apertura de ofertas, NO la
  recepcion de ofertas ni el retiro del pliego.
- Si la primera linea es una categoria del indice del Boletin (LIMPIEZA,
  EFECTOS VARIOS, PRODUCTOS ALIMENTICIOS, VIALES, CIVILES), no es el organismo.
- El objeto va con las palabras del aviso, sin resumir ni reformular.

En `confianza` se honesto: un valor bajo cuando el aviso es ambiguo vale mas que
uno alto y equivocado, porque abajo del umbral esto va a revision humana.
"""


def esquema_google() -> dict:
    props = {c: {"type": t, "nullable": True, "description": d} for c, t, d in CAMPOS}
    props["confianza"] = {"type": "NUMBER", "description": "0 a 1. Qué tan seguro estás de la extracción."}
    return {"type": "OBJECT", "properties": props, "required": [c for c, _, _ in CAMPOS] + ["confianza"]}


def vacio() -> dict:
    d = {c: None for c, _, _ in CAMPOS}
    d["confianza"] = 0.0
    return d


# --------------------------------------------------------------- extraccion


def extraer(texto: str) -> dict:
    """Una llamada al modelo. Devuelve datos + telemetria + error."""
    t0 = time.perf_counter()
    try:
        import logging

        from google import genai
        from google.genai import types

        logging.getLogger("google_genai.models").setLevel(logging.ERROR)
        cli = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        r = cli.models.generate_content(
            model=MODELO,
            contents=texto[:60_000],
            config=types.GenerateContentConfig(
                system_instruction=PROMPT, temperature=0,
                response_mime_type="application/json", response_schema=esquema_google(),
            ),
        )
    except ImportError as e:
        return {"datos": vacio(), "error": f"falta el paquete: {e}", "tokens_in": 0, "tokens_out": 0, "ms": 0}
    except Exception as e:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        return {"datos": vacio(), "error": f"{type(e).__name__}: {e}", "tokens_in": 0, "tokens_out": 0, "ms": ms}

    ms = int((time.perf_counter() - t0) * 1000)
    u = getattr(r, "usage_metadata", None)
    try:
        datos = {**vacio(), **json.loads(r.text)}
    except (json.JSONDecodeError, TypeError) as e:
        return {"datos": vacio(), "error": f"json inválido: {e}", "tokens_in": 0, "tokens_out": 0, "ms": ms}
    return {"datos": datos, "error": None, "ms": ms,
            "tokens_in": getattr(u, "prompt_token_count", 0) or 0,
            "tokens_out": getattr(u, "candidates_token_count", 0) or 0}


def costo(tin: int, tout: int) -> float:
    return tin / 1e6 * USD_IN + tout / 1e6 * USD_OUT


# --------------------------------------------------------------- el agente


# Errores que se arreglan solos esperando: cupo por minuto, modelo saturado,
# conexion cortada. Los demas (clave invalida, modelo que no existe, esquema mal
# formado) no mejoran con reintentar y cada reintento cuesta tiempo y plata.
TRANSITORIOS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "INTERNAL",
                "ConnectError", "ReadTimeout", "Timeout", "ConnectionError")
ESPERAS = (5, 15, 40)


def es_transitorio(error: str) -> bool:
    return any(t.lower() in error.lower() for t in TRANSITORIOS)


def extraer_con_reintentos(texto: str, verboso: bool = True) -> dict:
    """extraer() con espera exponencial sobre los errores que se arreglan solos.

    Sin esto, un solo 429 en una corrida de 115 casos pierde el caso. El cupo
    gratuito de Google son 15 llamadas por minuto: a una llamada cada 2 o 3
    segundos se toca, y tocarlo no es un error del sistema.
    """
    r = extraer(texto)
    for i, espera in enumerate(ESPERAS, 1):
        if not r["error"] or not es_transitorio(r["error"]):
            return r
        if verboso:
            print(f"    transitorio ({r['error'][:60]}) · reintento {i}/{len(ESPERAS)} "
                  f"en {espera}s", flush=True)
        time.sleep(espera)
        r = extraer(texto)
    return r


def procesar(a: dict, idx: dict, umbral: float) -> dict:
    """Un caso de punta a punta. Devuelve el registro de traza completo."""
    caso = {"aviso": a["id"], "edicion": a["_meta"]["edicion"], "formato": a["_meta"]["formato"],
            "momento": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    r = extraer_con_reintentos(a["_texto"])
    caso |= {"modelo": MODELO, "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
             "latencia_ms": r["ms"], "costo_usd": round(costo(r["tokens_in"], r["tokens_out"]), 6),
             "confianza_extraccion": r["datos"].get("confianza")}

    if r["error"]:
        return caso | {"decision": "error_extraccion", "motivo": r["error"]}

    datos = r["datos"]
    caso["extraido"] = {c: datos.get(c) for c, _, _ in CAMPOS}

    k = comun.llave(datos.get("uoc"), datos.get("numero_procedimiento"))
    if not k:
        return caso | {"decision": "sin_llave",
                       "motivo": "el aviso no declara UOC: el organismo no tramita por COMPR.AR"}
    caso["llave"] = "-".join(k)

    cands = idx.get(k, [])
    if not cands:
        return caso | {"decision": "sin_registro",
                       "motivo": "la llave no existe en el registro: retraso de publicación o datos incompletos"}

    fila, conf, señales = comun.elegir(datos, cands, a["_meta"]["publicado_desde"])
    caso |= {"proceso": fila["Numero_Proceso"], "candidatos": len(cands),
             "confianza_emparejamiento": conf, "señales": señales}

    if conf < umbral:
        return caso | {"decision": "escalado",
                       "motivo": f"confianza {conf} por debajo del umbral {umbral}: puede no ser el mismo proceso"}

    comparacion = comun.comparar(datos, fila)
    disc = [c["campo"] for c in comparacion if c["estado"] == "difiere" and c["reportable"]]
    omit = [c["campo"] for c in comparacion if c["estado"] == "solo_en_registro"]
    return caso | {"decision": "aprobado", "comparacion": comparacion,
                   "discrepancias": disc, "omitidos_por_el_boletin": omit}


def main() -> None:
    ap = argparse.ArgumentParser(description="Agente conciliador de contrataciones públicas.")
    ap.add_argument("--limite", type=int, help="tope de casos")
    ap.add_argument("--umbral", type=float, default=comun.UMBRAL)
    ap.add_argument("--presupuesto", type=float, default=PRESUPUESTO, help="tope de gasto en USD")
    ap.add_argument("--solo-etiquetados", action="store_true",
                    help="sólo los avisos con etiqueta del proyecto 01 (para evaluar)")
    args = ap.parse_args()

    cargar_env()

    # CONTROL PREVIO. Las dos fallas que rompen las N llamadas por igual —no hay
    # clave, no esta el paquete— se chequean UNA vez, antes del bucle, y con el
    # comando exacto para arreglarlas.
    #
    # La primera corrida real escribio cinco `error_extraccion` identicos por un
    # paquete que faltaba. El agente se porto bien (gasto USD 0.0000, dejo la
    # traza, no se colgo y la reanudacion no cuenta los errores como hechos),
    # pero el bucle no tenia por que enterarse cinco veces de lo mismo: un error
    # que afecta a todos los casos no es un error POR caso.
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("Falta GOOGLE_API_KEY en .env — copiala de ../p01/.env")
    try:
        import google.genai  # noqa: F401
    except ImportError:
        sys.exit("Falta el paquete google-genai. Desde la raiz del proyecto:\n"
                 "    python -m venv .venv\n"
                 "    .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
                 "y volve a correr con .venv\\Scripts\\python.exe src\\agente.py")

    idx = comun.cargar_registro()
    meta = {r["id"]: r for r in json.loads((ENTRADA / "indice_p01.json").read_text(encoding="utf-8"))}
    etiquetados = {json.loads(l)["id"] for l in (ENTRADA / "etiquetas_p01.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}

    avisos = []
    for doc_id, m in sorted(meta.items()):
        if m.get("tipo") != "llamado":
            continue
        if args.solo_etiquetados and doc_id not in etiquetados:
            continue
        ruta = ENTRADA / "avisos" / m["txt"]
        if not ruta.exists():
            continue
        avisos.append({"id": doc_id, "_meta": m, "_texto": ruta.read_text(encoding="utf-8")})
    if args.limite:
        avisos = avisos[: args.limite]

    traza = _permitir_escritura(REPORTES / "traza.jsonl")
    auditoria = _permitir_escritura(REPORTES / "auditoria.jsonl")
    REPORTES.mkdir(exist_ok=True)

    hechos = set()
    if traza.exists():
        hechos = {json.loads(l)["aviso"] for l in traza.read_text(encoding="utf-8").splitlines()
                  if l.strip() and json.loads(l).get("decision") != "error_extraccion"}
    pendientes = [a for a in avisos if a["id"] not in hechos]

    print(f"avisos: {len(avisos)} llamados · ya procesados {len(hechos)} · a correr {len(pendientes)}")
    print(f"presupuesto: USD {args.presupuesto:.2f} · umbral de confianza {args.umbral}\n")
    if not pendientes:
        print("Nada pendiente.")
        return

    gastado = 0.0
    est = costo(*TOKENS_EST)
    cuenta: dict[str, int] = {}
    t0 = time.perf_counter()
    cortado = 0
    exitos = errores_seguidos = 0
    en_seco = None

    with traza.open("a", encoding="utf-8") as ft, auditoria.open("a", encoding="utf-8") as fa:
        for n, a in enumerate(pendientes, 1):
            # El control de gasto va ANTES de la llamada, con el costo estimado.
            if gastado + est > args.presupuesto:
                cortado = len(pendientes) - n + 1
                print(f"\nTOPE DE GASTO · USD {gastado:.4f} de {args.presupuesto:.2f}. "
                      f"Me detengo con {cortado} casos sin procesar.")
                break

            caso = procesar(a, idx, args.umbral)
            gastado += caso.get("costo_usd", 0.0)
            cuenta[caso["decision"]] = cuenta.get(caso["decision"], 0) + 1

            ft.write(json.dumps(caso, ensure_ascii=False) + "\n")
            ft.flush()
            fa.write(json.dumps({k: caso.get(k) for k in
                                 ("momento", "aviso", "decision", "motivo", "proceso",
                                  "confianza_emparejamiento", "discrepancias")},
                                ensure_ascii=False) + "\n")
            fa.flush()

            # CORTE EN SECO. Si nada funciono todavia y ya fallaron varios
            # seguidos, el problema no es de estos casos: es de la corrida. Un
            # error que afecta a todos no es un error POR caso, y escribirlo 115
            # veces no agrega informacion, solo ruido en la traza.
            if caso["decision"] == "error_extraccion":
                errores_seguidos += 1
            else:
                exitos += 1
                errores_seguidos = 0
            if exitos == 0 and errores_seguidos >= CORTE_EN_SECO:
                en_seco = caso["motivo"]
                cortado = len(pendientes) - n
                break

            if n % 10 == 0 or n == len(pendientes):
                seg = time.perf_counter() - t0
                print(f"  {n}/{len(pendientes)}  {seg:.0f}s  USD {gastado:.4f}  {dict(sorted(cuenta.items()))}",
                      flush=True)

    if en_seco:
        print(f"\nCORTE EN SECO · {CORTE_EN_SECO} errores seguidos y ningun caso resuelto.")
        print(f"  {en_seco}")
        print("  No sigo: el problema es de la corrida, no de los casos. Arreglalo y volve")
        print("  a correr el mismo comando — la traza no cuenta los errores como hechos.")
    print(f"\nGastado USD {gastado:.4f} de USD {args.presupuesto:.2f}")
    if cortado:
        print(f"Quedaron {cortado} casos sin procesar. Volvé a correr el mismo comando.")
    print(f"Traza en reports/traza.jsonl · auditoría en reports/auditoria.jsonl")
    print(f"Resumen:  python src/informe.py")


if __name__ == "__main__":
    main()
