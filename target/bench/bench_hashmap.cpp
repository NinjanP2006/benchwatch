#include <benchmark/benchmark.h>

#include <unordered_map>
#include <vector>

#include "inject.hpp"
#include "perfkit/flat_map.hpp"
#include "perfkit/random.hpp"

namespace {

constexpr std::size_t kLookupsPerIteration = 16384;

// Half the probes hit existing keys, half are random 64-bit keys that
// almost certainly miss.
std::vector<std::uint64_t> make_probes(const std::vector<std::uint64_t>& keys) {
    perfkit::SplitMix64 rng(perfkit::kDefaultSeed + 1);
    std::vector<std::uint64_t> probes(kLookupsPerIteration);
    for (auto& p : probes) p = (rng.next() & 1) ? keys[rng.below(keys.size())] : rng.next();
    return probes;
}

void BM_FlatMapLookup(benchmark::State& state) {
    const auto n = static_cast<std::size_t>(state.range(0));
    const auto keys = perfkit::random_u64s(n);
    perfkit::FlatMap map(n);
    for (std::size_t i = 0; i < n; ++i) map.insert_or_assign(keys[i], i);
    const auto probes = make_probes(keys);

    for (auto _ : state) {
        perfkit::bench::SlowdownScope inject;
        std::uint64_t sum = 0;
        for (const auto key : probes) {
            if (const auto* v = map.find(key)) sum += *v;
        }
        benchmark::DoNotOptimize(sum);
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations() * kLookupsPerIteration));
}

// Reference point for FlatMap; not part of the library under test.
void BM_StdUnorderedMapLookup(benchmark::State& state) {
    const auto n = static_cast<std::size_t>(state.range(0));
    const auto keys = perfkit::random_u64s(n);
    std::unordered_map<std::uint64_t, std::uint64_t> map;
    map.reserve(n);
    for (std::size_t i = 0; i < n; ++i) map.insert_or_assign(keys[i], i);
    const auto probes = make_probes(keys);

    for (auto _ : state) {
        perfkit::bench::SlowdownScope inject;
        std::uint64_t sum = 0;
        for (const auto key : probes) {
            if (const auto it = map.find(key); it != map.end()) sum += it->second;
        }
        benchmark::DoNotOptimize(sum);
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations() * kLookupsPerIteration));
}

// Map sizes chosen to sit roughly in L1/L2, L3, and DRAM.
BENCHMARK(BM_FlatMapLookup)->Arg(1 << 10)->Arg(1 << 16)->Arg(1 << 20)->Unit(benchmark::kMicrosecond);
BENCHMARK(BM_StdUnorderedMapLookup)->Arg(1 << 10)->Arg(1 << 16)->Arg(1 << 20)->Unit(benchmark::kMicrosecond);

}  // namespace
