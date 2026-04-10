from pathlib import Path

from app.common.utils.path_utils import expand_pdf_paths
from app.domain.models.document_task import DocumentTask


class FileDiscoveryService:
    def build_tasks(self, inputs: list[Path], output_dir: Path, suffix: str, overwrite: bool) -> list[DocumentTask]:
        files = expand_pdf_paths(inputs)
        tasks: list[DocumentTask] = []
        for path in files:
            root = path.parent
            name = f"{path.stem}{suffix}.pdf"
            output = output_dir / name
            if output.exists() and not overwrite:
                continue
            tasks.append(DocumentTask(path, output, root))
        return tasks
