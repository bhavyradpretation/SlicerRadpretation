import qt
import ctk
from Utils.config import config
from Utils.logger import logger

class SettingsWidget(qt.QWidget):
    """UI for managing PACS and DICOMweb settings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = qt.QFormLayout(self)
        
        # PACS URL
        self.pacs_url_edit = qt.QLineEdit()
        self.pacs_url_edit.setToolTip("Base URL for Orthanc/PACS (e.g., http://localhost:8042)")
        layout.addRow("PACS URL:", self.pacs_url_edit)
        
        # DICOMWeb Path
        self.dicomweb_path_edit = qt.QLineEdit()
        self.dicomweb_path_edit.setToolTip("Path to DICOMweb endpoint (e.g., /dicom-web)")
        layout.addRow("DICOMWeb Path:", self.dicomweb_path_edit)
        
        # Authentication Mode
        self.auth_mode_combo = qt.QComboBox()
        self.auth_mode_combo.addItems(["None", "Basic Auth"])
        self.auth_mode_combo.currentIndexChanged.connect(self.on_auth_mode_changed)
        layout.addRow("Authentication Mode:", self.auth_mode_combo)
        
        # Username
        self.username_edit = qt.QLineEdit()
        self.username_label = qt.QLabel("Username:")
        layout.addRow(self.username_label, self.username_edit)
        
        # Password
        self.password_edit = qt.QLineEdit()
        self.password_edit.setEchoMode(qt.QLineEdit.Password)
        self.password_label = qt.QLabel("Password:")
        layout.addRow(self.password_label, self.password_edit)
        
        # Save Button
        self.save_btn = qt.QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addRow(self.save_btn)
        
        # Status Label
        self.status_label = qt.QLabel("")
        layout.addRow(self.status_label)

    def load_settings(self):
        self.pacs_url_edit.setText(config.pacs_url)
        self.dicomweb_path_edit.setText(config.dicomweb_path)
        self.auth_mode_combo.setCurrentText(config.auth_mode)
        self.username_edit.setText(config.username)
        self.password_edit.setText(config.password)
        self.on_auth_mode_changed()

    def on_auth_mode_changed(self):
        is_basic = self.auth_mode_combo.currentText == "Basic Auth"
        self.username_label.setVisible(is_basic)
        self.username_edit.setVisible(is_basic)
        self.password_label.setVisible(is_basic)
        self.password_edit.setVisible(is_basic)

    def save_settings(self):
        config.pacs_url = self.pacs_url_edit.text.strip()
        config.dicomweb_path = self.dicomweb_path_edit.text.strip()
        config.auth_mode = self.auth_mode_combo.currentText
        config.username = self.username_edit.text.strip()
        config.password = self.password_edit.text
        
        logger.info(f"PACS Settings saved. URL: {config.pacs_url}, Auth: {config.auth_mode}")
        
        self.status_label.setText("Settings saved successfully!")
        self.status_label.setStyleSheet("color: #4CAF50;") # Green color
        
        # Close parent QDialog after 5 seconds
        parent = self.parent()
        while parent:
            if isinstance(parent, qt.QDialog):
                qt.QTimer.singleShot(1000, parent.accept)
                break
            parent = parent.parent()
