# Contribuer — MDL Redressement

Merci de votre intérêt. Ce guide couvre l'essentiel pour mettre en place un
environnement de développement et faire passer les contrôles qualité.

## Prérequis

- Node ≥ 20
- Python 3.11

## Installation

```bash
# Variables d'environnement (JWT_SECRET REQUIS, >= 32 caractères)
cp .env.example .env        # puis renseigner JWT_SECRET (openssl rand -hex 32)

# Frontend (monorepo Turborepo)
npm install

# Backend (API FastAPI + moteur ML)
pip install -e "apps/api[dev]"
```

## Lancer en développement

```bash
npm run dev          # turbo : web + api en parallèle
npm run dev:web      # Next.js seul (port 3000)
npm run dev:api      # uvicorn app.main:app --reload (port 8000)
```

## Lint & tests

Backend (depuis `apps/api/`) :

```bash
ruff check .
black --check .
python -m pytest -q
```

Frontend :

```bash
npm run lint         # ESLint
```

Avant toute proposition de modification, vérifier que `ruff`, `black --check`,
`pytest` et `eslint` passent.

## Conventions

Les conventions de code et de test du projet sont documentées dans
[`.claude/rules/`](.claude/rules/) :

- [`.claude/rules/code-style.md`](.claude/rules/code-style.md) — style, structure,
  séparation app/ vs xScripts/, chemins `pathlib`, état persistant.
- [`.claude/rules/testing.md`](.claude/rules/testing.md) — framework pytest,
  DataFrames synthétiques, seed fixe (1750), pas de GPU ni de données réelles.

Merci de les lire avant de contribuer.
