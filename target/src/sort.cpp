#include "perfkit/sort.hpp"

#include <algorithm>
#include <cstdlib>

namespace perfkit {

void sort_ints(std::span<std::int64_t> values) {
    std::sort(values.begin(), values.end());
}

namespace slow {

void sort_ints(std::span<std::int64_t> values) {
    std::qsort(values.data(), values.size(), sizeof(std::int64_t), [](const void* a, const void* b) {
        const auto x = *static_cast<const std::int64_t*>(a);
        const auto y = *static_cast<const std::int64_t*>(b);
        return (x > y) - (x < y);
    });
}

}  // namespace slow
}  // namespace perfkit
