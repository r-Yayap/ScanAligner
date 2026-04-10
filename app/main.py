import sys

from PySide6.QtWidgets import QApplication

from app.bootstrap import build_app
from app.config.constants import APP_NAME, APP_ORG


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    view, _ = build_app()
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
