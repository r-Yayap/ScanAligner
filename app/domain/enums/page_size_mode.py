from enum import Enum


class PageSizeMode(str, Enum):
    PRESERVE_DOMINANT = "preserve_dominant"
    FORCE_UNIFORM = "force_uniform"
    FIT_TO_CONTENT = "fit_to_content"
