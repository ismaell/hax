#!/usr/bin/env python3
"""Generate a man page in mdoc format from hax's sources of truth."""
import re, subprocess, os, glob, sys

SRC_ROOT = sys.argv[2] if len(sys.argv) > 2 else '.'

def fail(msg):
    print(f'gen_mdoc: {msg}', file=sys.stderr)
    sys.exit(1)

# --- Validate inputs exist ---
for rel in ('src/cli.c', 'src/config.c', 'README.md'):
    if not os.path.isfile(os.path.join(SRC_ROOT, rel)):
        fail(f'missing input: {rel}')

# --- OPTIONS from cli.c ---
src = open(os.path.join(SRC_ROOT, 'src/cli.c')).read()
try:
    start = src.index('HELP_OPTIONS[] = {')
    end = src.index('};', start) + 2
except ValueError:
    fail('HELP_OPTIONS[] not found in src/cli.c')
block = src[start:end]
options = []
for m in re.finditer(r'\{"([^"]+)"\s*,\s*((?:"[^"]*"\s*)+)\}', block):
    flags = m.group(1)
    desc = ' '.join(re.findall(r'"([^"]*)"', m.group(2)))
    desc = ' '.join(desc.split())
    if not desc:
        fail(f'empty description for option: {flags}')
    options.append((flags, desc))
if not options:
    fail('no options extracted from cli.c')

# --- ENVIRONMENT from config.c ---
src = open(os.path.join(SRC_ROOT, 'src/config.c')).read()
try:
    start = src.index('REGISTRY[] = {')
    end = src.index('};', start) + 2
except ValueError:
    fail('REGISTRY[] not found in src/config.c')
block = src[start:end]
envs = []
for m in re.finditer(r'\{\.key\s*=\s*"([^"]+)"(.*?)\},', block, re.DOTALL):
    key = m.group(1)
    body = m.group(2)
    ev = re.search(r'\.env_var\s*=\s*"([^"]+)"', body)
    if not ev:
        continue
    env_var = ev.group(1)
    desc_match = re.search(r'\.description\s*=\s*(.*)', body, re.DOTALL)
    desc_raw = desc_match.group(1) if desc_match else ''
    desc_parts = re.findall(r'"([^"]*)"', desc_raw)
    desc = ' '.join(' '.join(desc_parts).split())
    if not desc:
        fail(f'empty description for env var: {env_var}')
    envs.append((key, env_var, desc))
if not envs:
    fail('no environment variables extracted from config.c')

# --- Tagline from cli.c ---
cli_src = open(os.path.join(SRC_ROOT, 'src/cli.c')).read()
tagline_m = re.search(r'const char \*tagline = "([^"]+)"', cli_src)
if not tagline_m:
    fail('tagline not found in cli.c')
tagline = tagline_m.group(1)

# --- README man sections ---
readme = open(os.path.join(SRC_ROOT, 'README.md')).read()

def extract_section(heading):
    # Extract content between a ## heading and the next ## or ### heading (or EOF)
    pattern = re.compile(r'^## ' + re.escape(heading) + r'\s*\n(.*?)(?=^## |^### |\Z)', re.MULTILINE | re.DOTALL)
    m = pattern.search(readme)
    if not m:
        fail(f'section "{heading}" not found in README.md')
    content = m.group(1).strip()
    # Remove code fences for synopsis
    return content

# SYNOPSIS
# Extract usage line from cli.c
cli_src = open(os.path.join(SRC_ROOT, 'src/cli.c')).read()
usage_m = re.search(r'ui_wrapped_rows\("([^"]+)"', cli_src)
if not usage_m:
    fail('usage line not found in src/cli.c')
synopsis_forms = [usage_m.group(1)]

# DESCRIPTION
description = extract_section('Description')
if not description:
    fail('empty description in README.md')

# --- Collect actual file paths from code ---
code_files = set()
for path in glob.glob(os.path.join(SRC_ROOT, 'src/**/*.c'), recursive=True):
    content = open(path).read()
    for m in re.finditer(r'xdg_hax_(config|state|cache)_path\("([^"]+)"\)', content):
        kind = m.group(1)
        rel = m.group(2)
        if kind == 'config':
            full = f'~/.config/hax/{rel}'
        elif kind == 'state':
            full = f'$XDG_STATE_HOME/hax/{rel}'
        else:
            full = f'$XDG_CACHE_HOME/hax/{rel}'
        code_files.add(full)

# --- FILES from README MAN FILES section ---
files_raw = extract_section('Files')
# Parse: path line followed by indented description lines
file_entries = []
current_path = None
current_desc = []
for line in files_raw.split('\n'):
    if line.strip() == '':
        if current_path:
            file_entries.append((current_path, ' '.join(current_desc).strip()))
            current_path = None
            current_desc = []
        continue
    if not line.startswith(' ') and not line.startswith('\t'):
        if current_path:
            file_entries.append((current_path, ' '.join(current_desc).strip()))
            current_desc = []
        current_path = line.strip()
    else:
        current_desc.append(line.strip())
if current_path:
    file_entries.append((current_path, ' '.join(current_desc).strip()))
if not file_entries:
    fail('no file entries extracted from README.md')

# Validate that README lists exactly the files found in code
readme_file_paths = set(e[0].rstrip('/') for e in file_entries)
normalized_code = set(f.rstrip('/') for f in code_files)
if readme_file_paths != normalized_code:
    missing = normalized_code - readme_file_paths
    extra = readme_file_paths - normalized_code
    if missing:
        fail(f'files in code but not README MAN FILES: {missing}')
    if extra:
        fail(f'files in README MAN FILES but not code: {extra}')

# --- SEE ALSO from docs/ ---
# see_also no longer used

# --- AUTHORS from git ---
try:
    authors = subprocess.check_output(['git', 'log', '--format=%an', '--reverse'], text=True).strip().split('\n')
except subprocess.CalledProcessError:
    fail('git log failed')
seen_authors = set()
unique_authors = []
for a in authors:
    if a and a not in seen_authors:
        seen_authors.add(a)
        unique_authors.append(a)
if not unique_authors:
    fail('no authors from git log')

# --- BUILD mdoc output (line by line) ---
out_lines = []
def add(s):
    out_lines.append(s)

add('.Dd $Mdocdate$')
add('.Dt HAX 1')
add('.Os')
add('.Sh NAME')
add('.Nm hax')
add(f'.Nd {tagline}')
add('.Sh SYNOPSIS')
for i, form in enumerate(synopsis_forms):
    form = form.strip()
    if form.lower().startswith('hax '):
        form = form[4:].strip()
    elif form.lower() == 'hax':
        form = ''
    add('.Nm')
    if form:
        add(form)
    if i < len(synopsis_forms) - 1:
        add('.Pp')
add('.Sh DESCRIPTION')
for para in description.split('\n\n'):
    para = para.strip()
    if not para:
        continue
    words = para.split()
    line = ''
    for w in words:
        if len(line) + len(w) + 1 > 70:
            add(line)
            line = w
        else:
            line = (line + ' ' + w).strip()
    if line:
        add(line)
add('.Sh OPTIONS')
add('.Bl -tag -width Ds')
for flags, desc in options:
    flag_parts = []
    for f in flags.split(', '):
        f = f.lstrip('-')
        if '=' in f:
            name, arg = f.split('=', 1)
            flag_parts.append(f'Fl {name} Ns = Ns Ar {arg}')
        else:
            flag_parts.append(f'Fl {f}')
    add('.It ' + ' , '.join(flag_parts))
    add(desc)
add('.El')
add('.Sh ENVIRONMENT')
add('.Bl -tag -width Ds')
for key, env_var, desc in envs:
    add(f'.It Ev {env_var}')
    add(f'{desc} (config key: {key})')
add('.El')
add('.Sh FILES')
add('.Bl -tag -width Ds')
for full, desc in file_entries:
    add(f'.It Pa {full}')
    add(desc)
add('.El')
add('.Sh AUTHORS')
for a in unique_authors:
    add(f'.An {a}')

# --- Write output ---
if not out_lines:
    fail('no output generated')
output_path = sys.argv[1] if len(sys.argv) > 1 else '/dev/stdout'
with open(output_path, 'w') as f:
    for line in out_lines:
        f.write(line + '\n')

print(f'gen_mdoc: wrote {len(out_lines)} lines to {output_path}', file=sys.stderr)
