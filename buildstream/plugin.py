#!/usr/bin/env python3
#
#  Copyright (C) 2017 Codethink Limited
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>

import datetime
from contextlib import contextmanager
from weakref import WeakValueDictionary

from . import _yaml
from . import ImplError
from .exceptions import _ALL_EXCEPTIONS
from ._message import Message, MessageType


class Plugin():
    """Plugin()

    Base Plugin class.

    Some common features to both Sources and Elements are found
    in this class.
    """
    def __init__(self, display_name, context, project, provenance, type_tag):
        self.__context = context        # The Context object
        self.__project = project        # The Project object
        self.__provenance = provenance  # The Provenance information
        self.__type_tag = type_tag      # The type of plugin (element or source)
        self.__unique_id = _plugin_register(self)  # Unique ID
        self.__display_name = display_name

        self.debug("Created: {}".format(self))

    def __del__(self):
        self.debug("Destroyed: {}".format(self))
        _plugin_unregister(self.__unique_id)

    def __str__(self):
        return "{kind} {typetag} at {provenance}".format(
            kind=self.get_kind(),
            typetag=self.__type_tag,
            provenance=self.__provenance)

    def get_kind(self):
        """Fetches the kind of this plugin

        Returns:
           (str): The kind of this plugin
        """
        modulename = type(self).__module__
        return modulename.split('.')[-1]

    def get_context(self):
        """Fetches the context

        Returns:
           (object): The :class:`.Context`
        """
        return self.__context

    def get_project(self):
        """Fetches the project

        Returns:
           (object): The :class:`.Project`
        """
        return self.__project

    def node_items(self, node):
        """Iterate over a dictionary loaded from YAML

        Args:
           dict: The YAML loaded dictionary object

        Returns:
           list: List of key/value tuples to iterate over

        BuildStream holds some private data in dictionaries loaded from
        the YAML in order to preserve information to report in errors.

        This convenience function should be used instead of the dict.items()
        builtin function provided by python.
        """
        for key, value in node.items():
            if key == _yaml.PROVENANCE_KEY:
                continue
            yield (key, value)

    def node_get_member(self, node, expected_type, member_name, default_value=None):
        """Fetch the value of a node member, raising an error if the value is
        missing or incorrectly typed.

        Args:
           node (dict): A dictionary loaded from YAML
           expected_type (type): The expected type of the node member
           member_name (str): The name of the member to fetch
           default_value (expected_type): A value to return when *member_name* is not specified in *node*

        Returns:
           The value of *member_name* in *node*, otherwise *default_value*

        Raises:
           :class:`.LoadError`: When *member_name* is not found and no *default_value* was provided

        Note:
           Returned strings are stripped of leading and trailing whitespace

        **Example:**

        .. code:: python

          # Expect a string 'name' in 'node'
          name = self.node_get_member(node, str, 'name')

          # Fetch an optional integer
          level = self.node_get_member(node, int, 'level', -1)
        """
        return _yaml.node_get(node, expected_type, member_name, default_value=default_value)

    def node_get_list_element(self, node, expected_type, member_name, indices):
        """Fetch the value of a list element from a node member, raising an error if the
        value is incorrectly typed.

        Args:
           node (dict): A dictionary loaded from YAML
           expected_type (type): The expected type of the node member
           member_name (str): The name of the member to fetch
           indices (list of int): List of indices to search, in case of nested lists

        Returns:
           The value of the list element in *member_name* at the specified *indices*

        Raises:
           :class:`.LoadError`

        Note:
           Returned strings are stripped of leading and trailing whitespace

        **Example:**

        .. code:: python

          # Fetch the list itself
          things = self.node_get_member(node, list, 'things')

          # Iterate over the list indices
          for i in range(len(things)):

              # Fetch dict things
              thing = self.node_get_list_element(
                  node, dict, 'things', [ i ])
        """
        return _yaml.node_get(node, expected_type, member_name, indices=indices)

    def configure(self, node):
        """Configure the Plugin from loaded configuration data

        Args:
           node (dict): The loaded configuration dictionary

        Raises:
           :class:`.SourceError`: If its a :class:`.Source` implementation
           :class:`.ElementError`: If its an :class:`.Element` implementation
           :class:`.LoadError`: If one of the *node* handling methods fail

        Plugin implementors should implement this method to read configuration
        data and store it. Use of the :func:`~buildstream.plugin.Plugin.node_get_member`
        convenience method will ensure that a nice :class:`.LoadError` is triggered
        whenever the YAML input configuration is faulty.

        Implementations may raise :class:`.SourceError` or :class:`.ElementError` for other errors.
        """
        raise ImplError("{tag} plugin '{kind}' does not implement configure()".format(
            tag=self.__type_tag, kind=self.get_kind()))

    def preflight(self):
        """Preflight Check

        Raises:
           :class:`.SourceError`: If its a :class:`.Source` implementation
           :class:`.ElementError`: If its an :class:`.Element` implementation
           :class:`.ProgramNotFoundError`: If a required host tool is not found

        This method is run after :func:`~buildstream.plugin.Plugin.configure` and
        after the pipeline is fully constructed. :class:`.Element` plugins are free
        to use the :func:`~buildstream.element.Element.dependencies` method and inspect
        public data at this time.

        Implementors should simply raise :class:`.SourceError` or :class:`.ElementError`
        with an informative message in the case that the host environment is
        unsuitable for operation.

        Plugins which require host tools (only sources usually) should obtain
        them with :func:`.utils.get_host_tool` which will raise
        :class:`.ProgramNotFoundError` automatically.
        """
        raise ImplError("{tag} plugin '{kind}' does not implement preflight()".format(
            tag=self.__type_tag, kind=self.get_kind()))

    def get_unique_key(self):
        """Return something which uniquely identifies the plugin input

        Returns:
           A string, list or dictionary which uniquely identifies the sources to use

        This is used to construct unique cache keys for elements and sources,
        sources should return something which uniquely identifies the payload,
        such as an sha256 sum of a tarball content. Elements should implement
        this by collecting any configurations which could possibly effect the
        output and return a dictionary of these settings.
        """
        raise ImplError("{tag} plugin '{kind}' does not implement get_unique_key()".format(
            tag=self.__type_tag, kind=self.get_kind()))

    def debug(self, brief, detail=None):
        """Print a debugging message

        Args:
           brief (str): The brief message
           detail (str): An optional detailed message, can be multiline output
        """
        self._message(MessageType.DEBUG, brief, detail=detail)

    def status(self, brief, detail=None):
        """Print a status message

        Args:
           brief (str): The brief message
           detail (str): An optional detailed message, can be multiline output
        """
        self._message(MessageType.STATUS, brief, detail=detail)

    def warn(self, brief, detail=None):
        """Print a warning message

        Args:
           brief (str): The brief message
           detail (str): An optional detailed message, can be multiline output
        """
        self._message(MessageType.WARN, brief, detail=detail)

    def error(self, brief, detail=None):
        """Print an error message

        Args:
           brief (str): The brief message
           detail (str): An optional detailed message, can be multiline output
        """
        self._message(MessageType.ERROR, brief, detail=detail)

    @contextmanager
    def timed_activity(self, activity_name):
        """Context manager for performing timed activities in plugins

        Args:
           activity_name: The name of the activity

        This function lets you perform timed tasks in your plugin,
        the core will take care of timing the duration of your
        task and printing start / fail / success messages.

        **Example**

        .. code:: python

          # Activity will be logged and timed
          with self.timed_activity("Mirroring {}".format(self.url)):

              # Non-zero is an error
              if subprocess.call(... command to create mirror ...):
                  raise SourceError(...)
        """
        starttime = datetime.datetime.now()
        try:
            self._message(MessageType.START, activity_name)
            yield
        except _ALL_EXCEPTIONS as e:
            # Re raise after queueing a fail message, the scheduler needs to know
            # there was an exception
            elapsed = datetime.datetime.now() - starttime
            self._message(MessageType.FAIL, activity_name, elapsed=elapsed)
            raise e

        elapsed = datetime.datetime.now() - starttime
        self._message(MessageType.SUCCESS, activity_name, elapsed=elapsed)

    #############################################################
    #            Private Methods used in BuildStream            #
    #############################################################

    # _get_display_name():
    #
    # Fetch the plugin's display name, to be used in message titles
    # and such.
    #
    def _get_display_name(self):
        return self.__display_name

    # _get_unique_id():
    #
    # Fetch the plugin's unique identifier
    #
    def _get_unique_id(self):
        return self.__unique_id

    def _message(self, message_type, brief, detail=None, elapsed=None):
        message = Message(self.__unique_id, message_type, brief,
                          detail=detail,
                          elapsed=elapsed)
        self.__context._message(message)

# Hold on to a lookup table by counter of all instantiated plugins.
# We use this to send the id back from child processes so we can lookup
# corresponding element/source in the master process.
#
# Use WeakValueDictionary() so the map we use to lookup objects does not
# keep the plugins alive after pipeline destruction.
#
# Note that Plugins can only be instantiated in the main process before
# scheduling tasks.
__PLUGINS_UNIQUE_ID = 0
__PLUGINS_TABLE = WeakValueDictionary()


# _plugin_lookup():
#
# Fetch a plugin in the current process by it's
# unique identifier
#
# Args:
#    unique_id: The unique identifier as returned by
#               plugin._get_unique_id()
#
# Returns:
#    (Plugin): The plugin for the given ID, or None
#
def _plugin_lookup(unique_id):
    try:
        plugin = __PLUGINS_TABLE[unique_id]
    except (AttributeError, KeyError):
        print("Could not find plugin with ID {}".format(unique_id))
        raise e

    return plugin


def _plugin_register(plugin):
    global __PLUGINS_UNIQUE_ID
    __PLUGINS_UNIQUE_ID += 1
    __PLUGINS_TABLE[__PLUGINS_UNIQUE_ID] = plugin
    return __PLUGINS_UNIQUE_ID


def _plugin_unregister(unique_id):
    del __PLUGINS_TABLE[str(unique_id)]
