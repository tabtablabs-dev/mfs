import json
import sys
from types import SimpleNamespace

from click.testing import CliRunner

from mfs.cli import _parse_byte_range, _parse_line_range, main
from mfs.errors import MfsError
from mfs.index import IndexStore
from mfs.modal_adapter import FsEntry, ModalAdapter, _normalize_modal_path
from mfs.paths import parse_target, resolve_target
from mfs.state import save_cwd


def invoke(*args: str):
    return CliRunner().invoke(main, list(args))


def test_version_command() -> None:
    result = invoke("version")

    assert result.exit_code == 0
    assert result.output.strip() == "0.0.1"


def test_version_json() -> None:
    result = invoke("version", "--json")

    assert result.exit_code == 0
    assert json.loads(result.output) == {"version": "0.0.1"}


def test_parse_virtual_modal_path() -> None:
    parsed = parse_target("Volumes/modal/tabtablabs/main/models/config.json")

    assert parsed.kind == "modal_path"
    assert parsed.profile == "tabtablabs"
    assert parsed.environment == "main"
    assert parsed.volume == "models"
    assert parsed.path == "/config.json"
    assert parsed.canonical_uri == "modal://tabtablabs/main/models/config.json"


def test_parse_modal_uri() -> None:
    parsed = parse_target("modal://tabtablabs/main/models/config.json")

    assert parsed.kind == "modal_path"
    assert parsed.profile == "tabtablabs"
    assert parsed.environment == "main"
    assert parsed.volume == "models"
    assert parsed.path == "/config.json"


def test_parse_root_discovery_paths() -> None:
    assert parse_target("Volumes/").kind == "providers_root"
    assert parse_target("Volumes/modal").kind == "modal_profiles"
    assert parse_target("Volumes/modal/tabtablabs").kind == "modal_environments"
    assert parse_target("Volumes/modal/tabtablabs/main").kind == "modal_volumes"


def test_ls_providers_root_json_does_not_require_modal() -> None:
    result = invoke("ls", "Volumes/", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["entries"] == [{"name": "modal", "type": "provider"}]


def test_ls_without_cwd_returns_stable_json_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MFS_STATE_PATH", str(tmp_path / "state.json"))

    result = invoke("ls", "--json")

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "CWD_NOT_SET"


def test_cd_without_target_resets_to_virtual_root(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("MFS_STATE_PATH", str(state_path))

    result = invoke("cd", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["cwd"] == "Volumes/"
    assert payload["state_path"] == str(state_path)


def test_pwd_reports_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("MFS_STATE_PATH", str(state_path))
    save_cwd("modal://tabtablabs/main/vol/a", state_path=state_path)

    result = invoke("pwd", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["cwd"] == "modal://tabtablabs/main/vol/a"
    assert payload["context"] == "modal/tabtablabs/main"


def test_resolve_relative_target_against_modal_cwd(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    save_cwd("modal://tabtablabs/main/vol/a/b", state_path=state_path)

    parsed = resolve_target("../cache", state_path=state_path)

    assert parsed.canonical_uri == "modal://tabtablabs/main/vol/a/cache"


def test_resolve_leading_slash_requires_volume_cwd(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    save_cwd("Volumes/", state_path=state_path)

    try:
        resolve_target("/cache", state_path=state_path)
    except MfsError as exc:
        assert exc.code == "CWD_VOLUME_REQUIRED"
    else:  # pragma: no cover
        raise AssertionError("expected MfsError")


def test_ls_filters_hidden_entries_by_default(monkeypatch) -> None:
    async def fake_list_target(_parsed, *, recursive, limit, timeout):
        return {
            "target": {},
            "uri": "Volumes/modal/tabtablabs/main/vol",
            "recursive": recursive,
            "limit": limit,
            "count": 3,
            "maybe_truncated": False,
            "entries": [
                {"name": ".secret", "path": "/.secret", "type": "file"},
                {"name": "visible", "path": "/visible", "type": "file"},
            ],
        }

    monkeypatch.setattr("mfs.cli._list_target", fake_list_target)

    result = invoke("ls", "Volumes/modal/tabtablabs/main/vol", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["include_hidden"] is False
    assert [entry["name"] for entry in payload["entries"]] == ["visible"]


def test_ls_all_includes_hidden_entries(monkeypatch) -> None:
    async def fake_list_target(_parsed, *, recursive, limit, timeout):
        return {
            "target": {},
            "uri": "Volumes/modal/tabtablabs/main/vol",
            "recursive": recursive,
            "limit": limit,
            "count": 2,
            "maybe_truncated": False,
            "entries": [
                {"name": ".secret", "path": "/.secret", "type": "file"},
                {"name": "visible", "path": "/visible", "type": "file"},
            ],
        }

    monkeypatch.setattr("mfs.cli._list_target", fake_list_target)

    result = invoke("ls", "Volumes/modal/tabtablabs/main/vol", "--all", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["include_hidden"] is True
    assert [entry["name"] for entry in payload["entries"]] == [".secret", "visible"]


def test_invalid_target_json_error(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("MFS_STATE_PATH", str(state_path))
    save_cwd("Volumes/", state_path=state_path)

    result = invoke("ls", "not-a-target", "--json")

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INVALID_TARGET"


def test_parse_default_byte_range_uses_max_bytes() -> None:
    assert _parse_byte_range(None, max_bytes=123) == (0, 123)


def test_parse_explicit_byte_range() -> None:
    assert _parse_byte_range("5:10", max_bytes=100) == (5, 10)


def test_parse_byte_range_rejects_over_cap() -> None:
    try:
        _parse_byte_range("0:101", max_bytes=100)
    except MfsError as exc:
        assert exc.code == "BYTE_LIMIT_EXCEEDED"
    else:  # pragma: no cover
        raise AssertionError("expected MfsError")


def test_parse_line_range() -> None:
    assert _parse_line_range("1:10") == (1, 10)


def test_parse_line_range_rejects_invalid_order() -> None:
    try:
        _parse_line_range("10:1")
    except MfsError as exc:
        assert exc.code == "INVALID_LINE_RANGE"
    else:  # pragma: no cover
        raise AssertionError("expected MfsError")


def test_tree_applies_depth_budget(monkeypatch) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def list_files(self, _parsed, *, recursive, limit):
            assert recursive is True
            assert limit == 10
            return [
                FsEntry(path="/a.txt", name="a.txt", type="file", size=5),
                FsEntry(path="/dir/b.txt", name="b.txt", type="file", size=7),
                FsEntry(path="/dir/deep/c.txt", name="c.txt", type="file", size=11),
            ]

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke(
        "tree", "Volumes/modal/tabtablabs/main/vol", "--depth", "1", "--limit", "10", "--json"
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["partial"] is True
    assert payload["limited_by"] == "depth"
    assert [entry["path"] for entry in payload["entries"]] == ["/a.txt", "/dir/b.txt"]


def test_du_sums_bounded_file_sizes(monkeypatch) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def list_files(self, _parsed, *, recursive, limit):
            assert recursive is True
            assert limit == 10
            return [
                FsEntry(path="/a.txt", name="a.txt", type="file", size=5),
                FsEntry(path="/dir", name="dir", type="directory", size=0),
                FsEntry(path="/dir/b.txt", name="b.txt", type="file", size=7),
            ]

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke("du", "Volumes/modal/tabtablabs/main/vol", "--limit", "10", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["size_bytes"] == 12
    assert payload["entry_count"] == 3
    assert payload["source"] == "live"


def test_find_filters_live_metadata_and_records_store(monkeypatch, tmp_path) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def list_files(self, _parsed, *, recursive, limit):
            assert recursive is True
            return [
                FsEntry(path="/a.json", name="a.json", type="file", size=5),
                FsEntry(path="/b.txt", name="b.txt", type="file", size=7),
            ]

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)
    store_path = tmp_path / "index.sqlite"

    result = invoke(
        "find",
        "Volumes/modal/tabtablabs/main/vol",
        "--glob",
        "*.json",
        "--store",
        str(store_path),
        "--json",
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["store_path"] == str(store_path)
    assert [entry["path"] for entry in payload["entries"]] == ["/a.json"]


def test_grep_uses_indexed_chunks(tmp_path) -> None:
    store_path = tmp_path / "index.sqlite"
    store = IndexStore(store_path)
    volume_uri = "modal://tabtablabs/main/vol"
    store.ensure_schema()
    store.upsert_file(volume_uri, {"path": "/a.txt", "type": "file", "size": 11})
    store.replace_chunks(volume_uri, "/a.txt", ["hello world\nbye world"])

    result = invoke(
        "grep",
        "Volumes/modal/tabtablabs/main/vol",
        "hello",
        "--store",
        str(store_path),
        "--json",
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["store_path"] == str(store_path)
    assert payload["matches"][0]["path"] == "/a.txt"
    assert payload["matches"][0]["line"] == 1


def test_search_lex_uses_fts(tmp_path) -> None:
    store_path = tmp_path / "index.sqlite"
    store = IndexStore(store_path)
    volume_uri = "modal://tabtablabs/main/vol"
    store.ensure_schema()
    store.upsert_file(volume_uri, {"path": "/a.txt", "type": "file", "size": 11})
    store.replace_chunks(volume_uri, "/a.txt", ["hello world"])

    result = invoke(
        "search",
        "Volumes/modal/tabtablabs/main/vol",
        "hello",
        "--lex",
        "--store",
        str(store_path),
        "--json",
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["path"] == "/a.txt"


def test_manifest_jsonl_uses_live_metadata(monkeypatch) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def list_files(self, _parsed, *, recursive, limit):
            assert recursive is True
            return [FsEntry(path="/a.txt", name="a.txt", type="file", size=5)]

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke("manifest", "Volumes/modal/tabtablabs/main/vol", "--jsonl")

    assert result.exit_code == 0
    rows = [json.loads(line) for line in result.output.splitlines()]
    assert rows[0]["path"] == "/a.txt"
    assert rows[0]["volume_uri"] == "modal://tabtablabs/main/vol"


def test_rm_requires_yes() -> None:
    result = invoke("rm", "Volumes/modal/tabtablabs/main/vol/a.txt", "--json")

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_put_directory_requires_recursive(tmp_path) -> None:
    local_dir = tmp_path / "artifact"
    local_dir.mkdir()

    result = invoke("put", str(local_dir), "Volumes/modal/tabtablabs/main/vol/artifact", "--json")

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "RECURSIVE_REQUIRED"


def test_cp_rejects_cross_volume() -> None:
    result = invoke(
        "cp",
        "Volumes/modal/tabtablabs/main/vol-a/a.txt",
        "Volumes/modal/tabtablabs/main/vol-b/a.txt",
        "--json",
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "CROSS_VOLUME_UNSUPPORTED"


def test_mkdir_creates_directory_like_marker(monkeypatch) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def mkdir_path(self, parsed, *, parents):
            assert parsed.canonical_uri == "modal://tabtablabs/main/vol/new-dir"
            assert parents is True
            return {
                "operation": "mkdir",
                "target_uri": parsed.canonical_uri,
                "marker_uri": "modal://tabtablabs/main/vol/new-dir/.mfskeep",
                "parents": parents,
                "created": True,
                "directory_semantics": "hidden_marker_file",
            }

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke("mkdir", "Volumes/modal/tabtablabs/main/vol/new-dir", "--parents", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["operation"] == "mkdir"
    assert payload["created"] is True
    assert payload["marker_uri"] == "modal://tabtablabs/main/vol/new-dir/.mfskeep"


def test_mkdir_at_environment_root_creates_v2_volume(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("MFS_STATE_PATH", str(state_path))
    save_cwd("Volumes/modal/tabtablabs/main", state_path=state_path)

    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def mkdir_path(self, parsed, *, parents):
            assert parsed.volume == "public-records"
            assert parsed.path == "/"
            return {
                "operation": "mkdir",
                "target_uri": parsed.volume_uri,
                "parents": parents,
                "created": True,
                "created_resource": "volume",
                "volume_id": "vo-test",
                "volume_version": "v2",
                "directory_semantics": "modal_volume",
            }

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke("mkdir", "public-records", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["target_uri"] == "modal://tabtablabs/main/public-records"
    assert payload["created_resource"] == "volume"
    assert payload["volume_version"] == "v2"


def test_mkdir_marker_path() -> None:
    from mfs.modal_adapter import _mkdir_marker_path, _parent_modal_path

    assert _mkdir_marker_path("public-records") == "/public-records/.mfskeep"
    assert _mkdir_marker_path("/public-records") == "/public-records/.mfskeep"
    assert _parent_modal_path("/public-records") == "/"
    assert _parent_modal_path("/a/b") == "/a"


def test_mkdir_existing_target_requires_parents(monkeypatch) -> None:
    class FakeAdapter:
        def __init__(self, *, timeout):
            pass

        async def mkdir_path(self, parsed, *, parents):
            raise MfsError(
                code="REMOTE_DEST_EXISTS",
                message="Remote directory-like target already exists; pass --parents to accept it",
                uri=parsed.canonical_uri,
                retryable=False,
            )

    monkeypatch.setattr("mfs.cli.ModalAdapter", FakeAdapter)

    result = invoke("mkdir", "Volumes/modal/tabtablabs/main/vol/new-dir", "--json")

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "REMOTE_DEST_EXISTS"


def test_normalize_modal_path_handles_relative_and_absolute_entries() -> None:
    assert _normalize_modal_path("campaign.json") == "/campaign.json"
    assert _normalize_modal_path("/campaign.json") == "/campaign.json"
    assert _normalize_modal_path("/") == "/"


def test_entry_from_proto_normalizes_live_modal_paths() -> None:
    class FakeFileEntryType:
        def __call__(self, value):
            return SimpleNamespace(name={1: "FILE"}.get(value, "UNKNOWN"))

    adapter = ModalAdapter()
    adapter._modal_bundle = {"FileEntryType": FakeFileEntryType()}
    entry = adapter._entry_from_proto(
        SimpleNamespace(path="campaign.json", type=1, size=83, mtime=1770831307)
    )

    assert entry.path == "/campaign.json"
    assert entry.name == "campaign.json"


def test_list_proto_entries_preserves_caller_uri_on_errors() -> None:
    class FakeRequest:
        def __init__(self, **_kwargs):
            pass

    class FakeRpc:
        def unary_stream(self, _request):
            raise RuntimeError('path "/missing" not found')

    fake_api_pb2 = SimpleNamespace(
        VolumeListFiles2Request=FakeRequest,
        VolumeListFilesRequest=FakeRequest,
    )
    fake_stub = SimpleNamespace(VolumeListFiles2=FakeRpc(), VolumeListFiles=FakeRpc())
    fake_volume = SimpleNamespace(object_id="vo-secret", _client=SimpleNamespace(stub=fake_stub))

    adapter = ModalAdapter()
    adapter._modal_bundle = {"api_pb2": fake_api_pb2}
    uri = "modal://tabtablabs/main/vol/missing"

    try:
        import asyncio

        asyncio.run(
            adapter._list_proto_entries(
                fake_volume,
                path="/missing",
                recursive=False,
                max_entries=1,
                uri=uri,
            )
        )
    except MfsError as exc:
        assert exc.code == "REMOTE_NOT_FOUND"
        assert exc.uri == uri
        assert "vo-secret" not in str(exc.to_dict())
    else:  # pragma: no cover
        raise AssertionError("expected MfsError")


def test_download_signed_urls_uses_adapter_timeout(monkeypatch) -> None:
    seen_timeouts = []

    class FakeTimeout:
        def __init__(self, *, total):
            self.total = total
            seen_timeouts.append(total)

    class FakeContent:
        async def iter_chunked(self, _size):
            yield b"ok"

    class FakeResponse:
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, _url):
            return FakeResponse()

    fake_aiohttp = SimpleNamespace(ClientTimeout=FakeTimeout, ClientSession=FakeSession)
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)

    import asyncio

    data = asyncio.run(ModalAdapter(timeout=0.25)._download_signed_urls(["https://x"], byte_cap=10))

    assert data == b"ok"
    assert seen_timeouts == [0.25]


def test_stat_treats_successful_empty_listing_as_empty_directory(monkeypatch) -> None:
    async def fake_list_files(_target, *, recursive, limit):
        assert recursive is False
        assert limit == 2
        return []

    adapter = ModalAdapter()
    monkeypatch.setattr(adapter, "list_files", fake_list_files)

    import asyncio

    result = asyncio.run(
        adapter.stat_path(parse_target("Volumes/modal/tabtablabs/main/vol/empty"), limit=2)
    )

    assert result["type"] == "directory"
    assert result["entry"]["path"] == "/empty"
    assert result["entry"]["child_count_limited"] == 0
