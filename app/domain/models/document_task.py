from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DocumentTask:
    input_path: Path
    output_path: Path
    root_path: Path
