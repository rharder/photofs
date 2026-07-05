#!/usr/bin/env python
"""
Command-line tool to mount Apple Photos libraries as a FUSE filesystem.

Usage:
    mount_photos [options] [photos_library] [mountpoint]

If photos_library is not specified, the default/active Photos library will be used.
If mountpoint is not specified or is '-', a mount point will be created
at the system's default location (/Volumes on macOS, /media on Linux).

If mountpoint begins with a dash (e.g., -./mount), a mount point will be
created within the specified directory using the library name.
"""

import sys
import os
import argparse

from photofs.photofs_fuse import mount_photos, HAS_OSXPHOTOS


def find_default_library():
    """Find the default Photos library path."""
    # Check default location first
    default_path = os.path.expanduser('~/Pictures/Photos Library.photoslibrary')
    if os.path.exists(default_path):
        return default_path
    
    # Check for .photoslibrary files in Pictures directory
    pictures_dir = os.path.expanduser('~/Pictures')
    if os.path.isdir(pictures_dir):
        for item in os.listdir(pictures_dir):
            if item.endswith('.photoslibrary'):
                return os.path.join(pictures_dir, item)
    
    # Try using osxphotos to find the last opened library
    try:
        import osxphotos
        db = osxphotos.PhotosDB()
        return db.dbfile
    except Exception:
        pass
    
    return None


def list_available_libraries():
    """List all available Photos libraries."""
    libraries = []
    
    # Check Pictures directory
    pictures_dir = os.path.expanduser('~/Pictures')
    if os.path.isdir(pictures_dir):
        for item in sorted(os.listdir(pictures_dir)):
            if item.endswith('.photoslibrary'):
                libraries.append(os.path.join(pictures_dir, item))
    
    # Check Documents directory for any .photoslibrary files
    docs_dir = os.path.expanduser('~/Documents')
    if os.path.isdir(docs_dir):
        for item in sorted(os.listdir(docs_dir)):
            if item.endswith('.photoslibrary'):
                full_path = os.path.join(docs_dir, item)
                if full_path not in libraries:
                    libraries.append(full_path)
    
    # Check one level deeper in Pictures (for subdirectories)
    if os.path.isdir(pictures_dir):
        for item in sorted(os.listdir(pictures_dir)):
            item_path = os.path.join(pictures_dir, item)
            if os.path.isdir(item_path):
                for subitem in sorted(os.listdir(item_path)):
                    if subitem.endswith('.photoslibrary'):
                        full_path = os.path.join(item_path, subitem)
                        if full_path not in libraries:
                            libraries.append(full_path)
    
    return sorted(libraries)


def main():
    parser = argparse.ArgumentParser(
        description='Mount an Apple Photos library as a read-only FUSE filesystem',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mount_photos                           # Mount default library
  mount_photos --default                # Mount default library
  mount_photos ~/Pictures/MyLibrary.photoslibrary
  mount_photos ~/Pictures/MyLibrary.photoslibrary /mnt/photos
  mount_photos --list                   # List available libraries
  mount_photos -v ~/Pictures/MyLibrary.photoslibrary  # Verbose
        """
    )
    
    parser.add_argument(
        'library',
        nargs='?',
        default=None,
        help='Path to the .photoslibrary file (defaults to active library)'
    )
    
    parser.add_argument(
        'mountpoint',
        nargs='?',
        default=None,
        help='Mount point directory (defaults to /Volumes/LibraryName on macOS, /media/LibraryName on Linux)'
    )
    
    parser.add_argument(
        '-d', '--default',
        action='store_true',
        help='Use the default/active Photos library'
    )
    
    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help='List available Photos libraries and exit'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Disable verbose logging'
    )
    
    parser.add_argument(
        '-f', '--foreground',
        action='store_true',
        default=True,
        help='Run in foreground (default)'
    )
    
    parser.add_argument(
        '-b', '--background',
        action='store_false',
        dest='foreground',
        help='Run in background'
    )
    
    args = parser.parse_args()
    
    if not HAS_OSXPHOTOS:
        print("Error: osxphotos library is required.")
        print("Install with: pip install osxphotos")
        sys.exit(1)
    
    # Handle --list (takes precedence over other arguments)
    if args.list:
        libraries = list_available_libraries()
        if libraries:
            print("Available Photos libraries:")
            for lib in libraries:
                print(f"  {lib}")
            
            # Mark default
            default_lib = find_default_library()
            if default_lib:
                print(f"\nDefault library: {default_lib}")
        else:
            print("No Photos libraries found.")
        sys.exit(0)
    
    # Determine library path
    if args.default or args.library is None:
        library_path = find_default_library()
        if library_path is None:
            libraries = list_available_libraries()
            if libraries:
                print(f"No default library found. Available libraries:")
                for lib in libraries:
                    print(f"  {lib}")
                print("\nUse --list to see all available libraries, or specify a path.")
                sys.exit(1)
            else:
                print("Error: No Photos libraries found.")
                sys.exit(1)
    else:
        library_path = args.library
    
    # Validate library path
    if not os.path.exists(library_path):
        print(f"Error: Photos library not found: {library_path}")
        sys.exit(1)
    
    if not library_path.endswith('.photoslibrary'):
        print(f"Error: Path does not appear to be a Photos library: {library_path}")
        sys.exit(1)
    
    # Determine mount point
    mount = args.mountpoint
    
    # Set verbose flag
    verbose = args.verbose and not args.quiet
    
    # Print loading message
    if verbose:
        print(f"Loading Photos library: {library_path}")
        print("This may take a while for large libraries (database size matters, not photo count)...")
    
    mount_photos(library_path, mount, foreground=args.foreground, verbose=verbose)


if __name__ == '__main__':
    main()
