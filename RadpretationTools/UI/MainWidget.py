import ctk
import qt
import slicer

from UI.ViewerWidget import ViewerWidget
from UI.ToolbarWidget import ToolbarWidget
from UI.SettingsWidget import SettingsWidget
from UI.LoginWidget import LoginWidget
from UI.StudiesWidget import StudiesWidget
from Utils.logger import logger

class MainWidget:
    """The main entry point for the Radpretation Slicer UI."""
    def __init__(self, parent_widget, layout):
        self.parent = parent_widget
        self.layout = layout
        self.setup_ui()

    def setup_ui(self):
        logger.info("Setting up Modern MainWidget UI")
        
        # --- PACS Settings ---
        self.settings_box = ctk.ctkCollapsibleButton()
        self.settings_box.text = "PACS Settings"
        self.settings_box.collapsed = True
        self.layout.addWidget(self.settings_box)
        settings_layout = qt.QVBoxLayout(self.settings_box)
        self.settings_widget = SettingsWidget()
        settings_layout.addWidget(self.settings_widget)
        
        # --- Web Platform Login ---
        self.login_box = ctk.ctkCollapsibleButton()
        self.login_box.text = "Web Platform Login"
        self.layout.addWidget(self.login_box)
        login_layout = qt.QVBoxLayout(self.login_box)
        self.login_widget = LoginWidget(on_login_success=self.on_login_success)
        login_layout.addWidget(self.login_widget)
        
        # --- Web Platform Studies ---
        self.studies_box = ctk.ctkCollapsibleButton()
        self.studies_box.text = "Web Platform Studies"
        self.studies_box.collapsed = True
        self.studies_box.enabled = False # Enabled after login
        self.layout.addWidget(self.studies_box)
        studies_layout = qt.QVBoxLayout(self.studies_box)
        self.studies_widget = StudiesWidget()
        studies_layout.addWidget(self.studies_widget)
        
        # --- Segmentation Actions (to be populated by services) ---
        self.seg_box = ctk.ctkCollapsibleButton()
        self.seg_box.text = "Segmentation Workflow"
        self.layout.addWidget(self.seg_box)
        self.seg_layout = qt.QVBoxLayout(self.seg_box)

        self.create_seg_btn = qt.QPushButton("Create New Segmentation")
        self.seg_layout.addWidget(self.create_seg_btn)

        self.export_seg_btn = qt.QPushButton("Export & Upload to Orthanc")
        self.seg_layout.addWidget(self.export_seg_btn)

        self.seg_status_label = qt.QLabel("Unsaved Changes: False")
        self.seg_layout.addWidget(self.seg_status_label)

        self.layout.addStretch(1)

    def on_login_success(self):
        self.login_box.collapsed = True
        self.studies_box.enabled = True
        self.studies_box.collapsed = False
        self.studies_widget.on_refresh_clicked()
