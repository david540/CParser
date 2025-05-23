#!/usr/bin/env python3
"""
Generate allocator boiler-plate for a set of C units.

Usage:
    gen_allocators.py <compile_commands.json> <file1.c> [file2.c …]

The script:
  • builds a temporary translation unit that #includes all given C files;
  • extracts pre-processing flags from compile_commands.json;
  • calls `extractor.extract_structs` and `allocator_gen.generate_allocators`;
  • prints the resulting C code.
"""

from __future__ import annotations

import json
import shlex
import sys
import tempfile
from pathlib import Path
from typing import List, Sequence
from collections import OrderedDict
# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

_PP_PREFIXES = (
    "-I", "-isystem", "-iquote", "-idirafter",
    "-D", "-U", "-include", "-imacros",
    "-iprefix", "-iwithprefix", "-iwithprefixbefore",
    "-nostdinc", "-f", "-m", "-std=", "-x", "-Xclang",
)

_PP_PREFIXES_REQUIRING_SEP_ARG = {
    "-I", "-isystem", "-iquote", "-idirafter",
    "-D", "-U", "-include", "-imacros",
    "-iprefix", "-iwithprefix", "-iwithprefixbefore",
    "-x", "-Xclang",
}

def _extract_pp_options(tokens: Sequence[str], base_directory: Path) -> List[str]:
    """
    Filter a compile-command token list, keeping only options that influence
    the pre-processor / language front-end (include paths, macros, language
    standard, etc.). Specifically resolves relative paths for -I options.

    Parameters
    ----------
    tokens
        The tokenised compile command (not including the compiler executable).
    base_directory
        The directory from which relative paths in the compile command
        should be resolved (i.e., the 'directory' field of the command entry).

    Returns
    -------
    List[str]
        Tokens relevant to Clang's front-end, with relative -I paths resolved.
    """
    pp: List[str] = []
    it = iter(tokens) # Create an iterator for easy `next()`

    for tok in it:
        # Case 1: Option is exactly "-I" (takes a separate path argument)
        if tok == "-I":
            pp.append(tok)  # Append "-I"
            try:
                path_arg = next(it)
                path_obj = Path(path_arg)
                # Resolve if relative and not a variable-like path (e.g. starting with '$')
                if not path_obj.is_absolute() and not path_arg.startswith("$"):
                    resolved_path = (base_directory / path_obj).resolve()
                    pp.append(resolved_path.as_posix())
                else:
                    pp.append(path_arg)  # Keep absolute path or variable path as is
            except StopIteration:
                sys.stderr.write(f"Warning: Expected path argument for '-I' but found none.\n")
                break  # Stop processing this command's tokens
            continue # Processed this token and its argument, move to next token

        # Case 2: Option starts with "-I" and path is concatenated (e.g., -I../include or -I/abs/path)
        # Ensure it's not just "-I" itself (len > 2)
        elif tok.startswith("-I") and len(tok) > 2:
            prefix = "-I"
            path_part = tok[len(prefix):]
            path_obj = Path(path_part)
            if not path_obj.is_absolute() and not path_part.startswith("$"):
                resolved_path = (base_directory / path_obj).resolve()
                pp.append(f"{prefix}{resolved_path.as_posix()}")
            else:
                pp.append(tok)  # Keep original form (e.g. -I/abs/path or -I$SYSROOT/path)
            continue # Processed this token, move to next token

        # Case 3: Other pre-processor options (macros, other includes, standards, etc.)
        # Check if the token starts with any of the known general pre-processor prefixes.
        # This handles options like -isystem, -D, -DMACRO, -std=c99, -Xclang, etc.
        if any(tok.startswith(pref) for pref in _PP_PREFIXES):
            pp.append(tok)
            # If the token *is* one that requires a separate argument
            # (e.g., tok is "-D", not "-DMACRO"; tok is "-isystem", not "-isystem/path")
            # Note: "-I" is in _PP_PREFIXES_REQUIRING_SEP_ARG, but it's handled by Case 1 due to `continue`.
            if tok in _PP_PREFIXES_REQUIRING_SEP_ARG:
                try:
                    # Append the next token as the argument for the current option.
                    pp.append(next(it))
                except StopIteration:
                    sys.stderr.write(f"Warning: Expected argument for '{tok}' but found none.\n")
                    break # Stop processing this command's tokens
            # If tok.startswith(pref) but tok is not in _PP_PREFIXES_REQUIRING_SEP_ARG,
            # it means the argument is part of the token itself (e.g., -DMACRO, -std=c99),
            # or it's a flag without an argument (e.g., -nostdinc).
            # In these cases, only `tok` is added, which is correct.

    return pp

# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write(
            "Usage: gen_allocators.py <compile_commands.json> <file1.c> [file2.c …]\n"
        )
        return 1

    compile_db_path = Path(sys.argv[1]).resolve()
    c_files = [Path(p).resolve() for p in sys.argv[2:]]
    
    for s in sys.argv[2:]:
        print(f'#include "{s}"')

    # --------------------------------------------------------------------- #
    # 1. Read compile_commands.json and gather front-end flags              #
    # --------------------------------------------------------------------- #
    try:
        compile_db = json.loads(compile_db_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"Error reading {compile_db_path}: {exc}\n")
        return 1

    clang_arguments: List[str] = []

    for entry in compile_db:
        entry_file = Path(entry.get("file", "")).resolve()
        if entry_file not in c_files:
            # Ignore unrelated translation units.
            continue
        root_path = entry.get("directory", "")
        if "arguments" in entry:
            tokens: Sequence[str] = entry["arguments"]
        elif "command" in entry:
            # Older CMake versions emit a single command-line string.
            tokens = shlex.split(entry["command"])
            # The first token is the compiler (“clang”), discard it.
            tokens = tokens[1:]
        else:  # pragma: no cover
            continue

        clang_arguments.extend(_extract_pp_options(tokens, root_path))
        
    

    # Deduplicate while preserving order.
    seen: set[str] = set()
    clang_arguments = [arg for arg in clang_arguments if not (arg in seen or seen.add(arg))]

    # --------------------------------------------------------------------- #
    # 2. Build a temporary umbrella translation unit                        #
    # --------------------------------------------------------------------- #
    tmp_c_path = Path(tempfile.gettempdir()) / "tmp_combined.c"
    with tmp_c_path.open("w", encoding="utf-8") as tmp_out:
        for src in c_files:
            tmp_out.write(f'#include "{src.as_posix()}"\n')

    processed_source = tmp_c_path  # Path is accepted by extract_structs

    # --------------------------------------------------------------------- #
    # 3. Extract struct metadata and generate allocator code                #
    # --------------------------------------------------------------------- #
    from extractor import extract_structs  # type: ignore
    from allocator_gen import generate_allocators  # type: ignore
    from function_call_writer import generate_main_file  # type: ignore
    from function_extract import extract_funcs  # type: ignore
    
    nm, pm = extract_structs(processed_source, clang_arguments)
    print (nm, file=sys.stderr)
    funcs: dict[tuple[str, str], list[tuple[str, str]]] = OrderedDict()
    for path in sys.argv[1:]:
        text = Path(path).read_text(encoding='utf-8', errors='ignore')
        funcs.update(extract_funcs(text))
    generated_allocs = generate_allocators(nm, pm)
    print(generated_allocs)
    #print(funcs)
    generated_main = generate_main_file(funcs, nm, pm)
    print(generated_main)
    return 0


if __name__ == "__main__":
    sys.exit(main())
    
# following updates, handle -o outname: write outname_allocs.c with the generated allocators, 
# outname.c with a main function calling all functions of the list of files given in input, 
# config-outname.json with content {"files": ["outname.c"], "cpp-extra-args":["-Iinclude","-Dblabla"]} 
# containing all precompilation informations
