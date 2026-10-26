# -*- coding: utf-8 -*-
"""Met à jour les bases publiques du site. Chaque module a sa fréquence ; un module en échec
est retenté le lendemain. L'état de chaque module est consigné dans data/bases_etat.json."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from commun import DATA, age_jours, ecrire_json, lire_json, maintenant  # noqa: E402
import carte, dvf, geocodage, permis, taux  # noqa: E402

MODULES = [("taux", taux), ("carte", carte), ("geocodage", geocodage), ("dvf", dvf), ("permis", permis)]


def main():
    forcer = (os.environ.get("FORCER") or "").strip().lower() in ("oui", "1", "true", "yes")
    seul = [m for m in (os.environ.get("MODULES") or "").replace(",", " ").split() if m]
    etat = lire_json("bases_etat.json", None) or {"modules": {}}
    modifie, echecs = False, 0
    for nom, mod in MODULES:
        if seul and nom not in seul:
            continue
        e = dict(etat["modules"].get(nom, {}))
        absent = not os.path.exists(os.path.join(DATA, mod.FICHIER))
        frequence = getattr(mod, "FREQUENCE_JOURS", 7)
        a_faire = forcer or absent or getattr(mod, "TOUJOURS", False) or age_jours(e.get("derniere_reussite")) >= frequence
        if e.get("statut") == "erreur" and age_jours(e.get("derniere_tentative")) >= 0.9:
            a_faire = True
        if not a_faire:
            print(f"[{nom}] à jour")
            continue
        print(f"[{nom}] mise à jour…", flush=True)
        tentative = maintenant()
        try:
            res = mod.executer() or {}
            print(f"[{nom}] ok : {res}", flush=True)
            if res.get("change") is False and e.get("statut") == "ok" and not forcer:
                continue
            e.update(statut="ok", derniere_tentative=tentative, derniere_reussite=maintenant(), resultat=res, erreur=None)
        except Exception as ex:
            echecs += 1
            traceback.print_exc()
            e.update(statut="erreur", derniere_tentative=tentative, erreur=f"{type(ex).__name__}: {ex}"[:3000])
        etat["modules"][nom] = e
        modifie = True
    if modifie:
        etat["maj"] = maintenant()
        etat["note"] = "État des mises à jour automatiques des bases publiques du site."
        ecrire_json("bases_etat.json", etat)
    print("Terminé" + (f" ({echecs} module(s) en échec)" if echecs else ""))


if __name__ == "__main__":
    main()
