"""Read-only suggestions from exact staged Git blob identities, not rename guesses."""
from __future__ import annotations
from collections import Counter, defaultdict
import os
from pathlib import Path
import re
import subprocess
from .core import LedgerError, digest, extract, load_manifest, read_text, safe_path


def git_read(root, *arguments):
    # Ignore inherited Git command/config/trace overrides. These process-local
    # options do not change repository configuration or the index.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_OPTIONAL_LOCKS='0',
               GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='', GIT_TERMINAL_PROMPT='0',
               GIT_NO_REPLACE_OBJECTS='1', GIT_LITERAL_PATHSPECS='1')
    command = ['git', '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
               '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
               '-c', 'trace2.normalTarget=0', '-c', 'trace2.eventTarget=0', '-c', 'trace2.perfTarget=0',
               *arguments]
    try:
        result = subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LedgerError(f'Cannot read local Git metadata (Git must be installed): {exc}') from exc
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace').strip()
        raise LedgerError(f'Git metadata unavailable; a local working tree with an existing HEAD is required: {detail}')
    if len(result.stdout) > 8 * 1024 * 1024:
        raise LedgerError('Git metadata exceeds the 8 MiB report limit')
    return result.stdout


def staged_entries(raw):
    """Parse NUL-delimited raw diff records with rename detection disabled."""
    fields = raw.split(b'\0')
    if fields[-1] != b'':
        raise LedgerError('Unexpected non-NUL-terminated Git raw diff')
    fields.pop()
    if len(fields) % 2:
        raise LedgerError('Unexpected Git raw diff record count')
    result = []
    for index in range(0, len(fields), 2):
        header = fields[index].decode('ascii')
        match = re.fullmatch(r':([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}|[0-9a-f]{64}) ([0-9a-f]{40}|[0-9a-f]{64}) ([A-Z])', header)
        if not match:
            raise LedgerError('Unsupported Git raw diff record')
        try:
            path = fields[index + 1].decode('utf-8')
        except UnicodeDecodeError as exc:
            raise LedgerError('Git paths must be valid UTF-8 for rename suggestions') from exc
        old_mode, new_mode, old_blob, new_blob, status = match.groups()
        result.append({'path': path, 'old_mode': old_mode, 'new_mode': new_mode,
                       'old_blob': old_blob, 'new_blob': new_blob, 'status': status})
    return result


def traverses_symlink(root, name):
    """Inspect original components before the OS can normalize away alias/.. ."""
    current = root
    for part in Path(name).parts:
        if part == '.':
            continue
        current = current.parent if part == '..' else current / part
        if not current.is_relative_to(root):
            return True
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            return True
    return False


def suggest_renames(root):
    root = root.resolve()
    if '\n' in str(root) or '\r' in str(root):
        raise LedgerError('Repository/knowledge-base roots containing line breaks are unsupported')
    dependencies = load_manifest(root)
    repository = Path(git_read(root, 'rev-parse', '--show-toplevel').decode('utf-8').rstrip('\r\n')).resolve()
    if not root.is_relative_to(repository):
        raise LedgerError('Knowledge base must be inside the Git working tree')
    head = git_read(root, 'rev-parse', '--verify', 'HEAD').decode('ascii').strip()
    entries = staged_entries(git_read(root, 'diff', '--cached', '--raw', '--no-renames', '--no-relative',
                                     '--no-ext-diff', '--no-textconv', '--no-color', '--ignore-submodules=all',
                                     '--abbrev=64', '-z', head, '--'))
    regular = {'100644', '100755'}
    deleted = {entry['path']: entry['old_blob'] for entry in entries if entry['status'] == 'D' and entry['old_mode'] in regular}
    added = defaultdict(list)
    for entry in entries:
        if entry['status'] == 'A' and entry['new_mode'] in regular:
            added[entry['new_blob']].append(entry['path'])
    deleted_counts = Counter(deleted.values())
    missing, indirect = {}, set()
    for dep in dependencies:
        for field in ('note', 'source'):
            original = dep[field]
            resolved = safe_path(root, original)
            if not resolved.exists():
                logical = Path(os.path.normpath(original)).as_posix()
                if traverses_symlink(root, original) or resolved != root / logical:
                    indirect.add(original)
                missing.setdefault(original, []).append({'field': field, 'dependency': dep})
    suggestions = []
    for old_path, usages in sorted(missing.items()):
        git_path = safe_path(root, old_path).relative_to(repository).as_posix()
        blob = None if old_path in indirect else deleted.get(git_path)
        candidates, skipped = [], []
        if blob:
            for destination in sorted(added[blob]):
                try:
                    relative = (repository / destination).relative_to(root).as_posix()
                except ValueError:
                    continue  # Never expose or read files outside the chosen knowledge base.
                try:
                    if traverses_symlink(root, relative) or safe_path(root, relative) != root / relative:
                        raise LedgerError('Candidate traverses symlinks; direct regular-file paths are required')
                    content = read_text(root, relative)
                    for usage in usages:
                        if usage['field'] == 'source':
                            dep = usage['dependency']
                            extract(content, dep.get('heading'), dep.get('occurrence', 1))
                    candidates.append({'path': relative, 'staged_blob': blob, 'working_text_sha256': digest(content)})
                except LedgerError as exc:
                    skipped.append({'path': relative, 'reason': str(exc)})
        reason = 'Exact blob identity in staged deletion/addition; review every candidate' if candidates else (
            'Missing path traverses symlinks; direct regular-file paths are required' if old_path in indirect else
            'Missing path is not a staged regular-file deletion' if blob is None else
            'No readable in-root staged addition has the same blob and required sections')
        suggestions.append({'missing_path': old_path, 'usages': usages, 'candidates': candidates,
                            'ambiguous': bool(blob and (len(added[blob]) > 1 or deleted_counts[blob] > 1)),
                            'skipped_candidates': skipped, 'reason': reason})
    return {'kind': 'sourceledger-rename-suggestions', 'version': 1, 'head': head, 'suggestions': suggestions,
            'instructions': 'Suggestions are not confirmed renames. Review paths and current content, edit the manifest yourself, then check and explicitly accept new dependency identities. No files, Git metadata or baselines were changed.'}
