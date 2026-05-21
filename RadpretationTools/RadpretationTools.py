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

        # Add custom Save Segmentation button to Slicer's standard Segment Editor
        qt.QTimer.singleShot(500, self.addSaveButtonToSegmentEditor)
        
        # Listen to module selection changes to keep Segment Editor button injected
        try:
            slicer.app.moduleManager().connect("moduleAboutToBeSelected(QString)", self.onModuleAboutToBeSelected)
        except Exception as e:
            logger.warning(f"Failed to connect to moduleManager: {e}")

    def onSegmentationChanged(self, has_unsaved_changes):
        self.mainWidget.has_unsaved_changes = has_unsaved_changes
        self.mainWidget.update_save_button_state()
        
        # Keep Segment Editor save button in sync
        if hasattr(self, 'segmentEditorSaveBtn') and self.segmentEditorSaveBtn:
            self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
            self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)

    def addSaveButtonToSegmentEditor(self):
        try:
            segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation()
            if not segmentEditorWidget:
                logger.warning("Segment Editor widget representation not found")
                return

            # Check if our custom controls container already exists
            existing_container = segmentEditorWidget.findChild(qt.QWidget, "RadpretationSegmentEditorControls")
            if existing_container:
                self.segmentEditorSaveBtn = existing_container.findChild(qt.QPushButton, "RadpretationSaveSegButton")
                self.segmentEditorBackBtn = existing_container.findChild(qt.QPushButton, "RadpretationBackToRadButton")
                return

            # Create container widget and horizontal layout
            container = qt.QWidget()
            container.setObjectName("RadpretationSegmentEditorControls")
            buttons_layout = qt.QHBoxLayout(container)
            buttons_layout.setContentsMargins(0, 5, 0, 5)
            buttons_layout.setSpacing(8)

            # Create the Back button
            self.segmentEditorBackBtn = qt.QPushButton("← Back to Radpretation")
            self.segmentEditorBackBtn.setObjectName("RadpretationBackToRadButton")
            self.segmentEditorBackBtn.setStyleSheet("""
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
            """)
            self.segmentEditorBackBtn.connect("clicked()", self.onBackToRadpretationClicked)
            buttons_layout.addWidget(self.segmentEditorBackBtn, 2)

            # Create the Save button
            self.segmentEditorSaveBtn = qt.QPushButton("Save Segmentation")
            self.segmentEditorSaveBtn.setObjectName("RadpretationSaveSegButton")
            self.segmentEditorSaveBtn.setStyleSheet(self.mainWidget.export_seg_btn.styleSheet)
            self.segmentEditorSaveBtn.enabled = self.mainWidget.export_seg_btn.enabled
            self.segmentEditorSaveBtn.connect("clicked()", self.onExportClicked)
            buttons_layout.addWidget(self.segmentEditorSaveBtn, 3)
            
            # Find and add container to Segment Editor layout
            layout = segmentEditorWidget.layout()
            if layout:
                layout.addWidget(container)
                logger.info("Successfully added Save & Back controls to Segment Editor")
            else:
                logger.warning("Segment Editor layout not found")
        except Exception as e:
            logger.error(f"Failed to add save and back controls to Segment Editor: {e}")

    def onModuleAboutToBeSelected(self, moduleName):
        if moduleName == "SegmentEditor":
            logger.info("Segment Editor module selected - ensuring Save button is present")
            qt.QTimer.singleShot(100, self.addSaveButtonToSegmentEditor)

    def onBackToRadpretationClicked(self):
        logger.info("Switching back to RadpretationTools module")
        slicer.util.selectModule("RadpretationTools")

    def onCreateSegmentationClicked(self):
        self.segmentation_service.create_segmentation()
        self.onSegmentationChanged(True)

    def onExportClicked(self):
        for btn in [self.mainWidget.export_seg_btn, getattr(self, 'segmentEditorSaveBtn', None)]:
            if btn:
                btn.setText("Exporting...")
                btn.setStyleSheet("""
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
                btn.enabled = False

        def on_complete(success, message):
            if success:
                # Success state
                for btn in [self.mainWidget.export_seg_btn, getattr(self, 'segmentEditorSaveBtn', None)]:
                    if btn:
                        btn.setText("Uploaded Successfully")
                        btn.setStyleSheet("""
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
                        btn.enabled = False
                
                # Set local state directly to prevent immediate grey reset
                self.mainWidget.has_unsaved_changes = False
                
                # Reset button after 5 seconds
                qt.QTimer.singleShot(5000, self.reset_export_button)
            else:
                for btn in [self.mainWidget.export_seg_btn, getattr(self, 'segmentEditorSaveBtn', None)]:
                    if btn:
                        btn.setText("Export Failed")
                        btn.setStyleSheet("""
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
        self.mainWidget.update_save_button_state()
        
        # Reset Segment Editor button too
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
