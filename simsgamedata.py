# -*- coding: utf-8 -*-

#Copyright (C) 2014, 2015 Fabian Hachenberg

#This file is part of BlenderSims Plugin.
#BlenderSims Plugin is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#More information about the license is provided in the LICENSE file.

#BlenderSims Plugin requires PySims Lib (see https://github.com/fHachenberg/PySims)
#The Sims™ is a trademark of Maxis and Electronic Arts.

'''
Classes to automatically look up files from the original game data
(from FAR archives mainly)
'''

import logging

from PySims.far import FarFile
from PySims.datastream import TextDataStream, BinaryDataStream

class DictFileLoader(object):
    '''
    Abstract class to allow to access the files in a direcory or FAR archive
    via dict access (obj[basename]) using the basename of the file.
    What 'basename' means and what to return depends on whether it is a
    FAR archive or a directory and also on the file type

    Because there are half a dozen of different variants which differ
    only very slightly, we have not implemented them using subclasses
    of an abstract base class. Instead this class has 3 properties
    which determine the way an file access is handles:
    * format_str is a format string which turns the basename into a full filename
    * openf is a function which accepts the full filename and has to return a stream
    * wrapstream is a function which accepts the opened stream and (optionally) wraps it in another class.

    wrapstream is meant to allow streams to binary format files to be
    wrapped in BinaryDataStream, streams to text format files in TextDataStream respectively
    '''
    def __init__(self, format_str, openf, wrapstream):
        self.format_str = format_str
        self.openf = openf
        self.wrapstream = wrapstream

    def __getitem__(self, basename):
        fullname = self.format_str % basename
        return self.wrapstream(self.openf(fullname))

class AnyFileLoader(object):
    '''
    Tries multiple DictFileLoaders, returns the first valid result
    '''
    def __init__(self, loaders):
        self.loaders = loaders

    def __getitem__(self, basename):
        for loader in self.loaders:
            try:
                return loader[basename]
            except IOError:
                pass
        #No match found, raise IOError
        raise IOError("Could not find match for basename '%s' in loaders %s" % (basename, self.loaders))

#Those are the variants to open the file

class OpenFromFar(object):
    '''
    IMPORTANT: Reuses the same stream over and over again, so it cannot
               be used to access multiple FAR files in parallel!
    '''
    def __init__(self, far_file, far_stream):
        self.far_stream = far_stream
        self.far_file = far_file #pass far file directly so we dont have to parse it multiple times!

    def __call__(self, fullname):
        return self.far_file.open(fullname, self.far_stream)

from os.path import join, isdir
from pathlib import Path
import tempfile

class GetFilenameFromTemporaryFromFar(OpenFromFar):
    '''
    case-insensitive!

    Extracts file into temporary file and returns its filename
    Relevant to load textures into Blender
    '''
    def __init__(self, far_file, far_stream):
        OpenFromFar.__init__(self, far_file, far_stream)
        self.content = dict((e.lower(), e) for e in self.far_file.filenames)

    def __call__(self, fullname):
        strm = self.far_file.open(self.content[fullname.lower()], self.far_stream)
        _, tmpfile = tempfile.mkstemp()
        with open(tmpfile, "wb") as f:
            f.write(strm.read())
        return tmpfile

class OpenFromDir(object):
    '''
    case-insensitive!
    '''
    def __init__(self, path):
        self.path = path
        self.content = dict((e.name.lower(), e) for e in Path(self.path).iterdir())

    def __call__(self, fullname):
        try:
            return open(self.content[fullname.lower()], "rb")
        except KeyError:
            raise IOError("No such file '%s' in '%s'" % (fullname, self.path))

class GetFilenameFromDir(OpenFromDir):
    '''
    case-insensitive!

    Does not actually open a stream but just returns the filename
    Relevant to load textures into Blender
    '''
    def __init__(self, path):
        OpenFromDir.__init__(self, path)

    def __call__(self, fullname):
        try:
            return self.content[fullname.lower()]
        except KeyError:
            raise IOError("No such file '%s' in '%s'" % (fullname, self.path))

#Those are the variants to wrap the stream

wrap_in_binarystream = lambda stream: BinaryDataStream(stream)
wrap_in_textstream   = lambda stream: TextDataStream(stream)
dont_wrap            = lambda stream: stream

#Those are the actual combinations for opening and wrapping
#please note that - in principle - the file extensions indicates if bin or txt format is present
FarFileAniLoader  = lambda far_file, far_stream: DictFileLoader("%s.cfp", OpenFromFar(far_file, far_stream), dont_wrap)
FarFileCharLoader = lambda far_file, far_stream: DictFileLoader("%s.cmx.bcf", OpenFromFar(far_file, far_stream), dont_wrap) #we dont have to wrap because loading routine is smart enough to figure it out for itself
FarFileSkinLoader = lambda far_file, far_stream: DictFileLoader("%s.bmf", OpenFromFar(far_file, far_stream), wrap_in_binarystream)
FarTexLoader      = lambda far_file, far_stream: DictFileLoader("%s.bmp", GetFilenameFromTemporaryFromFar(far_file, far_stream), dont_wrap)
DirTexLoader      = lambda path:       DictFileLoader("%s.bmp", GetFilenameFromDir(path), dont_wrap)
DirCharLoader     = lambda path:       DictFileLoader("%s.cmx", OpenFromDir(path), dont_wrap) #we dont have to wrap because loading routine is smart enough to figure it out for itself
DirSkinLoader     = lambda path:       DictFileLoader("%s.skn", OpenFromDir(path), wrap_in_textstream)
DirTexLoader      = lambda path:       DictFileLoader("%s.bmp", GetFilenameFromDir(path), dont_wrap)
