## Conventions de test — MDL Redressement Tool

- Framework : pytest
- Tester les transformations de données (column_mapper, df_builder) avec des DataFrames synthétiques
- Tester les utilitaires (state_manager, territory, data_loader) unitairement
- Ne jamais tester directement les scripts xScripts/ — ce sont des boîtes noires validées
- Pour les tests d'entraînement : utiliser des DataFrames de 10 lignes max, 2 epochs
- Vérifier les shapes numpy/tensor en entrée et sortie
- Tester les chemins de fichiers avec `tmp_path` pytest fixture
- Les tests ne doivent pas nécessiter de GPU ni de données réelles
- Seed fixe (1750) dans les tests pour reproductibilité
