import subprocess
import pytest
from pathlib import Path

# Assuming allocator_gen.py is in the root of the repository
ALLOCATOR_GEN_SCRIPT = Path(__file__).parent.parent / "allocator_gen.py"

def run_allocator_gen(args):
    """Helper function to run allocator_gen.py and return the result."""
    command = ["python", str(ALLOCATOR_GEN_SCRIPT)] + args
    return subprocess.run(command, capture_output=True, text=True)

def test_successful_execution_with_file(tmp_path):
    # Create a temporary C file
    c_code = "struct Point { int x; int y; };"
    temp_file = tmp_path / "test_point.c"
    temp_file.write_text(c_code)

    # Run allocator_gen.py with the temporary file
    result = run_allocator_gen([str(temp_file)])

    # Assert successful execution
    assert result.returncode == 0
    assert "struct Point* alloc_struct_Point(int d, int max_d)" in result.stdout

def test_successful_execution_with_string_input():
    # Define a C code string
    c_code_string = "struct Vector { double i; double j; };"

    # Run allocator_gen.py with the C code string
    result = run_allocator_gen(["-", c_code_string])

    # Assert successful execution
    assert result.returncode == 0
    assert "struct Vector* alloc_struct_Vector(int d, int max_d)" in result.stdout

def test_failure_non_existent_file():
    # Run allocator_gen.py with a non-existent file
    result = run_allocator_gen(["non_existent_file.c"])

    # Assert failure
    assert result.returncode != 0
    # Check for a more specific error message if possible,
    # for now, we assume stderr will contain some error message.
    assert "Error: Source file not found" in result.stderr or "No such file or directory" in result.stderr

def test_failure_c_syntax_error(tmp_path):
    # Create a temporary C file with a syntax error
    c_code_error = "struct ErrorProne { int a; char b; );"  # Missing '{'
    temp_file_error = tmp_path / "test_error.c"
    temp_file_error.write_text(c_code_error)

    # Run allocator_gen.py with the file containing a syntax error
    result = run_allocator_gen([str(temp_file_error)])

    # Assert failure
    assert result.returncode != 0
    # Check for a specific error message related to parsing or libclang
    # This might need adjustment based on the actual error output of allocator_gen.py
    assert "error" in result.stderr.lower() # A general check for "error" in stderr

def test_execution_with_clang_args(tmp_path):
    # Create a temporary C file that requires a macro
    c_code_macro = "struct MacroStruct { MY_TYPE field; };"
    temp_file_macro = tmp_path / "test_macro.c"
    temp_file_macro.write_text(c_code_macro)

    # Run allocator_gen.py with the macro definition
    result_with_macro = run_allocator_gen([str(temp_file_macro), "-DMY_TYPE=int"])

    # Assert successful execution and correct output
    assert result_with_macro.returncode == 0
    assert "struct MacroStruct* alloc_struct_MacroStruct(int d, int max_d)" in result_with_macro.stdout
    # Add more specific checks for 'field' handling if possible,
    # e.g., checking for 'tis_make_unknown' or similar based on expected generated code.
    # For now, the presence of the allocator function is the primary check.

    # Run allocator_gen.py without the macro definition
    result_without_macro = run_allocator_gen([str(temp_file_macro)])

    # Assert failure or incorrect output (depending on error handling)
    assert result_without_macro.returncode != 0
    # Or, if it exits with 0 but fails to generate the specific allocator:
    # assert "struct MacroStruct* alloc_struct_MacroStruct(int d, int max_d)" not in result_without_macro.stdout
    # A more robust check would be to see if stderr contains an error about MY_TYPE being undefined.
    assert "error" in result_without_macro.stderr.lower() # General check for "error"
    assert "MY_TYPE" in result_without_macro.stderr # Check for the undefined macro name in stderr
