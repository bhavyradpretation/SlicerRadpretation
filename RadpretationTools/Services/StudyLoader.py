import os
import threading
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
            callback=lambda cache_dir: self._on_download_complete(
                cache_dir, study_model, completion_callback, load_id
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

            if self._is_cache_complete(cache_root, study_uid):
                logger.info(f"Study {study_uid} is already fully cached. Skipping download.")
                self.cache_manager.touch_cache(study_uid)
                if progress_callback:
                    progress_callback(100, "Loading from cache...")
                return self._resolve_import_dir(cache_root, study_uid)

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
            return dicom_dir
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

    def _download_instances_parallel(self, study_uid, dicom_dir, auth_header, progress_callback):
        from Utils.config import config
        import concurrent.futures

        logger.info(f"Looking up instances for {study_uid} via QIDO-RS...")
        instance_map = self.dicom_service.fetch_all_study_instances(study_uid, auth_header=auth_header)
        if not instance_map:
            logger.error("Could not find instances in DICOMweb.")
            return False

        total_instances = len(instance_map)
        logger.info(f"Total instances to stream: {total_instances}")
        if progress_callback:
            progress_callback(10, f"Streaming {total_instances} instances from PACS...")

        max_workers = max(1, min(32, total_instances))
        completed = 0
        chunk_size = 256 * 1024
        req_timeout = (15, 300)

        def download_task(item):
            series_uid, inst_uid = item
            output_path = os.path.join(dicom_dir, f"{inst_uid}.dcm")
            if os.path.exists(output_path):
                return True

            sess = _orthanc_http_session(auth_header)
            wado_rs_url = (
                f"{config.dicomweb_endpoint}/studies/{study_uid}"
                f"/series/{series_uid}/instances/{inst_uid}"
            )

            # Prefer raw DICOM (fast path); fall back to multipart only if required.
            for accept_header in (
                "application/dicom",
                'multipart/related; type="application/dicom"',
            ):
                try:
                    req_headers = {"Accept": accept_header}
                    with sess.get(
                        wado_rs_url, headers=req_headers, stream=True, timeout=req_timeout
                    ) as r:
                        r.raise_for_status()
                        content_type = r.headers.get("Content-Type", "")

                        if "multipart/related" in content_type.lower():
                            boundary = ""
                            for part in content_type.split(";"):
                                if "boundary=" in part.lower():
                                    boundary = part.split("=")[1].strip('"')
                                    break
                            if not boundary:
                                continue

                            content = r.content
                            boundary_bytes = b"--" + boundary.encode()
                            dicom_data = None
                            for part in content.split(boundary_bytes):
                                if b"application/dicom" in part.lower():
                                    idx = part.find(b"\r\n\r\n")
                                    if idx != -1:
                                        dicom_data = part[idx + 4 :]
                                        if dicom_data.endswith(b"\r\n"):
                                            dicom_data = dicom_data[:-2]
                                        break
                            if dicom_data is None:
                                continue
                            with open(output_path, "wb") as f:
                                f.write(dicom_data)
                            return True

                        with open(output_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    f.write(chunk)
                        return True
                except Exception as e:
                    logger.debug(f"WADO-RS request with Accept header '{accept_header}' failed: {e}")

            # Last resort: legacy WADO-URI (single-part, no multipart parsing).
            return bool(
                self.dicom_service.download_instance(
                    study_uid, series_uid, inst_uid, output_path, auth_header=auth_header
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_task, item): item for item in instance_map}
            for future in concurrent.futures.as_completed(futures):
                if not future.result():
                    raise RuntimeError(f"Failed to download instance {futures[future]}")
                completed += 1
                if progress_callback and completed % max(1, total_instances // 15) == 0:
                    progress = 10 + int((completed / total_instances) * 80)
                    progress_callback(progress, f"Streaming {completed}/{total_instances}")

        logger.info("Parallel WADO download complete.")
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

    def _on_download_complete(self, cache_dir, study_model, completion_callback, load_id):
        if load_id != StudyLoader._load_generation:
            logger.info("Ignoring stale study load completion (superseded by a newer request).")
            return

        if not cache_dir:
            if completion_callback:
                completion_callback(False)
            return

        logger.info(f"Download complete. Importing cache dir into Slicer: {cache_dir}")

        widget_ref = None
        try:
            logger.info("Clearing MRML scene for new study load...")
            slicer.mrmlScene.Clear(0)

            db = slicer.dicomDatabase
            if db and db.isOpen:
                target_study_uid = study_model.study_instance_uid
                logger.info(f"Removing old study reference {target_study_uid} from Slicer DICOM database...")
                db.removeStudy(target_study_uid)

            if hasattr(slicer.modules, "radpretationtools"):
                widget_ref = slicer.modules.radpretationtools
            elif hasattr(slicer.modules, "RadpretationTools"):
                widget_ref = slicer.modules.RadpretationTools

            if widget_ref:
                widget = widget_ref.widgetRepresentation().self()
                if hasattr(widget, "segmentation_service") and widget.segmentation_service:
                    widget.segmentation_service.active_study_uid = study_model.study_instance_uid
                    widget.segmentation_service.active_segmentation_node = None
                    widget.segmentation_service.mark_saved()
        except Exception as e:
            logger.error(f"Error clearing scene or resetting active segmentation: {e}")

        try:
            DICOMUtils.importDicom(cache_dir)
            logger.info("DICOM data imported to local Slicer database successfully.")

            db = slicer.dicomDatabase
            if db.isOpen:
                target_study_uid = study_model.study_instance_uid
                series_to_load = self._series_for_viewport(db, target_study_uid)

                if series_to_load:
                    logger.info(f"Auto-loading {len(series_to_load)} volume series into viewports...")
                    DICOMUtils.loadSeriesByUID(series_to_load)
                else:
                    logger.warning("Could not find imported series in Slicer DB to auto-load.")

            seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
            if seg_nodes:
                loaded_seg = list(seg_nodes)[0]
                logger.info(f"Detected loaded segmentation node: {loaded_seg.GetName()}")
                if widget_ref:
                    widget = widget_ref.widgetRepresentation().self()
                    if hasattr(widget, "segmentation_service") and widget.segmentation_service:
                        widget.segmentation_service.set_active_segmentation(loaded_seg)
            else:
                logger.info("No loaded segmentation nodes detected. Auto-creating segmentation...")
                if widget_ref:
                    try:
                        widget = widget_ref.widgetRepresentation().self()
                        if hasattr(widget, "onCreateSegmentationClicked"):
                            widget.onCreateSegmentationClicked()
                        elif hasattr(widget, "segmentation_service") and widget.segmentation_service:
                            widget.segmentation_service.create_segmentation()
                    except Exception as e:
                        logger.error(f"Failed to automatically create segmentation: {e}")

            if completion_callback:
                completion_callback(True)
        except Exception as e:
            logger.error(f"Failed to load cached DICOM into Slicer: {e}")
            if completion_callback:
                completion_callback(False)
        finally:
            logger.info("Keeping temporary download directory intact for active Slicer session.")
