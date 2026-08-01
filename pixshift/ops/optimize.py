"""Operation wrappers for optimize analysis workflows."""

from ..optimize_engine import OptimizeResult, analyze_image


def analyze(input_path: str) -> OptimizeResult:
    """Analyze one image and return optimization recommendation."""
    return analyze_image(input_path)
