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

from typing import Optional, Tuple

import click

DEFAULT_TILE_SIZE = 512


# noinspection PyShadowingBuiltins
@click.command(name="level")
@click.argument('input')
@click.option('--output', '-o', metavar='OUTPUT',
              help='Output path. If omitted, "INPUT.levels" will be used.'
                   ' You can also use S3 object storage URLs of the form'
                   ' "s3://<bucket>/<path>" or "https://<endpoint>"')
@click.option('--link', '-L', is_flag=True, flag_value=True,
              help='Link the INPUT instead of converting it to a level'
                   ' zero dataset. Use with care, as the INPUT\'s internal'
                   ' spatial chunk sizes may be inappropriate'
                   ' for imaging purposes.')
@click.option('--tile-size', '-t', metavar='TILE_SIZE',
              help=f'Tile size, given as single integer number or'
                   f' as <tile-width>,<tile-height>. '
                   f'If omitted, the tile size will be derived'
                   f' from the INPUT\'s'
                   f' internal spatial chunk sizes.'
                   f' If the INPUT is not chunked,'
                   f' tile size will be {DEFAULT_TILE_SIZE}.')
@click.option('--num-levels-max', '-n', metavar='NUM_LEVELS_MAX', type=int,
              help=f'Maximum number of levels to generate. '
                   f'If not given, the number of levels will'
                   f' be derived from spatial dimension and tile sizes.')
@click.option('--replace', '-r', is_flag=True, flag_value=True,
              help=f'Whether to replace an existing dataset at OUTPUT.')
@click.option('--anon', '-a', is_flag=True, flag_value=True,
              help=f'For S3 inputs or outputs, whether the access'
                   f' is anonymous. By default, credentials are required.')
def level(input: str,
          output: Optional[str],
          link: bool,
          tile_size: Optional[str],
          num_levels_max: int,
          replace: bool,
          anon: bool):
    """
    Generate multi-resolution levels.

    Transform the given dataset by INPUT into the levels of a
    multi-level pyramid with spatial resolution decreasing by a
    factor of two in both spatial dimensions and write the
    result to directory OUTPUT.

    INPUT may be an S3 object storage URL of the form
    "s3://<bucket>/<path>" or "https://<endpoint>".
    """
    import time
    import os
    from xcube.cli.common import parse_cli_sequence
    from xcube.cli.common import assert_positive_int_item
    from xcube.core.store import new_fs_data_store

    input_path = input
    output_path = output
    link_input = link

    if tile_size is not None:
        tile_size = parse_cli_sequence(
            tile_size,
            metavar='TILE_SIZE', num_items=2,
            item_plural_name='tile sizes',
            item_parser=int,
            item_validator=assert_positive_int_item
        )

    if num_levels_max is not None and num_levels_max < 1:
        raise click.ClickException(
            f"NUM_LEVELS_MAX must be a positive integer"
        )

    input_protocol, input_path = _split_protocol_and_path(input_path)

    if not output_path:
        dir_path = os.path.dirname(input_path).replace("\\", "/")
        basename, ext = os.path.splitext(os.path.basename(input_path))
        output_protocol = input_protocol
        output_path = f'{dir_path}/{basename + ".levels"}'
    else:
        output_protocol, output_path = _split_protocol_and_path(output_path)

    if link_input and input_protocol != output_protocol:
        raise click.ClickException('Links can be used only'
                                   ' if input and output are in'
                                   ' the same filesystem')

    start_time = time.time()

    input_store = new_fs_data_store(input_protocol,
                                    storage_options=dict(anon=anon)
                                    if input_protocol == 's3' else None)
    input_dataset = input_store.open_data(input_path)

    output_store = new_fs_data_store(output_protocol,
                                     storage_options=dict(anon=anon)
                                     if output_protocol == 's3' else None)
    try:
        output_store.write_data(
            input_dataset,
            output_path,
            replace=replace,
            tile_size=tile_size,
            num_levels=num_levels_max,
            base_dataset_id=input_path if link_input else None,
        )
    except FileExistsError as e:
        raise click.ClickException(
            f"output {output_path!r} already exists"
        ) from e

    print(f"Multi-level dataset written to {output_path}"
          f" after {time.time() - start_time} seconds")


def _split_protocol_and_path(path) -> Tuple[str, str]:
    if '://' in path:
        protocol, path = path.split('://', 2)
        if protocol == 'https':
            protocol = 's3'
    else:
        protocol = 'file'
    return protocol, path
