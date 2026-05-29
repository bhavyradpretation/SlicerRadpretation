import os
import shutil
import tempfile
from Utils.logger import logger

class CacheManager:
    """Manages the temporary storage used for streaming DICOMs from DICOMweb."""
    
    def __init__(self):
        base_temp_dir = tempfile.gettempdir()
        try:
            import slicer
            if hasattr(slicer, 'app') and slicer.app is not None:
                slicer_temp = slicer.app.temporaryPath
                if slicer_temp:
                    base_temp_dir = slicer_temp
        except Exception as e:
            logger.debug(f"Could not get Slicer temporary path: {e}")

        cache_path = os.path.join(base_temp_dir, "RadpretationDICOMCache")
        self.cache_dir = os.path.normpath(cache_path).replace('\\', '/')
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _marker_path(self, study_uid):
        return os.path.join(self.cache_dir, f".{study_uid}.complete")

    def touch_cache(self, study_uid):
        """Touches the complete marker of a study cache folder to refresh its modification time."""
        try:
            marker_file = self._marker_path(study_uid)
            legacy_marker = os.path.join(self.cache_dir, study_uid, ".complete")
            check_path = marker_file if os.path.exists(marker_file) else legacy_marker
            study_dir = os.path.join(self.cache_dir, study_uid)
            if os.path.exists(check_path):
                import time
                os.utime(check_path, None)
                if os.path.isdir(study_dir):
                    os.utime(study_dir, None)
                logger.info(f"Touched cache for study: {study_uid}")
        except Exception as e:
            logger.warning(f"Failed to touch cache for study {study_uid}: {e}")

    def clear_cache(self):
        """Cleans up old cached studies that exceed the retention threshold."""
        try:
            from Utils.config import config
            retention_days = config.cache_retention_days
            
            # If set to Never Clear (e.g. 9999), we skip automatic cleanup
            if retention_days >= 9999:
                logger.info("Cache retention set to 'Never Clear'. Skipping automatic cleanup.")
                return

            if not os.path.exists(self.cache_dir):
                return

            import time
            now = time.time()
            threshold_seconds = retention_days * 24 * 3600

            cleaned_count = 0
            for name in os.listdir(self.cache_dir):
                item_path = os.path.join(self.cache_dir, name)
                if name.startswith(".") and name.endswith(".complete"):
                    check_path = item_path
                elif os.path.isdir(item_path):
                    marker_file = os.path.join(item_path, ".complete")
                    check_path = marker_file if os.path.exists(marker_file) else item_path
                else:
                    continue

                mtime = os.path.getmtime(check_path)
                age_seconds = now - mtime
                if age_seconds > threshold_seconds:
                    logger.info(f"Cleaning up old cache: {item_path} (age: {age_seconds / 3600:.1f} hours)")
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                        study_uid = name[1:-9] if name.startswith(".") else None
                        if study_uid:
                            study_dir = os.path.join(self.cache_dir, study_uid)
                            if os.path.isdir(study_dir):
                                shutil.rmtree(study_dir, ignore_errors=True)
                    cleaned_count += 1
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old cache folder(s).")
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")

    def clear_all_cache(self):
        """Completely wipes the entire temporary DICOM cache to free space immediately."""
        try:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
            self._ensure_cache_dir()
            logger.info("All temporary DICOM cache cleared.")
        except Exception as e:
            logger.error(f"Failed to clear all cache: {e}")

    def get_study_cache_dir(self, study_uid):
        """Gets a dedicated directory for a specific study."""
        study_dir = os.path.join(self.cache_dir, study_uid)
        if not os.path.exists(study_dir):
            os.makedirs(study_dir)
        return study_dir
