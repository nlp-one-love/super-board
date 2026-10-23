#!/usr/bin/env python3
"""Installer lifecycle tests confined to self-created Git sandboxes in /tmp."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package', ROOT / 'scripts/super-board-package.py')
package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='super-board-package-test-'))
        self.source, self.target = self.temp / 'source', self.temp / 'target'
        self.source.mkdir(); self.target.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.target)], check=True)
        for relative, content in {'VERSION': '3.1.2-gitea.1\n', 'LICENSE': 'MIT\n',
            'skills/super-board/SKILL.md': 'test skill\n',
            'skills/super-board/references/agents-md-block.md': 'managed rules\n',
            'scripts/example.py': 'print("first")\n'}.items():
            p = self.source / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

    def install(self):
        plan, manifest, content = package.make_plan(self.target, self.source, 'codex')
        return package.apply(self.target, plan, manifest, content)

    def test_install_repeat_no_nested_git_and_internal_alias(self):
        self.install(); plan, _, _ = package.make_plan(self.target, self.source, 'codex')
        self.assertEqual(plan['changes'], []); self.assertEqual(plan['conflicts'], [])
        self.assertEqual((self.target / '.claude/bin/example.py').resolve(), self.target / '.agents/bin/example.py')
        self.assertFalse(list((self.target / '.agents').rglob('.git')))

    def test_local_edit_conflicts_before_first_write(self):
        self.install(); p = self.target / '.agents/bin/example.py'; p.write_text('my changes\n')
        (self.source / 'scripts/example.py').write_text('new upstream\n')
        plan, manifest, content = package.make_plan(self.target, self.source, 'codex')
        self.assertTrue(plan['conflicts'])
        with self.assertRaises(package.Conflict):
            package.apply(self.target, plan, manifest, content)
        self.assertEqual(p.read_text(), 'my changes\n')

    def test_upgrade_and_rollback(self):
        self.install(); (self.source / 'scripts/example.py').write_text('print("second")\n')
        update = self.install()
        self.assertIn('second', (self.target / '.agents/bin/example.py').read_text())
        package.rollback(self.target, update['backup'], False)
        self.assertIn('first', (self.target / '.agents/bin/example.py').read_text())

    def test_rollback_preserves_new_user_edit(self):
        self.install(); (self.source / 'scripts/example.py').write_text('second\n'); update = self.install()
        p = self.target / '.agents/bin/example.py'; p.write_text('user\n')
        self.assertTrue(package.rollback(self.target, update['backup'], False)['conflicts'])
        self.assertEqual(p.read_text(), 'user\n')

    def test_uninstall_preserves_external_rules_and_user_skill(self):
        (self.target / 'AGENTS.md').write_text('user rules\n')
        user = self.target / '.agents/skills/my-skill/SKILL.md'; user.parent.mkdir(parents=True); user.write_text('mine')
        self.install()
        plan, manifest, content = package.make_plan(self.target, self.source, 'codex', True)
        package.apply(self.target, plan, manifest, content, True)
        self.assertEqual((self.target / 'AGENTS.md').read_text(), 'user rules\n')
        self.assertEqual(user.read_text(), 'mine')
        self.assertFalse((self.target / '.agents/bin/example.py').exists())

    def test_symlink_parent_refused_without_touching_external(self):
        outside = self.temp / 'outside'; outside.mkdir()
        (self.target / '.agents').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(package.Conflict):
            package.make_plan(self.target, self.source, 'codex')
        self.assertEqual(list(outside.iterdir()), [])

    def test_hardlink_refused(self):
        p = self.target / '.agents/bin/example.py'; p.parent.mkdir(parents=True); p.write_text('mine')
        os.link(p, self.temp / 'linked')
        with self.assertRaises(package.Conflict):
            package.make_plan(self.target, self.source, 'codex')

    def test_user_edit_outside_agents_block_survives_update(self):
        self.install(); p = self.target / 'AGENTS.md'; p.write_text('new user rule\n' + p.read_text())
        self.install()
        self.assertTrue(p.read_text().startswith('new user rule\n'))

    def test_user_edit_inside_agents_block_conflicts(self):
        self.install(); p = self.target / 'AGENTS.md'; p.write_text(p.read_text().replace('managed rules', 'my rules'))
        plan, _, _ = package.make_plan(self.target, self.source, 'codex')
        self.assertTrue(plan['conflicts'])

    def test_traversal_rejected(self):
        for name in ('../outside', '/etc/passwd', '.git/config', '.agents/../oops', 'x\\y'):
            with self.assertRaises(package.Conflict):
                package.safe(self.target, name)

    def test_shared_repositories_folder_refused(self):
        with self.assertRaises(package.Conflict):
            package.main(['install', '--source', str(self.source), '--target', str(self.temp)])

    def test_failed_upgrade_restores_touched_files(self):
        self.install(); (self.source / 'scripts/example.py').write_text('upgrade\n')
        plan, manifest, content = package.make_plan(self.target, self.source, 'codex')
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        original = package.put; failed = False
        def put(path, entry, blob=None):
            nonlocal failed
            if path.name == 'manifest.json' and not failed:
                failed = True; raise OSError('injected interruption')
            return original(path, entry, blob)
        with patch.object(package, 'put', side_effect=put):
            with self.assertRaises(OSError):
                package.apply(self.target, plan, manifest, content)
        self.assertIn('first', (self.target / '.agents/bin/example.py').read_text())

    def test_downloader_rejects_traversal_and_archive_links(self):
        import io, tarfile
        spec = importlib.util.spec_from_file_location('download', ROOT / 'scripts/super-board-download.py')
        download = importlib.util.module_from_spec(spec); spec.loader.exec_module(download)
        for index, name in enumerate(('super-board/../outside', '/tmp/outside', 'super-board/.git/config', 'super-board/link')):
            archive = self.temp / ('bad%d.tar.gz' % index)
            with tarfile.open(archive, 'w:gz') as out:
                entry = tarfile.TarInfo(name)
                if name.endswith('/link'):
                    entry.type = tarfile.SYMTYPE; entry.linkname = '/tmp/outside'
                    out.addfile(entry)
                else:
                    entry.size = 3; out.addfile(entry, io.BytesIO(b'bad'))
            with self.assertRaises(ValueError):
                download.extract(archive, self.temp / ('unpack%d' % index))


if __name__ == '__main__':
    unittest.main()
