import os
import shutil
import tempfile
import slicer
from Integrations.orthanc_client import OrthancClient
from Utils.logger import logger
from Utils.helpers import AsyncTaskRunner

class ExportService:
    """Exports DICOM SEG/RTSTRUCT and uploads to Orthanc."""
    
    def __init__(self, segmentation_service):
        self.seg_service = segmentation_service

    def export_and_upload(self, callback=None):
        if hasattr(self.seg_service, "prepare_for_export"):
            ready, message = self.seg_service.prepare_for_export()
            if not ready:
                logger.error(f"Export preflight failed: {message}")
                if callback:
                    callback(False, message)
                return

        seg_node = self.seg_service.get_active_segmentation()
        if not seg_node:
            logger.error("No active segmentation to export.")
            if callback:
                callback(False, "No active segmentation found.")
            return

        # Slicer DICOM export must run on the main thread because it interacts with the MRML scene and Subject Hierarchy
        logger.info("Exporting DICOM SEG locally...")
        export_dir = tempfile.mkdtemp()
        
        try:
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            segItemID = shNode.GetItemByDataNode(seg_node)
            
            # Log segmentation and reference volume details for easy troubleshooting of 2D/CR exports
            logger.info(f"Exporting segmentation node: {seg_node.GetName()}, SH Item ID: {segItemID}")
            ref_volume_id = seg_node.GetNodeReferenceID("ReferenceVolumeGeometry")
            if ref_volume_id:
                ref_volume = slicer.mrmlScene.GetNodeByID(ref_volume_id)
                if ref_volume:
                    ref_vol_item = shNode.GetItemByDataNode(ref_volume)
                    logger.info(f"Reference Volume Node: {ref_volume.GetName()} ({ref_volume.GetClassName()}), SH Item ID: {ref_vol_item}")
                else:
                    logger.warning(f"Reference Volume Node with ID '{ref_volume_id}' not found in MRML scene.")
            else:
                logger.warning("No ReferenceVolumeGeometry set on the segmentation node.")

            dicomPlugin = slicer.modules.dicomPlugins['DICOMSegmentationPlugin']()
            exportables = dicomPlugin.examineForExport(segItemID)
            
            if not exportables:
                raise Exception("Segmentation cannot be exported. Ensure the segmentation has a valid reference volume and the reference volume was loaded from a DICOM database.")
            
            exportable = exportables[0]
            exportable.directory = export_dir
            
            logger.info("Generating DICOM SEG file using native plugin...")
            # The plugin expects a LIST of exportables. Return value (Slicer 5.x):
            #   "" = success; non-empty str = error message. Older builds may return True/False.
            result = dicomPlugin.export([exportable])
            if isinstance(result, str):
                if result.strip():
                    raise Exception(result)
            elif not result:
                raise Exception("DICOM Segmentation Plugin failed to export.")

            # Plugin writes e.g. subject_hierarchy_export.SEG{datetime}.dcm (may be nested)
            exported_files = []
            for root, _, names in os.walk(export_dir):
                for name in names:
                    if name.lower().endswith(".dcm"):
                        exported_files.append(os.path.join(root, name))
            exported_files.sort(key=os.path.getmtime, reverse=True)
            if not exported_files:
                logger.error(f"No .dcm under export dir (listing): {export_dir}")
                raise Exception(
                    "DICOM SEG export produced no .dcm file. "
                    "Paint at least one non-empty segment, set segment terminology (category & type), "
                    "and ensure the source volume is still in the DICOM database."
                )

            export_path = exported_files[0]

            from Services.StudyLoader import StudyLoader
            StudyLoader.patch_dicom_for_export(export_path)

            logger.info(f"Export completed to {export_path}. Starting background upload...")
            
            # Extract StudyInstanceUID to associate the upload properly
            study_uid = self.seg_service.get_active_study_uid() if hasattr(self.seg_service, 'get_active_study_uid') else None
            
            # Run the network upload in the background
            AsyncTaskRunner.run(
                task_func=self._upload_worker,
                callback=lambda success: self._on_upload_complete(success, export_path, export_dir, callback),
                file_path=export_path,
                study_uid=study_uid
            )
        except Exception as e:
            logger.error(f"Export failed: {e}")
            if callback: callback(False, f"Export failed: {e}")

    def _upload_worker(self, file_path, study_uid=None):
        from Services.DICOMWebService import DICOMWebService
        # study_uid is technically required by DICOMweb STOW-RS route, but Orthanc might accept it on the root endpoint. 
        # But STOW-RS standard is POST /dicom-web/studies. DICOMWebService already uses /dicom-web/studies.
        return DICOMWebService.upload_instance_stow_rs(study_uid, file_path)

    def _on_upload_complete(self, success, file_path, export_dir, callback):
        # Cleanup
        try:
            if os.path.isdir(export_dir):
                shutil.rmtree(export_dir, ignore_errors=True)
            elif os.path.isfile(file_path):
                os.remove(file_path)
        except Exception:
            pass

        if success:
            logger.info("Upload to Orthanc successful.")
            self.seg_service.mark_saved()
            if callback: callback(True, "Upload Complete")
        else:
            logger.error("Upload to Orthanc failed.")
            if callback: callback(False, "Upload Failed")
