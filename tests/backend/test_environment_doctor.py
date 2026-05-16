from pathlib import Path
import tempfile
import unittest

from factory.doctor.environment_doctor import build_report, format_human_report


class EnvironmentDoctorTests(unittest.TestCase):
    def test_build_report_reads_env_values_from_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            claude_dir = repo_root / ".claude"
            claude_dir.mkdir()
            workdir = repo_root / "workdir"
            ios_dir = repo_root / "ios"
            android_dir = repo_root / "android"
            workdir.mkdir()
            ios_dir.mkdir()
            android_dir.mkdir()
            (claude_dir / ".env").write_text(
                "\n".join(
                    [
                        f"SDD_WORKDIR={workdir}",
                        f"IOS_DIR={ios_dir}",
                        f"ANDROID_DIR={android_dir}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (claude_dir / "settings.local.json").write_text(
                '{"enabledMcpjsonServers":["ios-rag","android-rag","frontend-rag"]}',
                encoding="utf-8",
            )

            report = build_report(
                repo_root=repo_root,
                env={},
                which_func=lambda name: f"/usr/bin/{name}",
                command_runner=lambda command: (0, "Authenticated"),
            )

            env_checks = {item["id"]: item for item in report["checks"]}
            self.assertEqual("ok", env_checks["env.SDD_WORKDIR"]["status"])
            self.assertEqual(".claude/.env", env_checks["env.SDD_WORKDIR"]["source"])
            self.assertEqual("missing", env_checks["toolchain.venv"]["status"])
            self.assertEqual("ok", env_checks["mcp.ios-rag"]["status"])
            self.assertEqual("ok", env_checks["mcp.android-rag"]["status"])

    def test_build_report_flags_missing_required_runner_and_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            claude_dir = repo_root / ".claude"
            claude_dir.mkdir()
            (repo_root / ".venv").mkdir()
            workdir = repo_root / "workdir"
            ios_dir = repo_root / "ios"
            android_dir = repo_root / "android"
            workdir.mkdir()
            ios_dir.mkdir()
            android_dir.mkdir()
            (claude_dir / ".env").write_text(
                "\n".join(
                    [
                        f"SDD_WORKDIR={workdir}",
                        f"IOS_DIR={ios_dir}",
                        f"ANDROID_DIR={android_dir}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (claude_dir / "settings.json").write_text(
                '{"enabledMcpjsonServers":["ios-rag"]}',
                encoding="utf-8",
            )

            def fake_which(name: str) -> str | None:
                mapping = {
                    "python3": "/usr/bin/python3",
                    "jq": "/usr/bin/jq",
                    "acli": "/usr/bin/acli",
                    "glab": "/usr/bin/glab",
                    "node": "/usr/bin/node",
                    "npm": "/usr/bin/npm",
                }
                return mapping.get(name)

            report = build_report(
                repo_root=repo_root,
                env={},
                which_func=fake_which,
                command_runner=lambda command: (1, "unauthorized"),
            )

            checks = {item["id"]: item for item in report["checks"]}
            self.assertEqual("ok", checks["toolchain.venv"]["status"])
            self.assertEqual("missing", checks["runner.any"]["status"])
            self.assertEqual("unauthorized", checks["auth.runner_any"]["status"])
            self.assertEqual("missing", checks["mcp.android-rag"]["status"])

    def test_format_human_report_includes_hints_for_failures(self) -> None:
        report = {
            "overall_status": "warn",
            "required_ok": 1,
            "required_total": 2,
            "optional_warnings": 0,
            "checks": [
                {
                    "id": "env.SDD_WORKDIR",
                    "category": "environment",
                    "label": "Task workdir root",
                    "required": True,
                    "status": "missing",
                    "details": "SDD_WORKDIR is not set.",
                    "value": None,
                    "source": None,
                    "hint": "Set SDD_WORKDIR.",
                }
            ],
        }

        text = format_human_report(report)

        self.assertIn("Overall status: warn", text)
        self.assertIn("hint: Set SDD_WORKDIR.", text)
