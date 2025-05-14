from extractor import extract_structs

def test_order_independent(tmp_path):
    code = r"""
        typedef struct Baz Baz_t;
        typedef struct Baz* pBaz;
        struct Baz { char c; };
    """
    cfile = tmp_path / "t5.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("char", "c")]

    # both canonical and alias names
    assert name_map["struct Baz"] == fields
    assert name_map["Baz_t"] == fields
    # single pointer present
    assert ptr_map["pBaz"] == fields