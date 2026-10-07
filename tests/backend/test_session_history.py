from pathlib import Path
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from backend.roles import session_history as history


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'task/runtime/implementer'
        self.workspace.mkdir(parents=True)
        self.codex = self.root / 'codex'
        self.claude = self.root / 'claude'
        self.codex.mkdir()
        self.environment = patch.dict(os.environ, {'CODEX_HOME': str(self.codex), 'CLAUDE_CONFIG_DIR': str(self.claude)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        with sqlite3.connect(self.codex / 'state_5.sqlite') as connection:
            connection.execute('CREATE TABLE threads(id TEXT, rollout_path TEXT, cwd TEXT, source TEXT, archived INTEGER, created_at REAL)')

    def transcript(self, runner, *, workspace=None, identity=None):
        workspace = (workspace or self.workspace).resolve()
        identity = identity or str(uuid.uuid4())
        if runner == 'codex':
            path = self.codex / 'sessions' / (identity + '.jsonl')
            payload = {'type': 'session_meta', 'payload': {'id': identity, 'cwd': str(workspace)}}
            with sqlite3.connect(self.codex / 'state_5.sqlite') as connection:
                connection.execute('INSERT INTO threads VALUES (?,?,?,?,?,?)',
                    (identity, str(path), str(workspace), 'cli', 0, 9999999999))
        else:
            path = self.claude / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', str(workspace)) / (identity + '.jsonl')
            payload = {'type': 'assistant', 'sessionId': identity, 'cwd': str(workspace), 'isSidechain': False}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + '\n' + json.dumps({'type': 'message', 'text': 'prior conversation'}) + '\n')
        return identity, path

    def test_checkpoint_and_resume_use_exact_identity_even_after_another_conversation_appears(self):
        for runner in ('codex', 'claude'):
            with self.subTest(runner=runner):
                (self.workspace / 'NATIVE_SESSION.json').unlink(missing_ok=True)
                identity, path = self.transcript(runner)
                record = history.capture(self.workspace, runner, required=True)
                self.transcript(runner)
                selected, resume = history.launcher_identity(self.workspace, runner, True)
                self.assertEqual(identity, selected)
                self.assertTrue(resume)
                self.assertEqual(identity, record['session_id'])

    def test_missing_transcript_is_restored_from_valid_checkpoint(self):
        identity, path = self.transcript('codex')
        original = path.read_bytes()
        history.capture(self.workspace, 'codex', required=True)
        path.unlink()
        self.assertEqual((identity, True), history.launcher_identity(self.workspace, 'codex', True))
        self.assertEqual(original, path.read_bytes())

    def test_corrupt_backup_does_not_start_a_different_dialog(self):
        _, path = self.transcript('claude')
        history.capture(self.workspace, 'claude', required=True)
        path.unlink()
        (self.workspace / 'native-transcript.jsonl').write_text('broken')
        with self.assertRaisesRegex(history.SessionHistoryError, 'unavailable'):
            history.launcher_identity(self.workspace, 'claude', True)

    def test_unbound_ambiguous_history_is_not_guessed(self):
        self.transcript('codex')
        self.transcript('codex')
        with self.assertRaisesRegex(history.SessionHistoryError, 'More than one'):
            history.capture(self.workspace, 'codex', required=True)

    def test_another_workspace_cannot_supply_this_roles_history(self):
        self.transcript('codex', workspace=self.root / 'other-task/implementer')
        self.assertIsNone(history.discover(self.workspace, 'codex'))
        with self.assertRaisesRegex(history.SessionHistoryError, 'No saved'):
            history.capture(self.workspace, 'codex', required=True)

    def test_fresh_claude_session_has_a_reserved_id(self):
        identity, resume = history.launcher_identity(self.workspace, 'claude', True)
        self.assertFalse(resume)
        uuid.UUID(identity)
        self.transcript('claude', identity=identity)
        self.assertEqual((identity, True), history.launcher_identity(self.workspace, 'claude', True))

    def test_launcher_passes_exact_session_and_preserves_model(self):
        repo = Path(__file__).resolve().parents[2]
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        arguments = self.root / 'arguments.json'
        for runner in ('codex', 'claude'):
            executable = bin_dir / runner
            executable.write_text('#!/usr/bin/env python3\nimport os,sys,json\nopen(os.environ["ARGUMENTS_FILE"],"w").write(json.dumps(sys.argv[1:]))\n')
            executable.chmod(0o755)
            identity = str(uuid.uuid4())
            environment = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'], ARGUMENTS_FILE=str(arguments),
                SDD_FACTORY_ROLE_RUNNER=runner, SDD_FACTORY_ROLE_MODEL='configured-model',
                SDD_FACTORY_ROLE_RESUME_MODE='native', SDD_FACTORY_ROLE_SESSION_ID=identity)
            result = subprocess.run(['bash', str(repo / 'factory/scripts/run-role-agent.sh')],
                env=environment, cwd=self.workspace, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            args = json.loads(arguments.read_text())
            self.assertIn(identity, args)
            self.assertIn('configured-model', args)
            self.assertNotIn('--last', args)
            self.assertNotIn('-c', args if runner == 'claude' else [])
