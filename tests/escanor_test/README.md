# Escanor

Escanor is a PySide6 desktop app for normalizing scanned PDFs before OCR, review, or extraction.

## Files

- `run_escanor.py` — launcher
- `escanor_settings.ini` — default settings file with hints
- `escanor/` — refactored package
  - `config.py` — config dataclass and load/save helpers
  - `core.py` — processing engine
  - `gui.py` — PySide6 interface

## Install

```bash
pip install PySide6 pymupdf opencv-python numpy
```

## Run

```bash
python run_escanor.py
```

You can also run:

```bash
python -m escanor
```

## Config behavior

Escanor loads `escanor_settings.ini` on startup.

- Edit that file manually to change startup defaults
- Or open the GUI and click **Save Current as Defaults**

## Notes

- Template is mainly used in `content` mode
- `outer_frame` is usually the best starting mode for engineering drawings
- `page_anchor = BR` is a good default when the bottom-right frame corner matters
