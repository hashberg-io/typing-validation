"""
A script to generate .rst files for API documentation.
"""

import glob
import importlib
import inspect
import json
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, TypeAliasType


def _list_package_contents(pkg_name: str) -> list[str]:
    modules = [pkg_name]
    for submod in pkgutil.iter_modules([pkg_name.replace(".", "/")]):
        submod_fullname = pkg_name + "." + submod.name
        if submod.ispkg:
            for subsubmod_name in _list_package_contents(submod_fullname):
                modules.append(subsubmod_name)
        else:
            modules.append(submod_fullname)
    return modules


SPECIAL_CLASS_MEMBERS_REL = (
    "__eq__",
    "__gt__",
    "__ge__",
    "__lt__",
    "__le__",
    "__ne__",
)
SPECIAL_CLASS_MEMBERS_UNOP = (
    "__abs__",
    "__not__",
    "__inv__",
    "__invert__",
    "__neg__",
    "__pos__",
)
SPECIAL_CLASS_MEMBERS_BINOP = (
    "__add__",
    "__and__",
    "__concat__",
    "__floordiv__",
    "__lshift__",
    "__mod__",
    "__mul__",
    "__matmul__",
    "__or__",
    "__pow__",
    "__rshift__",
    "__sub__",
    "__truediv__",
    "__xor__",
)
SPECIAL_CLASS_MEMBERS_BINOP_I = tuple(
    f"__i{name[2:]}" for name in SPECIAL_CLASS_MEMBERS_BINOP
)
SPECIAL_CLASS_MEMBERS_BINOP_R = tuple(
    f"__r{name[2:]}" for name in SPECIAL_CLASS_MEMBERS_BINOP
)
SPECIAL_CLASS_MEMBERS_CAST = (
    "__bool__",
    "__int__",
    "__float__",
    "__complex__",
    "__bytes__",
    "__str__",
)
SPECIAL_CLASS_MEMBERS_OTHER = (
    "__init__",
    "__new__",
    "__call__",
    "__repr__",
    "__index__",
    "__contains__",
    "__delitem__",
    "__getitem__",
    "__setitem__",
    "__getattr__",
    "__setattr__",
    "__delattr__",
    "__set_name__",
    "__set__",
    "__get__",
)
SPECIAL_CLASS_MEMBERS = (
    SPECIAL_CLASS_MEMBERS_REL
    + SPECIAL_CLASS_MEMBERS_UNOP
    + SPECIAL_CLASS_MEMBERS_BINOP
    + SPECIAL_CLASS_MEMBERS_BINOP_I
    + SPECIAL_CLASS_MEMBERS_BINOP_R
    + SPECIAL_CLASS_MEMBERS_CAST
    + SPECIAL_CLASS_MEMBERS_OTHER
)


STRUCTURE_HELP = """Expected a 'make-api.json' file, with the following structure:
{
    "pkg_name": str,
    "pkg_path": str,
    "apidocs_folder": str,
    "toc_filename": str | None,
    "type_alias_dict_filename": str | None,
    "include_members": dict[str, list[str]],
    "type_aliases": dict[str, list[str]],
    "exclude_members": dict[str, list[str]],
    "include_modules": list[str],
    "exclude_modules": list[str],
    "member_fullnames": dict[str, dict[str, str]],
    "special_class_members": dict[str, list[str]],
    "manual_doc": dict[str, list[str]],
}

The keys "pkg_name", "pkg_path" and "apidocs_folder" are required; every other
key is optional. Set "toc_filename" to null to skip generating a table of
contents file.
"""


class ConfigError(Exception):
    """Raised when the 'make-api.json' configuration fails validation."""


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_opt_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_str_to_str_list(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_str_list(item) for key, item in value.items()
    )


def _is_str_to_str_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(item, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in item.items())
        for key, item in value.items()
    )


# For each key: whether it is required, the predicate validating its value, and a
# human-readable description of the expected value used in error messages.
_SCHEMA: dict[str, tuple[bool, Callable[[Any], bool], str]] = {
    "pkg_name": (True, _is_str, "a string"),
    "pkg_path": (True, _is_str, "a string"),
    "apidocs_folder": (True, _is_str, "a string"),
    "toc_filename": (False, _is_opt_str, "a string or null"),
    "type_alias_dict_filename": (False, _is_opt_str, "a string or null"),
    "include_members": (
        False,
        _is_str_to_str_list,
        "a mapping of strings to lists of strings",
    ),
    "type_aliases": (
        False,
        _is_str_to_str_list,
        "a mapping of strings to lists of strings",
    ),
    "exclude_members": (
        False,
        _is_str_to_str_list,
        "a mapping of strings to lists of strings",
    ),
    "include_modules": (False, _is_str_list, "a list of strings"),
    "exclude_modules": (False, _is_str_list, "a list of strings"),
    "member_fullnames": (
        False,
        _is_str_to_str_dict,
        "a mapping of strings to mappings of strings to strings",
    ),
    "special_class_members": (
        False,
        _is_str_to_str_list,
        "a mapping of strings to lists of strings",
    ),
    "manual_doc": (
        False,
        _is_str_to_str_list,
        "a mapping of strings to lists of strings",
    ),
}


@dataclass(frozen=True)
class MakeApiConfig:
    """Validated contents of a 'make-api.json' configuration file."""

    pkg_name: str
    pkg_path: str
    apidocs_folder: str
    toc_filename: str | None = None
    type_alias_dict_filename: str | None = None
    include_members: dict[str, list[str]] = field(default_factory=dict)
    type_aliases: dict[str, list[str]] = field(default_factory=dict)
    exclude_members: dict[str, list[str]] = field(default_factory=dict)
    include_modules: list[str] = field(default_factory=list)
    exclude_modules: list[str] = field(default_factory=list)
    member_fullnames: dict[str, dict[str, str]] = field(default_factory=dict)
    special_class_members: dict[str, list[str]] = field(default_factory=dict)
    manual_doc: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any) -> "MakeApiConfig":
        """
        Validates a decoded JSON object and builds a :class:`MakeApiConfig`.

        Raises :class:`ConfigError`, listing every problem found, if the data
        does not match the expected schema.
        """
        if not isinstance(data, dict):
            raise ConfigError(
                "Expected the make-api configuration to be a JSON object, got "
                f"{type(data).__name__}.\n\n{STRUCTURE_HELP}"
            )
        errors: list[str] = []
        for key in data:
            if key not in _SCHEMA:
                errors.append(f"unknown key {key!r}")
        kwargs: dict[str, Any] = {}
        for key, (required, checker, expected) in _SCHEMA.items():
            if key not in data:
                if required:
                    errors.append(f"missing required key {key!r}")
                continue
            value = data[key]
            if checker(value):
                kwargs[key] = value
            else:
                errors.append(f"key {key!r}: expected {expected}, got {value!r}")
        if errors:
            listing = "\n".join(f"  - {error}" for error in errors)
            raise ConfigError(
                f"Invalid make-api configuration:\n{listing}\n\n{STRUCTURE_HELP}"
            )
        return cls(**kwargs)

    @classmethod
    def from_json(cls, path: str) -> "MakeApiConfig":
        """Loads and validates a 'make-api.json' configuration file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def _collect_type_aliases(
    manual: dict[str, list[str]], modules_dict: dict[str, ModuleType]
) -> dict[str, list[str]]:
    """
    Merges the manually configured type aliases with the PEP 695 ``type``
    aliases auto-detected in the given modules.

    A ``type X = ...`` statement creates a :class:`typing.TypeAliasType`, which
    is detected here and attributed to the module that defines it. Manual
    entries take precedence: they are listed first, so they win whenever the
    same alias name is defined in more than one module. The manual config can
    also supplement auto-detection with legacy aliases (e.g. ``X: TypeAlias =
    ...`` or bare assignments) that are not ``TypeAliasType`` instances.
    """
    auto: dict[str, list[str]] = {}
    for mod_name, mod in modules_dict.items():
        for member_name, member in vars(mod).items():
            if member_name.startswith("_"):
                continue
            if isinstance(member, TypeAliasType) and member.__module__ == mod_name:
                auto.setdefault(mod_name, []).append(member_name)
    merged: dict[str, list[str]] = {}
    for mod_name in [*manual, *auto]:
        if mod_name in merged:
            continue
        merged[mod_name] = list(
            dict.fromkeys(manual.get(mod_name, []) + auto.get(mod_name, []))
        )
    return merged


def make_apidocs() -> None:
    """
    A script to generate .rst files for API documentation.
    """
    try:
        cfg = MakeApiConfig.from_json("make-api.json")
    except FileNotFoundError:
        print("Could not find a 'make-api.json' file in the current directory.\n")
        print(STRUCTURE_HELP)
        sys.exit(1)
    except ConfigError as e:
        print(e)
        sys.exit(1)

    pkg_name = cfg.pkg_name
    pkg_path = cfg.pkg_path
    apidocs_folder = cfg.apidocs_folder
    toc_filename = cfg.toc_filename
    type_alias_dict_filename = cfg.type_alias_dict_filename
    # Copied because the type-alias members are merged into it below.
    include_members = {key: list(value) for key, value in cfg.include_members.items()}
    exclude_members = cfg.exclude_members
    include_modules = cfg.include_modules
    exclude_modules = cfg.exclude_modules
    member_fullnames = cfg.member_fullnames
    special_class_members = cfg.special_class_members
    manual_doc = cfg.manual_doc

    cwd = os.getcwd()
    os.chdir(pkg_path)
    sys.path = [os.getcwd()] + sys.path
    modules = _list_package_contents(pkg_name)
    modules_dict = {mod_name: importlib.import_module(mod_name) for mod_name in modules}
    for mod_name in include_modules:
        if mod_name not in modules_dict:
            modules_dict[mod_name] = importlib.import_module(mod_name)
    os.chdir(cwd)

    type_aliases = _collect_type_aliases(cfg.type_aliases, modules_dict)
    for mod_name, type_alias_members in type_aliases.items():
        if mod_name not in include_members:
            include_members[mod_name] = []
        include_members[mod_name].extend(type_alias_members)

    os.makedirs(apidocs_folder, exist_ok=True)
    print(f"Removing all docfiles from {apidocs_folder}/")
    for apidoc_file in glob.glob(f"{apidocs_folder}/*.rst"):
        print(f"    {apidoc_file}")
        os.remove(apidoc_file)
    print()

    type_alias_fullnames: dict[str, str] = {}

    print("Pre-processing type aliases:")
    for mod_name, mod_type_aliases in type_aliases.items():
        if mod_name in exclude_modules:
            continue
        for member_name in mod_type_aliases:
            member_fullname = f"{mod_name}.{member_name}"
            if member_name in type_alias_fullnames:
                print(
                    f"    WARNING! Skipping type alias {member_name} -> {member_fullname}"
                )
                print(
                    f"             Existing type alias {member_name} -> {type_alias_fullnames[member_name]}"
                )
            else:
                type_alias_fullnames[member_name] = member_fullname
                print(f"    {member_name} -> {member_fullname}")
    print()

    for mod_name, mod in modules_dict.items():
        if mod_name in exclude_modules:
            continue
        filename = f"{apidocs_folder}/{mod_name}.rst"
        print(f"Writing API docfile {filename}")
        lines: list[str] = [
            mod_name,
            "=" * len(mod_name),
            "",
            f".. automodule:: {mod_name}",
            "",
        ]
        mod__all__ = getattr(mod, "__all__", [])
        reexported_members: list[tuple[str, str]] = []
        for member_name in sorted(name for name in dir(mod)):
            to_include = (
                mod_name in include_members and member_name in include_members[mod_name]
            )
            to_exclude = (
                mod_name in exclude_members and member_name in exclude_members[mod_name]
            )
            if to_exclude:
                continue
            member = getattr(mod, member_name)
            if member_name.startswith("_") and not to_include:
                continue
            member = getattr(mod, member_name)
            member_module = inspect.getmodule(member)
            member_module_name = (
                member_module.__name__ if member_module is not None else None
            )
            imported_member = member_module is not None and member_module != mod
            if mod_name in include_members and member_name in include_members[mod_name]:
                imported_member = False
            if member_name in type_alias_fullnames:
                member_fullname = type_alias_fullnames[member_name]
            elif (
                mod_name in member_fullnames
                and member_name in member_fullnames[mod_name]
            ):
                member_fullname = member_fullnames[mod_name][member_name]
            elif imported_member:
                if inspect.ismodule(member):
                    member_fullname = member_module_name or ""
                else:
                    member_fullname = f"{member_module_name}.{member_name}"
            else:
                member_fullname = f"{mod_name}.{member_name}"
            member_kind = "data"
            if inspect.isclass(member):
                member_kind = "class"
            elif inspect.isfunction(member):
                member_kind = "function"
            elif inspect.ismodule(member):
                member_kind = "module"
            if not imported_member:
                member_name_ = (
                    member_name[:-1] + "\\_"
                    if member_name.endswith("_")
                    else member_name
                )
                member_lines: list[str] = [
                    member_name_,
                    "-" * len(member_name_),
                    "",
                ]
                # Optional manual documentation, inserted before the autodoc
                # directive for members Autodoc cannot describe on its own.
                member_lines.extend(manual_doc.get(member_fullname, []))
                member_lines.append(f".. auto{member_kind}:: {member_fullname}")
                if member_kind == "class":
                    member_lines.append("    :show-inheritance:")
                    member_lines.append("    :members:")
                    _special_class_submembers: list[str] = []
                    if (
                        member_fullname in special_class_members
                        and special_class_members[member_fullname]
                    ):
                        _special_class_submembers.extend(
                            special_class_members[member_fullname]
                        )
                    for submember_name in SPECIAL_CLASS_MEMBERS:
                        if not hasattr(member, submember_name):
                            continue
                        submember = getattr(member, submember_name)
                        if (
                            not hasattr(submember, "__doc__")
                            or submember.__doc__ is None
                        ):
                            continue
                        if not ":meta public:" in submember.__doc__:
                            continue
                        if submember_name not in _special_class_submembers:
                            _special_class_submembers.append(submember_name)
                    if _special_class_submembers:
                        member_lines.append(
                            f"    :special-members: {', '.join(_special_class_submembers)}"
                        )
                member_lines.append("")
                if member_name in type_alias_fullnames:
                    print(
                        f"    {member_kind} {member_name} -> {type_alias_fullnames[member_name]} (type alias)"
                    )
                else:
                    print(f"    {member_kind} {member_name}")
                lines.extend(member_lines)
            elif member_name in mod__all__:
                reexported_members.append((member_fullname, member_kind))
        if reexported_members:
            reexported_members_header = f"{mod_name}.__all__"
            print(f"    {reexported_members_header}:")
            lines.extend(
                [
                    reexported_members_header,
                    "-" * len(reexported_members_header),
                    "",
                    "The following members were explicitly reexported using ``__all__``:",
                    "",
                ]
            )
            refkinds = {
                "data": "obj",
                "function": "func",
                "class": "class",
                "module": "mod",
            }
            for member_fullname, member_kind in reexported_members:
                refkind = f":py:{refkinds[member_kind]}:"
                lines.append(f"    - {refkind}`{member_fullname}`")
                print(f"        {member_kind} {member_fullname}")
            lines.append("")
        with open(filename, "w") as f:
            f.write("\n".join(lines))
        print("")

    if toc_filename is not None:
        toctable_lines = [
            ".. toctree::",
            "    :maxdepth: 2",
            "    :caption: API Documentation",
            "",
        ]
        print(f"Writing TOC for API docfiles at {toc_filename}")
        for mod_name in modules_dict:
            if mod_name in exclude_modules:
                continue
            line = f"    {apidocs_folder}/{mod_name}"
            toctable_lines.append(line)
            print(line)
        toctable_lines.append("")
        print()

        with open(toc_filename, "w") as f:
            f.write("\n".join(toctable_lines))

    if type_alias_dict_filename is not None:
        print(f"Writing type alias dictionary: {type_alias_dict_filename}")
        for name, fullname in type_alias_fullnames.items():
            print(f"    {name} -> {fullname}")
        print()
        with open(type_alias_dict_filename, "w") as f:
            json.dump(type_alias_fullnames, f, indent=4)


if __name__ == "__main__":
    make_apidocs()
