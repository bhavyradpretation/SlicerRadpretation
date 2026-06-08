import requests
import json
import os
from Utils.config import config
from Utils.logger import logger

class OrthancClient:
    """Client for communicating with Orthanc PACS via its REST API."""
    
    def __init__(self, base_url=None):
        self.base_url = (base_url or config.pacs_url).rstrip('/')
        self.req_kwargs = config.get_requests_kwargs()
        
        # Initialize a Session for connection pooling/keep-alive to improve performance
        self.session = requests.Session()
        if "auth" in self.req_kwargs:
            self.session.auth = self.req_kwargs["auth"]
        if "headers" in self.req_kwargs:
            self.session.headers.update(self.req_kwargs["headers"])

    def fetch_studies(self):
        """Fetch all studies from Orthanc."""
        url = f"{self.base_url}/studies?expand"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            logger.info("Successfully fetched studies from Orthanc.")
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch studies from Orthanc: {e}")
            return []

    def lookup_study_id(self, study_instance_uid):
        """Find the Orthanc internal ID for a DICOM StudyInstanceUID."""
        url = f"{self.base_url}/tools/lookup"
        try:
            response = self.session.post(url, data=study_instance_uid)
            response.raise_for_status()
            results = response.json()
            for res in results:
                if res.get("Type") == "Study":
                    return res.get("ID")
            return None
        except Exception as e:
            logger.error(f"Failed to lookup study ID for {study_instance_uid}: {e}")
            return None

    def download_study_archive(self, study_id, target_dir, progress_callback=None):
        """Download a study archive (ZIP) and extract DICOM files into target_dir."""
        import uuid
        import zipfile
        import time

        url = f"{self.base_url}/studies/{study_id}/archive"
        zip_path = os.path.join(target_dir, f"{study_id}_{uuid.uuid4().hex}.zip")
        try:
            logger.info(f"Downloading study archive {study_id} from Orthanc (bulk ZIP)...")
            os.makedirs(target_dir, exist_ok=True)
            
            start_download = time.time()
            with self.session.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            pct = 10 + int((downloaded / total) * 75)
                            progress_callback(pct, "Downloading study archive...")

            download_duration = time.time() - start_download
            logger.info(f"Bulk ZIP download completed in {download_duration:.2f} seconds. Starting parallel extraction...")

            if progress_callback:
                progress_callback(88, "Extracting study archive...")

            start_extract = time.time()
            
            # Read ZIP info
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]

            # Pre-create all parent directories sequentially to prevent Windows directory creation race conditions
            parent_dirs = set()
            for member in members:
                upperdir = os.path.dirname(os.path.join(target_dir, member.filename))
                if upperdir:
                    parent_dirs.add(upperdir)
            for directory in sorted(parent_dirs, key=len):
                os.makedirs(directory, exist_ok=True)

            # Parallel extraction using a thread pool with independent ZipFile instances for thread-safety
            import concurrent.futures
            
            def extract_member(member):
                target_path = os.path.join(target_dir, member.filename)
                try:
                    with zipfile.ZipFile(zip_path, "r") as thread_zf:
                        data = thread_zf.read(member)
                    with open(target_path, "wb") as f:
                        f.write(data)
                except Exception as ex:
                    logger.error(f"Failed to extract {member.filename}: {ex}")

            # Using 8 workers is a good balance for SSD write speed and zlib decompression CPU utilization
            max_workers = min(8, len(members)) if members else 1
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(extract_member, members))

            extract_duration = time.time() - start_extract
            logger.info(f"Study archive extracted in {extract_duration:.2f} seconds.")

            try:
                os.remove(zip_path)
            except OSError:
                pass

            logger.info(f"Study archive extracted to {target_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to download/extract study archive: {e}")
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except OSError:
                pass
            return False

    def upload_dicom(self, file_path):
        """Upload a single DICOM file (e.g., DICOM SEG or RTStruct) to Orthanc."""
        url = f"{self.base_url}/instances"
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            headers = {'Content-Type': 'application/dicom'}
            response = self.session.post(url, data=data, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully uploaded {file_path} to Orthanc.")
            return True
        except Exception as e:
            logger.error(f"Failed to upload DICOM to Orthanc: {e}")
            return False
