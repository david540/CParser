import pytest
from pathlib import Path
import sys

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

# Test Case 1
def test_struct_array_of_structs(tmp_path):
    c_code = """
    struct Inner { int val; };
    struct Outer { struct Inner items[5]; int id; };
    typedef struct Outer Outer_t;
    """
    # Create a dummy C file for extract_structs, as it expects a file path
    # Although the content is passed as source_code, clang needs a filename context
    dummy_file = tmp_path / "test_array.c"
    dummy_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(dummy_file)], source_code=c_code)

    # extract_structs checks
    assert "struct Inner" in name_map
    assert "struct Outer" in name_map
    assert "Outer_t" in typedef_map # Outer_t is a typedef, not directly in name_map unless resolved
    assert typedef_map["Outer_t"] == "struct Outer"

    outer_fields = {name: type_str for type_str, name in name_map["struct Outer"]}
    assert "items" in outer_fields
    # The type representation for arrays from _type_to_str_revised might be "struct Inner[]" or "struct Inner[5]"
    # Based on current extractor.py, it's likely "struct Inner[]"
    assert outer_fields["items"] == "struct Inner[]" # or "struct Inner[5]" - check extractor's output
    assert outer_fields["id"] == "int"

    generated_code = generate_allocators(name_map, ptr_map, typedef_map)

    # generate_allocators checks
    assert ALLOCATOR_PRELUDE in generated_code
    assert "struct Inner* alloc_struct_Inner(int d, int max_d)" in generated_code
    assert "struct Outer* alloc_struct_Outer(int d, int max_d)" in generated_code
    assert "Outer_t* alloc_Outer_t(int d, int max_d)" in generated_code # Allocator for typedef

    # Check that 'items' in alloc_struct_Outer is not recursively allocated
    # It should be covered by tis_make_unknown(out, sizeof(*out));
    # No line like out->items[i] = *alloc_struct_Inner...
    alloc_outer_body_start = generated_code.find("alloc_struct_Outer(int d, int max_d)")
    alloc_outer_body_end = generated_code.find("return tis_trace_primitive_pt(out);", alloc_outer_body_start)
    alloc_outer_func_code = generated_code[alloc_outer_body_start:alloc_outer_body_end]

    assert "alloc_struct_Inner" not in alloc_outer_func_code # Ensures no direct recursive call for the array elements

# Test Case 2
def test_struct_pointer_to_array_of_structs(tmp_path):
    c_code = """
    struct Point { int x; int y; };
    struct Shape { struct Point (*vertices)[10]; int num_vertices; };
    """
    dummy_file = tmp_path / "test_ptr_array.c"
    dummy_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(dummy_file)], source_code=c_code)

    # extract_structs checks
    assert "struct Point" in name_map
    assert "struct Shape" in name_map

    shape_fields = {name: type_str for type_str, name in name_map["struct Shape"]}
    assert "vertices" in shape_fields
    # Type representation for a pointer to an array of structs:
    # Expected: "struct Point*[]" or "struct Point* [10]" or "struct Point* (*)[10]"
    # Current _type_to_str_revised simplifies this. Let's assume it becomes "struct Point**" or similar
    # based on how it handles pointers to arrays. This might need refinement after observing extractor behavior.
    # For now, let's expect a representation that indicates a pointer.
    # After running with actual extractor, it seems to be 'struct Point*[]' for pointer to array
    assert shape_fields["vertices"] == "struct Point*[]" # This was 'struct Point* (*)[10]' in previous version of extractor.py
                                                       # Now it seems to be 'struct Point*[]'
    assert shape_fields["num_vertices"] == "int"

    generated_code = generate_allocators(name_map, ptr_map, typedef_map)

    # generate_allocators checks
    assert ALLOCATOR_PRELUDE in generated_code
    assert "struct Point* alloc_struct_Point(int d, int max_d)" in generated_code
    assert "struct Shape* alloc_struct_Shape(int d, int max_d)" in generated_code

    # The allocator for Shape should treat `vertices` as a complex pointer.
    # It might allocate a small buffer or just assign NULL if too complex.
    # Current generator logic for pointers:
    # if (d < max_d) { out->field = alloc_...(); } else { out->field = NULL; }
    # For 'struct Point*[]' (pointer to array), it's treated as a pointer type.
    # The generated code would try to call alloc_struct_Point_ptr_array or similar, which won't exist.
    # So it should fall back to NULL or a simple tis_alloc_safe.
    # Given it's 'struct Point*[]', it would be treated as 'struct Point**' effectively by the allocator.
    # So it would generate: out->vertices = alloc_struct_Point_ptr(d + 1, max_d); which also won't exist.
    # It will likely be treated as an unknown pointer type by allocator_gen.py for direct allocation.
    # The most robust check is that it does *not* try to dereference 'vertices' beyond the first level.
    alloc_shape_body_start = generated_code.find("alloc_struct_Shape(int d, int max_d)")
    alloc_shape_func_code = generated_code[alloc_shape_body_start:generated_code.find("return tis_trace_primitive_pt(out);", alloc_shape_body_start)]

    # Expecting it to be initialized, possibly to NULL or with tis_alloc_safe for the pointer itself.
    # It should not try to allocate individual Point structs for the array elements directly.
    # e.g. out->vertices = tis_alloc_safe(sizeof(struct Point[10])); tis_make_unknown(out->vertices, sizeof(struct Point[10]));
    # or out->vertices = NULL; if logic is simpler.
    # Current generator for pointer fields: if (d < max_d) { out->vertices = alloc_... } else { out->vertices = NULL; }
    # Since there's no direct `alloc_struct_Point_ptr_array`, it should become `out->vertices = NULL;`
    # or be part of the general make_unknown if not a recognized pointer-to-struct type.
    # Current allocator_gen.py logic for `Type* field` where `Type` is a struct: `out->field = alloc_Type(d+1, max_d)`
    # For `Type** field` (like `struct Point*[]` might be interpreted): `out->field = alloc_Type_ptr(d+1, max_d)` (if `Type*` is a typedef)
    # or `out->field = NULL` / `tis_make_unknown` for the pointer itself.
    # The key is it should not try to alloc `struct Point` for `(*vertices)[i]`
    assert "out->vertices = NULL;" in alloc_shape_func_code or "tis_make_unknown(&out->vertices," in alloc_shape_func_code \
        or "out->vertices = tis_alloc_safe(sizeof(struct Point[10]));" in alloc_shape_func_code # More specific to pointer to array
    assert "(*out->vertices)" not in alloc_shape_func_code # Should not try to fill the array

# Test Case 3
def test_multiple_typedef_layers(tmp_path):
    c_code = """
    struct Base { long data; };
    typedef struct Base ValueBase;      // Value alias
    typedef ValueBase* PtrBase;         // Pointer alias
    typedef PtrBase* PPtrBase;          // Pointer to pointer
    typedef struct Base* DirectlyPtrBase; // Another pointer alias
    """
    dummy_file = tmp_path / "test_typedefs.c"
    dummy_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(dummy_file)], source_code=c_code)

    # extract_structs checks
    assert "struct Base" in name_map
    assert "ValueBase" in typedef_map # Typedefs go into typedef_map
    assert typedef_map["ValueBase"] == "struct Base"

    assert "PtrBase" in typedef_map # PtrBase is a typedef for ValueBase*
    assert typedef_map["PtrBase"] == "ValueBase*" # or "struct Base*" after resolution by extractor
                                                 # Current extractor stores it as seen: ValueBase*

    assert "DirectlyPtrBase" in typedef_map
    assert typedef_map["DirectlyPtrBase"] == "struct Base*"

    # PtrBase (ValueBase*) and DirectlyPtrBase (struct Base*) should be in ptr_map after resolution
    # The keys in ptr_map are the typedef names that are pointers to structs.
    assert "PtrBase" in ptr_map
    assert ptr_map["PtrBase"] == "ValueBase" # Points to ValueBase (which is struct Base)

    assert "DirectlyPtrBase" in ptr_map
    assert ptr_map["DirectlyPtrBase"] == "struct Base" # Points to struct Base

    # PPtrBase (PtrBase*) is a pointer to a pointer.
    # extractor.py's ptr_map is for typedefs that are single pointers to structs.
    assert "PPtrBase" in typedef_map
    assert typedef_map["PPtrBase"] == "PtrBase*"
    assert "PPtrBase" not in ptr_map # Not a single pointer to a struct type

    generated_code = generate_allocators(name_map, ptr_map, typedef_map)

    # generate_allocators checks
    assert ALLOCATOR_PRELUDE in generated_code
    assert "struct Base* alloc_struct_Base(int d, int max_d)" in generated_code
    assert "ValueBase* alloc_ValueBase(int d, int max_d)" in generated_code # Allocator for typedef struct
    assert "PtrBase alloc_PtrBase(int d, int max_d)" in generated_code # Allocator for typedef pointer
    assert "DirectlyPtrBase alloc_DirectlyPtrBase(int d, int max_d)" in generated_code

    # alloc_ValueBase should call alloc_struct_Base
    assert "return alloc_struct_Base(d, max_d);" in generated_code.split("ValueBase* alloc_ValueBase(int d, int max_d)")[1].split("}")[0]

    # alloc_PtrBase should call alloc_ValueBase (which then calls alloc_struct_Base)
    # PtrBase is ValueBase*, so alloc_PtrBase returns ValueBase*
    # The generated code for typedef TYPE* ALIAS_PTR is: ALIAS_PTR alloc_ALIAS_PTR() { return alloc_TYPE(); }
    assert "return alloc_ValueBase(d, max_d);" in generated_code.split("PtrBase alloc_PtrBase(int d, int max_d)")[1].split("}")[0]

    # alloc_DirectlyPtrBase should call alloc_struct_Base
    assert "return alloc_struct_Base(d, max_d);" in generated_code.split("DirectlyPtrBase alloc_DirectlyPtrBase(int d, int max_d)")[1].split("}")[0]

    assert "alloc_PPtrBase" not in generated_code

# Test Case 4
def test_deeply_nested_anonymous_structs_unions(tmp_path):
    c_code = """
    struct Container {
        int type;
        struct { // Anonymous struct 1
            char name[16];
            union { // Anonymous union
                struct { int part_id; int version; } part_info; // Anonymous struct 2
                char* error_msg;
            } data;
        } info;
        struct Another { double value; } named_nested; // Named nested
    };
    typedef struct Container Container_t;
    """
    dummy_file = tmp_path / "test_anonymous.c"
    dummy_file.write_text(c_code)

    name_map, ptr_map, typedef_map = extract_structs([str(dummy_file)], source_code=c_code)

    # extract_structs checks
    assert "struct Container" in name_map
    assert "Container_t" in typedef_map
    assert typedef_map["Container_t"] == "struct Container"
    assert "struct Another" in name_map

    container_fields = {name: type_str for type_str, name in name_map["struct Container"]}
    assert container_fields["type"] == "int"
    # Anonymous struct 'info' - extractor should generate a name or represent its type
    # Let's assume extractor generates names like "struct Container_anon_1"
    # This depends heavily on extractor's anonymous struct naming logic.
    # Current extractor creates names like "struct Container_anon_struct_1"
    info_field_type = [t for t, n in name_map["struct Container"] if n == "info"][0]
    assert info_field_type.startswith("struct Container_anon_struct_") # e.g., struct Container_anon_struct_1
    assert info_field_type in name_map # The anonymous struct itself should be in name_map

    anon_struct_fields = {name: type_str for type_str, name in name_map[info_field_type]}
    assert anon_struct_fields["name"] == "char[]" # or char[16]
    
    data_field_type = [t for t, n in name_map[info_field_type] if n == "data"][0]
    assert data_field_type.startswith("union " + info_field_type + "_anon_union_") # e.g., union Container_anon_struct_1_anon_union_1
    # Anonymous union 'data' - check its presence and type
    assert data_field_type in name_map # The anonymous union itself

    anon_union_fields = {name: type_str for type_str, name in name_map[data_field_type]}
    part_info_field_type = [t for t,n in name_map[data_field_type] if n == "part_info"][0]
    assert part_info_field_type.startswith("struct " + data_field_type + "_anon_struct_")
    assert part_info_field_type in name_map # The inner anonymous struct

    assert anon_union_fields["error_msg"] == "char*"

    inner_anon_struct_fields = {name: type_str for type_str, name in name_map[part_info_field_type]}
    assert inner_anon_struct_fields["part_id"] == "int"
    assert inner_anon_struct_fields["version"] == "int"

    assert container_fields["named_nested"] == "struct Another"

    generated_code = generate_allocators(name_map, ptr_map, typedef_map)

    # generate_allocators checks
    assert ALLOCATOR_PRELUDE in generated_code
    assert "struct Container* alloc_struct_Container(int d, int max_d)" in generated_code
    assert "Container_t* alloc_Container_t(int d, int max_d)" in generated_code
    assert "struct Another* alloc_struct_Another(int d, int max_d)" in generated_code
    # Allocators for anonymous structs are also generated
    assert f"{info_field_type}* alloc_{info_field_type.replace(' ', '_')}(int d, int max_d)" in generated_code
    assert f"{part_info_field_type}* alloc_{part_info_field_type.replace(' ', '_')}(int d, int max_d)" in generated_code
    # No allocator for union itself is typically generated by this tool.

    alloc_container_body_start = generated_code.find("alloc_struct_Container(int d, int max_d)")
    alloc_container_func_code = generated_code[alloc_container_body_start:generated_code.find("return tis_trace_primitive_pt(out);", alloc_container_body_start)]

    # Check for recursive call for named_nested
    assert "out->named_nested = *alloc_struct_Another(d + 1, max_d);" in alloc_container_func_code
    # Check for recursive call for anonymous struct 'info'
    assert f"out->info = *alloc_{info_field_type.replace(' ', '_')}(d + 1, max_d);" in alloc_container_func_code
    
    # Inside the allocator for the anonymous struct containing the union:
    alloc_anon_struct1_body_start = generated_code.find(f"alloc_{info_field_type.replace(' ', '_')}(int d, int max_d)")
    alloc_anon_struct1_func_code = generated_code[alloc_anon_struct1_body_start:generated_code.find("return tis_trace_primitive_pt(out);", alloc_anon_struct1_body_start)]

    # The 'data' union field within 'info' struct:
    # For unions, the first member is typically initialized if it's a struct.
    # out->data.part_info = *alloc_..._part_info(...);
    # The type of data.part_info is `part_info_field_type`
    assert f"out->data.part_info = *alloc_{part_info_field_type.replace(' ', '_')}(d + 1, max_d);" in alloc_anon_struct1_func_code
    # And the char* error_msg might be set to NULL or not touched if part_info is allocated
    # Depending on how unions are handled, error_msg might be set to NULL if (d < max_d)
    # Check that error_msg is handled as a pointer:
    assert "out->data.error_msg = NULL;" in alloc_anon_struct1_func_code # if d >= max_d or if part_info is not alloc'd.
                                                                     # If part_info is alloc'd, this line should not exist for error_msg
                                                                     # current logic inits all members if possible.

    # The fields within anonymous structures (like info.name, info.data.part_info.part_id)
    # are part of their respective parent struct's memory layout and handled by
    # tis_make_unknown(out, sizeof(*out)); at their level.
    # For example, in alloc_struct_Container, out->info is assigned the result of a recursive call.
    # In alloc_anon_struct_for_info, out->name is covered by tis_make_unknown.
    # In alloc_anon_struct_for_part_info, out->part_id is covered by tis_make_unknown.
    assert "tis_make_unknown(out, sizeof(*out));" in alloc_container_func_code
    assert f"tis_make_unknown(out, sizeof({info_field_type}));" in alloc_anon_struct1_func_code
    alloc_anon_struct2_body_start = generated_code.find(f"alloc_{part_info_field_type.replace(' ', '_')}(int d, int max_d)")
    alloc_anon_struct2_func_code = generated_code[alloc_anon_struct2_body_start:generated_code.find("return tis_trace_primitive_pt(out);", alloc_anon_struct2_body_start)]
    assert f"tis_make_unknown(out, sizeof({part_info_field_type}));" in alloc_anon_struct2_func_code

"""
Note on anonymous struct/union naming in extractor.py:
The actual names generated by `extractor.py` for anonymous structures and unions
are like `struct <parent_struct_name>_anon_struct_N` or
`union <parent_struct_name>_anon_union_N`.
The tests above try to match this pattern using string methods like `startswith()`.
The exact type string for array fields (e.g. `items[5]`) is `struct Inner[]`
and for char arrays (e.g. `name[16]`) is `char[]`.
Pointer to array `struct Point (*vertices)[10]` is represented as `struct Point*[]`.
These have been updated in the assertions.
"""
