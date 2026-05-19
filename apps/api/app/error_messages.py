"""User-friendly error messages (FR) for API responses.

This module maps low-level Python / pandas / numpy / TF exceptions to clean
French messages safe to surface in the frontend UI. Raw stack traces and
implementation details stay in the server logs (`logger.exception(...)`),
while users only see actionable, localized text.

Usage:
    from ..error_messages import user_message

    try:
        ...
    except Exception as exc:
        logger.exception("Operation failed")
        raise HTTPException(status_code=400, detail=user_message(exc))
"""

from __future__ import annotations

import json
import zipfile


def user_message(exc: Exception) -> str:
    """Translate a raw exception into a localized, user-friendly message (FR).

    The mapping is intentionally conservative: the more specific the exception
    type, the more contextual the message. For everything we don't recognize,
    we return a generic "internal error" string and rely on `logger.exception`
    to capture the stack trace server-side.
    """
    # --- Filesystem ---
    if isinstance(exc, FileNotFoundError):
        path = getattr(exc, "filename", None)
        if path:
            return f"Fichier introuvable : {path}"
        return "Fichier introuvable."

    if isinstance(exc, PermissionError):
        return "Acces refuse au fichier ou au dossier (verifiez les permissions)."

    if isinstance(exc, IsADirectoryError):
        return "Un fichier etait attendu, mais un dossier a ete fourni."

    if isinstance(exc, NotADirectoryError):
        return "Un dossier etait attendu, mais un fichier a ete fourni."

    if isinstance(exc, OSError):
        # Catches generic IO errors (disk full, broken pipe, etc.)
        return "Erreur d'acces fichier. Verifiez que le fichier existe et est lisible."

    # --- Archive / parsing ---
    if isinstance(exc, zipfile.BadZipFile):
        return "Archive ZIP invalide ou corrompue."

    if isinstance(exc, json.JSONDecodeError):
        return "Fichier JSON / GeoJSON invalide : le contenu n'est pas un JSON correct."

    if isinstance(exc, UnicodeDecodeError):
        return (
            "Impossible de decoder le fichier (encodage non reconnu). "
            "Essayez d'enregistrer le fichier en UTF-8."
        )

    # --- Data / DataFrame ---
    if isinstance(exc, KeyError):
        # KeyError args are usually a single column name
        key = exc.args[0] if exc.args else "?"
        return f"Colonne manquante dans les donnees : {key!r}"

    if isinstance(exc, IndexError):
        return "Index hors limite dans les donnees (DataFrame ou tableau trop court)."

    if isinstance(exc, AttributeError):
        # Typically pandas/numpy "object has no attribute X" — usually a coding bug
        return "Erreur de structure de donnees. Verifiez le format du fichier importe."

    if isinstance(exc, TypeError):
        msg = str(exc)
        # Pandas often raises "Expected DataFrame, got list" / "got NoneType"
        if "DataFrame" in msg or "Series" in msg:
            return "Format de donnees inattendu (DataFrame attendu)."
        return "Type de donnees invalide pour cette operation."

    if isinstance(exc, ValueError):
        msg = str(exc)
        if not msg:
            return "Valeur invalide dans les donnees."
        if "convert" in msg.lower() or "could not convert" in msg.lower():
            return f"Conversion de valeur impossible : {msg}"
        if "shape" in msg.lower():
            return f"Forme des donnees incompatible : {msg}"
        if "empty" in msg.lower():
            return "Les donnees fournies sont vides."
        # Default: surface the (usually already-French) ValueError message verbatim
        return msg

    if isinstance(exc, ZeroDivisionError):
        return "Division par zero dans le calcul (verifiez les denominateurs dans les donnees)."

    if isinstance(exc, ArithmeticError):
        return "Erreur de calcul numerique (overflow / underflow)."

    # --- Memory ---
    if isinstance(exc, MemoryError):
        return "Memoire insuffisante pour traiter ce volume de donnees."

    # --- Catch-all ---
    return "Erreur interne inattendue. Consultez les logs serveur pour le detail."
