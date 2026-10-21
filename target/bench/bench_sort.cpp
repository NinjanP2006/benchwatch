#include <benchmark/benchmark.h>

#include <algorithm>
#include <vector>

#include "inject.hpp"
#include "perfkit/random.hpp"
#include "perfkit/sort.hpp"

namespace {

void BM_Sort(benchmark::State& state) {
    const auto n = static_cast<std::size_t>(state.range(0));
    const std::vector<std::int64_t> input = perfkit::random_i64s(n);
    std::vector<std::int64_t> work(n);

    for (auto _ : state) {
        perfkit::bench::SlowdownScope inject;
        std::copy(input.begin(), input.end(), work.begin());
        perfkit::sort_ints(work);
        benchmark::DoNotOptimize(work.data());
        benchmark::ClobberMemory();
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations() * n));
}

BENCHMARK(BM_Sort)->RangeMultiplier(16)->Range(1 << 12, 1 << 20)->Unit(benchmark::kMicrosecond);

}  // namespace
