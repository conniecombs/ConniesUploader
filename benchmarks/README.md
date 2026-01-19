# Performance Benchmarks

This directory contains performance benchmarks for Connie's Uploader Ultimate.

## Available Benchmarks

### 1. File Operations Benchmarks (`bench_file_operations.py`)
Tests the performance of file scanning, validation, and processing operations:
- File size validation
- File extension validation
- Filename validation
- Directory scanning (various file counts)
- Nested directory scanning

### 2. Image Processing Benchmarks (`bench_image_processing.py`)
Tests the performance of image processing operations:
- Image loading (small, medium, large)
- Thumbnail generation
- Image resizing
- Batch processing operations

## Running Benchmarks

### Run All Benchmarks
```bash
# Run file operations benchmarks
python benchmarks/bench_file_operations.py

# Run image processing benchmarks
python benchmarks/bench_image_processing.py
```

### Run Individual Benchmarks
```bash
# From project root
python -m benchmarks.bench_file_operations
python -m benchmarks.bench_image_processing
```

## Understanding Results

Each benchmark displays results in the following format:
```
benchmark_name                           | iterations | total_time | avg_time/op | ops/sec
---------------------------------------- | ---------- | ---------- | ----------- | ----------
validate_file_size                       |  10000 ops |   0.1234s |   0.0123ms/op |  81037.21 ops/sec
```

### Key Metrics

- **iterations**: Number of times the operation was repeated
- **total_time**: Total time for all iterations (seconds)
- **avg_time/op**: Average time per operation (milliseconds)
- **ops/sec**: Operations per second (throughput)

### Performance Baselines

These benchmarks establish performance baselines to:
1. Track performance over time
2. Identify performance regressions
3. Compare optimization strategies
4. Validate performance improvements

## Adding New Benchmarks

To add a new benchmark:

1. Create a new file `bench_<category>.py`
2. Import the `BenchmarkResult` class or create your own
3. Write benchmark functions following the existing pattern
4. Update this README with the new benchmark information

### Example Benchmark Function

```python
def bench_my_operation():
    """Benchmark description."""
    print("\\n" + "=" * 100)
    print("MY OPERATION BENCHMARKS")
    print("=" * 100)

    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        # Your operation here
        my_function()
    end = time.perf_counter()

    total_time = end - start
    avg_time = total_time / iterations
    ops_per_sec = iterations / total_time

    result = BenchmarkResult(
        name="my_operation",
        iterations=iterations,
        total_time=total_time,
        avg_time=avg_time,
        ops_per_sec=ops_per_sec
    )
    print(result)
```

## CI/CD Integration

To track performance over time, consider:
- Running benchmarks in CI/CD
- Storing results in artifacts
- Comparing against baseline metrics
- Setting performance regression thresholds

## Notes

- Benchmarks use temporary files and directories
- All test data is automatically cleaned up
- Results may vary based on system resources
- Run benchmarks multiple times for consistent results
- Avoid running benchmarks during heavy system load
