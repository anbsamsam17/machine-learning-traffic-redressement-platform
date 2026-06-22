## Conventions de code — MDL Redressement Tool

- Python 3.11+, encodage UTF-8
- Noms de pages Streamlit : `N_NomPage.py` (TV) ou `Nb_NomPage.py` (variante PL)
- Utils dans `app/utils/`, jamais de logique métier ML dans `app/`
- Logique métier ML exclusivement dans `xScripts/`
- Imports TensorFlow/Keras toujours précédés de la désactivation GPU :
  ```python
  os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
  os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
  ```
- Chemins : toujours `pathlib.Path`, jamais de strings hardcodés
- Workspace root : `utils.territory.get_workspace_root()`, pas de `os.getcwd()`
- State persistant : via `utils.state_manager` (load_state / update_state), pas de fichiers ad hoc
- Pas de `st.experimental_*` — utiliser les API stables Streamlit
- Colonnes DataFrame : respecter les 35 noms standard définis dans `project-context.md`
