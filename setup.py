from setuptools import setup, find_packages

setup(
    name='photosfs',
    version='0.1',
    description='Mount Apple Photos libraries as a FUSE filesystem',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Robert Harder',
    author_email='rob@iharder.net',
    url='https://github.com/rharder/photosfs',
    packages=find_packages(),
    install_requires=[
        'fusepy>=3.0',
        'osxphotos>=0.30',
    ],
    entry_points={
        'console_scripts': [
            'mount_photosfs=photosfs.mount_photosfs:main',
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'License :: Public Domain',
        'Operating System :: MacOS',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: System :: Filesystems',
        'Topic :: Multimedia :: Graphics',
    ],
    python_requires='>=3.8',
)
