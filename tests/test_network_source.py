"""SMB contracts use local synthetic fixtures; no company server is contacted."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
import uuid
from unittest import mock

from team_drive import fs_access
from team_drive.engine import Engine
from team_drive.errors import DriveError
from team_drive.network_source import WindowsShareSource, normalize_share_path, resolve_share_path, share_settings
from team_drive.service_config import settings


class ShareSyntaxTests(unittest.TestCase):
    def test_explicit_unc_and_mapped_paths_only(self):
        self.assertEqual(normalize_share_path(r"\\server.example\approved\Finance"), r"\\server.example\approved\Finance")
        self.assertEqual(normalize_share_path("Z:\\Finance\\"), "Z:\\Finance")
        for path in ("relative", "C:relative", "/mnt/share", "https://example.invalid/docs",
                     r"\\?\UNC\server\share", r"\\.\pipe\secret", r"\\server",
                     r"\\server\share\..\outside", r"\\server\share\a:stream",
                     r"\\server\share\CON", "\\\\server\\share\\trailing ",
                     "\\\\server\\share\\\\empty"):
            with self.subTest(path=path), self.assertRaises(DriveError):
                normalize_share_path(path)

    def test_configuration_keeps_explicit_network_spelling_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            config = {"provider": "windows_share", "root": r"Z:\Finance", "state_dir": str(Path(temp) / "state")}
            path.write_text(json.dumps(config))
            actual = settings(path)
            self.assertEqual(actual["config"]["root"], r"Z:\Finance")
            self.assertEqual(actual["config"]["windows_share"]["max_items"], 10000)
            self.assertFalse((Path(temp) / "state").exists())
        for config in ({"password": "synthetic"}, {"max_items": True}, {"max_depth": 129}, {"scan_budget_seconds": float("inf")}):
            with self.assertRaises(DriveError):
                share_settings(config)

    @unittest.skipIf(os.name == "nt", "Windows validates mapped drives natively")
    def test_non_windows_fails_without_connecting_or_treating_unc_as_local(self):
        with self.assertRaises(DriveError) as caught:
            fs_access.SourceAccess(r"\\server\share", allow_network=True)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_PLATFORM")

    @unittest.skipUnless(os.name == "nt", "Windows native local boundary")
    def test_windows_unc_encoding_and_local_provider_stay_strict(self):
        self.assertEqual(fs_access._extended(r"\\server\share\a"), r"\\?\UNC\server\share\a")
        self.assertEqual(fs_access._canonical(r"\\?\UNC\SERVER\share\a"), r"\\server\share\a")
        with self.assertRaises(DriveError):
            fs_access._valid_windows_path(r"\\server\share")
        with self.assertRaises(DriveError) as caught:
            fs_access._WindowsDirectories(r"\\server\share", allow_network=True, state=True)
        self.assertEqual(caught.exception.code, "UNSAFE_STATE")
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(DriveError) as caught:
            resolve_share_path(temp)
        self.assertEqual(caught.exception.code, "SHARE_UNAVAILABLE")

    @unittest.skipUnless(os.name == "nt", "Windows native protocol ABI")
    def test_native_protocol_rejects_offline_cache_and_unknown_provider(self):
        import ctypes
        for kind, flags in ((0x00020000, 2), (0x00260000, 0), (0x002E0000, 0)):
            def fake_info(_handle, info_class, buffer, size):
                self.assertEqual(info_class, 13)
                self.assertEqual(buffer._obj.version, 2)
                self.assertEqual(buffer._obj.size, ctypes.sizeof(fs_access._RemoteProtocolInfo))
                self.assertEqual(size, ctypes.sizeof(fs_access._RemoteProtocolInfo))
                buffer._obj.version, buffer._obj.protocol, buffer._obj.flags = 3, kind, flags
                return 1
            with self.subTest(kind=kind, flags=flags), mock.patch.object(fs_access._kernel, "GetFileInformationByHandleEx", side_effect=fake_info):
                with self.assertRaises(DriveError) as caught:
                    fs_access._share_info(1)
            self.assertEqual(caught.exception.code, "SHARE_PROTOCOL_UNVERIFIED")

    @unittest.skipUnless(os.name == "nt", "Windows native read-only CreateFile contract")
    def test_native_share_open_never_requests_write_create_or_delete_sharing(self):
        with mock.patch.object(fs_access._kernel, "CreateFileW", return_value=42) as create:
            self.assertEqual(fs_access._handle(r"\\synthetic-server\approved\folder", directory=True), 42)
        args = create.call_args[0]
        self.assertEqual(args[0], r"\\?\UNC\synthetic-server\approved\folder")
        self.assertEqual(args[1], 0x80000000)
        self.assertEqual(args[2], 1)
        self.assertEqual(args[4], 3)
        self.assertEqual(args[5], 0x00200000 | 0x02000000)


class SyntheticShareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="df-share-contract-")
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.mapping = r"\\synthetic-server\approved"
        self.principal = "synthetic-user-binding"
        self.natives = []
        outer = self
        local_type = fs_access.WindowsSource if os.name == "nt" else fs_access.PosixSource

        def normalized(info):
            return SimpleNamespace(**{key: (getattr(info, "st_birthtime_ns", info.st_ctime_ns) if key == "st_ctime_ns" else getattr(info, key, 0))
                for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_nlink", "st_file_attributes")})

        class FakeNative:
            def __init__(self, _root, allow_network=False):
                if not allow_network:
                    raise AssertionError("Network opt-in missing")
                self.local = local_type(outer.root)
                self.root, self.identity = self.local.root, self.local.identity
                self.target = outer.mapping
                self.denied, self.offline, self.incomplete = set(), False, False
                outer.natives.append(self)

            def check_root(self):
                if self.offline:
                    raise DriveError("SHARE_ROOT_UNAVAILABLE", "Synthetic unavailable share")
                self.local.check_root()

            def observe(self, relative):
                self.check_root()
                if relative in self.denied:
                    raise PermissionError("Synthetic denial")
                return normalized(self.root.joinpath(*relative.split("/")).lstat())

            def open_read(self, relative):
                self.observe(relative)
                fd, info = self.local.open_read(relative)
                return fd, normalized(info)

            def stat_fd(self, fd):
                return normalized(os.fstat(fd))

            def walk(self, errors, **limits):
                self.check_root()
                for row in self.local.walk(errors):
                    yield row
                if self.incomplete:
                    errors.append(True)

            def close(self):
                self.local.close()

        self.patches = [mock.patch("team_drive.network_source.resolve_share_path", side_effect=lambda _raw: self.mapping),
                        mock.patch("team_drive.network_source._principal_binding", side_effect=lambda: self.principal),
                        mock.patch.object(fs_access, "WindowsSource", FakeNative, create=True)]
        for patch in self.patches:
            patch.start()
        self.source = WindowsShareSource(r"Z:\Approved", max_file_bytes=1024)
        self.engine = None

    def tearDown(self):
        if self.engine:
            self.engine.close()
        self.source.close()
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def write(self, relative="budget.csv", content="category,amount\ntravel,120\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def build_engine(self):
        config = self.base / "profile.json"
        config.write_text(json.dumps({"provider": "windows_share", "root": r"Z:\Approved", "state_dir": str(self.base / "index")}))
        self.engine = Engine(str(config), autostart=False)
        self.engine.scan_once()
        return self.engine.search("travel")["files"][0]

    def test_digest_binds_content_identity_and_current_source(self):
        path = self.write()
        snapshot = io.BytesIO()
        first, info = self.source.digest("budget.csv", snapshot)
        self.assertEqual(snapshot.getvalue(), path.read_bytes())
        origin = self.source.evidence("budget.csv")
        self.assertEqual(origin["source_version"], first)
        self.assertEqual(origin["content_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotEqual(first, origin["content_sha256"])
        self.assertEqual(info.st_size, len(snapshot.getvalue()))
        replacement = self.write("replacement.csv")
        os.replace(replacement, path)
        changed, _ = self.source.digest("budget.csv")
        self.assertNotEqual(first, changed, "A replaced object cannot reuse the old evidence version.")

    def test_incomplete_walk_never_publishes_partial_manifest(self):
        self.write()
        list(self.source.walk([]))
        before = self.source.evidence("budget.csv")
        self.write("new.csv")
        self.source._native.incomplete = True
        errors = []
        with self.assertRaises(DriveError):
            list(self.source.walk(errors))
        self.assertTrue(errors)
        self.assertEqual(self.source.evidence("budget.csv"), before)
        self.assertEqual(self.source.evidence("new.csv"), {})

    def test_mapping_and_identity_changes_reject_prior_scope(self):
        old = self.mapping
        self.mapping = r"\\synthetic-server\different"
        with self.assertRaises(DriveError) as caught:
            self.source.check_root()
        self.assertEqual(caught.exception.code, "SHARE_ROOT_CHANGED")
        self.mapping = old
        self.principal = "different-synthetic-user"
        with self.assertRaises(DriveError) as caught:
            self.source.check_root()
        self.assertEqual(caught.exception.code, "SHARE_IDENTITY_CHANGED")

    def test_revocation_and_changed_content_block_cached_candidates(self):
        self.write()
        self.source.digest("budget.csv")
        origin = self.source.evidence("budget.csv")
        self.source._native.denied.add("budget.csv")
        with self.assertRaises(DriveError) as caught:
            self.source.verify_origin("budget.csv", origin)
        self.assertEqual(caught.exception.code, "SHARE_UNAVAILABLE")
        self.source._native.denied.clear()
        self.write(content="category,amount\ntravel,999\n")
        with self.assertRaises(DriveError) as caught:
            self.source.verify_origin("budget.csv", origin)
        self.assertEqual(caught.exception.code, "SHARE_SOURCE_CHANGED")

    def test_limits_and_deadline_do_not_publish_evidence(self):
        self.write(content="x" * 1025)
        with self.assertRaises(DriveError) as caught:
            self.source.digest("budget.csv")
        self.assertEqual(caught.exception.code, "FILE_TOO_LARGE")
        self.assertEqual(self.source.evidence("budget.csv"), {})
        with self.assertRaises(DriveError) as caught:
            self.source.digest("budget.csv", deadline=0)
        self.assertEqual(caught.exception.code, "SHARE_TIMEOUT")

    def test_engine_roundtrip_origin_and_current_permission_before_rerank(self):
        self.write()
        file = self.build_engine()
        self.assertEqual(file["origin"]["provider"], "windows_share")
        self.assertTrue(self.engine.status()["capabilities"]["network_source"])
        result = self.engine.read(file["file_id"], expected_version=file["source_version"])
        self.assertEqual(result["origin"]["source_version"], result["source_version"])
        self.engine.search("travel", mode="hybrid")
        self.engine._source._native.denied.add("budget.csv")
        self.engine.retrieval.config["rerank"]["enabled"] = True
        with mock.patch("team_drive.retrieval._post") as model:
            denied = self.engine.call("search", {"query": "travel", "mode": "hybrid", "rerank": True})
        model.assert_not_called()
        self.assertFalse(denied["ok"])
        self.assertNotIn("files", denied)
        self.assertNotIn("120", json.dumps(denied))

    def test_cached_ranked_snippet_rechecks_current_access(self):
        self.write()
        self.build_engine()
        self.engine.search("travel", mode="hybrid")
        self.engine._source._native.denied.add("budget.csv")
        denied = self.engine.call("search", {"query": "travel", "mode": "hybrid"})
        self.assertFalse(denied["ok"])
        self.assertNotIn("files", denied)
        self.assertNotIn("120", json.dumps(denied))

    def test_mapping_change_invalidates_coverage_before_list(self):
        self.write()
        self.build_engine()
        self.mapping = r"\\synthetic-server\replacement"
        denied = self.engine.call("list")
        self.assertEqual(denied["error"]["code"], "SHARE_ROOT_CHANGED")
        self.assertNotIn("files", denied)
        with self.engine._db() as db:
            self.assertFalse(self.engine._coverage(db)["inventory_complete"])

    def test_semantic_index_rechecks_access_before_cached_text(self):
        self.write()
        self.build_engine()
        self.engine.retrieval.config["semantic"]["enabled"] = True
        self.engine._source._native.denied.add("budget.csv")
        with mock.patch.object(self.engine.retrieval, "index_file") as index:
            with self.assertRaises(DriveError):
                self.engine.scan_once()
        index.assert_not_called()

    def test_engine_outage_or_partial_scan_does_not_delete(self):
        self.write()
        file = self.build_engine()
        native = self.engine._source._native
        native.incomplete = True
        with self.assertRaises(DriveError):
            self.engine.scan_once()
        with self.engine._db() as db:
            row = db.execute("SELECT status,source_version FROM files WHERE id=?", (file["file_id"],)).fetchone()
            self.assertEqual(tuple(row), ("ready", file["source_version"]))
            self.assertFalse(self.engine._coverage(db)["inventory_complete"])
        native.offline = True
        self.assertFalse(self.engine.call("search", {"query": "travel"})["ok"])

    def test_engine_changed_same_bytes_requires_new_version_and_refresh(self):
        path = self.write()
        file = self.build_engine()
        replacement = self.write("replacement.csv")
        os.replace(replacement, path)
        stale = self.engine.call("read", {"file_id": file["file_id"], "expected_version": file["source_version"]})
        self.assertEqual(stale["error"]["code"], "STALE_SOURCE")
        self.engine.scan_once()
        fresh = self.engine.search("travel")["files"][0]
        self.assertNotEqual(file["source_version"], fresh["source_version"])


@unittest.skipUnless(os.name == "nt" and os.environ.get("DF_MCP_TEST_SMB") == "1",
                     "Real localhost SMB test requires Windows and explicit DF_MCP_TEST_SMB=1")
class NativeLocalhostSMBTests(unittest.TestCase):
    def test_current_user_readonly_share_and_local_index_roundtrip(self):
        # Explicit opt-in only: create one unique, synthetic, localhost share.
        # Do not enable services, change firewall rules, or use external servers.
        with tempfile.TemporaryDirectory(prefix="df-simulated-smb-") as temp:
            base = Path(temp).resolve()
            source = base / "SIMULATED_SOURCE"
            source.mkdir()
            document = source / "budget.csv"
            document.write_text("category,amount\nSIMULATED_TRAVEL,120\n", encoding="utf-8")
            name = "df_simulated_" + uuid.uuid4().hex
            env = dict(os.environ, DF_MCP_TEST_SHARE_NAME=name, DF_MCP_TEST_SHARE_PATH=str(source))

            def powershell(command):
                return subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                                      env=env, capture_output=True, text=True, timeout=30)

            engine = None
            try:
                setup = powershell("$ErrorActionPreference='Stop'; "
                    "$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name; "
                    "New-SmbShare -Name $env:DF_MCP_TEST_SHARE_NAME -Path $env:DF_MCP_TEST_SHARE_PATH "
                    "-ReadAccess $identity -CachingMode None -ErrorAction Stop | Out-Null; "
                    "Write-Output 'SIMULATED_SMB_CREATED'")
                self.assertEqual(setup.returncode, 0,
                    "Native SMB fixture was not created. This explicit test requires Administrator rights and an already running Server service; "
                    "no service/firewall was changed. " + setup.stderr[-1500:])
                self.assertIn("SIMULATED_SMB_CREATED", setup.stdout)
                config = base / "profile.json"
                state = base / "LOCAL_INDEX"
                config.write_text(json.dumps({"provider": "windows_share", "root": "\\\\localhost\\" + name,
                                              "state_dir": str(state)}), encoding="utf-8")
                engine = Engine(str(config), autostart=False)
                self.assertEqual(engine.scan_once()["job"]["status"], "complete")
                file = engine.search("SIMULATED_TRAVEL")["files"][0]
                read = engine.read(file["file_id"], expected_version=file["source_version"])
                self.assertEqual(read["origin"]["provider"], "windows_share")
                self.assertEqual(read["origin"]["source_version"], read["source_version"])
                self.assertEqual(engine.state, state)
                self.assertEqual([child.name for child in source.iterdir()], ["budget.csv"])
                document.write_text("category,amount\nSIMULATED_TRAVEL,999\n", encoding="utf-8")
                stale = engine.call("read", {"file_id": file["file_id"], "expected_version": file["source_version"]})
                self.assertEqual(stale["error"]["code"], "STALE_SOURCE")
                engine.scan_once()
                current = engine.search("SIMULATED_TRAVEL")["files"][0]
                self.assertNotEqual(current["source_version"], file["source_version"])
            finally:
                try:
                    if engine is not None:
                        engine.close()
                finally:
                    # Also clean up an uncertain setup outcome (e.g. timeout).
                    # The name and exact path are unique to this test fixture.
                    removed = powershell("$ErrorActionPreference='Stop'; "
                        "$share=Get-SmbShare -Name $env:DF_MCP_TEST_SHARE_NAME -ErrorAction SilentlyContinue; "
                        "if ($null -ne $share) { "
                        "if ($share.Path -ne $env:DF_MCP_TEST_SHARE_PATH) { throw 'Unexpected synthetic share target' }; "
                        "Remove-SmbShare -Name $env:DF_MCP_TEST_SHARE_NAME -Force -Confirm:$false -ErrorAction Stop }")
                    self.assertEqual(removed.returncode, 0, "Synthetic share cleanup failed: " + removed.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
