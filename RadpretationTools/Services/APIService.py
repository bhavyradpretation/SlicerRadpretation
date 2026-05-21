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
    def fetch_reports(reviewer_id=None):
        """Fetches a list of scan tests (studies) from the API."""
        # Using a wide search to get reports, optionally filter by reviewer ID if needed, 
        # but the prompt API uses reviewer=<id>. If we don't know it, we can leave it blank or get from token info.
        # Actually, let's just make the request as close to the user's example as possible, 
        # perhaps omitting reviewer if we don't have it, or parsing it from login response.
        # Wait, the user's request URL:
        # http://localhost:8000/api/scanTests?page=1&limit=10&sortBy=report.updatedAt&sortOrder=desc&patientName=&scanStartDate=&scanEndDate=&reportStatus=&reviewer=68ee18a8dd6eedf5e2538851&testId=
        # We can just request without reviewer to get all, or we could have stored reviewer ID on login.
        
        # We will request the basic list for now.
        url = f"{config.web_api_url.rstrip('/')}/api/scanTests?page=1&limit=50&sortBy=report.updatedAt&sortOrder=desc"
        
        headers = {}
        if config.web_token:
            headers["Authorization"] = config.web_token

        try:
            logger.info(f"Fetching reports from {url}")
            response = requests.get(url, headers=headers, timeout=10)
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
                    
                    patient_name = f"{patient_info.get('firstName', '')} {patient_info.get('lastName', '')}".strip()
                    if not patient_name:
                        patient_name = "Unknown Patient"
                    
                    # StudyModel fields
                    study = StudyModel(
                        patient_name=patient_name,
                        patient_id=patient_info.get("patientId", "Unknown"),
                        study_instance_uid=report_info.get("studyInstanceUID", ""),
                        study_date=item.get("createdAt", ""),
                        currentReviewer=current_reviewer,
                        accession_number=item.get("refNumber", ""),
                        modalities=report_info.get("modality", "")
                    )
                    
                    # Only add if it has a valid UID
                    if study.study_instance_uid:
                        studies.append(study)
                        
                return True, studies
            else:
                return False, data.get("message", "Failed to fetch reports")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch reports: {e}")
            return False, str(e)
