#include <benchmark/benchmark.h>

#include <vector>

#include "inject.hpp"
#include "perfkit/memory.hpp"
#include "perfkit/random.hpp"

namespace {

constexpr std::size_t kAccesses = 1 << 18;
constexpr std::size_t kCacheLineStride = 64 / sizeof(std::uint32_t);

// Memory-bound kernel, one access per cache line. Its noise is dominated by
// the memory subsystem rather than the core, which makes it a useful
// contrast case when tuning the detector.
void BM_StridedSum(benchmark::State& state) {
    const auto bytes = static_cast<std::size_t>(state.range(0));
    std::vector<std::uint32_t> data(bytes / sizeof(std::uint32_t));
    perfkit::SplitMix64 rng(perfkit::kDefaultSeed);
    for (auto& v : data) v = static_cast<std::uint32_t>(rng.next());

    for (auto _ : state) {
        perfkit::bench::SlowdownScope inject;
        benchmark::DoNotOptimize(perfkit::strided_sum(data, kCacheLineStride, kAccesses));
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations() * kAccesses));
}

// Working sets: 32 KiB (L1), 8 MiB (L3), 64 MiB (DRAM).
BENCHMARK(BM_StridedSum)->Arg(32 << 10)->Arg(8 << 20)->Arg(64 << 20)->Unit(benchmark::kMicrosecond);

}  // namespace
