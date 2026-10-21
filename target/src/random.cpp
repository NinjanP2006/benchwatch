#include "perfkit/random.hpp"

#include <charconv>

namespace perfkit {

std::vector<std::int64_t> random_i64s(std::size_t n, std::uint64_t seed) {
    SplitMix64 rng(seed);
    std::vector<std::int64_t> out(n);
    for (auto& v : out) v = static_cast<std::int64_t>(rng.next());
    return out;
}

std::vector<std::uint64_t> random_u64s(std::size_t n, std::uint64_t seed) {
    SplitMix64 rng(seed);
    std::vector<std::uint64_t> out(n);
    for (auto& v : out) v = rng.next();
    return out;
}

std::string random_csv_ints(std::size_t n, std::uint64_t seed) {
    // Mix of magnitudes so digit counts vary: 1 to 19 digits.
    static constexpr std::int64_t kMagnitudes[] = {
        10, 1'000, 1'000'000, 1'000'000'000'000LL, 1'000'000'000'000'000'000LL};

    SplitMix64 rng(seed);
    std::string out;
    out.reserve(n * 8);
    char buf[24];
    for (std::size_t i = 0; i < n; ++i) {
        const std::int64_t mag = kMagnitudes[rng.below(std::size(kMagnitudes))];
        std::int64_t v = static_cast<std::int64_t>(rng.below(static_cast<std::uint64_t>(mag)));
        if (rng.next() & 1) v = -v;
        if (i) out.push_back(',');
        const auto res = std::to_chars(buf, buf + sizeof buf, v);
        out.append(buf, res.ptr);
    }
    return out;
}

}  // namespace perfkit
