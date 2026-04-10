from pathlib import Path

from app.common.utils.path_utils import expand_pdf_paths


def test_expand_pdf_paths_deduplicates(tmp_path: Path) -> None:
    file1 = tmp_path / "a.pdf"
    file1.write_bytes(b"x")
    paths = expand_pdf_paths([file1, file1])
    assert len(paths) == 1
