#include "perfkit/memory.hpp"

#include <stdexcept>

namespace perfkit {

std::uint64_t strided_sum(std::span<const std::uint32_t> data, std::size_t stride,
                          std::size_t accesses) {
    const std::size_t n = data.size();
    if (stride == 0 || stride >= n) throw std::invalid_argument("strided_sum: need 0 < stride < size");

    std::uint64_t sum = 0;
    std::size_t idx = 0;
    for (std::size_t k = 0; k < accesses; ++k) {
        sum += data[idx];
        idx += stride;
        if (idx >= n) idx -= n;
    }
    return sum;
}

}  // namespace perfkit
