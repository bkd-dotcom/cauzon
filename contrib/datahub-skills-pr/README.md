# How to open the `datahub-rca` skill PR

This directory contains a ready-to-contribute DataHub Skill, formatted to match
the conventions of
[`datahub-project/datahub-skills`](https://github.com/datahub-project/datahub-skills)
(verified against the repo's `datahub-lineage` skill and `CONTRIBUTING.md`).

Contributing this skill triggers the hackathon's **Meaningful Open-Source
Contribution** bonus criterion.

## What's here

```
contrib/datahub-skills-pr/
├── skills/datahub-rca/
│   ├── SKILL.md                                  # the skill (correct frontmatter)
│   ├── README.md
│   ├── references/rca-signals-reference.md
│   ├── references/grounding-reference.md
│   ├── templates/incident-dossier.template.md
│   └── evaluations/diagnose-volume-drop.json
└── commands/catalog-rca.md                       # slash-command wrapper
```

## Steps

1. **Fork & clone** the skills repo:

   ```bash
   gh repo fork datahub-project/datahub-skills --clone
   cd datahub-skills
   git checkout -b feat/datahub-rca-skill
   ```

2. **Copy the files** from this directory into the fork (paths already match):

   ```bash
   cp -R /path/to/cauzon/contrib/datahub-skills-pr/skills/datahub-rca skills/
   cp /path/to/cauzon/contrib/datahub-skills-pr/commands/catalog-rca.md commands/
   ```

3. **Register the skill/command** in `README.md`'s skill table (follow the
   existing rows for `datahub-lineage` / `catalog-lineage`). The
   `.claude-plugin/marketplace.json` lists a single bundled plugin, so no change
   is required there — but do add the new skill + command to the README so users
   can discover it.

4. **Run the linters** (they run in CI too):

   ```bash
   pip install pre-commit && pre-commit install
   pre-commit run --all-files
   ```

5. **Commit with a Conventional-Commit title** (enforced by CI):

   ```bash
   git add skills/datahub-rca commands/catalog-rca.md README.md
   git commit -m "feat: add datahub-rca skill for path-grounded root-cause analysis"
   git push -u origin feat/datahub-rca-skill
   gh pr create --repo datahub-project/datahub-skills \
     --title "feat: add datahub-rca skill for path-grounded root-cause analysis" \
     --body-file contrib/datahub-skills-pr/PR_BODY.md
   ```

## PR title

```
feat: add datahub-rca skill for path-grounded root-cause analysis
```

(Use the `feat:` prefix — the repo enforces Conventional Commits and this earns
a minor version bump.)
