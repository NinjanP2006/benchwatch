#include "perfkit/sort.hpp"

#include <algorithm>

namespace perfkit {

void sort_ints(std::span<std::int64_t> values) {
    std::sort(values.begin(), values.end());
}

namespace slow {

void sort_ints(std::span<std::int64_t> values) {
    std::make_heap(values.begin(), values.end());
    std::sort_heap(values.begin(), values.end());
}

}  // namespace slow
}  // namespace perfkit
