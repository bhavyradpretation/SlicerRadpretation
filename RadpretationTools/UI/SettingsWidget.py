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
        
        # Cache Settings Section
        self.cache_header = qt.QLabel("Cache Settings")
        self.cache_header.setFont(qt.QFont("Arial", 9, qt.QFont.Bold))
        layout.addRow("", self.cache_header)

        # Cache Retention
        self.cache_days_combo = qt.QComboBox()
        self.cache_days_combo.addItem("1 Day", 1)
        self.cache_days_combo.addItem("3 Days (Recommended)", 3)
        self.cache_days_combo.addItem("5 Days", 5)
        self.cache_days_combo.addItem("Never Clear", 9999)
        layout.addRow("Cache Retention:", self.cache_days_combo)
        
        # Clear Cache Button
        self.clear_cache_btn = qt.QPushButton("Clear Cache Now")
        self.clear_cache_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
                padding: 5px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f44336;
            }
        """)
        self.clear_cache_btn.clicked.connect(self.on_clear_cache_clicked)
        layout.addRow("", self.clear_cache_btn)

        # Spacer before Save Button
        layout.addRow("", qt.QLabel(""))

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

        # Load cache retention
        retention = config.cache_retention_days
        for idx in range(self.cache_days_combo.count):
            if self.cache_days_combo.itemData(idx) == retention:
                self.cache_days_combo.currentIndex = idx
                break

    def on_auth_mode_changed(self):
        is_basic = self.auth_mode_combo.currentText == "Basic Auth"
        self.username_label.setVisible(is_basic)
        self.username_edit.setVisible(is_basic)
        self.password_label.setVisible(is_basic)
        self.password_edit.setVisible(is_basic)

    def on_clear_cache_clicked(self):
        confirm = qt.QMessageBox.question(
            self,
            "Clear DICOM Cache",
            "Are you sure you want to completely clear the local DICOM cache? This will delete all downloaded studies.",
            qt.QMessageBox.Yes | qt.QMessageBox.No
        )
        if confirm == qt.QMessageBox.Yes:
            from Services.CacheManager import CacheManager
            cache_mgr = CacheManager()
            cache_mgr.clear_all_cache()
            qt.QMessageBox.information(self, "Cache Cleared", "The DICOM cache has been completely cleared.")

    def save_settings(self):
        config.pacs_url = self.pacs_url_edit.text.strip()
        config.dicomweb_path = self.dicomweb_path_edit.text.strip()
        config.auth_mode = self.auth_mode_combo.currentText
        config.username = self.username_edit.text.strip()
        config.password = self.password_edit.text
        
        # Save cache retention days
        selected_index = self.cache_days_combo.currentIndex
        retention_days = self.cache_days_combo.itemData(selected_index)
        if retention_days is not None:
            config.cache_retention_days = int(retention_days)
        
        logger.info(f"PACS Settings saved. URL: {config.pacs_url}, Auth: {config.auth_mode}, Cache Retention: {config.cache_retention_days} days")
        
        self.status_label.setText("Settings saved successfully!")
        self.status_label.setStyleSheet("color: #4CAF50;") # Green color
        
        # Close parent QDialog after 1 second
        parent = self.parent()
        while parent:
            if isinstance(parent, qt.QDialog):
                qt.QTimer.singleShot(1000, parent.accept)
                break
            parent = parent.parent()
