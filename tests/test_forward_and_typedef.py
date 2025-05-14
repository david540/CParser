from extractor import extract_structs

def test_forward_and_typedef(tmp_path):
    code = r"""
        struct A;
        typedef struct A nA;
        struct A { int a; char* b; };
        typedef struct A* pA;
    """
    cfile = tmp_path / "t1.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("int", "a"), ("char*", "b")]

    # canonical name and alias
    assert name_map["struct A"] == fields
    assert name_map["nA"] == fields
    # single‑level pointer alias present
    assert ptr_map["pA"] == fields