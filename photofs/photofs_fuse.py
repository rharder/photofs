#!/usr/bin/env python
"""
FUSE filesystem implementation for Apple Photos libraries.

Uses osxphotos to read Photos.app library data and presents it as a
read-only filesystem with the following structure:

/Photos Library Name/
├── Albums/              # All top-level albums
│   ├── Album 1/
│   │   ├── photo1.jpg
│   │   └── photo2.jpg
│   └── Album 2/
│       └── photo3.jpg
├── Folders/             # Album folders
│   └── Folder Name/
│       └── Album inside folder/
├── Media/               # All media files (flat)
├── Faces/               # Photos grouped by recognized faces
│   ├── John Doe/
│   │   ├── photo1.jpg
│   │   └── ...
│   └── Jane Smith/
├── Locations/           # Photos grouped by location
│   ├── Paris, France/
│   │   └── photo1.jpg
│   └── New York, NY/
├── Keywords/            # Photos grouped by keywords/tags
│   ├── Beach/
│   │   └── photo1.jpg
│   └── Sunset/
└── By Date/             # Photos grouped by date (year/month)
    ├── 2024/
    │   ├── 01-January/
    │   │   └── photo1.jpg
    │   └── 02-February/
    └── 2023/
        └── ...

"""

import os
import time
import datetime
import atexit
import shutil
import sys
import traceback
import re
from errno import ENOENT, EPERM, EACCES
from stat import S_IFDIR, S_IFREG
from threading import Lock
from collections import defaultdict

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
    
    _CHMOD_DIR = 0o555  # Read-only + execute for directories
    _CHMOD_FILE = 0o444  # Read-only for files
    
    chmod = os.chmod
    chown = os.chown
    readlink = os.readlink
    
    # Disable unused operations
    getxattr = None
    listxattr = None
    opendir = None
    releasedir = None
    
    # Disable all write operations to ensure absolute read-only
    # These will raise EPERM if called
    def _read_only_error(self, *args, **kwargs):
        raise FuseOSError(EPERM)
    
    write = _read_only_error
    truncate = _read_only_error
    unlink = _read_only_error
    rmdir = _read_only_error
    mkdir = _read_only_error
    symlink = _read_only_error
    rename = _read_only_error
    link = _read_only_error
    chmod = _read_only_error
    chown = _read_only_error
    utimens = _read_only_error
    create = _read_only_error
    mknod = _read_only_error
    setxattr = _read_only_error
    removexattr = _read_only_error
    
    def __init__(self, photos_db, verbose=False):
        """
        Initialize the FUSE filesystem with a Photos library.
        
        :param photos_db: osxphotos.PhotosDB instance
        :param verbose: Enable verbose logging
        """
        self._library = photos_db
        self.rwlock = Lock()
        self.verbose = verbose
        self._file_handles = {}
        self._next_fh = 1
        
        # Caches for better performance
        self._cache = {
            'faces': None,      # Dict: face_name -> list of photos
            'locations': None,  # Dict: location_name -> list of photos
            'keywords': None,   # Dict: keyword -> list of photos
            'by_date': None,    # Dict: (year, month) -> list of photos
        }
        
        # Pre-compute caches
        self._build_caches()
    
    @property
    def library(self):
        """Returns the osxphotos PhotosDB instance."""
        return self._library
    
    def _build_caches(self):
        """Pre-compute caches for faces, locations, keywords, and dates."""
        if self.verbose:
            print("Building caches for faces, locations, keywords, and dates...")
        
        faces_cache = defaultdict(list)
        locations_cache = defaultdict(list)
        keywords_cache = defaultdict(list)
        by_date_cache = defaultdict(list)
        
        for photo in self._library.photos:
            # Cache by faces
            if hasattr(photo, 'person_info') and photo.person_info:
                for person in photo.person_info:
                    name = self._get_person_name(person)
                    if name:
                        faces_cache[name].append(photo)
            elif hasattr(photo, 'persons') and photo.persons:
                for person in photo.persons:
                    faces_cache[person].append(photo)
            
            # Cache by location
            location = self._get_photo_location(photo)
            if location:
                locations_cache[location].append(photo)
            
            # Cache by keywords
            if hasattr(photo, 'keywords') and photo.keywords:
                for keyword in photo.keywords:
                    keywords_cache[keyword].append(photo)
            
            # Cache by date
            date_info = self._get_photo_date_info(photo)
            if date_info:
                year, month, month_name = date_info
                # Store by year
                by_date_cache[f"{year}"].append(photo)
                # Store by year/month
                by_date_cache[f"{year}/{month_name}"].append(photo)
        
        self._cache['faces'] = dict(faces_cache)
        self._cache['locations'] = dict(locations_cache)
        self._cache['keywords'] = dict(keywords_cache)
        self._cache['by_date'] = dict(by_date_cache)
        
        if self.verbose:
            print(f"  Faces: {len(faces_cache)} people")
            print(f"  Locations: {len(locations_cache)} places")
            print(f"  Keywords: {len(keywords_cache)} tags")
            print(f"  By Date: {len(by_date_cache)} date groups")
    
    def _get_person_name(self, person):
        """Extract a clean name from person info."""
        if isinstance(person, str):
            return person
        elif isinstance(person, dict):
            return person.get('name') or person.get('person')
        elif hasattr(person, 'name'):
            return person.name
        return None
    
    def _get_photo_location(self, photo):
        """Extract location information from a photo."""
        # Try different location attributes
        if hasattr(photo, 'place') and photo.place:
            return photo.place
        if hasattr(photo, 'location') and photo.location:
            return photo.location
        if hasattr(photo, 'city') and photo.city:
            parts = [photo.city]
            if hasattr(photo, 'state') and photo.state:
                parts.append(photo.state)
            if hasattr(photo, 'country') and photo.country:
                parts.append(photo.country)
            return ', '.join(parts) if parts else None
        return None
    
    def _get_photo_date_info(self, photo):
        """Extract date information from a photo."""
        if hasattr(photo, 'date') and photo.date:
            try:
                dt = photo.date
                if isinstance(dt, str):
                    dt = datetime.datetime.fromisoformat(dt)
                year = dt.year
                month = dt.month
                month_name = datetime.date(1900, month, 1).strftime('%B')
                return (year, month, month_name)
            except (ValueError, TypeError):
                pass
        return None
    
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
        /Faces -> photos grouped by recognized faces
        /Faces/PersonName -> photos of that person
        /Faces/PersonName/photo.jpg -> individual photo
        /Locations -> photos grouped by location
        /Locations/PlaceName -> photos from that location
        /Locations/PlaceName/photo.jpg -> individual photo
        /Keywords -> photos grouped by keywords
        /Keywords/Keyword -> photos with that keyword
        /Keywords/Keyword/photo.jpg -> individual photo
        /By Date -> photos grouped by date
        /By Date/Year -> photos from that year
        /By Date/Year/Month -> photos from that month
        /By Date/Year/Month/photo.jpg -> individual photo
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
            if top_level in ['Albums', 'Folders', 'Media', 'Faces', 'Locations', 'Keywords', 'By Date']:
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
        
        # Handle Faces directory
        elif parts[0] == 'Faces':
            if len(parts) == 2:
                # /Faces/PersonName - directory for a person
                person_name = parts[1]
                photos = self._get_photos_by_face(person_name)
                if photos is not None:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(photos))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # /Faces/PersonName/photo.jpg - individual photo
                person_name, photo_name = parts[1], parts[2]
                photos = self._get_photos_by_face(person_name)
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, photo_name)
                    if photo:
                        st = os.lstat(photo.path)
                        st_dict = dict((key, getattr(st, key)) 
                                      for key in ('st_atime', 'st_ctime', 'st_mode', 
                                                  'st_mtime', 'st_nlink', 'st_size'))
                        st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                        return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        # Handle Locations directory
        elif parts[0] == 'Locations':
            if len(parts) == 2:
                # /Locations/PlaceName - directory for a location
                location_name = parts[1]
                photos = self._get_photos_by_location(location_name)
                if photos is not None:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(photos))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # /Locations/PlaceName/photo.jpg - individual photo
                location_name, photo_name = parts[1], parts[2]
                photos = self._get_photos_by_location(location_name)
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, photo_name)
                    if photo:
                        st = os.lstat(photo.path)
                        st_dict = dict((key, getattr(st, key)) 
                                      for key in ('st_atime', 'st_ctime', 'st_mode', 
                                                  'st_mtime', 'st_nlink', 'st_size'))
                        st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                        return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        # Handle Keywords directory
        elif parts[0] == 'Keywords':
            if len(parts) == 2:
                # /Keywords/Keyword - directory for a keyword
                keyword = parts[1]
                photos = self._get_photos_by_keyword(keyword)
                if photos is not None:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(photos))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # /Keywords/Keyword/photo.jpg - individual photo
                keyword, photo_name = parts[1], parts[2]
                photos = self._get_photos_by_keyword(keyword)
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, photo_name)
                    if photo:
                        st = os.lstat(photo.path)
                        st_dict = dict((key, getattr(st, key)) 
                                      for key in ('st_atime', 'st_ctime', 'st_mode', 
                                                  'st_mtime', 'st_nlink', 'st_size'))
                        st_dict['st_mode'] = S_IFREG | self._CHMOD_FILE
                        return self.add_uid_gid_pid(st_dict)
                raise FuseOSError(ENOENT)
        
        # Handle By Date directory
        elif parts[0] == 'By Date':
            if len(parts) == 2:
                # /By Date/Year - directory for a year
                year = parts[1]
                # Check if it's a year directory
                if year.isdigit():
                    photos = self._get_photos_by_date_year(year)
                    if photos is not None:
                        # Count subdirectories (months) and photos
                        months = self._get_months_for_year(year)
                        st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                                  st_nlink=2 + len(months) + len(photos))
                        return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 3:
                # /By Date/Year/Month - directory for a month
                year, month_name = parts[1], parts[2]
                photos = self._get_photos_by_date_month(year, month_name)
                if photos is not None:
                    st = dict(st_mode=(S_IFDIR | self._CHMOD_DIR), 
                              st_nlink=2 + len(photos))
                    return self.add_uid_gid_pid(st)
                raise FuseOSError(ENOENT)
            elif len(parts) == 4:
                # /By Date/Year/Month/photo.jpg - individual photo
                year, month_name, photo_name = parts[1], parts[2], parts[3]
                photos = self._get_photos_by_date_month(year, month_name)
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, photo_name)
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
        
        elif path == '/Faces':
            # List all recognized faces
            if self._cache['faces']:
                for face_name in sorted(self._cache['faces'].keys()):
                    entries.append(face_name)
        
        elif path.startswith('/Faces/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /Faces/PersonName - list photos for this person
                face_name = parts[1]
                photos = self._get_photos_by_face(face_name)
                if photos:
                    for photo in photos:
                        entries.append(os.path.basename(photo.path))
        
        elif path == '/Locations':
            # List all locations
            if self._cache['locations']:
                for location in sorted(self._cache['locations'].keys()):
                    entries.append(location)
        
        elif path.startswith('/Locations/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /Locations/PlaceName - list photos for this location
                location = parts[1]
                photos = self._get_photos_by_location(location)
                if photos:
                    for photo in photos:
                        entries.append(os.path.basename(photo.path))
        
        elif path == '/Keywords':
            # List all keywords
            if self._cache['keywords']:
                for keyword in sorted(self._cache['keywords'].keys()):
                    entries.append(keyword)
        
        elif path.startswith('/Keywords/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /Keywords/Keyword - list photos with this keyword
                keyword = parts[1]
                photos = self._get_photos_by_keyword(keyword)
                if photos:
                    for photo in photos:
                        entries.append(os.path.basename(photo.path))
        
        elif path == '/By Date':
            # List all years
            if self._cache['by_date']:
                years = set()
                for key in self._cache['by_date'].keys():
                    if '/' in key:
                        year = key.split('/')[0]
                        years.add(year)
                    else:
                        years.add(key)
                for year in sorted(years):
                    entries.append(year)
        
        elif path.startswith('/By Date/'):
            parts = [p for p in path.split('/') if p]
            if len(parts) == 2:
                # /By Date/Year - list months
                year = parts[1]
                if year.isdigit():
                    months = self._get_months_for_year(year)
                    for month in sorted(months):
                        entries.append(month)
            elif len(parts) == 3:
                # /By Date/Year/Month - list photos for this month
                year, month_name = parts[1], parts[2]
                photos = self._get_photos_by_date_month(year, month_name)
                if photos:
                    for photo in photos:
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
        
        # Only allow read operations
        if flags & os.O_WRONLY or flags & os.O_RDWR or flags & os.O_APPEND:
            raise FuseOSError(EPERM)
        
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
            elif parts[0] == 'Faces' and len(parts) == 3:
                # /Faces/PersonName/photo.jpg
                photos = self._get_photos_by_face(parts[1])
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, parts[2])
            elif parts[0] == 'Locations' and len(parts) == 3:
                # /Locations/PlaceName/photo.jpg
                photos = self._get_photos_by_location(parts[1])
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, parts[2])
            elif parts[0] == 'Keywords' and len(parts) == 3:
                # /Keywords/Keyword/photo.jpg
                photos = self._get_photos_by_keyword(parts[1])
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, parts[2])
            elif parts[0] == 'By Date' and len(parts) == 4:
                # /By Date/Year/Month/photo.jpg
                photos = self._get_photos_by_date_month(parts[1], parts[2])
                if photos:
                    photo = self._find_photo_in_list_by_filename(photos, parts[3])
        
        if photo and os.path.exists(photo.path):
            # Ensure we only open in read mode
            actual_flags = flags & ~(os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
            actual_flags |= os.O_RDONLY
            
            fh = self._next_fh
            self._next_fh += 1
            fd = os.open(photo.path, actual_flags, mode)
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
    
    # New helper methods for cached access
    
    def _get_photos_by_face(self, face_name):
        """Get photos for a specific face/person."""
        return self._cache['faces'].get(face_name)
    
    def _get_photos_by_location(self, location):
        """Get photos for a specific location."""
        return self._cache['locations'].get(location)
    
    def _get_photos_by_keyword(self, keyword):
        """Get photos for a specific keyword."""
        return self._cache['keywords'].get(keyword)
    
    def _get_photos_by_date_year(self, year):
        """Get photos for a specific year."""
        return self._cache['by_date'].get(year)
    
    def _get_photos_by_date_month(self, year, month_name):
        """Get photos for a specific year and month."""
        key = f"{year}/{month_name}"
        return self._cache['by_date'].get(key)
    
    def _get_months_for_year(self, year):
        """Get all month names for a specific year."""
        months = set()
        for key in self._cache['by_date'].keys():
            if key.startswith(f"{year}/"):
                month = key.split('/')[1]
                months.add(month)
        return months
    
    def _find_photo_in_list_by_filename(self, photo_list, filename):
        """Find a photo in a list by filename."""
        if photo_list:
            for photo in photo_list:
                if os.path.basename(photo.path) == filename:
                    return photo
        return None


def mount_photos(library_path, mount=None, foreground=True, verbose=False):
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
        photos_db = osxphotos.PhotosDB(library_path)
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
        PhotosFUSEFS(photos_db, verbose=verbose),
        mount,
        nothreads=False,
        foreground=foreground,
        ro=True,
        allow_other=True,
        fsname=lib_name,
        volname=lib_name
    )
    
    return fuse
