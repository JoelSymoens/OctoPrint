"""
This file is responsible for calculating the version of OctoPrint.

It's based heavily on versioneer and miniver.

The version is calculated as follows:

If a file named `_static_version.py` exists in the package root, it is
imported and the version is read from there. This is the case for
source distributions created by `setup.py sdist` as well as binary distributions
built by `setup.py bdist` and `setup.py bdist_wheel`.

If no such file exists, the version is calculated from git and the provided set
of branch version rules. If the current branch matches one of the rules, the
version is calculated as `<tag>.dev<distance>+g<short>` where `<tag>` is the
virtual tag associated with the current branch, `<distance>` is the distance of
the current HEAD from the reference commit of the branch and `<short>` is the
short SHA1 of the current HEAD. If the current branch does not match any of the
rules, the version is the closest tag reachable from the current HEAD.

If the current HEAD is dirty, the version as calculated from a matching branch
rule is appended with `.dirty`. Versions from a closest tag instead get
`.post<distance>.dev0` appended.

If no tag can be determined but a commit hash, the version is `0+unknown.g<short>`.

If no commit hash can be determined either, the version is `0+unknown`.
"""

import errno
import os
import re
import subprocess
import sys

# Adjust this on every release (candidate) ----------------------------------------------

BRANCH_VERSIONS = """
# Configuration for the branch versions, manually mapping tags based on branches
#
# Format is
#
#   <branch-regex> <tag> <reference commit>
#
# The data is processed from top to bottom, the first matching line wins.

# maintenance is currently the branch for preparation of maintenance release 1.10.0
# so are any fix/... and improve/... branches
maintenance 1.10.0 cd955e9a46782119b36cc22b8dea5652ebbf9774
fix/.* 1.10.0 cd955e9a46782119b36cc22b8dea5652ebbf9774
improve/.* 1.10.0 cd955e9a46782119b36cc22b8dea5652ebbf9774

# staging/bugfix is the branch for preparation of the 1.9.x bugfix releases
# so are any bug/... branches
staging/bugfix 1.9.4 506648c152681bf4b1416cf2b5aaf97d526ee752 pep440-dev
bug/.* 1.9.4 506648c152681bf4b1416cf2b5aaf97d526ee752 pep440-dev

# staging/maintenance is currently the branch for preparation of 1.10.0rc2
# so is regressionfix/...
staging/maintenance 1.10.0rc2 f1e7f3253cccfbc2cd2e445646fbc2d3b31250d1
regressionfix/.* 1.10.0rc2 f1e7f3253cccfbc2cd2e445646fbc2d3b31250d1

# staging/devel is currently inactive (but has the 1.4.1rc4 namespace)
staging/devel 1.4.1rc4 650d54d1885409fa1d411eb54b9e8c7ff428910f

# devel and dev/* are development branches and thus get resolved to 2.0.0.dev for now
devel 2.0.0 2da7aa358d950b4567aaab8f18d6b5779193e077
dev/* 2.0.0 2da7aa358d950b4567aaab8f18d6b5779193e077
feature/* 2.0.0 2da7aa358d950b4567aaab8f18d6b5779193e077
"""

# ---------------------------------------------------------------------------------------

package_root = os.path.dirname(os.path.realpath(__file__))
package_name = os.path.basename(package_root)

STATIC_FILE = "_static_version.py"

STATIC_FILE_TEMPLATE = """
# This file has been generated by _version.py.
version = "{version}"
branch = "{branch}"
revision = "{revision}"
""".strip()

FALLBACK = "0+unknown"
FALLBACK_WITH_SHA = "0+unknown.g{short}"
FALLBACK_DICT = {
    "version": FALLBACK,
    "branch": None,
    "revision": None,
}

PEP440_REGEX = re.compile(
    r"""
    ^\s*
    v?
    (?:
        (?:(?P<epoch>[0-9]+)!)?                           # epoch
        (?P<release>[0-9]+(?:\.[0-9]+)*)                  # release segment
        (?P<pre>                                          # pre-release
            [-_\.]?
            (?P<pre_l>(a|b|c|rc|alpha|beta|pre|preview))
            [-_\.]?
            (?P<pre_n>[0-9]+)?
        )?
        (?P<post>                                         # post release
            (?:-(?P<post_n1>[0-9]+))
            |
            (?:
                [-_\.]?
                (?P<post_l>post|rev|r)
                [-_\.]?
                (?P<post_n2>[0-9]+)?
            )
        )?
        (?P<dev>                                          # dev release
            [-_\.]?
            (?P<dev_l>dev)
            [-_\.]?
            (?P<dev_n>[0-9]+)?
        )?
    )
    (?:\+(?P<local>[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?       # local version
    \s*$
""",
    re.VERBOSE | re.IGNORECASE,
)
# Taken from the sources of packaging.version, https://github.com/pypa/packaging/blob/21.3/packaging/version.py#L225-L254

_verbose = False


def _git(*args, **kwargs):
    git = ["git"]
    if sys.platform == "win32":
        git = ["git.cmd", "git.exe"]

    cwd = kwargs.pop("cwd", None)
    if cwd is None:
        cwd = os.path.dirname(__file__)
    hide_stderr = kwargs.pop("hide_stderr", False)
    verbose = kwargs.pop("verbose", False)

    p = None
    for c in git:
        try:
            dispcmd = str([c] + list(args))
            if verbose:
                print("trying %s" % dispcmd)
            p = subprocess.Popen(
                [c] + list(args),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=(subprocess.PIPE if hide_stderr else None),
            )
            break
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                continue
            if verbose:
                print("unable to run %s" % dispcmd)
                print(e)
            return None
    else:
        if verbose:
            print(f"unable to find command, tried {git}")
        return None
    stdout = p.communicate()[0].strip().decode()
    if p.returncode != 0:
        if verbose:
            print("unable to run %s (error)" % dispcmd)
        return None
    return stdout


def _get_long():
    return _git("rev-parse", "HEAD")


def _get_short():
    return _git("rev-parse", "--short", "HEAD")


def _get_tag():
    return _git("describe", "--tags", "--abbrev=0", "--always")


def _get_branch():
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def _get_dirty():
    describe = _git("describe", "--tags", "--dirty", "--always")
    return describe is None or describe.endswith("-dirty")


def _get_distance(ref):
    distance = _git("rev-list", f"{ref}..HEAD", "--count")
    if distance is None:
        return None
    try:
        return int(distance)
    except Exception:
        return None


def _parse_branch_versions():
    # parses rules for branches with virtual tags as defined in BRANCH_VERSIONS
    if not BRANCH_VERSIONS:
        return []

    import re

    branch_versions = []
    for line in BRANCH_VERSIONS.splitlines():
        if "#" in line:
            line = line[: line.index("#")]
        line = line.strip()
        if not line:
            continue

        try:
            split_line = list(map(lambda x: x.strip(), line.split()))
            if not len(split_line):
                continue
            if len(split_line) != 3:
                continue

            matcher = re.compile(split_line[0])
            branch_versions.append([matcher, split_line[1], split_line[2]])
        except Exception:
            break
    return branch_versions


def _validate_version(version):
    # validates a version string against PEP440
    return PEP440_REGEX.search(version) is not None


def _get_data_from_git():
    # retrieves version info from git checkout, taking virtual tags into account
    branch = _get_branch()
    if _verbose:
        print(f"Branch: {branch}")

    is_dirty = _get_dirty()
    if _verbose:
        print(f"Dirty:  {is_dirty}")  # noqa: E241

    sha = _get_long()
    if _verbose:
        print(f"SHA:    {sha}")  # noqa: E241

    short = _get_short()
    if _verbose:
        print(f"Short:  {short}")  # noqa: E241

    tag = _get_tag()
    distance = _get_distance(tag)
    template = "{tag}"
    dirty = "+g{short}.dirty"

    if branch is not None:
        lookup = _parse_branch_versions()
        for matcher, virtual_tag, ref_commit in lookup:
            if not matcher.match(branch):
                continue

            tag = virtual_tag
            distance = _get_distance(ref_commit)
            template = "{tag}.dev{distance}+g{short}"
            dirty = ".dirty"
            break

    if is_dirty:
        template += dirty

    vars = {
        "tag": tag,
        "distance": distance,
        "full": sha,
        "short": short,
    }

    if any([vars[x] is None and "{" + x + "}" in template for x in vars]):
        if short is None:
            template = FALLBACK
        else:
            template = FALLBACK_WITH_SHA
        if is_dirty:
            template += ".dirty"

    version = template.format(**vars)
    if not _validate_version(version):
        return None
    return {
        "version": version,
        "branch": branch,
        "revision": sha,
    }


def _get_data_from_static_file():
    # retrieves version info from _static_version.py
    data = {}
    with open(os.path.join(package_root, STATIC_FILE)) as f:
        exec(f.read(), {}, data)
    if data["version"] == "__use_git__":
        return None
    if not _validate_version(data["version"]):
        return None
    return data


def _get_data_from_keywords():
    # retrieves version info from expanded git keywords
    git_refnames = "$Format:%d$"
    git_full = "$Format:%H$"
    if git_refnames.startswith("$Format") or git_full.startswith("$Format"):
        # keywords not expanded, method not applicable
        return None

    refs = {
        r.strip()[8:] if r.strip().startswith("HEAD -> ") else r.strip()
        for r in git_refnames.strip().strip("()").split(",")
    }

    tags = {r[5:] for r in refs if r.startswith("tag: ")}
    if not tags:
        tags = {r for r in refs if re.search(r"\d", r)}
    tag = sorted(tags)[0] if tags else None

    branches = [
        r
        for r in refs
        if not r.startswith("tag: ") and r != "HEAD" and not r.startswith("refs/")
    ]
    branch = branches[0] if branches else None

    if tag is None:
        template = FALLBACK_WITH_SHA
    else:
        template = "{tag}"

    version = template.format(short=git_full[:8], tag=tag)
    if not _validate_version(version):
        return None

    return {
        "version": version,
        "branch": branch,
        "revision": git_full,
    }


def _write_static_file(path, data=None):
    # writes version data to _static_version.py
    if data is None:
        data = get_data()

    try:
        os.remove(path)
    except OSError:
        pass

    with open(path, "w") as f:
        f.write(STATIC_FILE_TEMPLATE.format(**data))


def get_data():
    # returns version data
    for method in (
        _get_data_from_static_file,
        _get_data_from_keywords,
        _get_data_from_git,
    ):
        data = method()
        if data is not None:
            return data

    return FALLBACK_DICT


def get_cmdclass(pkg_source_path):
    from setuptools import Command
    from setuptools.command.build_py import build_py as build_py_orig
    from setuptools.command.sdist import sdist as sdist_orig

    class _build_py(build_py_orig):
        def run(self):
            super().run()

            src_marker = "src" + os.path.sep
            if pkg_source_path.startswith(src_marker):
                path = pkg_source_path[len(src_marker) :]
            else:
                path = pkg_source_path

            _write_static_file(os.path.join(self.build_lib, path, STATIC_FILE))

    class _sdist(sdist_orig):
        def make_release_tree(self, base_dir, files):
            super().make_release_tree(base_dir, files)

            _write_static_file(os.path.join(base_dir, pkg_source_path, STATIC_FILE))

    class version(Command):
        description = "prints the version"
        user_options = []

        def initialize_options(self):
            pass

        def finalize_options(self):
            pass

        def run(self):
            print(get_data()["version"])

    return dict(sdist=_sdist, build_py=_build_py, version=version)


if __name__ == "__main__":
    _verbose = True
    print(get_data()["version"])
