"""
Temporary tools to aid in Linux support development.

Will be fully removed when support is ready.
NOT to be used in any non-temporary code.
"""
import os
import json
import sys

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


FORCE_WARNING_MESSAGE = f"""{bcolors.WARNING}
***************************************************************************
You are forcing execution on a reportedly unsuported Operating System.
Unless you have a specific reason to do so, crashes are normal and expected.
***************************************************************************{bcolors.ENDC}
"""

class Info:
    aij = None
    _PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "appinfo.json")
    if aij is None:
        aij = json.load(open(_PATH))
    lnk = aij["github_link"]
    ver = aij["version"]
    l_rdy = aij["linux_ready"]
    l_prog = aij["linux_dev_progress"]


class ProgTrk:
    prog = Info.l_prog        # percentage based current implementation progress
    color = bcolors.ENDC
    if (prog < 33):
        color = bcolors.OKBLUE
    elif (prog < 66):
        color = bcolors.OKCYAN
    else:
        color = bcolors.OKGREEN

    def GetProg():
        m = 100
        if (ProgTrk.prog > m):
            ProgTrk.prog = 100
        
        s = 25
        ps = round(ProgTrk.prog / (m / s))
        
        fill = "=" * (ps - 1)
        marker = ">"
        blank = "-" * (s - ps)

        bar = f"{ProgTrk.color}[{fill}{marker}{blank}] ~{ProgTrk.prog}% complete.{bcolors.ENDC}"

        return bar
    
    def LinuxDevProgError():
        import distro
        import _linux_support_wip_tools as ltools
        s = " "
        print(f"""{ltools.bcolors.FAIL}
|=========================================================|
 Linux support is under development and not yet available.
|=========================================================|{ltools.bcolors.ENDC}
Detected host operating system:{ltools.bcolors.BOLD} {ltools.bcolors.WARNING}{s.join(distro.linux_distribution()[:-1])}
{ltools.bcolors.ENDC}

Current Linux support implementation progress: {ProgTrk.GetProg()}


{bcolors.OKBLUE}If you are on Windows{bcolors.ENDC}, please report the issue at
{ltools.bcolors.HEADER}{ltools.Info.lnk}{ltools.bcolors.ENDC} specifying app version {ltools.bcolors.OKCYAN}{ltools.Info.ver}
{ltools.bcolors.OKBLUE}and run the program again using the '--force' argument.{bcolors.ENDC}


*******************
Program has exited.
*******************""")
        sys.exit()

