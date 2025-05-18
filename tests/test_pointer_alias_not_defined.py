from extractor import extract_structs

def test_pointer_alias(tmp_path):
    code = r"""
        struct Foo;
        typedef struct Foo Foo;
        typedef struct Foo* pFoo;
    """
    cfile = tmp_path / "t3.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("double", "x")]

    
    assert len(name_map.keys()) == 0
    assert len(ptr_map.keys()) == 0