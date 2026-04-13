from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from conftest_qt import QtSmokeBase


class WorkspaceWidgetPrimitiveTests(QtSmokeBase):
    def test_master_checkbox_toggles_like_binary_control(self):
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import MasterCheckBox

        widget = MasterCheckBox("Select All")
        widget.setCheckState(Qt.CheckState.PartiallyChecked)

        widget.nextCheckState()
        self.assertEqual(widget.checkState(), Qt.CheckState.Checked)

        widget.nextCheckState()
        self.assertEqual(widget.checkState(), Qt.CheckState.Unchecked)
        widget.close()

    def test_elided_label_sets_tooltip_only_when_elided(self):
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import ElidedLabel

        full_text = "A very long movie title that should be truncated"
        host = QWidget()
        host.resize(240, 60)
        label = ElidedLabel(full_text, parent=host)
        label.resize(60, 20)
        host.show()
        label.show()
        self._app.processEvents()

        self.assertTrue(label.toolTip())

        host.resize(800, 60)
        label.resize(label.fontMetrics().horizontalAdvance(full_text) + 20, 20)
        self._app.processEvents()

        self.assertEqual(label.toolTip(), "")
        host.close()

    def test_folder_preview_row_preserves_full_target_tooltip(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import FolderPreviewRowWidget

        widget = FolderPreviewRowWidget(
            "Some Extremely Long Source Folder Name",
            "Some Extremely Long Target Folder Name",
        )

        self.assertEqual(widget._target.toolTip(), "Some Extremely Long Target Folder Name")
        widget.close()