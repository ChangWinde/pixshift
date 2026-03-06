"""Shared typed models for command summaries."""

from dataclasses import dataclass


@dataclass
class OperationSummary:
    """Aggregate counters and sizes for batch operations."""

    total: int = 0
    success: int = 0
    failed: int = 0
    total_input_size: int = 0
    total_output_size: int = 0

    def register(self, input_size: int, output_size: int, ok: bool) -> None:
        """Update summary counters from a single operation result."""
        self.total += 1
        self.total_input_size += int(input_size or 0)
        if ok:
            self.success += 1
            self.total_output_size += int(output_size or 0)
        else:
            self.failed += 1

