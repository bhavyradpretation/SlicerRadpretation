# Radpretation-plugin

## 1. What is Radpretation-plugin?
The **Radpretation-plugin** (RadpretationTools) is an advanced workstation integration extension for [3D Slicer](https://www.slicer.org/). It serves as a bridge between the cloud-based clinical web workflow (like the Radpretation Next.js/OHIF viewer platform) and heavy on-premise 3D radiological processing. By running a local bridge server within Slicer, it enables automated remote control of the Slicer workspace from a web browser.

## 2. Features
*   **Automated Study Loading**: Stream DICOM instances directly from an Orthanc PACS using high-performance, multi-threaded DICOMweb (QIDO-RS / WADO-URI) requests.
*   **One-Click Uploads**: Automatically packages Slicer segmentations into standard DICOM SEG objects and pushes them back to Orthanc over REST APIs.
*   **Local Bridge Server**: Runs a background HTTP API on `localhost:5000` to allow the Radpretation web application to send commands to Slicer (e.g., triggering a study load remotely).
*   **Dynamic PACS Configuration**: Manage PACS endpoints and basic authentication directly from the UI without modifying source code.
*   **Asynchronous Processing**: Prevents Slicer UI freezes by handling heavy I/O operations (streaming slices, Slicer DB importing, network uploads) in dedicated background threads.

## 3. Installation
1. Open **3D Slicer**.
2. Navigate to `Edit > Application Settings > Modules`.
3. Click the `>>` icon under **Additional module paths** and select the `RadpretationTools` directory.
4. Restart Slicer.
5. In the Module dropdown (usually the magnifying glass icon), search for **RadpretationTools** and select it.

## 4. Development Setup
This extension relies entirely on the internal Python environment shipped with Slicer.
1. Clone this repository to your local machine.
2. Follow the Installation steps above to link Slicer to your local repository path.
3. If you need to install custom Python packages, use Slicer's embedded Python executable:
   ```bash
   "C:\Program Files\Slicer 5.x.x\bin\PythonSlicer.exe" -m pip install <package>
   ```
4. **Threading Rules**: 3D Slicer's `slicer.mrmlScene` and UI elements are **not** thread-safe. When writing async workers in the `Services/` directory, utilize `Utils.helpers.AsyncTaskRunner` and `Utils.helpers.MainThreadDispatcher` to safely push GUI updates and MRML node creations back to the main thread.

## 5. PACS Configuration
The plugin supports dynamic PACS configuration via Slicer's `qt.QSettings`:
1. Expand the **PACS Settings** collapsible button in the plugin UI.
2. Enter the **PACS URL** (default: `http://localhost:8042`).
3. Enter the **DICOMWeb Path** (default: `/dicom-web`).
4. Select the **Authentication Mode** (`None` or `Basic Auth`).
5. If using `Basic Auth`, provide your **Username** and **Password**.
6. Click **Save Settings**. These settings will persist across Slicer restarts.

## 6. How Open Study Works
When a user clicks "Open in 3D Slicer" on the Radpretation web platform:
1. The web platform sends a local HTTP POST request to `http://localhost:5000/load-study` (the Slicer Local Bridge Server).
2. The payload contains the `StudyInstanceUID`.
3. Slicer's `StudyLoader` service kicks off a background thread that queries Orthanc via DICOMweb.
4. The instances are downloaded in parallel to a local temporary cache directory.
5. Once downloaded, the DICOM files are verified and securely imported into the local Slicer DICOM Database.
6. Finally, the series are automatically loaded into the Slicer 3D viewports via `DICOMUtils.loadSeriesByUID()`.

## 7. Screenshots
*(Add screenshots here once UI is finalized)*
* `![Main UI](./Resources/main_ui.png)`
* `![PACS Settings](./Resources/pacs_settings.png)`

## 8. Architecture
The codebase is structured into modular domains:
```text
RadpretationTools/
├── RadpretationTools.py       # Main Slicer module entry point
├── Integrations/              # External API clients (Orthanc, Bridge)
├── Models/                    # Data models representing DICOM entities
├── Services/                  # Core business logic (Cache, DICOMWeb, Loading, Export)
├── UI/                        # Modular user interface components (Main, Settings, Viewer)
└── Utils/                     # Cross-cutting utilities (Config, Logger, Async Helpers)
```

## 9. Roadmap
*   **Auto-Update Mechanism**: Allow the plugin to pull updates directly from the web platform.
*   **RTSTRUCT Support**: Expand native DICOM export to support RTSTRUCT in addition to DICOM SEG.
*   **Two-Way Synchronization**: Automatically pull previous segmentations from Orthanc when opening a study.
*   **Progress Overlays**: Native Slicer UI overlays for download/upload progress bars.

## 10. License
Radpretation is licensed under the Apache License 2.0.

You are free to use, modify, and distribute this project in accordance with the license terms. See the [LICENSE](LICENSE) file for full details.
