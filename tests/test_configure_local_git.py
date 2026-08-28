import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "configure_local_git.py"
SPEC = importlib.util.spec_from_file_location("configure_local_git", SCRIPT)
git_hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(git_hygiene)


class ConfigureLocalGitTests(unittest.TestCase):
    def test_removes_only_empty_finder_icon_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            git_dir = pathlib.Path(directory) / ".git"
            refs = git_dir / "refs" / "codex" / "capture"
            refs.mkdir(parents=True)
            empty_icon = refs / "Icon\r"
            nonempty_icon = refs.parent / "Icon\r"
            valid_ref = refs / "base"
            empty_icon.write_bytes(b"")
            nonempty_icon.write_bytes(b"resource fork")
            valid_ref.write_text("a" * 40 + "\n")

            removed = git_hygiene.remove_invalid_finder_refs(git_dir)

            self.assertEqual(removed, [empty_icon])
            self.assertFalse(empty_icon.exists())
            self.assertEqual(nonempty_icon.read_bytes(), b"resource fork")
            self.assertEqual(valid_ref.read_text(), "a" * 40 + "\n")

    def test_fetch_hide_ref_is_added_once_without_overwriting_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(
                ["git", "config", "--local", "--add", "fetch.hideRefs", "refs/private"],
                cwd=repo, check=True,
            )

            first = git_hygiene.configure_fetch_hide_ref(repo)
            second = git_hygiene.configure_fetch_hide_ref(repo)

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(
                git_hygiene.fetch_hidden_refs(repo),
                ["refs/private", "refs/codex"],
            )

    def test_fetch_succeeds_with_recreated_icon_after_hide_ref_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            remote = root / "remote.git"
            seed = root / "seed"
            client = root / "client"
            subprocess.run(["git", "init", "--bare", "-q", remote], check=True)
            subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=seed, check=True)
            (seed / "README").write_text("fixture\n")
            subprocess.run(["git", "add", "README"], cwd=seed, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=seed, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=seed, check=True)
            subprocess.run(["git", "push", "-q", "origin", "main"], cwd=seed, check=True)

            subprocess.run(["git", "init", "-q", client], check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=client, check=True)
            icon = client / ".git" / "refs" / "codex" / "capture" / "Icon\r"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"")
            failed = subprocess.run(
                ["git", "fetch", "origin", "main"], cwd=client,
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("bad object", failed.stderr)

            git_hygiene.configure_fetch_hide_ref(client)
            succeeded = subprocess.run(
                ["git", "fetch", "origin", "main"], cwd=client,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(succeeded.returncode, 0, succeeded.stderr)
            self.assertTrue(icon.exists(), "設定應隔離污染，而不是依賴每次刪檔")


if __name__ == "__main__":
    unittest.main()
