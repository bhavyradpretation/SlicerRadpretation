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

    def get_next_segmentation_name(self):
        """Find the maximum suffix number in existing segmentation nodes in the scene and return the next one."""
        prefix = "RadpretationSeg"
        max_num = 0
        nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for node in nodes:
            name = node.GetName()
            if name.startswith(prefix):
                suffix = name[len(prefix):]
                if suffix.startswith("_"):
                    suffix = suffix[1:]
                try:
                    num = int(suffix)
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        next_num = max_num + 1
        return f"{prefix}_{next_num}"

    def resolve_active_segmentation(self):
        """Sync active segmentation from Segment Editor, tracked node, or scene."""
        try:
            widget_repr = slicer.modules.segmenteditor.widgetRepresentation()
            if widget_repr:
                editor = widget_repr.self().editor
                if editor and editor.segmentationNode():
                    self.active_segmentation_node = editor.segmentationNode()
                    return self.active_segmentation_node
        except Exception as e:
            logger.debug(f"Could not read Segment Editor active segmentation: {e}")

        if self.active_segmentation_node and self.active_segmentation_node.GetScene():
            return self.active_segmentation_node

        seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        if seg_nodes:
            self.active_segmentation_node = list(seg_nodes)[0]
        else:
            self.active_segmentation_node = None
        return self.active_segmentation_node

    def _get_reference_volume_for_segmentation(self, seg_node):
        if not seg_node:
            return None
        ref_id = seg_node.GetNodeReferenceID("ReferenceVolumeGeometry")
        if ref_id:
            vol = slicer.mrmlScene.GetNodeByID(ref_id)
            if vol:
                return vol
        return self._resolve_reference_volume()

    def _open_segment_editor(self, seg_node, vol=None):
        if not seg_node:
            return
        if not vol:
            vol = self._get_reference_volume_for_segmentation(seg_node)
        slicer.util.selectModule("SegmentEditor")
        try:
            editor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            if editor:
                editor.setSegmentationNode(seg_node)
                if vol:
                    editor.setSourceVolumeNode(vol)
        except Exception as e:
            logger.warning(f"Could not configure Segment Editor: {e}")

    def create_segmentation(self):
        """Create a segmentation node. Returns True on success."""
        vol = self._resolve_reference_volume()
        if not vol:
            slicer.util.warningDisplay(
                "No volume is loaded. Open a study first, then create a segmentation.",
                windowTitle="Create Segmentation",
            )
            return False

        name = self.get_next_segmentation_name()
        self.active_segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        self.active_segmentation_node.CreateDefaultDisplayNodes()
        self._link_segmentation_to_volume(self.active_segmentation_node, vol)
        self._ensure_default_segment(self.active_segmentation_node)

        self.has_unsaved_changes = False
        if self.on_changed_callback:
            self.on_changed_callback(False)

        self._start_tracking()
        self._open_segment_editor(self.active_segmentation_node, vol)
        logger.info("Segmentation created and tracking started.")
        return True

    def set_active_segmentation(self, seg_node):
        """Set an existing segmentation node as active and track its modifications."""
        self.active_segmentation_node = seg_node
        self.has_unsaved_changes = False
        if self.on_changed_callback:
            self.on_changed_callback(False)
        self._start_tracking()
        self._ensure_default_segment(self.active_segmentation_node)

        vol = self._get_reference_volume_for_segmentation(seg_node)
        if vol:
            self._link_segmentation_to_volume(seg_node, vol)

        self._open_segment_editor(self.active_segmentation_node, vol)
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
        return self.resolve_active_segmentation()

    def delete_segmentation(self):
        """Delete the active segmentation node, clear observers, and clear Slicer Segment Editor focus."""
        if not self.active_segmentation_node:
            logger.warning("No active segmentation node to delete.")
            return False

        logger.info(f"Deleting active segmentation node: {self.active_segmentation_node.GetName()}")
        
        # Stop tracking observers
        self.observer_manager.remove_all()
        
        # Remove from scene
        slicer.mrmlScene.RemoveNode(self.active_segmentation_node)
        self.active_segmentation_node = None
        self.has_unsaved_changes = False
        
        if self.on_changed_callback:
            self.on_changed_callback(False)

        # Clear active segmentation node in Segment Editor
        try:
            segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            if segmentEditorWidget:
                segmentEditorWidget.setSegmentationNode(None)
        except Exception as e:
            logger.debug(f"Failed to clear segmentation node in segment editor: {e}")
            
        return True

    def validate_export_ready(self):
        """Validate if the active segmentation node is ready for export."""
        node = self.resolve_active_segmentation()
        if not node:
            return False, "No active segmentation node."
        
        # Check if reference volume geometry is linked
        ref_vol_id = node.GetNodeReferenceID("ReferenceVolumeGeometry")
        if not ref_vol_id:
            # Try to resolve reference volume dynamically if not set
            vol = self._resolve_reference_volume()
            if vol:
                self._link_segmentation_to_volume(node, vol)
                ref_vol_id = node.GetNodeReferenceID("ReferenceVolumeGeometry")
                
        if not ref_vol_id:
            return False, "No reference volume linked to this segmentation."
            
        ref_vol = slicer.mrmlScene.GetNodeByID(ref_vol_id)
        if not ref_vol:
            return False, "Linked reference volume was not found in the scene."
            
        # Verify there is at least one segment
        segmentation = node.GetSegmentation()
        if not segmentation or segmentation.GetNumberOfSegments() == 0:
            return False, "Segmentation has no segments. Please create at least one segment."
            
        return True, ""

    def prepare_for_export(self):
        """Preflight checks before exporting."""
        self.resolve_active_segmentation()
        return self.validate_export_ready()

    def rename_active_segmentation(self, new_name):
        """Rename the active segmentation node. Returns (success, message)."""
        node = self.resolve_active_segmentation()
        if not node:
            return False, "No active segmentation node found."

        new_name = (new_name or "").strip()
        if not new_name:
            return False, "Segmentation name cannot be empty."

        invalid_chars = '\\/:*?"<>|'
        if any(ch in new_name for ch in invalid_chars):
            return False, f"Name cannot contain any of: {invalid_chars}"

        for other in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            if other != node and other.GetName() == new_name:
                return False, f"A segmentation node named '{new_name}' already exists."

        old_name = node.GetName()
        if old_name == new_name:
            return True, new_name

        node.SetName(new_name)
        self._open_segment_editor(node, self._get_reference_volume_for_segmentation(node))
        logger.info(f"Renamed active segmentation from '{old_name}' to '{new_name}'")
        return True, new_name

    def _ensure_default_segment(self, node):
        """Ensure the segmentation node has at least one segment."""
        if not node:
            return
        segmentation = node.GetSegmentation()
        if segmentation and segmentation.GetNumberOfSegments() == 0:
            segment_id = segmentation.AddEmptySegment("Segment_1")
            logger.info(f"Created default empty segment 'Segment_1' for node '{node.GetName()}'.")

    def _resolve_reference_volume(self):
        """Find a suitable reference volume in the scene."""
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
        return vol

    def _link_segmentation_to_volume(self, node, vol):
        """Link a segmentation node to a reference volume and SubjectHierarchy."""
        if not node or not vol:
            return
        node.SetReferenceImageGeometryParameterFromVolumeNode(vol)
        node.SetNodeReferenceID("ReferenceVolumeGeometry", vol.GetID())
        
        # Link in Subject Hierarchy
        try:
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            if shNode:
                volItemID = shNode.GetItemByDataNode(vol)
                if volItemID:
                    studyItemID = shNode.GetItemParent(volItemID)
                    if studyItemID:
                        segItemID = shNode.GetItemByDataNode(node)
                        if segItemID:
                            shNode.SetItemParent(segItemID, studyItemID)
                            logger.info(f"Segmentation node '{node.GetName()}' linked to volume '{vol.GetName()}' under correct Study in SubjectHierarchy.")
        except Exception as e:
            logger.warning(f"Failed to place segmentation in SubjectHierarchy: {e}")
