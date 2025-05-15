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
    """
    Calculates the pointer depth of a type and returns the ultimate canonical non-pointer type.
    It correctly handles typedefs at each level of pointer indirection.
    Example: For `typedef int* IntPtr; typedef IntPtr IntPtrAlias; int*** p;`
             - _ptr_depth(type of p) -> (3, int_type)
             - _ptr_depth(type of IntPtrAlias) -> (1, int_type)
    """
    depth = 0
    current_type = t
    
    while True:
        # Resolve typedefs at the current level to get the underlying type structure
        canonical_form = current_type.get_canonical()
        
        if canonical_form.kind == TypeKind.POINTER:
            depth += 1
            current_type = canonical_form.get_pointee() # Move to the type being pointed to
        else:
            # The canonical form is no longer a pointer. This is our base type.
            current_type = canonical_form 
            break
            
    return depth, current_type


def _type_to_str_revised(t: Type, *, struct_decl_hash_to_identifier: Dict[int, str]) -> str:
    """
    Converts a libclang Type object to its string representation.
    Uses `struct_decl_hash_to_identifier` to correctly name structs, including anonymous ones.
    """
    kind = t.kind
    
    if kind == TypeKind.POINTER:
        return _type_to_str_revised(t.get_pointee(), struct_decl_hash_to_identifier=struct_decl_hash_to_identifier) + "*"
    
    if kind == TypeKind.CONSTANTARRAY or kind == TypeKind.INCOMPLETEARRAY or kind == TypeKind.VARIABLEARRAY or kind == TypeKind.DEPENDENTSIZEDARRAY:
        element_type_str = _type_to_str_revised(t.element_type, struct_decl_hash_to_identifier=struct_decl_hash_to_identifier)
        # For simplicity, using "[]". For CONSTANTARRAY, t.array_size could provide size.
        return f"{element_type_str}[]"

    if kind == TypeKind.RECORD: # struct or union
        decl = t.get_declaration()
        # Get the unique identifier (name or "anon_<hash>") for this struct/union
        identifier = struct_decl_hash_to_identifier.get(decl.hash)
        if not identifier: # Fallback, though prescan should cover all cases of known structs
            identifier = decl.spelling or f"unresolved_anon_{decl.hash}"
        
        # Distinguish between struct and union if necessary, though current output doesn't
        # For example, by checking decl.kind (CursorKind.STRUCT_DECL vs CursorKind.UNION_DECL)
        # Here, we just use "struct" as per original logic for simplicity.
        return f"struct {identifier}" # Or "union {identifier}" if decl.kind is UNION_DECL

    if kind == TypeKind.TYPEDEF:
        # When a field's type is a typedef, we use the typedef's name directly in the string.
        # The resolution of this typedef to an underlying struct (if applicable for map keys)
        # is handled by the main extract_structs logic when processing typedef declarations.
        return t.spelling

    if kind == TypeKind.ELABORATED:
        # An elaborated type (e.g., "struct Foo" or "union Bar" in a declaration)
        # should be resolved to its underlying named type for string representation.
        return _type_to_str_revised(t.get_named_type(), struct_decl_hash_to_identifier=struct_decl_hash_to_identifier)
        
    if kind == TypeKind.ENUM:
        decl = t.get_declaration()
        if decl.spelling:
            return f"enum {decl.spelling}"
        return "enum <anonymous>" # Or a more unique ID if needed for anonymous enums

    # For other basic types (INT, CHAR_S, VOID, FLOAT, DOUBLE etc.)
    return t.spelling


###############################################################################
# Public API                                                                   #
###############################################################################

def extract_structs(source: str | Path,
                               clang_args: Optional[Sequence[str]] = None
                               ) -> Tuple[Dict[str, Fields], Dict[str, Fields]]:
    """
    Extracts struct definitions from C source code using a multi-pass AST traversal.

    Args:
        source: Path to the C source file or the source code as a string.
        clang_args: Optional list of clang command-line arguments.

    Returns:
        A tuple containing two dictionaries:
        - name_to_struct: Maps struct names or typedef aliases (to structs) to their fields.
                          Keys for direct structs are "struct <name>".
        - pointer_to_struct: Maps typedef aliases (to pointers to structs) to the pointed-to struct's fields.
    """
    clang_args = list(clang_args or [])

    if isinstance(source, Path):
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

    # --- Data Structures ---
    struct_fields_map: Dict[str, Fields] = {}
    struct_decl_hash_to_identifier: Dict[int, str] = {}
    name_to_struct: Dict[str, Fields] = {}
    pointer_to_struct: Dict[str, Fields] = {}

    # --- Pass 1: Pre-scan for all struct (and union) declaration identifiers ---
    def prescan_struct_identifiers_recursive(cursor: Cursor):
        # We are interested in RECORD types, which include structs and unions.
        # The original code focused on STRUCT_DECL. This explicitly includes UNION_DECL.
        if cursor.kind == CursorKind.STRUCT_DECL or cursor.kind == CursorKind.UNION_DECL:
            decl_hash = cursor.hash
            if cursor.spelling: 
                struct_decl_hash_to_identifier[decl_hash] = cursor.spelling
            else: 
                # Use a prefix to distinguish anonymous structs/unions if needed, e.g., "anon_struct_"
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
                struct_identifier = cursor.spelling or f"error_anon_{decl_hash}"

            current_fields: Fields = []
            for field_cursor in cursor.get_children():
                if field_cursor.kind == CursorKind.FIELD_DECL:
                    field_type_str = _type_to_str_revised(
                        field_cursor.type, 
                        struct_decl_hash_to_identifier=struct_decl_hash_to_identifier
                    )
                    current_fields.append((field_type_str, field_cursor.spelling))
            
            struct_fields_map[struct_identifier] = current_fields
            
            if cursor.spelling:
                # For named structs/unions, add to name_to_struct with "struct <name>" or "union <name>"
                # The original code used "struct <name>" for both.
                # To be more precise, one could use cursor.kind to choose "struct" or "union".
                # For now, sticking to "struct" prefix for compatibility with original intent for `name_to_struct`.
                name_to_struct[f"struct {cursor.spelling}"] = current_fields
        
        for child in cursor.get_children():
            collect_struct_definitions_recursive(child)

    collect_struct_definitions_recursive(tu.cursor)

    # --- Pass 3: Process typedefs and link them to struct/union definitions ---
    def process_typedefs_recursive(cursor: Cursor):
        if cursor.kind == CursorKind.TYPEDEF_DECL:
            alias_name = cursor.spelling 
            type_of_alias = cursor.type 
            
            # ptr_depth will count pointer levels, base_type is the ultimate non-pointer canonical type.
            ptr_depth, ultimate_base_type = _ptr_depth(type_of_alias)
            
            # The ultimate_base_type returned by _ptr_depth is already canonical.
            if ultimate_base_type.kind == TypeKind.RECORD: # Is the target a struct or union?
                # Get the declaration cursor of this struct/union
                struct_decl_cursor = ultimate_base_type.get_declaration()
                
                target_struct_identifier = struct_decl_hash_to_identifier.get(struct_decl_cursor.hash)
                
                if target_struct_identifier and target_struct_identifier in struct_fields_map:
                    fields = struct_fields_map[target_struct_identifier]
                    
                    if ptr_depth == 0: # Typedef directly to a struct/union
                        name_to_struct[alias_name] = fields
                    elif ptr_depth == 1: # Typedef to a pointer to a struct/union
                        pointer_to_struct[alias_name] = fields
                    # Deeper pointer levels (e.g., typedef struct Foo** PtrPtrFoo) are not
                    # explicitly handled by the original problem's output structure for pointer_to_struct,
                    # which seems to expect only single pointers.
        
        for child in cursor.get_children():
            process_typedefs_recursive(child)
            
    process_typedefs_recursive(tu.cursor)

    return name_to_struct, pointer_to_struct

###############################################################################
# CLI helper                                                                   #
###############################################################################

if __name__ == "__main__": # pragma: no cover
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: script.py <source_file_or_string> [clang-args...]\n")
        sys.stderr.write("If providing source as a string, use '-' for the first argument, then the string, e.g., script.py - \"struct A {int x;}; typedef struct A* APtr;\" \n")
        sys.exit(1)

    source_input = sys.argv[1]
    
    processed_source: str | Path
    clang_arguments: Sequence[str]

    if source_input == "-" : # Read from command line string
        if len(sys.argv) < 3:
            sys.stderr.write("Error: Source string expected after '-'.\n")
            sys.stderr.write("Usage: script.py - \"<source_code_string>\" [clang-args...]\n")
            sys.exit(1)
        processed_source = sys.argv[2]
        clang_arguments = sys.argv[3:]
        print(f"Processing source string: \"{processed_source[:70]}{'...' if len(processed_source) > 70 else ''}\"")
    elif Path(source_input).is_file(): # Read from file
        processed_source = Path(source_input)
        clang_arguments = sys.argv[2:]
        print(f"Processing source file: {processed_source}")
    else: # Treat as string if not a file and not '-', this allows passing simple strings directly
        processed_source = source_input
        clang_arguments = sys.argv[2:] # All subsequent args are clang args
        print(f"Processing source string: \"{processed_source[:70]}{'...' if len(processed_source) > 70 else ''}\"")


    try:
        nm, pm = extract_structs(processed_source, clang_arguments)
        output = {"name_to_struct": nm, "pointer_to_struct": pm}
        print(json.dumps(output, indent=2))
    except FileNotFoundError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    except ImportError as e:
        sys.stderr.write(f"Import Error: {e}. Make sure libclang is installed and configured.\n")
        sys.exit(1)
    except RuntimeError as e:
        sys.stderr.write(f"Runtime Error: {e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"An unexpected error occurred: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
