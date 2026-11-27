# Changelog

Format bazat pe [Keep a Changelog](https://keepachangelog.com/). Versiunile urmează `manifest.json`.

## [0.2.0] - 2026-11-27

### Cerințe
- Necesită Home Assistant **2026.3** sau mai nou (iconița integrării e încărcată din folderul local `brand/`, suportat de la 2026.3).

### Modificări care pot strica configurări existente
- Starea senzorului **„Rovinietă valabilă până la”** este acum o **dată** (tip `date`), nu text `dd.mm.yyyy`. Automatizările sau șabloanele care parsau textul trebuie actualizate (folosește direct starea ca dată sau senzorul `timestamp`).

### Reparat
- La o eroare temporară la citirea vehiculelor sau a facturilor, integrarea păstrează ultimele valori cunoscute, în loc să marcheze vehiculele ca indisponibile sau să arate totalul plătit ca 0.
- Un răspuns `403` sau `429` de la portal nu mai deschide fals fluxul de reautentificare; doar `401` înseamnă autentificare eșuată.

### Adăugat
- `VIN` și seria certificatului de înmatriculare sunt dezactivate implicit (categorie „diagnostic”).
- Teste automate (81) și validare în GitHub Actions (hassfest, HACS, ruff, mypy, pytest).
- Autoevaluare Integration Quality Scale (`quality_scale.yaml`, țintă Bronze).
- Secțiuni noi în README: dispozitive suportate, actualizarea datelor, depanare, dezinstalare.
