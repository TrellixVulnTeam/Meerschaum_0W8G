#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
Functions for managing packages and virtual environments reside here.
"""

from __future__ import annotations
import importlib, os, pathlib
from meerschaum.utils.typing import Any, List, SuccessTuple, Optional, Union
from meerschaum.utils.threading import Lock, RLock

from meerschaum.utils.packages._packages import packages, all_packages
from meerschaum.utils.warnings import warn, error

_import_module = importlib.import_module
_import_hook_venv = None
active_venvs = set()
_locks = {
    'active_venvs': RLock(),
    'sys.path': RLock(),
}
_checked_for_updates = set()

def import_module(
        name: str,
        venv: Optional[str] = None,
        check_update: bool = True,
        check_pypi: bool = False,
        install: bool = True,
        split: bool = True,
        warn: bool = True,
        color: bool = True,
        debug: bool = False,
        deactivate: bool = True,
    ) -> Union['ModuleType', None]:
    """
    Manually import a module from a virtual environment (or the base environment).
    """
    if venv is None:
        try:
            return _import_module(name)
        except ModuleNotFoundError:
            return None
    if debug:
        from meerschaum.utils.debug import dprint
    from meerschaum.utils.warnings import warn as warn_function
    root_name = name.split('.')[0] if split else name
    install_name = all_packages.get(root_name, root_name)
    venv_path = pathlib.Path(venv_target_path(venv))
    mod_path = venv_path
    for _dir in name.split('.')[:-1]:
        mod_path = mod_path / _dir
    root_path = venv_path / root_name
    root_path = (
        (venv_path / root_name / '__init__.py') if (venv_path / root_name / '__init__.py').exists()
        else venv_path / (root_name + '.py')
    )

    possible_end_module_filename = name.split('.')[-1] + '.py'
    try:
        mod_path = (
            (mod_path / possible_end_module_filename)
            if possible_end_module_filename in os.listdir(mod_path)
            else (
                mod_path / name.split('.')[-1] / '__init__.py'
            )
        )
    except Exception as e:
        mod_path = None

    spec = (
        importlib.util.find_spec(name) if mod_path is None or not mod_path.exists()
        else importlib.util.spec_from_file_location(name, str(mod_path))
    )
    root_spec = (
        importlib.util.find_spec(root_name) if not root_path.exists()
        else importlib.util.spec_from_file_location(root_name, str(root_path))
    )


    ### Check for updates before importing.
    _version = (
        determine_version(pathlib.Path(root_spec.origin), name=root_name, debug=debug)
        if root_spec.origin is not None else None
    )
    #  print(root_name, _version, mod_path, root_path)
    #  input()

    if debug:
        dprint(f'root_name: {root_name}', color=color)
    if _version is not None:
        if debug:
            dprint(f'_version: {_version}', color=color)
        if check_update:
            if need_update(
                None, name=name, version=_version, split=split,
                check_pypi=check_pypi, debug=debug
            ):
                if install:
                    if not pip_install(
                        root_name,
                        venv = venv,
                        split = False,
                        deactivate = False,
                        check_update = check_update,
                        color = color,
                        debug = debug
                    ) and warn:
                        warn_function(
                            f"There's an update available for '{install_name}', " +
                            "but it failed to install. " +
                            "Try install via Meershaum with `install packages '{install_name}'`.",
                            ImportWarning,
                            stacklevel = 3,
                            color = False,
                        )
                elif warn:
                    warn_function(
                        f"There's an update available for '{root_name}'.",
                        stack = False,
                        color = False,
                    )
                spec = (
                    importlib.util.find_spec(name) if mod_path is None or not mod_path.exists()
                    else importlib.util.spec_from_file_location(name, str(mod_path))
                )


    if spec is None:
        try:
            mod = _import_module(name)
        except Exception as e:
            mod = None
        return mod

    if venv is not None:
        activate_venv(venv)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod = _import_module(name)
    if deactivate and venv is not None:
        deactivate_venv(venv)
    return mod


def determine_version(
        path: pathlib.Path,
        name: Optional[str] = None,
        debug: bool = False,
    ) -> Union[str, None]:
    """
    Determine the `__version__` string without importing a module.
    NOTE: This can only determine the __version__ of the package root!

    :param path:
        The file path of the module.
    """
    if debug:
        from meerschaum.utils.debug import dprint
    if name is None:
        name = path.parent.stem if path.stem == '__init__' else path.stem
    spec = importlib.util.spec_from_file_location(name, str(path))
    _version_directly_set = False
    _version_imported_as = False
    _version_line = None
    with open(path, 'r') as f:
        for line in f.readlines():
            #  print(line, end='')

            ### Check if __version__ was directly set.
            if '__version__=' in line.replace(' ', ''):
                _version_line = line
                _version_directly_set = True

            ### Check if __version__ was imported from somewhere else.
            elif ('from' in line and 'import' in line and '__version__' in line):
                _version_line = line
                _version_directly_set = False
                _version_imported_as = ('as__version__' in line.replace(' ', ''))

    ### If we've found a line where __version__ is set,
    ### determine whether it's set directly or imported.
    _version = None
    if _version_line is not None:
        if _version_directly_set:
            _l = _version_line.replace('__version__', '_tmpversion')
            try:
                exec(_l, globals())
            except Exception as e:
                ### The version could not be parsed.
                return None
            _version = _tmpversion
        else:
            _version_module_name = _version_line.split(' ')[1]
            _version_sub_dirs = _version_module_name.split('.')[1:]
            _version_module_path = pathlib.Path(
                (path.parent if path.stem == '__init__' else path)
            )
            for _dir in _version_sub_dirs[:-1]:
                _version_module_path = _version_module_path / _dir
            possible_end_module_filename = _version_module_name.split('.')[-1] + '.py'
            try:
                _version_module_path = (
                    (_version_module_path / possible_end_module_filename)
                    if possible_end_module_filename in os.listdir(_version_module_path)
                    else (
                        _version_module_path / _version_module_name.split('.')[-1] / '__init__.py'
                    )
                )
            except Exception as e:
                _version_module_path = None

            if debug:
                dprint(f"_version_module_path: {_version_module_path}", color=False)
            if _version_module_path is None:
                return None

            return determine_version(_version_module_path, name=_version_module_name, debug=debug)

    return _version


def need_update(
        package: 'ModuleType',
        name: Optional[str] = None,
        version: Optional[str] = None,
        check_pypi: bool = False,
        split: bool = True,
        color: bool = True,
        debug: bool = False,
    ) -> bool:
    """
    Check if a Meerschaum dependency needs an update.
    Returns a bool for whether or not a package needs to be updated.

    :param package:
        The module of the package to be updated.

    :param check_pypi:
        If `True`, check pypi.org for updates.
        Defaults to `False`.

    :param split:
        If `True`, split the module's name on periods to detrive the root name.
        DEfaults to `True`.

    :param color:
        If `True`, format debug output.
        Defaults to `True`.

    :param debug:
        Verbosity toggle.
    """
    if debug:
        from meerschaum.utils.debug import dprint
    import re
    root_name = (
        package.__name__.split('.')[0] if split else package.__name__
    ) if name is None else (
        name.split('.')[0] if split else name
    )
    install_name = all_packages.get(root_name, root_name)
    if install_name in _checked_for_updates:
        return False
    _checked_for_updates.add(install_name)

    _install_no_version = re.split('[=<>,! ]', install_name)[0]
    if debug:
        dprint(f"_install_no_version: {_install_no_version}", color=color)
    required_version = install_name.replace(_install_no_version, '')

    ### No minimum version was specified, and we're not going to check PyPI.
    if not required_version and not check_pypi:
        return False

    if debug:
        dprint(f"required_version: {required_version}", color=color)

    try:
        version = package.__version__ if version is None else version
    except Exception as e:
        if debug:
            dprint("No version could be determined from the installed package.", color=color)
        return False

    packaging_version = attempt_import('packaging.version', check_update=False, lazy=False)

    ### Get semver if necessary
    if required_version:
        semver = attempt_import('semver', check_update=False, lazy=False)
        try:
            match = semver.match
        except Exception as e:
            ### Something funky is going on with semver.
            match = None
        if match is None:
            error("Please reinstall the package `semver`.")


    if check_pypi:
        ### Check PyPI for updates
        update_checker = attempt_import('update_checker', lazy=False, check_update=False)
        checker = update_checker.UpdateChecker()
        result = checker.check(_install_no_version, version)
    else:
        ### Skip PyPI and assume we can't be sure.
        result = None

    ### Compare PyPI's version with our own.
    if result is not None:
        if debug:
            dprint(f"Available version: {result.available_version}", color=color)
            dprint(f"Required version: {required_version}", color=color)

        ### We have a result from PyPI and a stated required version.
        if required_version:
            try:
                return match(result.available_version, required_version)
            except Exception as e:
                if debug:
                    dprint(f"Failed to match versions with exception:\n{e}", color=color)
                return False

        ### If `check_pypi` and we don't have a required version, check if PyPI's version
        ### is newer than the installed version.
        else:
            return (
                packaging_version.parse(result.available_version) > 
                packaging_version.parse(version)
            )

    ### We might be depending on a prerelease.
    ### Sanity check that the required version is not greater than the installed version.
    try:
        return not match(version, required_version) if required_version else False
    except Exception as e:
        if debug:
            dprint(e)
        return False
    try:
        return (
            packaging_version.parse(version) > 
            packaging_version.parse(required_version)
        )
    except Exception as e:
        if debug:
            dprint(e)
        return False

def is_venv_active(
        venv: str = 'mrsm',
        color : bool = True,
        debug: bool = False
    ) -> bool:
    """
    Check if a virtual environment is active
    """
    if venv is None:
        return False
    if debug:
        from meerschaum.utils.debug import dprint
        dprint(f"Checking if virtual environment '{venv}' is active.", color=color)
    return venv in active_venvs

def deactivate_venv(
        venv: str = 'mrsm',
        color : bool = True,
        debug: bool = False
    ) -> bool:
    """
    Remove a virtual environment from sys.path (if it's been activated).
    """
    import sys
    global active_venvs

    if venv is None:
        return True

    if debug:
        from meerschaum.utils.debug import dprint
        dprint(f"Deactivating virtual environment '{venv}'...", color=color)

    if venv in active_venvs:
        _locks['active_venvs'].acquire()
        active_venvs.remove(venv)
        _locks['active_venvs'].release()

    if sys.path is None:
        return False

    target = venv_target_path(venv, debug=debug)
    _locks['sys.path'].acquire()
    if str(target) in sys.path:
        sys.path.remove(str(target))
    _locks['sys.path'].release()

    if debug:
        dprint(f'sys.path: {sys.path}', color=color)

    return True

def activate_venv(
        venv: str = 'mrsm',
        color : bool = True,
        debug: bool = False
    ) -> bool:
    """
    Create a virtual environment (if it doesn't exist) and add it to sys.path if necessary.
    """
    global active_venvs
    if venv in active_venvs or venv is None:
        return True
    if debug:
        from meerschaum.utils.debug import dprint
    import sys, os, platform
    from meerschaum.config._paths import VIRTENV_RESOURCES_PATH
    _venv = None
    virtualenv = attempt_import(
        'virtualenv', venv=None, lazy=False, install=True, warn=False, debug=debug, color=False,
        check_update=False,
    )
    if virtualenv is None:
        try:
            import ensurepip
            import venv as _venv
            virtualenv = None
        except ImportError:
            _venv = None
    if virtualenv is None and _venv is None:
        print(
            "Failed to import virtualenv! "
            + "Please install virtualenv via pip then restart Meerschaum."
        )
        sys.exit(1)
    venv_path = VIRTENV_RESOURCES_PATH / venv
    bin_path = pathlib.Path(
        venv_path,
        ('bin' if platform.system() != 'Windows' else "Scripts")
    )
    if not venv_path.exists():
        if _venv is not None:
            _venv.create(
                venv_path,
                system_site_packages = False,
                with_pip = True,
                symlinks = (platform.system() != 'Windows'),
            )
        else:
            virtualenv.cli_run([str(venv_path), '--download', '--system-site-packages'])

    old_cwd = pathlib.Path(os.getcwd())
    os.chdir(VIRTENV_RESOURCES_PATH)
    try:
        if debug:
            dprint(f"Activating virtual environment '{venv}'...", color=color)
        _locks['active_venvs'].acquire()
        active_venvs.add(venv)
    except Exception:
        pass
    finally:
        _locks['active_venvs'].release()
        os.chdir(old_cwd)

    ### override built-in import with attempt_import
    #  install_import_hook(venv, debug=debug)
    target = venv_target_path(venv, debug=debug)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    if debug:
        dprint(f'sys.path: {sys.path}', color=color)
    #  print(sys.path)
    return True

def venv_exec(code: str, venv: str = 'mrsm', debug: bool = False) -> bool:
    """
    Execute Python code in a subprocess via a virtual environment's interpeter.

    Return True if the code successfully executes, False on failure.
    """
    import subprocess, sys, platform, os
    from meerschaum.config._paths import VIRTENV_RESOURCES_PATH
    from meerschaum.utils.debug import dprint
    executable = (
        sys.executable if venv is None
        else os.path.join(
            VIRTENV_RESOURCES_PATH, venv, (
                'bin' if platform.system() != 'Windows' else 'Scripts'
            ), 'python'
        )
    )
    cmd_list = [executable, '-c', code]
    if debug:
        dprint(str(cmd_list))
    return subprocess.call(cmd_list) == 0

def get_pip(debug : bool = False) -> bool:
    """
    Download and run the get-pip.py script.
    """
    import sys, subprocess
    from meerschaum.utils.misc import wget
    from meerschaum.config._paths import CACHE_RESOURCES_PATH
    from meerschaum.config.static import _static_config
    url = _static_config()['system']['urls']['get-pip.py']
    dest = CACHE_RESOURCES_PATH / 'get-pip.py'
    try:
        wget(url, dest, color=False, debug=debug)
    except Exception as e:
        print(f"Failed to fetch pip from '{url}'. Please install pip and restart Meerschaum.") 
        sys.exit(1)
    cmd_list = [sys.executable, str(dest)] 
    return subprocess.call(cmd_list) == 0

def pip_install(
        *packages: List[str],
        args: Optional[List[str]] = None,
        venv: str = 'mrsm',
        deactivate: bool = True,
        split : bool = False,
        check_update: bool = True,
        check_pypi: bool = True,
        check_wheel : bool = True,
        _uninstall : bool = False,
        color : bool = True,
        debug: bool = False
    ) -> bool:
    """
    Install pip packages
    """
    from meerschaum.config.static import _static_config
    if args is None:
        args = ['--upgrade'] if not _uninstall else []
    if color:
        try:
            from meerschaum.utils.formatting import ANSI, UNICODE
        except ImportError:
            ANSI, UNICODE = False, False
    else:
        ANSI, UNICODE = False, False
    if check_wheel:
        try:
            import wheel
            have_wheel = True
        except ImportError as e:
            have_wheel = False
    _args = list(args)
    try:
        if venv is not None:
            activate_venv(venv=venv, color=color, debug=debug)
        import pip
        have_pip = True
        if venv is not None and deactivate:
            deactivate_venv(venv=venv, debug=debug, color=color)
    except ImportError:
        have_pip = False
    if not have_pip:
        try:
            import ensurepip
        except ImportError:
            ensurepip = None
        if ensurepip is None:
            if not get_pip(debug=debug):
                import sys
                print(
                    "Failed to import pip and ensurepip. " +
                    "Please install pip and restart Meerschaum.\n\n" +
                    "You can find instructions on installing pip here: " +
                    "https://pip.pypa.io/en/stable/installing/"
                )
                sys.exit(1)
        else:
            ensurepip.bootstrap(upgrade=True, )
        import pip
    if venv is not None:
        activate_venv(venv=venv, debug=debug, color=color)
        if '--ignore-installed' not in args and '-I' not in _args and not _uninstall:
            _args += ['--ignore-installed']

    if check_update and need_update(pip, check_pypi=check_pypi, debug=debug) and not _uninstall:
        _args.append('pip')
    _args = (['install'] if not _uninstall else ['uninstall']) + _args

    if check_wheel and not _uninstall:
        if not have_wheel:
            _args.append('wheel')

    if not ANSI and '--no-color' not in _args:
        _args.append('--no-color')

    if '--no-warn-conflicts' not in _args and not _uninstall:
        _args.append('--no-warn-conflicts')

    if '--disable-pip-version-check' not in _args:
        _args.append('--disable-pip-version-check')

    if venv is not None and '--target' not in _args and '-t' not in _args and not _uninstall:
        _args += ['--target', venv_target_path(venv, debug=debug)]
    elif (
        '--target' not in _args
            and '-t' not in _args
            and os.environ.get(
                _static_config()['environment']['runtime'], None
            ) != 'docker'
            and not inside_venv()
            and not _uninstall
    ):
        _args += ['--user']
    if '--progress-bar' in _args:
        _args.remove('--progress-bar')
    if UNICODE and not _uninstall:
        _args += ['--progress-bar', 'pretty']
    elif not _uninstall:
        _args += ['--progress-bar', 'ascii']
    if debug:
        if '-v' not in _args or '-vv' not in _args or '-vvv' not in _args:
            pass
    else:
        if '-q' not in _args or '-qq' not in _args or '-qqq' not in _args:
            pass

    _packages = []
    for p in packages:
        root_name = p.split('.')[0] if split else p
        install_name = all_packages.get(root_name, root_name)
        _packages.append(install_name)

    msg = "Installing packages:" if not _uninstall else "Uninstalling packages:"
    for p in _packages:
        msg += f'\n  - {p}'
    print(msg)

    success = run_python_package('pip', _args + _packages, venv=venv, debug=debug) == 0
    if venv is not None and deactivate:
        deactivate_venv(venv=venv, debug=debug, color=color)
    msg = (
        "Successfully " + ('un' if _uninstall else '') + "installed packages." if success 
        else "Failed to " + ('un' if _uninstall else '') + "install packages."
    )
    print(msg)
    if debug:
        print('pip ' + ('un' if _uninstall else '') + 'install returned:', success)
    return success

def pip_uninstall(
        *args, **kw
    ) -> bool:
    """
    Uninstall Python packages.
    """
    return pip_install(*args, _uninstall=True, **{k: v for k, v in kw.items() if k != '_uninstall'})

def run_python_package(
        package_name : str,
        args : Optional[List[str]] = None,
        venv : Optional[str] = None,
        cwd : Optional[str] = None,
        foreground : bool = False,
        debug : bool = False,
        **kw : Any,
    ) -> Union[int, subprocess.Popen]:
    """
    Runs an installed python package.
    E.g. Translates to `/usr/bin/python -m [package]`

    :param package_name:
        The Python module to be executed.

    :param args:
        Additional command line arguments to be appended after `-m [package]`.
        Defaults to `None`.

    :param venv:
        If specified, execute the Python interpreter from a virtual environment.
        Defaults to `None`.

    :param cwd:
        If specified, change directories before starting the process.
        Defaults to `None`.

    :param foreground:
        If `True`, start the subprocess as a foreground process.
        Defaults to `False`.

    :param kw:
        Additional keyword arguments to pass to `meerschaum.utils.process.run_process()`
        and by extension `subprocess.Popen()`.
    """
    import sys, platform
    from subprocess import call
    from meerschaum.config._paths import VIRTENV_RESOURCES_PATH
    from meerschaum.utils.process import run_process
    from meerschaum.utils.warnings import warn
    if args is None:
        args = []
    old_cwd = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    executable = (
        sys.executable if venv is None
        else os.path.join(
            VIRTENV_RESOURCES_PATH, venv, (
                'bin' if platform.system() != 'Windows' else 'Scripts'
            ), ('python' + ('.exe' if platform.system() == 'Windows' else ''))
        )
    )
    command = [executable, '-m', str(package_name)] + [str(a) for a in args]
    import traceback
    if debug:
        print(command, file=sys.stderr)
    try:
        rc = run_process(command, foreground=foreground, **kw)
    except Exception as e:
        print(traceback.format_exc(e))
        warn(e, color=False)
        rc = call(command)
    except KeyboardInterrupt:
        rc = 1
    os.chdir(old_cwd)
    return rc

def attempt_import(
        *names: List[str],
        lazy: bool = True,
        warn: bool = True,
        install: bool = True,
        venv: str = 'mrsm',
        precheck: bool = True,
        split: bool = True,
        check_update: bool = False,
        check_pypi: bool = False,
        deactivate: bool = True,
        color: bool = True,
        debug: bool = False
    ) -> Union['ModuleType', Tuple['ModuleType']]:
    """
    Raise a warning if packages are not installed; otherwise import and return modules.
    If lazy = True, return lazy-imported modules.

    Returns tuple of modules if multiple names are provided, else returns one module.

    Examples:

        ```
        >>> pandas, sqlalchemy = attempt_import('pandas', 'sqlalchemy')
        >>> pandas = attempt_import('pandas')

        ```

    :param names:
        The packages to be imported.

    :param lazy:
        If True, lazily load packages.
        Defaults to False.

    :param warn:
        If True, raise a warning if a package cannot be imported.
        Defaults to True.

    :param install:
        If True, attempt to install a missing package into the designated virtual environment.
        If `check_update` is True, install updates if available.
        Defaults to True.

    :param venv:
        The virtual environment in which to search for packages and to install packages into.
        Defaults to 'mrsm'.

    :param precheck:
        If True, attempt to find module before importing (necessary for checking if modules exist
        and retaining lazy imports), otherwise assume lazy is False.
        Defaults to True.        

    :param split:
        If True, split packages' names on '.'.
        Defaults to True.

    :param check_update:
        If `True` and `install` is `True`, install updates if the required minimum version
        does not match.
        Defaults to `False`.

    :param check_pypi:
        If `True` and `check_update` is `True`, check PyPI when determining whether
        an update is required.
        Defaults to `False`.
    """

    import importlib.util

    ### to prevent recursion, check if parent Meerschaum package is being imported
    if names == ('meerschaum',):
        return _import_module('meerschaum')

    if venv == 'mrsm' and _import_hook_venv is not None:
        if debug:
            print(f"Import hook for virtual environment '{_import_hook_venv}' is active.")
        venv = _import_hook_venv

    if venv is not None:
        _locks['sys.path'].acquire()
        activate_venv(venv=venv, color=color, debug=debug)
    _warnings = _import_module('meerschaum.utils.warnings')
    warn_function = _warnings.warn

    def do_import(_name: str, **kw) -> Union['ModuleType', None]:
        if venv is not None:
            activate_venv(venv=venv, debug=debug)
        ### determine the import method (lazy vs normal)
        from meerschaum.utils.misc import filter_keywords
        import_method = (import_module if check_update else _import_module) if not lazy else lazy_import
        try:
            mod = import_method(_name, **(filter_keywords(import_method, **kw)))
        except Exception as e:
            if warn:
                warn_function(
                    f"Failed to import module '{_name}'.\nException:\n{e}",
                    ImportWarning,
                    stacklevel = (5 if lazy else 4),
                    color = False,
                )
            mod = None
        if venv is not None:
            deactivate_venv(venv=venv, color=color, debug=debug)
        return mod

    modules = []
    for name in names:
        ### Enforce virtual environment (something is deactivating in the loop so check each pass).
        if venv is not None:
            activate_venv(debug=debug)
        ### Check if package is a declared dependency.
        root_name = name.split('.')[0] if split else name
        install_name = all_packages.get(root_name, None)
        if install_name is None:
            install_name = root_name
            if warn and root_name != 'plugins':
                warn_function(
                    f"Package '{root_name}' is not declared in meerschaum.utils.packages.",
                    ImportWarning,
                    stacklevel = 3,
                    color = False
                )

        ### Determine if the package exists.
        if precheck is False:
            found_module = (
                do_import(
                    name, debug=debug, warn=False, venv=venv, color=color,
                    check_update=False, check_pypi=False, deactivate=False,
                ) is not None
            )
        else:
            found_module = (
                venv_contains_package(name, venv=venv, debug=debug)
                or is_installed(name, venv=None)
            )

        if not found_module:
            if install:
                ### NOTE: pip_install deactivates venv, so deactivate must be False.
                if not pip_install(
                    root_name,
                    venv = venv,
                    deactivate = False,
                    split = False,
                    #  split = split,
                    check_update = check_update,
                    color = color,
                    debug = debug
                ) and warn:
                    warn_function(
                        f"Failed to install '{install_name}'.",
                        ImportWarning,
                        stacklevel = 3,
                        color = False, ### Color triggers a deactivate, so keep as False
                    )
            elif warn:
                ### Raise a warning if we can't find the package and install = False.
                warn_function(
                    (f"\n\nMissing package '{name}'; features will not work correctly. "
                     f"\n\nSet install=True when calling attempt_import.\n"),
                    ImportWarning,
                    stacklevel = 3,
                    color = False,
                )

        ### Do the import. Will be lazy if lazy=True.
        m = do_import(
            name, debug=debug, warn=warn, venv=venv, color=color,
            check_update=check_update, check_pypi=check_pypi, install=install,
        )
        modules.append(m)

    if venv is not None:
        _locks['sys.path'].release()
        if deactivate:
            deactivate_venv(venv=venv, debug=debug, color=color)

    modules = tuple(modules)
    if len(modules) == 1:
        return modules[0]
    return modules

def lazy_import(
        name: str,
        local_name: str = None,
        venv: Optional[str] = None,
        warn: bool = True, 
        deactivate: bool = True,
        check_update: bool = False,
        check_pypi: bool = False,
        debug : bool = False
    ) -> meerschaum.utils.packages.lazy_loader.LazyLoader:
    """
    Lazily import a package
    Based off the tensorflow LazyLoader implementation (Apache 2.0 License)
    """
    from meerschaum.utils.packages.lazy_loader import LazyLoader
    if local_name is None:
        local_name = name
    return LazyLoader(
        local_name,
        globals(),
        name,
        venv = venv,
        warn = warn,
        deactivate = deactivate,
        check_pypi = check_pypi,
        check_update = check_update,
        debug = debug
    )

def import_pandas(deactivate : bool = False, debug : bool = False, lazy : bool = False,  **kw) -> 'ModuleType':
    """
    Quality-of-life function to attempt to import the configured version of pandas.
    """
    import sys
    from meerschaum.config import get_config
    pandas_module_name = get_config('system', 'connectors', 'all', 'pandas', patch=True)
    ### NOTE: modin does NOT currently work!
    if pandas_module_name == 'modin':
        pandas_module_name = 'modin.pandas'

    activate_venv(venv='mrsm', debug=debug)
    pd = attempt_import(pandas_module_name, deactivate=deactivate, debug=debug, lazy=lazy, **kw)
    if deactivate:
        deactivate_venv(venv='mrsm', debug=debug)
    return pd

def import_rich(
        lazy: bool = True, deactivate : bool = False, debug : bool = False,
        **kw : Any
    ) -> 'ModuleType':
    """
    Quality of life function for importing rich.
    """
    from meerschaum.utils.formatting import ANSI, UNICODE
    if not ANSI and not UNICODE:
        return None

    activate_venv(venv='mrsm', debug=debug)

    ## need typing_extensions for `from rich import box`
    typing_extensions = attempt_import('typing_extensions', deactivate=deactivate, lazy=False)
    pygments = attempt_import('pygments', deactivate=deactivate, lazy=False)
    rich = attempt_import('rich', lazy=lazy, deactivate=deactivate, **kw)
    if deactivate:
        deactivate_venv(venv='mrsm', debug=debug)
    return rich

def _dash_less_than_2(**kw) -> bool:
    """
    Return a bool denoting whether the installed version of Dash is less than 2.0.0.
    """
    dash = attempt_import('dash')
    if dash is None:
        return None
    packaging_version = attempt_import('packaging.version', **kw)
    less_than_2 = (
        packaging_version.parse(dash.__version__) < 
        packaging_version.parse('2.0.0')
    )

def import_dcc(warn=False, **kw) -> 'ModuleType':
    """
    Import Dash Core Components (`dcc`).
    """
    return (
        attempt_import('dash_core_components', warn=warn, **kw)
        if _dash_less_than_2(warn=warn, **kw) else attempt_import('dash.dcc', warn=warn, **kw)
    )

def import_html(warn=False, **kw) -> 'ModuleType':
    """
    Import Dash HTML Components (`html`).
    """
    return (
        attempt_import('dash_html_components', warn=warn, **kw)
        if _dash_less_than_2(warn=warn, **kw) else attempt_import('dash.html', warn=warn, **kw)
    )


def get_modules_from_package(
        package: 'package',
        names: bool = False,
        recursive: bool = False,
        lazy: bool = False,
        modules_venvs: bool = False,
        debug: bool = False
    ):
    """
    Find and import all modules in a package.

    Returns: either list of modules or tuple of lists

    names = False (default) : modules
    names = True            : (__all__, modules)
    """
    from os.path import dirname, join, isfile, isdir, basename
    import glob

    pattern = '*' if recursive else '*.py'
    module_names = glob.glob(join(dirname(package.__file__), pattern), recursive=recursive)
    _all = [
        basename(f)[:-3] if isfile(f) else basename(f)
        for f in module_names
            if ((isfile(f) and f.endswith('.py')) or isdir(f))
               and not f.endswith('__init__.py')
               and not f.endswith('__pycache__')
    ]

    if debug:
        from meerschaum.utils.debug import dprint
        dprint(str(_all))
    modules = []
    for module_name in [package.__name__ + "." + mod_name for mod_name in _all]:
        ### there's probably a better way than a try: catch but it'll do for now
        try:
            ### if specified, activate the module's virtual environment before importing.
            ### NOTE: this only considers the filename, so two modules from different packages
            ### may end up sharing virtual environments.
            if modules_venvs:
                activate_venv(module_name.split('.')[-1], debug=debug)
            m = lazy_import(module_name, debug=debug) if lazy else _import_module(module_name)
            modules.append(m)
        except Exception as e:
            if debug:
                dprint(e)
        finally:
            if modules_venvs:
                deactivate_venv(module_name.split('.')[-1], debug=debug)
    if names:
        return _all, modules

    return modules

def import_children(
        package: Optional['ModuleType'] = None,
        package_name: Optional[str] = None,
        types : Optional[List[str]] = None,
        lazy: bool = True,
        recursive: bool = False,
        debug: bool = False
    ) -> List['ModuleType']:
    """
    Import all functions in a package to its __init__.
    Returns of list of modules.

    :param package:
        Package to import its functions into.
        If None (default), use parent.

    :param package_name:
        Name of package to import its functions into
        If None (default), use parent.

    :param types:
        Types of members to return.
        Default : ['method', 'builtin', 'class', 'function', 'package', 'module']

    """
    import sys, inspect

    if types is None:
        types = ['method', 'builtin', 'function', 'class', 'module']

    ### if package_name and package are None, use parent
    if package is None and package_name is None:
        package_name = inspect.stack()[1][0].f_globals['__name__']

    ### populate package or package_name from other other
    if package is None:
        package = sys.modules[package_name]
    elif package_name is None:
        package_name = package.__name__

    ### Set attributes in sys module version of package.
    ### Kinda like setting a dictionary
    ###   functions[name] = func
    modules = get_modules_from_package(package, recursive=recursive, lazy=lazy, debug=debug)
    _all, members = [], []
    objects = []
    for module in modules:
        _objects = []
        for ob in inspect.getmembers(module):
            for t in types:
                ### ob is a tuple of (name, object)
                if getattr(inspect, 'is' + t)(ob[1]):
                    _objects.append(ob)

        if 'module' in types:
            _objects.append((module.__name__.split('.')[0], module))
        objects += _objects
    for ob in objects:
        setattr(sys.modules[package_name], ob[0], ob[1])
        _all.append(ob[0])
        members.append(ob[1])

    if debug:
        from meerschaum.utils.debug import dprint
        dprint(str(_all))
    ### set __all__ for import *
    setattr(sys.modules[package_name], '__all__', _all)
    return members

def reload_package(
        package: str,
        lazy: bool = False,
        debug: bool = False,
        **kw: Any
    ) -> 'ModuleType':
    """
    Recursively load a package's subpackages, even if they were not previously loaded
    """
    import pydoc
    if isinstance(package, str):
        package_name = package
    else:
        try:
            package_name = package.__name__
        except Exception as e:
            package_name = str(package)
    return pydoc.safeimport(package_name, forceload=1)

def is_installed(
        name: str,
        venv : Optional[str] = None,
    ) -> bool:
    """
    Check whether a package is installed.
    name : str
        Name of the package in question
    """
    import importlib.util
    if venv is not None:
        activate_venv(venv=venv)
    found = importlib.util.find_spec(name) is not None
    if venv is None:
        return found
    mod = attempt_import(name, venv=venv)
    found = (venv == package_venv(mod))
    deactivate_venv(venv=venv)
    return found

def venv_contains_package(
        name: str, venv: Optional[str] = None, debug: bool = False,
    ) -> bool:
    """
    Search the contents of a virtual environment for a package.
    """
    import os
    if venv is None:
        return is_installed(name, venv=venv)
    vtp = venv_target_path(venv)
    if not vtp.exists():
        return False
    return name.split('.')[0] in os.listdir(vtp)

def venv_target_path(venv : str, debug : bool = False) -> pathlib.Path:
    """
    Return a virtual environment's site-package path.
    """
    import os, sys, platform
    from meerschaum.config._paths import VIRTENV_RESOURCES_PATH

    venv_root_path = str(os.path.join(VIRTENV_RESOURCES_PATH, venv))
    target_path = venv_root_path

    ### Ensure 'lib' or 'Lib' exists.
    lib = 'lib' if platform.system() != 'Windows' else 'Lib'
    if lib not in os.listdir(venv_root_path):
        print(f"Failed to find lib directory for virtual environment '{venv}'.")
        sys.exit(1)
    target_path = os.path.join(target_path, lib)

    ### Check if a 'python3.x' folder exists.
    python_folder = 'python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor)
    if python_folder in os.listdir(target_path): ### Linux
        target_path = os.path.join(target_path, python_folder)

    ### Ensure 'site-packages' exists.
    if 'site-packages' in os.listdir(target_path): ### Windows
        target_path = os.path.join(target_path, 'site-packages')
    else:
        from meerschaum.config._paths import set_root
        import traceback
        traceback.print_stack()
        print(f"Failed to find site-packages directory for virtual environment '{venv}'.")
        sys.exit(1)

    if debug:
        print(f"Target path for virtual environment '{venv}':\n" + str(target_path))
    return pathlib.Path(target_path)

def package_venv(package : 'ModuleType') -> Optional[str]:
    """
    Inspect a package and return the virtual environment in which it presides.
    """
    from meerschaum.config._paths import VIRTENV_RESOURCES_PATH
    if str(VIRTENV_RESOURCES_PATH) not in package.__file__:
        return None
    return package.__file__.split(str(VIRTENV_RESOURCES_PATH))[1].split(os.path.sep)[1]

def inside_venv() -> bool:
    """
    Determine whether current Python interpreter is running inside a virtual environment.
    """
    import sys
    return (
        hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix')
                and sys.base_prefix != sys.prefix
        )
    )
