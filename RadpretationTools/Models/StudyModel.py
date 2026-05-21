from dataclasses import dataclass, field
from typing import List, Any

@dataclass
class StudyModel:
    patient_name: str
    patient_id: str
    study_instance_uid: str
    study_date: str
    currentReviewer: str
    accession_number: str
    modalities: str
    series: List[Any] = field(default_factory=list)
