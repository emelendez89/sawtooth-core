# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------

from abc import ABCMeta
import ctypes
from enum import IntEnum
import logging
import os
import sys


LOGGER = logging.getLogger(__name__)


class Library:

    def __init__(self, library_loader):
        lib_prefix_mapping = {
            "darwin": "lib",
            "linux": "lib",
            "linux2": "lib",
        }
        lib_suffix_mapping = {
            "darwin": ".dylib",
            "linux": ".so",
            "linux2": ".so",
        }

        os_name = sys.platform

        lib_location = os.environ.get('SAWTOOTH_LIB_HOME', '')
        if lib_location and lib_location[-1:] != '/':
            lib_location += '/'

        try:
            lib_prefix = lib_prefix_mapping[os_name]
            lib_suffix = lib_suffix_mapping[os_name]
        except KeyError:
            raise OSError("OS isn't supported: {}".format(os_name))

        library_path = "{}{}sawtooth_validator{}".format(
            lib_location, lib_prefix, lib_suffix)

        LOGGER.debug("loading library %s", library_path)

        self._cdll = library_loader(library_path)

    def call(self, name, *args):
        return getattr(self._cdll, name)(*args)


LIBRARY = Library(ctypes.CDLL)
LIBRARY.call("pylogger_init", LOGGER.getEffectiveLevel())
PY_LIBRARY = Library(ctypes.PyDLL)


def prepare_byte_result():
    """Returns pair of byte pointer and size value for use as return parameters
    in a LIBRARY call
    """
    return (ctypes.POINTER(ctypes.c_uint8)(), ctypes.c_size_t(0))


def from_c_bytes(c_data, c_data_len, reclaim=True):
    """Takes a byte pointer and a length and converts it into a python bytes
    value. The bytes are reclaimed using Rust FFI code if reclaim is True.
    """
    # pylint: disable=invalid-slice-index
    py_bytes = bytes(c_data[:c_data_len.value])
    if reclaim:
        LIBRARY.call(
            "ffi_reclaim_bytes",
            ctypes.byref(c_data),
            ctypes.byref(c_data_len))
    return py_bytes


class OwnedPointer(metaclass=ABCMeta):
    """An owned pointer will call drop when this pointer is garbage collected.
    """
    def __init__(self, drop_ffi_call_fn, initialized_ptr=None):
        """Constructs an owned pointer.
        Initializing the pointer is left to the extending classes

        Args:
            drop_ffi_call_fn (str): the name of the FFI function to call on
                drop or garbage collection.
            initialized_ptr (ctypes.c_void_p:optional): a preinitialized
                pointer to the native memory
        """
        if initialized_ptr is not None:
            self._ptr = initialized_ptr
        else:
            self._ptr = ctypes.c_void_p()

        self._drop_ffi_fn = drop_ffi_call_fn

    def drop(self):
        """Explicitly drop this pointer.  The memory will be deallocated via
        the drop_ffi_call_fn passed to the constructor.
        """
        if self._ptr:
            LIBRARY.call(self._drop_ffi_fn, self._ptr)
            self._ptr = None

    def __del__(self):
        self.drop()

    @property
    def pointer(self):
        """Return a reference to the pointer, for use in other ffi wrappers.
        """
        return self._ptr

    def as_ref(self):
        return RefPointer(self.pointer)


class RefPointer:
    """A reference to a pointer.

    This pointer does not manage any deallocation of the underlying memory.
    """
    def __init__(self, ptr):
        self._ptr = ptr

    @property
    def pointer(self):
        return self._ptr


class CommonErrorCode(IntEnum):
    Success = 0
    NullPointerProvided = 0x01

    Unknown = 0xff


def python_to_sender_callback(sender):
    """Wraps a sender in a callback.  The sender must have a "send" function
    which receive the arguments from the callback

    Args:
        sender (:obj:) an object that has a "send" function

    Returns:
        a function
    """
    def callback_wrapper(*args):
        return sender.send(*args)

    return callback_wrapper
