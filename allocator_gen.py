"""
Code-generator : construit des fonctions alloc_* pour chaque struct / alias.

Utilisation :
    python allocator_gen.py path/to/file.c [path/other.c ...] > alloc.c
Vous pouvez ensuite compiler `alloc.c` avec le(s) header(s) d’origine.

Dépendances : pycparser (déjà requis par extractor.py)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from textwrap import indent
from typing import Dict, List, Tuple

from extractor import extract_structs

Fields = List[Tuple[str, str]]


###############################################################################
# utilitaires -----------------------------------------------------------------
###############################################################################
_star_re = re.compile(r'\*+$')             # cache le pattern

def clean_key(key: str) -> str:
    """ 'struct Foo**'   -> 'Foo'
        ' Bar * '        -> 'Bar'
        'pBaz'           -> 'pBaz'  """
    #key = re.sub(r'^union\s+', '', key)   # retire le préfixe «struct »
    #key = re.sub(r'^struct\s+', '', key)   # retire le préfixe «struct »
    key = key.strip().replace(' ', '_')     # espaces internes & bords
    key = _star_re.sub('', key)            # toute traîne d’*
    return key

def is_pointer_alias(key: str, pointer_map: Dict[str, Fields]) -> bool:
    return key in pointer_map


def ptr_depth(type_str: str) -> int:
    """Nombre d’étoiles dans le type (« int ** » → 2)."""
    return type_str.count("*")


def is_struct_type(type_str: str, struct_names: set[str]) -> bool:
    base = re.sub(r"\s*\*+$", "", type_str).strip()
    return base in struct_names


###############################################################################
# génération ------------------------------------------------------------------
###############################################################################
PRELUDE = """\
#include <stdlib.h>
void* auto_alloc_safe(size_t size){
    void* out = malloc(size);
    if (out == NULL) { exit(1); }
    return out;
}
void auto_make_unknown(void* data, size_t size){
    for (size_t i = 0; i < size; i++) {
        ((char*)data)[i] = (char)(rand() % 256);
    }
}
"""

ALLOC_TPL = """\
{ret_type} alloc_{fname}(int d, int max_d)
{{
    {struct_type} out = ({struct_type})auto_alloc_safe(sizeof(*out));
    auto_make_unknown(out, sizeof(*out));
{body}
    return out;
}}
"""

def make_body(fields: Fields,
              struct_names: set[str]) -> str:
    lines: List[str] = []
    lines.append("if(d < max_d - 1) {")
    for f_type, f_name in fields:
        depth = ptr_depth(f_type)
        base  = re.sub(r"\\s*\\*+$", "", f_type).strip()

        # ---- pointeur simple vers struct connue → récursif ------------------
        if depth == 1 and is_struct_type(base, struct_names):
            callee = clean_key(base)
            lines.append(
                f"    out->{f_name} = alloc_{callee}(d + 1, max_d);"
            )
        # ---- valeur d’une struct connue -------------------------------------
        elif depth == 0 and is_struct_type(base, struct_names):
            callee = clean_key(base)
            lines.append(
                f"    out->{f_name} = *alloc_{callee}(d + 1, max_d);"
            )
        # ---- sinon : mémoire inconnue ---------------------------------------
        elif depth == 1 and not "[" in f_type and not "[" in f_name:
            lines.append(
                f"    out->{f_name} = auto_alloc_safe(128);"
            )
            lines.append(
                f"    auto_make_unknown(out->{f_name}, 128);"
            )
        else:
            # champ scalaire : rien à faire, on l’a déjà « unknown-é »
            pass
    lines.append("    }")
    return "\n".join(lines)


def generate_allocators(name_map: Dict[str, Fields],
                        ptr_map: Dict[str, Fields]) -> str:
    struct_names = set(name_map)  # toutes les alias « valeur »
    parts: List[str] = [PRELUDE]

    for iter in [0,1]:
        # 1) d’abord les alias valeur (inclut « struct Foo »)
        for key, fields in name_map.items():
            fname       = clean_key(key)
            struct_type = f"{key}*" 
            ret_type    = struct_type
            body        = make_body(fields, struct_names)
            if iter == 0: 
                parts.append(f"{ret_type} alloc_{fname}(int d, int max_d);\n")
            else:
                parts.append(
                    ALLOC_TPL.format(
                        ret_type=ret_type,
                        fname=fname,
                        struct_type=struct_type,
                        body=indent(body, "    "),
                    )
                )

        # 2) puis les alias pointeurs simples  -----------------------------------
        for key, fields in ptr_map.items():
            fname    = clean_key(key)
            # retrouve le vrai nom de struct pour appeler le bon alloc_…
            # (on suppose qu’au moins un alias valeur possède exactement le même
            #   tableau de champs).
            target_alias = next(
                k for k, v in name_map.items() if v == fields
            )
            callee = clean_key(target_alias)
            if iter == 0: 
                parts.append(f"{key} alloc_{fname}(int d, int max_d);\n")
            else:
                parts.append(
                    f"{key} alloc_{fname}(int d, int max_d)\n{{\n"
                    f"    return alloc_{callee}(d, max_d);\n"
                    f"}}\n"
                )

    return "\n".join(parts)



