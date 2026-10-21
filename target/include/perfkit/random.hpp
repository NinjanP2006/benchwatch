#pragma once

// Deterministic data generation shared by tests and benchmarks.
//
// std::mt19937 is portable, but the std:: distributions are not: libstdc++ and
// MSVC produce different values for the same seed. Benchmarks must see
// identical inputs on every platform, so we use SplitMix64 and our own
// range reduction instead.

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace perfkit {

class SplitMix64 {
public:
    explicit constexpr SplitMix64(std::uint64_t seed) noexcept : state_(seed) {}

    constexpr std::uint64_t next() noexcept {
        std::uint64_t z = (state_ += 0x9E3779B97F4A7C15ULL);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        return z ^ (z >> 31);
    }

    // Uniform-ish in [0, bound). Modulo bias is irrelevant for benchmark inputs.
    constexpr std::uint64_t below(std::uint64_t bound) noexcept { return next() % bound; }

private:
    std::uint64_t state_;
};

inline constexpr std::uint64_t kDefaultSeed = 0x5EED'BE7C'0000'0001ULL;

std::vector<std::int64_t> random_i64s(std::size_t n, std::uint64_t seed = kDefaultSeed);
std::vector<std::uint64_t> random_u64s(std::size_t n, std::uint64_t seed = kDefaultSeed);

// Comma-separated signed integers spanning a range of digit counts, e.g. "-12,90817,3".
std::string random_csv_ints(std::size_t n, std::uint64_t seed = kDefaultSeed);

}  // namespace perfkit
