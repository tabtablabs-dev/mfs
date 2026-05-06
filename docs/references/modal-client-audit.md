# Modal client audit for mfs spec

Date: 2026-05-06

## Sources checked

- Modal docs: Volumes v2, Volume reference, CLI volume reference, NetworkFileSystem, CloudBucketMounts, Dicts, Queues.
- DeepWiki: `modal-labs/modal-client` pages for Volumes/NFS, resource management CLI, configuration/profile management, configuration/authentication.
- Source audit: cloned `modal-labs/modal-client` at commit `1e69463` and inspected `py/modal/volume.py`, `py/modal/cli/volume.py`, `py/modal/config.py`, `py/modal/client.py`, `py/modal/_object.py`, `modal_proto/api.proto`.
- Local installed SDK: `modal==1.3.5` signatures checked by introspection.

No public CodeWiki mirror for `modal-labs/modal-client` was found via web search. Treat this source audit as the code-level audit until a CodeWiki URL is available.

## Findings that affect mfs

### NetworkFileSystem does not replace mfs

`modal.NetworkFileSystem` is deprecated and will be removed. It is the more transparent NFS-style abstraction, but Modal docs recommend `modal.Volume` for new projects. So `mfs` should stay focused on Volumes, not switch to NFS.

### CloudBucketMount does not replace mfs

`modal.CloudBucketMount` targets S3/R2/GCS and inherits Mountpoint limitations: append mode and arbitrary-offset write are unsupported. Docs say to use Volumes when these features are needed. It is adjacent, not a substitute for a Modal Volume query CLI.

### Modal Volumes already expose enough SDK surface for mfs MVP

Public SDK / CLI source show:

- `Volume.from_name(name, environment_name=..., version=..., client=...)`
- `Volume.objects.list(environment_name=...)`
- `iterdir(path, recursive=True)` / `listdir(path, recursive=False)`
- `read_file(path)` streaming bytes
- `read_file_into_fileobj(path, fileobj)`
- `remove_file(path, recursive=False)`
- `copy_files(src_paths, dst_path, recursive=False)`
- `batch_upload(force=False)` with `put_file` and `put_directory`

So basic read/write/list is not missing from Modal. The unique value of `mfs` is:

- filesystem-shaped virtual paths
- stable JSON output
- bounded agent-safe defaults
- local SQLite metadata + FTS index
- manifest/change workflows

### Private/proto surface is better than public SDK for two bounded-query features

`modal_proto/api.proto` includes:

- `VolumeGetFile2Request.start` and `len` for byte-range reads.
- `VolumeListFiles2Request.max_entries` for bounded listing.

Public `Volume.read_file(path)` does not expose start/len. Public `Volume.iterdir/listdir` do not expose max_entries. If MVP needs true bounded remote reads/listing, keep that inside the Modal adapter and version-gate/test it. Do not leak proto details into command handlers.

### File metadata is minimal

`FileEntry` has:

- `path`
- `type`
- `mtime`
- `size`

No remote etag/content hash is exposed in public file listings. `mfs` should not design around Modal-provided etags. Use `mtime + size` as metadata signal; compute `sha256` only for content actually read into cache/index.

### Profile-in-path is possible but not free

Modal profiles are local config sections in `~/.modal.toml`, selected by `MODAL_PROFILE` or active profile state. `_Client.from_env()` is a singleton based on current config and can return a cached client. With profile in the path, `mfs` must not accidentally reuse one global active-profile client for multiple profile segments.

Adapter implication:

- Build a per-profile client factory/cache.
- Prefer explicit client construction from the selected profile's token/server settings.
- Avoid relying on `modal.Client.from_env()` singleton for multi-profile commands.
- If direct SDK profile plumbing proves unsafe, isolate a subprocess fallback with `MODAL_PROFILE=<profile>` inside the Modal adapter only.

### Copy semantics are narrower than mfs initially implied

`Volume.copy_files(src_paths, dst_path, recursive=False)` copies within a single Volume. It is not cross-volume copy. Source shows recursive copy is unsupported for v1 Volumes and supported through `VolumeCopyFiles2` for v2.

MVP implication:

- `mfs cp` should be same-profile, same-env, same-volume only.
- Cross-volume copy is post-MVP or explicit get+put.
- Recursive copy should be v2-only or fail clearly on v1.

### Directory get/put should be explicit

Modal CLI `volume get` downloads directories recursively. For agent safety, `mfs get` should require `--recursive` when remote path is a directory. Likewise local directory upload should require `--recursive`.

### Queues and Dicts do not force mutation queue into MVP

Modal Queues are for communication between active functions; queue contents expire 24 hours after last put and are not reliable archival storage. Dicts have a locking primitive, but per-object size/expiry guidance means they are not a substitute for a durable mutation log. The spec's decision to defer mutation queue is still sound.

## Spec changes recommended

1. Keep SDK-first, but note private/proto range and `max_entries` use as adapter-confined if needed.
2. Add root discovery paths: `Volumes/`, `Volumes/modal/`, `Volumes/modal/PROFILE/`, `Volumes/modal/PROFILE/ENV/`.
3. Remove `etag` from MVP schema.
4. Add volume identity fields: profile, env, name, volume_id, version, workspace when discoverable.
5. Narrow `cp` to same volume in MVP.
6. Require `--recursive` for directory get/put.
7. Clarify `cat` range semantics: byte range is native; line range is text/index-backed or bounded best effort.
