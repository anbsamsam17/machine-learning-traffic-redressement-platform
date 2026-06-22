#!/bin/bash
# Hook: vérifier que les imports ne sont pas cassés après un edit
# Fait un dry-run de compilation Python sur le fichier modifié

PROJECT_DIR="$CLAUDE_PROJECT_DIR"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

# Ne vérifier que les fichiers Python
if [[ ! "$FILE_PATH" == *.py ]]; then
  exit 0
fi

# Trouver Python
PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
fi
if [ ! -f "$PYTHON" ]; then
  PYTHON="python"
fi

# Vérifier la syntaxe (compile sans exécuter)
SYNTAX_OUTPUT=$("$PYTHON" -c "
import py_compile, sys
try:
    py_compile.compile('$FILE_PATH', doraise=True)
    print('OK')
except py_compile.PyCompileError as e:
    print(f'SYNTAX ERROR: {e}')
    sys.exit(1)
" 2>&1)
SYNTAX_EXIT=$?

if [ $SYNTAX_EXIT -ne 0 ]; then
  jq -n --arg output "$SYNTAX_OUTPUT" '{
    "continue": true,
    "systemMessage": ("ERREUR DE SYNTAXE detectee dans le fichier modifie. Corrige immediatement :\n" + $output)
  }'
  exit 0
fi

exit 0
