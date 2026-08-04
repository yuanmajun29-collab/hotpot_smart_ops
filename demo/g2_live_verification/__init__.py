"""
G2: 椒江店真实验证工具包
"""

from .live_verifier import G2LiveVerifier, VerificationReport
from .expo_evidence_generator import ExpoEvidenceGenerator

__all__ = ["G2LiveVerifier", "VerificationReport", "ExpoEvidenceGenerator"]
