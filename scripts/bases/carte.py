# -*- coding: utf-8 -*-
"""Fond de carte : contours des arrondissements de Paris et des communes de la petite couronne,
simplifiés et projetés en coordonnées SVG (largeur 1000)."""
import math

from commun import ecrire_json, json_url, maintenant

FICHIER = "carte.json"
FREQUENCE_JOURS = 180
LARGEUR = 1000
TOLERANCE = 0.00022  # degrés (≈ 20 m), après correction de la longitude
PARIS = [
    "https://geo.api.gouv.fr/communes?codeDepartement=75&type=arrondissement-municipal&format=geojson&geometry=contour",
    "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson/arrondissements-municipaux-50m.geojson",
    "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson/arrondissements-municipaux-100m.geojson",
    "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2025/geojson/arrondissements-municipaux-100m.geojson",
    "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/arrondissements-municipaux-100m.geojson",
]
COURONNE = "https://geo.api.gouv.fr/departements/{dep}/communes?format=geojson&geometry=contour"
DEPS = ["92", "93", "94"]


def _dp(points, tol):
    """Douglas-Peucker itératif sur une liste de (x, y)."""
    if len(points) < 4:
        return points
    garder = [False] * len(points)
    garder[0] = garder[-1] = True
    pile = [(0, len(points) - 1)]
    while pile:
        a, b = pile.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norme = math.hypot(dx, dy) or 1e-12
        dmax, imax = -1, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norme
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol and imax > 0:
            garder[imax] = True
            pile += [(a, imax), (imax, b)]
    return [p for p, g in zip(points, garder) if g]


def _simplifier_anneau(points, tol):
    """Anneau fermé : découpe au point le plus éloigné du premier, simplifie chaque moitié."""
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 4:
        return points
    x0, y0 = points[0]
    m = max(range(len(points)), key=lambda i: (points[i][0] - x0) ** 2 + (points[i][1] - y0) ** 2)
    a = _dp(points[: m + 1], tol)
    b = _dp(points[m:] + [points[0]], tol)
    return a[:-1] + b[:-1]


def _anneaux(geom):
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def _nom(code, nom):
    if code.startswith("751") and len(code) == 5:
        n = int(code[3:])
        return f"Paris {n}{'er' if n == 1 else 'e'}"
    return nom


def executer():
    zones, journal = [], {}
    paris = None
    for url in PARIS:
        try:
            fc = json_url(url)
            feats = [f for f in fc.get("features", []) if str(f.get("properties", {}).get("code", "")).startswith("751")]
            if len(feats) >= 20:
                paris = feats
                journal["75"] = url
                break
            journal.setdefault("essais_75", []).append(f"{url} : {len(feats)} zones")
        except Exception as e:
            journal.setdefault("essais_75", []).append(f"{url} : {type(e).__name__} {e}")
    if not paris:
        raise RuntimeError("contours de Paris introuvables : " + " | ".join(journal.get("essais_75", [])))
    for f in paris:
        p = f["properties"]
        zones.append((str(p["code"]), _nom(str(p["code"]), p.get("nom", "")), "75", f["geometry"]))
    for dep in DEPS:
        fc = json_url(COURONNE.format(dep=dep))
        for f in fc.get("features", []):
            p = f["properties"]
            zones.append((str(p["code"]), p.get("nom", ""), dep, f["geometry"]))
        journal[dep] = COURONNE.format(dep=dep)

    tous = [pt for _, _, _, g in zones for anneau in _anneaux(g) for pt in anneau]
    lon_min = min(p[0] for p in tous); lon_max = max(p[0] for p in tous)
    lat_min = min(p[1] for p in tous); lat_max = max(p[1] for p in tous)
    c = math.cos(math.radians((lat_min + lat_max) / 2))
    k = LARGEUR / ((lon_max - lon_min) * c)
    hauteur = round((lat_max - lat_min) * k, 1)

    def xy(lon, lat):
        return ((lon - lon_min) * c * k, (lat_max - lat) * k)

    sortie, px = [], []
    for code, nom, dep, geom in zones:
        chemins, meilleur, aire_max = [], None, -1
        for anneau in _anneaux(geom):
            plan = [((pt[0] - lon_min) * c, pt[1]) for pt in anneau]
            simple = _simplifier_anneau(plan, TOLERANCE)
            if len(simple) < 3:
                continue
            pts = [((x) * k, (lat_max - lat) * k) for x, lat in simple]
            chemins.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
            aire = 0.0; cx = cy = 0.0
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
                t = x1 * y2 - x2 * y1
                aire += t; cx += (x1 + x2) * t; cy += (y1 + y2) * t
            if abs(aire) > aire_max and aire:
                aire_max = abs(aire); meilleur = (cx / (3 * aire), cy / (3 * aire))
        if not chemins:
            continue
        sortie.append({"code": code, "nom": nom, "dep": dep, "d": "".join(chemins),
                       "c": [round(meilleur[0], 1), round(meilleur[1], 1)] if meilleur else None})
        if dep == "75":
            for anneau in _anneaux(geom):
                px += [xy(pt[0], pt[1]) for pt in anneau]
    marge = 12
    xs = [p[0] for p in px]; ys = [p[1] for p in px]
    cadre_paris = [round(min(xs) - marge, 1), round(min(ys) - marge, 1),
                   round(max(xs) - min(xs) + 2 * marge, 1), round(max(ys) - min(ys) + 2 * marge, 1)]
    ecrire_json(FICHIER, {
        "source": {"editeur": "API Découpage administratif (geo.api.gouv.fr) et contours administratifs Etalab, d'après l'IGN",
                   "url": "https://geo.api.gouv.fr/decoupage-administratif", "licence": "Licence Ouverte 2.0"},
        "maj": maintenant(),
        "largeur": LARGEUR, "hauteur": hauteur,
        "proj": {"lon0": lon_min, "lat0": lat_max, "c": c, "k": k},
        "cadre_paris": cadre_paris,
        "zones": sorted(sortie, key=lambda z: z["code"]),
    }, compact=True)
    return {"zones": len(sortie), "sources": journal}
