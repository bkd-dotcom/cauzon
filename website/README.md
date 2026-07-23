# Cauzon — Landing Website

A high-end, dependency-free marketing site for Cauzon (path-grounded root-cause
analysis for DataHub). Pure HTML/CSS/JS — no build step.

## Component patterns used

Inspired by top UI component libraries (Aceternity, Magic UI, Linear, Vercel/Geist):

- **Aurora background** — animated gradient orbs + masked dot-grid
- **Animated gradient-border cards** with cursor **spotlight**
- **Bento grid** architecture showcase
- **Animated beam lineage** — the interactive investigation replay
- **Marquee** of MCP tools
- **Number tickers**, **scroll-reveal**, **scroll progress bar**
- **Glassmorphism** nav that morphs to a floating pill on scroll
- **Typewriter terminal** replay of a live investigation
- Full **reduced-motion** and mobile support

## Run locally

```bash
cd website
python3 -m http.server 8099
# open http://localhost:8099
```

## Deploy

It's static — deploy the `website/` folder to any host:

- **GitHub Pages**: set Pages source to `/website` (or move contents to `/docs`)
- **Netlify / Vercel / Cloudflare Pages**: publish directory = `website`, no build command

## Files

```
website/
├── index.html      # all sections
├── styles.css      # premium styling + component patterns
├── app.js          # interactions (terminal, replay, reveal, tickers, nav)
└── assets/         # logo + icons
```
