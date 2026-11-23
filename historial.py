# -*- coding: utf-8 -*-
"""Historial: guarda lo que recomendó la página, lo califica solo cuando terminan los partidos
y lleva tus apuestas (las que registras en la página o que me pasas por el chat)."""
import json
from datetime import timedelta

from nucleo import (DATOS, PA_UMBRAL, a_mx, cargar_partido, casa_cubre, es_ganador, escribir_json, evaluar_regla,
                    leer_json, media, pago_anticipado)

HIST = DATOS / "historial.json"                # picks recomendados: clave -> registro
SUGERIDOS = DATOS / "parlays_sugeridos.json"   # parlays armados del día: clave -> registro
APUESTAS = DATOS / "apuestas.json"             # TUS apuestas (las escribe la página o Claude)
ESTADO_AP = DATOS / "apuestas_estado.json"     # calificación automática de tus apuestas


def clave(p):
    return f"{p['juego']}|{json.dumps(p['regla'], sort_keys=True)}"


def nombre_partido(j):
    return f"{j['L']['corto']} vs {j['V']['corto']}" if j["base"] == "futbol" else f"{j['V']['corto']} @ {j['L']['corto']}"


def info_juego(j):
    return {"juego": j["id"], "liga": j["liga"], "sport": j["sport"], "tipo": j["tipo"], "base": j["base"],
            "fecha": j["fecha"], "partido": nombre_partido(j)}


# --------------------------------------------------------------------------- guardar

def guardar(picks_cats, juegos, parlays_hoy, ahora):
    """picks_cats: [(pick, {categorías})]. Solo se guardan antes de que empiece su partido."""
    h = leer_json(HIST, {})
    for p, cats in picks_cats:
        j = juegos[p["juego"]]
        if a_mx(j["fecha"]) <= ahora:
            continue
        k = clave(p)
        viejo = h.get(k)
        if viejo and viejo["estado"] != "pendiente":
            continue
        h[k] = {**info_juego(j), "clave": k, "texto": p["texto"], "deporte": p["deporte"], "clase": p["clase"],
                "est": p["est"], "est_pa": (p.get("pa") or {}).get("est"), "momio": p.get("momio"),
                "real": p.get("real"), "regla": p["regla"], "estado": "pendiente",
                "cats": sorted(set(cats) | set((viejo or {}).get("cats", []))),
                "creado": (viejo or {}).get("creado") or ahora.isoformat()}
    escribir_json(HIST, h)

    s = leer_json(SUGERIDOS, {})
    hoy = ahora.date().isoformat()
    for pl in parlays_hoy:
        k = f"{hoy}|{pl['nombre']}"
        legs = pl["legs_picks"]
        # se congela en cuanto empieza su primer partido
        if k in s and min(a_mx(juegos[q["juego"]]["fecha"]) for q in legs if q["juego"] in juegos) <= ahora:
            continue
        s[k] = {"clave": k, "fecha": hoy, "nombre": pl["nombre"], "legs": [clave(q) for q in legs],
                "textos": [q["texto"] for q in legs], "dec": pl["dec"], "prob": pl["prob"], "creado": ahora.isoformat()}
    escribir_json(SUGERIDOS, s)


# --------------------------------------------------------------------------- calificar

def _calificar_regla(r, ahora, recs):
    """Estado de una apuesta: pendiente / gano / perdio / anulada / sin_dato (+ si pegó el Pago Anticipado)."""
    if a_mx(r["fecha"]) > ahora - timedelta(hours=2, minutes=30):
        return "pendiente", None, False
    if r["regla"].get("k") == "mma":  # UFC: el resultado sale del perfil del peleador
        import ufc
        ok, v = ufc.evaluar(r["regla"])
        if ok == "pendiente":
            return ("sin_dato" if a_mx(r["fecha"]) < ahora - timedelta(days=4) else "pendiente"), None, False
        return ("anulada" if ok is None else ("gano" if ok else "perdio")), v, False
    k = (r["liga"], r["juego"])
    if k not in recs:
        recs[k] = cargar_partido(r["liga"], r["sport"], r["base"], r["juego"])
    rec = recs[k]
    if not rec:
        return ("sin_dato" if a_mx(r["fecha"]) < ahora - timedelta(days=4) else "pendiente"), None, False
    ok, v = evaluar_regla(r["regla"], rec, r["base"])
    pa = es_ganador(r["regla"]) and r["tipo"] in PA_UMBRAL and pago_anticipado(r["regla"], rec, r["base"], r["tipo"])
    return ("anulada" if ok is None else ("gano" if ok else "perdio")), v, pa


def calificar(ahora):
    h = leer_json(HIST, {})
    recs, n = {}, 0
    for r in h.values():
        if r["estado"] != "pendiente":
            continue
        e, v, pa = _calificar_regla(r, ahora, recs)
        if e != "pendiente":
            r.update(estado=e, valor=v, pa=pa)
            n += 1
    escribir_json(HIST, h)

    aps = leer_json(APUESTAS, [])
    estado = {}
    for a in aps:
        legs = []
        for lg in a.get("legs", []):
            if lg.get("resultado"):  # lo marcaste tú
                legs.append({"estado": lg["resultado"]})
                continue
            if not lg.get("regla") or not lg.get("juego"):
                legs.append({"estado": "pendiente"})
                continue
            e, v, pa = _calificar_regla(lg, ahora, recs)
            # el Pago Anticipado cuenta solo si la casa de esa apuesta lo tiene en ese deporte
            if e == "perdio" and pa and lg.get("pa", True) and casa_cubre(a.get("casa"), lg.get("tipo")):
                e = "gano_pa"
            legs.append({"estado": e, "valor": v, "pa": pa})
        es = [x["estado"] for x in legs]
        if a.get("resultado"):
            final = a["resultado"]
        elif "perdio" in es:
            final = "perdio"
        elif es and all(x in ("gano", "gano_pa", "anulada") for x in es):
            final = "gano"
        else:
            final = "pendiente"
        estado[a["id"]] = {"legs": legs, "estado": final}
    escribir_json(ESTADO_AP, estado)
    return n


# --------------------------------------------------------------------------- resumen para la página

def _grupo(rs, usar_pa=False):
    ok = lambda r: r["estado"] == "gano" or (usar_pa and r.get("pa"))
    n = len(rs)
    g = sum(1 for r in rs if ok(r))
    return {"n": n, "g": g, "pct": round(g / n, 3) if n else None,
            "est": round(media([(r.get("est_pa") if usar_pa and r.get("est_pa") else r["est"]) for r in rs]) or 0, 3)}


NOMBRES_CAT = {"candado": "Candados", "joyita:valor": "Joyitas · valor", "joyita:tipica": "Joyitas · línea típica",
               "joyita:sin_estrella": "Joyitas · sin la estrella", "joyita:rol": "Joyitas · rol nuevo",
               "joyita:matchup": "Joyitas · matchup", "combinada": "Combinadas"}


def resumen(usar_pa=True):
    h = leer_json(HIST, {})
    cal = [r for r in h.values() if r["estado"] in ("gano", "perdio")]
    por_cat = {}
    for r in cal:
        for c in r.get("cats", []):
            if c.startswith("parlay:"):
                c = "pata de parlay"
            por_cat.setdefault(c, []).append(r)
    por_dep = {}
    for r in cal:
        por_dep.setdefault(r["deporte"], []).append(r)
    cortes = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    calib = []
    for a, b in cortes:
        rs = [r for r in cal if a <= r["est"] < b]
        if rs:
            g = _grupo(rs)
            calib.append({"rango": f"{int(a * 100)}–{min(int(b * 100), 100)}%", **g})
    # Pago Anticipado: cuántas veces salvó un "gana" que se perdió
    ml = [r for r in h.values() if r["estado"] in ("gano", "perdio") and es_ganador(r["regla"]) and r["tipo"] in PA_UMBRAL]
    salvadas = sum(1 for r in ml if r["estado"] == "perdio" and r.get("pa"))
    # parlays sugeridos
    s = leer_json(SUGERIDOS, {})
    pls = []
    for x in sorted(s.values(), key=lambda x: x["creado"], reverse=True):
        es = []
        for k in x["legs"]:
            r = h.get(k)
            if not r:
                es.append("sin_dato")
                continue
            e = r["estado"]
            if e == "perdio" and usar_pa and r.get("pa"):
                e = "gano_pa"
            es.append(e)
        if "perdio" in es:
            fin = "perdio"
        elif es and all(e in ("gano", "gano_pa", "anulada") for e in es):
            fin = "gano"
        else:
            fin = "pendiente"
        pls.append({"fecha": x["fecha"], "nombre": x["nombre"], "dec": x["dec"], "prob": x["prob"],
                    "textos": x["textos"], "legs": es, "estado": fin})
    hechos = [p for p in pls if p["estado"] != "pendiente"]
    por_pl = {}
    for p in hechos:
        g = por_pl.setdefault(p["nombre"], {"n": 0, "g": 0, "neto": 0.0})
        g["n"] += 1
        if p["estado"] == "gano":
            g["g"] += 1
            g["neto"] += 100 * (p["dec"] - 1)
        else:
            g["neto"] -= 100
    recientes = sorted([r for r in h.values() if r["estado"] in ("gano", "perdio", "anulada")],
                       key=lambda r: r["fecha"], reverse=True)[:80]
    return {
        "total": _grupo(cal),
        "por_cat": [{"cat": NOMBRES_CAT.get(c, c.capitalize()), **_grupo(rs)} for c, rs in
                    sorted(por_cat.items(), key=lambda kv: -len(kv[1]))],
        "por_dep": [{"dep": d, **_grupo(rs)} for d, rs in sorted(por_dep.items(), key=lambda kv: -len(kv[1]))],
        "calib": calib,
        "pa": {"ganadores": len(ml), "salvadas": salvadas},
        "parlays": pls[:40],
        "por_parlay": [{"nombre": k, **v} for k, v in por_pl.items()],
        "pendientes": sum(1 for r in h.values() if r["estado"] == "pendiente"),
        "recientes": [{"texto": r["texto"], "partido": r["partido"], "fecha": r["fecha"], "estado": r["estado"],
                       "valor": r.get("valor"), "est": r["est"], "momio": r.get("momio"), "pa": r.get("pa"),
                       "deporte": r["deporte"]} for r in recientes],
    }


def apuestas_y_estado():
    return leer_json(APUESTAS, []), leer_json(ESTADO_AP, {})
