from extractor import extract_structs

def test_multi_pointer(tmp_path):
    code = r"""
        struct Bar { int v; };
        typedef struct Bar** ppBar;   // double pointer ➜ must be IGNORED
    """
    cfile = tmp_path / "t4.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)

    # canonical struct key must exist
    assert "struct Bar" in name_map
    # double‑pointer alias **must not be recorded**
    assert "ppBar" not in ptr_map