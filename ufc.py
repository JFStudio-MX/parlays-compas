# -*- coding: utf-8 -*-
"""UFC: peleas de los próximos días, historial de cada peleador (resultado, método y round de sus últimas peleas)
y apuestas: gana, va a decisión, gana por KO/TKO y gana por sumisión. Datos de ESPN."""
from datetime import timedelta

from mercados import estimar, nuevo_pick
from nucleo import B, DIAS_ES, MESES_ES, a_mx, etiqueta_dia, get_json, leer_momios, momio_prob, sin_vig

W = "https://site.web.api.espn.com/apis/common/v3/sports/mma/athletes"
N_PELEAS = 10


def _perfil(aid, ttl=24 * 3600):
    return get_json(f"{W}/{aid}", ttl=ttl) or {}


def historial(aid, ttl=24 * 3600):
    """Últimas peleas terminadas: [{evento, fecha, gano (True/False/None), metodo: ko/sub/dec/otro, round}]"""
    d = _perfil(aid, ttl)
    out = []
    for ev in (d.get("eventsMap") or {}).values():
        res = ((ev.get("status") or {}).get("result") or {}).get("name") or ""
        if not res or ev.get("gameResult") not in ("W", "L", "D"):
            continue
        metodo = "ko" if "ko" in res else ("sub" if "submission" in res else ("dec" if res.startswith("decision") else "otro"))
        out.append({"evento": str(ev.get("id")), "fecha": ev.get("gameDate", "")[:10],
                    "gano": {"W": True, "L": False}.get(ev["gameResult"]), "metodo": metodo,
                    "round": (ev.get("status") or {}).get("period")})
    out.sort(key=lambda x: x["fecha"], reverse=True)
    return out[:N_PELEAS], d.get("athlete") or {}


def _info(a):
    stats = {s.get("name"): s.get("displayValue") for s in ((a.get("statsSummary") or {}).get("statistics") or [])}
    x = [f"récord {stats['wins-losses-draws']}" if stats.get("wins-losses-draws") else None,
         f"{a['age']} años" if a.get("age") else None, a.get("displayHeight"),
         f"alcance {a['displayReach']}" if a.get("displayReach") else None, (a.get("stance") or {}).get("text")
         if isinstance(a.get("stance"), dict) else a.get("stance")]
    return " · ".join(str(v) for v in x if v)


def buscar(ahora, dias=14):
    """Peleas que no han empezado en los próximos días, con sus picks."""
    hoy = ahora.date()
    vistos, juegos, picks = set(), [], []
    for k in range(-1, dias + 1):
        d = hoy + timedelta(days=k)
        sb = get_json(f"{B}/mma/ufc/scoreboard?dates={d:%Y%m%d}", ttl=3 * 3600) or {}
        for e in sb.get("events", []):
            for c in e.get("competitions", []):
                cid = str(c["id"])
                if cid in vistos or c["status"]["type"].get("state") != "pre":
                    continue
                vistos.add(cid)
                dt = a_mx(c.get("date") or e["date"])
                if dt < ahora or (dt.date() - hoy).days > dias:
                    continue
                cs = c.get("competitors") or []
                if len(cs) != 2:
                    continue
                orden = sorted(cs, key=lambda x: 0 if x.get("homeAway") == "home" else (x.get("order") or 1))
                lados = {}
                for lado, x in zip(("L", "V"), orden):
                    a = x["athlete"]
                    hist, perfil = historial(str(x["id"]))
                    rec = next((r.get("summary") for r in x.get("records") or [] if r.get("type") == "total"), None)
                    apellido = a.get("shortName", "").split(" ")[-1] or a.get("displayName", "")
                    lados[lado] = {"id": str(x["id"]), "abbr": apellido[:12], "corto": apellido,
                                   "nombre": a.get("displayName"),
                                   "logo": f"https://a.espncdn.com/i/headshots/mma/players/full/{x['id']}.png",
                                   "color": None, "color2": None, "rank": None, "liga_hist": "ufc",
                                   "forma": "".join("G" if h["gano"] else ("P" if h["gano"] is False else "E") for h in hist[:5]),
                                   "n_hist": len(hist), "descanso": None, "record": rec, "info": _info(perfil),
                                   "_hist": hist}
                j = {"id": cid, "liga": "ufc", "liga_nombre": e.get("name") or "UFC", "tipo": "ufc", "base": "ufc",
                     "sport": "mma", "fecha": c.get("date") or e["date"], "hora": f"{dt:%H:%M}",
                     "dia": etiqueta_dia(dt, hoy), "dl": f"{DIAS_ES[dt.weekday()]} {dt.day} {MESES_ES[dt.month - 1]}",
                     "orden": dt.isoformat(), "L": lados["L"], "V": lados["V"], "neutral": True,
                     "momios": leer_momios(c), "indoor": True, "clima_txt": None, "previo": {},
                     "lesiones": {"L": [], "V": []}, "evento": str(e["id"]),
                     "division": (c.get("type") or {}).get("abbreviation"), "estelar": c is e["competitions"][-1]}
                ps = mercados(j)
                j["picks"] = [p["id"] for p in ps]
                for l in ("L", "V"):
                    j[l].pop("_hist", None)
                juegos.append(j)
                picks += ps
    return juegos, picks


def _serie(hist, f):
    return [[{"ko": "KO", "sub": "SUB", "dec": "DEC"}.get(h["metodo"], "—") + ("" if h["gano"] else "·P"), f(h)] for h in hist]


def mercados(j):
    """Picks de una pelea con el historial de los dos peleadores."""
    hA, hB = j["L"]["_hist"], j["V"]["_hist"]
    if len(hA) < 3 or len(hB) < 3:
        return []
    m = j["momios"] or {}
    pL, pV = sin_vig(m.get("ml_L"), m.get("ml_V"))
    out = []
    regla = lambda tipo, lado=None: {"k": "mma", "evento": j["evento"], "pelea": j["id"],
                                     "atleta": j[lado]["id"] if lado else j["L"]["id"],
                                     "rival": j["V" if lado == "L" else "L"]["id"] if lado else j["V"]["id"], "tipo": tipo}

    def pick(fam, texto, sub, okA, okB, lado=None, momio=None, p_mkt=None, est=None):
        sA, sB = _serie(hA, okA), _serie(hB, okB)
        hits = sum(o for _, o in sA) + sum(o for _, o in sB)
        n = len(sA) + len(sB)
        h5 = sum(o for _, o in sA[:5]) + sum(o for _, o in sB[:5])
        n5 = len(sA[:5]) + len(sB[:5])
        e = est if est is not None else estimar(hits, n, p_mkt)
        p = nuevo_pick(juego=j["id"], deporte="ufc", liga="UFC", clase="equipo", fam=fam, orden=0, texto=texto, sub=sub,
                       hits=hits, n=n, h5=h5, n5=n5, est=round(min(max(e, 0.02), 0.97), 3), momio=momio,
                       real=momio is not None, p_mkt=round(p_mkt, 3) if p_mkt else None, justo=momio_prob(e),
                       cancha=None, serie=[sA, sB], nombres=[j["L"]["abbr"], j["V"]["abbr"]], tags=[], lado=lado,
                       quien=j[lado]["nombre"] if lado else "Pelea", apuesta=texto, regla=regla(fam_tipo[fam], lado))
        out.append(p)
        return p

    fam_tipo = {"ml_L": "gana", "ml_V": "gana", "dec_si": "decision", "dec_no": "no_decision",
                "ko_L": "ko", "ko_V": "ko", "sub_L": "sub", "sub_V": "sub"}
    wA = (sum(1 for h in hA if h["gano"]) + 1) / (len(hA) + 2)
    wB = (sum(1 for h in hB if h["gano"]) + 1) / (len(hB) + 2)
    pA = wA * (1 - wB) / (wA * (1 - wB) + wB * (1 - wA))  # quién gana según el historial de los dos
    # los récords inflan (los invictos suelen venir de pelear contra rivales más flojos): se acerca al 50/50
    pA = 0.5 + (pA - 0.5) * 0.75
    if pL:
        pA = (pA * 10 + pL * 30) / 40  # con momio, la casa pesa más
    A, Bn = j["L"]["corto"], j["V"]["corto"]
    pick("ml_L", f"Gana {A}", "Ganador de la pelea", lambda h: bool(h["gano"]), lambda h: h["gano"] is False,
         lado="L", momio=m.get("ml_L"), p_mkt=pL, est=pA)
    pick("ml_V", f"Gana {Bn}", "Ganador de la pelea", lambda h: h["gano"] is False, lambda h: bool(h["gano"]),
         lado="V", momio=m.get("ml_V"), p_mkt=pV, est=1 - pA)
    # decisión: parte de la base de UFC (~47% de las peleas llegan a los jueces) y la mueve con el historial de los dos
    nd = sum(1 for h in hA + hB if h["metodo"] == "dec")
    p_dec = (nd + 0.47 * 12) / (len(hA) + len(hB) + 12)
    pick("dec_si", "Va a decisión: Sí", "La pelea llega a los jueces", lambda h: h["metodo"] == "dec",
         lambda h: h["metodo"] == "dec", est=p_dec)
    pick("dec_no", "Va a decisión: No", "Se acaba antes (KO, TKO o sumisión)", lambda h: h["metodo"] != "dec",
         lambda h: h["metodo"] != "dec", est=1 - p_dec)
    # por método: qué tan seguido gana así × qué tan seguido el rival pierde así
    for lado, yo, rival, nom, p_gana in (("L", hA, hB, A, pA), ("V", hB, hA, Bn, 1 - pA)):
        for met, fam, txt in (("ko", f"ko_{lado}", "por KO/TKO"), ("sub", f"sub_{lado}", "por sumisión")):
            ganadas = [h for h in yo if h["gano"]]
            share = (sum(1 for h in ganadas if h["metodo"] == met) + .5) / (len(ganadas) + 2)
            pierde = (sum(1 for h in rival if h["gano"] is False and h["metodo"] == met) + .3) / (len(rival) + 2)
            est = p_gana * (0.7 * share + 0.3 * min(1, pierde * 3))
            if est < 0.12:
                continue
            pick(fam, f"Gana {nom} {txt}", f"Método de victoria", lambda h, met=met: bool(h["gano"]) and h["metodo"] == met,
                 lambda h, met=met: h["gano"] is False and h["metodo"] == met, lado=lado, est=est)
    info = [f"{j[l]['nombre']}: {j[l]['info']}" for l in ("L", "V") if j[l].get("info")]
    for p in out:
        p["tags"] = [j["division"]] if j.get("division") else []
    j["peleadores"] = info
    return out


def evaluar(regla):
    """Califica una apuesta de UFC: (True/False/None, valor) o ('pendiente', None) si no ha terminado."""
    hist, _ = historial(regla["atleta"])
    pelea = next((h for h in hist if h["evento"] == regla["evento"]), None)
    if not pelea:  # el perfil guardado es de antes de la pelea: pídelo otra vez (máximo cada 3 h)
        hist, _ = historial(regla["atleta"], ttl=3 * 3600)
        pelea = next((h for h in hist if h["evento"] == regla["evento"]), None)
    if not pelea:
        return "pendiente", None
    t, g, met = regla["tipo"], pelea["gano"], pelea["metodo"]
    valor = f"{'ganó' if g else ('perdió' if g is False else 'empate/sin resultado')} por {met.upper()} (R{pelea['round']})"
    if t == "decision":
        return met == "dec", valor
    if t == "no_decision":
        return met != "dec", valor
    if g is None:
        return None, valor
    if t == "gana":
        return g, valor
    return (g and met == t), valor
