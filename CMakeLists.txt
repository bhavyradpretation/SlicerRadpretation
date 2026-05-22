cmake_minimum_required(VERSION 3.20.6...3.22.6 FATAL_ERROR)

project(RadpretationExtension)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/bhavyradpretation/Radpretation-Slicer-Plugin")
set(EXTENSION_CONTRIBUTORS "Bhavy Raheja (Radpretation)")
set(EXTENSION_DESCRIPTION "AI-powered radiology workflow extension for 3D Slicer with Orthanc and DICOMWeb integration.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/bhavyradpretation/Radpretation-Slicer-Plugin/main/RadpretationExtension.png")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/bhavyradpretation/Radpretation-Slicer-Plugin/main/ss.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(RadpretationTools)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
