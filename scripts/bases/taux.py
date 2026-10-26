# -*- coding: utf-8 -*-
"""Taux de l'OAT 10 ans : série mensuelle de la Banque centrale européenne (taux long terme, France)."""
import csv
import io

from commun import ecrire_json, maintenant, telecharger

SERIE = "IRS.M.FR.L.L40.CI.0000.EUR.N.Z"
API = "https://data-api.ecb.europa.eu/service/data/IRS/M.FR.L.L40.CI.0000.EUR.N.Z?format=csvdata&startPeriod=2015-01"
PAGE = "https://data.ecb.europa.eu/data/datasets/IRS/IRS.M.FR.L.L40.CI.0000.EUR.N.Z"
FICHIER = "taux.json"
FREQUENCE_JOURS = 6


def executer():
    brut = telecharger(API, entetes={"Accept": "text/csv"}).decode("utf-8-sig")
    points = []
    for ligne in csv.DictReader(io.StringIO(brut)):
        periode, valeur = (ligne.get("TIME_PERIOD") or "").strip(), (ligne.get("OBS_VALUE") or "").strip()
        if not periode or not valeur:
            continue
        try:
            points.append({"periode": periode, "valeur": round(float(valeur), 3)})
        except ValueError:
            continue
    points.sort(key=lambda p: p["periode"])
    if len(points) < 24:
        raise ValueError(f"série trop courte ({len(points)} points)")
    ecrire_json(FICHIER, {
        "titre": "Taux de l'OAT 10 ans",
        "description": "Rendement des emprunts d'État français à 10 ans, moyenne mensuelle (taux long terme publié par la BCE pour la France).",
        "unite": "%",
        "source": {
            "editeur": "Banque centrale européenne — ECB Data Portal",
            "titre": f"Taux d'intérêt à long terme, France, échéance 10 ans (série {SERIE})",
            "url": PAGE,
            "conditions": "Statistiques de la BCE, réutilisables avec mention de la source.",
        },
        "maj": maintenant(),
        "points": points,
    })
    return {"points": len(points), "dernier": points[-1]}
