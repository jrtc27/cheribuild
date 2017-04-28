#
# Copyright (c) 2017 Alex Richardson
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
import os
import shlex
import subprocess
import sys

from pathlib import Path

from .config.loader import ConfigLoaderBase, DefaultValueOnlyConfigOption
from .config.jenkinsconfig import JenkinsConfig
from .project import SimpleProject
# noinspection PyUnresolvedReferences
from .projects import *  # make sure all projects are loaded so that targetManager gets populated
# noinspection PyUnresolvedReferences
from .projects.cross import *  # make sure all projects are loaded so that targetManager gets populated
from .projects.cross.crosscompileproject import CrossCompileProject
from .targets import targetManager
from .utils import *


class JenkinsConfigLoader(ConfigLoaderBase):
    """
    A simple config loader that always returns the default value for all added options
    """

    def load(self):
        self._parsedArgs = self._parser.parse_args()

    def finalizeOptions(self, availableTargets: list, **kwargs):
        targetOption = self._parser.add_argument("targets", metavar="TARGET", nargs=1,
                                                 help="The target to build", choices=availableTargets)
        if "_ARGCOMPLETE" in os.environ:
            try:
                import argcomplete
            except ImportError:
                sys.exit("argcomplete missing")
            targetCompleter = argcomplete.completers.ChoicesCompleter(availableTargets)
            targetOption.completer = targetCompleter
            argcomplete.autocomplete(
                self._parser,
                always_complete_options=None,  # don't print -/-- by default
                print_suppressed=True,  # also include target-specific options
            )

    def __init__(self):
        super().__init__(DefaultValueOnlyConfigOption)

    def parseArguments(self):
        self._parsedArgs = self._parser.parse_args()


def _jenkins_main():
    allTargetNames = list(sorted(targetManager.targetNames))
    configLoader = JenkinsConfigLoader()
    # Register all command line options
    cheriConfig = JenkinsConfig(configLoader, allTargetNames)
    SimpleProject._configLoader = configLoader
    targetManager.registerCommandLineOptions()
    cheriConfig.load()
    setCheriConfig(cheriConfig)
    # cheriConfig.dumpOptionsJSON()

    do_build = True
    do_tarball = False
    if do_build:
        # unpack the SDK if it has not been extracted yet:
        "tar Jxf $SDK_CPU-$ISA-jemalloc-sdk.tar.xz --strip-components 1 -C cherisdk"
        if not cheriConfig.sdkBinDir.is_dir():
            if not cheriConfig.sdkArchivePath.exists():
                fatalError(cheriConfig.sdkBinDir, "does not exist and SDK archive", cheriConfig.sdkArchivePath,
                           "does not exist!")
            runCmd("tar", "Jxf", cheriConfig.sdkArchivePath, "--strip-components", "1", "-C", cheriConfig.sdkSysrootDir)
        assert len(cheriConfig.targets) == 1
        target = targetManager.targetMap[cheriConfig.targets[0]]
        target.checkSystemDeps(cheriConfig)
        # need to set destdir after checkSystemDeps:
        project = target.project
        assert project
        if isinstance(project, CrossCompileProject):
            project.destdir = cheriConfig.outputRoot
            project.installPrefix = cheriConfig.installationPrefix
            project.installDir = cheriConfig.outputRoot
        target.execute()
    if do_tarball:
        raise NotImplementedError()


def jenkins_main():
    try:
        _jenkins_main()
    except KeyboardInterrupt:
        sys.exit("Exiting due to Ctrl+C")
    except subprocess.CalledProcessError as err:
        fatalError("Command ", "`" + " ".join(map(shlex.quote, err.cmd)) + "` failed with non-zero exit code",
                   err.returncode)