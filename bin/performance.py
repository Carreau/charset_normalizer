from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from glob import glob
from math import ceil
from os.path import isdir
from statistics import mean, stdev
from sys import argv
from time import perf_counter_ns

from chardet import detect as chardet_detect

from charset_normalizer import detect
from charset_normalizer.api import from_bytes
import charset_normalizer.md
import charset_normalizer.constant
import charset_normalizer.api
import charset_normalizer.models
import charset_normalizer.utils

NANO = 1_000_000_000


def calc_percentile(data, percentile):
    n = len(data)
    p = n * percentile / 100
    sorted_data = sorted(data)

    return sorted_data[int(p)] if p.is_integer() else sorted_data[int(ceil(p)) - 1]


def process_file(tbt_path, size_coeff, preloaded_content=None):
    """
    Process a single file and return timing results for both chardet and charset_normalizer.

    Args:
        tbt_path: Path to the file to process
        size_coeff: Size multiplier for testing with larger content
        preloaded_content: Optional pre-loaded file content to avoid I/O

    Returns:
        tuple: (path, chardet_time, charset_normalizer_time, io_time)
    """
    # Time: file I/O
    if preloaded_content is not None:
        content = preloaded_content
        io_time = 0.0
    else:
        io_start = perf_counter_ns()
        with open(tbt_path, "rb") as fp:
            content = fp.read() * size_coeff
        io_time = perf_counter_ns() - io_start

    before = perf_counter_ns()
    # chardet_detect(content)
    import time

    time.sleep(0.0005)
    chardet_time = perf_counter_ns() - before

    before = perf_counter_ns()
    from_bytes(content).best()
    charset_normalizer_time = perf_counter_ns() - before

    return tbt_path, chardet_time, charset_normalizer_time, io_time


def performance_compare(arguments):
    parser = argparse.ArgumentParser(
        description="Performance CI/CD check for Charset-Normalizer"
    )

    parser.add_argument(
        "-s",
        "--size-increase",
        action="store",
        default=1,
        type=int,
        dest="size_coeff",
        help="Apply artificial size increase to challenge the detection mechanism further",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        dest="quiet",
        help="Do not print individual test results",
    )

    parser.add_argument(
        "-e",
        "--export",
        action="store",
        default=None,
        type=str,
        dest="export_filename",
        help="Specify a file to export the performance results to.",
    )

    parser.add_argument(
        "-n",
        "--threads",
        action="store",
        default=1,
        type=int,
        dest="num_threads",
        help="Number of threads to use for parallel processing (default: 1 for sequential)",
    )

    parser.add_argument(
        "--preload",
        action="store_true",
        dest="preload",
        help="Pre-load all files into memory before processing to eliminate I/O contention",
    )

    args = parser.parse_args(arguments)

    if not isdir("./char-dataset"):
        print(
            "This script require https://github.com/Ousret/char-dataset to be cloned on package root directory"
        )
        exit(1)

    if args.num_threads < 0:
        print(
            "Number of threads must be at least 0 (in main thread), or >1 ThreadpoolExecutor"
        )
        exit(1)

    chardet_results = []
    charset_normalizer_results = []
    io_times = []
    paths = []

    file_list = sorted(glob("./char-dataset/**/*.*"))
    total_files = len(file_list)

    print(f"Processing {total_files} files using {args.num_threads} thread(s)...")

    # Pre-load all files into memory if requested
    file_contents = {}
    if args.preload:
        print("Pre-loading all files into memory...")
        preload_start = perf_counter_ns()
        for path in file_list:
            with open(path, "rb") as fp:
                file_contents[path] = fp.read() * args.size_coeff
        preload_time = round((perf_counter_ns() - preload_start) / 1_000_000_000, 2)
        print(f"Pre-loading complete in {preload_time}s")

    start_time = perf_counter_ns()

    if args.num_threads == 0:
        # Sequential processing (original behavior)
        pfs_time = 0
        sc = args.size_coeff
        for idx, tbt_path in enumerate(file_list):
            pfs = perf_counter_ns()
            tbt_path, chardet_time, charset_normalizer_time, io_time = process_file(
                tbt_path,
                sc,
                None
                # file_contents.get(tbt_path)
            )
            delta = perf_counter_ns() - pfs
            pfs_time += delta

            # print(
            #    round(
            #        (delta - (chardet_time + charset_normalizer_time + io_time)) / NANO,
            #        2,
            #    )
            # )
            paths.append(tbt_path)
            chardet_results.append(chardet_time)
            charset_normalizer_results.append(charset_normalizer_time)
            io_times.append(io_time)

            cn_faster = (chardet_time / charset_normalizer_time) * 100 - 100
            if not args.quiet:
                print(
                    f"{idx + 1:>3}/{total_files} {tbt_path:<82} C:{chardet_time:.5f}  "
                    f"CN:{charset_normalizer_time:.5f}  {cn_faster:.1f} %"
                )
            else:
                pass
                print(f"\r{idx}/{total_files}", end="")
    else:
        # Multithreaded processing
        pfs_time = 0
        for sub in {"api", "md", "utils", "models"}:
            if getattr(charset_normalizer, sub).__file__.endswith(".py"):
                print(
                    "CHARSET NORMALISER",
                    sub,
                    "NOT COMPILED WITH MYPYC",
                    getattr(charset_normalizer, sub),
                )
        with ThreadPoolExecutor(max_workers=args.num_threads) as executor:
            # Submit all files to the thread pool
            future_to_path = {
                executor.submit(
                    process_file, tbt_path, args.size_coeff, file_contents.get(tbt_path)
                ): tbt_path
                for tbt_path in file_list
            }

            # Process results as they complete
            for completed, future in enumerate(as_completed(future_to_path)):
                (
                    tbt_path,
                    chardet_time,
                    charset_normalizer_time,
                    io_time,
                ) = future.result()
                paths.append(tbt_path)
                chardet_results.append(chardet_time)
                charset_normalizer_results.append(charset_normalizer_time)
                io_times.append(io_time)

                charset_normalizer_time = charset_normalizer_time
                cn_faster = (chardet_time / charset_normalizer_time) * 100 - 100
                if not args.quiet:
                    print(
                        f"{completed:>3}/{total_files} {tbt_path:<82} C:{chardet_time:.5f}  "
                        f"CN:{charset_normalizer_time:.5f}  {cn_faster:.1f} %"
                    )
                else:
                    print(f"\r{completed}/{total_files}", end="")
    print()

    end_time = perf_counter_ns()
    total_elapsed_time = (end_time - start_time) / NANO
    print(f"\nTotal time elapsed: {total_elapsed_time} seconds")
    print(f"\nTotal pfs : {(pfs_time / NANO):2f} seconds")

    # Timing analysis for multithreading efficiency
    total_io_time = sum(io_times) / NANO
    total_cn_time = sum(charset_normalizer_results) / NANO
    total_cd_time = sum(chardet_results) / NANO
    total_work_time = total_io_time + total_cn_time + total_cd_time

    print(f"\n{'-' * 102}\nTiming Breakdown (using {args.num_threads} thread(s)):\n")
    print(f"Total I/O time (sum):           {total_io_time:.2f}s")
    print(f"Total CD detection time (sum):  {total_cd_time:.2f}s")
    print(f"Total CN detection time (sum):  {total_cn_time:.2f}s")
    print(f"Total work time (sum):          {total_work_time:.2f}s")
    print(f"Actual wall time:               {total_elapsed_time:.2f}s")

    if args.num_threads > 1:
        theoretical_speedup = args.num_threads
        actual_speedup = (
            total_work_time / total_elapsed_time if total_elapsed_time > 0 else 0
        )
        efficiency = (
            (actual_speedup / theoretical_speedup) * 100
            if theoretical_speedup > 0
            else 0
        )

        print(f"\nParallel Efficiency Analysis:")
        print(f"Theoretical speedup (# threads): {theoretical_speedup}x")
        print(f"Actual speedup:                  {actual_speedup:.2f}x")
        print(f"Parallel efficiency:             {efficiency:.1f}%")
        print(
            f"Time unaccounted for:            {max(0, total_elapsed_time - (total_work_time / args.num_threads)):.2f}s"
        )

        if efficiency < 80:
            print(
                f"\nWARNING: Low parallel efficiency ({efficiency:.1f}%). Possible causes:"
            )
            print(
                "  - GIL is still enabled (check with: python -c 'import sys; print(sys._is_gil_enabled())')"
            )
            print("  - Thread synchronization overhead (locks, print statements, etc.)")
            print("  - I/O contention or memory bandwidth limits")

    if args.export_filename:
        print(f"\nExporting performance results to {args.export_filename}...")
        with open(f"{args.export_filename}.csv", "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["path", "chardet_time", "charset_normalizer_time"])
            for path, chardet_time, charset_normalizer_time in zip(
                paths, chardet_results, charset_normalizer_results
            ):
                writer.writerow([path, chardet_time, charset_normalizer_time])
        print("Export complete.")

    return analyse(file_list, charset_normalizer_results, chardet_results, args.num_threads)


def analyse(file_list, charset_normalizer_results, chardet_results, num_threads=1):
    total_files = len(file_list)
    # Print the top 10 rows with the slowest execution time
    print(
        f"\n{'-' * 102}\nTop 10 rows with the slowest execution time of charset_normalizer:\n"
    )
    sorted_results = sorted(
        enumerate(charset_normalizer_results), key=lambda x: x[1], reverse=True
    )
    for idx, time in sorted_results[:10]:
        tbt_path = file_list[idx]
        print(f"{idx + 1:>3}/{total_files} {tbt_path:<82}  CN:{time:.5f}")

    # Print charset normalizer statistics
    min_time = min(charset_normalizer_results)
    max_time = max(charset_normalizer_results)
    stdev_time = stdev(charset_normalizer_results)
    mean_time = mean(charset_normalizer_results)
    cv = (stdev_time / mean_time) * 100  # Coefficient of variation
    print(f"\n{'-' * 102}\nCharset Normalizer statistics (using {num_threads} thread(s)):\n")
    print(f"Minimum Execution Time: {min_time:.5f} seconds")
    print(f"Maximum Execution Time: {max_time:.5f} seconds")
    print(f"Mean Execution Time: {mean_time:.5f} seconds")
    print(f"Standard Deviation: {stdev_time:.5f} seconds")
    print(f"Coefficient of Variation (CV): {cv:.1f} %")

    # Print comparison statistics for chardet and charset normalizer
    chardet_avg_delay = round(mean(chardet_results) * 1000)
    chardet_99p = round(calc_percentile(chardet_results, 99) * 1000)
    chardet_95p = round(calc_percentile(chardet_results, 95) * 1000)
    chardet_50p = round(calc_percentile(chardet_results, 50) * 1000)

    charset_normalizer_avg_delay = round(mean(charset_normalizer_results) * 1000)
    charset_normalizer_99p = round(
        calc_percentile(charset_normalizer_results, 99) * 1000
    )
    charset_normalizer_95p = round(
        calc_percentile(charset_normalizer_results, 95) * 1000
    )
    charset_normalizer_50p = round(
        calc_percentile(charset_normalizer_results, 50) * 1000
    )

    # mypyc can offer performance ~1ms in the 50p. When eq to 0 assume 1 due to imprecise nature of this test.
    if charset_normalizer_50p == 0:
        charset_normalizer_50p = 1

    print(f"\n{'-' * 102}\nCharset Normalizer vs Chardet statistics:\n")

    print("------------------------------")
    print("--> Chardet Conclusions")
    print("   --> Avg: " + str(chardet_avg_delay) + "ms")
    print("   --> 99th: " + str(chardet_99p) + "ms")
    print("   --> 95th: " + str(chardet_95p) + "ms")
    print("   --> 50th: " + str(chardet_50p) + "ms")

    print("------------------------------")
    print("--> Charset-Normalizer Conclusions")
    print("   --> Avg: " + str(charset_normalizer_avg_delay) + "ms")
    print("   --> 99th: " + str(charset_normalizer_99p) + "ms")
    print("   --> 95th: " + str(charset_normalizer_95p) + "ms")
    print("   --> 50th: " + str(charset_normalizer_50p) + "ms")

    print("------------------------------")
    print("--> Charset-Normalizer / Chardet: Performance Сomparison")
    print(
        "   --> Avg: x"
        + str(round(chardet_avg_delay / charset_normalizer_avg_delay, 2))
    )
    print("   --> 99th: x" + str(round(chardet_99p / charset_normalizer_99p, 2)))
    print("   --> 95th: x" + str(round(chardet_95p / charset_normalizer_95p, 2)))
    print("   --> 50th: x" + str(round(chardet_50p / charset_normalizer_50p, 2)))

    return (
        0
        if chardet_avg_delay > charset_normalizer_avg_delay
        and chardet_99p > charset_normalizer_99p
        else 1
    )


if __name__ == "__main__":
    exit(performance_compare(argv[1:]))
