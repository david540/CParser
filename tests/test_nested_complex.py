from extractor import extract_structs

def test_nested_complex(tmp_path):
    code = r"""
        struct Outer;
        struct Inner { int x; };
        typedef struct Inner Inner_t;
        typedef struct Outer* pOuter;
        struct Outer {
            struct Inner in;
            double v;
        };
        typedef struct Outer** ppOuter;   // should be ignored (double ptr)

        typedef struct {
            int a;
            struct Outer* link;
        } AnonS;
        typedef AnonS* pAnonS;
    """
    f = tmp_path / "nested.c"
    f.write_text(code)

    name_map, ptr_map = extract_structs(f)

    inner_fields = [("int", "x")]
    outer_fields = [("struct Inner", "in"), ("double", "v")]
    anon_fields = [("int", "a"), ("struct Outer*", "link")]

    # Canonical + alias for Inner
    assert name_map["struct Inner"] == inner_fields
    assert name_map["Inner_t"] == inner_fields

    # Canonical for Outer
    assert name_map["struct Outer"] == outer_fields
    # Single pointer alias is present, double pointer ignored
    assert ptr_map["pOuter"] == outer_fields
    assert "ppOuter" not in ptr_map

    # Anonymous struct alias + pointer alias
    assert name_map["AnonS"] == anon_fields
    assert ptr_map["pAnonS"] == anon_fields