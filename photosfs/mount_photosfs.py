#!/usr/bin/env python
"""
Command-line tool to mount Apple Photos libraries as a FUSE filesystem.

Usage:
    mount_photosfs.py /path/to/Photos\ Library.photoslibrary [mountpoint]

If mountpoint is not specified or is '-', a mount point will be created
at the system's default location (/Volumes on macOS, /media on Linux).

If mountpoint begins with a dash (e.g., -./mount), a mount point will be
created within the specified directory using the library name.
"""

import sys
import os

from photos_fuse import mount_photosfs, HAS_OSXPHOTOS


def main():
    if len(sys.argv) < 2:
        print('usage: %s photos_library [mountpoint]' % sys.argv[0])
        print("""
            Mount an Apple Photos library as a read-only FUSE filesystem.

            Arguments:
                photos_library    Path to the .photoslibrary file
                mountpoint        Optional mount point

            If mountpoint is not specified or is '-', a mount point will be
            created at the system default location (/Volumes on macOS, 
            /media on Linux) using the library name.

            If mountpoint begins with a dash (e.g., -./mount), a mount point
            will be created within the specified directory using the library name.

            Example:
                mount_photosfs.py ~/Pictures/Photos\ Library.photoslibrary
                mount_photosfs.py ~/Pictures/Photos\ Library.photoslibrary /mnt/photos
                mount_photosfs.py ~/Pictures/Photos\ Library.photoslibrary -.
        """)
        sys.exit(1)
    
    if not HAS_OSXPHOTOS:
        print("Error: osxphotos library is required.")
        print("Install with: pip install osxphotos")
        sys.exit(1)
    
    library_path = sys.argv[1]
    
    if len(sys.argv) > 2:
        mount = sys.argv[2]
    else:
        mount = None
    
    mount_photosfs(library_path, mount, foreground=True, verbose=True)


if __name__ == '__main__':
    main()
