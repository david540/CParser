"""
Test allocation of complex nested structures with multiple pointer types.
"""

from pathlib import Path
import pytest
from extractor import extract_structs
from allocator_gen import generate_allocators

def test_complex_nested_allocation(tmp_path):
    # Create a test C file with complex nested structures
    c_file = tmp_path / "test.c"
    c_file.write_text("""
    struct Node {
        int value;
        struct Node* next;
        struct Node** prev;
    };

    struct Tree {
        struct Node* root;
        struct {
            struct Node* left;
            struct Node* right;
        } children;
        struct Tree* parent;
    };

    typedef struct Node* NodePtr;
    typedef NodePtr* NodePtrPtr;
    """)

    # Extract structs and generate allocators
    name_map, ptr_map = extract_structs(c_file)
    code = generate_allocators(name_map, ptr_map)

    # Verify the generated code contains complex nested structure handling
    assert "alloc_Node" in code
    assert "alloc_Tree" in code
    assert "alloc_NodePtr" in code
    assert "alloc_NodePtrPtr" in code
    assert "tis_alloc_safe" in code
    assert "tis_make_unknown" in code 