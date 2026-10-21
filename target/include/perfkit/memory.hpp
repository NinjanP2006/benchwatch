#pragma once

#include <cstddef>
#include <cstdint>
#include <span>

namespace perfkit {

// Sums `accesses` elements starting at index 0 and advancing by `stride`,
// wrapping around the end of `data`. Memory-bound when `data` exceeds the
// cache. Throws std::invalid_argument unless 0 < stride < data.size().
std::uint64_t strided_sum(std::span<const std::uint32_t> data, std::size_t stride,
                          std::size_t accesses);

}  // namespace perfkit
