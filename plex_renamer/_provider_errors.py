"""Provider-neutral exceptions shared without importing the provider registry."""


class SeasonMapUnavailableError(RuntimeError):
    """Provider could not return a trustworthy season map for a known show."""
