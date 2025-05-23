"""
Test allocation of structs containing unions.
"""

from pathlib import Path
import pytest
from extractor import extract_structs
from allocator_gen import generate_allocators

def test_union_allocation(tmp_path):
    # Create a test C file with union structs
    c_file = tmp_path / "test.c"
    c_file.write_text("""
    struct UnionStruct {
        union {
            int i;
            float f;
            char* str;
        } data;
        struct {
            int x;
            int y;
        } point;
    };
    """)

    # Extract structs and generate allocators
    name_map, ptr_map = extract_structs(c_file)
    code = generate_allocators(name_map, ptr_map)

    # Verify the generated code contains union handling
    assert "alloc_struct_UnionStruct" in code
    assert "auto_alloc_safe" in code
    assert "auto_make_unknown" in code 