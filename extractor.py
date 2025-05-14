"""
Extractor module that passes the full test‑suite described in the canvas.
Rules implemented
─────────────────
* Each fully defined **named** struct is stored under the canonical key
  `"struct <Tag>"` inside **name_to_struct**.
* `pointer_to_struct` contains **only one‑level pointer typedefs** (e.g. `Foo*`).
  Aliases such as `Foo**` or deeper are ignored.
* Aliases defined *before* the struct body (forward declarations) are handled.
* Anonymous structs are referenced through their typedef alias(es).
* Pointer aliases that point to another typedef (e.g. `typedef AnonS* pAnonS;`)
  are resolved to the underlying anonymous struct.
Implementation uses **pycparser** (pure‑Python, no libclang dependency).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from pycparser import c_ast, parse_file

# Public types
Fields = List[Tuple[str, str]]  # [(type_string, field_name)]

###############################################################################
# Helper functions
###############################################################################

def _type_to_str(node: c_ast.Node) -> str:
    """Return a textual representation of a pycparser type node."""
    if isinstance(node, c_ast.TypeDecl):
        return _type_to_str(node.type)

    if isinstance(node, c_ast.IdentifierType):
        return " ".join(node.names)

    if isinstance(node, c_ast.PtrDecl):
        return _type_to_str(node.type) + "*"

    if isinstance(node, c_ast.ArrayDecl):
        return _type_to_str(node.type) + "[]"

    if isinstance(node, c_ast.Struct):
        return f"struct {node.name or '<anon>'}"

    # Fallback – should not really happen in our tests.
    return str(node)


def _ptr_depth(node: c_ast.Node) -> Tuple[int, c_ast.Node]:
    """Return (depth, underlying_node) for nested PtrDecl wrappers."""
    depth = 0
    while isinstance(node, c_ast.PtrDecl):
        depth += 1
        node = node.type
    return depth, node

###############################################################################
# First pass – collect every struct definition / forward declaration
###############################################################################

def _collect_structs(node: c_ast.Node,
                     struct_defs: Dict[str, Fields | None],
                     anon_map: Dict[int, str]) -> None:
    """Fill struct_defs with tag → fields (or None) and map id(node) for anonymous."""
    if isinstance(node, c_ast.Struct):
        tag = node.name or f"anon_{id(node)}"
        anon_map[id(node)] = tag
        if node.decls:  # full definition
            struct_defs[tag] = [(_type_to_str(d.type), d.name) for d in node.decls]
        else:  # forward‑decl
            struct_defs.setdefault(tag, None)

    for _key, child in node.children():
        _collect_structs(child, struct_defs, anon_map)

###############################################################################
# Second pass – collect all typedef aliases (with their pointer depth & node)
###############################################################################

def _collect_typedefs(node: c_ast.Node,
                      alias_nodes: Dict[str, Tuple[int, c_ast.Node]],
                      anon_map: Dict[int, str]) -> None:
    """Map alias → (pointer_depth, underlying_type_node)."""
    if isinstance(node, c_ast.Typedef):
        alias = node.name
        depth, base = _ptr_depth(node.type)
        alias_nodes[alias] = (depth, base)

    for _k, child in node.children():
        _collect_typedefs(child, alias_nodes, anon_map)

###############################################################################
# Resolution helpers
###############################################################################

def _resolve_to_fields(base: c_ast.Node,
                       struct_defs: Dict[str, Fields | None],
                       anon_map: Dict[int, str],
                       name_to_struct: Dict[str, Fields]) -> Fields | None:
    """Try to resolve *base* node to a list of fields, else None."""
    # Case 1 : struct literal
    if isinstance(base, c_ast.Struct):
        tag = anon_map[id(base)]
        return struct_defs.get(tag)

    # Case 2 : TypeDecl …
    if isinstance(base, c_ast.TypeDecl):
        inner = base.type
        # 2a – direct struct identifier « struct Foo »
        if isinstance(inner, c_ast.IdentifierType) and "struct" in inner.names:
            tag = inner.names[inner.names.index("struct") + 1]
            return struct_defs.get(tag)
        # 2b – alias name (e.g. inner.names == ["AnonS"])
        if isinstance(inner, c_ast.IdentifierType):
            alias_name = inner.names[-1]
            return name_to_struct.get(alias_name)
        # 2c – embedded struct again
        if isinstance(inner, c_ast.Struct):
            tag = anon_map[id(inner)]
            return struct_defs.get(tag)

    # Unhandled type (enum, builtin, etc.)
    return None

###############################################################################
# Main extraction function
###############################################################################

def extract_structs(c_path: str | Path) -> Tuple[Dict[str, Fields], Dict[str, Fields]]:
    """Return (name_to_struct, pointer_to_struct) for all structs in a C file."""
    ast = parse_file(
        str(c_path),
        use_cpp=True,
        cpp_args=["-I", "utils/fake_libc_include"],
    )

    # Pass 1 : structs
    struct_defs: Dict[str, Fields | None] = {}
    anon_map: Dict[int, str] = {}
    _collect_structs(ast, struct_defs, anon_map)

    # Pass 2 : typedef alias → (ptr_depth, base_node)
    alias_nodes: Dict[str, Tuple[int, c_ast.Node]] = {}
    _collect_typedefs(ast, alias_nodes, anon_map)

    # Output dicts
    name_to_struct: Dict[str, Fields] = {}
    pointer_to_struct: Dict[str, Fields] = {}

    # Canonical names for *named* structs with full definitions
    for tag, fields in struct_defs.items():
        if fields and not tag.startswith("anon_"):
            name_to_struct[f"struct {tag}"] = fields

    # Iteratively resolve aliases until no progress
    unresolved = dict(alias_nodes)
    progress = True
    while progress and unresolved:
        progress = False
        still = {}
        for alias, (depth, base) in unresolved.items():
            fields = _resolve_to_fields(base, struct_defs, anon_map, name_to_struct)
            if fields is None:
                still[alias] = (depth, base)  # try later
                continue

            if depth == 0:  # non‑pointer alias
                name_to_struct[alias] = fields
                progress = True
            elif depth == 1:  # single pointer alias only
                pointer_to_struct[alias] = fields
                progress = True
            # depth ≥ 2 ignored by spec
        unresolved = still

    return name_to_struct, pointer_to_struct

###############################################################################
# CLI helper (optional)
###############################################################################
if __name__ == "__main__":
    import json, sys

    nm, pm = extract_structs(sys.argv[1])
    print(json.dumps({"name_to_struct": nm, "pointer_to_struct": pm}, indent=2))