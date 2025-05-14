"""
Test allocation of structs containing bitfields.
"""

from pathlib import Path
import pytest
from extractor import extract_structs
from allocator_gen import generate_allocators

def test_bitfield_allocation(tmp_path):
    # Create a test C file with bitfield structs
    c_file = tmp_path / "test.c"
    c_file.write_text("""
    struct BitFieldStruct {
        unsigned int flags : 4;
        unsigned int mode : 2;
        unsigned int : 2;  /* unnamed bitfield */
        unsigned int status : 8;
    };
    """)

    # Extract structs and generate allocators
    name_map, ptr_map = extract_structs(c_file)
    code = generate_allocators(name_map, ptr_map)

    # Verify the generated code contains bitfield handling
    assert "alloc_BitFieldStruct" in code
    assert "tis_alloc_safe" in code
    assert "tis_make_unknown" in code 