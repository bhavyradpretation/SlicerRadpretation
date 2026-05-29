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

    def clear_cache(self):
        """Completely wipes the temporary DICOM cache to free space."""
        try:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
            self._ensure_cache_dir()
            logger.info("Temporary DICOM cache cleared.")
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")

    def get_study_cache_dir(self, study_uid):
        """Gets a dedicated directory for a specific study."""
        study_dir = os.path.join(self.cache_dir, study_uid)
        if not os.path.exists(study_dir):
            os.makedirs(study_dir)
        return study_dir
