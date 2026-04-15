# MDL Redressement Tool v2

> Plateforme SaaS de modelisation de redressement FCD : donnees brutes -> entrainement NN -> evaluation -> rapports.

## Modes

1. **Modele Tous Vehicules (TV)** — Pipeline complet : import, mapping, config, entrainement, evaluation
2. **Modele Poids Lourds (PL)** — Meme pipeline, parametres PL
3. **Carte de Debits** — Applique modeles TV+PL sur donnees FCD, genere GeoJSON
4. **Fichier Compteurs** — Genere le fichier standardise counting-loops

## Stack

- **Frontend** : Next.js 15, shadcn/ui, Tailwind CSS v4, Framer Motion
- **Backend** : FastAPI, TensorFlow/Keras (CPU), pandas, geopandas
- **Infra** : Docker Compose, nginx, GitHub Actions CI/CD

## Quickstart

### Local (dev)

```bash
# Backend
cd apps/api
python -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\activate sur Windows
pip install -e ".[dev,prod]"
uvicorn app.main:app --reload --port 8000

# Frontend
cd apps/web
npm install
npm run dev
```

### Docker

```bash
docker compose -f infra/docker-compose.yml up --build
```

L'app est accessible sur http://localhost (nginx) ou http://localhost:3000 (direct).

## Architecture

```
apps/
  web/     -> Next.js 15 frontend (port 3000)
  api/     -> FastAPI backend (port 8000)
infra/     -> Docker, nginx, CI/CD
```

## Securite

- Aucune donnee stockee cote serveur
- Fichiers traites en memoire, supprimes apres session
- CPU uniquement (CUDA desactive)
