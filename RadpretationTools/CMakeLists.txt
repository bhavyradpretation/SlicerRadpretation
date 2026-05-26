#-----------------------------------------------------------------------------
set(MODULE_NAME RadpretationTools)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  UI/__init__.py
  UI/LoginWidget.py
  UI/MainWidget.py
  UI/SettingsWidget.py
  UI/StudiesWidget.py
  UI/ToolbarWidget.py
  UI/ViewerWidget.py
  Services/__init__.py
  Services/APIService.py
  Services/CacheManager.py
  Services/DICOMWebService.py
  Services/ExportService.py
  Services/LocalBridgeServer.py
  Services/SegmentationService.py
  Services/StudyLoader.py
  Integrations/__init__.py
  Integrations/bridge_client.py
  Integrations/orthanc_client.py
  Models/__init__.py
  Models/StudyModel.py
  Utils/__init__.py
  Utils/config.py
  Utils/constants.py
  Utils/events.py
  Utils/helpers.py
  Utils/logger.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/UI/${MODULE_NAME}.ui
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )
