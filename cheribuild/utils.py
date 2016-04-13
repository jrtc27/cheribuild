import os
import shlex
import subprocess
import sys
from .colour import coloured, AnsiColour
from .chericonfig import CheriConfig

# reduce the number of import statements per project  # no-combine
__all__ = ["typing", "CheriConfig", "IS_LINUX", "IS_FREEBSD", "printCommand",  # no-combine
           "runCmd", "statusUpdate", "fatalError", "coloured", "AnsiColour", "setCheriConfig"]  # no-combine

IS_LINUX = sys.platform.startswith("linux")
IS_FREEBSD = sys.platform.startswith("freebsd")
_cheriConfig = None  # type: CheriConfig


# To make it easier to use this as a module (probably most of these commands should be in Project)
def setCheriConfig(c: "CheriConfig"):
    print("Setting cheri config to", c)
    global _cheriConfig
    _cheriConfig = c


def printCommand(arg1: "typing.Union[str, typing.Sequence[typing.Any]]", *remainingArgs,
                 colour=AnsiColour.yellow, cwd=None, sep=" ", printVerboseOnly=False, **kwargs):
    if _cheriConfig.quiet or (printVerboseOnly and not _cheriConfig.verbose):
        return
    # also allow passing a single string
    if not type(arg1) is str:
        allArgs = arg1
        arg1 = allArgs[0]
        remainingArgs = allArgs[1:]
    newArgs = ("cd", shlex.quote(str(cwd)), "&&") if cwd else tuple()
    # comma in tuple is required otherwise it creates a tuple of string chars
    newArgs += (shlex.quote(str(arg1)),) + tuple(map(shlex.quote, map(str, remainingArgs)))
    print(coloured(colour, newArgs, sep=sep), flush=True, **kwargs)


def runCmd(*args, captureOutput=False, captureError=False, input: "typing.Union[str, bytes]"=None, timeout=None,
           printVerboseOnly=False, **kwargs):
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        cmdline = args[0]  # list with parameters was passed
    else:
        cmdline = args
    cmdline = list(map(str, cmdline))  # make sure they are all strings
    printCommand(cmdline, cwd=kwargs.get("cwd"), printVerboseOnly=printVerboseOnly)
    kwargs["cwd"] = str(kwargs["cwd"]) if "cwd" in kwargs else os.getcwd()
    if _cheriConfig.pretend:
        return CompletedProcess(args=cmdline, returncode=0, stdout=b"", stderr=b"")

    # actually run the process now:
    if input is not None:
        assert "stdin" not in kwargs  # we need to use stdin here
        kwargs['stdin'] = subprocess.PIPE
        if not isinstance(input, bytes):
            input = str(input).encode("utf-8")
    if captureOutput:
        assert "stdout" not in kwargs  # we need to use stdout here
        kwargs["stdout"] = subprocess.PIPE
    if captureError:
        assert "stderr" not in kwargs  # we need to use stdout here
        kwargs["stderr"] = subprocess.PIPE
    elif _cheriConfig.quiet and "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.DEVNULL
    with subprocess.Popen(cmdline, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            # TODO py35: pass stderr=stderr as well
            raise subprocess.TimeoutExpired(process.args, timeout, output=stdout)
        except:
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
        if retcode:
            raise subprocess.CalledProcessError(retcode, process.args, output=stdout)
        return CompletedProcess(process.args, retcode, stdout, stderr)


def statusUpdate(*args, sep=" ", **kwargs):
    print(coloured(AnsiColour.cyan, *args, sep=sep), **kwargs)


def fatalError(*args, sep=" "):
    # we ignore fatal errors when simulating a run
    if _cheriConfig.pretend:
        print(coloured(AnsiColour.red, ("Potential fatal error:",) + args, sep=sep))
    else:
        sys.exit(coloured(AnsiColour.red, ("Fatal error:",) + args, sep=sep))