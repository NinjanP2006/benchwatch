#pragma once

// Synthetic slowdown injection, used to validate the regression detector
// against slowdowns of known size.
//
// Configure with -DPERFKIT_INJECT_SLOWDOWN_PCT=5 and every benchmark iteration
// wrapped in a SlowdownScope busy-waits for an extra 5% of its own measured
// duration. Busy-waiting (not sleeping) keeps the core occupied, like real
// extra work would.
//
// With the default of 0 the scope is an empty object and compiles away, so the
// normal build carries no clock reads. The injected build adds about three
// clock reads per iteration, which we subtract from the spin target; any
// residual bias is around 0.1% for the >=20us iterations used in this suite.

#include <algorithm>
#include <chrono>

#ifndef BENCH_INJECT_SLOWDOWN_PCT
#define BENCH_INJECT_SLOWDOWN_PCT 0
#endif

namespace perfkit::bench {

inline constexpr double kInjectSlowdownPct = BENCH_INJECT_SLOWDOWN_PCT;
inline constexpr bool kInjectEnabled = kInjectSlowdownPct > 0.0;

class SlowdownScope {
    using Clock = std::chrono::steady_clock;
    using Nanos = std::chrono::duration<double, std::nano>;

public:
    SlowdownScope() noexcept {
        if constexpr (kInjectEnabled) start_ = Clock::now();
    }

    ~SlowdownScope() {
        if constexpr (kInjectEnabled) {
            const auto stop = Clock::now();
            const Nanos target = Nanos(stop - start_) * (kInjectSlowdownPct / 100.0) - 3 * clock_read_cost();
            const auto deadline = stop + std::chrono::duration_cast<Clock::duration>(std::max(target, Nanos(0)));
            while (Clock::now() < deadline) {
            }
        }
    }

    SlowdownScope(const SlowdownScope&) = delete;
    SlowdownScope& operator=(const SlowdownScope&) = delete;

private:
    static Nanos clock_read_cost() {
        static const Nanos cost = [] {
            constexpr int kReads = 100'000;
            const auto t0 = Clock::now();
            for (int i = 0; i < kReads; ++i) (void)Clock::now();
            return Nanos(Clock::now() - t0) / kReads;
        }();
        return cost;
    }

    Clock::time_point start_{};
};

}  // namespace perfkit::bench
