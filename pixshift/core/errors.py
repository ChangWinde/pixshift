"""Typed policy errors shared by command and engine boundaries."""


class OperationPolicyError(ValueError):
    """Base error for a rejected operation plan."""

    code = "operation_policy_error"


class InvalidFilenameComponentError(OperationPolicyError):
    """A filename fragment contains path syntax or unsafe bytes."""

    code = "invalid_filename_component"


class OutputBoundaryError(OperationPolicyError):
    """A planned output escapes its approved root directory."""

    code = "output_boundary_violation"


class OutputCollisionError(OperationPolicyError):
    """Multiple source files resolve to the same output path."""

    code = "output_collision"
