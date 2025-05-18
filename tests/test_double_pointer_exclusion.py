from extractor import extract_structs

def test_double_pointer_exclusion(tmp_path):
    code = r"""
        struct X { int k; };
        typedef struct X* pX;     // single pointer – keep
        typedef struct X** ppX;   // double pointer – skip
        typedef struct X*** pppX; // triple pointer – skip
    """
    cfile = tmp_path / "dp.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("int", "k")]

    assert name_map["struct X"] == fields
    assert ptr_map["pX"] == fields
    assert "ppX" not in ptr_map
    assert "pppX" not in ptr_map
    assert len(name_map.keys()) == 1
    assert len(ptr_map.keys()) == 1