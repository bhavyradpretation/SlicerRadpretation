import qt
from Utils.config import config
from Services.APIService import APIService
from Utils.logger import logger

class LoginWidget(qt.QWidget):
    """UI for Web Application Login."""
    
    # Custom signal to notify when login is successful
    # Since qt.Signal doesn't exist in PythonQt this way easily without QObject subclasses 
    # we can just use a callback function provided by the parent.
    
    def __init__(self, parent=None, on_login_success=None):
        super().__init__(parent)
        self.on_login_success = on_login_success
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        form_layout = qt.QFormLayout()
        
        self.url_edit = qt.QLineEdit()
        self.url_edit.setToolTip("Base URL for Web API (e.g., http://localhost:8000)")
        form_layout.addRow("Web API URL:", self.url_edit)
        
        self.email_edit = qt.QLineEdit()
        form_layout.addRow("Email:", self.email_edit)
        
        self.password_edit = qt.QLineEdit()
        self.password_edit.setEchoMode(qt.QLineEdit.Password)
        form_layout.addRow("Password:", self.password_edit)
        
        layout.addLayout(form_layout)
        
        self.login_btn = qt.QPushButton("Login")
        self.login_btn.clicked.connect(self.on_login_clicked)
        layout.addWidget(self.login_btn)
        
        self.status_label = qt.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        layout.addStretch(1)

    def load_settings(self):
        self.url_edit.setText(config.web_api_url)
        # Maybe remember email in settings? Not for now, unless requested.

    def on_login_clicked(self):
        url = self.url_edit.text.strip()
        email = self.email_edit.text.strip()
        password = self.password_edit.text
        
        if not url or not email or not password:
            self.show_status("Please fill in all fields.", error=True)
            return
            
        # Save URL
        config.web_api_url = url
        
        self.show_status("Logging in...")
        self.login_btn.setEnabled(False)
        
        qt.QTimer.singleShot(100, lambda: self._do_login(email, password))

    def _do_login(self, email, password):
        success, message = APIService.login(email, password)
        self.login_btn.setEnabled(True)
        
        if success:
            self.show_status(message, error=False)
            if self.on_login_success:
                self.on_login_success()
        else:
            self.show_status(f"Login failed: {message}", error=True)

    def show_status(self, msg, error=False):
        self.status_label.setText(msg)
        if error:
            self.status_label.setStyleSheet("color: #F44336;")
        else:
            self.status_label.setStyleSheet("color: #4CAF50;")
