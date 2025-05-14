from extractor import extract_structs

def test_pointer_alias(tmp_path):
    code = r"""
        struct Foo { double x; };
        typedef struct Foo* pFoo;
    """
    cfile = tmp_path / "t3.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("double", "x")]

    assert name_map["struct Foo"] == fields
    assert ptr_map["pFoo"] == fields