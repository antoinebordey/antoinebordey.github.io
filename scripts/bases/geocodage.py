# -*- coding: utf-8 -*-
"""Géocodage des adresses des fiches (Base Adresse Nationale, service de géocodage de la Géoplateforme IGN)."""
import re
import time
import urllib.parse

from commun import ecrire_json, json_url, lire_json, maintenant, segments_adresse

API = "https://data.geopf.fr/geocodage/search"
DOC = "https://geoservices.ign.fr/documentation/services/services-geoplateforme/geocodage"
FICHIER = "geo.json"
FREQUENCE_JOURS = 0  # incrémental : ne relance que les adresses nouvelles ou modifiées
TOUJOURS = True
SCORE_MIN = 0.45


def premiere_adresse(adresse):
    segs = segments_adresse(adresse)
    if not segs:
        return ""
    seg = segs[0]
    m = re.match(r"^(\d+)\s*(bis|ter|quater)?\s*(?:(?:[-–]|à)\s*\d+\s*(?:bis|ter)?)?[\s,]+(.+)$", seg, re.I)
    if m:
        return f"{m.group(1)}{' ' + m.group(2) if m.group(2) else ''} {m.group(3)}".strip()
    return seg


def requete(t):
    a = t.get("actif") or {}
    adresse = premiere_adresse(a.get("adresse") or "")
    if not adresse:
        return None, None
    commune = (a.get("commune") or "").strip()
    dep = None
    m = re.search(r"\((\d{2,3})\)", commune)
    if m:
        dep = m.group(1)
    commune = re.sub(r"\s*\(.*?\)", "", commune).strip()
    arr = a.get("arrondissements") or []
    if commune.lower() == "paris":
        dep = "75"
        if len(arr) == 1:
            return f"{adresse} {75000 + int(arr[0])} Paris", {"dep": "75", "postcode": str(75000 + int(arr[0]))}
        return f"{adresse} Paris", {"dep": "75"}
    return f"{adresse} {commune}".strip(), {"dep": dep}


def executer():
    deals = lire_json("deals.json", {"transactions": []})
    ancien = lire_json(FICHIER, None) or {}
    fiches = dict(ancien.get("fiches", {}))
    ids = set()
    appels = nouveaux = rejetes = 0
    for t in deals.get("transactions", []):
        q, attendu = requete(t)
        if not q:
            continue
        ids.add(t["id"])
        prec = fiches.get(t["id"])
        if prec and prec.get("requete") == q:
            continue
        params = {"q": q, "limit": 1, "index": "address"}
        if attendu and attendu.get("postcode"):
            params["postcode"] = attendu["postcode"]
        appels += 1
        try:
            fc = json_url(API + "?" + urllib.parse.urlencode(params))
        except Exception:
            time.sleep(1)
            continue
        time.sleep(0.15)
        feats = fc.get("features") or []
        if not feats:
            fiches[t["id"]] = {"requete": q, "trouve": False}
            rejetes += 1
            continue
        f = feats[0]
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"][:2]
        code_postal = str(p.get("postcode") or "")
        ok = float(p.get("score") or 0) >= SCORE_MIN
        if attendu and attendu.get("dep") and code_postal and not code_postal.startswith(attendu["dep"]):
            ok = False
        if not ok:
            fiches[t["id"]] = {"requete": q, "trouve": False, "meilleur": p.get("label"), "score": round(float(p.get("score") or 0), 3)}
            rejetes += 1
            continue
        fiches[t["id"]] = {"requete": q, "trouve": True, "lat": round(lat, 6), "lon": round(lon, 6),
                           "libelle": p.get("label"), "precision": p.get("type"), "score": round(float(p.get("score") or 0), 3),
                           "code_insee": p.get("citycode")}
        nouveaux += 1
    for i in list(fiches):
        if i not in ids:
            del fiches[i]
    change = fiches != ancien.get("fiches")
    if change or not ancien:
        ecrire_json(FICHIER, {
            "source": {"editeur": "IGN — Géoplateforme, service de géocodage (Base Adresse Nationale)", "url": DOC,
                       "licence": "Licence Ouverte 2.0"},
            "maj": maintenant(),
            "note": "Seules les fiches dont l'adresse est publiée par une source sont géolocalisées ; la première adresse citée est retenue.",
            "fiches": dict(sorted(fiches.items())),
        })
    return {"change": bool(change or not ancien), "appels": appels, "geolocalisees": nouveaux, "rejetees": rejetes,
            "total": sum(1 for v in fiches.values() if v.get("trouve"))}
