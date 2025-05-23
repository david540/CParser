from typing import List, Dict, Tuple
from allocator_gen import clean_key
from extractor import Fields
from typing import Dict, List, Tuple

def generate_main_file(
    functions: Dict[tuple[str, str], list[tuple[str, str]]],
    nm:Dict[str, Fields],
    pm:Dict[str, Fields]
) -> str:
    """
    Generates a main function that calls all functions in 'functions',
    initializing their parameters appropriately.
    """
    output = []
    output.append('int main(void) {')

    for ret_type, func_name in functions.keys():
        params = functions[(ret_type, func_name)]
        if func_name == 'main': continue
        output.append('    if(rand()){')  # New scope for each function
        param_names = []
        for (var_type, var_name) in params:
            clean_type = var_type.replace('const ', '').strip()
            struct_name = clean_key(clean_type)
            param_names.append(var_name)
            if '*' in clean_type:
                if struct_name in nm:
                    output.append(f'        {clean_type} {var_name} = alloc_{struct_name}(0, 5);')
                elif struct_name not in pm:
                    output.append(f'        {clean_type} {var_name} = malloc(32);')
                    output.append(f'        auto_make_unknown({var_name}, 32);')
            else:
                if struct_name in nm:
                    output.append(f'        {clean_type} {var_name};')
                    output.append(f'        {var_name} = *alloc_{struct_name}(0, 5);')
                elif struct_name in pm:
                    output.append(f'        {clean_type} {var_name};')
                    output.append(f'        {var_name} = alloc_{struct_name}(0, 5);')
                elif struct_name == 'bool':
                    output.append(f'        {clean_type} {var_name};')
                    output.append(f'        {var_name} = tis_nondet(0, 1);')
                else:
                    output.append(f'        {clean_type} {var_name};')
                    output.append(f'        auto_make_unknown(&{var_name}, sizeof({clean_type}));')

        param_str = ', '.join(param_names)
        output.append(f'        {func_name}({param_str});')
        output.append('    }\n')

    output.append('    return 0;')
    output.append('}')

    return '\n'.join(output)
