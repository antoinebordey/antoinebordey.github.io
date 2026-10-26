# -*- coding: utf-8 -*-
"""Outils communs aux scripts de mise à jour des bases publiques (bibliothèque standard uniquement)."""
import datetime
import json
import os
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(RACINE, "data")
UA = "ParisDealMonitor/1.0 (+https://antoinebordey.github.io)"


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def age_jours(iso):
    if not iso:
        return 10 ** 6
    try:
        d = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return 10 ** 6
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds() / 86400


def ouvrir(url, timeout=120, entetes=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(entetes or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def telecharger(url, timeout=120, essais=3, entetes=None):
    """Renvoie le contenu (bytes). Les erreurs 404/410 sont remontées immédiatement."""
    derniere = None
    for i in range(essais):
        try:
            with ouvrir(url, timeout=timeout, entetes=entetes) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 410):
                raise
            derniere = e
        except Exception as e:  # réseau, délai…
            derniere = e
        time.sleep(3 * (i + 1))
    raise derniere


def telecharger_vers(url, chemin, timeout=600, essais=3):
    """Télécharge un gros fichier sur disque, par morceaux."""
    derniere = None
    for i in range(essais):
        try:
            with ouvrir(url, timeout=timeout) as r, open(chemin, "wb") as f:
                while True:
                    bloc = r.read(1 << 20)
                    if not bloc:
                        break
                    f.write(bloc)
            return chemin
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 410):
                raise
            derniere = e
        except Exception as e:
            derniere = e
        time.sleep(5 * (i + 1))
    raise derniere


def json_url(url, **params):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return json.loads(telecharger(url).decode("utf-8"))


def lire_json(nom, defaut=None):
    chemin = os.path.join(DATA, nom)
    if not os.path.exists(chemin):
        return defaut
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def ecrire_json(nom, obj, compact=False):
    chemin = os.path.join(DATA, nom)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, chemin)


def sans_accents(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def normaliser(s):
    """Majuscules, sans accents ni ponctuation, espaces simples."""
    s = sans_accents(s).upper()
    s = "".join(c if c.isalnum() else " " for c in s)
    return " ".join(s.split())


def segments_adresse(adresse):
    """Découpe « 38-46 rue du Rocher et 19-23 rue de Vienne, 75008 Paris » en adresses élémentaires,
    sans code postal ni commune ni parenthèses."""
    import re
    a = re.sub(r"\([^)]*\)", " ", adresse or "")
    a = re.sub(r",?\s*\b\d{5}\b.*$", "", a)
    morceaux = re.split(r"\s+et\s+|;|/|,\s*(?=\d)", a, flags=re.I)
    return [" ".join(m.split()).strip(" ,") for m in morceaux if m and m.strip(" ,")]
