#!/bin/bash
# Hook: tests de non-régression après modification de code Python dans app/ ou xScripts/
# Ne lance les tests que si des fichiers critiques ont été modifiés

PROJECT_DIR="$CLAUDE_PROJECT_DIR"

# Lire le stdin pour récupérer le fichier édité
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

# Ne tester que si c'est un fichier Python dans app/ ou xScripts/
if [[ ! "$FILE_PATH" == *.py ]]; then
  exit 0
fi

case "$FILE_PATH" in
  *app/utils/*|*app/pages/*|*app/main.py|*xScripts/*)
    ;; # continuer
  *)
    exit 0 ;; # pas un fichier critique, skip
esac

# Trouver Python
PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
fi
if [ ! -f "$PYTHON" ]; then
  PYTHON="python"
fi

# Vérifier que pytest est disponible
if ! "$PYTHON" -m pytest --version &>/dev/null 2>&1; then
  exit 0
fi

# Lancer les tests rapides (timeout 60s, pas de tests lents)
cd "$PROJECT_DIR"
TEST_OUTPUT=$("$PYTHON" -m pytest tests/ -x -q --timeout=30 --tb=short -m "not slow" 2>&1)
TEST_EXIT=$?

if [ $TEST_EXIT -ne 0 ]; then
  jq -n --arg output "$TEST_OUTPUT" '{
    "continue": true,
    "systemMessage": ("TESTS EN ECHEC apres modification. Non-regression echouee. Corrige avant de continuer :\n" + $output)
  }'
  exit 0
fi

# Tests passés
jq -n '{
  "continue": true,
  "systemMessage": "Tests de non-regression OK."
}'
exit 0
