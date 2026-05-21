import ctk
import qt
import slicer

from UI.ViewerWidget import ViewerWidget
from UI.ToolbarWidget import ToolbarWidget
from UI.SettingsWidget import SettingsWidget
from UI.LoginWidget import LoginWidget
from UI.StudiesWidget import StudiesWidget
from Utils.logger import logger
from Utils.config import config

class MainWidget:
    """The main entry point for the Radpretation Slicer UI."""
    def __init__(self, parent_widget, layout):
        self.parent = parent_widget
        self.layout = layout
        self.setup_ui()

    def setup_ui(self):
        logger.info("Setting up Modern MainWidget UI")
        
        # --- Top Header Bar ---
        self.header_layout = qt.QHBoxLayout()
        self.header_layout.setContentsMargins(0, 5, 0, 5)
        
        # Dynamic Login/Logout Button
        self.login_status_btn = qt.QPushButton()
        self.login_status_btn.setFont(qt.QFont("Arial", 9, qt.QFont.Bold))
        self.login_status_btn.clicked.connect(self.on_login_status_btn_clicked)
        self.header_layout.addWidget(self.login_status_btn)
        
        self.header_layout.addStretch(1)
        
        # PACS Settings Icon Button
        self.settings_btn = qt.QPushButton("⚙")
        self.settings_btn.setToolTip("PACS Settings")
        self.settings_btn.setFixedSize(30, 30)
        self.settings_btn.setFont(qt.QFont("Arial", 11, qt.QFont.Bold))
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
        """)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        self.header_layout.addWidget(self.settings_btn)
        
        self.layout.addLayout(self.header_layout)
        
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
        self.create_seg_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                padding: 8px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0098ff;
            }
            QPushButton:pressed {
                background-color: #005999;
            }
        """)
        self.seg_layout.addWidget(self.create_seg_btn)

        self.export_seg_btn = qt.QPushButton("Save Segmentation")
        self.seg_layout.addWidget(self.export_seg_btn)

        self.has_unsaved_changes = False
        
        self.update_save_button_state()

        self.layout.addStretch(1)

        # Trigger auto-login if saved credentials exist
        self.auto_login()

    def on_login_success(self):
        logger.info("Login successful. Updating state...")
        self.update_login_ui_state(logged_in=True)
        self.studies_widget.on_refresh_clicked()

    def update_login_ui_state(self, logged_in):
        if logged_in:
            self.login_status_btn.setText("Logout")
            self.login_status_btn.setEnabled(True)
            self.login_status_btn.setStyleSheet("""
                QPushButton {
                    background-color: #d32f2f;
                    color: white;
                    padding: 6px 15px;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #f44336;
                }
            """)
            self.studies_box.enabled = True
            self.studies_box.collapsed = False
        else:
            self.login_status_btn.setText("Login")
            self.login_status_btn.setEnabled(True)
            self.login_status_btn.setStyleSheet("""
                QPushButton {
                    background-color: #007acc;
                    color: white;
                    padding: 6px 15px;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #0098ff;
                }
            """)
            self.studies_box.enabled = False
            self.studies_box.collapsed = True

    def auto_login(self):
        email = config.web_email
        password = config.web_password
        if email and password:
            logger.info("Saved credentials found, attempting background auto-login...")
            self.login_status_btn.setText("Auto-logging in...")
            self.login_status_btn.setEnabled(False)
            
            def do_background_login():
                from Services.APIService import APIService
                success, message = APIService.login(email, password)
                if success:
                    logger.info("Auto-login successful.")
                    self.on_login_success()
                else:
                    logger.warning(f"Auto-login failed: {message}")
                    self.on_login_failed(message)
            
            qt.QTimer.singleShot(200, do_background_login)
        else:
            self.update_login_ui_state(logged_in=False)

    def on_login_failed(self, message):
        self.update_login_ui_state(logged_in=False)
        slicer.util.errorDisplay(f"Auto-login failed: {message}")

    def on_login_status_btn_clicked(self):
        if config.web_token:
            self.logout()
        else:
            self.open_login_dialog()

    def logout(self):
        logger.info("Logging out, clearing credentials and session token...")
        config.web_token = None
        config.web_email = ""
        config.web_password = ""
        
        self.update_login_ui_state(logged_in=False)
        slicer.util.delayDisplay("Logged out successfully.", 2000)

    def open_login_dialog(self):
        self.login_dialog = qt.QDialog(slicer.util.mainWindow())
        self.login_dialog.setWindowTitle("Web Platform Login")
        self.login_dialog.setMinimumWidth(350)
        self.login_dialog.setMinimumHeight(200)
        dialog_layout = qt.QVBoxLayout(self.login_dialog)
        
        def on_success():
            self.login_dialog.accept()
            self.on_login_success()
            
        login_widget = LoginWidget(parent=self.login_dialog, on_login_success=on_success)
        dialog_layout.addWidget(login_widget)
        self.login_dialog.exec_()

    def open_settings_dialog(self):
        settings_dialog = qt.QDialog(slicer.util.mainWindow())
        settings_dialog.setWindowTitle("PACS Settings")
        settings_dialog.setMinimumWidth(350)
        dialog_layout = qt.QVBoxLayout(settings_dialog)
        
        settings_widget = SettingsWidget(parent=settings_dialog)
        dialog_layout.addWidget(settings_widget)
        settings_dialog.exec_()


    def update_save_button_state(self):
        if self.has_unsaved_changes:
            self.export_seg_btn.enabled = True
            self.export_seg_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ffb74d;
                    color: white;
                    padding: 8px;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #ffa726;
                }
                QPushButton:pressed {
                    background-color: #e65100;
                }
            """)
        else:
            self.export_seg_btn.enabled = False
            self.export_seg_btn.setStyleSheet("""
                QPushButton {
                    background-color: #999999;
                    color: white;
                    padding: 8px;
                    border-radius: 6px;
                    font-size: 11px;
                }
            """)