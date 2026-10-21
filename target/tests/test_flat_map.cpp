#include <catch2/catch_test_macros.hpp>

#include <unordered_map>

#include "perfkit/flat_map.hpp"
#include "perfkit/random.hpp"

TEST_CASE("FlatMap basic operations", "[flat_map]") {
    perfkit::FlatMap map;
    CHECK(map.size() == 0);
    CHECK(map.find(0) == nullptr);

    map.insert_or_assign(0, 10);  // key 0 must be a valid key
    map.insert_or_assign(7, 70);
    REQUIRE(map.find(0) != nullptr);
    CHECK(*map.find(0) == 10);
    CHECK(*map.find(7) == 70);
    CHECK(map.find(8) == nullptr);
    CHECK(map.size() == 2);

    map.insert_or_assign(7, 71);
    CHECK(*map.find(7) == 71);
    CHECK(map.size() == 2);
}

TEST_CASE("FlatMap grows and keeps load factor at or below 75%", "[flat_map]") {
    perfkit::FlatMap map;
    const auto initial_capacity = map.capacity();
    for (std::uint64_t k = 0; k < 10'000; ++k) {
        map.insert_or_assign(k, k * 2);
        REQUIRE(map.size() * 4 <= map.capacity() * 3);
    }
    CHECK(map.capacity() > initial_capacity);
    for (std::uint64_t k = 0; k < 10'000; ++k) {
        const auto* v = map.find(k);
        REQUIRE(v != nullptr);
        CHECK(*v == k * 2);
    }
}

TEST_CASE("FlatMap agrees with std::unordered_map on random operations", "[flat_map]") {
    perfkit::SplitMix64 rng(123);
    perfkit::FlatMap map;
    std::unordered_map<std::uint64_t, std::uint64_t> reference;

    // Small key space forces overwrites and long probe chains.
    for (int i = 0; i < 50'000; ++i) {
        const std::uint64_t key = rng.below(5'000);
        const std::uint64_t value = rng.next();
        map.insert_or_assign(key, value);
        reference[key] = value;
    }
    CHECK(map.size() == reference.size());
    for (std::uint64_t key = 0; key < 6'000; ++key) {
        const auto it = reference.find(key);
        const auto* v = map.find(key);
        if (it == reference.end()) {
            CHECK(v == nullptr);
        } else {
            REQUIRE(v != nullptr);
            CHECK(*v == it->second);
        }
    }
}
