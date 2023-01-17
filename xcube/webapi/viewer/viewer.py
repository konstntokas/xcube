# The MIT License (MIT)
# Copyright (c) 2022 by the xcube team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import json
import socket
import threading
from pathlib import Path
from typing import Optional, Union, Mapping, Any

import tornado.ioloop
import xarray as xr

from xcube.constants import LOG
from xcube.core.mldataset import MultiLevelDataset
from xcube.server.server import Server
from xcube.server.webservers.tornado import TornadoFramework
from xcube.webapi.datasets.context import DatasetsContext

_LAB_INFO_FILE = "~/.xcube/jupyterlab/lab-info.json"


class Viewer:
    """
    Experimental class that represents the xcube Viewer
    in Jupyter Notebooks.

    :param server_config: Server configuration.
        See "xcube serve --show configschema".
    """

    def __init__(self, server_config: Optional[Mapping[str, Any]] = None):
        server_config = dict(server_config or {})

        port = server_config.get("port")
        address = server_config.get("address")

        if port is None:
            port = _find_port()
        if address is None:
            address = "0.0.0.0"

        server_config["port"] = port
        server_config["address"] = address
        self._server_config = server_config

        # Got trick from
        # https://stackoverflow.com/questions/55201748/running-a-tornado-server-within-a-jupyter-notebook
        self._io_loop = tornado.ioloop.IOLoop()
        thread = threading.Thread(target=self._io_loop.start)
        thread.daemon = True
        thread.start()

        self._server = Server(TornadoFramework(io_loop=self._io_loop,
                                               shared_io_loop=True),
                              config=server_config)

        self._io_loop.add_callback(self._server.start)

        server_url = _get_server_url(port)
        self._server_url = server_url
        self._viewer_url = f"{server_url}/viewer/?serverUrl={server_url}"

    @property
    def server_config(self) -> Mapping[str, Any]:
        return self._server_config

    @property
    def server_url(self):
        return self._server_url

    @property
    def viewer_url(self):
        return self._viewer_url

    @property
    def is_server_running(self) -> bool:
        return self._server is not None

    def stop_server(self):
        if self._server is not None:
            # noinspection PyBroadException
            try:
                self._server.stop()
            except:
                pass
        self._server = None
        self._io_loop = None

    def add_dataset(self,
                    dataset: Union[xr.Dataset, MultiLevelDataset],
                    ds_id: Optional[str] = None,
                    title: Optional[str] = None):
        if not self._check_server_running():
            return
        datasets_ctx: DatasetsContext = \
            self._server.ctx.get_api_ctx('datasets')
        return datasets_ctx.add_dataset(dataset, ds_id=ds_id, title=title)

    def remove_dataset(self, ds_id: str):
        if not self._check_server_running():
            return
        datasets_ctx: DatasetsContext = \
            self._server.ctx.get_api_ctx('datasets')
        datasets_ctx.remove_dataset(ds_id)

    def show(self,
             width: Union[int, str] = "100%",
             height: Union[str, int] = 800):
        try:
            from IPython.core.display import HTML
            return HTML(
                f'<iframe src="{self._viewer_url}&compact=1"'
                f' width="{width}"'
                f' height="{height}"'
                f'/>'
            )
        except ImportError as e:
            print(f"Error: {e}; Trying to open Viewer in web browser...")
            try:
                import webbrowser
                webbrowser.open_new_tab(self.viewer_url)
            except:
                print("Failed too.")

    def info(self):
        # Consider outputting this as HTML if in Notebook
        print(f"Server: {self.server_url}")
        print(f"Viewer: {self.viewer_url}")

    def _check_server_running(self):
        if not self.is_server_running:
            print('Server not running')
        return self.is_server_running


def _get_server_url(port: int) -> str:
    lab_url = None
    has_proxy = None
    lab_info_path = Path(*_LAB_INFO_FILE.split("/"))
    if lab_info_path.exists():
        try:
            with lab_info_path.open() as fp:
                lab_info = json.load(fp)
            lab_url = lab_info["lab_url"]
            has_proxy = lab_info["has_proxy"]
        except (OSError, KeyError):
            LOG.warning(f"Failed loading {lab_info_path}")
            pass
    if lab_url and has_proxy:
        return f"{lab_url}proxy/{port}"
    else:
        return f"http://localhost:{port}"


def _find_port(start: int = 8000, end: Optional[int] = None) -> int:
    """Find a port not in use in range *start* to *end*"""
    end = end if isinstance(end, int) and end >= start else start + 12000
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError("No available port found")
