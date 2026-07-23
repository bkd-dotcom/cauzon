# Cauzon — project website

A small static site for Cauzon. Plain HTML/CSS/JS, no build step, no
dependencies beyond a web font.

## Run locally

```bash
cd website
python3 -m http.server 8098
# open http://localhost:8098
```

## Deploy

Static files — publish the `website/` folder to any host. This repo deploys it
to GitHub Pages via `.github/workflows/deploy-pages.yml` on every push that
touches `website/`.

## Files

```
website/
├── index.html   # content
├── styles.css   # styling
├── app.js       # mobile nav toggle
└── assets/      # logo + icons
```
