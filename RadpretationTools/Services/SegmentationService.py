import slicer
import vtk
from Utils.logger import logger
from Utils.events import ObserverManager

class SegmentationService:
    """Manages the Slicer Segment Editor workflow and tracks unsaved changes."""
    def __init__(self, on_changed_callback=None):
        self.has_unsaved_changes = False
        self.active_segmentation_node = None
        self.active_study_uid = None
        self.observer_manager = ObserverManager()
        self.on_changed_callback = on_changed_callback

    def create_segmentation(self):
        """Create a segmentation node and track its modifications."""
        self.active_segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "RadpretationSeg")
        self.active_segmentation_node.CreateDefaultDisplayNodes()
        
        # Link to active volume dynamically by checking the currently visible background volume first,
        # falling back to the first available scalar volume node in the scene.
        vol = None
        try:
            layoutManager = slicer.app.layoutManager()
            if layoutManager:
                redWidget = layoutManager.sliceWidget("Red")
                if redWidget:
                    sliceLogic = redWidget.sliceLogic()
                    sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
                    if sliceCompositeNode:
                        volumeID = sliceCompositeNode.GetBackgroundVolumeID()
                        if volumeID:
                            vol = slicer.mrmlScene.GetNodeByID(volumeID)
        except Exception as e:
            logger.debug(f"Could not get Red slice background volume: {e}")
            
        if not vol:
            volume_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
            if volume_nodes:
                vol = list(volume_nodes)[0]

        if vol:
            self.active_segmentation_node.SetReferenceImageGeometryParameterFromVolumeNode(vol)
            self.active_segmentation_node.SetNodeReferenceID("ReferenceVolumeGeometry", vol.GetID())
            
            # Place the segmentation node in the same SubjectHierarchy folder (Study) as the volume
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            volItemID = shNode.GetItemByDataNode(vol)
            if volItemID:
                studyItemID = shNode.GetItemParent(volItemID)
                if studyItemID:
                    segItemID = shNode.GetItemByDataNode(self.active_segmentation_node)
                    shNode.SetItemParent(segItemID, studyItemID)
                    logger.info("Segmentation placed under the correct Study in SubjectHierarchy.")
            
        self._start_tracking()
        
        # Open Slicer Segment Editor
        slicer.util.selectModule("SegmentEditor")
        
        # Set the active nodes in the segment editor widget
        segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
        segmentEditorWidget.setSegmentationNode(self.active_segmentation_node)
        if vol:
            segmentEditorWidget.setSourceVolumeNode(vol)

        logger.info("Segmentation created and tracking started.")

    def set_active_segmentation(self, seg_node):
        """Set an existing segmentation node as active and track its modifications."""
        self.active_segmentation_node = seg_node
        self.has_unsaved_changes = False
        if self.on_changed_callback:
            self.on_changed_callback(False)
        self._start_tracking()
        
        # Open Slicer Segment Editor
        slicer.util.selectModule("SegmentEditor")
        
        # Link to reference volume and configure Segment Editor
        vol = None
        ref_volume_id = seg_node.GetNodeReferenceID("ReferenceVolumeGeometry")
        if ref_volume_id:
            vol = slicer.mrmlScene.GetNodeByID(ref_volume_id)
        if not vol:
            try:
                layoutManager = slicer.app.layoutManager()
                if layoutManager:
                    redWidget = layoutManager.sliceWidget("Red")
                    if redWidget:
                        sliceLogic = redWidget.sliceLogic()
                        sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
                        if sliceCompositeNode:
                            volumeID = sliceCompositeNode.GetBackgroundVolumeID()
                            if volumeID:
                                vol = slicer.mrmlScene.GetNodeByID(volumeID)
            except Exception as e:
                logger.debug(f"Could not get Red slice background volume: {e}")
        if not vol:
            volume_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
            if volume_nodes:
                vol = list(volume_nodes)[0]
                
        if vol:
            seg_node.SetReferenceImageGeometryParameterFromVolumeNode(vol)
            seg_node.SetNodeReferenceID("ReferenceVolumeGeometry", vol.GetID())
            
            # Place the segmentation node in the same SubjectHierarchy folder (Study) as the volume
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            volItemID = shNode.GetItemByDataNode(vol)
            if volItemID:
                studyItemID = shNode.GetItemParent(volItemID)
                if studyItemID:
                    segItemID = shNode.GetItemByDataNode(self.active_segmentation_node)
                    shNode.SetItemParent(segItemID, studyItemID)
                    logger.info("Segmentation placed under the correct Study in SubjectHierarchy.")
            
        segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
        if segmentEditorWidget:
            segmentEditorWidget.setSegmentationNode(self.active_segmentation_node)
            if vol:
                segmentEditorWidget.setSourceVolumeNode(vol)

        logger.info(f"Segmentation node '{seg_node.GetName()}' set as active and tracking started.")

    def get_active_study_uid(self):
        """Get the StudyInstanceUID associated with the current segmentation or active volume."""
        if hasattr(self, 'active_study_uid') and self.active_study_uid:
            return self.active_study_uid
            
        # Fallback to robust SubjectHierarchy check
        if self.active_segmentation_node:
            ref_volume_id = self.active_segmentation_node.GetNodeReferenceID("ReferenceVolumeGeometry")
            if ref_volume_id:
                vol_node = slicer.mrmlScene.GetNodeByID(ref_volume_id)
                if vol_node:
                    uid = self._get_study_uid_from_volume(vol_node)
                    if uid:
                        return uid
        
        volume_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        for vol_node in volume_nodes:
            uid = self._get_study_uid_from_volume(vol_node)
            if uid:
                return uid
        return None

    def _get_study_uid_from_volume(self, vol_node):
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        if shNode:
            itemID = shNode.GetItemByDataNode(vol_node)
            if itemID:
                studyInstanceUID = shNode.GetItemUID(itemID, "StudyInstanceUID")
                if studyInstanceUID:
                    return studyInstanceUID
                
                studyItemID = shNode.GetItemParent(itemID)
                if studyItemID:
                    studyInstanceUID = shNode.GetItemUID(studyItemID, "StudyInstanceUID")
                    if studyInstanceUID:
                        return studyInstanceUID
        
        uid = vol_node.GetAttribute("DICOM.StudyInstanceUID")
        if uid:
            return uid
            
        seriesInstanceUID = vol_node.GetAttribute("DICOM.SeriesInstanceUID")
        if seriesInstanceUID and slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
            studyInstanceUID = slicer.dicomDatabase.studyForSeries(seriesInstanceUID)
            if studyInstanceUID:
                return studyInstanceUID
                
        return None

    def _start_tracking(self):
        self.observer_manager.remove_all()
        if self.active_segmentation_node:
            self.observer_manager.add_observer(
                self.active_segmentation_node, 
                vtk.vtkCommand.ModifiedEvent, 
                self._on_segmentation_modified
            )

    def _on_segmentation_modified(self, caller, event):
        if not self.has_unsaved_changes:
            self.has_unsaved_changes = True
            logger.info("Segmentation edited. Unsaved changes set to True.")
            if self.on_changed_callback:
                self.on_changed_callback(True)

    def mark_saved(self):
        self.has_unsaved_changes = False
        logger.info("Segmentation saved. Unsaved changes cleared.")
        if self.on_changed_callback:
            self.on_changed_callback(False)

    def get_active_segmentation(self):
        return self.active_segmentation_node
