"""
Test allocation of structs containing arrays.
"""

from pathlib import Path
import pytest
from extractor import extract_structs
from allocator_gen import generate_allocators

def test_array_allocation(tmp_path):
    # Create a test C file with array structs
    c_file = tmp_path / "test.c"
    c_file.write_text("""
    struct ArrayStruct {
        int data[10];
        char* strings[5];
        struct Inner* ptrs[3];
    };

    struct Inner {
        int value;
    };
    """)

    # Extract structs and generate allocators
    name_map, ptr_map = extract_structs(c_file)
    code = generate_allocators(name_map, ptr_map)

    # Verify the generated code contains array handling
    assert "alloc_struct_ArrayStruct" in code
    assert "alloc_struct_Inner" in code
    assert "auto_alloc_safe" in code
    assert "auto_make_unknown" in code 