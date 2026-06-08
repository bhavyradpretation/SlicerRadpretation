import os
import qt
import slicer

from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from UI.MainWidget import MainWidget
from Utils.logger import logger
from Utils.ui_styles import (
    PRIMARY_BUTTON,
    SECONDARY_BUTTON,
    DANGER_BUTTON,
    DISABLED_BUTTON,
    SAVE_BUTTON_EXPORTING,
    SAVE_BUTTON_FAILED,
    SAVE_BUTTON_SUCCESS,
)

# Save button transient labels — do not overwrite these with idle amber/grey styles
_SAVE_BUTTON_FEEDBACK_LABELS = frozenset({
    "Exporting...",
    "Uploaded Successfully",
    "Export Failed",
})

BACK_TO_RAD_BUTTON_STYLE = """
    QPushButton {
        background-color: #333333;
        color: white;
        padding: 8px;
        border: 1px solid #555555;
        border-radius: 6px;
        font-weight: bold;
        font-size: 11px;
    }
    QPushButton:hover {
        background-color: #444444;
    }
    QPushButton:pressed {
        background-color: #222222;
    }
"""

class RadpretationTools(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RadpretationTools"
        self.parent.categories = ["Radpretation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Bhavy Raheja"]
        self.parent.helpText = "Radpretation Advanced Workstation integration for 3D Slicer."
        self.parent.acknowledgementText = "Developed for Radpretation."
        
        # Auto-open module on startup when main window is ready
        if not slicer.app.commandOptions().noMainWindow:
            slicer.app.connect("startupCompleted()", self.autoOpenModule)

    def autoOpenModule(self):
        logger.info("Automatically selecting RadpretationTools module on startup")
        slicer.util.selectModule("RadpretationTools")



class RadpretationToolsWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.mainWidget = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        logger.info("Initializing RadpretationToolsWidget setup")

        # Instantiate the UI architecture
        self.mainWidget = MainWidget(self, self.layout)
        
        # Connections will be established below

        # Instantiate Services
        from Services.SegmentationService import SegmentationService
        from Services.ExportService import ExportService
        from Services.LocalBridgeServer import LocalBridgeServer
        from Utils.helpers import MainThreadDispatcher

        # Initialize the dispatcher on the main thread so its QTimer is bound to Slicer's main event loop
        MainThreadDispatcher.get_instance()

        self.segmentation_service = SegmentationService(self.onSegmentationChanged)
        self.export_service = ExportService(self.segmentation_service)
        
        # Add Slicer scene node observers to update Segment Editor controls dynamically
        self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onSceneNodeChanged)
        self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeRemovedEvent, self.onSceneNodeChanged)
        
        self.local_bridge_server = LocalBridgeServer(self.mainWidget)
        self.local_bridge_server.start()

        # Connect UI Buttons
        self.mainWidget.export_seg_btn.connect("clicked()", self.onExportClicked)

        # Add custom Save Segmentation button to Slicer's standard Segment Editor
        qt.QTimer.singleShot(500, self.addSaveButtonToSegmentEditor)
        
        # Listen to module selection changes to keep Segment Editor button injected
        try:
            slicer.app.moduleManager().connect("moduleAboutToBeSelected(QString)", self.onModuleAboutToBeSelected)
        except Exception as e:
            logger.warning(f"Failed to connect to moduleManager: {e}")

    def onSegmentationChanged(self, has_unsaved_changes):
        self.mainWidget.has_unsaved_changes = has_unsaved_changes
        self.refreshSaveButtonState()

    def _save_button_in_feedback_state(self):
        return self.mainWidget.export_seg_btn.text in _SAVE_BUTTON_FEEDBACK_LABELS

    def _set_save_button_feedback(self, text, stylesheet, enabled=False):
        """Apply export progress / success / failure styling to both Save buttons."""
        for btn in [self.mainWidget.export_seg_btn, getattr(self, "segmentEditorSaveBtn", None)]:
            if btn:
                btn.setText(text)
                btn.setStyleSheet(stylesheet)
                btn.enabled = enabled

    def refreshSaveButtonState(self):
        """Enable Save when a segmentation is present and export-ready."""
        if self._save_button_in_feedback_state():
            return

        ready, _ = self.segmentation_service.validate_export_ready()
        self.mainWidget.save_available = ready
        self.mainWidget.update_save_button_state()

        if hasattr(self, "segmentEditorSaveBtn") and self.segmentEditorSaveBtn:
            self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
            self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)

    def addSaveButtonToSegmentEditor(self):
        try:
            segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation()
            if not segmentEditorWidget:
                logger.warning("Segment Editor widget representation not found")
                return

            # Keep Radpretation's "active segmentation" in sync with Segment Editor's selector.
            # Without this, Save can operate on a stale/cached segmentation node when the user
            # switches to a different segmentation in the Segment Editor UI.
            self._connectSegmentEditorSegmentationSelector(segmentEditorWidget)

            # Check if our custom controls container already exists
            existing_container = segmentEditorWidget.findChild(qt.QWidget, "RadpretationSegmentEditorControls")
            if existing_container:
                self.segmentEditorCreateBtn = existing_container.findChild(qt.QPushButton, "RadpretationCreateSegButton")
                self.segmentEditorDeleteBtn = existing_container.findChild(qt.QPushButton, "RadpretationDeleteSegButton")
                self.segmentEditorRenameBtn = existing_container.findChild(qt.QPushButton, "RadpretationRenameSegButton")
                self.segmentEditorBackBtn = existing_container.findChild(qt.QPushButton, "RadpretationBackToRadButton")
                self.segmentEditorSaveBtn = existing_container.findChild(qt.QPushButton, "RadpretationSaveSegButton")
                
                # Reconnect buttons to the current widget instance's callbacks
                for btn, callback in [
                    (self.segmentEditorCreateBtn, self.onCreateSegClicked),
                    (self.segmentEditorRenameBtn, self.onRenameSegClicked),
                    (self.segmentEditorDeleteBtn, self.onDeleteSegClicked),
                    (self.segmentEditorBackBtn, self.onBackToRadpretationClicked),
                    (self.segmentEditorSaveBtn, self.onExportClicked),
                ]:
                    if btn:
                        try:
                            btn.disconnect("clicked()")
                        except Exception:
                            pass
                        btn.connect("clicked()", callback)

                if self.segmentEditorBackBtn:
                    self.segmentEditorBackBtn.setStyleSheet(BACK_TO_RAD_BUTTON_STYLE)
                if self.segmentEditorSaveBtn:
                    self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)
                    self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
                self.updateSegmentEditorButtonsState()
                return

            # Create container widget and vertical layout for extra control and neat layout
            container = qt.QWidget()
            container.setObjectName("RadpretationSegmentEditorControls")
            
            main_controls_layout = qt.QVBoxLayout(container)
            main_controls_layout.setContentsMargins(0, 10, 0, 5)
            main_controls_layout.setSpacing(10)

            # Row 1: Segmentation Management Actions (Create, Delete, Rename)
            row1_layout = qt.QHBoxLayout()
            row1_layout.setSpacing(8)

            # 1. Create Button
            self.segmentEditorCreateBtn = qt.QPushButton("✚ Create")
            self.segmentEditorCreateBtn.setObjectName("RadpretationCreateSegButton")
            self.segmentEditorCreateBtn.setToolTip("Create a new segmentation node (Limit: 1 active)")
            self.segmentEditorCreateBtn.connect("clicked()", self.onCreateSegClicked)
            row1_layout.addWidget(self.segmentEditorCreateBtn, 1)

            # 2. Rename Button
            self.segmentEditorRenameBtn = qt.QPushButton("✏ Rename")
            self.segmentEditorRenameBtn.setObjectName("RadpretationRenameSegButton")
            self.segmentEditorRenameBtn.setToolTip("Rename the active segmentation node")
            self.segmentEditorRenameBtn.connect("clicked()", self.onRenameSegClicked)
            row1_layout.addWidget(self.segmentEditorRenameBtn, 1)

            # 3. Delete Button
            self.segmentEditorDeleteBtn = qt.QPushButton("🗑 Delete")
            self.segmentEditorDeleteBtn.setObjectName("RadpretationDeleteSegButton")
            self.segmentEditorDeleteBtn.setToolTip("Delete the active segmentation node")
            self.segmentEditorDeleteBtn.connect("clicked()", self.onDeleteSegClicked)
            row1_layout.addWidget(self.segmentEditorDeleteBtn, 1)

            main_controls_layout.addLayout(row1_layout)

            # Row 2: Standard Navigation / Sync Actions (Back, Save)
            row2_layout = qt.QHBoxLayout()
            row2_layout.setSpacing(8)

            # Back button
            self.segmentEditorBackBtn = qt.QPushButton("← Back to Radpretation")
            self.segmentEditorBackBtn.setObjectName("RadpretationBackToRadButton")
            self.segmentEditorBackBtn.setStyleSheet(BACK_TO_RAD_BUTTON_STYLE)
            self.segmentEditorBackBtn.connect("clicked()", self.onBackToRadpretationClicked)
            row2_layout.addWidget(self.segmentEditorBackBtn, 2)

            # Save button
            self.segmentEditorSaveBtn = qt.QPushButton("Save Segmentation")
            self.segmentEditorSaveBtn.setObjectName("RadpretationSaveSegButton")
            self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)
            self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
            self.segmentEditorSaveBtn.connect("clicked()", self.onExportClicked)
            row2_layout.addWidget(self.segmentEditorSaveBtn, 3)

            main_controls_layout.addLayout(row2_layout)
            
            # Find and add container to Segment Editor layout
            layout = segmentEditorWidget.layout()
            if layout:
                layout.addWidget(container)
                logger.info("Successfully added full Radpretation control suite to Segment Editor")
                self.updateSegmentEditorButtonsState()
            else:
                logger.warning("Segment Editor layout not found")
        except Exception as e:
            logger.error(f"Failed to add save and back controls to Segment Editor: {e}")

    def _connectSegmentEditorSegmentationSelector(self, segmentEditorWidget):
        """Connect Segment Editor's segmentation selector to our state."""
        try:
            # Find the qMRMLNodeComboBox that selects a vtkMRMLSegmentationNode.
            selector = None
            try:
                combos = segmentEditorWidget.findChildren(slicer.qMRMLNodeComboBox)
            except Exception:
                combos = []

            for cb in combos:
                try:
                    nodeTypes = getattr(cb, "nodeTypes", None)
                    if nodeTypes and "vtkMRMLSegmentationNode" in list(nodeTypes):
                        selector = cb
                        break
                    nodeType = getattr(cb, "nodeType", None)
                    if nodeType == "vtkMRMLSegmentationNode":
                        selector = cb
                        break
                except Exception:
                    continue

            if not selector:
                # Segment Editor may not be fully initialized yet; we'll retry on next injection.
                logger.debug("Could not locate Segment Editor segmentation selector yet.")
                return

            # If selector has changed or we haven't connected yet, connect it.
            if not getattr(self, "_segSelectorConnected", False) or getattr(self, "_segmentEditorSegSelector", None) != selector:
                old_selector = getattr(self, "_segmentEditorSegSelector", None)
                if old_selector:
                    try:
                        old_selector.disconnect("currentNodeChanged(vtkMRMLNode*)")
                    except Exception:
                        pass
                
                self._segmentEditorSegSelector = selector
                selector.connect("currentNodeChanged(vtkMRMLNode*)", self.onEditorSegmentationNodeChanged)
                self._segSelectorConnected = True
                logger.info("Connected Segment Editor segmentation selector to Radpretation state.")

            # Always ensure the selector's current node matches our active segmentation node
            active_node = self.segmentation_service.active_segmentation_node
            if active_node and selector.currentNode() != active_node:
                logger.info(f"Syncing selector currentNode to active segmentation node: {active_node.GetName()}")
                try:
                    # Temporarily block signals to avoid triggering onEditorSegmentationNodeChanged again recursively
                    selector.blockSignals(True)
                    selector.setCurrentNode(active_node)
                finally:
                    selector.blockSignals(False)
        except Exception as e:
            logger.debug(f"Failed to connect Segment Editor segmentation selector: {e}")

    def onModuleAboutToBeSelected(self, moduleName):
        if moduleName == "SegmentEditor":
            logger.info("Segment Editor module selected - ensuring Save button is present")
            qt.QTimer.singleShot(100, self.addSaveButtonToSegmentEditor)

    def onBackToRadpretationClicked(self):
        logger.info("Switching back to RadpretationTools module")
        slicer.util.selectModule("RadpretationTools")

    def onEditorSegmentationNodeChanged(self, node):
        logger.info(f"Editor segmentation node changed: {node.GetName() if node else 'None'}")
        
        current_node = self.segmentation_service.active_segmentation_node
        if current_node != node:
            self.segmentation_service.active_segmentation_node = node
            
            if node:
                self.segmentation_service._start_tracking()
                self.segmentation_service._ensure_default_segment(node)
                
                ref_vol_id = node.GetNodeReferenceID("ReferenceVolumeGeometry")
                if not ref_vol_id:
                    vol = self.segmentation_service._resolve_reference_volume()
                    if vol:
                        self.segmentation_service._link_segmentation_to_volume(node, vol)
            else:
                self.segmentation_service.observer_manager.remove_all()
                
            # Retrieve the correct, node-specific unsaved changes state
            has_changes = self.segmentation_service.has_unsaved_changes
            self.onSegmentationChanged(has_changes)
            
        self.updateSegmentEditorButtonsState()

    def onSceneNodeChanged(self, caller, event):
        self.updateSegmentEditorButtonsState()

    def finalizeStudyLoad(self, load_dicom_seg=True, retry_count=0):
        """Always open Segment Editor with active segmentation after a study loads.

        load_dicom_seg: when True, wait for SEG series imported from PACS; when False, create a new seg.
        """
        max_retries = 10

        volumes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        if not volumes and retry_count < max_retries:
            qt.QTimer.singleShot(
                400, lambda: self.finalizeStudyLoad(load_dicom_seg, retry_count + 1)
            )
            return

        seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        if seg_nodes:
            loaded_seg = list(seg_nodes)[0]
            logger.info(f"Activating segmentation after study load: {loaded_seg.GetName()}")
            self.segmentation_service.set_active_segmentation(loaded_seg)
        elif load_dicom_seg and retry_count < max_retries:
            qt.QTimer.singleShot(
                400, lambda: self.finalizeStudyLoad(load_dicom_seg, retry_count + 1)
            )
            return
        else:
            logger.info("Creating new segmentation for Segment Editor after study load.")
            if self.segmentation_service.create_segmentation():
                self.onSegmentationChanged(False)

        qt.QTimer.singleShot(200, self.addSaveButtonToSegmentEditor)
        self.updateSegmentEditorButtonsState()
        self.refreshSaveButtonState()

    def onCreateSegClicked(self):
        if self.segmentation_service.create_segmentation():
            self.onSegmentationChanged(self.segmentation_service.has_unsaved_changes)
        self.updateSegmentEditorButtonsState()
        self.refreshSaveButtonState()

    def onDeleteSegClicked(self):
        if not self.segmentation_service.resolve_active_segmentation():
            slicer.util.warningDisplay("No active segmentation node found to delete.")
            return

        confirm = slicer.util.confirmOkCancelDisplay(
            "Are you sure you want to delete the active segmentation? This action cannot be undone.",
            "Confirm Deletion"
        )
        if confirm:
            self.segmentation_service.delete_segmentation()
            self.onSegmentationChanged(False)
            self.updateSegmentEditorButtonsState()
            self.refreshSaveButtonState()

    def onRenameSegClicked(self):
        node = self.segmentation_service.resolve_active_segmentation()
        if not node:
            slicer.util.warningDisplay("No segmentation is loaded. Create or load one first.")
            return

        current_name = node.GetName()
        while True:
            dialog = qt.QInputDialog(slicer.util.mainWindow())
            dialog.setWindowTitle("Rename Segmentation")
            dialog.setLabelText("Enter a new name for this segmentation:")
            dialog.setTextValue(current_name)
            
            if not dialog.exec_():
                return
                
            new_name = dialog.textValue().strip()
            success, message = self.segmentation_service.rename_active_segmentation(new_name)
            if success:
                slicer.util.infoDisplay(f"Renamed to '{message}'", windowTitle="Rename")
                self.updateSegmentEditorButtonsState()
                self.refreshSaveButtonState()
                return
            slicer.util.warningDisplay(message, windowTitle="Rename Segmentation")
            current_name = new_name or current_name

    def updateSegmentEditorButtonsState(self):
        try:
            existing_segs = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
            has_seg = len(existing_segs) > 0
            
            # Keep segmentation service active node in sync with Segment Editor widget's actual selection
            try:
                segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation()
                if segmentEditorWidget:
                    editor = segmentEditorWidget.self().editor
                    if editor and editor.segmentationNode():
                        self.segmentation_service.active_segmentation_node = editor.segmentationNode()
            except Exception as e:
                logger.debug(f"Could not read Segment Editor active node: {e}")

            if hasattr(self, "segmentEditorCreateBtn") and self.segmentEditorCreateBtn:
                self.segmentEditorCreateBtn.enabled = True
                self.segmentEditorCreateBtn.setStyleSheet(PRIMARY_BUTTON)

            if hasattr(self, "segmentEditorDeleteBtn") and self.segmentEditorDeleteBtn:
                self.segmentEditorDeleteBtn.enabled = has_seg
                self.segmentEditorDeleteBtn.setStyleSheet(
                    DANGER_BUTTON if has_seg else DISABLED_BUTTON
                )

            if hasattr(self, "segmentEditorRenameBtn") and self.segmentEditorRenameBtn:
                self.segmentEditorRenameBtn.enabled = has_seg
                self.segmentEditorRenameBtn.setStyleSheet(
                    SECONDARY_BUTTON if has_seg else DISABLED_BUTTON
                )
            self.refreshSaveButtonState()
        except Exception as e:
            logger.error(f"Error updating Segment Editor buttons: {e}")

    def onCreateSegmentationClicked(self):
        # Legacy callback for backward compatibility or direct calls
        self.onCreateSegClicked()

    def onExportClicked(self):
        ready, message = self.segmentation_service.prepare_for_export()
        if not ready:
            slicer.util.errorDisplay(message, windowTitle="Save Segmentation")
            self.refreshSaveButtonState()
            return

        self._set_save_button_feedback("Exporting...", SAVE_BUTTON_EXPORTING, enabled=False)

        def on_complete(success, message):
            if success:
                # ExportService.mark_saved() already cleared unsaved state; keep green visible
                self.mainWidget.has_unsaved_changes = False
                self._set_save_button_feedback(
                    "Uploaded Successfully", SAVE_BUTTON_SUCCESS, enabled=False
                )
                qt.QTimer.singleShot(5000, self.reset_export_button)
            else:
                self._set_save_button_feedback("Export Failed", SAVE_BUTTON_FAILED)

                slicer.util.errorDisplay(
                    message or "Failed to save segmentation.",
                    windowTitle="Save Segmentation",
                )
                qt.QTimer.singleShot(5000, self.reset_export_button)

        self.export_service.export_and_upload(on_complete)

    def cleanup(self):
        try:
            slicer.app.moduleManager().disconnect("moduleAboutToBeSelected(QString)", self.onModuleAboutToBeSelected)
        except Exception as e:
            logger.debug(f"Could not disconnect moduleAboutToBeSelected: {e}")
            
        if hasattr(self, 'local_bridge_server'):
            self.local_bridge_server.stop()
        if hasattr(self, 'segmentation_service'):
            self.segmentation_service.observer_manager.remove_all()
        self.removeObservers()

    def reset_export_button(self):
        self.mainWidget.export_seg_btn.setText("Save Segmentation")
        self.refreshSaveButtonState()

        if hasattr(self, 'segmentEditorSaveBtn') and self.segmentEditorSaveBtn:
            self.segmentEditorSaveBtn.setText("Save Segmentation")
            self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
            self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)

class RadpretationToolsLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)

class RadpretationToolsTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
