#
# Copyright (c) 2016 Alex Richardson
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
import functools
import sys
import time

from collections import OrderedDict
from .config.chericonfig import CheriConfig, CrossCompileTarget
from .utils import *



class Target(object):
    instantiating_targets_should_warn = True

    def __init__(self, name, projectClass: "typing.Type[SimpleProject]"):
        self.name = name
        self.projectClass = projectClass
        self.__project = None  # type: pycheribuild.project.SimpleProject
        self._completed = False
        self._tests_have_run = False
        self._creating_project = False  # avoid cycles

    def get_or_create_project(self, target_arch: "typing.Optional[CrossCompileTarget]", config) -> "SimpleProject":
        # Note: MultiArchTarget uses caller to select the right project (e.g. libcxxrt-native needs libunwind-native path)
        if self.__project is None:
            self.__project = self.create_project(config)
        assert self.__project is not None
        return self.__project

    def get_dependencies(self, config) -> "typing.List[Target]":
        return self.projectClass.recursive_dependencies(config)

    def checkSystemDeps(self, config: CheriConfig):
        if self._completed:
            return
        project = self.get_or_create_project(None, config)
        with setEnv(PATH=config.dollarPathWithOtherTools):
            # make sure all system dependencies exist first
            project.checkSystemDependencies()

    def create_project(self, config: CheriConfig) -> "SimpleProject":
        assert not self._creating_project
        if self.instantiating_targets_should_warn:
            raise RuntimeError(coloured(AnsiColour.magenta, "Instantiating target", self.name, "before run()!"))
        self._creating_project = True
        return self._create_project(config)

    def _create_project(self, config: CheriConfig) -> "SimpleProject":
        return self.projectClass(config)

    def execute(self, config: CheriConfig):
        if self._completed:
            # TODO: make this an error once I have a clean solution for the pseudo targets
            warningMessage(self.name, "has already been executed!")
            return
        # instantiate the project and run it
        starttime = time.time()
        assert self.__project is not None, "Should have been initialized in checkSystemDeps()"
        project = self.__project
        new_env = {"PATH": project.config.dollarPathWithOtherTools}
        if project.config.clang_colour_diags:
            new_env["CLANG_FORCE_COLOR_DIAGNOSTICS"] = "always"
        with setEnv(**new_env):
            project.process()
        statusUpdate("Built target '" + self.name + "' in", time.time() - starttime, "seconds")
        self._completed = True

    def run_tests(self, config: "CheriConfig"):
        if self._tests_have_run:
            # TODO: make this an error once I have a clean solution for the pseudo targets
            warningMessage(self.name, "has already been executed!")
            return
        # instantiate the project and run it
        starttime = time.time()
        project = self.get_or_create_project(None, config)
        new_env = {"PATH": project.config.dollarPathWithOtherTools}
        if project.config.clang_colour_diags:
            new_env["CLANG_FORCE_COLOR_DIAGNOSTICS"] = "always"
        with setEnv(**new_env):
            project.run_tests()
        statusUpdate("Ran tests for target '" + self.name + "' in", time.time() - starttime, "seconds")
        self._tests_have_run = True

    def reset(self):
        # For unit tests to get a fresh instance
        self._completed = False
        self._tests_have_run = False
        self.__project = None
        self._creating_project = False

    def __lt__(self, other: "Target"):
        # print(self, "__lt__", other)
        # if this target is one of the dependencies order it before
        otherDeps = other.projectClass._cached_dependencies()
        # print("other deps:", otherDeps)
        if self in otherDeps:
            # print(self, "is in", other, "deps -> is less")
            return True
        # and if it is the other way around we are not less
        if other in self.projectClass._cached_dependencies():
            # print(other, "is in", self, "deps -> is greater")
            return False
        if other.name.startswith("run") and not self.name.startswith("run"):
            return True  # run must be executed last
        elif self.name.startswith("run"):
            return False
        if other.name.startswith("disk-image") and not self.name.startswith("disk-image"):
            return True  # disk-image should be done just before run
        elif self.name.startswith("disk-image"):
            return False
        # print(self, "is not in", other, "deps -> is not less")
        # otherwise just keep everything in order
        return False
        # This was previously done
        # ownDeps = self.projectClass.allDependencyNames()
        # if len(ownDeps) < len(otherDeps):
        #     return True
        # if len(ownDeps) > len(otherDeps):
        #     return False
        # return self.name < other.name  # not a dep and number of deps is the same -> compare name

    def __repr__(self):
        return "<Target " + self.name + ">"


# XXX: can't call this CrossCompileTarget since that is already the name of the enum
class MultiArchTarget(Target):
    def __init__(self, name, projectClass, target_arch: "typing.Optional[CrossCompileTarget]",
                 base_target: "MultiArchTargetAlias"):
        super().__init__(name, projectClass)
        self.target_arch = target_arch
        base_target.derived_targets.append(self)

    def _create_project(self, config: CheriConfig):
        from .projects.cross.crosscompileproject import CrossCompileMixin
        from .projects.cross.cheribsd import BuildFreeBSD
        assert issubclass(self.projectClass, CrossCompileMixin) or issubclass(self.projectClass, BuildFreeBSD)
        return self.projectClass(config)

    def __repr__(self):
        return "<Cross target (" + self.target_arch.name + ") " + self.name + ">"


# This is used for targets like "libcxx", etc and resolves to "libcxx-cheri/libcxx-native/libcxx-mips"
# at runtime
class MultiArchTargetAlias(Target):
    def __init__(self, name, projectClass):
        super().__init__(name, projectClass)
        self.derived_targets = []  # type: typing.List[MultiArchTarget]


    def get_real_target(self, cross_target: "typing.Optional[CrossCompileTarget]", config) -> MultiArchTarget:
        if cross_target is None:
            # Use the default target:
            cross_target = self.projectClass.get_crosscompile_target(config)
        assert cross_target is not None
        # find the correct derived project:
        for tgt in self.derived_targets:
            if tgt.target_arch == cross_target:
                return tgt
        raise LookupError("Could not find target for " + str(cross_target))

    def get_or_create_project(self, cross_target: "typing.Optional[CrossCompileTarget]", config) -> "SimpleProject":
        # If there are any derived targets pick the right one based on the target_arch:
        assert self.derived_targets, "derived targets must not be empty"
        return self.get_real_target(cross_target, config).get_or_create_project(cross_target, config)

    def _create_project(self, config: CheriConfig):
        from .projects.cross.crosscompileproject import CrossCompileMixin
        from .projects.cross.cheribsd import BuildFreeBSD
        assert issubclass(self.projectClass, CrossCompileMixin) or issubclass(self.projectClass, BuildFreeBSD)
        return self.projectClass(config)

    def execute(self, config):
        return self.get_real_target(None, config).execute(config)

    def run_tests(self, config: "CheriConfig"):
        return self.get_real_target(None, config).run_tests(config)

    def checkSystemDeps(self, config: CheriConfig):
        return self.get_real_target(None, config).checkSystemDeps(config)

    def __repr__(self):
        return "<Cross target alias " + self.name + ">"


class TargetManager(object):
    def __init__(self):
        self._allTargets = {}

    def addTarget(self, target: Target) -> None:
        self._allTargets[target.name] = target

    def registerCommandLineOptions(self):
        # this cannot be done in the Project metaclass as otherwise we get
        # RuntimeError: super(): empty __class__ cell
        # https://stackoverflow.com/questions/13126727/how-is-super-in-python-3-implemented/28605694#28605694
        for tgt in self._allTargets.values():
            tgt.projectClass.setupConfigOptions()

    @property
    def targetNames(self):
        return self._allTargets.keys()

    @property
    def targets(self) -> "typing.Iterable[Target]":
        return self._allTargets.values()

    def get_target_raw(self, name: str):
        # return the actual target without resolving MultiArchTargetAlias
        return self._allTargets[name]

    def get_target(self, name: str, arch: "typing.Optional[CrossCompileTarget]", config: CheriConfig) -> Target:
        target = self.get_target_raw(name)
        # print("get_target", name, arch, end="")
        if isinstance(target, MultiArchTargetAlias):
            # Pick the default architecture if no arch was passed
            # print(" raw_target:", target, " default arch = ", target.projectClass.default_architecture, end="")
            if arch is None and target.projectClass.default_architecture is not None:
                arch = target.projectClass.default_architecture
            target = target.get_real_target(arch, config)
        # print(" ->", target)
        return target

    def topologicalSort(self, targets: "typing.List[Target]") -> "typing.Iterable[typing.List[Target]]":
        # based on http://rosettacode.org/wiki/Topological_sort#Python
        data = dict((t.name, set(t.get_dependencies(None))) for t in targets)

        # add all the targets that aren't included yet
        allDependencyNames = [t.projectClass.allDependencyNames() for t in targets]
        possiblyMissingDependencies = functools.reduce(set.union, allDependencyNames, set())
        for dep in possiblyMissingDependencies:
            if dep not in data:
                data[dep] = self._allTargets[dep].dependencies

        # do the actual sorting
        while True:
            ordered = set(item for item, dep in data.items() if not dep)
            if not ordered:
                break
            yield list(sorted(ordered))
            data = {item: (dep - ordered) for item, dep in data.items()
                    if item not in ordered}
        assert not data, "A cyclic dependency exists amongst %r" % data

    @staticmethod
    def sort_in_dependency_order(targets: "typing.List[Target]") -> "typing.List[Target]":
        # pythons sorted() is guaranteed to be stable:
        sorted_targets = list(sorted(targets))
        # remove duplicates (insert into an orderdict to keep order
        return list(OrderedDict((x, True) for x in sorted_targets).keys())

    def get_all_targets(self, explicit_targets: "typing.List[Target]", config: CheriConfig) -> "typing.List[Target]":
        add_dependencies = config.includeDependencies
        chosen_targets = []  # type: typing.List[Target]
        for t in explicit_targets:
            chosen_targets.append(t)
            deps_to_add = []
            if add_dependencies:
                deps_to_add = t.projectClass.recursive_dependencies(config)
            elif t.projectClass.dependenciesMustBeBuilt:
                # some targets such as sdk always need their dependencies build:
                deps_to_add = t.projectClass.recursive_dependencies(config)
            elif t.projectClass.isAlias:
                assert not t.projectClass.dependenciesMustBeBuilt
                # for aliases without full dependencies just add the direct dependencies
                deps_to_add = t.projectClass.direct_dependencies(config)
            # Now add all the dependencies:
            for dep_target in deps_to_add:
                # when --skip-sdk is passed don't include sdk dependencies
                if config.skipSdk and dep_target.projectClass.is_sdk_target:
                    if config.verbose:
                        statusUpdate("Not adding ", t, "dependency", dep_target,
                                     "since it is an SDK target and --skip-sdk was passed.")
                    continue
                chosen_targets.append(dep_target)

        sort = self.sort_in_dependency_order(chosen_targets)
        return sort

    def run(self, config: CheriConfig):
        chosenTargets = self.get_all_chosen_targets(config)

        for target in chosenTargets:
            target.checkSystemDeps(config)
        # all dependencies exist -> run the targets
        for target in chosenTargets:
            if config.print_targets_only:
                statusUpdate("Will build target", coloured(AnsiColour.yellow, target.name))
                print("    Dependencies for", target.name, "are", target.projectClass.allDependencyNames(config))
            else:
                target.execute(config)

    def get_all_chosen_targets(self, config) -> "typing.Iterable[Target]":
        # check that all target dependencies are correct:
        for t in self._allTargets.values():
            for dep in t.get_dependencies(config):
                if dep.name not in self._allTargets:
                    sys.exit("Invalid dependency " + dep.name + " for " + t.projectClass.__name__)
        # targetsSorted = sorted(self._allTargets.values())
        # print(" ".join(t.name for t in targetsSorted))
        # assert self._allTargets["llvm"] < self._allTargets["cheribsd"]
        # assert self._allTargets["llvm"] < self._allTargets["all"]
        # assert self._allTargets["disk-image"] > self._allTargets["qemu"]
        # assert self._allTargets["sdk"] > self._allTargets["sdk-sysroot"]
        explicitlyChosenTargets = []  # type: typing.List[Target]
        for targetName in config.targets:
            if targetName not in self._allTargets:
                sys.exit(coloured(AnsiColour.red, "Target", targetName, "does not exist. Valid choices are",
                                  ",".join(self.targetNames)))
            explicitlyChosenTargets.append(self.get_target(targetName, None, config))
        chosenTargets = self.get_all_targets(explicitlyChosenTargets, config)
        if config.verbose:
            print("Will execute the following targets:", " ".join(t.name for t in chosenTargets))
        # now that the chosen targets have been resolved run them
        Target.instantiating_targets_should_warn = False  # Fine to instantiate Project() now
        return chosenTargets

    def reset(self):
        for i in self._allTargets.values():
            i.reset()

targetManager = TargetManager()
