from pathlib import Path
from extractor import extract_structs
from allocator_gen import generate_allocators


def test_unknown_field(tmp_path: Path):
    code = r"""
        struct S {
            int   n;
            char* buf;          /* pointeur vers type inconnu */
        };
    """
    f = tmp_path / "unk.c"
    f.write_text(code)

    nmap, pmap = extract_structs(f)
    cgen = generate_allocators(nmap, pmap)

    # le champ buf doit être traité via tis_alloc_safe(128)
    assert "out->buf = tis_alloc_safe(128);" in cgen
