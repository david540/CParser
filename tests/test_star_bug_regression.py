"""
Ce test reproduit exactement le bogue 'alloc_Node*(' et vérifie qu'il a
disparu.
"""
import re
from pathlib import Path

from extractor import extract_structs
from allocator_gen import generate_allocators


def test_no_trailing_star_on_recursive_call(tmp_path: Path):
    csrc = r"""
        struct Node { struct Node* next; };
    """
    fn = tmp_path / "star.c"
    fn.write_text(csrc)

    name_map, ptr_map = extract_structs(fn)
    generated = generate_allocators(name_map, ptr_map)

    # Le code incorrect était 'alloc_Node*(' — il NE doit plus apparaître
    assert "alloc_Node*(" not in generated

    # La bonne forme doit être là
    assert re.search(r"out->next\s*=\s*alloc_struct_Node\(d \+ 1, max_d\);", generated)
    
    
    assert len(name_map.keys()) == 1
