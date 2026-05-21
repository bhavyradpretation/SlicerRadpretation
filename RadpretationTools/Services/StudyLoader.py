import os
import shutil
import threading
import slicer
from DICOMLib import DICOMUtils
from Services.DICOMWebService import DICOMWebService
from Services.CacheManager import CacheManager
from Utils.helpers import AsyncTaskRunner
from Utils.logger import logger

# Thread-local HTTP sessions keep connections warm across parallel instance fetches (faster than naive requests.get per file).
_thread_local = threading.local()

def _orthanc_http_session(auth_header=None):
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from Utils.config import config

    if not getattr(_thread_local, "session", None):
        session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.2, status_forcelist=(502, 503, 504))
        adapter = HTTPAdapter(pool_connections=48, pool_maxsize=48, max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        kwargs = config.get_requests_kwargs()
        if "auth" in kwargs:
            session.auth = kwargs["auth"]
            
        if auth_header:
            session.headers.update({"Authorization": auth_header})
            
        _thread_local.session = session
    return _thread_local.session


class StudyLoader:
    """Orchestrates pulling studies via DICOMweb, caching them, and loading them into Slicer."""
    
    def __init__(self):
        self.dicom_service = DICOMWebService()
        self.cache_manager = CacheManager()

    def load_study_remote(self, study_model, auth_header=None, progress_callback=None, completion_callback=None):
        """
        Main entry point to load a study.
        Downloads all series to cache in a background thread, then loads them.
        """
        logger.info(f"Initiating remote load for study: {study_model.study_instance_uid}")
        
        # We run the heavy downloading inside a background thread so UI doesn't freeze
        AsyncTaskRunner.run(
            task_func=self._download_study_worker,
            callback=lambda cache_dir: self._on_download_complete(cache_dir, study_model, completion_callback),
            study_model=study_model,
            auth_header=auth_header,
            progress_callback=progress_callback
        )

    def _download_study_worker(self, study_model, auth_header, progress_callback):
        """Background worker that streams DICOM files natively and verifies them."""
        try:
            logger.info("Worker started. Phase 1: Download using DICOMweb QIDO-RS and WADO-URI")
            study_uid = study_model.study_instance_uid
            
            import uuid
            # Use a completely unique UUID for the download directory to prevent any 
            # file locks or ghost files from previous Slicer imports.
            batch_id = uuid.uuid4().hex
            cache_dir = os.path.join(self.cache_manager.cache_dir, f"{study_uid}_{batch_id}")
            os.makedirs(cache_dir, exist_ok=True)
            logger.info(f"Unique cache dir created: {cache_dir}")
            
            from Utils.config import config
            
            logger.info(f"Looking up instances for {study_uid} via QIDO-RS...")
            instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
            
            if not instance_map:
                logger.error("Could not find instances in DICOMweb.")
                return None

            total_instances = len(instance_map)
            logger.info(f"Total instances to stream: {total_instances}")
            if total_instances == 0:
                logger.warning("No instances found for study.")
                return None
            if progress_callback:
                progress_callback(10, f"Streaming {total_instances} instances from PACS...")

            # Phase 1: Parallel Download
            import concurrent.futures
            completed = 0
            max_workers = max(1, min(48, total_instances))
            chunk_size = 256 * 1024
            req_timeout = (15, 300)

            def download_task(item):
                series_uid, inst_uid = item
                output_path = os.path.join(cache_dir, f"{inst_uid}.dcm")
                if os.path.exists(output_path):
                    return True
                
                sess = _orthanc_http_session(auth_header)
                
                # Use WADO-RS to fetch the instance. Orthanc's DICOMweb plugin supports
                # Accept: application/dicom to return the raw file instead of multipart.
                wado_rs_url = f"{config.dicomweb_endpoint}/studies/{study_uid}/series/{series_uid}/instances/{inst_uid}"
                
                # Add strictly compliant Accept header for WADO-RS
                req_headers = {"Accept": "multipart/related; type=\"application/dicom\""}
                
                with sess.get(wado_rs_url, headers=req_headers, stream=True, timeout=req_timeout) as r:
                    r.raise_for_status()
                    
                    # If the server ignores Accept: application/dicom and returns multipart/related,
                    # we must parse it manually to extract the raw DICOM binary data.
                    content_type = r.headers.get("Content-Type", "")
                    
                    if "multipart/related" in content_type.lower():
                        logger.info("Server returned multipart/related, parsing...")
                        boundary = ""
                        for part in content_type.split(";"):
                            if "boundary=" in part.lower():
                                boundary = part.split("=")[1].strip('"')
                                break
                                
                        if not boundary:
                            raise Exception("Multipart response missing boundary")
                            
                        # Read entire response into memory to parse multipart
                        content = r.content
                        boundary_bytes = b"--" + boundary.encode()
                        parts = content.split(boundary_bytes)
                        
                        dicom_data = None
                        for part in parts:
                            if b"application/dicom" in part.lower():
                                idx = part.find(b"\r\n\r\n")
                                if idx != -1:
                                    # Extract payload and remove trailing CRLF if present
                                    dicom_data = part[idx+4:]
                                    if dicom_data.endswith(b"\r\n"):
                                        dicom_data = dicom_data[:-2]
                                    break
                                    
                        if dicom_data is None:
                            raise Exception("Could not find application/dicom part in multipart response")
                            
                        with open(output_path, "wb") as f:
                            f.write(dicom_data)
                    else:
                        # Raw DICOM streaming
                        with open(output_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    f.write(chunk)
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(download_task, item): item for item in instance_map}
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                    completed += 1
                    if progress_callback and completed % max(1, total_instances // 20) == 0:
                        progress = 10 + int((completed / total_instances) * 80)
                        progress_callback(progress, f"Streaming {completed}/{total_instances}")
            
            logger.info("Phase 1 Complete. All slices streamed successfully.")
            
            # Phase 2: Verify
            logger.info("Phase 2: Verification. Checking integrity of downloaded files...")
            if progress_callback:
                progress_callback(95, "Verifying downloaded files...")
                
            missing_files = []
            for item in instance_map:
                series_uid, inst_uid = item
                output_path = os.path.join(cache_dir, f"{inst_uid}.dcm")
                if not os.path.exists(output_path):
                    missing_files.append(output_path)
            
            if missing_files:
                raise FileNotFoundError(f"Verification Failed! {len(missing_files)} files did not download correctly.")
                
            logger.info("Phase 2 Complete. All files verified successfully.")

            if progress_callback:
                progress_callback(100, "Done.")
                
            return cache_dir
        except Exception as e:
            import traceback
            logger.error(f"CRITICAL ERROR in worker: {repr(e)}\n{traceback.format_exc()}")
            raise

    def _on_download_complete(self, cache_dir, study_model, completion_callback):
        """Called on main thread when background download finishes."""
        if not cache_dir:
            if completion_callback:
                completion_callback(False)
            return

        logger.info(f"Download complete. Importing cache dir into Slicer: {cache_dir}")
        
        try:
            DICOMUtils.importDicom(cache_dir)
            logger.info("DICOM data imported to local Slicer database successfully.")
            
            # Auto-load the study into the viewports!
            db = slicer.dicomDatabase
            if db.isOpen:
                target_study_uid = study_model.study_instance_uid
                series_to_load = []
                
                # Search the Slicer DB for the series we just imported
                for patient in db.patients():
                    for study in db.studiesForPatient(patient):
                        if study == target_study_uid:
                            for series in db.seriesForStudy(study):
                                series_to_load.append(series)
                
                if len(series_to_load) > 0:
                    logger.info(f"Auto-loading {len(series_to_load)} series into viewports...")
                    DICOMUtils.loadSeriesByUID(series_to_load)
                else:
                    logger.warning("Could not find imported series in Slicer DB to auto-load.")
            
            # Ensure our module is active
            slicer.util.selectModule("RadpretationTools")
            
            if completion_callback:
                completion_callback(True)
        except Exception as e:
            logger.error(f"Failed to load cached DICOM into Slicer: {e}")
            if completion_callback:
                completion_callback(False)
