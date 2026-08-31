class ETLError(Exception):
    """Base ETL exception."""


class ConfigurationError(ETLError):
    """Invalid or incomplete configuration."""


class SourceDataError(ETLError):
    """Input data is missing or inconsistent."""


class ConnectorError(ETLError):
    """Remote API request failed."""
