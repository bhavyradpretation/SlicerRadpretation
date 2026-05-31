import qt
import slicer
from Services.APIService import APIService
from Services.StudyLoader import StudyLoader
from Utils.logger import logger
from Utils.config import config
from Utils.ui_styles import SECONDARY_BUTTON, SUCCESS_BUTTON, DISABLED_BUTTON

class StudiesWidget(qt.QWidget):
    """UI for displaying a list of studies from the Web Application and loading them."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.studies = []
        self.current_page = 1
        self.total_pages = 1
        self.limit = 8
        
        # Debounce timer for search
        self.search_timer = qt.QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(500)  # 500ms debounce
        self.search_timer.timeout.connect(self.on_search_debounced)
        
        self.setup_ui()

    def setup_ui(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        
        # Header controls (Top Bar)
        controls_layout = qt.QHBoxLayout()
        controls_layout.setSpacing(8)
        
        self.search_input = qt.QLineEdit()
        self.search_input.setPlaceholderText(" 🔍   Search patient name...")
        self.search_input.setMinimumWidth(120)
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 7px 12px;
                border: 1px solid rgba(128, 128, 128, 0.3);
                border-radius: 6px;
                background-color: rgba(128, 128, 128, 0.05);
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #007acc;
                background-color: rgba(128, 128, 128, 0.08);
            }
        """)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.on_refresh_clicked)
        controls_layout.addWidget(self.search_input)
        
        self.refresh_btn = qt.QPushButton("Reload Studies")
        self.refresh_btn.setToolTip("Reload Studies List")
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.setStyleSheet(SECONDARY_BUTTON)
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        controls_layout.addWidget(self.refresh_btn)
        
        self.seg_toggle_btn = qt.QPushButton()
        self.seg_toggle_btn.setToolTip("Toggle loading segmentation files automatically")
        self.seg_toggle_btn.setFixedHeight(32)
        self.seg_toggle_btn.setCheckable(True)
        self.seg_toggle_btn.setChecked(config.load_with_seg)
        self.seg_toggle_btn.toggled.connect(self.on_seg_toggle_toggled)
        self.update_seg_toggle_style()
        controls_layout.addWidget(self.seg_toggle_btn)
        
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)
        
        # Studies Table
        self.table = qt.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Patient ID", "Patient Name", "Modality"])
        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                alternate-background-color: rgba(128, 128, 128, 0.03);
                gridline-color: rgba(128, 128, 128, 0.1);
                border: 1px solid rgba(128, 128, 128, 0.2);
                border-radius: 8px;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid rgba(128, 128, 128, 0.08);
            }
            QTableWidget::item:selected {
                background-color: rgba(0, 122, 204, 0.15);
                color: inherit;
            }
            QHeaderView::section {
                background-color: rgba(128, 128, 128, 0.05);
                padding: 8px;
                border: none;
                border-bottom: 2px solid #007acc;
                font-weight: bold;
                color: inherit;
            }
        """)
        
        # Hide vertical header row indices
        self.table.verticalHeader().setVisible(False)
        
        # Lock header and table heights to fit exactly 8 rows without scrolling
        self.table.horizontalHeader().setFixedHeight(32)
        self.table.setFixedHeight(276) # 32px header + 8 rows * 30px + 4px borders
        self.table.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, qt.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qt.QHeaderView.Stretch)
        header.setSectionResizeMode(2, qt.QHeaderView.ResizeToContents)
        
        # Connect row double click or single click to load study
        self.table.cellDoubleClicked.connect(self.on_study_double_clicked)
        layout.addWidget(self.table)
        
        # Pagination Layout
        pagination_layout = qt.QHBoxLayout()
        pagination_layout.setContentsMargins(0, 4, 0, 4)
        
        self.prev_btn = qt.QPushButton("◀")
        self.prev_btn.setFixedSize(36, 28)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(128, 128, 128, 0.05);
                border: 1px solid rgba(128, 128, 128, 0.2);
                border-radius: 6px;
                color: inherit;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.1);
            }
            QPushButton:disabled {
                border: 1px solid rgba(128, 128, 128, 0.1);
                color: rgba(128, 128, 128, 0.3);
                background-color: transparent;
            }
        """)
        self.prev_btn.clicked.connect(self.on_prev_clicked)
        self.prev_btn.setEnabled(False)
        pagination_layout.addWidget(self.prev_btn)
        
        self.page_label = qt.QLabel("Page 1 of 1")
        self.page_label.setAlignment(qt.Qt.AlignCenter)
        self.page_label.setFont(qt.QFont("Arial", 9, qt.QFont.Bold))
        self.page_label.setStyleSheet("color: #888888; padding: 0 10px;")
        pagination_layout.addWidget(self.page_label)
        
        self.next_btn = qt.QPushButton("▶")
        self.next_btn.setFixedSize(36, 28)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(128, 128, 128, 0.05);
                border: 1px solid rgba(128, 128, 128, 0.2);
                border-radius: 6px;
                color: inherit;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.1);
            }
            QPushButton:disabled {
                border: 1px solid rgba(128, 128, 128, 0.1);
                color: rgba(128, 128, 128, 0.3);
                background-color: transparent;
            }
        """)
        self.next_btn.clicked.connect(self.on_next_clicked)
        self.next_btn.setEnabled(False)
        pagination_layout.addWidget(self.next_btn)
        
        layout.addLayout(pagination_layout)
        
        # Status Label at the bottom (Premium Status Indicator Area)
        self.status_label = qt.QLabel("")
        self.status_label.setFont(qt.QFont("Arial", 9, qt.QFont.Bold))
        self.status_label.setAlignment(qt.Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
        self.status_label.setMinimumWidth(50)
        self.status_label.setStyleSheet("padding: 4px; margin-top: 4px;")
        layout.addWidget(self.status_label)

    def on_search_text_changed(self):
        self.search_timer.stop()
        self.search_timer.start()

    def on_search_debounced(self):
        self.current_page = 1
        self.fetch_studies()

    def on_refresh_clicked(self):
        self.search_timer.stop()
        self.current_page = 1
        self.fetch_studies()

    def on_seg_toggle_toggled(self, checked):
        config.load_with_seg = checked
        self.update_seg_toggle_style()
        logger.info(f"Load with segmentation toggled to: {checked}")

    def update_seg_toggle_style(self):
        if self.seg_toggle_btn.isChecked():
            self.seg_toggle_btn.setText("Load with Seg")
            self.seg_toggle_btn.setStyleSheet(SUCCESS_BUTTON)
        else:
            self.seg_toggle_btn.setText("Load without Seg")
            self.seg_toggle_btn.setStyleSheet(DISABLED_BUTTON)

    def on_prev_clicked(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.fetch_studies()

    def on_next_clicked(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.fetch_studies()

    def fetch_studies(self):
        self.show_status("Fetching studies...")
        self.refresh_btn.setEnabled(False)
        qt.QTimer.singleShot(100, self._do_fetch)

    def _do_fetch(self):
        patient_name = self.search_input.text.strip().replace("🔍", "").strip()
        success, result = APIService.fetch_reports(
            page=self.current_page,
            limit=self.limit,
            patient_name=patient_name
        )
        self.refresh_btn.setEnabled(True)
        
        if success:
            studies, total_pages, current_page = result
            self.studies = studies
            self.total_pages = total_pages
            self.current_page = current_page
            
            self.populate_table()
            self.update_pagination_ui()
            self.show_status("", error=False)
        else:
            self.show_status(f"Failed: {result}", error=True)

    def update_pagination_ui(self):
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.total_pages)

    def populate_table(self):
        self.table.setRowCount(0)
        for i, study in enumerate(self.studies):
            self.table.insertRow(i)
            self.table.setRowHeight(i, 30)
            self.table.setItem(i, 0, qt.QTableWidgetItem(study.patient_id))
            self.table.setItem(i, 1, qt.QTableWidgetItem(study.patient_name))
            self.table.setItem(i, 2, qt.QTableWidgetItem(study.modalities))

    def on_study_double_clicked(self, row, col):
        self.load_study_at_row(row)



    def load_study_at_row(self, row):
        if row < 0 or row >= len(self.studies):
            return
        if getattr(self, "_study_loading", False):
            self.show_status("A study is already loading. Please wait...", error=False)
            return

        study = self.studies[row]
        self._study_loading = True
        self.table.setEnabled(False)

        self.show_status(f"Loading {study.patient_name}...", error=False)

        if not hasattr(self, "_study_loader"):
            self._study_loader = StudyLoader()
        loader = self._study_loader
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
        from Utils.helpers import MainThreadDispatcher
        if getattr(self, "_last_progress_percent", -1) == percent:
            return
        self._last_progress_percent = percent
        MainThreadDispatcher.get_instance().dispatch(
            self.show_status, f"[{percent}%] {msg}", False
        )

    def on_load_complete(self, success):
        from Utils.helpers import MainThreadDispatcher

        def _finish():
            self._study_loading = False
            self._last_progress_percent = -1
            self.table.setEnabled(True)
            if success:
                self.show_status("Study loaded successfully.", False)
            else:
                self.show_status("Failed to load study.", True)

        MainThreadDispatcher.get_instance().dispatch(_finish)

    def show_status(self, msg, error=False):
        self.status_label.setText(msg)
        if error:
            self.status_label.setStyleSheet("color: #F44336;")
        else:
            self.status_label.setStyleSheet("color: #4CAF50;")
