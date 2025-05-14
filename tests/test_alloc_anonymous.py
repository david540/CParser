import re
from pathlib import Path
from extractor import extract_structs
from allocator_gen import generate_allocators


def test_anonymous(tmp_path: Path):
    code = r"""
        typedef struct {
            long id;
        } Rec;
        typedef Rec* pRec;
    """
    f = tmp_path / "anon.c"
    f.write_text(code)

    nmap, pmap = extract_structs(f)
    cgen = generate_allocators(nmap, pmap)

    # prototypes pour alias valeur + pointeur
    assert "Rec* alloc_Rec(" in cgen
    assert "pRec alloc_pRec(" in cgen

    # pRec doit simplement faire return alloc_Rec
    assert re.search(r"return\s+alloc_Rec\(d,\s*max_d\);", cgen)
