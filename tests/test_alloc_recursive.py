import re
from pathlib import Path

from extractor import extract_structs
from allocator_gen import generate_allocators


def test_recursive(tmp_path: Path):
    code = r"""
        struct Node {
            int id;
            struct Node* next;   // récursif
        };
    """
    f = tmp_path / "rec.c"
    f.write_text(code)

    nmap, pmap = extract_structs(f)
    cgen = generate_allocators(nmap, pmap)
    print(cgen)

    # prototype
    assert "struct Node* alloc_struct_Node(int d, int max_d)" in cgen

    # corps : doit appeler alloc_Node sur next
    pattern = r"out->next\s*=\s*alloc_struct_Node\(d \+ 1, max_d\);"
    assert re.search(pattern, cgen)
