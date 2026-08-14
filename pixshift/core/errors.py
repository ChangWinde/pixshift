"""Typed policy errors shared by command and engine boundaries."""


class OperationPolicyError(ValueError):
    """Base error for a rejected operation plan."""

    code = "operation_policy_error"


class ImageTooLargeError(OperationPolicyError):
    """The image exceeds the pixel budget that guards against decompression bombs."""

    code = "image_too_large"

    def __init__(self, pixels: int, limit: int) -> None:
        super().__init__(f"{self.code}:{pixels}>{limit}")


class InvalidFilenameComponentError(OperationPolicyError):
    """A filename fragment contains path syntax or unsafe bytes."""

    code = "invalid_filename_component"


class OutputBoundaryError(OperationPolicyError):
    """A planned output escapes its approved root directory."""

    code = "output_boundary_violation"


class OutputCollisionError(OperationPolicyError):
    """Multiple source files resolve to the same output path."""

    code = "output_collision"


class AnimatedInputNotSupportedError(OperationPolicyError):
    """A still-image operation received a multi-frame image."""

    code = "animated_input_not_supported"

    def __init__(self) -> None:
        super().__init__(self.code)
