#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace perfkit {

// Open-addressing hash map from uint64 to uint64 with linear probing.
// Insert and lookup only; no erase. Grows at 75% load.
class FlatMap {
public:
    explicit FlatMap(std::size_t expected_size = 0);

    void insert_or_assign(std::uint64_t key, std::uint64_t value);

    // Returns nullptr when the key is absent. Pointer is invalidated by insertion.
    const std::uint64_t* find(std::uint64_t key) const noexcept {
        std::size_t i = hash(key) & mask_;
        while (used_[i]) {
            if (slots_[i].key == key) return &slots_[i].value;
            i = (i + 1) & mask_;
        }
        return nullptr;
    }

    std::size_t size() const noexcept { return size_; }
    std::size_t capacity() const noexcept { return slots_.size(); }

private:
    struct Slot {
        std::uint64_t key;
        std::uint64_t value;
    };

    static std::uint64_t hash(std::uint64_t key) noexcept {
        key = (key ^ (key >> 30)) * 0xBF58476D1CE4E5B9ULL;
        key = (key ^ (key >> 27)) * 0x94D049BB133111EBULL;
        return key ^ (key >> 31);
    }

    void rehash(std::size_t new_capacity);

    std::vector<Slot> slots_;
    std::vector<std::uint8_t> used_;
    std::size_t mask_ = 0;
    std::size_t size_ = 0;
};

}  // namespace perfkit
