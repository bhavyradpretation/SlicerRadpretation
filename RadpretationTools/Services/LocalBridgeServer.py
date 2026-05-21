import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import qt
import slicer

from Utils.config import LOCAL_BRIDGE_PORT
from Utils.logger import logger
from Services.DICOMWebService import DICOMWebService
from Services.StudyLoader import StudyLoader

class LocalBridgeRequestHandler(BaseHTTPRequestHandler):
    """Handles incoming HTTP requests from the React frontend."""
    
    # We pass the study_loader instance dynamically to the handler class
    study_loader = None
    ui_callback = None

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Origin, Content-Type, Accept, Authorization')
        self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Origin, Content-Type, Accept, Authorization')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests from the frontend."""
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/open-study':
            query = urllib.parse.parse_qs(parsed_path.query)
            study_uid = query.get('studyInstanceUID', [None])[0]
            
            auth_header = self.headers.get('Authorization')
            
            if not study_uid:
                self._send_error(400, "Missing studyInstanceUID parameter")
                return
            
            logger.info(f"Received request to open study: {study_uid}")
            self._set_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Slicer is opening the study"}).encode('utf-8'))
            
            # Offload to main thread for Slicer safety
            if self.ui_callback:
                from Utils.helpers import MainThreadDispatcher
                MainThreadDispatcher.get_instance().dispatch(self.ui_callback, study_uid, auth_header)
        else:
            self._send_error(404, "Not Found")

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode('utf-8'))

    # Disable default HTTP server logging to console to keep Slicer log clean
    def log_message(self, format, *args):
        pass


class LocalBridgeServer:
    """Manages the background HTTP server."""
    
    def __init__(self, main_widget):
        self.main_widget = main_widget
        self.server = None
        self.thread = None
        self.dicom_service = DICOMWebService()
        self.study_loader = StudyLoader()

    def start(self):
        """Starts the server in a background thread."""
        if self.server:
            return
            
        try:
            # Setup Handler
            handler = LocalBridgeRequestHandler
            handler.study_loader = self.study_loader
            handler.ui_callback = self.handle_open_study_request
            
            self.server = HTTPServer(('localhost', LOCAL_BRIDGE_PORT), handler)
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.daemon = True
            self.thread.start()
            logger.info(f"Local Bridge Server running on http://localhost:{LOCAL_BRIDGE_PORT}")
        except Exception as e:
            logger.error(f"Failed to start Local Bridge Server: {e}")

    def stop(self):
        """Stops the server gracefully."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None
            logger.info("Local Bridge Server stopped.")

    def handle_open_study_request(self, study_uid, auth_header=None):
        """Called on the main Qt thread when the frontend requests a study."""
        self.main_widget.seg_status_label.setText(f"Resolving Study {study_uid}...")
        
        # We need to find the study model from DICOMweb first
        def resolve_and_load():
            try:
                target_study = self.dicom_service.fetch_study(study_uid, auth_header=auth_header)
                
                if target_study:
                    def on_progress(percent, message):
                        from Utils.helpers import MainThreadDispatcher
                        MainThreadDispatcher.get_instance().dispatch(
                            self.main_widget.seg_status_label.setText, 
                            f"{message} ({percent}%)"
                        )
                    
                    def on_complete(success):
                        from Utils.helpers import MainThreadDispatcher
                        msg = "Study loaded successfully." if success else "Failed to load study."
                        MainThreadDispatcher.get_instance().dispatch(
                            self.main_widget.seg_status_label.setText, 
                            msg
                        )

                    from Utils.helpers import MainThreadDispatcher
                    MainThreadDispatcher.get_instance().dispatch(
                        self.study_loader.load_study_remote,
                        study_model=target_study,
                        auth_header=auth_header,
                        progress_callback=on_progress,
                        completion_callback=on_complete
                    )
                else:
                    from Utils.helpers import MainThreadDispatcher
                    MainThreadDispatcher.get_instance().dispatch(
                        self.main_widget.seg_status_label.setText, 
                        "Study not found in DICOMweb."
                    )
            except Exception as e:
                logger.error(f"Error resolving study: {e}")
                
        # Run resolution in background
        t = threading.Thread(target=resolve_and_load)
        t.daemon = True
        t.start()
