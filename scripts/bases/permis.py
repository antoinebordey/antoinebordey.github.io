# -*- coding: utf-8 -*-
"""Permis de construire (liste Sitadel des autorisations d'urbanisme créant des locaux non résidentiels) :
rapprochement avec les adresses des fiches. Seuls les demandeurs personnes morales (SIREN) sont nommés."""
import csv
import gzip
import io
import os
import re
import tempfile
import zipfile

from commun import ecrire_json, json_url, lire_json, maintenant, normaliser, segments_adresse, telecharger_vers

JEU_ID = "689c42fa521ccf80ce954f83"
JEU_API = f"https://www.data.gouv.fr/api/1/datasets/{JEU_ID}/"
JEU_PAGE = f"https://www.data.gouv.fr/fr/datasets/{JEU_ID}/"
FICHIER = "permis.json"
FREQUENCE_JOURS = 7
DEPS = ("75", "92", "93", "94")
DEPUIS = "2022-01-01"
TYPES_VOIE = {"RUE", "R", "AVENUE", "AV", "AVE", "BOULEVARD", "BD", "BLD", "BLVD", "PLACE", "PL", "QUAI", "QU", "IMPASSE", "IMP",
              "ALLEE", "ALL", "COURS", "CRS", "PASSAGE", "PAS", "SQUARE", "SQ", "VILLA", "VLA", "CITE", "CHEMIN", "CHE", "ROUTE", "RTE",
              "ESPLANADE", "ESP", "PARVIS", "PROMENADE", "PROM", "RUELLE", "SENTIER", "SEN", "VOIE", "ROND", "POINT", "RPT", "PORTE", "PTE",
              "HAMEAU", "HAM", "PASSERELLE", "GALERIE", "GAL", "COUR", "CARREFOUR", "CAR", "SENTE", "PLACETTE"}
ARTICLES = {"DU", "DE", "DES", "LA", "LE", "LES", "D", "L", "AU", "AUX"}
ABREV = {"ST": "SAINT", "STE": "SAINTE", "GAL": "GENERAL", "MAL": "MARECHAL", "PDT": "PRESIDENT", "PRES": "PRESIDENT"}


def coeur_voie(voie):
    mots = [ABREV.get(m, m) for m in normaliser(voie).split()]
    while mots and mots[0] in TYPES_VOIE:
        mots = mots[1:]
    return " ".join(m for m in mots if m not in ARTICLES)


def segments(adresse):
    for seg in segments_adresse(adresse):
        m = re.match(r"^\s*(\d+)\s*(?:bis|ter|quater|[a-z])?\s*(?:[-–à]\s*(\d+)\s*(?:bis|ter|[a-z])?)?[\s,]+(.+?)\s*$", seg, re.I)
        if not m:
            continue
        n1 = int(m.group(1)); n2 = int(m.group(2)) if m.group(2) else n1
        if n2 < n1:
            n1, n2 = n2, n1
        yield n1, n2, coeur_voie(m.group(3))


def cibles(deals, noms_communes):
    """{(code_commune, coeur_voie): [(id_fiche, n1, n2)]}"""
    index = {}
    for t in deals.get("transactions", []):
        a = t.get("actif") or {}
        commune = re.sub(r"\s*\(.*?\)", "", a.get("commune") or "").strip()
        if commune.lower() == "paris":
            codes = [f"751{int(n):02d}" for n in (a.get("arrondissements") or [])] or [f"751{n:02d}" for n in range(1, 21)]
        else:
            code = noms_communes.get(normaliser(commune))
            codes = [code] if code else ["NOM:" + normaliser(commune)]
        for n1, n2, voie in segments(a.get("adresse")):
            if not voie:
                continue
            for code in codes:
                index.setdefault((code, voie), []).append((t["id"], n1, n2))
    return index


def _col(entete, *noms, contient=None):
    maj = {c.upper().strip(): c for c in entete}
    for n in noms:
        if n in maj:
            return maj[n]
    if contient:
        for c in entete:
            u = c.upper()
            if all(x in u for x in contient):
                return c
    return None


def _date(v):
    v = (v or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return v[:10]
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return v[:10]


def _ressource():
    meta = json_url(JEU_API)
    res = meta.get("resources", [])
    titres = [f"{r.get('title')} [{r.get('format')}]" for r in res]
    candidats = [r for r in res if re.search(r"locaux|non.?r[ée]sidentiel", (r.get("title") or "") + " " + (r.get("description") or ""), re.I)]
    candidats = [r for r in candidats if (r.get("format") or "").lower() in ("csv", "zip", "gz", "csv.gz", "")] or candidats
    if not candidats:
        raise RuntimeError("aucune ressource « locaux » trouvée parmi : " + " | ".join(titres))
    candidats.sort(key=lambda r: (r.get("last_modified") or ""), reverse=True)
    return candidats[0], titres, meta.get("title")


def _ouvrir_csv(chemin):
    with open(chemin, "rb") as f:
        tete = f.read(4)
    if tete[:2] == b"PK":
        z = zipfile.ZipFile(chemin)
        nom = max((n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))), key=lambda n: z.getinfo(n).file_size)
        brut = z.open(nom)
    elif tete[:2] == b"\x1f\x8b":
        brut = gzip.open(chemin, "rb")
    else:
        brut = open(chemin, "rb")
    texte = io.TextIOWrapper(brut, encoding="utf-8", errors="replace", newline="")
    premiere = texte.readline()
    sep = ";" if premiere.count(";") >= premiere.count(",") else ","
    entete = next(csv.reader([premiere], delimiter=sep))
    entete = [h.strip().strip('"').lstrip("﻿") for h in entete]
    return entete, csv.reader(texte, delimiter=sep)


def executer():
    deals = lire_json("deals.json", {"transactions": []})
    carte = lire_json("carte.json", {}) or {}
    noms = {normaliser(z["nom"]): z["code"] for z in carte.get("zones", []) if not z["code"].startswith("751")}
    index = cibles(deals, noms)
    ressource, titres, titre_jeu = _ressource()
    with tempfile.TemporaryDirectory() as tmp:
        chemin = os.path.join(tmp, "permis.bin")
        telecharger_vers(ressource["url"], chemin, timeout=900)
        entete, lecteur = _ouvrir_csv(chemin)
        c = {
            "dep": _col(entete, "DEP", "DEP_CODE", "CODE_DEP", "DEPARTEMENT", "DEP_CODE_TER"),
            "comm": _col(entete, "COMM", "COMM_CODE", "CODE_COMMUNE", "INSEE_COM", "CODGEO", "COM", "COMM_CODE_TER"),
            "num": _col(entete, "ADR_NUM_TER", "NUM_VOIE_TER", contient=("NUM", "TER")),
            "voie": _col(entete, "ADR_LIBVOIE_TER", "LIBVOIE_TER", contient=("LIBVOIE",)),
            "typevoie": _col(entete, "ADR_TYPEVOIE_TER", "TYPEVOIE_TER", contient=("TYPEVOIE",)),
            "cp": _col(entete, "ADR_CODPOST_TER", "CODPOST_TER", contient=("CODPOST", "TER")),
            "localite": _col(entete, "ADR_LOCALITE_TER", "LOCALITE_TER", contient=("LOCALITE", "TER")),
            "type": _col(entete, "TYPE_DAU", contient=("TYPE", "DAU")),
            "numero": _col(entete, "NUM_DAU", contient=("NUM", "DAU")),
            "etat": _col(entete, "ETAT_DAU", contient=("ETAT", "DAU")),
            "date": _col(entete, "DATE_REELLE_AUTORISATION", "DPC_AUT", contient=("DATE", "AUTORIS")),
            "debut": _col(entete, "DATE_REELLE_DOC", contient=("DATE", "DOC")),
            "fin": _col(entete, "DATE_REELLE_DAACT", contient=("DATE", "DAACT")),
            "nature": _col(entete, "NATURE_PROJET_COMPLETEE", "NATURE_PROJET_DECLAREE", contient=("NATURE", "PROJET")),
            "denom": _col(entete, "DENOM_DEM", contient=("DENOM",)),
            "siren": _col(entete, "SIREN_DEM", contient=("SIREN",)),
        }
        manquantes = [k for k in ("num", "voie", "date") if not c[k]]
        if manquantes or not (c["comm"] or c["cp"]):
            raise RuntimeError(f"colonnes introuvables {manquantes} ; en-tête : {entete[:80]}")
        pos = {k: entete.index(v) for k, v in c.items() if v}
        surfaces = [(i, h) for i, h in enumerate(entete) if "SURF" in h.upper()]
        lus = retenus = 0
        resultats = {}
        for ligne in lecteur:
            lus += 1
            def v(k):
                i = pos.get(k)
                return ligne[i].strip() if i is not None and i < len(ligne) else ""
            comm, cp = v("comm"), v("cp")
            dep = v("dep") or (comm[:2] if comm else cp[:2])
            if dep[:2] not in DEPS:
                continue
            date = _date(v("date"))
            if date < DEPUIS:
                continue
            if comm in ("75056", "") and cp.startswith("750") and len(cp) == 5:
                comm = "751" + cp[3:]
            num = re.match(r"\d+", v("num"))
            voie = coeur_voie(v("voie"))
            if not num or not voie:
                continue
            num = int(num.group())
            touches = index.get((comm, voie), []) + index.get(("NOM:" + normaliser(v("localite")), voie), [])
            if not touches:
                continue
            for id_fiche, n1, n2 in touches:
                if not (n1 <= num <= n2):
                    continue
                surf = {}
                for i, h in surfaces:
                    if i < len(ligne):
                        try:
                            x = float(ligne[i].replace(",", ".") or 0)
                        except ValueError:
                            continue
                        if x:
                            surf[h] = round(x)
                entree = {"type": v("type"), "numero": v("numero"), "date_autorisation": date, "etat": v("etat"),
                          "debut_travaux": _date(v("debut")) or None, "achevement": _date(v("fin")) or None,
                          "adresse": " ".join(x for x in (str(num), v("typevoie"), v("voie")) if x), "code_commune": comm, "nature_projet": v("nature"),
                          "surfaces": surf}
                if v("siren"):
                    entree["demandeur"] = v("denom") or None
                    entree["siren"] = v("siren")
                liste = resultats.setdefault(id_fiche, [])
                if entree["numero"] not in {e["numero"] for e in liste}:
                    liste.append(entree)
                    retenus += 1
    for liste in resultats.values():
        liste.sort(key=lambda e: e["date_autorisation"], reverse=True)
    ecrire_json(FICHIER, {
        "source": {"editeur": "SDES — liste des permis de construire et autres autorisations d'urbanisme (Sitadel)",
                   "jeu": titre_jeu, "fichier": ressource.get("title"), "url": JEU_PAGE,
                   "maj_source": ressource.get("last_modified"), "licence": "Licence Ouverte 2.0"},
        "maj": maintenant(),
        "depuis": DEPUIS,
        "note": "Autorisations rapprochées par numéro et nom de voie de l'adresse publiée de l'actif ; seuls les demandeurs personnes morales sont nommés.",
        "fiches": dict(sorted(resultats.items())),
    })
    return {"lignes_lues": lus, "permis_rattaches": retenus, "fiches": len(resultats), "ressource": ressource.get("title"),
            "colonnes": {k: v for k, v in c.items()}, "entete": entete[:150], "ressources_du_jeu": titres}
