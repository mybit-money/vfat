"""VFAT report development overlay."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

INPUT_SCHEMA_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.0"
CALCULATION_VERSION = "1.2"

__all__ = ["CALCULATION_VERSION", "INPUT_SCHEMA_VERSION", "REPORT_SCHEMA_VERSION"]
