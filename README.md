# photofs: Apple Photos Library FUSE Filesystem

Mount your Apple Photos library as a read-only filesystem using FUSE. This allows you to browse and access your Photos library content through standard filesystem operations.

## Features

- Mount Photos libraries as a navigable directory structure
- Access photos organized by Albums and Folders
- Flat Media view for all original files
- **Browse by Faces** - Photos grouped by recognized people
- **Browse by Locations** - Photos grouped by geographic location
- **Browse by Keywords** - Photos grouped by tags/keywords
- **Browse by Date** - Photos grouped by year and month
- **Absolute read-only protection** - All write operations are blocked at the filesystem level
- **Multiple library support** - Auto-detect and mount any Photos library
- Caching for better performance with large libraries
- Cross-platform (macOS, Linux, FreeBSD)

## Installation

```bash
# Clone the repository
git clone https://github.com/rharder/photofs.git
cd photofs

# Install in development mode
pip install -e .

# Or install from PyPI (when published)
pip install photofs
```

## Requirements

- Python 3.8+
- FUSE implementation for your OS:
  - macOS: [osxfuse](https://osxfuse.github.io/)
  - Linux: fuse (usually pre-installed)
  - FreeBSD: Built-in or fusefs-kmod
- Python packages (installed automatically):
  - `fusepy` - FUSE bindings for Python
  - `osxphotos` - Apple Photos library access

## Usage

```bash
# Mount the default/active Photos library
mount_photos

# Mount a specific library
mount_photos ~/Pictures/Photos\ Library.photoslibrary

# Mount to a specific location
mount_photos ~/Pictures/Photos\ Library.photoslibrary /mnt/photos

# Mount in current directory
mount_photos ~/Pictures/Photos\ Library.photoslibrary -.

# List all available Photos libraries
mount_photos --list

# Verbose output
mount_photos -v ~/Pictures/Photos\ Library.photoslibrary

# Run in background
mount_photos -b ~/Pictures/Photos\ Library.photoslibrary /mnt/photos

# Unmount (standard FUSE command)
fusermount -u /mnt/photos  # Linux
umount /mnt/photos          # macOS
```

## Filesystem Structure

When mounted, your Photos library will appear as:

```
/Photos Library Name/
├── Albums/              # All top-level albums
│   ├── Vacation 2024/
│   │   ├── IMG_0001.JPG
│   │   ├── IMG_0002.JPG
│   │   └── ...
│   ├── Family/
│   └── ...
├── Folders/             # Album folders
│   └── Trips/
│       └── Europe 2023/
│           ├── IMG_0100.JPG
│           └── ...
├── Media/               # All media files (flat)
│   ├── IMG_0001.JPG
│   ├── IMG_0002.JPG
│   └── ...
├── Faces/               # Photos grouped by recognized people
│   ├── John Doe/
│   │   ├── IMG_0001.JPG
│   │   └── ...
│   └── Jane Smith/
│       └── ...
├── Locations/           # Photos grouped by geographic location
│   ├── Paris, France/
│   │   ├── IMG_0100.JPG
│   │   └── ...
│   └── New York, NY/
│       └── ...
├── Keywords/            # Photos grouped by tags/keywords
│   ├── Beach/
│   │   ├── IMG_0200.JPG
│   │   └── ...
│   └── Sunset/
│       └── ...
└── By Date/             # Photos grouped by date (year/month)
    ├── 2024/
    │   ├── January/
    │   │   ├── IMG_0300.JPG
    │   │   └── ...
    │   └── February/
    │       └── ...
    └── 2023/
        └── ...
```

## Command Line Options

```bash
mount_photos [OPTIONS] [LIBRARY_PATH] [MOUNTPOINT]

Options:
  -d, --default    Use the default/active Photos library
  -l, --list       List available Photos libraries and exit
  -v, --verbose    Enable verbose logging
  -q, --quiet      Disable verbose logging
  -f, --foreground Run in foreground (default)
  -b, --background  Run in background

Arguments:
  LIBRARY_PATH     Path to the .photoslibrary file (defaults to active library)
  MOUNTPOINT       Mount point directory (defaults to /Volumes/LibraryName on macOS)
```

## Project Structure

```
photofs/
├── photofs/
│   ├── __init__.py
│   ├── photofs_fuse.py    # FUSE filesystem implementation
│   └── mount_photos.py    # CLI entry point
├── setup.py
├── README.md
└── requirements.txt
```

## Development

```bash
# Install development dependencies
pip install -e .[dev]

# Run tests
python -m pytest
```

## Comparison with pyphotofs

This project is the successor to [pyphotofs](https://github.com/rharder/pyphotofs), which supported iPhoto libraries. The key differences:

| Feature | pyphotofs | photofs |
|---------|-----------|---------|
| Library format | iPhoto (AlbumData.xml) | Photos.app (SQLite) |
| Backend library | plistlib | osxphotos |
| Metadata access | Basic | Full (faces, persons, keywords, etc.) |
| Python version | 2.7/3.x | 3.8+ |

## License

This project is released into the **Public Domain**. See LICENSE for details.

## Credits

Created by Robert Harder (rob@iharder.net).

Built on top of [osxphotos](https://github.com/RhetTbull/osxphotos) by Rhet Turnbull.

## TODO

- [ ] Add support for smart albums
- [ ] Expose EXIF metadata as file attributes (xattr)
- [ ] Support for video files
- [ ] Caching for better performance with large libraries
- [ ] macOS native mount command integration (`mount -t photosfs`)
