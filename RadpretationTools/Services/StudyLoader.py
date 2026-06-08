import os
import threading
import qt
import slicer
from DICOMLib import DICOMUtils
from Services.DICOMWebService import DICOMWebService
from Services.CacheManager import CacheManager
from Integrations.orthanc_client import OrthancClient
from Utils.helpers import AsyncTaskRunner
from Utils.logger import logger

# Global shared requests session for Keep-Alive connection pooling
_shared_session = None
_session_lock = threading.Lock()


def _orthanc_http_session(auth_header=None):
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from Utils.config import config
    global _shared_session

    with _session_lock:
        if _shared_session is None:
            session = requests.Session()
            retries = Retry(total=2, backoff_factor=0.2, status_forcelist=(502, 503, 504))
            adapter = HTTPAdapter(pool_connections=128, pool_maxsize=128, max_retries=retries)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

            kwargs = config.get_requests_kwargs()
            if "auth" in kwargs:
                session.auth = kwargs["auth"]
            _shared_session = session
            
    return _shared_session


class StudyLoader:
    """Orchestrates pulling studies via DICOMweb, caching them, and loading them into Slicer."""

    _load_lock = threading.Lock()
    _load_generation = 0

    def __init__(self):
        self.dicom_service = DICOMWebService()
        self.cache_manager = CacheManager()

    @staticmethod
    def _parse_multipart_dicom(content, boundary):
        """
        Parses a multipart/related byte stream and yields valid DICOM byte blocks.
        """
        import io
        import pydicom
        
        boundary_bytes = b"--" + boundary.encode('utf-8')
        parts = content.split(boundary_bytes)
        
        for part in parts:
            idx = part.find(b"\r\n\r\n")
            if idx == -1:
                continue
            
            headers = part[:idx]
            body = part[idx + 4 :]
            
            headers_lower = headers.lower()
            if b"application/dicom" in headers_lower or b"application/octet-stream" in headers_lower or b"image/" in headers_lower:
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                elif body.endswith(b"\n"):
                    body = body[:-1]
                
                try:
                    if len(body) > 132 and body[128:132] == b"DICM":
                        yield body
                        continue
                    
                    pydicom.dcmread(io.BytesIO(body), stop_before_pixels=True)
                    yield body
                except Exception:
                    continue

    @staticmethod
    def _marker_path(cache_root, study_uid):
        """Marker lives beside study folders so Slicer import never sees it."""
        return os.path.join(cache_root, f".{study_uid}.complete")

    @staticmethod
    def _dicom_dir(cache_root, study_uid):
        return os.path.join(cache_root, study_uid, "dicom")

    @staticmethod
    def _resolve_import_dir(cache_root, study_uid):
        """Return the directory that contains .dcm files for a cached study."""
        dicom_dir = StudyLoader._dicom_dir(cache_root, study_uid)
        if os.path.isdir(dicom_dir) and StudyLoader._count_dcm_files(dicom_dir) > 0:
            return dicom_dir
        legacy_dir = os.path.join(cache_root, study_uid)
        if os.path.isdir(legacy_dir) and StudyLoader._count_dcm_files(legacy_dir) > 0:
            return legacy_dir
        return dicom_dir

    @staticmethod
    def _count_dcm_files(root_dir):
        count = 0
        for root, _, names in os.walk(root_dir):
            for name in names:
                if name.lower().endswith(".dcm"):
                    count += 1
        return count

    @staticmethod
    def _is_cache_complete(cache_root, study_uid):
        marker = StudyLoader._marker_path(cache_root, study_uid)
        if os.path.exists(marker):
            return StudyLoader._count_dcm_files(StudyLoader._resolve_import_dir(cache_root, study_uid)) > 0
        legacy_marker = os.path.join(cache_root, study_uid, ".complete")
        return os.path.exists(legacy_marker) and StudyLoader._count_dcm_files(
            StudyLoader._resolve_import_dir(cache_root, study_uid)
        ) > 0

    @staticmethod
    def _write_complete_marker(cache_root, study_uid):
        marker = StudyLoader._marker_path(cache_root, study_uid)
        with open(marker, "w", encoding="utf-8") as f:
            f.write("complete")
        logger.info(f"Created complete marker file: {marker}")

    @staticmethod
    def _get_local_cached_instances(dicom_dir):
        """Scans the local cached files and returns a dictionary mapping SOPInstanceUID to absolute file path."""
        import pydicom
        local_instances = {}
        if not os.path.isdir(dicom_dir):
            return local_instances

        for root, _, files in os.walk(dicom_dir):
            for name in files:
                if name.startswith('.'):
                    continue
                file_path = os.path.join(root, name)
                
                # Fast path: if the filename is f"{uid}.dcm"
                basename, ext = os.path.splitext(name)
                if all(c.isdigit() or c == '.' for c in basename) and len(basename) > 10:
                    local_instances[basename] = file_path
                    continue
                
                try:
                    ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                    uid = getattr(ds, "SOPInstanceUID", None)
                    if uid:
                        local_instances[str(uid)] = file_path
                except Exception as e:
                    logger.debug(f"Skipping non-DICOM or unreadable file: {file_path}")
        return local_instances

    @staticmethod
    def patch_dicom_for_export(file_path):
        """Patch spatial tags only when exporting SEG (not during study load)."""
        try:
            import pydicom
            from pydicom.uid import generate_uid

            ds = pydicom.dcmread(file_path)
            sop_class = str(getattr(ds, "SOPClassUID", "") or "")
            modality = str(getattr(ds, "Modality", "") or "")
            # Never patch segmentation objects — bogus geometry breaks SEG import.
            if modality == "SEG" or "1.2.840.10008.5.1.4.1.1.66.4" in sop_class:
                return

            modified = False
            if "FrameOfReferenceUID" not in ds or not ds.FrameOfReferenceUID:
                study_uid = getattr(ds, "StudyInstanceUID", "")
                if study_uid:
                    import hashlib
                    hash_val = hashlib.sha256(study_uid.encode()).hexdigest()
                    nums = [str(int(hash_val[i : i + 7], 16)) for i in range(0, 56, 7)]
                    uid_str = f"2.25.{'.'.join(nums)}"[:64].rstrip(".")
                    ds.FrameOfReferenceUID = uid_str
                else:
                    ds.FrameOfReferenceUID = generate_uid()
                modified = True

            if "ImagePositionPatient" not in ds or not ds.ImagePositionPatient:
                ds.ImagePositionPatient = [0.0, 0.0, 0.0]
                modified = True

            if "ImageOrientationPatient" not in ds or not ds.ImageOrientationPatient:
                ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
                modified = True

            if modified:
                ds.save_as(file_path)
        except Exception as e:
            logger.error(f"Failed to patch DICOM file '{file_path}': {e}")

    @staticmethod
    def _flatten_and_rename_dicom_dir(dicom_dir):
        """
        Recursively scans dicom_dir, reads SOPInstanceUID from each DICOM file,
        moves it directly to dicom_dir named as f"{SOPInstanceUID}.dcm", and
        cleans up nested empty subdirectories.
        """
        import pydicom
        import shutil

        logger.info(f"Flattening and renaming DICOM files in {dicom_dir}...")
        
        # Collect all files first to avoid modifying the directory structure while walking
        all_files = []
        for root, dirs, files in os.walk(dicom_dir):
            for name in files:
                all_files.append(os.path.join(root, name))

        for file_path in all_files:
            if not os.path.exists(file_path):
                continue
            
            basename, ext = os.path.splitext(os.path.basename(file_path))
            # If already a flattened SOPInstanceUID file in the root of dicom_dir, skip
            parent_dir = os.path.dirname(file_path)
            is_in_root = (os.path.normpath(parent_dir) == os.path.normpath(dicom_dir))
            
            if is_in_root and ext.lower() == ".dcm" and all(c.isdigit() or c == '.' for c in basename) and len(basename) > 10:
                continue

            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                uid = getattr(ds, "SOPInstanceUID", None)
                if uid:
                    uid_str = str(uid).strip()
                    target_path = os.path.join(dicom_dir, f"{uid_str}.dcm")
                    if os.path.normpath(file_path) != os.path.normpath(target_path):
                        shutil.move(file_path, target_path)
                else:
                    if not is_in_root:
                        os.remove(file_path)
            except Exception as e:
                logger.debug(f"Removing unreadable/invalid file during flatten: {file_path} (error: {e})")
                if not is_in_root:
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass

        # Now remove any subdirectories under dicom_dir
        for root, dirs, files in os.walk(dicom_dir, topdown=False):
            if os.path.normpath(root) == os.path.normpath(dicom_dir):
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError as e:
                logger.debug(f"Failed to remove directory {root}: {e}")

    def load_study_remote(self, study_model, auth_header=None, progress_callback=None, completion_callback=None):
        """Download (or reuse cache) and import a study. Only the latest request is applied."""
        study_uid = study_model.study_instance_uid
        logger.info(f"Initiating remote load for study: {study_uid}")

        with self._load_lock:
            StudyLoader._load_generation += 1
            load_id = StudyLoader._load_generation

        self.cache_manager.clear_cache()

        AsyncTaskRunner.run(
            task_func=self._download_study_worker,
            callback=lambda result: self._on_download_complete(
                result, study_model, completion_callback, load_id
            ),
            study_model=study_model,
            auth_header=auth_header,
            progress_callback=progress_callback,
            load_id=load_id,
        )

    def _download_study_worker(self, study_model, auth_header, progress_callback, load_id):
        try:
            study_uid = study_model.study_instance_uid
            cache_root = self.cache_manager.cache_dir
            dicom_dir = self._dicom_dir(cache_root, study_uid)

            # --- CACHE PACS SYNC LOGIC ---
            if self._is_cache_complete(cache_root, study_uid):
                from Utils.config import config
                
                # If load_with_seg is OFF, we bypass PACS sync completely and load instantly
                if not getattr(config, "load_with_seg", True):
                    logger.info(f"Study {study_uid} cache is complete. load_with_seg is OFF; bypassing PACS sync check.")
                    self.cache_manager.touch_cache(study_uid)
                    if progress_callback:
                        progress_callback(100, "Loading from cache...")
                    return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}

                # If load_with_seg is ON, we check PACS specifically for missing SEG series/instances
                logger.info(f"Study {study_uid} cache is complete. Checking PACS for new/missing segmentations...")
                try:
                    # Fetch series modalities from PACS (fast QIDO-RS metadata check)
                    series_modalities = self.dicom_service.fetch_study_series_modalities(study_uid, auth_header=auth_header)
                    seg_series_uids = [s_uid for s_uid, mod in series_modalities.items() if mod == "SEG"]
                    
                    if not seg_series_uids:
                        logger.info(f"No segmentation series found on PACS for study {study_uid}. Loading instantly from cache.")
                        self.cache_manager.touch_cache(study_uid)
                        if progress_callback:
                            progress_callback(100, "Loading from cache...")
                        return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}
                    
                    # We have SEG series on PACS. Let's check if we have all their instances in our local cache
                    instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
                    seg_instances = [(s_uid, inst_uid) for s_uid, inst_uid in instance_map if s_uid in seg_series_uids]
                    
                    missing_seg_instances = []
                    for s_uid, inst_uid in seg_instances:
                        output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
                        if not os.path.exists(output_path):
                            missing_seg_instances.append((s_uid, inst_uid))
                    
                    if not missing_seg_instances:
                        logger.info(f"All PACS segmentation instances are already cached locally for study {study_uid}. Loading instantly.")
                        self.cache_manager.touch_cache(study_uid)
                        if progress_callback:
                            progress_callback(100, "Loading from cache...")
                        return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}

                    # We have missing SEG instances! Download only those missing SEG slices in parallel
                    logger.info(f"Downloading {len(missing_seg_instances)} missing segmentation slices from PACS...")
                    if progress_callback:
                        progress_callback(10, f"Syncing {len(missing_seg_instances)} new seg slices from PACS...")
                    
                    if self._download_instances_parallel(
                        study_uid, dicom_dir, auth_header, progress_callback, instance_map=missing_seg_instances
                    ):
                        logger.info("Successfully downloaded missing segmentation instances.")
                        # Sync complete, we return newly_downloaded=True so Slicer DB imports the new files
                        self._write_complete_marker(cache_root, study_uid)
                        if progress_callback:
                            progress_callback(100, "Synchronization complete.")
                        return {"cache_dir": dicom_dir, "newly_downloaded": True}
                    else:
                        raise RuntimeError("Failed to download missing segmentation instances.")
                        
                except Exception as pacs_err:
                    logger.warning(f"Failed to check/sync PACS segmentations: {pacs_err}. Falling back to existing cache copy.")
                    self.cache_manager.touch_cache(study_uid)
                    if progress_callback:
                        progress_callback(100, "Loading from cache...")
                    return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}
            # -------------------------------------

            # If cache is not complete at all, proceed with a full study download
            os.makedirs(dicom_dir, exist_ok=True)

            if progress_callback:
                progress_callback(5, "Preparing download...")

            # Try parallel WADO download FIRST as it is faster and bypasses zipping on the server (OHIF style)
            download_strategy_used = "wado"
            if self._download_instances_parallel(
                study_uid, dicom_dir, auth_header, progress_callback
            ):
                logger.info("Parallel WADO download succeeded.")
            elif self._try_orthanc_bulk_download(study_uid, dicom_dir, progress_callback):
                logger.info("Bulk Orthanc archive download succeeded (fallback).")
                download_strategy_used = "zip"
            else:
                logger.error("All download strategies failed.")
                return None

            if progress_callback:
                progress_callback(95, "Verifying downloaded files...")

            if self._count_dcm_files(dicom_dir) == 0:
                raise FileNotFoundError("No DICOM files found after download.")

            # Flatten and rename in the background worker only if bulk ZIP download was used
            if download_strategy_used == "zip":
                try:
                    import time
                    start_flatten = time.time()
                    StudyLoader._flatten_and_rename_dicom_dir(dicom_dir)
                    logger.info(f"Background DICOM flattening/renaming took {time.time() - start_flatten:.2f} seconds.")
                except Exception as e:
                    logger.warning(f"Failed to flatten DICOM directory in background: {e}")

            self._write_complete_marker(cache_root, study_uid)
            if progress_callback:
                progress_callback(100, "Done.")
            return {"cache_dir": dicom_dir, "newly_downloaded": True}
        except Exception as e:
            import traceback
            logger.error(f"CRITICAL ERROR in worker: {repr(e)}\n{traceback.format_exc()}")
            raise

    def _try_orthanc_bulk_download(self, study_uid, dicom_dir, progress_callback):
        try:
            client = OrthancClient()
            orthanc_id = client.lookup_study_id(study_uid)
            if not orthanc_id:
                return False
            return client.download_study_archive(
                orthanc_id, dicom_dir, progress_callback=progress_callback
            )
        except Exception as e:
            logger.warning(f"Orthanc bulk download failed, will use WADO-RS: {e}")
            return False

    def _download_instances_parallel(self, study_uid, dicom_dir, auth_header, progress_callback, instance_map=None):
        from Utils.config import config
        import concurrent.futures
        import time

        if instance_map is None:
            logger.info(f"Looking up instances for {study_uid} via QIDO-RS...")
            instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
            if not instance_map:
                logger.error("Could not find instances in DICOMweb.")
                return False

        total_instances = len(instance_map)
        logger.info(f"Total instances to download in parallel: {total_instances}")
        if total_instances == 0:
            return True
            
        if progress_callback:
            progress_callback(10, f"Preparing parallel download of {total_instances} slices...")

        # Find missing instances
        missing_instances = []
        for series_uid, inst_uid in instance_map:
            output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
            if not os.path.exists(output_path):
                missing_instances.append((series_uid, inst_uid))

        if not missing_instances:
            logger.info("All instances are already cached locally.")
            return True

        logger.info(f"Downloading {len(missing_instances)} missing slices...")
        
        # We will use the thread-local HTTP session for connection pooling
        session = _orthanc_http_session(auth_header)

        # Smart Accept header probing for WADO-RS
        probed_accept_header = "application/dicom"

        def download_single_slice(item):
            s_uid, inst_uid = item
            output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
            
            # 1. Try WADO-URI first (raw DICOM, no multipart/related overhead)
            wado_uri_url = f"{config.orthanc_wado_uri}?requestType=WADO&studyUID={study_uid}&seriesUID={s_uid}&objectUID={inst_uid}&contentType=application/dicom"
            try:
                response = session.get(wado_uri_url, stream=True, timeout=15)
                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=65536):
                            f.write(chunk)
                    return True
            except Exception as e:
                logger.debug(f"WADO-URI failed for {inst_uid}: {e}")

            # 2. Try WADO-RS as fallback
            wado_rs_url = f"{config.dicomweb_endpoint}/studies/{study_uid}/series/{s_uid}/instances/{inst_uid}"
            try:
                response = session.get(wado_rs_url, headers={"Accept": probed_accept_header}, stream=True, timeout=15)
                if response.status_code == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "multipart/related" in content_type.lower():
                        boundary = ""
                        for part in content_type.split(";"):
                            if "boundary=" in part.lower():
                                boundary = part.split("=")[1].strip('"')
                                break
                        if boundary:
                            content = response.content
                            boundary_bytes = b"--" + boundary.encode()
                            dicom_data = None
                            for part in content.split(boundary_bytes):
                                if b"application/dicom" in part.lower() or b"application/octet-stream" in part.lower():
                                    idx = part.find(b"\r\n\r\n")
                                    if idx != -1:
                                        dicom_data = part[idx + 4 :]
                                        if dicom_data.endswith(b"\r\n"):
                                            dicom_data = dicom_data[:-2]
                                        break
                            if dicom_data is not None:
                                with open(output_path, "wb") as f:
                                    f.write(dicom_data)
                                return True
                    else:
                        with open(output_path, "wb") as f:
                            for chunk in response.iter_content(chunk_size=65536):
                                f.write(chunk)
                        return True
            except Exception as e:
                logger.debug(f"WADO-RS failed for {inst_uid}: {e}")
            return False

        # Execute parallel downloads
        completed = 0
        # 32 workers is an excellent pool size for WADO-URI parallel downloads
        max_workers = min(32, len(missing_instances))
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_single_slice, item): item for item in missing_instances}
            for future in concurrent.futures.as_completed(futures):
                if not future.result():
                    logger.error(f"Failed to download slice: {futures[future]}")
                    return False
                completed += 1
                if progress_callback and completed % max(1, len(missing_instances) // 10) == 0:
                    pct = 10 + int((completed / len(missing_instances)) * 85)
                    progress_callback(pct, f"Streaming slices {completed}/{len(missing_instances)}...")

        download_duration = time.time() - start_time
        logger.info(f"Successfully downloaded {len(missing_instances)} slices in parallel in {download_duration:.2f} seconds.")
        return True

    @staticmethod
    def _series_modality(db, series_uid):
        try:
            files = db.filesForSeries(series_uid)
            if files:
                return (db.fileValue(files[0], "0008,0060") or "").strip().upper()
        except Exception:
            pass
        return ""

    @staticmethod
    def _series_for_viewport(db, study_uid):
        """Volume series only — skip SEG/RT so Slicer does not fail on incomplete geometry."""
        skip = {"SEG", "RTSTRUCT", "RTPLAN", "RTDOSE", "PR", "KO", "SR"}
        series_uids = []
        for patient in db.patients():
            for study in db.studiesForPatient(patient):
                if study != study_uid:
                    continue
                for series in db.seriesForStudy(study):
                    modality = StudyLoader._series_modality(db, series)
                    if modality in skip:
                        logger.info(f"Skipping non-viewport series {series} (modality={modality or 'unknown'})")
                        continue
                    series_uids.append(series)
        return series_uids

    def _on_download_complete(self, worker_result, study_model, completion_callback, load_id):
        if load_id != StudyLoader._load_generation:
            logger.info("Ignoring stale study load completion (superseded by a newer request).")
            return

        if not worker_result:
            if completion_callback:
                completion_callback(False)
            return

        cache_dir = worker_result.get("cache_dir")
        newly_downloaded = worker_result.get("newly_downloaded", True)

        logger.info(f"Download complete. Importing cache dir into Slicer: {cache_dir} (newly_downloaded={newly_downloaded})")

        # Start batch processing to prevent intermediate GUI redraws and flickering
        slicer.mrmlScene.StartState(slicer.vtkMRMLScene.BatchProcessState)
        
        widget_ref = None
        try:
            logger.info("Clearing MRML scene for new study load...")
            slicer.mrmlScene.Clear(0)

            db = slicer.dicomDatabase
            target_study_uid = study_model.study_instance_uid
            
            if db and db.isOpen:
                # Check if study is already in the database
                series_in_db = db.seriesForStudy(target_study_uid)
                
                # If we have newly downloaded files, or the study is not in Slicer's DB,
                # we need to import it.
                if newly_downloaded or not series_in_db:
                    logger.info(f"Importing/updating study {target_study_uid} in Slicer DICOM database...")
                    import time
                    start_import = time.time()
                    # We import using Slicer's utility which operates by reference (copyFiles=False by default)
                    DICOMUtils.importDicom(cache_dir)
                    logger.info(f"Slicer DICOM database import took {time.time() - start_import:.2f} seconds.")
                else:
                    logger.info(f"Study {target_study_uid} is already indexed in Slicer DICOM database. Skipping import.")

            if hasattr(slicer.modules, "radpretationtools"):
                widget_ref = slicer.modules.radpretationtools
            elif hasattr(slicer.modules, "RadpretationTools"):
                widget_ref = slicer.modules.RadpretationTools

            if widget_ref:
                widget = widget_ref.widgetRepresentation().self()
                if hasattr(widget, "segmentation_service") and widget.segmentation_service:
                    widget.segmentation_service.active_study_uid = target_study_uid
                    widget.segmentation_service.active_segmentation_node = None
                    widget.segmentation_service.mark_saved()
        except Exception as e:
            logger.error(f"Error clearing scene or resetting active segmentation: {e}")

        try:
            from Utils.config import config
            load_with_seg = config.load_with_seg

            db = slicer.dicomDatabase
            if db.isOpen:
                target_study_uid = study_model.study_instance_uid
                series_to_load = self._series_for_viewport(db, target_study_uid)

                if series_to_load:
                    logger.info(f"Auto-loading {len(series_to_load)} volume series into viewports...")
                    DICOMUtils.loadSeriesByUID(series_to_load)
                else:
                    logger.warning("Could not find imported series in Slicer DB to auto-load.")

                if load_with_seg:
                    seg_series = []
                    for patient in db.patients():
                        for study in db.studiesForPatient(patient):
                            if study != target_study_uid:
                                continue
                            for series in db.seriesForStudy(study):
                                modality = self._series_modality(db, series)
                                if modality == "SEG":
                                    seg_series.append(series)
                    
                    if seg_series:
                        logger.info(f"Auto-loading {len(seg_series)} segmentation series...")
                        try:
                            DICOMUtils.loadSeriesByUID(seg_series)
                        except Exception as e:
                            logger.error(f"Failed to load segmentation series: {e}")

            if widget_ref:
                widget = widget_ref.widgetRepresentation().self()
                if hasattr(widget, "finalizeStudyLoad"):
                    logger.info("Scheduling post-load Segment Editor activation...")
                    qt.QTimer.singleShot(500, lambda: widget.finalizeStudyLoad(load_with_seg))
                elif hasattr(widget, "segmentation_service") and widget.segmentation_service:
                    qt.QTimer.singleShot(
                        500,
                        lambda: widget.segmentation_service.create_segmentation(),
                    )
            elif not load_with_seg:
                logger.info("Load with segmentation DICOM disabled; volumes only from PACS.")

            if completion_callback:
                completion_callback(True)
        except Exception as e:
            logger.error(f"Failed to load cached DICOM into Slicer: {e}")
            if completion_callback:
                completion_callback(False)
        finally:
            # End batch processing to trigger a single, smooth UI and viewport render update
            slicer.mrmlScene.EndState(slicer.vtkMRMLScene.BatchProcessState)
            logger.info("Keeping temporary download directory intact for active Slicer session.")
