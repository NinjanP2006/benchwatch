#include "perfkit/parse.hpp"

#include <charconv>
#include <sstream>
#include <stdexcept>
#include <string>

namespace perfkit {

std::vector<std::int64_t> parse_csv_ints(std::string_view text) {
    std::vector<std::int64_t> out;
    if (text.empty()) return out;

    const char* p = text.data();
    const char* const end = p + text.size();
    for (;;) {
        std::int64_t value = 0;
        const auto [next, ec] = std::from_chars(p, end, value);
        if (ec != std::errc{}) throw std::invalid_argument("parse_csv_ints: bad integer");
        out.push_back(value);
        p = next;
        if (p == end) return out;
        if (*p != ',') throw std::invalid_argument("parse_csv_ints: expected ','");
        if (++p == end) throw std::invalid_argument("parse_csv_ints: trailing ','");
    }
}

namespace slow {

std::vector<std::int64_t> parse_csv_ints(std::string_view text) {
    std::vector<std::int64_t> out;
    if (text.empty()) return out;
    if (text.back() == ',') throw std::invalid_argument("parse_csv_ints: trailing ','");

    std::istringstream in{std::string(text)};
    std::string field;
    while (std::getline(in, field, ',')) {
        // std::stoll is laxer than from_chars; reject what it would accept but we don't.
        if (field.empty() || field.front() == '+' || field.front() == ' ' ||
            field.front() == '\t' || field.front() == '\n') {
            throw std::invalid_argument("parse_csv_ints: bad integer");
        }
        std::size_t consumed = 0;
        long long value = 0;
        try {
            value = std::stoll(field, &consumed);
        } catch (const std::exception&) {
            throw std::invalid_argument("parse_csv_ints: bad integer");
        }
        if (consumed != field.size()) throw std::invalid_argument("parse_csv_ints: expected ','");
        out.push_back(value);
    }
    return out;
}

}  // namespace slow
}  // namespace perfkit
