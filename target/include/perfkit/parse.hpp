#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

namespace perfkit {

// Parses comma-separated signed 64-bit integers, e.g. "1,-20,300".
// No whitespace, no leading '+', no empty fields. An empty string yields an
// empty vector. Throws std::invalid_argument on malformed input or overflow.
std::vector<std::int64_t> parse_csv_ints(std::string_view text);

namespace slow {
// Same contract, implemented with std::istringstream + std::stoll.
std::vector<std::int64_t> parse_csv_ints(std::string_view text);
}  // namespace slow

}  // namespace perfkit
