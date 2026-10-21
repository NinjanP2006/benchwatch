#include "perfkit/flat_map.hpp"

#include <bit>

namespace perfkit {

namespace {
constexpr std::size_t kMinCapacity = 16;

std::size_t capacity_for(std::size_t expected_size) {
    // Keep load <= 75% once `expected_size` elements are inserted.
    const std::size_t needed = expected_size + expected_size / 3 + 1;
    return std::bit_ceil(needed < kMinCapacity ? kMinCapacity : needed);
}
}  // namespace

FlatMap::FlatMap(std::size_t expected_size) {
    rehash(capacity_for(expected_size));
}

void FlatMap::insert_or_assign(std::uint64_t key, std::uint64_t value) {
    if ((size_ + 1) * 4 > capacity() * 3) rehash(capacity() * 2);

    std::size_t i = hash(key) & mask_;
    while (used_[i]) {
        if (slots_[i].key == key) {
            slots_[i].value = value;
            return;
        }
        i = (i + 1) & mask_;
    }
    used_[i] = 1;
    slots_[i] = {key, value};
    ++size_;
}

void FlatMap::rehash(std::size_t new_capacity) {
    std::vector<Slot> old_slots = std::move(slots_);
    std::vector<std::uint8_t> old_used = std::move(used_);

    slots_.assign(new_capacity, Slot{});
    used_.assign(new_capacity, 0);
    mask_ = new_capacity - 1;
    size_ = 0;

    for (std::size_t j = 0; j < old_slots.size(); ++j) {
        if (!old_used[j]) continue;
        std::size_t i = hash(old_slots[j].key) & mask_;
        while (used_[i]) i = (i + 1) & mask_;
        used_[i] = 1;
        slots_[i] = old_slots[j];
        ++size_;
    }
}

}  // namespace perfkit
