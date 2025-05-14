import re
from pathlib import Path
from extractor import extract_structs
from allocator_gen import generate_allocators


def test_nested(tmp_path: Path):
    code = r"""
        struct Inner { int x; };
        typedef struct Inner Inner_t;

        struct Outer {
            struct Inner   in;   /* valeur */
            struct Inner*  pin;  /* pointeur simple */
        };
        typedef struct Outer* pOuter;
    """
    f = tmp_path / "nested.c"
    f.write_text(code)

    nmap, pmap = extract_structs(f)
    cgen = generate_allocators(nmap, pmap)

    # ---------------- prototypes ----------------
    assert "struct Outer* alloc_Outer(" in cgen
    assert "pOuter alloc_pOuter(" in cgen
    assert "Inner_t* alloc_Inner_t(" in cgen   # alias valeur

    # ---------------- corps d'Outer ------------
    body = re.search(
        r"struct Outer\* alloc_Outer\(.*?\)\s*{(?P<body>[^}]+)}",
        cgen,
        re.S,
    ).group("body")

    # champ valeur -> *alloc_Inner
    assert "*alloc_Inner(d + 1, max_d);" in body
    # champ pointeur -> alloc_Inner
    assert "pin = alloc_Inner(d + 1, max_d);" in body
