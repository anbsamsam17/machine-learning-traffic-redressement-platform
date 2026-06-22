#!/bin/bash
# Hook PreToolUse: BLOQUER les modifications sur les fichiers critiques
# Protège xScripts/ (logique métier), xData/, xMDL/ (données/modèles)

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normaliser le path (remplacer \ par /)
FILE_PATH=$(echo "$FILE_PATH" | tr '\\' '/')

# === BLOQUER : modification de données ou modèles ===
if echo "$FILE_PATH" | grep -qE '/(xData|xDataLearning|xMDL|xMDL_PL|xMDL_final|xMDL_Results|xMDL_PL_Results)/'; then
  if echo "$FILE_PATH" | grep -qE '\.(h5|mat|geojson|csv|shp|dbf|shx|prj)$'; then
    echo "BLOQUE: Modification interdite sur les fichiers de donnees/modeles: $FILE_PATH" >&2
    exit 2
  fi
fi

# === AVERTIR : modification de xScripts/ (logique métier) ===
if echo "$FILE_PATH" | grep -qE '/xScripts/'; then
  jq -n --arg path "$FILE_PATH" '{
    "continue": true,
    "systemMessage": ("ATTENTION: Tu modifies un script metier critique (" + $path + "). La logique metier dans xScripts/ ne doit etre modifiee que sur demande explicite de l'\''utilisateur. Verifie que c'\''est bien le cas.")
  }'
  exit 0
fi

exit 0
