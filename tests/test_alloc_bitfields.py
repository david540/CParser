"""
Test allocation of structs containing bitfields.
"""

import sys
from pathlib import Path
import pytest

# Add project root to sys.path to allow importing extractor and allocator_gen
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from extractor import extract_structs
from allocator_gen import generate_allocators

# Common prelude expected in generated allocator files
ALLOCATOR_PRELUDE = """\
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

def get_allocator_function_body(allocator_name_suffix, generated_code):
    """
    Helper to extract the body of a specific allocator function.
    allocator_name_suffix is e.g., "struct_MyStruct" for "alloc_struct_MyStruct"
    """
    try:
        # Find the start of the function
        # Adjusted to handle "struct_Name" or "typedef_Name" patterns
        func_sig_start = f"alloc_{allocator_name_suffix}(int d, int max_d)"
        start_idx = generated_code.index(func_sig_start)
        
        # Find the opening brace of the function body
        open_brace_idx = generated_code.index("{", start_idx)
        
        # Find the corresponding closing brace to delimit the function body
        brace_level = 1
        current_idx = open_brace_idx + 1
        while current_idx < len(generated_code):
            if generated_code[current_idx] == '{':
                brace_level += 1
            elif generated_code[current_idx] == '}':
                brace_level -= 1
                if brace_level == 0:
                    end_idx = current_idx
                    # Return the content from the start of the signature to the closing brace
                    return generated_code[start_idx : end_idx + 1]
            current_idx += 1
        return None # Should not happen for well-formed C code
    except ValueError:
        # Function signature not found in the generated code
        return None

# Refactored test_bitfield_allocation
def test_bitfield_allocation(tmp_path):
    c_code = """
    struct BitFieldStruct {
        unsigned int flags : 4;
        unsigned int mode : 2;
        unsigned int : 2;  /* unnamed bitfield */
        unsigned int status : 8;
    };
    """
    c_file = tmp_path / "test_bitfield.c"
    c_file.write_text(c_code)

    # extract_structs now returns a tuple: (name_map, ptr_map, typedef_map)
    name_map, ptr_map, typedef_map = extract_structs([str(c_file)], source_code=c_code)

    # Check name_map
    assert "struct BitFieldStruct" in name_map
    # Correctly form the dictionary for easier lookup, excluding unnamed fields
    extracted_fields = {name: type_str for type_str, name in name_map["struct BitFieldStruct"] if name}
    
    assert extracted_fields["flags"] == "unsigned int"
    assert extracted_fields["mode"] == "unsigned int"
    assert extracted_fields["status"] == "unsigned int"
    
    # Ensure only named fields are counted for this assertion
    assert len(extracted_fields) == 3

    code = generate_allocators(name_map, ptr_map, typedef_map)

    assert ALLOCATOR_PRELUDE in code
    allocator_func_signature = "struct BitFieldStruct* alloc_struct_BitFieldStruct(int d, int max_d)"
    assert allocator_func_signature in code
    
    alloc_func_body = get_allocator_function_body("struct_BitFieldStruct", code)
    assert alloc_func_body is not None, f"Allocator function body for struct_BitFieldStruct not found. Code:\n{code}"
    assert "out = tis_alloc_safe(sizeof(struct BitFieldStruct));" in alloc_func_body
    assert "tis_make_unknown(out, sizeof(*out));" in alloc_func_body # Check for sizeof(*out) specifically
    assert "return tis_trace_primitive_pt(out);" in alloc_func_body

def test_mixed_bitfields_and_regular_fields(tmp_path):
    c_code = """
    struct MixedBitFields {
        unsigned int flag1 : 1;
        int normal_int;
        unsigned int val : 3;
        char normal_char;
        unsigned int :0; // Zero-width bitfield for alignment
        unsigned int flag2 : 1;
    };
    """
    c_file = tmp_path / "test_mixed.c"
    c_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(c_file)], source_code=c_code)

    assert "struct MixedBitFields" in name_map
    extracted_fields = {name: type_str for type_str, name in name_map["struct MixedBitFields"] if name}

    assert extracted_fields["flag1"] == "unsigned int"
    assert extracted_fields["normal_int"] == "int"
    assert extracted_fields["val"] == "unsigned int"
    assert extracted_fields["normal_char"] == "char"
    assert extracted_fields["flag2"] == "unsigned int"
    assert len(extracted_fields) == 5


    code = generate_allocators(name_map, ptr_map, typedef_map)

    assert ALLOCATOR_PRELUDE in code
    allocator_func_signature = "struct MixedBitFields* alloc_struct_MixedBitFields(int d, int max_d)"
    assert allocator_func_signature in code
    
    alloc_func_body = get_allocator_function_body("struct_MixedBitFields", code)
    assert alloc_func_body is not None, f"Allocator function body for struct_MixedBitFields not found. Code:\n{code}"
    assert "out = tis_alloc_safe(sizeof(struct MixedBitFields));" in alloc_func_body
    assert "tis_make_unknown(out, sizeof(*out));" in alloc_func_body
    assert "return tis_trace_primitive_pt(out);" in alloc_func_body
    # Ensure regular fields are not individually allocated by assignment (e.g. out->normal_int = ...)
    assert "out->normal_int =" not in alloc_func_body
    assert "out->normal_char =" not in alloc_func_body

def test_various_underlying_types_for_bitfields(tmp_path):
    c_code = """
    struct VariousTypesBitFields {
        signed int signed_bf : 3;
        unsigned int unsigned_bf : 4;
        int plain_int_bf : 2; 
        // _Bool bool_bf : 1; // C99 _Bool - pycparser might see as unsigned int or int
        // char char_bf : 2;   // Often treated as int/unsigned int by parsers for bitfields
    };
    """
    # For `_Bool bool_bf : 1;`, pycparser represents `_Bool` as `unsigned int`
    # For `char char_bf : 2;`, pycparser represents `char` as `char` (but its signedness is impl-defined)
    # For bitfields, C standard says int, signed int, unsigned int. Compilers may allow others.
    # pycparser seems to parse the type as given, but for bitfields, the actual storage is int-aligned.
    # Let's test what extractor.py gives us.
    c_file = tmp_path / "test_various_types.c"
    c_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(c_file)], source_code=c_code)

    assert "struct VariousTypesBitFields" in name_map
    extracted_fields = {name: type_str for type_str, name in name_map["struct VariousTypesBitFields"] if name}

    # Based on pycparser's behavior with C-struct-parser:
    # 'signed int' becomes 'int'
    # 'unsigned int' remains 'unsigned int'
    # 'int' remains 'int'
    assert extracted_fields["signed_bf"] == "int" 
    assert extracted_fields["unsigned_bf"] == "unsigned int"
    assert extracted_fields["plain_int_bf"] == "int"
    assert len(extracted_fields) == 3

    code = generate_allocators(name_map, ptr_map, typedef_map)

    assert ALLOCATOR_PRELUDE in code
    allocator_func_signature = "struct VariousTypesBitFields* alloc_struct_VariousTypesBitFields(int d, int max_d)"
    assert allocator_func_signature in code
    
    alloc_func_body = get_allocator_function_body("struct_VariousTypesBitFields", code)
    assert alloc_func_body is not None, f"Allocator function body for struct_VariousTypesBitFields not found. Code:\n{code}"
    assert "out = tis_alloc_safe(sizeof(struct VariousTypesBitFields));" in alloc_func_body
    assert "tis_make_unknown(out, sizeof(*out));" in alloc_func_body
    assert "return tis_trace_primitive_pt(out);" in alloc_func_body

"""
Summary of changes:
- Added sys.path.insert for robust imports.
- Added ALLOCATOR_PRELUDE.
- Added get_allocator_function_body helper for more precise assertions.
- Refactored test_bitfield_allocation:
    - Now uses 3-tuple return from extract_structs.
    - Checks name_map for field names and types.
    - Specifically checks for `tis_make_unknown(out, sizeof(*out))` within the allocator.
- Added test_mixed_bitfields_and_regular_fields:
    - Tests struct with interleaved bitfields and normal fields.
    - Checks name_map for all field types.
    - Verifies allocator uses `tis_make_unknown(out, sizeof(*out))` and does not init regular fields individually.
- Added test_various_underlying_types_for_bitfields:
    - Tests bitfields with `signed int`, `unsigned int`, `int`.
    - Checks name_map based on pycparser's typical output.
    - Verifies allocator uses `tis_make_unknown(out, sizeof(*out))`.
"""
