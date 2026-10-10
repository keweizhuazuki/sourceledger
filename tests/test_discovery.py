import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from sourceledger.core import LedgerError, accept, check, history
from sourceledger.discovery import discover
from sourceledger.cli import main


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'notes').mkdir()
        (self.root / 'sources').mkdir()
        self.write('sources/policy.md', '# Policy\n## Access\n30 days\n## Access\n14 days\n')

    def write(self, name, content):
        (self.root / name).write_text(content, encoding='utf-8')

    def scan(self, text):
        self.write('notes/start.md', text)
        return discover(self.root, ['notes/start.md'])

    def test_checked_in_anchor_example_is_read_only_and_reviewable(self):
        root = Path(__file__).resolve().parents[1] / 'examples/discovery'
        report = discover(root, ['anchor-note.md'])
        self.assertEqual(len(report['candidates']), 8)
        self.assertEqual(len(report['skipped']), 2)
        self.assertFalse((root / '.sourceledger').exists())
        self.assertEqual(report['candidates'][6]['dependency']['occurrence'], 2)

    def test_literal_punctuation_heading_fragments_preserve_raw_titles(self):
        examples = [('Install (Linux/macOS)', 'install-linuxmacos'),
                    ("What's new?", 'whats-new'), ('Version 2.0', 'version-20'),
                    ('FAQ: setup!', 'faq-setup'), ('Say "hello", please; now.', 'say-hello-please-now')]
        self.write('sources/readme.md', '\n'.join('## ' + title + '\nDetails.' for title, _ in examples))
        report = self.scan('\n'.join(f'[section](../sources/readme.md#{slug})' for _, slug in examples))
        self.assertEqual([row['dependency']['heading'] for row in report['candidates']], [title for title, _ in examples])
        self.assertEqual(report['skipped'], [])
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_punctuation_slug_collisions_keep_exact_occurrences(self):
        self.write('sources/collisions.md', '## FAQ!\nfirst\n## FAQ\nsecond\n## FAQ-1\nthird\n## FAQ!\nfourth\n')
        report = self.scan('[a](../sources/collisions.md#faq) [b](../sources/collisions.md#faq-1) [c](../sources/collisions.md#faq-1-1) [d](../sources/collisions.md#faq-2)')
        self.assertEqual([(row['dependency']['heading'], row['dependency']['occurrence']) for row in report['candidates']], [('FAQ!', 1), ('FAQ', 1), ('FAQ-1', 1), ('FAQ!', 2)])
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [row['dependency'] for row in report['candidates']]}))
        checked = check(self.root)
        self.assertEqual(checked['summary']['new'], 4)
        accept(self.root, checked['review_token'])
        self.assertEqual(check(self.root)['summary']['current'], 4)

    def test_intraword_underscores_are_literal_but_emphasis_is_rejected(self):
        for title in ['api_key', 'api__key', '版本_2']:
            with self.subTest(title=title):
                self.write('sources/underscores.md', '## ' + title + '\nDetails')
                report = self.scan(f'[a](../sources/underscores.md#{title.lower()})')
                self.assertEqual(report['candidates'][0]['dependency']['heading'], title)
        for title in ['_Access_', '__Access__', 'Read _Access_', 'Access_', '_Access', 'api_-key']:
            with self.subTest(title=title):
                self.write('sources/underscores.md', '## ' + title + '\nDetails')
                report = self.scan('[a](../sources/underscores.md#_access_) [b](../sources/underscores.md#access)')
                self.assertEqual(report['candidates'], [])
                self.assertTrue(all('underscores may be emphasis' in row['reason'] for row in report['skipped']))

    def test_unsupported_heading_anywhere_prevents_guessed_numbering(self):
        for unsupported in ['_FAQ_', '**FAQ**', '`FAQ`', '[FAQ](somewhere.md)', 'FAQ &amp; answers', 'FAQ\\!', ':warning: FAQ']:
            with self.subTest(unsupported=unsupported):
                self.write('sources/mixed.md', '## FAQ!\nfirst\n## ' + unsupported + '\nsecond\n')
                report = self.scan('[a](../sources/mixed.md#faq)')
                self.assertEqual(report['candidates'], [])
                self.assertIn('manual review', report['skipped'][0]['reason'])
                # Whole-file dependencies do not require anchor interpretation.
                self.assertEqual(len(self.scan('[all](../sources/mixed.md)')['candidates']), 1)

    def test_nonascii_punctuation_and_punctuation_only_headings_are_skipped(self):
        for title in ['What’s new?', 'FAQ：设置', 'A—B', '“FAQ”', '!!!']:
            with self.subTest(title=title):
                self.write('sources/rich.md', '## ' + title + '\nDetails')
                report = self.scan('[a](../sources/rich.md#faq)')
                self.assertEqual(report['candidates'], [])
                self.assertIn('manual review', report['skipped'][0]['reason'])

    def test_raw_script_and_mixed_indent_code_never_become_candidates(self):
        report = self.scan('<script>\n\n[a](../sources/policy.md)\n</script>\n\n \t[a](../sources/policy.md)')
        self.assertEqual(report['candidates'], [])

    def test_comment_and_setext_headings_cannot_shift_fragment_mapping(self):
        for content in ('<!--\n# Access\n-->\n# Access\nreal', 'Access\n======\n# Access\nreal'):
            self.write('sources/ambiguous.md', content)
            report = self.scan('[a](../sources/ambiguous.md#access)')
            self.assertEqual(report['candidates'], [])
            self.assertIn('manual review', report['skipped'][0]['reason'])

    def test_container_tilde_fences_and_nested_image_labels_are_skipped(self):
        for text in ('> ~~~\n> [a](../sources/policy.md)\n> ~~~', '- ~~~\n  [a](../sources/policy.md)\n  ~~~', '![outer [nested](../sources/policy.md)](missing.png)'):
            self.assertEqual(self.scan(text)['candidates'], [])

    def test_symlink_note_preserves_lexical_link_base_and_identity(self):
        self.write('sources/original.md', '[local](source.md)')
        self.write('sources/source.md', 'Wrong base')
        self.write('notes/source.md', 'Correct lexical base')
        try:
            (self.root / 'notes/alias.md').symlink_to(self.root / 'sources/original.md')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        report = discover(self.root, ['notes/alias.md'])
        self.assertEqual(report['candidates'][0]['dependency'], {'note': 'notes/alias.md', 'source': 'notes/source.md'})

    def test_entity_decoding_preserves_literal_ampersands_and_escapes(self):
        for name in ('a&notfile.md', 'a&notit;.md', 'a&b.md', 'a&amp;b.md'):
            self.write('sources/' + name, 'Text')
        report = self.scan('[one](../sources/a&notfile.md) [two](../sources/a&notit;.md) [three](../sources/a&amp;b.md) [four](../sources/a\\&amp;b.md)')
        self.assertEqual([row['dependency']['source'] for row in report['candidates']], ['sources/a&notfile.md', 'sources/a&notit;.md', 'sources/a&b.md', 'sources/a&amp;b.md'])

    def test_symlink_loop_is_skipped_without_aborting_report(self):
        try:
            (self.root / 'sources/loop.md').symlink_to('loop.md')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        report = self.scan('[loop](../sources/loop.md) [good](../sources/policy.md)')
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(len(report['skipped']), 1)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes unavailable')
    def test_named_pipe_is_rejected_before_opening(self):
        os.mkfifo(self.root / 'sources/pipe')
        report = self.scan('[pipe](../sources/pipe)')
        self.assertEqual(report['candidates'], [])
        self.assertIn('regular', report['skipped'][0]['reason'])

    def test_cdata_and_processing_instruction_blocks_are_skipped(self):
        for opening, closing in (('<![CDATA[', ']]>'), ('<?processing', '?>')):
            report = self.scan(f'{opening}\n\n[a](../sources/policy.md)\n{closing}\n\n[real](../sources/policy.md)')
            self.assertEqual(len(report['candidates']), 1)
            self.assertEqual(len(report['candidates'][0]['links']), 1)
            self.assertEqual(report['candidates'][0]['links'][0]['line'], 6)

    def test_list_containers_cannot_shift_fragment_identity(self):
        for content in ('-  # Access\n  list\n\n# Access\nreal', '- ~~~\n  # Access\n  fake\n  ~~~\n\n# Access\nreal'):
            self.write('sources/container.md', content)
            report = self.scan('[a](../sources/container.md#access)')
            self.assertEqual(report['candidates'], [])
            self.assertIn('manual review', report['skipped'][0]['reason'])

    def test_symlink_self_navigation_is_not_a_dependency(self):
        self.write('notes/real.md', '[self](alias.md)')
        try:
            (self.root / 'notes/alias.md').symlink_to(self.root / 'notes/real.md')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        report = discover(self.root, ['notes/alias.md'])
        self.assertEqual(report['candidates'], [])
        self.assertIn('Same-document', report['skipped'][0]['reason'])

    def test_blockquoted_html_and_escaped_backtick_parity_are_masked(self):
        text = '> <script>\n> [fake](../sources/policy.md)\n> </script>'
        self.assertEqual(self.scan(text)['candidates'], [])
        text = r'\\`[fake](../sources/policy.md)`'
        self.assertEqual(self.scan(text)['candidates'], [])
        text = r'`code \` [real](../sources/policy.md)'
        self.assertEqual(len(self.scan(text)['candidates']), 1)

    def test_relative_paths_duplicate_fragments_and_deduplication(self):
        report = self.scan('[a](../sources/policy.md#access-1)\n[again](../sources/policy.md#access-1)')
        self.assertEqual(len(report['candidates']), 1)
        row = report['candidates'][0]
        self.assertEqual(row['dependency'], {'note': 'notes/start.md', 'source': 'sources/policy.md', 'heading': 'Access', 'occurrence': 2})
        self.assertEqual([link['line'] for link in row['links']], [1, 2])
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_percent_encoded_unicode_spaces_and_quoted_title(self):
        self.write('sources/访问 policy.md', '## 访问 设置\nText')
        report = self.scan('[policy](../sources/%E8%AE%BF%E9%97%AE%20policy.md#%E8%AE%BF%E9%97%AE-%E8%AE%BE%E7%BD%AE "title")')
        self.assertEqual(report['candidates'][0]['dependency']['heading'], '访问 设置')
        self.assertEqual(report['skipped'], [])

    def test_angle_destination_and_balanced_or_escaped_parentheses(self):
        self.write('sources/policy (old).md', 'Old')
        report = self.scan('[one](<../sources/policy (old).md>) [two](../sources/policy%20(old).md) [three](../sources/policy%20\\(old\\).md)')
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(len(report['candidates'][0]['links']), 3)

    def test_network_schemes_queries_and_images_are_skipped(self):
        report = self.scan('[web](https://example.com/policy) [mail](mailto:a@example.com) [share](//server/policy) [query](../sources/policy.md?v=2) ![image](../sources/policy.md)')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(len(report['skipped']), 5)

    def test_code_comments_and_raw_html_are_not_candidates(self):
        link = '[a](../sources/policy.md)'
        report = self.scan(f'```md\n<!--\n{link}\n```\n`{link}`\n    {link}\n<!-- {link} -->\n<div>\n{link}\n</div>\n\n{link}')
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(len(report['candidates'][0]['links']), 1)
        self.assertIn('Raw HTML', report['skipped'][0]['reason'])

    def test_reference_wiki_and_multiline_destinations_report_limits(self):
        report = self.scan('[policy][ref]\n[ref]: ../sources/policy.md\n[[policy]]\n[unfinished](\n../sources/policy.md)')
        self.assertEqual(report['candidates'], [])
        self.assertGreaterEqual(len(report['skipped']), 4)

    def test_missing_file_fragment_non_plain_headings_and_binary(self):
        self.write('sources/rich.md', '## **Access**\nText')
        (self.root / 'sources/binary.dat').write_bytes(b'\xff\xfe')
        report = self.scan('[missing](missing.md) [fragment](../sources/policy.md#missing) [rich](../sources/rich.md#access) [binary](../sources/binary.dat)')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(len(report['skipped']), 4)

    def test_traversal_absolute_paths_and_encoded_escape_rejected(self):
        report = self.scan('[outside](../../outside.md) [absolute](/etc/passwd) [encoded](%2fetc%2fpasswd) [escape](%2e%2e/%2e%2e/outside.md)')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(len(report['skipped']), 4)

    def test_external_symlink_is_rejected(self):
        try:
            (self.root / 'sources/escape').symlink_to(self.root.parent, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        report = self.scan('[escape](../sources/escape/outside.md)')
        self.assertEqual(report['candidates'], [])
        self.assertIn('escapes', report['skipped'][0]['reason'])

    def test_same_document_navigation_is_not_source_dependency(self):
        report = self.scan('# Heading\n[local](#heading) [explicit](start.md#heading)')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(len(report['skipped']), 2)

    def test_bad_percent_encoding_and_nul_are_reported(self):
        report = self.scan('[bad](bad%ZZ.md) [nul](%00.md) [utf8](%FF.md)')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(len(report['skipped']), 3)

    def test_duplicate_slug_collisions_are_deterministic(self):
        self.write('sources/collisions.md', '# A\none\n# A\ntwo\n# A-1\nthree\n')
        report = self.scan('[a](../sources/collisions.md#a-1-1)')
        self.assertEqual(report['candidates'][0]['dependency']['heading'], 'A-1')

    def test_discovery_proposal_cannot_be_used_as_manifest(self):
        report = self.scan('[a](../sources/policy.md#access)')
        self.write('sourceledger.json', json.dumps(report))
        with self.assertRaises(LedgerError):
            check(self.root)

    def test_reviewed_candidates_can_be_tracked_without_autoacceptance(self):
        report = self.scan('[a](../sources/policy.md#access)')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [row['dependency'] for row in report['candidates']]}))
        self.assertEqual(check(self.root)['summary']['new'], 1)
        self.assertEqual(history(self.root)['batches'], [])
        accept(self.root, check(self.root)['review_token'])
        token = check(self.root)['review_token']
        before = history(self.root)
        discover(self.root, ['notes/start.md'])
        self.assertEqual(history(self.root), before)
        self.assertEqual(check(self.root)['review_token'], token)

    def test_cli_output_is_separate_and_never_overwritten(self):
        self.write('notes/start.md', '[a](../sources/policy.md)')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = ['--root', str(self.root), 'discover', 'notes/start.md', '--format', 'json']
            self.assertEqual(main(args + ['--output', str(self.root / 'sourceledger.json')]), 2)
            self.assertFalse((self.root / 'sourceledger.json').exists())
            proposal = self.root / 'proposal.json'
            self.assertEqual(main(args + ['--output', str(proposal)]), 0)
            self.assertEqual(main(args + ['--output', str(proposal)]), 2)
            self.assertEqual(json.loads(proposal.read_text())['kind'], 'sourceledger-discovery')
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_missing_requested_note_is_an_error(self):
        with self.assertRaises(LedgerError):
            discover(self.root, ['missing.md'])

    def test_unclosed_code_delimiter_has_warning(self):
        report = self.scan('`unclosed\n[a](../sources/policy.md)')
        self.assertEqual(report['candidates'], [])
        self.assertIn('Unclosed', report['skipped'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
