import concurrent.futures
import os
import urllib.request
from argparse import ArgumentParser, SUPPRESS, ArgumentTypeError
import sys

import inquirer
import requests
from progress.bar import IncrementalBar
from yaspin import yaspin


def human_size(bytes, units=[' bytes', ' KB', ' MB', ' GB', ' TB', ' PB', ' EB']):
    """ Returns a human readable string representation of bytes"""
    return str(bytes) + units[0] if bytes < 1024 else human_size(bytes >> 10, units[1:])


def download_datasets(datasets, output_dir, threads):
    for dataset in datasets:
        dataset_dir = os.path.join(output_dir, dataset['name'])
        if not os.path.exists(dataset_dir):
            os.mkdir(dataset_dir)

        downloads = [(
            i['downloadURL'],
            os.path.join(dataset_dir, os.path.split(i['downloadURL'])[1])
        ) for i in dataset['items']]

        print(f'Starting to Download {dataset["name"]}')
        bar = IncrementalBar('Progress', max=len(dataset['items']))
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            future_to_retrieve = {executor.submit(urllib.request.urlretrieve, url, localpath): (url, localpath) for
                                  url, localpath in downloads}
            for _ in concurrent.futures.as_completed(future_to_retrieve):
                bar.next()
            bar.finish()


def check_extent(value):
    extent_split = value.split(',')
    if len(extent_split) != 4:
        raise ArgumentTypeError("%s not in expected format of xmin,ymin,xmax,ymax" % value)
    try:
        extent_split = [float(c) for c in extent_split]
    except:
        raise ArgumentTypeError("encountered non-numeric value in %s" % value)

    if extent_split[0] < -180 or extent_split[0] > 180:
        raise ArgumentTypeError(f'xmin {extent_split[0]} must be between -180 and 180')
    if extent_split[2] < -180 or extent_split[2] > 180:
        raise ArgumentTypeError(f'xmax {extent_split[2]} must be between -180 and 180')
    if extent_split[1] < -90 or extent_split[1] > 90:
        raise ArgumentTypeError(f'ymin {extent_split[1]} must be between -90 and 90')
    if extent_split[3] < -90 or extent_split[3] > 90:
        raise ArgumentTypeError(f'ymax {extent_split[3]} must be between -90 and 90')
    if extent_split[0] > extent_split[2]:
        raise ArgumentTypeError(f"xmin ({extent_split[0]}) can't be greater than xmax ({extent_split[2]})")
    if extent_split[1] > extent_split[3]:
        raise ArgumentTypeError(f"ymin ({extent_split[1]}) can't be greater than ymax ({extent_split[3]})")
    return extent_split

def check_output_dir(value):
    if not os.path.exists(value):
        try:
            os.mkdir(value)
        except:
            raise ArgumentTypeError(f'unable to create output_dir: {value}')
    return value


def get_available_products(bbox):
    params = {
        'bbox': bbox,
        'offset': 0,
        'max': 25000
    }
    r = requests.get('https://viewer.nationalmap.gov/tnmaccess/api/products', params=params)
    if r.status_code == 200:
        products_response = r.json()
        items = products_response['items']
        datasets_unwinded = []
        for item in items:
            for ds_name in item['datasets']:
                try:
                    unwound_ds = next(x for x in datasets_unwinded if x['name'] == ds_name)
                except:
                    unwound_ds = {'name': ds_name, 'items': []}
                    datasets_unwinded.append(unwound_ds)
                unwound_ds['items'].append(item)

        datasets_unwinded.sort(key=lambda k: k['name'])
        return (products_response['messages'], products_response['errors'], datasets_unwinded)

    else:
        #print(f'error from tnm api.  http error code:{r.status_code}')
        raise Exception()


def main(extent, output_dir, threads):
    with yaspin(text="Querying TNM Api", color="yellow") as spinner:
        try:
            messages, errors, available_products = get_available_products(extent)
            spinner.ok()
        except:
            spinner.fail()

    if len(messages) > 0:
        print('Messages:')
        for msg in messages:
            print(f'   {msg}')

    if len(errors) > 0:
        print('Errors:')
        for err in errors:
            print(f'   {err}')

    if len(available_products)==0:
        print('No products found in requested extent')
        sys.exit()

    questions = [
        inquirer.Checkbox('datasets',
                          message="What dataset(s) do you want to download",
                          choices=[
                              f"{ds['name']} | {len(ds['items'])} items @ {human_size(sum(i.get('sizeInBytes', 0) for i in ds['items']))}"
                              for ds in available_products],
                          ),
    ]
    answers = inquirer.prompt(questions)
    selected_dataset_names = [ds.split('|')[0].strip() for ds in answers['datasets']]
    selected_datasets = [p for p in available_products if p['name'] in selected_dataset_names]
    download_datasets(selected_datasets, output_dir, threads)


if __name__ == "__main__":

    parser = ArgumentParser(description='USGS National Map Download CLI', add_help=False)
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')

    # Add back help
    optional.add_argument(
        '-h',
        '--help',
        action='help',
        default=SUPPRESS,
        help='show this help message and exit'
    )
    # Add required parameters of extent and output directory
    required.add_argument(
        "-e",
        "--extent",
        type=check_extent,
        required=True,
        help="WGS84 Extent (xmin,ymin,xmax,ymax) of area to download data"
    )
    required.add_argument(
        "-o",
        "--output_dir",
        type=check_output_dir,
        required=True,
        help="Directory where data will be downloaded to"
    )
    # Add optional parameters
    optional.add_argument(
        "-t",
        "--threads",
        type=int,
        default=5,
        help="The number of threads used to download data"
    )
    args = parser.parse_args()

    # do it
    main(args.extent, args.output_dir, args.threads)
