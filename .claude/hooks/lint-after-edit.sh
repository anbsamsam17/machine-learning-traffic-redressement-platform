#!/bin/bash
# Hook: lint après chaque Edit/Write sur un fichier Python
# Vérifie la propreté du code avec ruff

PROJECT_DIR="$CLAUDE_PROJECT_DIR"

# Lire le stdin (input du hook) pour récupérer le fichier édité
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

# Ne linter que les fichiers Python
if [[ ! "$FILE_PATH" == *.py ]]; then
  exit 0
fi

# Vérifier que ruff est installé
if ! command -v ruff &>/dev/null; then
  RUFF_PATH="$PROJECT_DIR/.venv/Scripts/ruff.exe"
  if [ ! -f "$RUFF_PATH" ]; then
    RUFF_PATH="$PROJECT_DIR/.venv/bin/ruff"
  fi
  if [ ! -f "$RUFF_PATH" ]; then
    # ruff pas disponible, skip silencieusement
    exit 0
  fi
else
  RUFF_PATH="ruff"
fi

# Lancer ruff check (erreurs de code)
LINT_OUTPUT=$("$RUFF_PATH" check "$FILE_PATH" --select=E,F,W --ignore=E501 2>&1)
LINT_EXIT=$?

# Lancer ruff format check (formatting)
FORMAT_OUTPUT=$("$RUFF_PATH" format --check "$FILE_PATH" 2>&1)
FORMAT_EXIT=$?

if [ $LINT_EXIT -ne 0 ] || [ $FORMAT_EXIT -ne 0 ]; then
  ERRORS=""
  if [ $LINT_EXIT -ne 0 ]; then
    ERRORS="LINT ERRORS:\n$LINT_OUTPUT"
  fi
  if [ $FORMAT_EXIT -ne 0 ]; then
    ERRORS="$ERRORS\nFORMATTING ISSUES:\n$FORMAT_OUTPUT"
  fi

  # Remonter les erreurs comme contexte pour Claude (non-bloquant)
  jq -n --arg errors "$ERRORS" '{
    "continue": true,
    "systemMessage": ("Ruff a detecte des problemes dans le fichier modifie. Corrige-les avant de continuer :\n" + $errors)
  }'
  exit 0
fi

exit 0
