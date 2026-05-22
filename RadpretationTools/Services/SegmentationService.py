import slicer
import vtk
from Utils.logger import logger
from Utils.events import ObserverManager

class SegmentationService:
    """Manages the Slicer Segment Editor workflow and tracks unsaved changes."""
    def __init__(self, on_changed_callback=None):
        self.has_unsaved_changes = False
        self.active_segmentation_node = None
        self.observer_manager = ObserverManager()
        self.on_changed_callback = on_changed_callback

    def create_segmentation(self):
        """Create a segmentation node and track its modifications."""
        self.active_segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "RadpretationSeg")
        self.active_segmentation_node.CreateDefaultDisplayNodes()
        
        # Link to active volume
        volume_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        if volume_nodes:
            # Use the first one
            vol = list(volume_nodes)[0]
            self.active_segmentation_node.SetReferenceImageGeometryParameterFromVolumeNode(vol)
            
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
        if volume_nodes:
            segmentEditorWidget.setSourceVolumeNode(list(volume_nodes)[0])

        logger.info("Segmentation created and tracking started.")

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
