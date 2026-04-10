from dataclasses import dataclass


@dataclass(slots=True)
class ProgressUpdate:
    file_index: int
    file_total: int
    page_index: int
    page_total: int
    message: str
