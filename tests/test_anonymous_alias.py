from extractor import extract_structs

def test_anonymous_alias(tmp_path):
    code = r"""
        typedef struct {
            long id;
        }  Rec;
        typedef struct {
            long id;
        }* pRec;
    """
    cfile = tmp_path / "t2.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [("long", "id")]

    # only alias names (no canonical struct key for anonymous)
    assert name_map["Rec"] == fields
    assert ptr_map["pRec"] == fields
    assert "struct Rec" not in name_map
    assert "struct Rec" not in ptr_map
    assert len(name_map.keys()) == 1
    assert len(ptr_map.keys()) == 1