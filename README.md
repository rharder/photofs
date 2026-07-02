# photosfs: Apple Photos Library FUSE Filesystem

Mount your Apple Photos library as a read-only filesystem using FUSE. This allows you to browse and access your Photos library content through standard filesystem operations.

## Features

- Mount Photos libraries as a navigable directory structure
- Access photos organized by Albums and Folders
- Flat Media view for all original files
- Read-only to protect your library
- Cross-platform (macOS, Linux, FreeBSD)

## Installation

```bash
# Clone the repository
git clone https://github.com/rharder/photosfs.git
cd photosfs

# Install in development mode
pip install -e .

# Or install from PyPI (when published)
pip install photosfs
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
# Basic mount with auto-created mount point
mount_photosfs ~/Pictures/Photos\ Library.photoslibrary

# Mount to a specific location
mount_photosfs ~/Pictures/Photos\ Library.photoslibrary /mnt/photos

# Mount in current directory
mount_photosfs ~/Pictures/Photos\ Library.photoslibrary -.

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
└── Media/               # All media files (flat)
    ├── IMG_0001.JPG
    ├── IMG_0002.JPG
    └── ...
```

## Project Structure

```
photosfs/
├── photosfs/
│   ├── __init__.py
│   ├── photos_fuse.py    # FUSE filesystem implementation
│   └── mount_photosfs.py # CLI entry point
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

| Feature | pyphotofs | photosfs |
|---------|-----------|----------|
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
