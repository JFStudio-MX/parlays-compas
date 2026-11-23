# -*- coding: utf-8 -*-
"""Pregúntale a la IA: responde preguntas de stats ("¿cuántas yardas por tierra permite la defensa de los Chiefs?")
con TeamRankings y con los datos de ESPN que ya tiene la app.

No es un agente: el código controla los pasos.
  1) Claude lee la pregunta y dice qué buscar (deporte, estadísticas, equipos, jugadores) -> JSON.
  2) El programa busca en TeamRankings y en el historial de ESPN guardado en cache/.
  3) Claude contesta en español con esos números.

Necesita el paquete oficial:  python -m pip install anthropic
y una clave de https://console.anthropic.com en datos/config.json -> "anthropic_api_key"
(o en la variable de entorno ANTHROPIC_API_KEY)."""
import json
import os
import re
import unicodedata

import estadisticas
from nucleo import CACHE, DATOS, leer_json, rasgos

CONTEXTO = DATOS / "contexto_ia.json"
MODELO = "claude-opus-5-5"
PRECIO = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}

PLAN_ESQUEMA = {
    "type": "object",
    "properties": {
        "deporte": {"type": "string", "enum": ["nfl", "nba", "nhl", "ncaaf", "ncaab", "futbol", "ninguno"]},
        "busquedas": {"type": "array", "items": {"type": "string"}},
        "equipos": {"type": "array", "items": {"type": "string"}},
        "jugadores": {"type": "array", "items": {"type": "string"}},
        "partidos": {"type": "boolean"},
    },
    "required": ["deporte", "busquedas", "equipos", "jugadores", "partidos"],
    "additionalProperties": False,
}

SISTEMA_PLAN = """Ayudas a una app personal de apuestas deportivas a decidir qué datos buscar para contestar una pregunta.
Fuentes disponibles:
1) TeamRankings: tablas por equipo de NFL, NBA, NHL, NCAA americano (ncaaf) y NCAA básquet (ncaab), con valor de la temporada, últimos 3, último partido, en casa, de visita y temporada pasada. En "busquedas" escribe hasta 3 nombres de estadística EN INGLÉS como los usa TeamRankings, por ejemplo "opponent rushing yards per game", "points per game", "opponent three point pct", "turnovers per game", "possessions per game". "Opponent ..." es lo que permite la defensa. TeamRankings no tiene fútbol soccer: para fútbol deja busquedas vacío.
2) ESPN (datos de la app): últimos 10 partidos de cada equipo con marcador, estadísticas por partido de jugadores, partidos de la semana con momios, lesiones y contexto.
En "equipos" pon el nombre completo como en ESPN (ej. "Kansas City Chiefs"); en "jugadores" el nombre completo. "partidos" es true si preguntan por un partido que viene (momios, quién gana, lesiones, etc.).
Si la pregunta no tiene que ver con deportes, deporte = "ninguno" y listas vacías."""

SISTEMA_RESPUESTA = """Eres el analista de la app de apuestas de Josh (México). Contesta en español mexicano, directo y corto (unas 150 palabras salvo que pidan más).
Usa solo los datos que vienen en el mensaje. Si un dato no está, dilo y di dónde verlo; no inventes números.
Da números concretos y el lugar en el ranking aclarando qué significa (en tablas de "Opponent", el 1 es la defensa que menos permite).
Cita la fuente en una línea al final (TeamRankings: temporada / últimos 3, o ESPN: últimos partidos).
Si te piden opinión sobre una apuesta, da los números a favor y en contra y una lectura honesta; no prometas resultados."""


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _cliente(cfg):
    import anthropic
    clave = (cfg.get("anthropic_api_key") or "").strip()
    return anthropic, (anthropic.Anthropic(api_key=clave) if clave else anthropic.Anthropic())


def estado(cfg):
    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    clave = bool((cfg.get("anthropic_api_key") or "").strip() or os.environ.get("ANTHROPIC_API_KEY"))
    return {"sdk": sdk, "clave": clave, "modelo": cfg.get("ia_modelo") or MODELO}


def _llamar(anthropic, client, cfg, sistema, mensajes, effort, formato=None):
    """Una llamada a Claude con los respaldos del servidor activados (si el modelo rechaza, otro modelo lo intenta)."""
    params = dict(model=cfg.get("ia_modelo") or MODELO, max_tokens=16000, system=sistema, messages=mensajes,
                  output_config={"effort": effort, **({"format": formato} if formato else {})})
    try:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    except (TypeError, anthropic.BadRequestError):  # paquete viejo o combinación no aceptada: sin respaldo
        return client.messages.create(**params)


def _texto(resp):
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


# --------------------------------------------------------------------------- datos locales (ESPN)

def _contexto():
    return leer_json(CONTEXTO, {"juegos": [], "historial": {}})


def _buscar_equipo(nombre, ctx):
    n = _norm(nombre)
    for g in ctx["juegos"]:
        for l in ("L", "V"):
            e = g[l]
            if n and (n == _norm(e["nombre"]) or n in _norm(e["nombre"]) or _norm(e["corto"]) == n
                      or _norm(e["abbr"]) == n):
                return g, l
    return None, None


def _recs(ctx, lh, tid):
    out = []
    for liga_ev, eid in ctx["historial"].get(f"{lh}|{tid}", []):
        r = leer_json(CACHE / "partidos" / liga_ev / f"{eid}.json", None)
        if r:
            out.append(r)
    return out


def _ultimos(g, lado, ctx):
    e = g[lado]
    base = g["base"]
    res = []
    for r in _recs(ctx, e["liga_hist"], e["id"]):
        f = rasgos(r, e["id"], base)
        if not f:
            continue
        x = {"fecha": f["fecha"][:10], "rival": f["rival"], "local": f["local"], "marcador": f"{f['pf']:g}-{f['pa']:g}"}
        if base == "nfl":  # yardas propias y permitidas (suma de jugadores)
            opp = next((k for k in r["eq"] if k != e["id"]), None)
            suma = lambda tid, k: sum((j.get(k) or 0) for j in (r["jug"].get(tid) or {}).values())
            x.update(yd_tierra=suma(e["id"], "ruy"), yd_pase=suma(e["id"], "pyd"),
                     yd_tierra_permitidas=suma(opp, "ruy"), yd_pase_permitidas=suma(opp, "pyd"))
        if base == "futbol":
            x.update(corners=f.get("corf"), corners_rival=f.get("corc"), tarjetas=f.get("tarf"))
        res.append(x)
    return res


CAMPOS = {"nba": ["min", "pts", "reb", "ast", "tpm", "pra"], "nhl": ["min", "gol", "asis", "sog", "sv"],
          "nfl": ["pyd", "ptd", "ruy", "ratt", "recs", "rey", "tgt", "td"], "futbol": ["tir", "tap", "gol", "tar"]}


def _jugador(nombre, ctx):
    n = _norm(nombre)
    for g in ctx["juegos"]:
        for l in ("L", "V"):
            e = g[l]
            recs = _recs(ctx, e["liga_hist"], e["id"])
            lineas, quien = [], None
            for r in recs:
                for pid, st in (r["jug"].get(e["id"]) or {}).items():
                    if n and n in _norm(st.get("n")):
                        quien = st.get("n")
                        lineas.append({"fecha": r["fecha"][:10],
                                       **{k: st.get(k) for k in CAMPOS.get(g["base"], []) if st.get(k) is not None}})
            if lineas:
                return {"jugador": quien, "equipo": e["nombre"], "proximo": f"{g['V']['corto']} @ {g['L']['corto']} {g['fecha'][:10]}",
                        "partidos": lineas}
    return None


def _juntar(plan, ctx):
    datos = {}
    tipo = plan.get("deporte")
    nombres_eq = []
    for q in plan.get("equipos", [])[:3]:
        g, l = _buscar_equipo(q, ctx)
        if g:
            nombres_eq.append(g[l]["nombre"])
            datos.setdefault("equipos_espn", []).append({
                "equipo": g[l]["nombre"], "forma_ultimos_5": g[l].get("forma"), "descanso_dias": g[l].get("descanso"),
                "proximo_partido": {"partido": f"{g['V']['nombre']} @ {g['L']['nombre']}", "fecha": g["fecha"],
                                    "liga": g["liga_nombre"], "momios": g.get("momios"), "contexto": g.get("previo"),
                                    "lesiones": g.get("lesiones"), "picks_de_la_app": g.get("picks", [])}
                if plan.get("partidos") else f"{g['V']['corto']} @ {g['L']['corto']} {g['fecha'][:10]}",
                "ultimos_partidos": _ultimos(g, l, ctx)})
    if tipo in estadisticas.DEP_TR:
        for q in plan.get("busquedas", [])[:3]:
            cands = estadisticas.buscar(tipo, q, 3)
            if not cands:
                continue
            st = estadisticas.leer(tipo, cands[0]["slug"])
            if not st:
                continue
            filas = st["filas"]
            elegidas = [f for f in filas if any(estadisticas.es_equipo(f, n) for n in nombres_eq)]
            muestra = elegidas + [f for f in filas[:3] + filas[-3:] if f not in elegidas] if elegidas else filas
            datos.setdefault("teamrankings", []).append({
                "estadistica": st["nombre"], "columnas": ["rank", "equipo"] + st["columnas"], "total_equipos": len(filas),
                "filas": [[f["rank"], f["equipo"]] + f["valores"] for f in muestra], "url": st["url"]})
    for q in plan.get("jugadores", [])[:3]:
        j = _jugador(q, ctx)
        if j:
            datos.setdefault("jugadores_espn", []).append(j)
    return datos


# --------------------------------------------------------------------------- principal

def preguntar(pregunta, previas, cfg):
    pregunta = (pregunta or "").strip()[:600]
    if not pregunta:
        return {"error": "Escribe una pregunta."}
    try:
        anthropic, client = _cliente(cfg)
    except ImportError:
        return {"error": "Falta instalar el paquete de la IA: abre una terminal y corre  python -m pip install anthropic"}
    ctx = _contexto()
    partidos = "\n".join(f"{g['liga_nombre']}: {g['V']['nombre']} @ {g['L']['nombre']} ({g['fecha'][:10]})"
                         for g in ctx["juegos"])
    charla = "".join(f"Pregunta anterior: {x.get('p', '')}\nRespuesta anterior: {x.get('r', '')[:600]}\n"
                     for x in (previas or [])[-2:])
    uso = {"in": 0, "out": 0}
    try:
        r1 = _llamar(anthropic, client, cfg, SISTEMA_PLAN, [{"role": "user", "content":
                     f"{charla}Pregunta: {pregunta}\n\nPartidos de la semana en la app:\n{partidos}"}], "low",
                     {"type": "json_schema", "schema": PLAN_ESQUEMA})
        if r1.stop_reason == "refusal":
            return {"error": "La IA no quiso responder esa pregunta."}
        uso["in"] += r1.usage.input_tokens
        uso["out"] += r1.usage.output_tokens
        plan = json.loads(_texto(r1) or "{}")
        datos = _juntar(plan, ctx) if plan.get("deporte") != "ninguno" else {}
        r2 = _llamar(anthropic, client, cfg, SISTEMA_RESPUESTA, [{"role": "user", "content":
                     f"{charla}Pregunta: {pregunta}\n\nDatos que encontró la app (JSON):\n"
                     f"{json.dumps(datos, ensure_ascii=False, default=str)}"}], "medium")
        if r2.stop_reason == "refusal":
            return {"error": "La IA no quiso responder esa pregunta."}
        uso["in"] += r2.usage.input_tokens
        uso["out"] += r2.usage.output_tokens
    except anthropic.AuthenticationError:
        return {"error": "La clave de la IA no sirve. Revisa anthropic_api_key en datos/config.json."}
    except anthropic.PermissionDeniedError:
        return {"error": "Tu clave no tiene permiso para ese modelo."}
    except anthropic.RateLimitError:
        return {"error": "Muchas preguntas seguidas: espera un minuto."}
    except anthropic.APIStatusError as e:
        return {"error": f"La IA respondió con un error ({e.status_code}). Intenta otra vez."}
    except anthropic.APIConnectionError:
        return {"error": "Sin conexión con la IA. Revisa tu internet."}
    pin, pout = PRECIO.get(cfg.get("ia_modelo") or MODELO, (4.0, 20.0))
    costo = (uso["in"] * pin + uso["out"] * pout) / 1_000_000
    fuentes = [t["url"] for t in datos.get("teamrankings", [])]
    if datos.get("equipos_espn") or datos.get("jugadores_espn"):
        fuentes.append("ESPN (historial guardado en la app)")
    return {"respuesta": _texto(r2), "fuentes": fuentes, "costo_usd": round(costo, 4), "plan": plan}
