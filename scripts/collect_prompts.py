#!/usr/bin/env python3
import os
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output_file = root / "prompts_all.txt"
text_exts = {'.py', '.md', '.mdx', '.ts', '.tsx', '.js', '.jsx', '.json', '.yaml', '.yml', '.txt', '.html', '.cfg', '.ini'}

found_files = []
prompt_blocks = 0

def extract_triple_quoted(text):
    pattern = re.compile(r'(["\']{3})(.*?prompt.*?)(\1)', re.S | re.I)
    return [m.group(2).strip() for m in pattern.finditer(text)]

with open(output_file, 'w', encoding='utf-8') as out:
    out.write('Collected prompts and prompt-containing snippets from repository\n')
    out.write('=\n\n')
    for dirpath, dirnames, filenames in os.walk(root):
        # skip common binary or virtual env dirs
        skip_dirs = {'node_modules', '.git', '.venv', 'venv', 'dist', 'build', 'target', '__pycache__'}
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in text_exts and not fname.lower().endswith('.prompt.md'):
                continue
            try:
                text = fpath.read_text(encoding='utf-8')
            except Exception:
                try:
                    text = fpath.read_text(encoding='latin-1')
                except Exception:
                    continue
            if re.search(r'prompt', text, re.I):
                found_files.append(str(fpath.relative_to(root)))
                out.write(f'File: {fpath.relative_to(root)}\n')
                out.write('-' * 60 + '\n')
                # for python-like files, try to extract triple-quoted strings that contain 'prompt'
                if fpath.suffix.lower() in {'.py', '.ts', '.js', '.jsx', '.tsx'}:
                    blocks = extract_triple_quoted(text)
                    if blocks:
                        for b in blocks:
                            out.write(b + '\n\n')
                            prompt_blocks += 1
                        out.write('\n')
                    else:
                        # fallback: show matching lines with context
                        lines = text.splitlines()
                        for i, line in enumerate(lines):
                            if re.search(r'prompt', line, re.I):
                                start = max(0, i-3)
                                end = min(len(lines), i+4)
                                snippet = '\n'.join(lines[start:end])
                                out.write(snippet + '\n')
                                out.write('...\n')
                else:
                    # for md/json/yaml and others: include whole file if it's markdown or show snippets
                    if fpath.suffix.lower() in {'.md', '.mdx'}:
                        out.write(text + '\n')
                        prompt_blocks += 1
                    else:
                        lines = text.splitlines()
                        for i, line in enumerate(lines):
                            if re.search(r'prompt', line, re.I):
                                start = max(0, i-3)
                                end = min(len(lines), i+4)
                                snippet = '\n'.join(lines[start:end])
                                out.write(snippet + '\n')
                                out.write('...\n')
                out.write('\n\n')

    out.write('Summary:\n')
    out.write(f'Files containing "prompt": {len(found_files)}\n')
    out.write(f'Extracted prompt-like blocks (approx): {prompt_blocks}\n')

print(f'Wrote {output_file}')
