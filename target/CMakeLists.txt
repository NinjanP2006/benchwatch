cmake_minimum_required(VERSION 3.24)
project(perfkit LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(PERFKIT_BUILD_TESTS "Build Catch2 correctness tests" ON)
option(PERFKIT_BUILD_BENCHMARKS "Build Google Benchmark targets" ON)
set(PERFKIT_INJECT_SLOWDOWN_PCT "0" CACHE STRING
    "Synthetic slowdown (percent of iteration time) added to every benchmark iteration; 0 disables")

if(NOT PERFKIT_INJECT_SLOWDOWN_PCT MATCHES "^[0-9]+(\\.[0-9]+)?$")
  message(FATAL_ERROR "PERFKIT_INJECT_SLOWDOWN_PCT must be a non-negative number, got '${PERFKIT_INJECT_SLOWDOWN_PCT}'")
endif()

# ---- Warnings ---------------------------------------------------------------
add_library(perfkit_warnings INTERFACE)
if(MSVC)
  target_compile_options(perfkit_warnings INTERFACE /W4 /permissive- /utf-8)
else()
  target_compile_options(perfkit_warnings INTERFACE -Wall -Wextra -Wpedantic)
endif()

# ---- Library under test -----------------------------------------------------
add_library(perfkit
  src/sort.cpp
  src/flat_map.cpp
  src/parse.cpp
  src/memory.cpp
  src/random.cpp
)
target_include_directories(perfkit PUBLIC include)
target_link_libraries(perfkit PRIVATE perfkit_warnings)

# ---- Third-party (pinned) ---------------------------------------------------
include(FetchContent)

if(PERFKIT_BUILD_BENCHMARKS)
  set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_WERROR OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(googlebenchmark
    GIT_REPOSITORY https://github.com/google/benchmark.git
    GIT_TAG        v1.9.1
    GIT_SHALLOW    TRUE
  )
  FetchContent_MakeAvailable(googlebenchmark)

  add_executable(bench
    bench/bench_sort.cpp
    bench/bench_hashmap.cpp
    bench/bench_parse.cpp
    bench/bench_memory.cpp
  )
  target_include_directories(bench PRIVATE bench)
  target_link_libraries(bench PRIVATE perfkit perfkit_warnings benchmark::benchmark_main)
  target_compile_definitions(bench PRIVATE BENCH_INJECT_SLOWDOWN_PCT=${PERFKIT_INJECT_SLOWDOWN_PCT})
endif()

if(PERFKIT_BUILD_TESTS)
  FetchContent_Declare(Catch2
    GIT_REPOSITORY https://github.com/catchorg/Catch2.git
    GIT_TAG        v3.7.1
    GIT_SHALLOW    TRUE
  )
  FetchContent_MakeAvailable(Catch2)

  add_executable(perfkit_tests
    tests/test_sort.cpp
    tests/test_flat_map.cpp
    tests/test_parse.cpp
    tests/test_memory.cpp
  )
  target_link_libraries(perfkit_tests PRIVATE perfkit perfkit_warnings Catch2::Catch2WithMain)

  enable_testing()
  add_test(NAME perfkit_tests COMMAND perfkit_tests)
endif()
