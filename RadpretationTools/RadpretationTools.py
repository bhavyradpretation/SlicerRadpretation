import os
import qt
import slicer

from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from UI.MainWidget import MainWidget
from Utils.logger import logger

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
        
        self.local_bridge_server = LocalBridgeServer(self.mainWidget)
        self.local_bridge_server.start()

        # Connect UI Buttons
        self.mainWidget.create_seg_btn.connect("clicked()", self.onCreateSegmentationClicked)
        self.mainWidget.export_seg_btn.connect("clicked()", self.onExportClicked)

    def onSegmentationChanged(self, has_unsaved_changes):
        self.mainWidget.has_unsaved_changes = has_unsaved_changes
        self.mainWidget.update_save_button_state()

    def onCreateSegmentationClicked(self):
        self.segmentation_service.create_segmentation()
        self.onSegmentationChanged(True)

    def onExportClicked(self):
        self.mainWidget.export_seg_btn.setText("Exporting...")
        self.mainWidget.export_seg_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef6c00;
                color: white;
                padding: 8px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:disabled {
                background-color: #ef6c00;
                color: white;
            }
        """)
        self.mainWidget.export_seg_btn.enabled = False

        def on_complete(success, message):
            if success:
                # Success state
                self.mainWidget.export_seg_btn.setText("Uploaded Successfully")
                self.mainWidget.export_seg_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #009600;
                        color: white;
                        padding: 8px;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                    QPushButton:disabled {
                        background-color: #009600;
                        color: white;
                    }
                """)
                # Set local state directly to prevent immediate grey reset
                self.mainWidget.has_unsaved_changes = False
                self.mainWidget.export_seg_btn.enabled = False
                
                # Reset button after 5 seconds
                qt.QTimer.singleShot(5000, self.reset_export_button)
            else:
                self.mainWidget.export_seg_btn.setText("Export Failed")
                self.mainWidget.export_seg_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #c62828;
                        color: white;
                        padding: 8px;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                    QPushButton:disabled {
                        background-color: #c62828;
                        color: white;
                    }
                """)
                # Reset button after 5 seconds on failure to allow retry
                qt.QTimer.singleShot(5000, self.reset_export_button)

        self.export_service.export_and_upload(on_complete)

    def cleanup(self):
        if hasattr(self, 'local_bridge_server'):
            self.local_bridge_server.stop()
        if hasattr(self, 'segmentation_service'):
            self.segmentation_service.observer_manager.remove_all()
        self.removeObservers()

    def reset_export_button(self):
        self.mainWidget.export_seg_btn.setText("Save Segmentation")
        self.mainWidget.update_save_button_state()

class RadpretationToolsLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)

class RadpretationToolsTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
