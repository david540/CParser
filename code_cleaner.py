"""
Code cleaner for C files to make them compatible with pycparser.
Removes GNU extensions, complex macros, assembly code, and other features
that pycparser doesn't support.
"""

import re
from pathlib import Path
from typing import List, Set

class CodeCleaner:
    def __init__(self):
        # Patterns to remove or replace
        self.patterns = [
            # Remove assembly code
            (r'__asm__\s*\([^)]*\)', ''),
            (r'__asm__\s*volatile\s*\([^)]*\)', ''),
            
            # Remove GCC attributes
            (r'__attribute__\s*\([^)]*\)', ''),
            
            # Remove GNU C extensions
            (r'__extension__', ''),
            (r'__restrict__', ''),
            (r'__inline__', 'inline'),
            (r'__inline', 'inline'),
            (r'__const__', 'const'),
            (r'__volatile__', 'volatile'),
            
            # Remove complex macros
            (r'#define\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*\\', ''),
            (r'#define\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*{[^}]*}', ''),
            
            # Remove built-in functions
            (r'__builtin_[a-zA-Z0-9_]+', ''),
            
            # Remove typeof
            (r'typeof\s*\([^)]*\)', 'int'),
            
            # Remove complex type declarations
            (r'__signed__', 'signed'),
            (r'__unsigned__', 'unsigned'),
            
            # Remove packed attributes
            (r'__packed__', ''),
            (r'__packed', ''),
            
            # Remove aligned attributes
            (r'__aligned__\s*\([^)]*\)', ''),
            (r'__aligned\s*\([^)]*\)', ''),
            
            # Remove section attributes
            (r'__section__\s*\([^)]*\)', ''),
            (r'__section\s*\([^)]*\)', ''),
            
            # Remove weak attributes
            (r'__weak__', ''),
            (r'__weak', ''),
            
            # Remove complex bitfield declarations
            (r':\s*[0-9]+\s*__attribute__\s*\([^)]*\)', ': 1'),
        ]
        
        # Compile patterns
        self.compiled_patterns = [(re.compile(pattern), repl) for pattern, repl in self.patterns]
        
        # Keep track of processed includes to avoid duplicates
        self.processed_includes: Set[str] = set()

    def clean_file(self, input_path: Path, output_path: Path) -> None:
        """Clean a single C file and write the result to output_path."""
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Remove comments
        content = self._remove_comments(content)
        
        # Process includes
        content = self._process_includes(content, input_path.parent)
        
        # Apply all cleaning patterns
        for pattern, repl in self.compiled_patterns:
            content = pattern.sub(repl, content)
        
        # Remove empty lines and normalize whitespace
        content = self._normalize_whitespace(content)
        
        # Write cleaned content
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _remove_comments(self, content: str) -> str:
        """Remove C-style comments from the content."""
        # Remove multi-line comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Remove single-line comments
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        return content

    def _process_includes(self, content: str, base_dir: Path) -> str:
        """Process #include directives and clean included files."""
        def process_include(match):
            include_path = match.group(1)
            if include_path in self.processed_includes:
                return f'#include "{include_path}"'
            
            # Try to find the include file
            include_file = base_dir / include_path
            if not include_file.exists():
                return f'#include "{include_path}"'
            
            # Clean the included file
            output_file = include_file.with_suffix('.clean.c')
            self.clean_file(include_file, output_file)
            self.processed_includes.add(include_path)
            
            return f'#include "{output_file.name}"'
        
        return re.sub(r'#include\s*["<]([^">]+)[">]', process_include, content)

    def _normalize_whitespace(self, content: str) -> str:
        """Remove empty lines and normalize whitespace."""
        # Replace multiple newlines with single newline
        content = re.sub(r'\n\s*\n', '\n\n', content)
        # Remove trailing whitespace
        content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
        return content

def clean_code(input_path: str | Path, output_path: str | Path) -> None:
    """Clean a C file and write the result to output_path."""
    cleaner = CodeCleaner()
    cleaner.clean_file(Path(input_path), Path(output_path))

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: code_cleaner.py input.c output.c")
        sys.exit(1)
    clean_code(sys.argv[1], sys.argv[2]) 