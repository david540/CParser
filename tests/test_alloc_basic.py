import re
from pathlib import Path

from extractor import extract_structs
from allocator_gen import generate_allocators


def test_basic(tmp_path: Path):
    code = r"""
        struct A { int a; };
        typedef struct A* pA;     /* pointeur simple */

        struct B { char* s; };
        typedef struct B B_t;     /* alias valeur */
    """
    f = tmp_path / "basic.c"
    f.write_text(code)

    name_map, ptr_map = extract_structs(f)
    cgen = generate_allocators(name_map, ptr_map)

    # --- prototypes attendus ----------------------------------------------
    assert "struct A* alloc_A(int d, int max_d)" in cgen
    assert re.search(r"\bpA alloc_pA\(int d, int max_d\)", cgen)

    # alias valeur => son propre allocateur
    assert "B_t* alloc_B_t(int d, int max_d)" in cgen

    # tous les canonicals "struct X" dans name_map sont couverts
    for k in name_map:
        assert f"alloc_{k.replace('struct ', '')}" in cgen
