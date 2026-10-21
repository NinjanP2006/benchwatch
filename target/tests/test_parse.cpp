#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>

#include <stdexcept>
#include <string>

#include "perfkit/parse.hpp"
#include "perfkit/random.hpp"

using ParseFn = std::vector<std::int64_t> (*)(std::string_view);
using Ints = std::vector<std::int64_t>;

TEST_CASE("CSV integer parsers share one contract", "[parse]") {
    const auto [name, parse] = GENERATE(table<const char*, ParseFn>({
        {"from_chars", &perfkit::parse_csv_ints},
        {"stoll", &perfkit::slow::parse_csv_ints},
    }));
    INFO("implementation: " << name);

    SECTION("valid input") {
        CHECK(parse("") == Ints{});
        CHECK(parse("0") == Ints{0});
        CHECK(parse("1,-20,300") == Ints{1, -20, 300});
        CHECK(parse("9223372036854775807,-9223372036854775808") == Ints{INT64_MAX, INT64_MIN});
    }

    SECTION("malformed input throws") {
        const std::string bad = GENERATE(as<std::string>{},
            ",", "1,", ",1", "1,,2", "1;2", "abc", "1a", " 1", "+1", "1 ", "-",
            "9223372036854775808",  // overflow
            "-9223372036854775809");
        INFO("input: '" << bad << "'");
        CHECK_THROWS_AS(parse(bad), std::invalid_argument);
    }
}

TEST_CASE("Parsers agree on generated benchmark input", "[parse]") {
    const auto text = perfkit::random_csv_ints(5'000);
    const auto fast = perfkit::parse_csv_ints(text);
    CHECK(fast.size() == 5'000);
    CHECK(fast == perfkit::slow::parse_csv_ints(text));
}

TEST_CASE("Generated data is deterministic for a seed", "[parse][random]") {
    CHECK(perfkit::random_csv_ints(100, 7) == perfkit::random_csv_ints(100, 7));
    CHECK(perfkit::random_csv_ints(100, 7) != perfkit::random_csv_ints(100, 8));
    // Golden value: guards against accidental changes to the generator, which
    // would silently change every benchmark's input.
    CHECK(perfkit::SplitMix64(0).next() == 0xE220A8397B1DCDAFULL);
}
