#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>

#include <algorithm>
#include <vector>

#include "perfkit/random.hpp"
#include "perfkit/sort.hpp"

using SortFn = void (*)(std::span<std::int64_t>);

TEST_CASE("sort implementations produce a sorted permutation", "[sort]") {
    const auto [name, sort_fn] = GENERATE(table<const char*, SortFn>({
        {"std", &perfkit::sort_ints},
        {"heap", &perfkit::slow::sort_ints},
    }));
    INFO("implementation: " << name);

    SECTION("empty and single element") {
        std::vector<std::int64_t> empty;
        sort_fn(empty);
        CHECK(empty.empty());

        std::vector<std::int64_t> one{42};
        sort_fn(one);
        CHECK(one == std::vector<std::int64_t>{42});
    }

    SECTION("duplicates and extremes") {
        std::vector<std::int64_t> v{5, INT64_MIN, 5, 0, INT64_MAX, -1, 5};
        sort_fn(v);
        CHECK(v == std::vector<std::int64_t>{INT64_MIN, -1, 0, 5, 5, 5, INT64_MAX});
    }

    SECTION("random input matches std::sort") {
        const auto n = GENERATE(2u, 17u, 1000u, 65536u);
        auto v = perfkit::random_i64s(n, n);
        auto expected = v;
        std::sort(expected.begin(), expected.end());
        sort_fn(v);
        CHECK(v == expected);
    }
}
