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

# Thread-local HTTP sessions keep connections warm across parallel instance fetches.
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
                if not getattr(config, "load_with_seg", True):
                    logger.info(f"Study {study_uid} cache is complete. load_with_seg is disabled; bypassing PACS sync check.")
                    self.cache_manager.touch_cache(study_uid)
                    if progress_callback:
                        progress_callback(100, "Loading from cache...")
                    return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}

                logger.info(f"Study {study_uid} cache is marked complete. Verifying sync with PACS...")
                
                # Fetch instance list from PACS to check if there are any updates/changes
                if progress_callback:
                    progress_callback(5, "Checking PACS for updates...")
                
                try:
                    logger.info(f"Fetching instance list from PACS for {study_uid} to verify cache...")
                    instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
                except Exception as pacs_err:
                    logger.warning(f"Failed to fetch study instances from PACS for sync check: {pacs_err}. Falling back to cached data.")
                    instance_map = None

                if not instance_map:
                    # If PACS fetch fails or returns empty (offline/error), fallback to existing cache to remain functional
                    logger.warning("PACS fetch returned no instances or was offline. Falling back to cached copy.")
                    self.cache_manager.touch_cache(study_uid)
                    if progress_callback:
                        progress_callback(100, "Loading from cache...")
                    return {"cache_dir": self._resolve_import_dir(cache_root, study_uid), "newly_downloaded": False}

                # PACS fetch succeeded, let's analyze local vs PACS files
                resolve_dir = self._resolve_import_dir(cache_root, study_uid)
                local_instances = self._get_local_cached_instances(resolve_dir)
                pacs_uids = {inst_uid for _, inst_uid in instance_map}
                
                missing_uids = pacs_uids - set(local_instances.keys())
                stale_uids = set(local_instances.keys()) - pacs_uids

                if not missing_uids and not stale_uids:
                    logger.info(f"Cache for study {study_uid} is perfectly in sync with PACS (total instances: {len(pacs_uids)}). Skipping download.")
                    self.cache_manager.touch_cache(study_uid)
                    if progress_callback:
                        progress_callback(100, "Cache is up-to-date. Loading...")
                    return {"cache_dir": resolve_dir, "newly_downloaded": False}

                logger.info(f"Cache out of sync for study {study_uid}. Missing: {len(missing_uids)}, Stale: {len(stale_uids)}")
                
                # Since we are modifying the cache, remove the complete marker file first to prevent partial/broken reads
                marker_file = self._marker_path(cache_root, study_uid)
                legacy_marker = os.path.join(cache_root, study_uid, ".complete")
                for marker in (marker_file, legacy_marker):
                    if os.path.exists(marker):
                        try:
                            os.remove(marker)
                        except Exception as e:
                            logger.warning(f"Could not remove complete marker {marker}: {e}")

                # Delete stale cached instances (e.g., deleted series/instances on PACS)
                if stale_uids:
                    logger.info(f"Deleting {len(stale_uids)} stale cached file(s) that are no longer on PACS...")
                    for uid in stale_uids:
                        path = local_instances[uid]
                        try:
                            os.remove(path)
                            logger.debug(f"Deleted stale cached file: {path}")
                        except Exception as e:
                            logger.warning(f"Failed to delete stale file {path}: {e}")

                # Download missing instances
                if missing_uids:
                    logger.info(f"Downloading {len(missing_uids)} missing instance(s) from PACS...")
                    if progress_callback:
                        progress_callback(10, f"Syncing {len(missing_uids)} new instances from PACS...")
                    
                    missing_instance_map = [(series_uid, inst_uid) for series_uid, inst_uid in instance_map if inst_uid in missing_uids]
                    
                    # Ensure dicom_dir exists
                    os.makedirs(dicom_dir, exist_ok=True)
                    
                    if self._download_instances_parallel(
                        study_uid, dicom_dir, auth_header, progress_callback, instance_map=missing_instance_map
                    ):
                        logger.info("Successfully synchronized cache by downloading missing instances.")
                    else:
                        logger.error("Failed to download missing instances to synchronize cache.")
                        raise RuntimeError("Failed to download missing instances for cache synchronization.")

                # Sync completed successfully, write the marker
                self._write_complete_marker(cache_root, study_uid)
                if progress_callback:
                    progress_callback(100, "Synchronization complete.")
                return {"cache_dir": dicom_dir, "newly_downloaded": True}
            # -------------------------------------

            # If cache is not complete at all, proceed with a full study download
            os.makedirs(dicom_dir, exist_ok=True)

            if progress_callback:
                progress_callback(5, "Preparing download...")

            # Parallel WADO is usually faster than Orthanc ZIP (ZIP is built server-side on demand).
            if self._download_instances_parallel(
                study_uid, dicom_dir, auth_header, progress_callback
            ):
                logger.info("Parallel WADO-RS download succeeded.")
            elif self._try_orthanc_bulk_download(study_uid, dicom_dir, progress_callback):
                logger.info("Bulk Orthanc archive download succeeded (WADO fallback).")
            else:
                logger.error("All download strategies failed.")
                return None

            if progress_callback:
                progress_callback(95, "Verifying downloaded files...")

            if self._count_dcm_files(dicom_dir) == 0:
                raise FileNotFoundError("No DICOM files found after download.")

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
        from collections import defaultdict
        import io
        import pydicom

        if instance_map is None:
            logger.info(f"Looking up instances for {study_uid} via QIDO-RS...")
            instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
            if not instance_map:
                logger.error("Could not find instances in DICOMweb.")
                return False

        total_instances = len(instance_map)
        logger.info(f"Total instances to stream: {total_instances}")
        if total_instances == 0:
            return True
        if progress_callback:
            progress_callback(10, f"Streaming {total_instances} instances from PACS...")

        # Group instances by series_uid
        series_groups = defaultdict(list)
        for series_uid, inst_uid in instance_map:
            series_groups[series_uid].append(inst_uid)

        # Check which instances are already cached
        missing_series = {}
        for s_uid, inst_uids in series_groups.items():
            missing_uids = [uid for uid in inst_uids if not os.path.exists(os.path.join(dicom_dir, f"{uid}.dcm"))]
            if missing_uids:
                missing_series[s_uid] = missing_uids

        if not missing_series:
            logger.info("All instances are already cached locally.")
            return True

        chunk_size = 256 * 1024
        req_timeout = (15, 300)

        # Phase 1: Try series-level retrieval
        failed_series = set()
        series_to_download = list(missing_series.keys())

        def download_series_task(series_uid):
            sess = _orthanc_http_session(auth_header)
            wado_rs_url = f"{config.dicomweb_endpoint}/studies/{study_uid}/series/{series_uid}"
            headers = {"Accept": 'multipart/related; type="application/dicom"'}
            
            try:
                logger.info(f"Attempting Retrieve Series WADO-RS: {wado_rs_url}")
                with sess.get(wado_rs_url, headers=headers, stream=True, timeout=req_timeout) as r:
                    r.raise_for_status()
                    
                    content_type = r.headers.get("Content-Type", "")
                    boundary = ""
                    for part in content_type.split(";"):
                        if "boundary=" in part.lower():
                            boundary = part.split("=")[1].strip().strip('"')
                            break
                    
                    if not boundary:
                        raise ValueError("No boundary found in Content-Type header for series retrieve")
                    
                    content = r.content
                    parsed_count = 0
                    for body in StudyLoader._parse_multipart_dicom(content, boundary):
                        try:
                            ds = pydicom.dcmread(io.BytesIO(body), stop_before_pixels=True)
                            inst_uid = str(getattr(ds, "SOPInstanceUID", ""))
                            if inst_uid:
                                output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
                                with open(output_path, "wb") as f:
                                    f.write(body)
                                parsed_count += 1
                        except Exception as parse_err:
                            logger.warning(f"Error parsing instance in series {series_uid}: {parse_err}")
                    
                    if parsed_count > 0:
                        logger.info(f"Successfully retrieved series {series_uid} (saved {parsed_count} instances)")
                        return True
                    else:
                        raise ValueError(f"No valid DICOM parts parsed for series {series_uid}")
            except Exception as e:
                logger.warning(f"Retrieve Series for {series_uid} failed: {e}. Will fall back to instance-level download.")
                return False

        logger.info(f"Attempting series-level WADO-RS Retrieve for {len(series_to_download)} series...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(series_to_download))) as executor:
            future_to_series = {
                executor.submit(download_series_task, s_uid): s_uid 
                for s_uid in series_to_download
            }
            for future in concurrent.futures.as_completed(future_to_series):
                s_uid = future_to_series[future]
                try:
                    if not future.result():
                        failed_series.add(s_uid)
                except Exception as exc:
                    logger.error(f"Series retrieve future failed for {s_uid}: {exc}")
                    failed_series.add(s_uid)

        # Collect remaining missing instances
        remaining_instances = []
        for s_uid in failed_series:
            for inst_uid in missing_series[s_uid]:
                output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
                if not os.path.exists(output_path):
                    remaining_instances.append((s_uid, inst_uid))

        # Phase 2: Fallback single-instance parallel download with smart Accept header probing
        if remaining_instances:
            logger.info(f"Downloading {len(remaining_instances)} remaining instances via instance-level fallback...")
            
            probed_accept_header = None
            probe_success = False
            first_item = remaining_instances[0]
            first_series_uid, first_inst_uid = first_item
            
            sess = _orthanc_http_session(auth_header)
            wado_rs_url = (
                f"{config.dicomweb_endpoint}/studies/{study_uid}"
                f"/series/{first_series_uid}/instances/{first_inst_uid}"
            )
            
            for accept_header in (
                "application/dicom",
                'multipart/related; type="application/dicom"',
            ):
                try:
                    r = sess.get(wado_rs_url, headers={"Accept": accept_header}, timeout=5)
                    if r.status_code == 200:
                        probed_accept_header = accept_header
                        probe_success = True
                        logger.info(f"Successfully probed Accept header: {accept_header}")
                        break
                except Exception as e:
                    logger.debug(f"Probe with Accept header '{accept_header}' failed: {e}")
            
            if not probe_success:
                probed_accept_header = "application/dicom"
                logger.warning("Accept header probe failed. Defaulting to 'application/dicom'")

            def download_single_task(item):
                s_uid, inst_uid = item
                output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
                if os.path.exists(output_path):
                    return True

                sess = _orthanc_http_session(auth_header)
                wado_rs_url = (
                    f"{config.dicomweb_endpoint}/studies/{study_uid}"
                    f"/series/{s_uid}/instances/{inst_uid}"
                )

                try:
                    with sess.get(wado_rs_url, headers={"Accept": probed_accept_header}, stream=True, timeout=req_timeout) as r:
                        if r.status_code == 200:
                            content_type = r.headers.get("Content-Type", "")
                            if "multipart/related" in content_type.lower():
                                boundary = ""
                                for part in content_type.split(";"):
                                    if "boundary=" in part.lower():
                                        boundary = part.split("=")[1].strip('"')
                                        break
                                if boundary:
                                    content = r.content
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
                            
                            with open(output_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=chunk_size):
                                    if chunk:
                                        f.write(chunk)
                            return True
                except Exception as e:
                    logger.debug(f"Instance download failed: {e}")

                # Last resort legacy WADO-URI
                return bool(
                    self.dicom_service.download_instance(
                        study_uid, s_uid, inst_uid, output_path, auth_header=auth_header
                    )
                )

            max_workers = max(1, min(32, len(remaining_instances)))
            completed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(download_single_task, item): item for item in remaining_instances}
                for future in concurrent.futures.as_completed(futures):
                    if not future.result():
                        raise RuntimeError(f"Failed to download instance {futures[future]}")
                    completed += 1
                    if progress_callback and completed % max(1, len(remaining_instances) // 15) == 0:
                        progress = 10 + int((completed / len(remaining_instances)) * 80)
                        progress_callback(progress, f"Streaming {completed}/{len(remaining_instances)}")

        logger.info("WADO download complete.")
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
                # we need to remove the old study reference and import
                if newly_downloaded or not series_in_db:
                    logger.info(f"Importing/updating study {target_study_uid} in Slicer DICOM database...")
                    if series_in_db:
                        db.removeStudy(target_study_uid)
                    DICOMUtils.importDicom(cache_dir)
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
