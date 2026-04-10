from PySide6.QtWidgets import QMessageBox, QWidget


def ask_append_or_replace(parent: QWidget) -> str:
    box = QMessageBox(parent)
    box.setWindowTitle("Add Input")
    box.setText("Append new items to existing list or replace all?")
    append_btn = box.addButton("Append", QMessageBox.AcceptRole)
    replace_btn = box.addButton("Replace", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked == append_btn:
        return "append"
    if clicked == replace_btn:
        return "replace"
    return "cancel"
