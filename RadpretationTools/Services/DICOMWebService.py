import requests
import json
from Utils.config import config
from Utils.logger import logger
from Models.StudyModel import StudyModel


class DICOMWebService:
    """Handles QIDO-RS and WADO-RS communication with Orthanc DICOMweb."""

    @staticmethod
    def _get_dicom_value(dicom_json, tag, default=""):
        try:
            if tag in dicom_json and "Value" in dicom_json[tag]:
                val = dicom_json[tag]["Value"]
                if len(val) > 0:
                    if isinstance(val[0], dict) and "Alphabetic" in val[0]:
                        return val[0]["Alphabetic"]
                    return str(val[0])
        except Exception:
            pass
        return default

    @staticmethod
    def fetch_study(study_uid, auth_header=None):
        """Fetch a specific study from the DICOMweb endpoint (QIDO-RS), respecting pagination limits."""
        url = f"{config.dicomweb_endpoint}/studies?StudyInstanceUID={study_uid}&limit=1&includefield=StudyDate&includefield=PatientName&includefield=ModalitiesInStudy"
        try:
            logger.info(f"Fetching specific study from {url}")
            kwargs = config.get_requests_kwargs()
            if auth_header:
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                kwargs['headers']['Authorization'] = auth_header

            response = requests.get(url, timeout=5, **kwargs)
            response.raise_for_status()
            studies_json = response.json()
            
            if not studies_json:
                return None
                
            s = studies_json[0]
            study = StudyModel(
                patient_name=DICOMWebService._get_dicom_value(s, "00100010", "Unknown"),
                patient_id=DICOMWebService._get_dicom_value(s, "00100020", "Unknown"),
                study_date=DICOMWebService._get_dicom_value(s, "00080020", ""),
                currentReviewer=DICOMWebService._get_dicom_value(s, "00081030", ""),
                accession_number=DICOMWebService._get_dicom_value(s, "00080050", ""),
                study_instance_uid=DICOMWebService._get_dicom_value(s, "0020000D", study_uid),
                modalities=DICOMWebService._get_dicom_value(s, "00080061", "")
            )
            if not study.modalities:
                study.modalities = DICOMWebService._get_dicom_value(s, "00080061", "UNK")
                
            return study
        except Exception as e:
            logger.error(f"Failed to fetch DICOMweb study {study_uid}: {e}")
            return None

    @staticmethod
    def fetch_all_study_instances(study_uid, auth_header=None):
        """Fetch list of all instances for a study in a single QIDO-RS request."""
        url = f"{config.dicomweb_endpoint}/studies/{study_uid}/instances"
        try:
            kwargs = config.get_requests_kwargs()
            if auth_header:
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                kwargs['headers']['Authorization'] = auth_header

            response = requests.get(url, timeout=10, **kwargs)
            response.raise_for_status()
            instances_json = response.json()
            
            instance_map = []
            for i in instances_json:
                inst_uid = DICOMWebService._get_dicom_value(i, "00080018", "")
                series_uid = DICOMWebService._get_dicom_value(i, "0020000E", "")
                if inst_uid and series_uid:
                    instance_map.append((series_uid, inst_uid))
            return instance_map
        except Exception as e:
            logger.error(f"Failed to fetch all instances for study {study_uid}: {e}")
            return []

    @staticmethod
    def download_instance(study_uid, series_uid, instance_uid, output_path, auth_header=None):
        """Download a single DICOM instance (WADO-URI)."""
        url = f"{config.orthanc_wado_uri}?requestType=WADO&studyUID={study_uid}&seriesUID={series_uid}&objectUID={instance_uid}&contentType=application/dicom"
        try:
            kwargs = config.get_requests_kwargs()
            if auth_header:
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                kwargs['headers']['Authorization'] = auth_header

            with requests.get(url, stream=True, timeout=10, **kwargs) as r:
                r.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Failed to download instance {instance_uid}: {e}")
    @staticmethod
    def upload_instance_stow_rs(study_uid, file_path, auth_header=None):
        """Upload a DICOM file using STOW-RS to DICOMweb endpoint."""
        url = f"{config.dicomweb_endpoint}/studies"
        try:
            kwargs = config.get_requests_kwargs()
            if auth_header:
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                kwargs['headers']['Authorization'] = auth_header

            with open(file_path, 'rb') as f:
                data = f.read()

            import uuid
            boundary = uuid.uuid4().hex
            
            headers = kwargs.get('headers', {})
            headers['Content-Type'] = f'multipart/related; type="application/dicom"; boundary="{boundary}"'
            headers['Accept'] = 'application/dicom+json'
            kwargs['headers'] = headers
            
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/dicom\r\n\r\n"
            ).encode('utf-8') + data + f"\r\n--{boundary}--\r\n".encode('utf-8')

            logger.info(f"Uploading instance to {url} via STOW-RS...")
            response = requests.post(url, data=body, **kwargs)
            response.raise_for_status()
            logger.info("Upload via STOW-RS successful.")
            return True
        except Exception as e:
            logger.error(f"Failed to upload instance via STOW-RS: {e}")
            return False
