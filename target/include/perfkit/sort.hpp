#pragma once

#include <cstdint>
#include <span>

namespace perfkit {

// Production sort: introsort via std::sort.
void sort_ints(std::span<std::int64_t> values);

namespace slow {
// std::qsort: correct, but every comparison is an indirect call that the
// compiler cannot inline. Swap it in for perfkit::sort_ints to plant a
// realistic regression. (Heapsort was tried first, but under MSVC it beats
// std::sort below ~1M elements, so it is not a reliable plant.)
void sort_ints(std::span<std::int64_t> values);
}  // namespace slow

}  // namespace perfkit
