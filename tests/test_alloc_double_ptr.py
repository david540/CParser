from pathlib import Path
from extractor import extract_structs
from allocator_gen import generate_allocators


def test_double_pointer_exclusion(tmp_path: Path):
    code = r"""
        struct X { int v; };
        typedef struct X* pX;     // simple  => OK
        typedef struct X** ppX;   // double  => IGNORÉ
        typedef struct X*** pppX; // triple  => IGNORÉ
    """
    f = tmp_path / "dp.c"
    f.write_text(code)

    name_map, ptr_map = extract_structs(f)
    cgen = generate_allocators(name_map, ptr_map)

    # simple pointeur         : doit exister
    assert "alloc_pX(" in cgen
    # double / triple pointeur : ne doit PAS exister
    assert "alloc_ppX(" not in cgen
    assert "alloc_pppX(" not in cgen
