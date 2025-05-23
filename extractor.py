from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

###############################################################################
# libclang loading                                                             #
###############################################################################

try:
    from clang import cindex
    from clang.cindex import (
        Cursor,
        CursorKind,
        Index,
        TranslationUnit,
        Type,
        TypeKind,
    )
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "libclang is required. Install the `clang` wheel or set CLANG_LIBRARY_FILE"
    ) from exc

if "CLANG_LIBRARY_FILE" in os.environ: # pragma: no cover
    cindex.Config.set_library_file(os.environ["CLANG_LIBRARY_FILE"])

###############################################################################
# Types                                                                        #
###############################################################################

Fields = List[Tuple[str, str]]  # [(type_string, field_name)]
__all__ = ["extract_structs", "Fields"]

###############################################################################
# Helpers                                                                      #
###############################################################################

def _ptr_depth(t: Type) -> Tuple[int, Type]:
    depth = 0
    current_type = t
    
    while True:
        canonical_form = current_type.get_canonical()
        
        if canonical_form.kind == TypeKind.POINTER:
            depth += 1
            current_type = canonical_form.get_pointee() 
        else:
            current_type = canonical_form 
            break
            
    return depth, current_type


def _type_to_str_revised(t: Type, *, struct_decl_hash_to_identifier: Dict[int, str]) -> str:
    kind = t.kind
    
    if kind == TypeKind.POINTER:
        return _type_to_str_revised(t.get_pointee(), struct_decl_hash_to_identifier=struct_decl_hash_to_identifier) + "*"
    
    if kind == TypeKind.CONSTANTARRAY or kind == TypeKind.INCOMPLETEARRAY or kind == TypeKind.VARIABLEARRAY or kind == TypeKind.DEPENDENTSIZEDARRAY:
        element_type_str = _type_to_str_revised(t.element_type, struct_decl_hash_to_identifier=struct_decl_hash_to_identifier)
        return f"{element_type_str}[]"

    if kind == TypeKind.RECORD: 
        decl = t.get_declaration()
        identifier = struct_decl_hash_to_identifier.get(decl.hash)
        if not identifier: 
            identifier = decl.spelling or f"unresolved_anon_{decl.hash}"
        
        # Determine prefix based on actual kind (struct or union)
        prefix = "struct"
        if decl.kind == CursorKind.UNION_DECL: # pragma: no cover
             prefix = "union"
        return f"{prefix} {identifier}"

    if kind == TypeKind.TYPEDEF:
        return t.spelling

    if kind == TypeKind.ELABORATED:
        return _type_to_str_revised(t.get_named_type(), struct_decl_hash_to_identifier=struct_decl_hash_to_identifier)
        
    if kind == TypeKind.ENUM:
        decl = t.get_declaration()
        if decl.spelling:
            return f"enum {decl.spelling}"
        return "enum <anonymous>" 

    return t.spelling


###############################################################################
# Public API                                                                   #
###############################################################################

def extract_structs(source: str | Path,
                               clang_args: Optional[Sequence[str]] = None
                               ) -> Tuple[Dict[str, Fields], Dict[str, Fields]]:
    clang_args = list(clang_args or [])

    if isinstance(source, Path):
        print(f"Parsing source file: {source}", file=sys.stderr)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        tu = Index.create().parse(
            str(source),
            args=clang_args,
            options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
    else: 
        tu = Index.create().parse(
            "virtual_file.c", 
            args=clang_args,
            unsaved_files=[("virtual_file.c", source)],
            options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
    
    if not tu: # pragma: no cover
        raise RuntimeError("libclang failed to parse the translation unit.")
    for diagnostic in tu.diagnostics:
        if diagnostic.severity >= cindex.Diagnostic.Error:
            print(f"ERROR: {diagnostic.location}: {diagnostic.spelling}", file=sys.stderr)
        elif diagnostic.severity >= cindex.Diagnostic.Warning:
            print(f"WARNING: {diagnostic.location}: {diagnostic.spelling}", file=sys.stderr)

    struct_fields_map: Dict[str, Fields] = {}
    struct_decl_hash_to_identifier: Dict[int, str] = {}
    name_to_struct: Dict[str, Fields] = {}
    pointer_to_struct: Dict[str, Fields] = {}

    # --- Pass 1: Pre-scan for all struct (and union) declaration identifiers ---
    # (Using the original Pass 1 logic from the problem description)
    def prescan_struct_identifiers_recursive(cursor: Cursor):
        if cursor.kind == CursorKind.STRUCT_DECL or cursor.kind == CursorKind.UNION_DECL:
            decl_hash = cursor.hash
            if cursor.spelling: 
                struct_decl_hash_to_identifier[decl_hash] = cursor.spelling
            else: 
                anon_name = f"anon_{decl_hash}" 
                struct_decl_hash_to_identifier[decl_hash] = anon_name
        
        for child in cursor.get_children():
            prescan_struct_identifiers_recursive(child)
    
    prescan_struct_identifiers_recursive(tu.cursor)

    # --- Pass 2: Collect struct (and union) definitions and their fields ---
    def collect_struct_definitions_recursive(cursor: Cursor):
        if (cursor.kind == CursorKind.STRUCT_DECL or cursor.kind == CursorKind.UNION_DECL) and cursor.is_definition():
            decl_hash = cursor.hash
            struct_identifier = struct_decl_hash_to_identifier.get(decl_hash)
            
            if not struct_identifier: 
                struct_identifier = cursor.spelling or f"error_anon_{decl_hash}" # pragma: no cover

            current_fields: Fields = []
            for field_cursor in cursor.get_children():
                if field_cursor.kind == CursorKind.FIELD_DECL:
                    field_type_str = _type_to_str_revised(
                        field_cursor.type, 
                        struct_decl_hash_to_identifier=struct_decl_hash_to_identifier
                    )
                    current_fields.append((field_type_str, field_cursor.spelling))
            
            struct_fields_map[struct_identifier] = current_fields
            
            # --- MODIFIED LOGIC TO ADD TO name_to_struct FOR TAGGED STRUCTS/UNIONS ---
            if cursor.spelling: 
                
                is_actually_tagged_in_c = False
                current_kind_str = ""

                if cursor.kind == CursorKind.STRUCT_DECL:
                    current_kind_str = "struct"
                elif cursor.kind == CursorKind.UNION_DECL: # pragma: no cover
                    current_kind_str = "union"
                
                if current_kind_str: 
                    if not cursor.is_anonymous():
                        expected_type_spelling = f"{current_kind_str} {cursor.spelling}"
                        if cursor.type.spelling == expected_type_spelling:
                            is_actually_tagged_in_c = True
                
                if is_actually_tagged_in_c:
                    # The key format uses "struct" as per original code's examples and test failure context
                    # For more strictness, current_kind_str should be used here too.
                    # Sticking to "struct" to directly address the failing test key "struct Rec".
                    # If unions were failing, this prefix would need current_kind_str.
                    name_to_struct[f"{current_kind_str} {cursor.spelling}"] = current_fields
            # --- END OF MODIFIED LOGIC ---
        
        for child in cursor.get_children():
            collect_struct_definitions_recursive(child)

    collect_struct_definitions_recursive(tu.cursor)

    # --- Pass 3: Process typedefs and link them to struct/union definitions ---
    # (Using the original Pass 3 logic from the problem description)
    def process_typedefs_recursive(cursor: Cursor):
        if cursor.kind == CursorKind.TYPEDEF_DECL:
            alias_name = cursor.spelling 
            type_of_alias = cursor.type 
            
            ptr_depth, ultimate_base_type = _ptr_depth(type_of_alias)
            
            if ultimate_base_type.kind == TypeKind.RECORD: 
                struct_decl_cursor = ultimate_base_type.get_declaration()
                target_struct_identifier = struct_decl_hash_to_identifier.get(struct_decl_cursor.hash)
                
                if target_struct_identifier and target_struct_identifier in struct_fields_map:
                    fields = struct_fields_map[target_struct_identifier]
                    
                    if ptr_depth == 0: 
                        name_to_struct[alias_name] = fields
                    elif ptr_depth == 1: 
                        pointer_to_struct[alias_name] = fields
        
        for child in cursor.get_children():
            process_typedefs_recursive(child)
            
    process_typedefs_recursive(tu.cursor)

    return name_to_struct, pointer_to_struct