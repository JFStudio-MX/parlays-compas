# -*- coding: utf-8 -*-
"""Contexto de cada partido: descanso, enfrentamientos directos, pronóstico de ESPN, portero probable (NHL),
clima (NFL), árbitro (fútbol) y qué permite cada rival por posición."""
from datetime import timedelta

from nucleo import B, a_mx, get_json, media, num

CLIMA_ES = {"sunny": "Soleado", "mostly sunny": "Casi soleado", "partly sunny": "Parcialmente soleado",
            "clear": "Despejado", "mostly clear": "Casi despejado", "cloudy": "Nublado", "mostly cloudy": "Muy nublado",
            "partly cloudy": "Parcialmente nublado", "intermittent clouds": "Nubes intermitentes",
            "rain": "Lluvia", "showers": "Chubascos", "light rain": "Lluvia ligera", "snow": "Nieve",
            "flurries": "Nevadas ligeras", "fog": "Niebla", "windy": "Viento", "thunderstorms": "Tormentas",
            "overcast": "Cielo cubierto", "hazy sunshine": "Sol con bruma"}


def previo(j):
    """Lo que ESPN trae del partido antes de jugarse (1 petición, guardada 1 hora)."""
    s = get_json(f"{B}/{j['sport']}/{j['liga']}/summary?event={j['id']}", ttl=3600)
    out = {}
    if not s:
        return out
    # pronóstico de ESPN (NBA BPI / NFL FPI)
    pr = s.get("predictor") or {}
    h, a = pr.get("homeTeam") or {}, pr.get("awayTeam") or {}
    if num(h.get("gameProjection")) is not None:
        out["espn"] = {"L": num(h.get("gameProjection")), "V": num(a.get("gameProjection"))}
    # enfrentamientos directos
    ss = s.get("seasonseries") or []
    if ss:
        x = ss[0]
        partidos = []
        for e in x.get("events") or []:
            st = e.get("statusType") or {}
            if not (st.get("completed") or e.get("status") == "post"):
                continue
            cs = {c.get("homeAway"): c for c in e.get("competitors") or []}
            if "home" not in cs or "away" not in cs:
                continue
            ab = lambda c: ((c.get("team") or {}).get("abbreviation") or "?")
            sc = lambda c: c.get("score") if not isinstance(c.get("score"), dict) else c["score"].get("displayValue")
            partidos.append({"fecha": (e.get("date") or "")[:10], "L": ab(cs["home"]), "Ls": sc(cs["home"]),
                             "V": ab(cs["away"]), "Vs": sc(cs["away"])})
        resumen = x.get("summary") or x.get("description") or ""
        if partidos or (resumen and "starts" not in resumen.lower()):
            out["h2h"] = {"titulo": traducir_serie(resumen), "partidos": partidos[:5]}
    # porteros probables (NHL)
    gl = s.get("goalies") or {}
    for side, lado in (("homeTeam", "L"), ("awayTeam", "V")):
        ath = (gl.get(side) or {}).get("athletes") or []
        if ath:
            out.setdefault("porteros", {})[lado] = {"id": str(ath[0].get("id")), "nombre": ath[0].get("displayName")}
    gi = s.get("gameInfo") or {}
    # clima (NFL al aire libre)
    w = gi.get("weather")
    if w:
        t = num(w.get("temperature"))
        g = num(w.get("gust"))
        out["clima"] = {"temp_c": round((t - 32) * 5 / 9) if t is not None else None,
                        "rafaga_kmh": round(g * 1.609) if g is not None else None,
                        "lluvia": num(w.get("precipitation"))}
    of = [o.get("displayName") for o in gi.get("officials") or [] if o.get("displayName")]
    if of:
        out["arbitro"] = of[0]
    return out


def traducir_serie(t):
    t = t or ""
    for a, b in (("Series tied", "Serie empatada"), ("leads series", "gana la serie"), ("Series starts", "Serie empieza"),
                 ("won series", "ganó la serie"), ("Last 5 Matchups", "Últimos 5")):
        t = t.replace(a, b)
    return t


def clima_texto(cond):
    if not cond:
        return ""
    return CLIMA_ES.get(cond.strip().lower(), cond)


def descanso(eventos, fecha_iso):
    """Días desde su partido anterior (jugado o programado) antes de este."""
    t = a_mx(fecha_iso)
    antes = [a_mx(e["date"]) for e in eventos if a_mx(e["date"]) < t - timedelta(hours=3)]
    if not antes:
        return None
    return (t.date() - max(antes).date()).days


# --------------------------------------------------------------------------- qué permite cada rival

def defensa_rival(base, historial):
    """historial: {tid: [recs de ese equipo]} de una misma liga.
    Devuelve factor(tid_rival, stat, pos) = lo que permite ese rival / promedio de la liga."""
    from mercados import PROPS
    stats = [s for s, _, _ in PROPS[base]]
    permite = {}  # tid -> {(pos, stat): promedio por partido}
    for tid, recs in historial.items():
        acum, n = {}, 0
        for rec in recs:
            opp = next((k for k in rec["eq"] if k != tid), None)
            jug = rec["jug"].get(opp) if opp else None
            if not jug:
                continue
            n += 1
            for st in jug.values():
                pos = (st.get("pos") or "?") if base == "nba" else "*"
                for s in stats:
                    v = st.get(s)
                    if isinstance(v, (int, float)):
                        acum[(pos, s)] = acum.get((pos, s), 0) + v
        if n >= 5:
            permite[tid] = {k: v / n for k, v in acum.items()}
    if len(permite) < 4:
        return lambda tid, stat, pos: None
    claves = {k for d in permite.values() for k in d}
    liga = {k: media([d.get(k, 0) for d in permite.values()]) for k in claves}

    def factor(tid, stat, pos):
        d = permite.get(tid)
        k = ((pos or "?") if base == "nba" else "*", stat)
        if not d or not liga.get(k):
            return None
        return d.get(k, 0) / liga[k]
    return factor


# --------------------------------------------------------------------------- árbitros (fútbol)

def tarjetas_por_arbitro(recs):
    """{árbitro: (promedio de tarjetas, partidos)} y el promedio general."""
    por, todos = {}, []
    for rec in recs:
        arb = (rec.get("arb") or [None])[0]
        tar = [e["st"].get("tar") for e in rec["eq"].values()]
        if None in tar or len(tar) != 2:
            continue
        t = sum(tar)
        todos.append(t)
        if arb:
            por.setdefault(arb, []).append(t)
    return {a: (sum(v) / len(v), len(v)) for a, v in por.items()}, (media(todos) if todos else None)


# --------------------------------------------------------------------------- porteros (NHL)

def porteros_historial(recs, tid):
    """Quién abrió cada partido reciente (el portero con más minutos)."""
    abridores = []
    for rec in recs:
        gs = [(st.get("min") or 0, st.get("n"), pid) for pid, st in (rec["jug"].get(tid) or {}).items() if st.get("portero")]
        if gs:
            abridores.append(max(gs))
    cuenta = {}
    for _, n, pid in abridores:
        cuenta[(pid, n)] = cuenta.get((pid, n), 0) + 1
    return abridores, cuenta
