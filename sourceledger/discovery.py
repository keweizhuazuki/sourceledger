"""Read-only, deliberately bounded Markdown link discovery.

This is not a CommonMark parser. Unsupported links remain visible as warnings;
only successfully resolved local UTF-8 sources become review candidates.
"""
from __future__ import annotations
import html
from html.entities import html5
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .core import LedgerError, dependency_key, digest, read_text, safe_path, sections


PUNCTUATION = r'!"#$%&\'()*+,-./:;<=>?@[\]^_`{|}~'


def unescape(value):
    # Decode escaped punctuation and complete entities in one pass. An escaped
    # ampersand must not be reinterpreted as an entity after removing its slash.
    pattern = r"\\([" + re.escape(PUNCTUATION) + r"])|&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});"
    def replace(match):
        if match[1] is not None:
            return match[1]
        entity = match[0]
        return html.unescape(entity) if entity.startswith('&#') or entity[1:] in html5 else entity
    return re.sub(pattern, replace, value)


def strip_containers(line):
    previous = None
    while previous != line:
        previous = line
        line = re.sub(r'^ {0,3}>[ \t]?', '', line)
        line = re.sub(r'^ {0,3}(?:[-*+]|[0-9]+[.)])[ \t]+', '', line)
    return line


def escaped_at(line, index):
    count = 0
    while index > 0 and line[index - 1] == '\\':
        count += 1
        index -= 1
    return count % 2 == 1


def visible_lines(text):
    """Mask code/comments and conservatively skip raw HTML blocks."""
    fence, comment, html_block, html_end = None, False, False, None
    inline_run, number = None, 0
    for number, original in enumerate(text.splitlines(), 1):
        line = strip_containers(original)
        fence_line = re.sub(r'^(?: {0,3}>[ \t]?)+', '', line)
        fence_line = re.sub(r'^ {0,3}(?:[-*+]|[0-9]+[.)])[ \t]+', '', fence_line)
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', fence_line)
        if fence:
            if marker:
                run, tail = marker.groups()
                if run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                    fence = None
            continue
        if html_end:
            if re.search(html_end, line, re.IGNORECASE):
                html_end = None
            continue
        if html_block:
            if not line.strip():
                html_block = False
            else:
                continue
        if comment:
            end = line.find('-->')
            if end == -1:
                continue
            line = ' ' * (end + 3) + line[end + 3:]
            comment = False
        while '<!--' in line:
            start = line.index('<!--')
            end = line.find('-->', start + 4)
            if end == -1:
                line = line[:start]
                comment = True
                break
            line = line[:start] + ' ' * (end + 3 - start) + line[end + 3:]
        # Recompute after masking comments so examples inside comments cannot
        # start a fence that consumes following prose.
        fence_line = re.sub(r'^(?: {0,3}>[ \t]?)+', '', line)
        fence_line = re.sub(r'^ {0,3}(?:[-*+]|[0-9]+[.)])[ \t]+', '', fence_line)
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', fence_line)
        if marker:
            run, tail = marker.groups()
            if run[0] != '`' or '`' not in tail:
                fence = run
            continue
        indent = re.match(r'^[ \t]*', line)[0]
        if len(indent.expandtabs(4)) >= 4:
            continue
        raw = re.match(r'^ {0,3}<(script|pre|style|textarea)(?:\s|>)', line, re.IGNORECASE)
        if raw:
            html_end = r'</' + raw[1] + r'\s*>'
        elif re.match(r'^ {0,3}<\?', line):
            html_end = r'\?>'
        elif re.match(r'^ {0,3}<!\[CDATA\[', line):
            html_end = r'\]\]>'
        elif re.match(r'^ {0,3}<![A-Z]', line):
            html_end = '>'
        elif re.match(r'^ {0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s|>|/)', line):
            html_block = True
        if html_end or html_block:
            if html_end and re.search(html_end, line, re.IGNORECASE):
                html_end = None
            yield number, '', 'Raw HTML block skipped; discovery is not a full Markdown parser'
            continue
        if re.search(r'</?[A-Za-z][A-Za-z0-9-]*(?:\s|>|/)|<\?|<!', line):
            yield number, '', 'Inline HTML skipped; configure any intended sources manually'
            continue
        output, index = [], 0
        while index < len(line):
            if line[index] == '`' and (inline_run is not None or not escaped_at(line, index)):
                end = index
                while end < len(line) and line[end] == '`':
                    end += 1
                run = end - index
                if inline_run is None:
                    inline_run = run
                elif inline_run == run:
                    inline_run = None
                output.append(' ' * run)
                index = end
            else:
                output.append(' ' if inline_run else line[index])
                index += 1
        yield number, ''.join(output), None
    if inline_run or comment or fence or html_end:
        yield number, '', 'Unclosed code/comment/HTML delimiter; inspect skipped content manually'


def destination(line, start):
    """Parse a single-line inline-link destination and optional quoted title."""
    index = start
    while index < len(line) and line[index].isspace():
        index += 1
    if index >= len(line):
        raise LedgerError('Multiline or unfinished inline link is unsupported')
    if line[index] == '<':
        end = index + 1
        while end < len(line) and (line[end] != '>' or line[end - 1] == '\\'):
            end += 1
        if end >= len(line):
            raise LedgerError('Unclosed angle-bracket destination')
        value, index = line[index + 1:end], end + 1
        if '<' in value:
            raise LedgerError('Nested angle brackets are unsupported')
    else:
        begin, depth = index, 0
        while index < len(line):
            char = line[index]
            if char == '\\' and index + 1 < len(line):
                index += 2
                continue
            if char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
            elif char.isspace():
                break
            index += 1
        value = line[begin:index]
        if '<' in value or '>' in value:
            raise LedgerError('Bare destinations cannot contain angle brackets')
        if depth:
            raise LedgerError('Unbalanced destination parentheses')
    tail = line[index:]
    match = re.match(r'''(?:\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*|\s*)\)''', tail)
    if not match:
        raise LedgerError('Unsupported title or multiline inline link')
    return unescape(value), index + match.end()


# Deliberately literal punctuation only: no general Markdown inline renderer.
_ANCHOR_PUNCTUATION = ".,;:!?\"'()/"
_ANCHOR_REMOVE = str.maketrans('', '', _ANCHOR_PUNCTUATION)


def literal_heading_slug(title):
    if any(not (char.isalnum() or char in " _-" + _ANCHOR_PUNCTUATION) for char in title):
        raise LedgerError('Fragment requires manual review: target heading contains unsupported markup or punctuation; use headings and configure explicitly')
    for run in re.finditer(r'_+', title):
        if (run.start() == 0 or run.end() == len(title)
                or not title[run.start() - 1].isalnum() or not title[run.end()].isalnum()):
            raise LedgerError('Fragment requires manual review: underscores may be emphasis markup; only intraword underscores are supported')
    if re.search(r':[A-Za-z0-9_+\-]+:', title):
        raise LedgerError('Fragment requires manual review: emoji shortcodes may change rendered heading text')
    base = title.lower().translate(_ANCHOR_REMOVE).replace(' ', '-')
    if title and not base:
        raise LedgerError('Fragment requires manual review: punctuation-only heading has an unsupported empty anchor')
    return base


def fragment_heading(content, fragment):
    if re.search(r'<!|<\?|</?[A-Za-z]|^ {0,3}>|^ {0,3}(?:[-*+]|[0-9]+[.)])(?:[ \t]+|$)|^ {0,3}(?:=+|-+)\s*$', content, re.MULTILINE):
        raise LedgerError('Fragment requires manual review: HTML, container or Setext syntax can change anchor numbering')
    headings = sections(content)
    # Validate every heading before resolving any candidate: an unsupported
    # earlier/later heading can collide with the rendered slug.
    bases = [literal_heading_slug(item['heading']) for item in headings]
    used = set()
    for item, base in zip(headings, bases):
        slug, suffix = base, 0
        while slug in used:
            suffix += 1
            slug = f'{base}-{suffix}'
        used.add(slug)
        if slug == fragment:
            return {'heading': item['heading'], 'occurrence': item['occurrence']}
    raise LedgerError(f'Unresolved fragment #{fragment}; no supported literal-ATX anchor matches')


def resolve_link(root, note, raw):
    if re.search(r'%(?![0-9A-Fa-f]{2})', raw):
        raise LedgerError('Malformed percent escape in destination')
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise LedgerError('External URL or URI scheme skipped; discovery never fetches network sources')
    if '?' in raw:
        raise LedgerError('Query-string destinations are unsupported')
    path = unquote(parsed.path, encoding='utf-8', errors='strict')
    fragment = unquote(parsed.fragment, encoding='utf-8', errors='strict')
    if not path:
        raise LedgerError('Same-document navigation skipped; it is not an external source dependency')
    if Path(path).is_absolute() or re.match(r'^[A-Za-z]:', path):
        raise LedgerError('Absolute source path skipped')
    source = safe_path(root, (Path(note).parent / path).as_posix())
    source_name = source.relative_to(root.resolve()).as_posix()
    if source == safe_path(root, note):
        raise LedgerError('Same-document navigation skipped; it is not an external source dependency')
    content = read_text(root, source_name)
    dep = {'note': note, 'source': source_name}
    if fragment:
        dep.update(fragment_heading(content, fragment))
    return dep, digest(content)


def nested_labels(line):
    depth, escaped = 0, False
    for char in line:
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '[':
            depth += 1
            if depth > 1:
                return True
        elif char == ']':
            depth = max(0, depth - 1)
    return False


def discover(root, notes):
    candidates, skipped, indexes = [], [], {}
    for requested in dict.fromkeys(notes):
        safe_path(root, requested)  # validate resolved target without changing the link's lexical base
        note = Path(os.path.normpath(requested)).as_posix()
        text = read_text(root, note)
        for number, line, warning in visible_lines(text):
            if warning:
                skipped.append({'note': note, 'line': number, 'destination': None, 'reason': warning})
                continue
            if re.search(r'\[\[|\]\[|^ {0,3}\[[^]]+\]:', line):
                skipped.append({'note': note, 'line': number, 'destination': None, 'reason': 'Wiki/reference-link syntax requires manual configuration'})
                continue
            if nested_labels(line):
                skipped.append({'note': note, 'line': number, 'destination': None, 'reason': 'Nested link/image labels require manual configuration'})
                continue
            cursor = 0
            for match in re.finditer(r'(?<!\\)(!?)\[(?:\\.|[^\[\]\\])*\]\(', line):
                if match.start() < cursor:
                    continue
                raw = line[match.start():]
                try:
                    raw, cursor = destination(line, match.end())
                    if match[1]:
                        raise LedgerError('Image link skipped; configure a text source explicitly if needed')
                    dep, source_hash = resolve_link(root, note, raw)
                    key = dependency_key(dep)
                    location = {'line': number, 'destination': raw}
                    if key in indexes:
                        candidates[indexes[key]]['links'].append(location)
                    else:
                        indexes[key] = len(candidates)
                        candidates.append({'dependency': dep, 'links': [location], 'note_hash': digest(text), 'source_hash': source_hash})
                except (LedgerError, OSError, ValueError, UnicodeError) as exc:
                    skipped.append({'note': note, 'line': number, 'destination': raw, 'reason': str(exc)})
    return {'kind': 'sourceledger-discovery', 'version': 1, 'candidates': candidates, 'skipped': skipped,
            'instructions': 'Review candidates, then copy selected dependency objects into sourceledger.json. This proposal is not a manifest. Run check and explicitly accept after reviewing source content.'}
