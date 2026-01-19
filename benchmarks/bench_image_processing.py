# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""
Benchmarks for image processing operations including thumbnail generation.
"""

import time
import tempfile
import sys
import os
from pathlib import Path
from PIL import Image

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


def create_test_image(path: Path, size: tuple = (1920, 1080)) -> Path:
    """Create a test image file."""
    # Create a simple gradient image
    img = Image.new("RGB", size, color=(73, 109, 137))
    img.save(path, "JPEG", quality=95)
    return path


def bench_pil_operations():
    """Benchmark PIL image operations."""
    print("\n" + "=" * 100)
    print("PIL IMAGE OPERATIONS BENCHMARKS")
    print("=" * 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create test images of different sizes
        test_images = {
            "small": create_test_image(tmpdir_path / "small.jpg", (800, 600)),
            "medium": create_test_image(tmpdir_path / "medium.jpg", (1920, 1080)),
            "large": create_test_image(tmpdir_path / "large.jpg", (3840, 2160)),
        }

        for size_name, img_path in test_images.items():
            # Benchmark image loading
            iterations = 100
            start = time.perf_counter()
            for _ in range(iterations):
                img = Image.open(img_path)
                img.close()
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"load_image_{size_name}",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)

            # Benchmark thumbnail generation
            iterations = 100
            start = time.perf_counter()
            for _ in range(iterations):
                img = Image.open(img_path)
                img.thumbnail((100, 100))
                img.close()
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"thumbnail_{size_name}",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)

            # Benchmark image resizing
            iterations = 100
            start = time.perf_counter()
            for _ in range(iterations):
                img = Image.open(img_path)
                img.resize((800, 600))
                img.close()
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"resize_{size_name}",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)


def bench_batch_operations():
    """Benchmark batch image processing operations."""
    print("\n" + "=" * 100)
    print("BATCH IMAGE PROCESSING BENCHMARKS")
    print("=" * 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create multiple test images
        batch_sizes = [10, 50, 100]

        for batch_size in batch_sizes:
            images = []
            for i in range(batch_size):
                img_path = tmpdir_path / f"batch_{i}.jpg"
                create_test_image(img_path, (1920, 1080))
                images.append(img_path)

            # Benchmark batch loading
            iterations = max(1, 10 // (batch_size // 10))  # Fewer iterations for larger batches
            start = time.perf_counter()
            for _ in range(iterations):
                for img_path in images:
                    img = Image.open(img_path)
                    img.close()
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"batch_load_{batch_size}_images",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)

            # Benchmark batch thumbnail generation
            start = time.perf_counter()
            for _ in range(iterations):
                for img_path in images:
                    img = Image.open(img_path)
                    img.thumbnail((100, 100))
                    img.close()
            end = time.perf_counter()

            total_time = end - start
            avg_time = total_time / iterations
            ops_per_sec = iterations / total_time if total_time > 0 else 0

            result = BenchmarkResult(
                name=f"batch_thumbnail_{batch_size}_images",
                iterations=iterations,
                total_time=total_time,
                avg_time=avg_time,
                ops_per_sec=ops_per_sec,
            )
            print(result)


def main():
    """Run all image processing benchmarks."""
    print("\n")
    print("╔" + "=" * 98 + "╗")
    print("║" + " " * 20 + "CONNIE'S UPLOADER - IMAGE PROCESSING BENCHMARKS" + " " * 31 + "║")
    print("╚" + "=" * 98 + "╝")

    bench_pil_operations()
    bench_batch_operations()

    print("\n" + "=" * 100)
    print("BENCHMARKS COMPLETE")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
