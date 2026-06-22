Corrige le bug ou problème suivant : $ARGUMENTS

Étapes à suivre :
1. **Lis** les fichiers concernés et `memory/project-context.md` pour le contexte
2. **Identifie** la cause racine (pas juste le symptôme)
3. **Corrige** en respectant les conventions du projet (voir `CLAUDE.md`)
4. **Vérifie** que la correction ne casse pas les pages adjacentes du pipeline
5. **Teste** avec `streamlit run app/main.py` si c'est un bug UI

Attention particulière :
- Ne modifie pas la logique métier dans `xScripts/` sans demander
- Vérifie les `session_state` keys — les pages partagent l'état via `state_manager.py`
- Si le bug touche l'entraînement, vérifie les shapes et les types numpy/tensor
