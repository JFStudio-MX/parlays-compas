# -*- coding: utf-8 -*-
"""Mercados: apuestas de equipo y de jugador, candados, joyitas, combinadas del mismo partido
y el armador de parlays."""
import math
import statistics

from nucleo import (BASE, PA_UMBRAL, decimal, est_de, evaluar_regla, media, momio_pata, momio_prob,
                    sin_vig)

PICKS = {}
_pid = [0]


def nuevo_pick(**kw):
    _pid[0] += 1
    kw["id"] = f"p{_pid[0]}"
    PICKS[kw["id"]] = kw
    return kw


def estimar(hits, n, p_mkt=None):
    # Con momio real, la casa pesa como 30 partidos: en ganador/hándicap/total casi siempre tiene razón,
    # y 15 de 20 en una muestra chica es en buena parte suerte.
    if p_mkt:
        return (hits + 30 * p_mkt) / (n + 30)
    return (hits + 1) / (n + 2)


def _v(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def media5(x):
    return math.floor(x) + 0.5


def fmt_linea(x):
    return f"{x:+g}" if x else "0"


# =========================================================================== equipo

def evaluar_equipo(j, hL, hV, fam, texto, vL, okL, vV, okV, orden=0, momio=None, p_mkt=None, sub=""):
    sL = [(vL(f), okL(f)) for f in hL if vL(f) is not None]
    sV = [(vV(f), okV(f)) for f in hV if vV(f) is not None]
    if len(sL) < 4 or len(sV) < 4:
        return None
    n = len(sL) + len(sV)
    hits = sum(o for _, o in sL) + sum(o for _, o in sV)
    h5 = sum(o for _, o in sL[:5]) + sum(o for _, o in sV[:5])
    n5 = len(sL[:5]) + len(sV[:5])
    # en su cancha: local en casa + visita de visita
    cL = [okL(f) for f in hL if f["local"] and vL(f) is not None]
    cV = [okV(f) for f in hV if not f["local"] and vV(f) is not None]
    est = estimar(hits, n, p_mkt)
    return nuevo_pick(
        juego=j["id"], deporte=j["tipo"], liga=j["liga_nombre"], clase="equipo", fam=fam, orden=orden,
        texto=texto, sub=sub, hits=hits, n=n, h5=h5, n5=n5, est=round(est, 3),
        momio=momio, real=momio is not None, p_mkt=round(p_mkt, 3) if p_mkt else None,
        justo=momio_prob(est), cancha=[sum(cL) + sum(cV), len(cL) + len(cV)],
        serie=[[[_v(v), o] for v, o in sL], [[_v(v), o] for v, o in sV]],
        nombres=[j["L"]["abbr"], j["V"]["abbr"]], tags=[],
    )


LADO_FAM = {"h1_L": "L", "h1_V": "V", "ml_L": "L", "dc_L": "L", "hcp_L": "L", "gL_o": "L", "corL_o": "L", "spa_L": "L",
            "ml_V": "V", "dc_V": "V", "hcp_V": "V", "gV_o": "V", "corV_o": "V", "spa_V": "V"}


def regla_equipo(fam, orden, j):
    """Cómo se califica la apuesta con el resultado final (ver nucleo.evaluar_regla)."""
    L, V = j["L"]["id"], j["V"]["id"]
    m, tid, op, x = {
        "ml_L": ("margen", L, ">", 0), "ml_V": ("margen", V, ">", 0), "emp": ("margen", L, "==", 0),
        "dc_L": ("margen", L, ">=", 0), "dc_V": ("margen", V, ">=", 0),
        "spa_L": ("mlf", L, ">=", 1), "spa_V": ("mlf", V, ">=", 1),
        "hcp_L": ("margen", L, ">", orden), "hcp_V": ("margen", V, ">", orden),
        "tot_o": ("total", None, ">", orden), "tot_u": ("total", None, "<", -orden),
        "h1_L": ("m1mg", L, ">", orden), "h1_V": ("m1mg", V, ">", orden),
        "m1_o": ("m1", None, ">", orden), "m1_u": ("m1", None, "<", -orden),
        "btts_si": ("btts", None, "==", 1), "btts_no": ("btts", None, "==", 0),
        "gL_o": ("pf", L, ">", orden), "gV_o": ("pf", V, ">", orden),
        "cor_o": ("cor", None, ">", orden), "cor_u": ("cor", None, "<", -orden),
        "corL_o": ("corf", L, ">", orden), "corV_o": ("corf", V, ">", orden),
        "tar_o": ("tar", None, ">", orden), "tar_u": ("tar", None, "<", -orden),
    }[fam]
    return {"k": "eq", "m": m, "tid": tid or L, "op": op, "x": x}


def pago_anticipado_pick(p, j, hL, hV):
    """Probabilidad del 'gana' contando el Pago Anticipado de Caliente (ventaja de 20 NBA / 17 NFL / 2 goles)."""
    thr = PA_UMBRAL.get(j["tipo"])
    if not thr or p["fam"] not in ("ml_L", "ml_V"):
        return None
    yo, otro = (hL, hV) if p["fam"] == "ml_L" else (hV, hL)
    a = [f["margen"] > 0 or f["mlf"] >= thr for f in yo if f.get("mlf") is not None]
    b = [f["margen"] < 0 or f["mlc"] >= thr for f in otro if f.get("mlc") is not None]
    a0 = [f["margen"] > 0 for f in yo if f.get("mlf") is not None]
    b0 = [f["margen"] < 0 for f in otro if f.get("mlc") is not None]
    n = len(a) + len(b)
    if n < 8:
        return None
    hits_pa, hits = sum(a) + sum(b), sum(a0) + sum(b0)
    extra = max(0.0, (hits_pa - hits) / n) * 0.85  # lo que suma el PA según su historia
    return {"est": round(min(0.99, p["est"] + extra), 3), "hits": hits_pa, "n": n, "umbral": thr,
            "extra": round(extra, 3)}


def mercados_equipo(j, hL, hV):
    t, m = j["base"], j["momios"] or {}
    L, V = j["L"]["corto"], j["V"]["corto"]
    out = []

    def add(*a, **k):
        p = evaluar_equipo(j, hL, hV, *a, **k)
        if p:
            out.append(p)

    mg = lambda f: f["margen"]
    tot = lambda f: f["total"]
    unidad = {"nba": "puntos", "nfl": "puntos", "nhl": "goles", "futbol": "goles"}[t]

    # ---- ganador
    if t == "futbol":
        pL, pE, pV = sin_vig(m.get("ml_L"), m.get("ml_E"), m.get("ml_V"))
        add("ml_L", f"Gana {L}", mg, lambda f: f["margen"] > 0, mg, lambda f: f["margen"] < 0,
            momio=m.get("ml_L"), p_mkt=pL, sub="Resultado final")
        add("ml_V", f"Gana {V}", mg, lambda f: f["margen"] < 0, mg, lambda f: f["margen"] > 0,
            momio=m.get("ml_V"), p_mkt=pV, sub="Resultado final")
        add("emp", "Empate", mg, lambda f: f["margen"] == 0, mg, lambda f: f["margen"] == 0,
            momio=m.get("ml_E"), p_mkt=pE, sub="Resultado final")
        # Súper Pago Anticipado: se paga con ir ganando por 1 gol en cualquier momento del partido
        mf, mc = lambda f: f.get("mlf"), lambda f: f.get("mlc")
        sub_spa = "Súper Pago Anticipado: con ir ganando por 1 gol se paga"
        add("spa_L", f"Gana {L} (Súper PA)", mf, lambda f: f["mlf"] >= 1, mc, lambda f: f["mlc"] >= 1, sub=sub_spa)
        add("spa_V", f"Gana {V} (Súper PA)", mc, lambda f: f["mlc"] >= 1, mf, lambda f: f["mlf"] >= 1, sub=sub_spa)
        add("dc_L", f"{L} o empate", mg, lambda f: f["margen"] >= 0, mg, lambda f: f["margen"] <= 0,
            p_mkt=(pL + pE) if pL else None, sub="Doble oportunidad")
        add("dc_V", f"{V} o empate", mg, lambda f: f["margen"] <= 0, mg, lambda f: f["margen"] >= 0,
            p_mkt=(pV + pE) if pV else None, sub="Doble oportunidad")
        add("hcp_L", f"{L} +1.5", mg, lambda f: f["margen"] > -1.5, mg, lambda f: f["margen"] < 1.5,
            orden=-1.5, sub="Hándicap (no pierde por 2 o más)")
        add("hcp_V", f"{V} +1.5", mg, lambda f: f["margen"] < 1.5, mg, lambda f: f["margen"] > -1.5,
            orden=-1.5, sub="Hándicap (no pierde por 2 o más)")
    else:
        pL, pV = sin_vig(m.get("ml_L"), m.get("ml_V"))
        sub = "Ganador (incl. prórroga)"
        add("ml_L", f"Gana {L}", mg, lambda f: f["margen"] > 0, mg, lambda f: f["margen"] < 0,
            momio=m.get("ml_L"), p_mkt=pL, sub=sub)
        add("ml_V", f"Gana {V}", mg, lambda f: f["margen"] < 0, mg, lambda f: f["margen"] > 0,
            momio=m.get("ml_V"), p_mkt=pV, sub=sub)
        s = m.get("sp_L")
        if t == "nhl":
            lineas = {"L": [-1.5, 1.5], "V": [-1.5, 1.5]}
        elif s is not None:
            alts = [0, 5, 10] if t == "nba" else [0, 3, 7, 10]
            lineas = {"L": [s + a for a in alts], "V": [-s + a for a in alts]}
        else:
            lineas = {"L": [], "V": []}
        psL, psV = sin_vig(m.get("sp_L_m"), m.get("sp_V_m"))
        for x in lineas["L"]:
            real = s is not None and abs(x - s) < 0.01
            add("hcp_L", f"{L} {fmt_linea(x)}", mg, lambda f, x=x: f["margen"] + x > 0,
                mg, lambda f, x=x: -f["margen"] + x > 0, orden=-x,
                momio=m.get("sp_L_m") if real else None, p_mkt=psL if real else None, sub="Hándicap")
        for x in lineas["V"]:
            real = s is not None and abs(x + s) < 0.01
            add("hcp_V", f"{V} {fmt_linea(x)}", mg, lambda f, x=x: -f["margen"] + x > 0,
                mg, lambda f, x=x: f["margen"] + x > 0, orden=-x,
                momio=m.get("sp_V_m") if real else None, p_mkt=psV if real else None, sub="Hándicap")

    # ---- totales
    T = m.get("total")
    if T is None:
        tots = [f["total"] for f in hL + hV]
        T = media5(sorted(tots)[len(tots) // 2]) if tots else None
    if T is not None:
        lad = {"nba": [-15, -10, -5, 0, 5, 10], "nfl": [-10, -7, -3, 0, 3, 7], "nhl": None, "futbol": None}[t]
        if lad is not None:
            lineas = [T + a for a in lad]
        elif t == "nhl":
            lineas = sorted({4.5, 5.5, 6.5, 7.5, T})
        else:
            lineas = sorted({0.5, 1.5, 2.5, 3.5, 4.5, T})
        po, pu = sin_vig(m.get("over_m"), m.get("under_m"))
        for x in lineas:
            real = m.get("total") is not None and abs(x - m["total"]) < 0.01
            add("tot_o", f"Más de {x:g} {unidad}", tot, lambda f, x=x: f["total"] > x, tot,
                lambda f, x=x: f["total"] > x, orden=x, momio=m.get("over_m") if real else None,
                p_mkt=po if real else None, sub="Total del partido")
            add("tot_u", f"Menos de {x:g} {unidad}", tot, lambda f, x=x: f["total"] < x, tot,
                lambda f, x=x: f["total"] < x, orden=-x, momio=m.get("under_m") if real else None,
                p_mkt=pu if real else None, sub="Total del partido")

    # ---- primera mitad / periodo
    m1 = lambda f: f.get("m1")
    if t in ("nba", "nfl") and T:
        b = media5(T / 2)
        lineas = [b + a for a in ([-10, -5, 0, 5] if t == "nba" else [-7, -3, 0, 3])]
        nom = "1a mitad"
    elif t == "nhl":
        lineas, nom = [0.5, 1.5, 2.5], "1er periodo"
    else:
        lineas, nom = [0.5, 1.5, 2.5], "1er tiempo"
    for x in lineas:
        add("m1_o", f"{nom}: más de {x:g} {unidad}", m1, lambda f, x=x: f["m1"] > x, m1,
            lambda f, x=x: f["m1"] > x, orden=x, sub=nom.capitalize())
        add("m1_u", f"{nom}: menos de {x:g} {unidad}", m1, lambda f, x=x: f["m1"] < x, m1,
            lambda f, x=x: f["m1"] < x, orden=-x, sub=nom.capitalize())

    # ---- hándicap de la 1a mitad / 1er periodo / 1er tiempo (con la ventaja al descanso)
    h1 = lambda f: f.get("m1mg")
    s = m.get("sp_L")
    if t in ("nba", "nfl"):
        if s is not None:
            b = media5(s / 2) if s >= 0 else -media5(-s / 2)  # la línea de mitad suele ser la mitad del spread
            alts = [0, 3, 6] if t == "nba" else [0, 3, 7]
            h1lin = {"L": [b + a for a in alts], "V": [-b + a for a in alts]}
        else:
            h1lin = {"L": [0.5, 3.5], "V": [0.5, 3.5]}
    else:  # NHL y fútbol: gana el periodo (-0.5), no lo pierde (+0.5), no pierde por 2 (+1.5)
        h1lin = {"L": [-0.5, 0.5, 1.5], "V": [-0.5, 0.5, 1.5]}
    txt_h1 = {-0.5: "gana el {n}", 0.5: "no pierde el {n}", 1.5: "+1.5 en el {n}"}
    for lado, nomb in (("L", L), ("V", V)):
        for x in h1lin[lado]:
            if t in ("nhl", "futbol"):
                texto = f"{nomb} {txt_h1[x].format(n=nom)}"
            else:
                texto = f"{nomb} {fmt_linea(x)} ({nom})"
            if lado == "L":
                add("h1_L", texto, h1, lambda f, x=x: f["m1mg"] + x > 0, h1, lambda f, x=x: -f["m1mg"] + x > 0,
                    orden=-x, sub=f"Hándicap {nom}")
            else:
                add("h1_V", texto, h1, lambda f, x=x: -f["m1mg"] + x > 0, h1, lambda f, x=x: f["m1mg"] + x > 0,
                    orden=-x, sub=f"Hándicap {nom}")

    if t == "futbol":
        ambos = lambda f: f"{int(f['pf'])}-{int(f['pa'])}"
        add("btts_si", "Ambos anotan: Sí", ambos, lambda f: f["pf"] > 0 and f["pa"] > 0, ambos,
            lambda f: f["pf"] > 0 and f["pa"] > 0, sub="Ambos equipos anotan")
        add("btts_no", "Ambos anotan: No", ambos, lambda f: not (f["pf"] > 0 and f["pa"] > 0), ambos,
            lambda f: not (f["pf"] > 0 and f["pa"] > 0), sub="Ambos equipos anotan")
        for x in (0.5, 1.5, 2.5):
            add("gL_o", f"{L}: más de {x:g} goles", lambda f: f["pf"], lambda f, x=x: f["pf"] > x,
                lambda f: f["pa"], lambda f, x=x: f["pa"] > x, orden=x, sub=f"Goles de {L}")
            add("gV_o", f"{V}: más de {x:g} goles", lambda f: f["pa"], lambda f, x=x: f["pa"] > x,
                lambda f: f["pf"], lambda f, x=x: f["pf"] > x, orden=x, sub=f"Goles de {V}")
        cor = lambda f: f.get("cor")
        for x in (7.5, 8.5, 9.5, 10.5, 11.5):
            add("cor_o", f"Más de {x:g} córners", cor, lambda f, x=x: f["cor"] > x, cor,
                lambda f, x=x: f["cor"] > x, orden=x, sub="Córners totales")
            add("cor_u", f"Menos de {x:g} córners", cor, lambda f, x=x: f["cor"] < x, cor,
                lambda f, x=x: f["cor"] < x, orden=-x, sub="Córners totales")
        for x in (2.5, 3.5, 4.5, 5.5, 6.5, 7.5):
            add("corL_o", f"{L}: más de {x:g} córners", lambda f: f.get("corf"), lambda f, x=x: f["corf"] > x,
                lambda f: f.get("corc"), lambda f, x=x: f["corc"] > x, orden=x, sub=f"Córners de {L}")
            add("corV_o", f"{V}: más de {x:g} córners", lambda f: f.get("corc"), lambda f, x=x: f["corc"] > x,
                lambda f: f.get("corf"), lambda f, x=x: f["corf"] > x, orden=x, sub=f"Córners de {V}")
        tar = lambda f: f.get("tar")
        for x in (2.5, 3.5, 4.5, 5.5, 6.5):
            add("tar_o", f"Más de {x:g} tarjetas", tar, lambda f, x=x: f["tar"] > x, tar,
                lambda f, x=x: f["tar"] > x, orden=x, sub="Tarjetas totales")
            add("tar_u", f"Menos de {x:g} tarjetas", tar, lambda f, x=x: f["tar"] < x, tar,
                lambda f, x=x: f["tar"] < x, orden=-x, sub="Tarjetas totales")
    for p in out:
        lado = LADO_FAM.get(p["fam"])
        p["lado"] = lado
        p["quien"] = j[lado]["nombre"] if lado else "Partido"
        p["apuesta"] = p["texto"]
        p["regla"] = regla_equipo(p["fam"], p["orden"], j)
        pa = pago_anticipado_pick(p, j, hL, hV)
        if pa:
            p["pa"] = pa
    return out


# =========================================================================== jugadores

PROPS = {
    "nba": [("pts", "puntos", [10, 15, 20, 25, 30, 35, 40]), ("reb", "rebotes", [4, 6, 8, 10, 12, 14]),
            ("ast", "asistencias", [3, 4, 6, 8, 10, 12]), ("tpm", "triples", [1, 2, 3, 4, 5, 6]),
            ("pra", "pts+reb+ast", [15, 20, 25, 30, 35, 40, 45, 50])],
    "nhl": [("pto", "punto(s)", [1, 2]), ("gol", "gol(es)", [1, 2]), ("sog", "tiros a gol", [2, 3, 4, 5]),
            ("sv", "atajadas", [20, 25, 30, 35])],
    "nfl": [("pyd", "yardas por pase", [150, 175, 200, 225, 250, 275, 300]), ("ptd", "TD de pase", [1, 2, 3]),
            ("ruy", "yardas por tierra", [30, 40, 50, 60, 75, 100]),
            ("recs", "recepciones", [2, 3, 4, 5, 6, 7, 8]), ("rey", "yardas recibiendo", [25, 30, 40, 50, 60, 75, 100]),
            ("td", "TD (anota)", [1])],
    "futbol": [("tir", "tiros", [1, 2, 3, 4]), ("tap", "tiros a puerta", [1, 2]), ("gol", "gol(es)", [1]),
               ("tar", "tarjeta", [1])],
}
ETIQ = {s: e for t in PROPS.values() for s, e, _ in t}
LADDER = {(t, s): l for t, v in PROPS.items() for s, _, l in v}
BINARIAS = {"gol", "td", "tar", "pto", "ptd"}
CONTEOS = {"tpm", "gol", "sog", "pto", "td", "ptd", "tar", "tap", "tir"}
NOMBRE_STAT = {"pts": "puntos", "reb": "rebotes", "ast": "asistencias", "tpm": "triples",
               "pra": "puntos + rebotes + asistencias", "pto": "puntos (gol o asistencia)", "gol": "goles",
               "sog": "tiros a gol", "sv": "atajadas", "pyd": "yardas por pase", "ptd": "pases de TD",
               "ruy": "yardas por tierra", "recs": "recepciones", "rey": "yardas recibiendo", "td": "TD",
               "tir": "tiros", "tap": "tiros a puerta", "tar": "tarjetas"}
SEG_FOTO = {"nba": "nba", "nfl": "nfl", "nhl": "nhl", "futbol": "soccer", "ncaab": "mens-college-basketball",
            "ncaaf": "college-football"}
STAT_PRINCIPAL = {
    "nba": [("pts", "pts", 4), ("reb", "reb", 2.5), ("ast", "ast", 2), ("pra", "PRA", 6)],
    "nhl": [("sog", "tiros", 1), ("pto", "puntos", 0.4)],
    "nfl": [("rey", "yd recibiendo", 15), ("recs", "recepciones", 1.5), ("ruy", "yd por tierra", 20)],
    "futbol": [("tir", "tiros", 1)],
}


def aplica(base, stat, prom):
    """A quién le aplica cada prop (promedios mínimos en su historial)."""
    g = lambda k: prom.get(k) or 0
    if base == "nba":
        return g("min") >= 15
    if base == "nhl":
        return g("min") >= 25 if stat == "sv" else (g("min") >= 12 and not prom.get("portero"))
    if base == "nfl":
        return {"pyd": g("patt") >= 15, "ptd": g("patt") >= 15, "ruy": g("ratt") >= 6,
                "recs": g("tgt") >= 3, "rey": g("tgt") >= 3, "td": g("uso") >= 6}[stat]
    if base == "futbol":
        return g("tit") >= 0.6
    return True


def prob_modelo(serie, x, stat, factor=1.0):
    """P(stat >= x): Poisson para conteos chicos, normal para puntos/yardas/rebotes.
    factor: qué tanto permite el rival vs el promedio de la liga (se aplica a la mitad)."""
    mu = sum(serie) / len(serie) * (1 + 0.5 * (factor - 1))
    if stat in CONTEOS:
        lam = max(mu, 0.05)
        return 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(int(x)))
    sd = max(statistics.pstdev(serie), 0.15 * mu, 1.0)
    z = (x - 0.5 - mu) / sd
    return 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))


def apuesta_prop(stat, x):
    """Como lo escribe la casa: 'Más de 24.5 puntos' = 25 o más."""
    if stat == "gol" and x == 1:
        return "Anota gol"
    if stat == "td":
        return "Anota touchdown"
    if stat == "tar":
        return "Le sacan tarjeta"
    if stat == "pto" and x == 1:
        return "Al menos 1 punto (gol o asistencia)"
    return f"Más de {x - 0.5:g} {NOMBRE_STAT[stat]}"


def campos_jugador(j, lado, pid, nombre, stat, x):
    ap = apuesta_prop(stat, x)
    return {"texto": f"{nombre}: {ap}", "apuesta": ap, "quien": nombre, "lado": lado, "sub": j[lado]["nombre"],
            "pid": pid, "stat": stat, "umbral": x,
            "foto": f"https://a.espncdn.com/i/headshots/{SEG_FOTO[j['tipo']]}/players/full/{pid}.png",
            "regla": {"k": "jug", "tid": j[lado]["id"], "pid": pid, "stat": stat, "x": x}}


def tabla_jugadores(recs, tid):
    """pid -> {n, juegos: [stats|None por partido del equipo, más reciente primero]}"""
    tabla = {}
    for i, rec in enumerate(recs):
        for pid, st in (rec["jug"].get(tid) or {}).items():
            t = tabla.setdefault(pid, {"n": st.get("n"), "juegos": [None] * len(recs)})
            t["juegos"][i] = st
    return tabla


def mercados_jugadores(j, lado, recs, lesion_ids, factor_rival=None):
    """factor_rival(stat, pos) -> cuánto permite el rival vs el promedio (1.0 = normal) o None."""
    base, tid = j["base"], j[lado]["id"]
    locales = [rec["eq"][tid]["local"] for rec in recs]
    es_local = lado == "L"
    out = []
    for pid, info in tabla_jugadores(recs, tid).items():
        idx = [i for i, g in enumerate(info["juegos"]) if g]
        juegos = [info["juegos"][i] for i in idx]
        if len(juegos) < 5:
            continue
        prom = {k: media([g.get(k) for g in juegos if isinstance(g.get(k), (int, float))])
                for k in ("min", "patt", "ratt", "tgt", "uso")}
        prom["tit"] = media([1 if g.get("tit") else 0 for g in juegos])
        prom["portero"] = any(g.get("portero") for g in juegos)
        pos = next((g.get("pos") for g in juegos if g.get("pos")), None)
        les = lesion_ids.get(pid) or lesion_ids.get(info["n"])
        if les and les["fuera"]:
            continue
        no_jugo_ultimos = info["juegos"][0] is None and (len(info["juegos"]) < 2 or info["juegos"][1] is None)
        for stat, etiqueta, ladder in PROPS[base]:
            if not aplica(base, stat, prom):
                continue
            pares = [(g.get(stat), locales[i]) for i, g in zip(idx, juegos) if g.get(stat) is not None]
            serie = [v for v, _ in pares]
            if len(serie) < 5:
                continue
            med = statistics.median(serie)
            fr = factor_rival(stat, pos) if factor_rival else None
            for x in ladder:
                hits = sum(v >= x for v in serie)
                n = len(serie)
                if hits / n < 0.6:
                    continue
                h5 = sum(v >= x for v in serie[:5])
                # mitad lo que pasó, mitad un modelo de su promedio (ajustado por el rival)
                est = min(0.99, max(0.02, 0.5 * estimar(hits, n) + 0.5 * prob_modelo(serie, x, stat, fr or 1.0)))
                cancha = [sum(v >= x for v, loc in pares if loc == es_local), sum(1 for _, loc in pares if loc == es_local)]
                tags = []
                if les:
                    tags.append(f"⚠ {les['estado']}")
                if no_jugo_ultimos:
                    tags.append("⚠ no jugó los últimos 2")
                if fr and abs(fr - 1) >= 0.10:
                    quien = f"a los {pos}" if pos and base == "nba" else ""
                    tags.append(f"rival permite {(fr - 1) * 100:+.0f}% {ETIQ[stat]} {quien}".strip())
                out.append(nuevo_pick(
                    juego=j["id"], deporte=j["tipo"], liga=j["liga_nombre"], clase="jugador", fam=f"{pid}:{stat}",
                    orden=x, **campos_jugador(j, lado, pid, info["n"], stat, x),
                    hits=hits, n=n, h5=h5, n5=min(5, n), est=round(est, 3), momio=None, real=False, p_mkt=None,
                    justo=momio_prob(est), serie=[[[_v(v), v >= x] for v in serie]], nombres=[info["n"]],
                    tags=tags, alerta=bool(les or no_jugo_ultimos), cancha=cancha, pos=pos,
                    dvp=round(fr, 3) if fr else None,
                    exig=1.0 if stat in BINARIAS else (round(x / med, 2) if med else 0),
                ))
    return out


def joyitas_jugadores(j, lado, recs, lesiones_equipo):
    """'Sin la estrella' y 'rol nuevo'."""
    base, tid = j["base"], j[lado]["id"]
    tabla = tabla_jugadores(recs, tid)
    out = []
    # ---- sin la estrella
    for les in lesiones_equipo:
        if not les["fuera"]:
            continue
        st = tabla.get(les["id"]) or next((v for v in tabla.values() if v["n"] == les["nombre"]), None)
        if not st:
            continue
        jugados = [g for g in st["juegos"] if g]
        if len(jugados) < 3:
            continue
        prom_min = media([g.get("min") for g in jugados])
        uso = media([g.get("uso") for g in jugados]) or 0
        if base == "nba" and (prom_min or 0) < 25:
            continue
        if base == "nhl" and (prom_min or 0) < 16:
            continue
        if base == "nfl" and uso < 8 and (media([g.get("patt") for g in jugados]) or 0) < 20:
            continue
        if base == "futbol":
            continue
        sin = [i for i, g in enumerate(st["juegos"]) if g is None]
        con = [i for i, g in enumerate(st["juegos"]) if g is not None]
        if len(sin) < 2 or len(con) < 3:
            continue
        for pid, info in tabla.items():
            if pid == les["id"] or info["n"] == les["nombre"]:
                continue
            for stat, etiq, dmin in STAT_PRINCIPAL[base]:
                vs = [info["juegos"][i].get(stat) for i in sin if info["juegos"][i] and info["juegos"][i].get(stat) is not None]
                vc = [info["juegos"][i].get(stat) for i in con if info["juegos"][i] and info["juegos"][i].get(stat) is not None]
                if len(vs) < 2 or len(vc) < 3:
                    continue
                ms, mc = media(vs), media(vc)
                if ms - mc < dmin or ms < mc * 1.25:
                    continue
                umbral = max([x for x in LADDER[(base, stat)] if all(v >= x for v in vs)] or [0])
                if not umbral:
                    continue
                hits = sum(v >= umbral for v in vs)
                con_rate = sum(v >= umbral for v in vc)
                # muestra chica: mezcla lo de "sin él" con todo su historial
                est = 0.6 * estimar(hits, len(vs)) + 0.4 * (hits + con_rate) / (len(vs) + len(vc))
                out.append(nuevo_pick(
                    juego=j["id"], deporte=j["tipo"], liga=j["liga_nombre"], clase="jugador", fam=f"{pid}:{stat}",
                    orden=umbral, **campos_jugador(j, lado, pid, info["n"], stat, umbral),
                    hits=hits, n=len(vs), h5=hits, n5=len(vs), est=round(est, 3), momio=None, real=False,
                    p_mkt=None, justo=momio_prob(est), serie=[[[_v(v), v >= umbral] for v in vs]],
                    nombres=[info["n"]], tags=["sin la estrella"], joya="sin_estrella",
                    razon=(f"Sin {les['nombre']} ({les['estado'].lower()}), {info['n']} promedia "
                           f"{ms:.1f} {etiq} vs {mc:.1f} cuando él juega. Pasó la línea en "
                           f"{hits}/{len(vs)} juegos sin él (con él: {con_rate}/{len(vc)})."),
                    score=(ms - mc) / max(mc, 1),
                ))
    # ---- rol nuevo / en racha
    for pid, info in tabla.items():
        juegos = info["juegos"]
        rec3 = [g for g in juegos[:3] if g]
        ant = [g for g in juegos[3:] if g]
        if len(rec3) < 3 or len(ant) < 3:
            continue
        if base in ("nba", "nhl"):
            m3, ma = media([g.get("min") for g in rec3]), media([g.get("min") for g in ant])
            if not m3 or not ma or m3 < ma * 1.25 or m3 - ma < (6 if base == "nba" else 3):
                continue
            uso_txt = f"juega {m3:.0f} min (antes {ma:.0f})"
        elif base == "nfl":
            m3, ma = media([g.get("uso") for g in rec3]), media([g.get("uso") for g in ant])
            if not m3 or ma is None or m3 < max(ma * 1.4, ma + 4):
                continue
            uso_txt = f"le llegan {m3:.0f} balones por juego (antes {ma:.0f})"
        else:
            continue
        for stat, etiq, dmin in STAT_PRINCIPAL[base]:
            v3 = [g.get(stat) for g in rec3 if g.get(stat) is not None]
            va = [g.get(stat) for g in ant if g.get(stat) is not None]
            if len(v3) < 3 or not va:
                continue
            a3, aa = media(v3), media(va)
            if a3 - aa < dmin or a3 < aa * 1.3:
                continue
            umbral = max([x for x in LADDER[(base, stat)] if all(v >= x for v in v3)] or [0])
            if not umbral:
                continue
            serie = v3 + va[:7]
            hits = sum(v >= umbral for v in serie)
            h5 = sum(v >= umbral for v in serie[:5])
            # 3 partidos es poco: mitad racha, mitad todo su historial
            est = 0.5 * estimar(3, 3) + 0.5 * hits / len(serie)
            out.append(nuevo_pick(
                juego=j["id"], deporte=j["tipo"], liga=j["liga_nombre"], clase="jugador", fam=f"{pid}:{stat}",
                orden=umbral, **campos_jugador(j, lado, pid, info["n"], stat, umbral),
                hits=hits, n=len(serie), h5=h5, n5=min(5, len(serie)), est=round(est, 3), momio=None, real=False,
                p_mkt=None, justo=momio_prob(est), serie=[[[_v(v), v >= umbral] for v in serie]],
                nombres=[info["n"]], tags=["rol nuevo"], joya="rol",
                razon=(f"Le dieron más juego: últimos 3 partidos {uso_txt}. Promedia {a3:.1f} {etiq} "
                       f"(antes {aa:.1f}). La línea de la casa suele tardar en subir."),
                score=(a3 - aa) / max(aa, 1),
            ))
    return out


def joyitas_matchup(picks):
    """Jugadores en forma contra un rival que permite mucho más de lo normal en su stat."""
    out = []
    for p in picks:
        if p["clase"] != "jugador" or p.get("joya") or p.get("alerta") or not p.get("dvp"):
            continue
        if p["stat"] in BINARIAS or p["deporte"] in ("ncaab", "ncaaf"):
            continue  # TDs/goles son pocos y en NCAA no hay liga completa con qué comparar: puro ruido
        if p["dvp"] < 1.15 or p["n"] < 7 or p["hits"] / p["n"] < 0.7 or p["est"] < 0.6:
            continue
        q = nuevo_pick(**{k: v for k, v in p.items() if k != "id"})
        q.update(joya="matchup", tags=list(p["tags"]) + ["matchup"], score=(p["dvp"] - 1) + (p["est"] - 0.6),
                 razon=(f"El rival permite {(p['dvp'] - 1) * 100:.0f}% más {ETIQ[p['stat']]} de lo normal"
                        f"{' a los ' + p['pos'] if p.get('pos') and BASE.get(p['deporte']) == 'nba' else ''}, "
                        f"y él pasó la línea {p['hits']}/{p['n']} veces."))
        out.append(q)
    return out


# =========================================================================== selección

MOMIO_MIN_CANDADO = -650  # más abajo que esto (-700, -1000…) paga demasiado poco aunque pegue


def cumple_candado(p):
    if p["n"] < (12 if p["clase"] == "equipo" else 7):
        return False
    if p.get("alerta") or p.get("joya") in ("rol", "sin_estrella", "matchup"):
        return False
    if momio_pata(p) < MOMIO_MIN_CANDADO:
        return False
    return (p["hits"] / p["n"] >= (0.85 if p["clase"] == "equipo" else 0.9)
            and p["h5"] >= p["n5"] - (1 if p["clase"] == "equipo" else 0) and p["est"] >= 0.75)


def valor_candado(p):
    """Para ordenar: los que tienen momio real y las líneas exigentes primero."""
    if p["clase"] == "jugador":
        return p["est"] + 0.15 * min(p.get("exig", 1), 1.2)
    return p["est"] + (0.15 if p["real"] else 0.05)


def mejor_por_familia(picks, cond):
    best = {}
    for p in picks:
        if not cond(p):
            continue
        k = (p["juego"], p["fam"])
        if k not in best or p["orden"] > best[k]["orden"] or (p["orden"] == best[k]["orden"] and p["est"] > best[k]["est"]):
            best[k] = p
    return list(best.values())


def uno_por_jugador(picks, clave):
    best, out = {}, []
    for p in picks:
        if p["clase"] != "jugador" or not p.get("pid"):
            out.append(p)
            continue
        k = (p["juego"], p["pid"])
        if k not in best or clave(p) > clave(best[k]):
            best[k] = p
    return out + list(best.values())


LINEA_TIPICA = {"Ambos anotan: Sí", "Ambos anotan: No", "Más de 9.5 córners", "Más de 4.5 tarjetas",
                "1er tiempo: más de 1.5 goles"}


def es_joyita_equipo(p, usar_pa):
    if p["clase"] != "equipo" or p["n"] < 12:
        return False
    if p["real"] and p["p_mkt"]:
        e = est_de(p, usar_pa)
        edge = e - p["p_mkt"]
        if edge >= 0.06 and p["momio"] >= -200 and p["hits"] / p["n"] >= 0.6:
            p["joya"] = "valor"
            p["score"] = edge
            con_pa = usar_pa and p.get("pa") and p["pa"]["extra"] > 0.01
            p["razon"] = (f"La casa le da {p['p_mkt'] * 100:.0f}% de probabilidad; en los últimos partidos de los dos "
                          f"equipos se cumplió {p['hits']}/{p['n']} ({p['hits'] / p['n'] * 100:.0f}%)."
                          + (f" Con el Pago Anticipado sube a {e * 100:.0f}%." if con_pa else ""))
            return True
        return False
    if p["deporte"] == "futbol" and p["texto"] in LINEA_TIPICA and p["hits"] / p["n"] >= 0.75:
        p["joya"] = "tipica"
        p["score"] = p["est"] - 0.5
        p["razon"] = (f"Es una línea que normalmente se paga parejo (cerca de -110/+110) y se cumplió "
                      f"{p['hits']}/{p['n']} en los partidos recientes de ambos. Revisa el momio en tu casa.")
        return True
    return False


def pool_parlays(todos):
    """Patas candidatas para los parlays armados (en la página se arman al abrirla).
    - De equipo: solo con momio real de la casa (pago exacto).
    - De jugador: se cumplieron 80%+ (momio aproximado ≈ o real si hay clave de The Odds API);
      la mejor línea por jugador y stat, y un escalón más fácil para la escalera."""
    equipo = [p for p in todos if p["clase"] == "equipo" and p["n"] >= 12
              and ((p["real"] and p["momio"]) or (p["fam"] in ("spa_L", "spa_V") and p["hits"] / p["n"] >= 0.7)
                   or (p["deporte"] == "ufc" and p["hits"] / p["n"] >= 0.7))]
    cond = lambda p: p["n"] >= 7 and not p.get("alerta") and p["hits"] / p["n"] >= 0.8
    jug = mejor_por_familia([p for p in todos if p["clase"] == "jugador" and not p.get("joya")], cond)
    fam = {(p["juego"], p["fam"]): p["orden"] for p in jug}
    extra = [p for p in todos if p["clase"] == "jugador" and not p.get("joya") and cond(p)
             and (p["juego"], p["fam"]) in fam and p["orden"] < fam[(p["juego"], p["fam"])]]
    return equipo + jug + mejor_por_familia(extra, lambda p: True)


# nombre, descripción, pago objetivo (decimal), patas máx., prob. mínima por pata, rango de momio, exacto
PLANTILLAS = [
    ("Lotería", "$10 que hagan $20,000 o más: 18 partidos de varias ligas y días.", 2000.0, 18, 0.5, (-400, 250), True),
    ("Escalera de candados", "Puros favoritos tipo -250 a -600: solos no pagan, juntos sí. "
     "Revisa en tu casa los momios con ≈.", 9999, 10, 0.78, (-650, -230), False),
    ("Corto", "Busca +160 o más con las patas más seguras que todavía pagan algo.", 2.6, 4, 0.65, None, False),
    ("Mediano", "Busca +500 o más: equilibrio entre pago y probabilidad.", 6.0, 6, 0.6, None, False),
    ("Bombazo", "Busca +2000 o más: pegar algo grande con poco. Pega pocas veces, apuesta poquito.", 21.0, 10, 0.5, None, False),
]


def seleccion_exacta(pool, n, objetivo, est_min, usar_pa=True, max_liga=5, equipos=None, rango=None):
    """n patas (una por partido y por equipo, máx. max_liga por liga) con la MAYOR probabilidad posible
    que todavía paguen al menos 'objetivo'. Maximiza sum(ln prob) con sum(ln momio) >= ln objetivo
    buscando el peso lam que equilibra las dos cosas."""
    equipos = equipos or {}
    datos = [(p, math.log(min(est_de(p, usar_pa), 0.99)), math.log(decimal(momio_pata(p, usar_pa))))
             for p in pool if est_de(p, usar_pa) >= est_min
             and (not rango or rango[0] <= momio_pata(p, usar_pa) <= rango[1])]

    def elegir(lam):
        mejor = {}
        for p, lp, ld in datos:
            s = lp + lam * ld
            if p["juego"] not in mejor or s > mejor[p["juego"]][0]:
                mejor[p["juego"]] = (s, p, ld)
        legs, ligas, suma, usados = [], {}, 0.0, set()
        for s, p, ld in sorted(mejor.values(), key=lambda x: -x[0]):
            eqs = set(equipos.get(p["juego"], ()))
            if ligas.get(p["liga"], 0) >= max_liga or eqs & usados:
                continue
            usados |= eqs
            legs.append(p)
            ligas[p["liga"]] = ligas.get(p["liga"], 0) + 1
            suma += ld
            if len(legs) == n:
                break
        return legs, suma

    meta = math.log(objetivo)
    lo, hi = 0.0, 4.0
    legs, suma = elegir(hi)
    if suma < meta:
        return legs
    for _ in range(40):
        mid = (lo + hi) / 2
        l2, s2 = elegir(mid)
        if s2 >= meta:
            hi, legs = mid, l2
        else:
            lo = mid
    return legs


def armar_parlays(pool, usar_pa=True, solo=None, equipos=None):
    """Igual que en la página: una por una, la pata que más paga por el riesgo que agrega
    (ln momio decimal / -ln probabilidad), una por partido, mezclando deportes.
    exacto: llena todas las patas apuntando al pago objetivo (cada pata debe pagar lo que falta repartido)."""
    r = {p["id"]: math.log(decimal(momio_pata(p, usar_pa))) / -math.log(min(est_de(p, usar_pa), 0.99))
         * (1 if p["real"] else 0.9) for p in pool}
    res = []
    for nombre, desc, objetivo, max_legs, est_min, rango, exacto in PLANTILLAS:
        if solo and nombre not in solo:
            continue
        if exacto:
            legs = seleccion_exacta(pool, max_legs, objetivo, est_min, usar_pa, equipos=equipos, rango=rango)
            d = math.prod(decimal(momio_pata(p, usar_pa)) for p in legs) if legs else 1
            if len(legs) < max_legs * 0.6 or d < objetivo * 0.5:
                continue
        else:
            legs, juegos, cuenta, d = [], set(), {}, 1.0
            while len(legs) < max_legs and d < objetivo:
                cands = [p for p in pool if p["juego"] not in juegos and est_de(p, usar_pa) >= est_min
                         and (not rango or rango[0] <= momio_pata(p, usar_pa) <= rango[1])]
                if not cands:
                    break
                p = max(cands, key=lambda p: r[p["id"]] - 0.15 * cuenta.get(p["deporte"], 0))
                legs.append(p)
                juegos.add(p["juego"])
                cuenta[p["deporte"]] = cuenta.get(p["deporte"], 0) + 1
                d *= decimal(momio_pata(p, usar_pa))
            if len(legs) < 2 or (objetivo < 999 and d < objetivo * 0.6):
                continue
        res.append({"nombre": nombre, "desc": desc, "legs": [p["id"] for p in legs], "dec": round(d, 2),
                    "prob": round(math.prod(est_de(p, usar_pa) for p in legs), 6)})
    return res


# =========================================================================== combinadas (mismo partido)

COMBINADAS = []


def combinadas(j, lado, recs, picks):
    """Dos apuestas del mismo partido que en la historia del equipo pegaron JUNTAS seguido.
    Ej.: 'Gana Lakers' + 'Luka más de 29.5 puntos'. Las casas las ofrecen como 'parlay del mismo partido'."""
    base, tid = j["base"], j[lado]["id"]
    if len(recs) < 6:
        return []
    def vec(p):
        return [evaluar_regla(p["regla"], rec, base, tid)[0] for rec in recs]
    eq_lado = [p for p in picks if p["clase"] == "equipo" and p.get("lado") == lado and p["n"] >= 12
               and p["hits"] / p["n"] >= 0.6 and p["fam"] in ("ml_L", "ml_V", "hcp_L", "hcp_V", "dc_L", "dc_V")]
    eq_lado = mejor_por_familia(eq_lado, lambda p: True)
    otros = mejor_por_familia([p for p in picks if not p.get("joya") and p["n"] >= 7 and p["hits"] / p["n"] >= 0.7
                               and ((p["clase"] == "jugador" and p.get("lado") == lado and not p.get("alerta"))
                                    or (p["clase"] == "equipo" and p.get("lado") is None))], lambda p: True)
    if not eq_lado or not otros:
        return []
    vecs = {p["id"]: vec(p) for p in eq_lado + otros}
    res = []
    for a in eq_lado:
        for b in otros:
            pares = [(x, y) for x, y in zip(vecs[a["id"]], vecs[b["id"]]) if x is not None and y is not None]
            n = len(pares)
            if n < 6:
                continue
            ja = sum(1 for x, y in pares if x and y)
            ra = sum(1 for x, _ in pares if x) / n
            rb = sum(1 for _, y in pares if y) / n
            if ja / n < 0.7 or not ra or not rb:
                continue
            lift = (ja / n) / (ra * rb)
            if lift < 1.05:
                continue  # si no pegan más juntas que separadas, no tiene chiste combinarlas
            if b["clase"] == "jugador" and b.get("exig", 1) < 0.55:
                continue  # línea regalada
            res.append({"juego": j["id"], "a": a["id"], "b": b["id"], "hits": ja, "n": n,
                        "est": round((ja + 1) / (n + 2), 3), "lift": round(lift, 2)})
    res.sort(key=lambda c: (-(c["est"] + 0.05 * min(c["lift"] - 1, 0.5)), -c["lift"]))
    elegidas, usados = [], set()
    for c in res:
        if c["b"] in usados:
            continue
        elegidas.append(c)
        usados.add(c["b"])
        if len(elegidas) == 2:
            break
    return elegidas
