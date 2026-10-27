# -*- coding: utf-8 -*-
"""Géocodage des adresses des fiches (Base Adresse Nationale, service de géocodage de la Géoplateforme IGN).

Un résultat n'est retenu que s'il correspond à l'adresse demandée : même voie, même numéro (quand le
service renvoie un numéro), même arrondissement ou même département. Sinon la fiche reste sans position."""
import re
import time
import unicodedata
import urllib.parse

from commun import ecrire_json, json_url, lire_json, maintenant, segments_adresse

API = "https://data.geopf.fr/geocodage/search"
DOC = "https://geoservices.ign.fr/documentation/services/services-geoplateforme/geocodage"
FICHIER = "geo.json"
FREQUENCE_JOURS = 0  # incrémental : ne relance que les adresses nouvelles ou modifiées
TOUJOURS = True
SCORE_MIN = 0.6
METHODE = 2  # à incrémenter quand les règles changent : tout est alors recalculé
TYPES_RETENUS = ("housenumber", "street")
MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "l", "d", "et", "a", "au", "aux", "en", "sur"}
ABREVIATIONS = {"bd": "boulevard", "bld": "boulevard", "av": "avenue", "ave": "avenue", "pl": "place", "fg": "faubourg",
                "fbg": "faubourg", "st": "saint", "ste": "sainte", "sq": "square", "imp": "impasse", "pass": "passage"}


def premiere_adresse(adresse):
    segs = segments_adresse(adresse)
    if not segs:
        return ""
    seg = segs[0]
    m = re.match(r"^(\d+)\s*(bis|ter|quater)?\s*(?:(?:[-–]|à)\s*\d+\s*(?:bis|ter)?)?[\s,]+(.+)$", seg, re.I)
    if m:
        return f"{m.group(1)}{' ' + m.group(2) if m.group(2) else ''} {m.group(3)}".strip()
    return seg


def decouper(adresse):
    """« 90 bis avenue Victor Hugo » -> ("90", "bis", "avenue Victor Hugo")."""
    m = re.match(r"^(\d+)\s*(bis|ter|quater)?\s+(.+)$", adresse, re.I)
    if m:
        return m.group(1), (m.group(2) or "").lower(), m.group(3)
    return None, "", adresse


def normaliser(texte):
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode("ascii").lower()
    mots = re.sub(r"[^a-z0-9]+", " ", t).split()
    return [ABREVIATIONS.get(w, w) for w in mots]


def meme_voie(demandee, trouvee):
    a = [w for w in normaliser(demandee) if w not in MOTS_VIDES]
    b = {w for w in normaliser(trouvee) if w not in MOTS_VIDES}
    return bool(a) and all(w in b for w in a)


def requete(t):
    """Texte de la requête et contrôles attendus sur le résultat."""
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
    arr = [int(x) for x in (a.get("arrondissements") or [])]
    numero, suffixe, voie = decouper(adresse)
    attendu = {"numero": numero, "suffixe": suffixe, "voie": voie}
    if commune.lower() == "paris":
        attendu["codes_insee"] = [str(75100 + x) for x in arr] or None
        attendu["paris"] = True
        # Le 16e a deux codes postaux (75016 et 75116) : pas de code postal dans la requête pour lui.
        if len(arr) == 1 and arr[0] != 16:
            return f"{adresse} {75000 + arr[0]} Paris", attendu
        return f"{adresse} Paris", attendu
    attendu["dep"] = dep
    return f"{adresse} {commune}".strip(), attendu


def controler(p, attendu):
    """Renvoie None si le résultat correspond à l'adresse demandée, sinon le motif du rejet."""
    score = float(p.get("score") or 0)
    if score < SCORE_MIN:
        return "score insuffisant"
    if p.get("type") not in TYPES_RETENUS:
        return "résultat trop imprécis"
    if not meme_voie(attendu["voie"], p.get("street") or p.get("name") or ""):
        return "voie différente"
    if p.get("type") == "housenumber" and attendu.get("numero"):
        m = re.match(r"^(\d+)\s*([a-z]*)", "".join(normaliser(str(p.get("housenumber") or ""))))
        if not m or m.group(1) != attendu["numero"] or (attendu.get("suffixe") and not m.group(2).startswith(attendu["suffixe"][0])):
            return "numéro différent"
    code_insee = str(p.get("citycode") or "")
    if attendu.get("paris"):
        if not code_insee.startswith("751"):
            return "commune différente"
        if attendu.get("codes_insee") and code_insee not in attendu["codes_insee"]:
            return "arrondissement différent"
    elif attendu.get("dep"):
        code_postal = str(p.get("postcode") or "")
        if code_postal and not code_postal.startswith(attendu["dep"]):
            return "département différent"
    return None


def executer():
    deals = lire_json("deals.json", {"transactions": []})
    ancien = lire_json(FICHIER, None) or {}
    meme_methode = ancien.get("methode") == METHODE
    fiches = dict(ancien.get("fiches", {})) if meme_methode else {}
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
        appels += 1
        try:
            fc = json_url(API + "?" + urllib.parse.urlencode({"q": q, "limit": 1, "index": "address"}))
        except Exception:
            time.sleep(1)
            continue
        time.sleep(0.15)
        feats = fc.get("features") or []
        if not feats:
            fiches[t["id"]] = {"requete": q, "trouve": False, "motif": "aucun résultat"}
            rejetes += 1
            continue
        f = feats[0]
        p = f.get("properties", {})
        motif = controler(p, attendu)
        if motif:
            fiches[t["id"]] = {"requete": q, "trouve": False, "motif": motif, "meilleur": p.get("label"),
                               "score": round(float(p.get("score") or 0), 3)}
            rejetes += 1
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        fiches[t["id"]] = {"requete": q, "trouve": True, "lat": round(lat, 6), "lon": round(lon, 6),
                           "libelle": p.get("label"), "precision": p.get("type"), "score": round(float(p.get("score") or 0), 3),
                           "code_insee": p.get("citycode")}
        nouveaux += 1
    for i in list(fiches):
        if i not in ids:
            del fiches[i]
    change = (fiches != ancien.get("fiches")) or not meme_methode
    if change or not ancien:
        ecrire_json(FICHIER, {
            "source": {"editeur": "IGN — Géoplateforme, service de géocodage (Base Adresse Nationale)", "url": DOC,
                       "licence": "Licence Ouverte 2.0"},
            "maj": maintenant(),
            "methode": METHODE,
            "note": ("Seules les fiches dont l'adresse est publiée par une source sont géolocalisées ; la première adresse "
                     "citée est retenue, et seulement si la voie, le numéro et l'arrondissement trouvés correspondent."),
            "fiches": dict(sorted(fiches.items())),
        })
    return {"change": bool(change or not ancien), "appels": appels, "geolocalisees": nouveaux, "rejetees": rejetes,
            "total": sum(1 for v in fiches.values() if v.get("trouve"))}
