#pragma once

#include <cstdint>
#include <span>

namespace perfkit {

// Production sort: introsort via std::sort.
void sort_ints(std::span<std::int64_t> values);

namespace slow {
// Heapsort: correct but ~2-3x slower on large inputs. Swap it in for
// perfkit::sort_ints to plant a realistic algorithmic regression.
void sort_ints(std::span<std::int64_t> values);
}  // namespace slow

}  // namespace perfkit
