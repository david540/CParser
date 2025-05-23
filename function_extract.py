#!/usr/bin/env python3
"""
parse_funcs.py – Extraction rapide des prototypes/défs de fonctions en C.

Usage :
    python parse_funcs.py mon_fichier.c autre.c
"""

from __future__ import annotations
import sys
import re
from pathlib import Path
from collections import OrderedDict
import json

# Expression régulière : retourne type de retour, nom de la fonction, et sa liste d’arguments
# Modifiée pour ne matcher que les définitions (accolade ouvrante '{' uniquement)
FUNC_RE = re.compile(
    r"""
        (?P<ret>                   # type de retour :
            [\w\*\s]+?             #   mots, *, espaces (non-gourmand)
        )
        \s+                        # au moins un espace
        (?P<name>[A-Za-z_]\w*)     # nom de la fonction
        \s*                        # espaces optionnels
        \(                         # parenthèse ouvrante
        (?P<args>[^)]*)            # tout sauf la ) = liste d’arguments brute
        \)                         # parenthèse fermante
        \s*                        # espaces optionnels
        \{                         # seulement une accolade ouvrante (définition)
    """,
    re.VERBOSE | re.MULTILINE,
)

def _parse_args(arg_str: str) -> list[tuple[str, str]]:
    """Coupe la chaîne d’arguments 'int n, const char *s' → [('int', 'n'), ('const char *', 's')]"""
    out = []
    for raw in (a.strip() for a in arg_str.split(',') if a.strip()):
        if raw == 'void':
            continue                    # fonction void(...)
        # On coupe sur le dernier espace : tout avant = type, après = nom
        parts = raw.rsplit(' ', 1)
        if len(parts) == 1:             # paramètre sans nom ? ex. ‘size_t’
            print("Error: unnamed parameter in function signature:", raw, file=sys.stderr)
            #exit(255)
        else:
            if parts[1].startswith('*'):
                parts[1] = parts[1].lstrip('*')
                parts[0] = parts[0].rstrip() + '*'
            out.append((parts[0], parts[1]))
    return out

def extract_funcs(src: str) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Retourne la map de toutes les fonctions trouvées dans une source C donnée."""
    funcs: dict[tuple[str, str], list[tuple[str, str]]] = OrderedDict()
    for m in FUNC_RE.finditer(src):
        ret = " ".join(m.group('ret').split())      # normalise les espaces dans le retour
        name = m.group('name')
        args = _parse_args(m.group('args'))
        funcs[(ret, name)] = args
    return funcs

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python parse_funcs.py fichier1.c [fichier2.c …]", file=sys.stderr)
        sys.exit(1)

    result: dict[tuple[str, str], list[tuple[str, str]]] = OrderedDict()
    for path in sys.argv[1:]:
        text = Path(path).read_text(encoding='utf-8', errors='ignore')
        result.update(extract_funcs(text))

    # Affiche en JSON, facile à consommer ailleurs
    print(json.dumps(
        {f"{ret} {name}": args for (ret, name), args in result.items()},
        indent=2,
        ensure_ascii=False
    ))

if __name__ == "__main__":
    main()
