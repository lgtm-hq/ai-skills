"""Install plane: consume resolved artifacts without resolving anything new.

Modules here read only an artifact directory, an optional repository lock and
the consumer profile. They never import the build plane's inventory,
selection, provenance builder or source cache, and never fetch.
"""
