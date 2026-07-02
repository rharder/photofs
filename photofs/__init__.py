"""
photofs: Mount Apple Photos libraries as a FUSE filesystem.

This package provides a read-only FUSE filesystem for accessing Apple Photos
libraries on macOS, exposing albums, folders, and photos as a navigable directory structure.

Uses osxphotos library to parse Photos.app SQLite databases.
"""

__author__ = "Robert Harder"
__email__ = "rob@iharder.net"
__version__ = "0.1"
__status__ = "Development"
