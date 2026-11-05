"""Install-plane failure raised before any filesystem write."""


class InstallError(ValueError):
    """An artifact, pin, profile or selection the install plane must refuse."""
