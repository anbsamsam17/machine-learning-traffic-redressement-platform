Effectue un audit de sécurité du projet MDL Redressement Tool.

Vérifie :
1. **Chemins fichiers** — pas d'injection de path via les entrées utilisateur Streamlit (territoire, noms de fichiers)
2. **Pickle/H5** — les fichiers modèles `.h5` sont chargés de manière sécurisée
3. **Variables d'environnement** — `.env` n'est pas versionné, pas de secrets en dur
4. **Dépendances** — versions dans `requirements.txt` sans vulnérabilités connues
5. **Données** — pas de fuite de données sensibles dans les rapports HTML générés
6. **Exécution de code** — pas d'`eval()`, `exec()` ou `pickle.loads()` non sécurisé

Produis un rapport avec sévérité (critique / élevé / moyen / faible) pour chaque finding.
