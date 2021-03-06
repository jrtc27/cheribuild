#
# Copyright (c) 2018 Alex Richardson
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#

from .utils import *
from pathlib import Path
from collections import OrderedDict
import os
import shlex
import stat
import sys


class MtreeEntry(object):
    def __init__(self, path: str, attributes: "typing.Dict[str, str]"):
        self.path = path
        self.attributes = attributes

    def is_dir(self):
        return self.attributes.get("type") == "dir"

    def is_file(self):
        return self.attributes.get("type") == "file"

    @classmethod
    def parse(cls, line: str, contents_root: Path=None) -> "MtreeEntry":
        elements = shlex.split(line)
        path = elements[0]
        # Ensure that the path is normalized:
        if path != ".":
            # print("Before:", path)
            assert path[:2] == "./"
            path = path[:2] + os.path.normpath(path[2:])
            # print("After:", path)
        attrDict = OrderedDict()  # keep them in insertion order
        for k,v in map(lambda s: s.split(sep="=", maxsplit=1), elements[1:]):
            # ignore some tags that makefs doesn't like
            # sometimes there will be time with nanoseconds in the manifest, makefs can't handle that
            # also the tags= key is not supported
            if k in ("tags", "time"):
                continue
            # convert relative contents=keys to absolute ones
            if contents_root and k == "contents":
                if not os.path.isabs(v):
                    v = str(contents_root / v)
            attrDict[k] = v
        return MtreeEntry(path, attrDict)
        # FIXME: use contents=

    @classmethod
    def parseAllDirsInMtree(cls, mtreeFile: Path) -> "typing.List[MtreeEntry]":
        with mtreeFile.open("r", encoding="utf-8") as f:
            result = []
            for line in f.readlines():
                if " type=dir" in line:
                    try:
                        result.append(MtreeEntry.parse(line))
                    except Exception:
                        warningMessage("Could not parse line", line, "in mtree file", mtreeFile)
            return result

    def __str__(self):
        return self.path + " " + " ".join(k + "=" + v for k, v in self.attributes.items())

    def __repr__(self):
        return "<MTREE entry: " + str(self) + ">"


class MtreeFile(object):
    def __init__(self, file: "typing.Union[io.StringIO,Path,typing.IO]"=None, contents_root: Path=None):
        self._mtree = OrderedDict()  # type: typing.Dict[str, MtreeEntry]
        if file:
            self.load(file, contents_root)

    def load(self, file: "typing.Union[io.StringIO,Path,typing.IO]", contents_root: Path=None):
        if isinstance(file, Path):
            with file.open("r") as f:
                self.load(f)
                return
        self._mtree.clear()
        for line in file.readlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entry = MtreeEntry.parse(line, contents_root)
                key = str(entry.path)
                assert key == "." or os.path.normpath(key[2:]) == key[2:]
                if key in self._mtree:
                    warningMessage("Found duplicate definition for", entry.path)
                self._mtree[key] = entry
            except Exception as e:
                warningMessage("Could not parse line", line, "in mtree file", file, ":", e)

    @staticmethod
    def _ensure_mtree_mode_fmt(mode: "typing.Union[str, int]") -> str:
        if not isinstance(mode, str):
            mode = "0" + oct(mode)[2:]
        assert mode.startswith("0")
        return mode

    @staticmethod
    def _ensure_mtree_path_fmt(path: str) -> str:
        # The path in mtree always starts with ./
        assert not path.endswith("/")
        assert path, "PATH WAS EMPTY?"
        mtree_path = path
        if mtree_path != ".":
            # ensure we normalize paths to avoid conflicting duplicates:
            mtree_path = "./" + os.path.normpath(path)
        return mtree_path

    @staticmethod
    def infer_mode_string(path: Path, should_be_dir):
        try:
            result = "0{0:o}".format(stat.S_IMODE(path.lstat().st_mode))  # format as octal with leading 0 prefix
        except IOError as e:
            default = "0755" if should_be_dir else "0644"
            warningMessage("Failed to stat", path, "assuming mode",  default, e)
            result = default
        # make sure that the .ssh config files are installed with the right permissions
        if path.name == ".ssh" and result != "0700":
            warningMessage("Wrong file mode", result, "for", path, " --  it should be 0700, fixing it for image")
            return "0700"
        if path.parent.name == ".ssh" and not path.name.endswith(".pub") and result != "0600":
            warningMessage("Wrong file mode", result, "for", path, " --  it should be 0600, fixing it for image")
            return "0600"
        return result

    def add_file(self, file: Path, path_in_image, mode=None, uname="root", gname="wheel", print_status=True,
                 parent_dir_mode=None):
        if isinstance(path_in_image, Path):
            path_in_image = str(path_in_image)
        assert not path_in_image.startswith("/")
        assert not path_in_image.startswith("./") and not path_in_image.startswith("..")
        if mode is None:
            mode = self.infer_mode_string(file, False)
        mode = self._ensure_mtree_mode_fmt(mode)
        mtree_path = self._ensure_mtree_path_fmt(path_in_image)
        assert mtree_path != ".", "files should not have name ."
        self.add_dir(str(Path(path_in_image).parent), mode=parent_dir_mode, uname=uname, gname=gname,
                     reference_dir=file.parent, print_status=print_status)
        if file.is_symlink():
            mtree_type = "link"
            last_attrib = ("link", os.readlink(str(file)))
        else:
            mtree_type = "file"
            # now add the actual entry (with contents=/path/to/file)
            contents_path = str(file.absolute())
            assert shlex.quote(contents_path) == contents_path, "Invalid special chars: " + contents_path
            last_attrib = ("contents", contents_path)
        attribs = OrderedDict([("type", mtree_type), ("uname", uname), ("gname", gname), ("mode", mode), last_attrib])
        if print_status:
            statusUpdate("Adding file", file, "to mtree as", mtree_path, file=sys.stderr)
        self._mtree[mtree_path] = MtreeEntry(mtree_path, attribs)

    def add_dir(self, path, mode=None, uname="root", gname="wheel", print_status=True, reference_dir=None):
        assert not path.startswith("/"), path
        path = path.rstrip("/")  # remove trailing slashes
        mtree_path = self._ensure_mtree_path_fmt(path)
        if mtree_path in self._mtree:
            return
        if mode is None:
            if reference_dir is None or mtree_path == ".":
                mode = "0755"
            else:
                if print_status:
                    statusUpdate("Inferring permissions for", path, "from", reference_dir, file=sys.stderr)
                mode = self.infer_mode_string(reference_dir, True)
        mode = self._ensure_mtree_mode_fmt(mode)
        # recursively add all parent dirs that don't exist yet
        parent = str(Path(path).parent)
        if parent != path:  # avoid recursion for path == "."
            # print("adding parent", parent, file=sys.stderr)
            if reference_dir is not None:
                self.add_dir(parent, None, uname, gname, print_status=print_status, reference_dir=reference_dir.parent)
            else:
                self.add_dir(parent, mode, uname, gname, print_status=print_status, reference_dir=None)
        # now add the actual entry
        attribs = OrderedDict([("type", "dir"), ("uname", uname), ("gname", gname), ("mode", mode)])
        if print_status:
            statusUpdate("Adding dir", path, "to mtree", file=sys.stderr)
        self._mtree[mtree_path] = MtreeEntry(mtree_path, attribs)

    def __contains__(self, item):
        mtree_path = self._ensure_mtree_path_fmt(str(item))
        return mtree_path in self._mtree

    def __repr__(self):
        import pprint
        return "<MTREE: " + pprint.pformat(self._mtree) + ">"

    def write(self, output: "typing.Union[io.StringIO,Path,typing.IO]"):
        if isinstance(output, Path):
            with output.open("w") as f:
                self.write(f)
                return
        output.write("#mtree 2.0\n")
        for path in sorted(self._mtree.keys()):
            output.write(str(self._mtree[path]))
            output.write("\n")
        output.write("# END\n")

