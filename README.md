# Paris Deal Monitor

Veille des transactions immobilières à Paris, à La Défense et en Île-de-France, par Antoine Bordey.

Site : https://antoinebordey.github.io

- `index.html` : le site (HTML, CSS et JavaScript, sans dépendance).
- `data/deals.json` : les opérations recensées et leurs sources, mis à jour automatiquement trois fois par semaine.
- `data/dvf.json`, `taux.json`, `permis.json`, `geo.json`, `carte.json` : bases publiques (prix DVF agrégés, OAT 10 ans, permis de construire, géolocalisation des adresses, contours), mises à jour automatiquement par les scripts de `scripts/bases/`.

Chaque chiffre est relié à une source publique ; les valeurs non communiquées restent marquées « NC ».
