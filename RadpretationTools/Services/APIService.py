import requests
from Utils.config import config
from Utils.logger import logger
from Models.StudyModel import StudyModel

class APIService:
    """Handles communication with the Web Application API (Authentication, Fetching Studies)."""

    @staticmethod
    def login(email, password):
        """Logs in the user and saves the access token in config."""
        url = f"{config.web_api_url.rstrip('/')}/api/auth/login"
        payload = {
            "email": email,
            "password": password,
            "ip": "127.0.0.1",
            "platform": "Win32",
            "device": "Radpretation Slicer Plugin"
        }
        try:
            logger.info(f"Attempting login to {url}")
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("statusCode") == 200 and "data" in data and "accessToken" in data["data"]:
                token = data["data"]["accessToken"]
                config.web_token = f"Bearer {token}"
                logger.info("Login successful, token saved.")
                return True, "Login successful"
            else:
                return False, data.get("message", "Unknown error during login")
        except requests.exceptions.RequestException as e:
            logger.error(f"Login failed: {e}")
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    return False, error_data.get("message", str(e))
                except ValueError:
                    return False, str(e)
            return False, str(e)

    @staticmethod
    def fetch_reports(reviewer_id=None, page=1, limit=10, patient_name=""):
        """Fetches a list of scan tests (studies) from the API with pagination and search."""
        params = {
            "page": page,
            "limit": limit,
            "sortBy": "report.updatedAt",
            "sortOrder": "desc",
            "patientName": patient_name
        }
        if reviewer_id:
            params["reviewer"] = reviewer_id
            
        url = f"{config.web_api_url.rstrip('/')}/api/scanTests"
        
        headers = {}
        if config.web_token:
            headers["Authorization"] = config.web_token

        try:
            logger.info(f"Fetching reports from {url} with params {params}")
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("statusCode") == 200 and "data" in data and "items" in data["data"]:
                items = data["data"]["items"]
                studies = []
                for item in items:
                    patient_info = item.get("patient", {})
                    report_info = item.get("report", {})

                    current_reviewer_list = report_info.get("currentReviewer", [])
                    current_reviewer = ""
                    if current_reviewer_list and isinstance(current_reviewer_list, list):
                        reviewer = current_reviewer_list[0]
                        first_name = reviewer.get("firstName", "")
                        last_name = reviewer.get("lastName", "")
                        current_reviewer = f"{first_name} {last_name}".strip()
                    
                    patient_name_val = f"{patient_info.get('firstName', '')} {patient_info.get('lastName', '')}".strip()
                    if not patient_name_val:
                        patient_name_val = "Unknown Patient"
                    
                    status_val = item.get("status", "")
                    
                    # StudyModel fields
                    study = StudyModel(
                        patient_name=patient_name_val,
                        patient_id=patient_info.get("patientId", "Unknown"),
                        study_instance_uid=report_info.get("studyInstanceUID", ""),
                        study_date=item.get("createdAt", ""),
                        currentReviewer=current_reviewer,
                        accession_number=item.get("refNumber", ""),
                        modalities=report_info.get("modality", ""),
                        status=status_val
                    )
                    
                    # Only add if it has a valid UID
                    if study.study_instance_uid:
                        studies.append(study)
                        
                # Metadata parsing
                meta = data["data"].get("meta", {})
                total_pages = meta.get("totalPages", 1)
                current_page = meta.get("currentPage", page)
                
                # Resilient fallback if meta is empty
                if not meta:
                    if len(items) < limit:
                        total_pages = page
                    else:
                        total_pages = page + 1
                        
                return True, (studies, total_pages, current_page)
            else:
                return False, data.get("message", "Failed to fetch reports")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch reports: {e}")
            return False, str(e)
