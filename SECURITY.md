# Politique de securite

## Signaler une vulnerabilite

Merci de signaler toute vulnerabilite de maniere responsable, **en prive**,
a l'adresse suivante :

- **samir.anbri@gmail.com**

Merci de ne pas ouvrir d'issue publique tant que la faille n'a pas ete
corrigee. Une reponse est apportee dans les meilleurs delais ; indiquez
si possible une description, les etapes de reproduction et l'impact estime.

## Versions supportees

Seule la derniere version publiee de l'application (`main`) recoit des
correctifs de securite.

## Mesures de securite en place

Les protections ci-dessous sont implementees et verifiees dans le code de
l'API (`apps/api/app/`).

- **Secret JWT en fail-fast** — au demarrage, un validateur Pydantic refuse
  un `JWT_SECRET` vide, place par defaut (`change-me*`) ou de moins de
  32 caracteres. L'application ne demarre pas avec un secret faible.
  _`app/config.py`_

- **Protection anti-IDOR (404)** — les sessions sont couplees a leur
  proprietaire via `get_owned_session` : un appelant qui n'est pas le
  proprietaire recoit un `404`, fermant les acces directs par identifiant
  (IDOR). _`app/auth.py`_

- **Protection contre le path-traversal** — les chemins fournis par
  l'utilisateur sont confines a la racine de session : resolution des
  symlinks puis verification que le chemin reste sous la racine autorisee,
  avec rejet des segments dangereux (`..`, slashs, NUL).
  _`app/security.py`_

- **Protection anti zip-bomb** — les archives `.zip` (shapefiles, modeles)
  sont controlees avant extraction : la taille decompressee totale est
  refusee au-dela de 1 Go. _`app/routers/upload.py`_

- **En-tetes de securite OWASP** — chaque reponse recoit
  `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Content-Security-Policy` et
  `Permissions-Policy`. _`app/middleware/security_headers.py`_

- **Limitation de debit (rate-limiting)** — un limiteur partage (slowapi)
  applique des quotas par utilisateur (ou par IP en repli) sur les routes
  sensibles. _`app/rate_limit.py`_

## Gestion des dependances

Les dependances (pip, npm, GitHub Actions) sont surveillees automatiquement
chaque semaine via Dependabot (`.github/dependabot.yml`).
