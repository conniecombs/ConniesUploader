# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""
Benchmarks for file operations including scanning, validation, and processing.
"""

import time
import tempfile
import shutil
from pathlib import Path
from typing import List, Callable, Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.file_handler import scan_inputs, validate_file_size, validate_file_extension
from modules.validation import sanitize_filename


class BenchmarkResult:
    """Stores benchmark results."""

    def __init__(
        self, name: str, iterations: int, total_time: float, avg_time: float, ops_per_sec: float
    ):
        self.name = name
        self.iterations = iterations
        self.total_time = total_time
        self.avg_time = avg_time
        self.ops_per_sec = ops_per_sec

    def __str__(self):
        return (
            f"{self.name:40s} | "
            f"{self.iterations:6d} ops | "
            f"{self.total_time:8.4f}s | "
            f"{self.avg_time * 1000:8.4f}ms/op | "
            f"{self.ops_per_sec:10.2f} ops/sec"
        )


def benchmark(func: Callable, iterations: int = 1000, *args, **kwargs) -> BenchmarkResult:
    """Run a benchmark on a function."""
    start = time.perf_counter()
    for _ in range(iterations):
        func(*args, **kwargs)
    end = time.perf_counter()

    total_time = end - start
    avg_time = total_time / iterations
    ops_per_sec = iterations / total_time if total_time > 0 else 0

    return BenchmarkResult(
        name=func.__name__,
        iterations=iterations,
        total_time=total_time,
        avg_time=avg_time,
        ops_per_sec=ops_per_sec,
    )


def create_test_files(count: int, directory: Path) -> List[Path]:
    """Create test image files."""
    files = []
    for i in range(count):
        file_path = directory / f"test_image_{i}.jpg"
        # Create a small dummy file
        with open(file_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 1000)  # Minimal JPEG header + padding
        files.append(file_path)
    return files


def bench_file_validation():
    """Benchmark file validation operations."""
    print("\n" + "=" * 100)
    print("FILE VALIDATION BENCHMARKS")
    print("=" * 100)

    # Create temporary test files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        test_files = create_test_files(100, tmpdir_path)

        # Benchmark file size validation
        result = benchmark(
            validate_file_size, iterations=10000, file_path=test_files[0], max_size=100 * 1024 * 1024
        )
        print(result)

        # Benchmark file extension validation
        result = benchmark(
            validate_file_extension, iterations=10000, file_path=test_files[0]
        )
        print(result)

        # Benchmark filename sanitization
        result = benchmark(sanitize_filename, iterations=10000, filename="test_image_1.jpg")
        print(result)


def bench_directory_scanning():
    """Benchmark directory scanning operations."""
    print("\n" + "=" * 100)
    print("DIRECTORY SCANNING BENCHMARKS")
    print("=" * 100)

    # Test with different file counts
    for file_count in [10, 50, 100, 500]:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            create_test_files(file_count, tmpdir_path)

            # Benchmark directory scanning
            iterations = max(1, 100 // file_count)  # Fewer iterations for larger sets
            start = time.perf_counter()
            for _ in range(iterations):
                scan_inputs([str(tmpdir_path)], validate_size=True)
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"scan_directory_{file_count}_files",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)


def bench_nested_directory_scanning():
    """Benchmark nested directory scanning."""
    print("\n" + "=" * 100)
    print("NESTED DIRECTORY SCANNING BENCHMARKS")
    print("=" * 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create nested structure: 5 subdirs, 20 files each = 100 files total
        for i in range(5):
            subdir = tmpdir_path / f"subdir_{i}"
            subdir.mkdir()
            create_test_files(20, subdir)

        # Benchmark nested directory scanning
        iterations = 10
        start = time.perf_counter()
        for _ in range(iterations):
            scan_inputs([str(tmpdir_path)], validate_size=True)
        end = time.perf_counter()

        total_time = end - start
        avg_time = total_time / iterations
        ops_per_sec = iterations / total_time if total_time > 0 else 0

        result = BenchmarkResult(
            name="scan_nested_directories_100_files",
            iterations=iterations,
            total_time=total_time,
            avg_time=avg_time,
            ops_per_sec=ops_per_sec,
        )
        print(result)


def main():
    """Run all file operation benchmarks."""
    print("\n")
    print("╔" + "=" * 98 + "╗")
    print("║" + " " * 20 + "CONNIE'S UPLOADER - FILE OPERATIONS BENCHMARKS" + " " * 32 + "║")
    print("╚" + "=" * 98 + "╝")

    bench_file_validation()
    bench_directory_scanning()
    bench_nested_directory_scanning()

    print("\n" + "=" * 100)
    print("BENCHMARKS COMPLETE")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
