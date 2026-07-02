#!/usr/bin/env python
"""
FUSE filesystem implementation for Apple Photos libraries.

Uses osxphotos to read Photos.app library data and presents it as a
read-only filesystem with the following structure:

/Photos Library Name/
├── Albums/
│   ├── Album 1/
│   │   ├── photo1.jpg
│   │   └── photo2.jpg
│   └── Album 2/
│       └── photo3.jpg
├── Folders/
│   └── Folder Name/
│       └── Album inside folder/
└── Media/
    └── All original media files

"""

import os
import time
import datetime
import atexit
import shutil
import sys
import traceback
from errno import ENOENT
from stat import S_IFDIR, S_IFREG
from threading import Lock

from fuse import FuseOSError, Operations, LoggingMixIn, fuse_get_context, FUSE

# Import osxphotos for Photos library access
try:
    import osxphotos
    HAS_OSXPHOTOS = True
except ImportError:
    HAS_OSXPHOTOS = False


class PhotosFUSEFS(LoggingMixIn, Operations):
    """
    FUSE filesystem that exposes an Apple Photos library as a directory tree.
    """
    
    _CHMOD_DIR = 0o755
    _CHMOD_FILE = 0o444
    
    chmod = os.chmod
    chown = os.chown
    readlink = os.readlink
    
    # Disable unused operations
    getxattr = None
    listxattr = None
    opendir = None
    releasedir = None
    
    def __init__(self, photos_library, verbose=False):
        """
        Initialize the FUSE filesystem with a Photos library.
        
        :param photos_library: osxphotos.PhotosLibrary instance
        :param verbose: Enable verbose logging
        """
        self._library = photos_library
        self.rwlock = Lock()
        self.verbose = verbose
        self._file_handles = {}
        self._next_fh = 1
    
    @property
    def library(self):
        """Returns the osxphotos PhotosLibrary instance."""
        return self._library
    
    def add_uid_gid_pid(self, st_dict):
        """Add current FUSE context uid, gid, pid to stat dict."""
        uid, gid, pid = fuse_get_context()
        st_dict['st_uid'] = uid
        st_dict['st_gid'] = gid
        st_dict['st_pid'] = pid
        return st_dict
    
    def getattr(self, path, fh=None):
        """
        Get file/directory attributes.
        
        Path structure:
        / -> root of library
        /Albums -> all top-level albums
        /Albums/AlbumName -> album contents
        /Albums/AlbumName/photo.jpg -> individual photo
        /Folders -> album folders
        /Folders/FolderName/AlbumName -> album inside folder
        /Media -> all media files (flat)
        """
        if self.verbose:
            print(f"getattr: {path}")
        
        if path == '/':
            # Root directory
            st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), st_nlink=2)
            return self.add_uid_gid_pid(st)
        
        # Parse the path
        parts = [p for p in path.split('/') if p]
        
        if not parts:
            raise FuseOSError(ENOENT)
        
        # Handle top-level directories
        if len(parts) == 1:
            top_level = parts[0]
            if top_level in ['Albums', 'Folders', 'Media']:
                st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), st_nlink=2)
                return self.add_uid_gid_pid(st)
            else:
                # Check if it's a top-level album (not in any folder)
                album = self._find_album_by_name(top_level)
                if album:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(list(album.photos)))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
        
        # Handle nested paths
        if parts[0] == 'Albums':
            # /Albums/AlbumName or /Albums/AlbumName/photo.jpg
            if len(parts) == 2:
                # This is an album
                album = self._find_album_by_name(parts[1])
                if album:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(list(album.photos)))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # This is a photo inside an album
                album_name, photo_name = parts[1], parts[2]
                album = self._find_album_by_name(album_name)
                if album:
                    photo = self._find_photo_in_album_by_filename(album, photo_name)
                    if photo:
                        st = os.lstat(photo.path)
                        st_dict = dict((key, getattr(st, key)) 
                                      for key in ('st_atime', 'st_ctime', 'st_mode', 
                                                  'st_mtime', 'st_nlink', 'st_size'))
                        st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                        return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        elif parts[0] == 'Folders':
            # /Folders/FolderName/AlbumName or /Folders/FolderName/AlbumName/photo.jpg
            if len(parts) == 2:
                # This is a folder
                folder_name = parts[1]
                folder = self._find_folder_by_name(folder_name)
                if folder:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(folder.albums))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # This is an album inside a folder
                folder_name, album_name = parts[1], parts[2]
                folder = self._find_folder_by_name(folder_name)
                if folder:
                    album = self._find_album_in_folder(folder, album_name)
                    if album:
                        st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                                  st_nlink=2 + len(list(album.photos)))
                        return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 4:
                # This is a photo inside an album inside a folder
                folder_name, album_name, photo_name = parts[1], parts[2], parts[3]
                folder = self._find_folder_by_name(folder_name)
                if folder:
                    album = self._find_album_in_folder(folder, album_name)
                    if album:
                        photo = self._find_photo_in_album_by_filename(album, photo_name)
                        if photo:
                            st = os.lstat(photo.path)
                            st_dict = dict((key, getattr(st, key)) 
                                          for key in ('st_atime', 'st_ctime', 'st_mode', 
                                                      'st_mtime', 'st_nlink', 'st_size'))
                            st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                            return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        elif parts[0] == 'Media':
            # /Media/photo.jpg - flat list of all media
            if len(parts) == 2:
                photo_name = parts[1]
                photo = self._find_photo_by_filename(photo_name)
                if photo:
                    st = os.lstat(photo.path)
                    st_dict = dict((key, getattr(st, key)) 
                                  for key in ('st_atime', 'st_ctime', 'st_mode', 
                                              'st_mtime', 'st_nlink', 'st_size'))
                    st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                    return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        raise FuseOSError(ENOENT)
    
    def readdir(self, path, fh=None):
        """List directory contents."""
        if self.verbose:
            print(f"readdir: {path}")
        
        entries = ['.', '..']
        
        if path == '/':
            entries.extend(['Albums', 'Folders', 'Media'])
            # Also add top-level albums (not in folders)
            for album in self._library.albums:
                if album.folder is None:
                    entries.append(album.name)
        
        elif path == '/Albums':
            for album in self._library.albums:
                if album.folder is None:
                    entries.append(album.name)
        
        elif path == '/Folders':
            for folder in self._library.folders:
                entries.append(folder.name)
        
        elif path == '/Media':
            for photo in self._library.photos:
                entries.append(os.path.basename(photo.path))
        
        elif path.startswith('/Albums/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /Albums/AlbumName
                album_name = parts[1]
                album = self._find_album_by_name(album_name)
                if album:
                    for photo in album.photos:
                        entries.append(os.path.basename(photo.path))
        
        elif path.startswith('/Folders/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /Folders/FolderName - list albums in this folder
                folder_name = parts[1]
                folder = self._find_folder_by_name(folder_name)
                if folder:
                    for album in folder.albums:
                        entries.append(album.name)
            elif len(parts) == 3:
                # /Folders/FolderName/AlbumName - list photos in this album
                folder_name, album_name = parts[1], parts[2]
                folder = self._find_folder_by_name(folder_name)
                if folder:
                    album = self._find_album_in_folder(folder, album_name)
                    if album:
                        for photo in album.photos:
                            entries.append(os.path.basename(photo.path))
        
        return entries
    
    def open(self, path, flags=0, mode=0):
        """Open a file for reading."""
        if self.verbose:
            print(f"open: {path} (flags={flags}, mode={mode})")
        
        # Find the photo
        parts = [p for p in path.split('/') if p]
        
        photo = None
        if len(parts) >= 2:
            if parts[0] == 'Albums' and len(parts) == 3:
                # /Albums/AlbumName/photo.jpg
                album = self._find_album_by_name(parts[1])
                if album:
                    photo = self._find_photo_in_album_by_filename(album, parts[2])
            elif parts[0] == 'Folders' and len(parts) == 4:
                # /Folders/FolderName/AlbumName/photo.jpg
                folder = self._find_folder_by_name(parts[1])
                if folder:
                    album = self._find_album_in_folder(folder, parts[2])
                    if album:
                        photo = self._find_photo_in_album_by_filename(album, parts[3])
            elif parts[0] == 'Media' and len(parts) == 2:
                # /Media/photo.jpg
                photo = self._find_photo_by_filename(parts[1])
        
        if photo and os.path.exists(photo.path):
            fh = self._next_fh
            self._next_fh += 1
            fd = os.open(photo.path, flags, mode)
            self._file_handles[fh] = (photo.path, fd)
            return fh
        
        raise FuseOSError(ENOENT)
    
    def read(self, path, size, offset, fh):
        """Read data from an open file."""
        if self.verbose:
            print(f"read: {path} (size={size}, offset={offset}, fh={fh})")
        
        if fh in self._file_handles:
            photo_path, fd = self._file_handles[fh]
            with self.rwlock:
                os.lseek(fd, offset, 0)
                return os.read(fd, size)
        
        raise FuseOSError(ENOENT)
    
    def release(self, path, fh):
        """Release an open file handle."""
        if self.verbose:
            print(f"release: {path} (fh={fh})")
        
        if fh in self._file_handles:
            photo_path, fd = self._file_handles[fh]
            os.close(fd)
            del self._file_handles[fh]
        
        return 0
    
    def flush(self, path, fh):
        """Flush file data (read-only, so this is a no-op)."""
        if self.verbose:
            print(f"flush: {path}")
        return 0
    
    def fsync(self, path, datasync, fh):
        """Sync file data (read-only, so this is a no-op)."""
        if self.verbose:
            print(f"fsync: {path}")
        return 0
    
    # Helper methods for finding library objects
    
    def _find_album_by_name(self, name):
        """Find an album by name (top-level, not in a folder)."""
        for album in self._library.albums:
            if album.name == name and album.folder is None:
                return album
        return None
    
    def _find_folder_by_name(self, name):
        """Find a folder by name."""
        for folder in self._library.folders:
            if folder.name == name:
                return folder
        return None
    
    def _find_album_in_folder(self, folder, name):
        """Find an album within a specific folder."""
        for album in folder.albums:
            if album.name == name:
                return album
        return None
    
    def _find_photo_in_album_by_filename(self, album, filename):
        """Find a photo in an album by its filename."""
        for photo in album.photos:
            if os.path.basename(photo.path) == filename:
                return photo
        return None
    
    def _find_photo_by_filename(self, filename):
        """Find a photo in the entire library by filename."""
        for photo in self._library.photos:
            if os.path.basename(photo.path) == filename:
                return photo
        return None


def mount_photosfs(library_path, mount=None, foreground=True, verbose=False):
    """
    Mount a Photos library as a FUSE filesystem.
    
    :param library_path: Path to the Photos library (.photoslibrary)
    :param mount: Mount point (None for auto-create based on library name)
    :param foreground: Run in foreground
    :param verbose: Enable verbose logging
    :return: FUSE instance
    """
    if not HAS_OSXPHOTOS:
        print("Error: osxphotos library is required. Install with: pip install osxphotos")
        sys.exit(1)
    
    # Load the Photos library
    try:
        photos_library = osxphotos.PhotosLibrary(library_path)
    except Exception as e:
        print(f"Error loading Photos library: {e}")
        sys.exit(1)
    
    def remove_mount(mount_path):
        """Clean up mount point on exit."""
        try:
            shutil.rmtree(mount_path)
        except OSError:
            traceback.print_exc(file=sys.stderr)
    
    # Determine mount point
    from platform import system
    
    this_system = system()
    if this_system == 'Darwin':
        preferred_mount = '/Volumes'
    elif this_system == 'Linux':
        preferred_mount = '/media'
    else:
        preferred_mount = '/media'
    
    lib_name = os.path.splitext(os.path.basename(library_path))[0]
    
    if mount is None or mount == '-':
        mount = os.path.join(preferred_mount, lib_name)
        try:
            os.makedirs(mount)
        except OSError:
            if not os.path.isdir(mount):
                raise
        atexit.register(remove_mount, os.path.abspath(mount))
    elif mount.startswith('-'):
        mount = os.path.join(mount[1:], lib_name)
        try:
            os.makedirs(mount)
        except OSError:
            if not os.path.isdir(mount):
                raise
        atexit.register(remove_mount, os.path.abspath(mount))
    
    if verbose:
        print(f"Photos Library: {library_path}")
        print(f"Mount point: {mount}")
    
    # Create and mount the FUSE filesystem
    fuse = FUSE(
        PhotosFUSEFS(photos_library, verbose=verbose),
        mount,
        nothreads=False,
        foreground=foreground,
        ro=True,
        allow_other=True,
        fsname=lib_name,
        volname=lib_name
    )
    
    return fuse
