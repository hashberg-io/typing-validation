"""
    Implements a descriptor class with validation features and the possibility
    to define read-only access.
"""

# Copyright (C) 2023 Hashberg Ltd

# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.

# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301
# USA

from __future__ import annotations
import sys
from typing import Any, Generic, Type, TypeVar, Union, cast
from .validation import can_validate, validate

if sys.version_info[1] >= 8:
    from typing import Protocol, final
else:
    from typing_extensions import Protocol, final

T = TypeVar("T")
""" Invariant type variable for generic objects. """

T_contra = TypeVar("T_contra", contravariant=True)
""" Contravariant type variable for generic objects. """

class ValidatorFunction(Protocol[T_contra]):
    """
        Structural type for validator functions of a descriptor.
    """

    def __call__(self, instance: Any, value: T_contra) -> bool:
        """
            Validates the given value for assignment to a descriptor,
            in the context of the given instance.

            Called passing the current ``instance`` and the ``value`` that is
            to be assigned to the descriptor.
            At the time when the validator function for a descriptor is invoked,
            the given ``value`` has already passed its runtime typecheck.
            Validator functions can use ``instance`` to perform validation
            involving other descriptors for the same class.
        """

class Descriptor(Generic[T]):
    """
        A descriptor class which includes:

        - static type checking for the descriptor value;
        - runtime type checking
        - optional runtime validation
        - the ability to make the descriptor read-only.

        Validation functionality can be customised by subclasses,
        see :meth:`Descriptor._is_validation_enabled`.

        The descriptor is backed by a protected or private attribute:

        - if the optional kwarg ``attr_name`` is specified in the constructor,
          the descriptor uses an attribute with that given name;
        - otherwise, the descriptor uses an attribute obtained from the
          descriptor name by prepending an underscore.

        If the attribute name starts with two underscores but does not end with
        two underscores, name-mangling is automatically performed.

    """
    #pylint: disable = too-many-instance-attributes

    __name: str
    __attr_name: str
    __slot_name: str
    __owner: Type[Any]
    __type: Type[T]
    __readonly: bool
    __validator: Union[ValidatorFunction[T], None]
    __error_msg: str|None

    __slots__ = ("__name", "__attr_name", "__slot_name", "__owner", "__type",
                 "__readonly","__validator", "__error_msg")

    def __init__(self, ty: Type[T],
                 validator: Union[ValidatorFunction[T], None] = None,
                 error_msg: Union[str, None] = None, *,
                 readonly: bool = False,
                 attr_name: Union[str, None] = None) -> None:
        """
            Creates a new descriptor with the given type and optional validator.

            :param ty: the type of the descriptor
            :param validator: an optional validator function for the descriptor
            :param readonly: whether the descriptor is read-only
            :param attr_name: the name of the backing attribute for the
                              descriptor, or :obj:`None` to use a default name

            :raises TypeError: if the type is not a valid type
            :raises TypeError: if the validator is not callable

            :meta public:
        """
        if not can_validate(ty):
            raise TypeError(f"Cannot validate type {ty!r}.")
        if validator is not None and not callable(validator):
            raise TypeError(f"Expected callable validator, got {validator!r}.")
        self.__type = ty
        self.__validator = validator
        self.__error_msg = error_msg
        self.__readonly = bool(readonly)
        if attr_name is not None:
            self.__slot_name = attr_name

    @final
    @property
    def name(self) -> str:
        """
            The name of the attribute.
        """
        return self.__name

    @final
    @property
    def type(self) -> Type[T]:
        """
            The type of the attribute.
        """
        return self.__type

    @final
    @property
    def owner(self) -> Type[Any]:
        """
            The class that owns the attribute.
        """
        return self.__owner

    @final
    @property
    def readonly(self) -> bool:
        """
            Whether the attribute is readonly.
        """
        return self.__readonly

    @final
    @property
    def validator(self) -> Union[ValidatorFunction[T], None]:
        """
            The custom validator function for the attribute,
            or :obj:`None` if no validator was specified.

            See :class:`ValidatorFunction`.
        """
        return self.__validator

    @final
    @property
    def error_msg(self) -> Union[str, None]:
        """
            The custom error message for the attribute,
            or :obj:`None` if no error message was specified.
        """
        return self.__error_msg

    @final
    def is_defined_on(self, instance: Any) -> bool:
        """
            Wether the descriptor is defined on the given instance.
        """
        return hasattr(instance, self.__attr_name)

    @final
    def __set_name__(self, owner: Type[Any], name: str) -> None:
        """
            Hook called when the descriptor is assigned to a class attribute.
            Sets the name for the descriptor.
        """
        try:
            slot_name = self.__slot_name
            if slot_name == name:
                raise ValueError(
                    f"Name of backing attribute for descriptor {self.name!r} "
                    "cannot be the same as the descriptor name."
                )
        except AttributeError:
            slot_name = f"_{name}"
            self.__slot_name = slot_name
        if slot_name.startswith("__") and not slot_name.endswith("__"):
            attr_name = f"_{owner.__name__}{slot_name}"
        else:
            attr_name = slot_name
        if hasattr(owner, "__slots__"):
            if slot_name not in owner.__slots__:
                raise AttributeError(
                    ('Private' if slot_name.startswith('__') else 'Protected')
                    + f" attribute {slot_name!r} must be defined in __slots__."
                )
        self.__owner = owner
        self.__name = name
        self.__attr_name = attr_name

    @final
    def __get__(self, instance: Any, _: Type[Any]) -> T:
        """
            Gets the value of the descriptor on the given instance.

            :raises AttributeError: if the attribute is not defined

            :meta public:
        """
        try:
            return cast(T, getattr(instance, self.__attr_name))
        except AttributeError:
            pass
        owner_name = self.__owner.__name__
        error_msg = f"{owner_name!r} object has no attribute {self.name!r}"
        raise AttributeError(error_msg)

    @final
    def __set__(self, instance: Any, value: T) -> None:
        """
            Sets the value of the descriptor on the given instance.

            :raises TypeError: if the value has the wrong type
            :raises ValueError: if a custom validator is specified and the
                                value is invalid
            :raises AttributeError: if the attribute is readonly

            :meta public:
        """
        if self._is_validation_enabled(instance):
            validate(value, self.type)
            validator = self.__validator
            if validator is not None and not validator(instance, value):
                raise ValueError(
                    f"Invalid value for attribute {self.name!r}: {value!r}."
                    + (
                        f" {self.__error_msg}"
                        if self.__error_msg is not None
                        else ""
                    )
                )

        if self.__readonly and self.is_defined_on(instance):
            raise AttributeError(
                f"Attribute {self.name!r} is readonly: it can only be set once."
            )
        setattr(instance, self.__attr_name, value)

    @final
    def __delete__(self, instance: Any) -> None:
        """
            Deletes the value of the descriptor on the given instance.

            :raises AttributeError: if the attribute is readonly
            :raises AttributeError: if the attribute is not defined

            :meta public:
        """
        if self.__readonly:
            raise AttributeError(
                f"Attribute {self.name!r} is readonly: it cannot be deleted."
            )
        if not self.is_defined_on(instance):
            owner_name = self.__owner.__name__
            error_msg = f"{owner_name!r} object has no attribute {self.name!r}"
            raise AttributeError(error_msg)
        delattr(instance, self.__attr_name)

    def _is_validation_enabled(self, instance: Any) -> bool:
        """
            Returns whether validation is enabled for the given instance.
            By default, validation is enabled, but ubclasses can override this
            method to provide more fine-grained control over validation.

            :meta public:
        """
        return True
