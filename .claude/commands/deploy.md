Prépare le déploiement de l'application pour un nouveau poste ou un partage.

Étapes :
1. **Vérifie** que `requirements.txt` est à jour avec les dépendances réelles
2. **Vérifie** que `lancer_app.bat` fonctionne avec la détection Python automatique
3. **Vérifie** qu'il n'y a pas de chemins absolus hardcodés (cherche `C:\Users\`)
4. **Liste** les fichiers/dossiers à exclure du package (`.venv`, `__pycache__`, `xMDL/`, `xData/`)
5. **Génère** un checklist de déploiement

Ne crée pas le package — liste seulement ce qu'il faut faire.
