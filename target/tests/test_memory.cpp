#include <catch2/catch_test_macros.hpp>

#include <numeric>
#include <stdexcept>
#include <vector>

#include "perfkit/memory.hpp"

TEST_CASE("strided_sum matches a naive modulo walk", "[memory]") {
    std::vector<std::uint32_t> data(1000);
    std::iota(data.begin(), data.end(), 1u);

    for (const std::size_t stride : {1u, 3u, 16u, 999u}) {
        std::uint64_t expected = 0;
        for (std::size_t k = 0; k < 5000; ++k) expected += data[(k * stride) % data.size()];
        INFO("stride " << stride);
        CHECK(perfkit::strided_sum(data, stride, 5000) == expected);
    }
}

TEST_CASE("strided_sum rejects invalid strides", "[memory]") {
    std::vector<std::uint32_t> data(10, 1);
    CHECK_THROWS_AS(perfkit::strided_sum(data, 0, 5), std::invalid_argument);
    CHECK_THROWS_AS(perfkit::strided_sum(data, 10, 5), std::invalid_argument);
    CHECK(perfkit::strided_sum(data, 3, 0) == 0);
}
