#%%
import tiledb
import numpy as np, pandas as pd
import sys, os, tempfile, time, glob
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager

# helper functions to generate data
from tiledb.tests.common import rand_datetime64_array, rand_utf8

# are we running as a test
in_test = hasattr(sys, '_called_from_test')

def generate_csvs(csv_folder, count=50, min_length=1, max_length=109):
    def make_dataframe(col_size):
        data = {
            'idx_datetime': rand_datetime64_array(col_size),
            'column_int64': np.random.randint(0,150000,size=col_size,dtype=np.int64),
            'column_uint32': np.random.randint(0,150000,size=col_size,dtype=np.uint32),
            'column_float64': np.random.rand(col_size),
            'column_utf8': np.array([rand_utf8(np.random.randint(1, 100)) for _ in range(col_size)])
        }
        df = pd.DataFrame.from_dict(data)

        df.set_index('idx_datetime', inplace=True)
        return df


    # create list of CSV row-counts to generate
    # (each file will have nrows from this list)
    csv_lengths = np.random.randint(min_length, max_length, size=count)

    for i, target_length in enumerate(csv_lengths):
        output_path = os.path.join(csv_folder, "gen_csv_{}.csv".format(i))

        df = make_dataframe(target_length)
        df.to_csv(output_path)

def from_csv_mp(csv_path, array_path, list_step_size=5, chunksize=100, max_workers=4,
                engine='processpool',
                initial_file_count=5,
                index_col=None,
                parse_dates=None,
                attr_types=None,
                sparse=True,
                debug=False,
                **kwargs):
    """
    Multi-process ingestion wrapper around tiledb.from_csv

    Currently uses ProcessPoolExecutor.
    """

    # Setting start method to 'spawn' is required before TileDB 2.1 to
    # avoid problems with TBB when spawning via fork.
    # NOTE: *must be inside __main__* or a function.
    if multiprocessing.get_start_method(True) is not 'spawn':
        multiprocessing.set_start_method('spawn', True)

    # Get a list of of CSVs from the target path
    csvs = glob.glob(csv_path + "/*.csv")
    if len(csvs) < 1:
        raise ValueError("Cannot ingest empty CSV list!")

    # first step: create the array. we read the first N csvs to create schema
    #             and as check for inconsistency before starting the full run.
    tiledb.from_csv(array_path, csvs[:initial_file_count],
                chunksize=chunksize, # must set chunksize here even though schema_only
                index_col = index_col,
                parse_dates=parse_dates,
                dtype=attr_types,
                column_types=attr_types,
                engine='c',
                debug=debug,
                allows_duplicates=True,
                sparse=sparse,
                mode='schema_only',
                **kwargs)

    print("Finished array schema creation")

    # controls number of CSV files passed to each worker process:
    # depending on the makeup of the files, we may want to read a number of
    # files consecutively (up to chunksize) in order to write more optimal
    # fragments.
    if (list_step_size > len(csvs)):
        raise ValueError("Please choose a step size smaller than the number of CSV files")

    tasks = []
    csv_chunks = []

    # high level ingestion timing
    start = time.time()
    # ingest the data in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for first in range(0, len(csvs)+1, list_step_size):
            last = min(len(csvs), first + list_step_size)
            print("  Submitting task for CSV list range: ", (first, last))
            task = executor.submit(
                tiledb.from_csv,
                *(array_path, csvs[first:last]),
                **dict(chunksize=chunksize,
                       index_col=index_col,
                       parse_dates=parse_dates,
                       dtype=attr_types,
                       column_types=attr_types,
                       engine='c',
                       debug=debug,
                       allows_duplicates=True),
                **kwargs,
                mode='append')
            tasks.append(task)

    print("Task results: ", [t.result() for t in tasks])

    print("Ingestion complete. Duration: ", time.time() - start)

##############################################################################
# Usage example
##############################################################################
def example():
    # set up test paths and data
    csv_path = tempfile.mkdtemp()
    generate_csvs(csv_path, count=73)
    print("Finished generating CSVs in path: ", csv_path)

    array_path = tempfile.mkdtemp()
    print("Writing output array to: ", array_path)

    # Create Schema
    attr_types = {
        'column_int64': np.int64,
        'column_uint32': np.uint32,
        'column_float64': np.float64,
        'column_utf8': np.str
        }

    from_csv_mp(csv_path, array_path, chunksize=27, list_step_size=5,
                max_workers=4, index_col=['idx_datetime'], attr_types=attr_types)

    print("Ingestion complete.")
    print("  Note: temp paths have undefined lifetime after exit.")

    # apparently no good way to check for "is interactive" in python
    if not in_test:
        input("  Press any key to continue: ")

    return csv_path, array_path

if __name__ == '__main__':
    example()


##############################################################################
# TEST SECTION
# uses this example as a test of various input combinations
##############################################################################
def df_from_csvs(path, **kwargs):
    idx_column = kwargs.pop('tiledb_idx_column', None)

    csv_paths = glob.glob(path + "/*.csv")
    csv_df_list = [pd.read_csv(p, **kwargs) for p in csv_paths]

    df = pd.concat(csv_df_list)

    # tiledb returns sorted values
    if idx_column is not None:
        df.sort_values(idx_column, inplace=True)
        df.set_index(idx_column, inplace=True)

    return df

def test_parallel_csv_ingestion():
    csv_path, array_path = example()
    import pandas._testing as tm
    from numpy.testing import assert_array_equal, assert_array_almost_equal

    attr_types = {
        'column_int64': np.int64,
        'column_uint32': np.uint32,
        'column_float64': np.float64,
        'column_utf8': np.str
        }

    # read dataframe from CSV list, set index, and sort
    df_direct = df_from_csvs(csv_path, dtype=attr_types,
                             tiledb_idx_column='idx_datetime')

    # validate the array generated in example()
    if True:
        df_tiledb = tiledb.open_dataframe(array_path)

        tm.assert_frame_equal(df_direct, df_tiledb)

    # ingest over several parameters
    for nproc in [1, 5]: # note: already did 4 above
        for csv_list_step in [5, 11]:
            for chunksize in [10, 100]:
                array_tmp = tempfile.mkdtemp()

                print("Running ingestion with nproc: '{}', step: '{}', chunksize: '{}'".format
                      (nproc, csv_list_step, chunksize))
                print("Writing output array to: ", array_tmp)

                from_csv_mp(csv_path, array_tmp,
                            chunksize=chunksize,
                            list_step_size=csv_list_step,
                            max_workers=nproc,
                            index_col=['idx_datetime'],
                            attr_types=attr_types)


                df_tiledb = tiledb.open_dataframe(array_tmp)
                tm.assert_frame_equal(df_direct, df_tiledb)

    print("Writing output array to: ", array_path)