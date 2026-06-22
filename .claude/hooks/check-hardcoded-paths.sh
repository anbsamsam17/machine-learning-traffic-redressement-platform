#!/bin/bash
# Hook: détecter les chemins hardcodés après un edit
# Empêche les C:\Users\... en dur qui cassent la portabilité

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

# Ne vérifier que les fichiers Python
if [[ ! "$FILE_PATH" == *.py ]]; then
  exit 0
fi

# Chercher des chemins Windows hardcodés
HARDCODED=$(grep -nE '(C:\\\\Users\\\\|C:/Users/|r"C:\\\\|r'\''C:\\\\)' "$FILE_PATH" 2>/dev/null | head -5)

if [ -n "$HARDCODED" ]; then
  jq -n --arg paths "$HARDCODED" '{
    "continue": true,
    "systemMessage": ("CHEMINS HARDCODES detectes. Utilise pathlib.Path et get_workspace_root() a la place :\n" + $paths)
  }'
  exit 0
fi

exit 0
