# Benchwatch

Benchmarks every pull request against its merge-base and reports, per benchmark, whether
the change caused a statistically meaningful slowdown.

## Benchmark target (`target/`)

A small C++20 library, `perfkit`, with kernels of different performance profiles:

| Kernel | Benchmarks | Profile |
|---|---|---|
| `sort_ints` (std::sort) | `BM_Sort/{4K,64K,1M}` | compute, branchy |
| `FlatMap` (open addressing) | `BM_FlatMapLookup/{1K,64K,1M}` | cache / latency |
| std::unordered_map (reference) | `BM_StdUnorderedMapLookup/{1K,64K,1M}` | pointer chasing |
| `parse_csv_ints` (std::from_chars) | `BM_ParseCsvInts/{4K,64K}` | byte-at-a-time parsing |
| `strided_sum` | `BM_StridedSum/{32KiB,8MiB,64MiB}` | memory bandwidth (64MiB is deliberately noisy) |

Each function in `perfkit::slow` (heapsort, stoll-based parser) is a correct but slower version of the matching production function. Swap one in to plant a real algorithmic regression.
All inputs come from a fixed-seed SplitMix64 generator, so they are identical across compilers and platforms.

### Build and run

Linux / WSL / Docker:

```sh
cmake -S target -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
./build/bench --benchmark_format=json --benchmark_repetitions=5
```

Windows (MSVC):

```sh
cmake -S target -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
build/Release/bench.exe --benchmark_format=json --benchmark_repetitions=5
```

### Synthetic slowdown injection

To validate the detector against slowdowns of known size, build a second copy with:

```sh
cmake -S target -B build-inject5 -DPERFKIT_INJECT_SLOWDOWN_PCT=5
```

Every benchmark iteration then busy-waits for an extra 5% of its own measured duration
(see `target/bench/inject.hpp`). At the default of `0` the hook compiles away entirely.
