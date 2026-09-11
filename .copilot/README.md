# .copilot/ — Configuration Copilot du dépôt

Ce répertoire centralise les consignes et compétences partagées par les clients Copilot et les outils associés.

## Structure

```text
.copilot/
├── instructions.md
├── skills/
│   ├── demo-seed-check/
│   ├── local-demo/
│   └── web-build-test/
└── README.md
```

## Ce qui est documenté ici

- `.copilot/instructions.md` : instructions globales et règles de contribution
- `.copilot/skills/*/SKILL.md` : compétences réutilisables et vérifiées
- `AGENTS.md` : source de vérité du dépôt, ses conventions et ses hypothèses métier
- `CLAUDE.md` et `COPILOT.md` : points d'entrée pour les outils spécifiques

## Quand utiliser une skill

Invocation via `skill: "demo-seed-check"`, `skill: "web-build-test"` ou
`skill: "local-demo"` dans un chat Copilot.

## Règles

- Ne pas dupliquer les compétences dans plusieurs emplacements.
- Mettre les règles métier dans `AGENTS.md`, pas dans les skills.
- Garder les fichiers de dépôt cohérents avec l'usage local de données bancaires sensibles.
- Pour tout changement fonctionnel, maintenir la seed avec `demo-seed-check` avant la validation
  globale avec `web-build-test`, puis présenter le résultat avec `local-demo`.
