from extractor import extract_structs

def test_pointer_alias(tmp_path):
    code = r"""
        union pthread_attr_t
        {
            char __size[__SIZEOF_PTHREAD_ATTR_T];
            long int __align;
        };
    """
    cfile = tmp_path / "t3.c"
    cfile.write_text(code)

    name_map, ptr_map = extract_structs(cfile)
    fields = [('char', '__size'), ('long', '__align')]

    print(name_map.keys(), name_map["union pthread_attr_t"])
    assert name_map["union pthread_attr_t"] == fields
    
    assert len(name_map.keys()) == 1
    assert len(ptr_map.keys()) == 0
