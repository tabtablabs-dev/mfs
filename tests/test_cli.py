import json
import sys
from types import SimpleNamespace

from click.testing import CliRunner

from mfs.cli import _parse_byte_range, main
from mfs.errors import MfsError
from mfs.modal_adapter import ModalAdapter, _normalize_modal_path
from mfs.paths import parse_target


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


def test_invalid_target_json_error() -> None:
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


def test_normalize_modal_path_handles_relative_and_absolute_entries() -> None:
    assert _normalize_modal_path("campaign.json") == "/campaign.json"
    assert _normalize_modal_path("/campaign.json") == "/campaign.json"
    assert _normalize_modal_path("/") == "/"


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
