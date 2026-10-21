#include <benchmark/benchmark.h>

#include <string>

#include "inject.hpp"
#include "perfkit/parse.hpp"
#include "perfkit/random.hpp"

namespace {

void BM_ParseCsvInts(benchmark::State& state) {
    const auto n = static_cast<std::size_t>(state.range(0));
    const std::string text = perfkit::random_csv_ints(n);

    for (auto _ : state) {
        perfkit::bench::SlowdownScope inject;
        auto values = perfkit::parse_csv_ints(text);
        benchmark::DoNotOptimize(values.data());
    }
    state.SetBytesProcessed(static_cast<std::int64_t>(state.iterations() * text.size()));
}

BENCHMARK(BM_ParseCsvInts)->Arg(1 << 12)->Arg(1 << 16)->Unit(benchmark::kMicrosecond);

}  // namespace
