"""Staff behavior detection module — Phase 3.

Covers: person detection (YOLO), PPE compliance, abnormal behavior
(loitering / whispering / unauthorized zone entry).
"""

from edge.staff_behavior.detector import StaffBehaviorDetector, DetectionResult

__all__ = ["StaffBehaviorDetector", "DetectionResult"]
