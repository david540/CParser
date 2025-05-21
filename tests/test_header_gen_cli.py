import subprocess
import pytest
from pathlib import Path
import json
import sys

# Assuming header_gen.py is in the root of the repository
HEADER_GEN_SCRIPT = Path(__file__).parent.parent / "header_gen.py"
# Define the prelude that header_gen.py is expected to output
PRELUDE = """\
#ifndef ALLOCATOR_HEADER_H
#define ALLOCATOR_HEADER_H

#include <stddef.h> // For size_t
#include <stdlib.h> // For malloc, free
#include <string.h> // For memset

// tis_malloc_free and tis_trace_primitive_pt are defined by TIS.
// We provide dummy definitions here for standalone compilation.
#ifndef TIS_KERNEL
#define tis_malloc_free(p) free(p)
#define tis_trace_primitive_pt(p) (p)

// Dummy tis_make_unknown for untracked allocations
static inline void *tis_make_unknown(void *p, size_t size) {
    if (p) {
        memset(p, 0xAB, size); // Fill with a pattern
    }
    return p;
}
#endif // TIS_KERNEL

// Function to allocate and initialize a structure
// d: current depth, max_d: maximum depth for nested structures
"""

def run_header_gen(args, cwd=None):
    """Helper function to run header_gen.py and return the result."""
    command = [sys.executable, str(HEADER_GEN_SCRIPT)] + args
    return subprocess.run(command, capture_output=True, text=True, cwd=cwd)

def create_compile_commands(tmp_path, commands_data, filename="compile_commands.json"):
    """Helper to create a compile_commands.json file."""
    cc_path = tmp_path / filename
    with open(cc_path, "w") as f:
        json.dump(commands_data, f)
    return cc_path

# Test Case 1
def test_successful_execution(tmp_path):
    c_files_dir = tmp_path / "c_files"
    c_files_dir.mkdir()
    test1_c = c_files_dir / "test1.c"
    test1_c.write_text("struct Foo { int f; };")
    test2_c = c_files_dir / "test2.c"
    test2_c.write_text("struct Bar { char b; };")

    compile_commands_content = [
        {
            "directory": str(c_files_dir),
            "file": str(test1_c.resolve()), # Absolute path
            "arguments": ["gcc", "-c", str(test1_c.resolve())]
        },
        {
            "directory": str(c_files_dir),
            "file": str(test2_c.resolve()), # Absolute path
            "arguments": ["gcc", "-c", str(test2_c.resolve())]
        }
    ]
    cc_json_path = create_compile_commands(tmp_path, compile_commands_content)

    result = run_header_gen([str(cc_json_path), str(test1_c), str(test2_c)])

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "struct Foo* alloc_struct_Foo(int d, int max_d)" in result.stdout
    assert "struct Bar* alloc_struct_Bar(int d, int max_d)" in result.stdout
    assert PRELUDE in result.stdout

# Test Case 2
def test_failure_missing_compile_commands_json():
    result = run_header_gen(["non_existent_compile_commands.json", "dummy.c"])
    assert result.returncode != 0
    assert "Error: Compilation database file not found" in result.stderr or "No such file or directory" in result.stderr

# Test Case 3
def test_failure_malformed_compile_commands_json(tmp_path):
    malformed_json_path = tmp_path / "compile_commands.json"
    malformed_json_path.write_text("this is not json")

    result = run_header_gen([str(malformed_json_path), "dummy.c"])
    assert result.returncode != 0
    assert "Error parsing compilation database" in result.stderr or "JSONDecodeError" in result.stderr

# Test Case 4
def test_include_path_from_compile_commands(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    includes_dir = proj_dir / "includes"
    includes_dir.mkdir()
    src_dir = proj_dir / "src"
    src_dir.mkdir()

    my_header_h = includes_dir / "my_header.h"
    my_header_h.write_text("struct MyStruct { int data; };")
    main_c = src_dir / "main.c"
    main_c.write_text("#include \"my_header.h\"\nstruct AnotherStruct { struct MyStruct ms; };")

    compile_commands_content = [
        {
            "directory": str(src_dir.resolve()),
            "file": str(main_c.resolve()),
            "arguments": ["gcc", "-I" + str(includes_dir.resolve()), str(main_c.name)] # main.c as relative to directory
        }
    ]
    cc_json_path = create_compile_commands(tmp_path, compile_commands_content)

    result = run_header_gen([str(cc_json_path), str(main_c)])

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "struct MyStruct* alloc_struct_MyStruct(int d, int max_d)" in result.stdout
    assert "struct AnotherStruct* alloc_struct_AnotherStruct(int d, int max_d)" in result.stdout
    assert PRELUDE in result.stdout

# Test Case 5
def test_failure_missing_c_file_in_compile_commands_entry(tmp_path):
    proj_src_dir = tmp_path / "proj" / "src"
    proj_src_dir.mkdir(parents=True)
    missing_file_c = proj_src_dir / "missing_file.c" # File is declared but not created

    compile_commands_content = [
        {
            "directory": str(proj_src_dir.resolve()),
            "file": str(missing_file_c.resolve()), # Absolute path to the non-existent file
            "arguments": ["gcc", "-c", str(missing_file_c.resolve())]
        }
    ]
    cc_json_path = create_compile_commands(tmp_path, compile_commands_content)

    # We run header_gen.py targeting the missing file explicitly.
    # header_gen.py itself might not fail until extractor.py (libclang) tries to parse it.
    result = run_header_gen([str(cc_json_path), str(missing_file_c)])

    assert result.returncode != 0
    # Expecting an error from libclang via extractor.py, or header_gen.py itself if it checks file existence
    assert "error" in result.stderr.lower()
    # A more specific check might be "could not build module" or "file not found" from clang's perspective
    # or from header_gen.py if it adds specific error handling for this.
    # For now, checking that the expected allocator is NOT generated, and an error occurred.
    assert "alloc_struct_" not in result.stdout # Ensure no allocator for a missing file's structs.

# Test Case 6
def test_no_c_file_arguments_processes_all_from_db(tmp_path):
    c_files_dir = tmp_path / "c_files"
    c_files_dir.mkdir()
    only_in_db_c = c_files_dir / "only_in_db.c"
    only_in_db_c.write_text("struct OnlyDB { int val; };")

    compile_commands_content = [
        {
            "directory": str(c_files_dir.resolve()),
            "file": str(only_in_db_c.resolve()),
            "arguments": ["gcc", "-c", str(only_in_db_c.resolve())]
        }
    ]
    cc_json_path = create_compile_commands(tmp_path, compile_commands_content)

    result = run_header_gen([str(cc_json_path)]) # No C file arguments

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "struct OnlyDB* alloc_struct_OnlyDB(int d, int max_d)" in result.stdout
    assert PRELUDE in result.stdout

# Test Case 7
def test_no_c_file_arguments_and_empty_db(tmp_path):
    cc_json_path = create_compile_commands(tmp_path, []) # Empty list for commands

    result = run_header_gen([str(cc_json_path)])

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert PRELUDE in result.stdout
    # Check that no allocator *implementations* are present.
    # The alloc_struct_ prefix is part of the function name.
    assert "alloc_struct_" not in result.stdout
    # The file should end with #endif // ALLOCATOR_HEADER_H
    assert result.stdout.strip().endswith("#endif // ALLOCATOR_HEADER_H")

pytest_plugins = ['pytester'] # For potential future use with pytester, not strictly needed now.
