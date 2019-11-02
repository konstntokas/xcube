# The MIT License (MIT)
# Copyright (c) 2019 by the xcube development team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys

import click

from xcube.util.clihelper import cli_option_scheduler, cli_option_traceback, handle_cli_exception, new_cli_ctx_obj
from xcube.util.plugin import get_extension_registry
from xcube.version import version

EXTENSION_POINT_CLI_COMMANDS = 'xcube.cli'


# noinspection PyShadowingBuiltins,PyUnusedLocal
@click.group(name='xcube')
@click.version_option(version)
@cli_option_traceback
@cli_option_scheduler
def cli(traceback=False, scheduler=None):
    """
    xcube Toolkit
    """


# Add registered CLI commands
for command in get_extension_registry().find_components(EXTENSION_POINT_CLI_COMMANDS):
    cli.add_command(command)


def main(args=None):
    # noinspection PyBroadException
    ctx_obj = new_cli_ctx_obj()
    try:
        exit_code = cli.main(args=args, obj=ctx_obj, standalone_mode=False)
    except Exception as e:
        exit_code = handle_cli_exception(e, traceback_mode=ctx_obj.get(False, "traceback"))
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
