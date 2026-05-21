import qt
import slicer
from Services.APIService import APIService
from Services.StudyLoader import StudyLoader
from Utils.logger import logger
from Utils.config import config

class StudiesWidget(qt.QWidget):
    """UI for displaying a list of studies from the Web Application and loading them."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.studies = []
        self.setup_ui()

    def setup_ui(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header controls
        controls_layout = qt.QHBoxLayout()
        self.refresh_btn = qt.QPushButton("Refresh Studies")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        controls_layout.addWidget(self.refresh_btn)
        
        self.status_label = qt.QLabel("")
        controls_layout.addWidget(self.status_label)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)
        
        # Studies Table
        self.table = qt.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Patient Name", "Modality", "Date", "Current Reviewer"])
        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, qt.QHeaderView.Stretch)
        header.setSectionResizeMode(1, qt.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, qt.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qt.QHeaderView.Stretch)
        
        # Connect row double click or single click to load study
        self.table.cellDoubleClicked.connect(self.on_study_double_clicked)
        
        layout.addWidget(self.table)
        
        self.load_btn = qt.QPushButton("Load Selected Study")
        self.load_btn.clicked.connect(self.on_load_clicked)
        layout.addWidget(self.load_btn)

    def on_refresh_clicked(self):
        self.show_status("Fetching studies...")
        self.refresh_btn.setEnabled(False)
        qt.QTimer.singleShot(100, self._do_fetch)

    def _do_fetch(self):
        success, result = APIService.fetch_reports()
        self.refresh_btn.setEnabled(True)
        
        if success:
            self.studies = result
            self.populate_table()
            self.show_status(f"Loaded {len(self.studies)} studies.", error=False)
        else:
            self.show_status(f"Failed: {result}", error=True)

    def populate_table(self):
        self.table.setRowCount(0)
        for i, study in enumerate(self.studies):
            self.table.insertRow(i)
            self.table.setItem(i, 0, qt.QTableWidgetItem(study.patient_name))
            self.table.setItem(i, 1, qt.QTableWidgetItem(study.modalities))
            
            # format date slightly if needed, for now just show as string
            date_str = study.study_date.split("T")[0] if "T" in study.study_date else study.study_date
            self.table.setItem(i, 2, qt.QTableWidgetItem(date_str))
            
            self.table.setItem(i, 3, qt.QTableWidgetItem(study.currentReviewer))

    def on_study_double_clicked(self, row, col):
        self.load_study_at_row(row)

    def on_load_clicked(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            slicer.util.warningDisplay("Please select a study to load.")
            return
            
        row = selected_ranges[0].topRow()
        self.load_study_at_row(row)

    def load_study_at_row(self, row):
        if row < 0 or row >= len(self.studies):
            return
            
        study = self.studies[row]
        
        self.show_status(f"Loading {study.patient_name}...", error=False)
        
        loader = StudyLoader()
        # Ensure we pass the appropriate auth header, config.web_token or None?
        # Note: DICOM Web might need Basic Auth or its own JWT, not the Web App JWT.
        # But wait, does LocalBridgeServer.py use `config.web_token`?
        # Typically the PACS auth is configured in config.auth_mode. 
        # The user's web app JWT is for the web app. The pacs auth might be separate.
        # So we just pass auth_header=None and let StudyLoader use config's get_requests_kwargs.
        
        # Actually, let's just call load_study_remote with the config's get_requests_kwargs auth if needed,
        # but load_study_remote takes auth_header as a param. Let's see what DICOMWebService uses.
        # It handles auth_header internally if provided.
        # LocalBridgeServer extracts auth from the HTTP request headers.
        
        loader.load_study_remote(
            study_model=study,
            auth_header=config.web_token,
            progress_callback=self.on_load_progress,
            completion_callback=self.on_load_complete
        )
        
    def on_load_progress(self, percent, msg):
        self.show_status(f"[{percent}%] {msg}", error=False)
        
    def on_load_complete(self, success):
        if success:
            self.show_status("Study loaded successfully.", error=False)
        else:
            self.show_status("Failed to load study.", error=True)

    def show_status(self, msg, error=False):
        self.status_label.setText(msg)
        if error:
            self.status_label.setStyleSheet("color: #F44336;")
        else:
            self.status_label.setStyleSheet("color: #4CAF50;")
