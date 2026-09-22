"""``xmagic drive``: every Drive route the client speaks, from the command line.

Driven against ``xmagic.testing.FakeXMagic`` rather than route-by-route respx
mocks: the CLI builds a real client, the fake answers in the recorded shapes,
and the assertions read the fake's state and call log. Under ``--json`` each
test parses ``result.stdout`` whole, which is the contract a script relies on.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from xmagic.cli.main import app
from xmagic.testing import FakeXMagic

runner = CliRunner()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeXMagic:
    """The CLI's client, bound to a fake backend instead of the network."""
    backend = FakeXMagic()
    monkeypatch.setattr("xmagic.cli.drive.XMagicClient", lambda **kw: backend.client(**kw))
    return backend


def _json(result: Result) -> Any:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _seed(fake: FakeXMagic, tmp_path: Path) -> tuple[str, str]:
    """A folder with one file in it; returns (folder_id, file_id)."""
    client = fake.client()
    folder = client.drive.create_folder("Docs")
    local = tmp_path / "notes.md"
    local.write_text("# notes\n")
    file = client.drive.upload_file(folder.id, local)
    fake.calls.clear()
    return folder.id, file.id


def test_ls_lists_folders(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, _ = _seed(fake, tmp_path)

    table = runner.invoke(app, ["drive", "ls"])
    listed = _json(runner.invoke(app, ["drive", "ls", "--json"]))

    assert table.exit_code == 0, table.output
    assert folder_id in table.stdout and "Docs" in table.stdout
    assert [(f["id"], f["name"]) for f in listed] == [(folder_id, "Docs")]


def test_ls_folder_lists_its_files(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)

    listed = _json(runner.invoke(app, ["drive", "ls", folder_id, "--json"]))

    assert [(f["id"], f["title"]) for f in listed] == [(file_id, "notes.md")]
    assert fake.calls[-1].params["parent_kb_id"] == folder_id  # plus the page parameters


def test_ls_recursive_pairs_each_folder_with_its_files(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)
    empty = fake.client().drive.create_folder("Empty")

    tree = _json(runner.invoke(app, ["drive", "ls", "-R", "--json"]))
    table = runner.invoke(app, ["drive", "ls", "--recursive"])

    assert [(t["folder"]["id"], [f["id"] for f in t["files"]]) for t in tree] == [
        (folder_id, [file_id]),
        (empty.id, []),
    ]
    assert table.exit_code == 0, table.output
    assert "notes.md" in table.stdout and "Empty" in table.stdout


def test_mkdir_info_rename(fake: FakeXMagic) -> None:
    created = _json(runner.invoke(app, ["drive", "mkdir", "Reports", "--json"]))
    assert created["name"] == "Reports"
    folder_id = created["id"]

    shown = _json(runner.invoke(app, ["drive", "info", folder_id, "--json"]))
    assert shown["id"] == folder_id
    assert fake.calls[-1].params == {"include_counts": "true"}

    renamed = _json(runner.invoke(app, ["drive", "rename", folder_id, "Q3 Reports", "--json"]))
    assert renamed["name"] == "Q3 Reports"
    assert fake.calls[-1].json == {"knowledge_base_name": "Q3 Reports"}
    assert fake.folders[folder_id].name == "Q3 Reports"

    plain = runner.invoke(app, ["drive", "rename", folder_id, "Final"])
    assert plain.exit_code == 0 and "Renamed" in plain.stdout


def test_rm_files_deletes_only_those(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)

    result = _json(runner.invoke(app, ["drive", "rm", folder_id, file_id, "--json"]))

    assert result == {"folder_id": folder_id, "deleted_files": [file_id]}
    assert fake.calls[-1].params == {"data_source_id": file_id}
    assert fake.folders[folder_id].files == {}


def test_rm_folder_asks_first(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, _ = _seed(fake, tmp_path)

    declined = runner.invoke(app, ["drive", "rm", folder_id], input="n\n")
    assert declined.exit_code == 1
    assert folder_id in fake.folders
    assert fake.calls == []

    confirmed = runner.invoke(app, ["drive", "rm", folder_id], input="y\n")
    assert confirmed.exit_code == 0, confirmed.output
    assert folder_id not in fake.folders


def test_rm_folder_with_yes_skips_the_prompt(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, _ = _seed(fake, tmp_path)

    result = _json(runner.invoke(app, ["drive", "rm", folder_id, "--yes", "--json"]))

    assert result == {"folder_id": folder_id, "deleted_folder": True}
    assert fake.calls[-1].method == "DELETE"
    assert folder_id not in fake.folders


def test_download_writes_a_zip(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)
    out = tmp_path / "out.zip"

    result = _json(
        runner.invoke(app, ["drive", "download", folder_id, file_id, "-o", str(out), "--json"])
    )

    assert result["zip"] == str(out) and result["extracted"] == []
    assert zipfile.ZipFile(io.BytesIO(out.read_bytes())).read("notes.md") == b"# notes\n"
    assert fake.calls[-1].params == {"data_source_id": file_id}


def test_download_extract_unpacks_and_keeps_no_zip(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)
    target = tmp_path / "unpacked"

    result = _json(
        runner.invoke(
            app, ["drive", "download", folder_id, file_id, "--extract", str(target), "--json"]
        )
    )

    assert result["zip"] is None
    assert result["extracted"] == [str(target / "notes.md")]
    assert (target / "notes.md").read_text() == "# notes\n"
    assert not list(Path.cwd().glob(f"{folder_id}.zip"))


def test_download_defaults_to_folder_named_zip(
    fake: FakeXMagic, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_id, file_id = _seed(fake, tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["drive", "download", folder_id, file_id])

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{folder_id}.zip").is_file()


def test_errors_go_to_stderr_with_exit_1(fake: FakeXMagic) -> None:
    result = runner.invoke(app, ["drive", "info", "folder-404", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not found" in result.output.lower()


def test_rm_folder_prompt_keeps_json_stdout_clean(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, _ = _seed(fake, tmp_path)

    result = runner.invoke(app, ["drive", "rm", folder_id, "--json"], input="y\n")

    assert result.exit_code == 0, result.output
    # CliRunner echoes the typed "y" into stdout, which a terminal would not;
    # the prompt itself must not be there.
    assert "Delete folder" not in result.stdout
    document = result.stdout[result.stdout.index("{") :]
    assert json.loads(document) == {"folder_id": folder_id, "deleted_folder": True}
    assert folder_id not in fake.folders


def test_download_reports_an_unwritable_output(fake: FakeXMagic, tmp_path: Path) -> None:
    folder_id, file_id = _seed(fake, tmp_path)
    target = tmp_path / "missing" / "out.zip"

    result = runner.invoke(
        app, ["drive", "download", folder_id, file_id, "--output", str(target), "--json"]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    # Rich wraps a long path across lines; compare without the line breaks.
    assert str(target) in result.output.replace("\n", "")
    assert not target.exists()
