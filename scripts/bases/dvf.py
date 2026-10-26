# -*- coding: utf-8 -*-
"""Prix des ventes (DVF géolocalisées, Etalab) : médianes au m² par commune / arrondissement.

Règles de réutilisation DVF : aucune vente individuelle n'est publiée, seulement des agrégats
calculés sur au moins SEUIL ventes ; les fichiers bruts ne sont jamais enregistrés dans le dépôt.
"""
import csv
import datetime
import gzip
import os
import statistics
import tempfile
import urllib.error

from commun import ecrire_json, maintenant, telecharger_vers

DEPARTEMENTS = {"75": "Paris", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne"}
URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{dep}.csv.gz"
JEU = "https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
JEU_DGFIP = "https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres/"
FICHIER = "dvf.json"
FREQUENCE_JOURS = 30
SEUIL = 11
CATEGORIES = {
    "local": "Locaux commerciaux et assimilés (bureaux, commerces, locaux d'activité)",
    "appartement": "Appartements",
}
CODES = {"2": "appartement", "4": "local"}
LIBELLES = {"Appartement": "appartement", "Local industriel. commercial ou assimilé": "local"}
BATI = {"1", "2", "4", "Maison", "Appartement", "Local industriel. commercial ou assimilé"}
BORNES = {"appartement": (1000, 60000), "local": (300, 100000)}


def _nom_zone(code, nom):
    if code.startswith("751") and len(code) == 5:
        n = int(code[3:])
        return f"Paris {n}{'er' if n == 1 else 'e'}"
    return nom


def _stats(valeurs):
    n = len(valeurs)
    if n < SEUIL:
        return {"n": n}
    valeurs = sorted(valeurs)
    q1, med, q3 = statistics.quantiles(valeurs, n=4, method="inclusive")
    return {"n": n, "med": round(med), "q1": round(q1), "q3": round(q3)}


def _lignes(chemin):
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def executer():
    annee_courante = datetime.date.today().year
    annees = [str(a) for a in range(annee_courante - 6, annee_courante + 1)]
    acc = {c: {} for c in CATEGORIES}      # cat -> zone -> année -> [prix]
    acc_dep = {c: {} for c in CATEGORIES}  # cat -> dep -> année -> [prix]
    zones, fichiers = {}, {}
    dmin, dmax = "9999", "0000"
    with tempfile.TemporaryDirectory() as tmp:
        for dep in DEPARTEMENTS:
            for annee in annees:
                cle = f"{dep}-{annee}"
                chemin = os.path.join(tmp, cle + ".csv.gz")
                try:
                    telecharger_vers(URL.format(annee=annee, dep=dep), chemin)
                except urllib.error.HTTPError as e:
                    fichiers[cle] = f"absent ({e.code})"
                    continue
                mutations = {}
                for r in _lignes(chemin):
                    if (r.get("nature_mutation") or "") != "Vente":
                        continue
                    idm = r.get("id_mutation")
                    m = mutations.get(idm)
                    if m is None:
                        try:
                            valeur = float(r.get("valeur_fonciere") or "nan")
                        except ValueError:
                            valeur = float("nan")
                        m = mutations[idm] = {"date": r.get("date_mutation") or "", "valeur": valeur,
                                              "commune": r.get("code_commune") or "", "nom": r.get("nom_commune") or "",
                                              "locaux": set()}
                    code = (r.get("code_type_local") or "").strip()
                    libelle = (r.get("type_local") or "").strip()
                    if code in BATI or libelle in BATI:
                        try:
                            surface = float(r.get("surface_reelle_bati") or 0)
                        except ValueError:
                            surface = 0.0
                        cat = CODES.get(code) or LIBELLES.get(libelle) or "autre"
                        m["locaux"].add((cat, r.get("id_parcelle") or "", r.get("lot_1_numero") or "", surface))
                os.remove(chemin)
                retenues = 0
                for m in mutations.values():
                    if len(m["locaux"]) != 1 or not (m["valeur"] > 0):
                        continue
                    cat, _, _, surface = next(iter(m["locaux"]))
                    if cat not in CATEGORIES or surface <= 0:
                        continue
                    prix = m["valeur"] / surface
                    bas, haut = BORNES[cat]
                    if not (bas <= prix <= haut) or len(m["date"]) < 4:
                        continue
                    a = m["date"][:4]
                    z = m["commune"]
                    acc[cat].setdefault(z, {}).setdefault(a, []).append(prix)
                    acc_dep[cat].setdefault(dep, {}).setdefault(a, []).append(prix)
                    zones[z] = {"nom": _nom_zone(z, m["nom"]), "dep": dep}
                    dmin, dmax = min(dmin, m["date"]), max(dmax, m["date"])
                    retenues += 1
                fichiers[cle] = f"ok ({retenues} ventes retenues)"
    if not zones:
        raise RuntimeError("aucune vente exploitable : " + "; ".join(f"{k} {v}" for k, v in fichiers.items()))

    def tableau(source):
        sortie = {}
        for cat, par_zone in source.items():
            sortie[cat] = {}
            for z, par_annee in par_zone.items():
                tout = [p for liste in par_annee.values() for p in liste]
                sortie[cat][z] = {a: _stats(v) for a, v in sorted(par_annee.items())}
                sortie[cat][z]["periode"] = _stats(tout)
        return sortie

    annees_vues = sorted({a for par_zone in acc.values() for par_annee in par_zone.values() for a in par_annee})
    partielles = [a for a in annees_vues if dmin > f"{a}-01-15" or dmax < f"{a}-12-15"]
    ecrire_json(FICHIER, {
        "titre": "Prix des ventes immobilières (DVF)",
        "source": {
            "editeur": "DGFiP — Demandes de valeurs foncières, version géolocalisée publiée par Etalab",
            "url": JEU, "url_dgfip": JEU_DGFIP, "licence": "Licence Ouverte 2.0",
        },
        "methode": ("Ventes de gré à gré (nature « Vente ») portant sur un seul local bâti, rapportées à la surface réelle bâtie. "
                    "Valeurs aberrantes écartées. Médiane et quartiles publiés seulement à partir de "
                    f"{SEUIL} ventes ; aucune vente individuelle n'est diffusée. Les cessions de sociétés (share deals) "
                    "et les ventes de plusieurs lots ne figurent pas dans ce calcul."),
        "seuil_ventes": SEUIL,
        "maj": maintenant(),
        "periode": {"debut": dmin, "fin": dmax},
        "annees": annees_vues,
        "annees_partielles": partielles,
        "categories": CATEGORIES,
        "departements": DEPARTEMENTS,
        "zones": dict(sorted(zones.items())),
        "stats": tableau(acc),
        "agregats": tableau(acc_dep),
        "fichiers": fichiers,
    }, compact=True)
    return {"zones": len(zones), "periode": f"{dmin} → {dmax}", "fichiers": fichiers}
