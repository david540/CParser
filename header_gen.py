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

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

_PP_PREFIXES = (
    "-I", "-isystem", "-iquote", "-idirafter",
    "-D", "-U", "-include", "-imacros",
    "-iprefix", "-iwithprefix", "-iwithprefixbefore",
    "-nostdinc", "-f", "-m", "-std=", "-x", "-Xclang",
)


def _extract_pp_options(tokens: Sequence[str]) -> List[str]:
    """
    Filter a compile-command token list, keeping only options that influence
    the pre-processor / language front-end (include paths, macros, language
    standard, etc.).

    Parameters
    ----------
    tokens
        The tokenised compile command (not including the compiler executable).

    Returns
    -------
    List[str]
        Tokens relevant to Clang's front-end.
    """
    pp: List[str] = []
    it = iter(tokens)

    for tok in it:
        # Match an option that begins with one of the recognised prefixes.
        if any(tok.startswith(pref) for pref in _PP_PREFIXES):
            pp.append(tok)

            # Handle options that take a *separate* argument (e.g. “-I path”).
            if tok in {
                "-I", "-isystem", "-iquote", "-idirafter",
                "-imacros", "-include", "-U", "-D",
                "-iprefix", "-iwithprefix", "-iwithprefixbefore",
            }:
                try:
                    pp.append(next(it))
                except StopIteration:
                    # Malformed compile_commands.json entry – ignore gracefully.
                    break

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

        if "arguments" in entry:
            tokens: Sequence[str] = entry["arguments"]
        elif "command" in entry:
            # Older CMake versions emit a single command-line string.
            tokens = shlex.split(entry["command"])
            # The first token is the compiler (“clang”), discard it.
            tokens = tokens[1:]
        else:  # pragma: no cover
            continue

        clang_arguments.extend(_extract_pp_options(tokens))

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

    nm, pm = extract_structs(processed_source, clang_arguments)
    generated = generate_allocators(nm, pm)
    print(generated)

    return 0


if __name__ == "__main__":
    sys.exit(main())
    
# following updates, handle -o outname: write outname_allocs.c with the generated allocators, 
# outname.c with a main function calling all functions of the list of files given in input, 
# config-outname.json with content {"files": ["outname.c"], "cpp-extra-args":["-Iinclude","-Dblabla"]} 
# containing all precompilation informations
