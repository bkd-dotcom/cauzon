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

3. **Update the routing table** in `skills/using-datahub/SKILL.md`. This step is
   easy to miss and the skill is unreachable without it: that table currently
   routes root-cause requests to `datahub-lineage`, so a user asking "why did this
   break?" would never land here.

   Change the lineage row to drop `root cause`, and add a row beneath it:

   ```diff
   -| **Explore lineage** (upstream, downstream, impact, root cause, dependencies)     | **Lineage** | `/datahub-lineage` |
   +| **Explore lineage** (upstream, downstream, impact, dependencies)                 | **Lineage** | `/datahub-lineage` |
   +| **Diagnose an incident** (why did X break, root cause of a failing assertion)    | **RCA**     | `/datahub-rca`     |
   ```

   Keep the column alignment — `prettier` and `markdownlint` both run in CI and
   will reformat or reject a ragged table.

4. **Register the skill/command** in `README.md` (follow the existing rows for
   `datahub-lineage` / `catalog-lineage`). There are several places that list the
   catalog skills — the usage examples, the `cp -r` install instructions, the
   directory tree, and the contributing paths — so grep for `datahub-lineage` and
   add a sibling entry wherever it appears.

   The `.claude-plugin/marketplace.json` lists a single bundled plugin with
   `source: "./"`, so no change is required there.

5. **Run the linters** (they run in CI too):

   ```bash
   pip install pre-commit && pre-commit install
   pre-commit run --all-files
   ```

6. **Commit with a Conventional-Commit title** (enforced by CI):

   ```bash
   git add skills/datahub-rca commands/catalog-rca.md \
     skills/using-datahub/SKILL.md README.md
   git commit -m "feat: add datahub-rca skill for path-grounded root-cause analysis"
   git push -u origin feat/datahub-rca-skill
   gh pr create --repo datahub-project/datahub-skills \
     --title "feat: add datahub-rca skill for path-grounded root-cause analysis" \
     --body-file /path/to/cauzon/contrib/datahub-skills-pr/PR_BODY.md
   ```

## PR title

```
feat: add datahub-rca skill for path-grounded root-cause analysis
```

(Use the `feat:` prefix — the repo enforces Conventional Commits and this earns
a minor version bump.)
