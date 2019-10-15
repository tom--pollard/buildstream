#
#  Copyright (C) 2018 Codethink Limited
#  Copyright (C) 2018-2019 Bloomberg Finance LP
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

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time

import grpc

from .._protos.build.bazel.remote.execution.v2 import remote_execution_pb2_grpc
from .._protos.build.buildgrid import local_cas_pb2_grpc
from .._protos.google.bytestream import bytestream_pb2_grpc

from .. import _signals, utils
from .._exceptions import CASCacheError
from .._message import Message, MessageType

_CASD_MAX_LOGFILES = 10


# CASDProcessManager
#
# This manages the subprocess that runs buildbox-casd.
#
# Args:
#     path (str): The root directory for the CAS repository
#     log_dir (str): The directory for the logs
#     log_level (LogLevel): Log level to give to buildbox-casd for logging
#     cache_quota (int): User configured cache quota
#     protect_session_blobs (bool): Disable expiry for blobs used in the current session
#
class CASDProcessManager:
    def __init__(self, path, log_dir, log_level, cache_quota, protect_session_blobs):
        self._log_dir = log_dir

        # Place socket in global/user temporary directory to avoid hitting
        # the socket path length limit.
        self._socket_tempdir = tempfile.mkdtemp(prefix="buildstream")
        self._socket_path = os.path.join(self._socket_tempdir, "casd.sock")
        self._connection_string = "unix:" + self._socket_path

        casd_args = [utils.get_host_tool("buildbox-casd")]
        casd_args.append("--bind=" + self._connection_string)
        casd_args.append("--log-level=" + log_level.value)

        if cache_quota is not None:
            casd_args.append("--quota-high={}".format(int(cache_quota)))
            casd_args.append("--quota-low={}".format(int(cache_quota / 2)))

            if protect_session_blobs:
                casd_args.append("--protect-session-blobs")

        casd_args.append(path)

        self._start_time = time.time()
        self._logfile = self._rotate_and_get_next_logfile()

        with open(self._logfile, "w") as logfile_fp:
            # Block SIGINT on buildbox-casd, we don't need to stop it
            # The frontend will take care of it if needed
            with _signals.blocked([signal.SIGINT], ignore=False):
                self.process = subprocess.Popen(casd_args, cwd=path, stdout=logfile_fp, stderr=subprocess.STDOUT)

    # _rotate_and_get_next_logfile()
    #
    # Get the logfile to use for casd
    #
    # This will ensure that we don't create too many casd log files by
    # rotating the logs and only keeping _CASD_MAX_LOGFILES logs around.
    #
    # Returns:
    #   (str): the path to the log file to use
    #
    def _rotate_and_get_next_logfile(self):
        try:
            existing_logs = sorted(os.listdir(self._log_dir))
        except FileNotFoundError:
            os.makedirs(self._log_dir)
        else:
            while len(existing_logs) >= _CASD_MAX_LOGFILES:
                logfile_to_delete = existing_logs.pop(0)
                os.remove(os.path.join(self._log_dir, logfile_to_delete))

        return os.path.join(self._log_dir, str(self._start_time) + ".log")

    # release_resources()
    #
    # Terminate the process and release related resources.
    #
    def release_resources(self, messenger=None):
        self._terminate(messenger)
        self.process = None
        shutil.rmtree(self._socket_tempdir)

    # _terminate()
    #
    # Terminate the buildbox casd process.
    #
    def _terminate(self, messenger=None):
        return_code = self.process.poll()

        if return_code is not None:
            # buildbox-casd is already dead

            if messenger:
                messenger.message(
                    Message(
                        MessageType.BUG,
                        "Buildbox-casd died during the run. Exit code: {}, Logs: {}".format(
                            return_code, self._logfile
                        ),
                    )
                )
            return

        self.process.terminate()

        try:
            # Don't print anything if buildbox-casd terminates quickly
            return_code = self.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            if messenger:
                cm = messenger.timed_activity("Terminating buildbox-casd")
            else:
                cm = contextlib.suppress()
            with cm:
                try:
                    return_code = self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=15)

                    if messenger:
                        messenger.message(
                            Message(MessageType.WARN, "Buildbox-casd didn't exit in time and has been killed")
                        )
                    return

        if return_code != 0 and messenger:
            messenger.message(
                Message(
                    MessageType.BUG,
                    "Buildbox-casd didn't exit cleanly. Exit code: {}, Logs: {}".format(return_code, self._logfile),
                )
            )

    # create_channel():
    #
    # Return a CASDChannel, note that the actual connection is not necessarily
    # established until it is needed.
    #
    def create_channel(self):
        return CASDChannel(self._socket_path, self._connection_string, self._start_time)


class CASDChannel:
    def __init__(self, socket_path, connection_string, start_time):
        self._socket_path = socket_path
        self._connection_string = connection_string
        self._start_time = start_time
        self._casd_channel = None
        self._bytestream = None
        self._casd_cas = None
        self._local_cas = None

    def _establish_connection(self):
        assert self._casd_channel is None

        while not os.path.exists(self._socket_path):
            # casd is not ready yet, try again after a 10ms delay,
            # but don't wait for more than 15s
            if time.time() > self._start_time + 15:
                raise CASCacheError("Timed out waiting for buildbox-casd to become ready")

            time.sleep(0.01)

        self._casd_channel = grpc.insecure_channel(self._connection_string)
        self._bytestream = bytestream_pb2_grpc.ByteStreamStub(self._casd_channel)
        self._casd_cas = remote_execution_pb2_grpc.ContentAddressableStorageStub(self._casd_channel)
        self._local_cas = local_cas_pb2_grpc.LocalContentAddressableStorageStub(self._casd_channel)

    # get_cas():
    #
    # Return ContentAddressableStorage stub for buildbox-casd channel.
    #
    def get_cas(self):
        if self._casd_channel is None:
            self._establish_connection()
        return self._casd_cas

    # get_local_cas():
    #
    # Return LocalCAS stub for buildbox-casd channel.
    #
    def get_local_cas(self):
        if self._casd_channel is None:
            self._establish_connection()
        return self._local_cas

    def get_bytestream(self):
        if self._casd_channel is None:
            self._establish_connection()
        return self._bytestream

    # is_closed():
    #
    # Return whether this connection is closed or not.
    #
    def is_closed(self):
        return self._casd_channel is None

    # close():
    #
    # Close the casd channel.
    #
    def close(self):
        if self.is_closed():
            return
        self._local_cas = None
        self._casd_cas = None
        self._casd_channel.close()
        self._casd_channel = None
