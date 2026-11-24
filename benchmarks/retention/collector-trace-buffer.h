// Diagnostic-only fixed buffer. No allocation, locks or I/O on collector paths.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

#ifndef BN_TRACE_CAPACITY
#define BN_TRACE_CAPACITY 2097152u
#endif

namespace BNTrace {
struct Record { uintptr_t source; uintptr_t target; uint32_t kind; uint32_t reserved; };
struct Header { char magic[8]; uint32_t version; uint32_t stride; uint64_t epoch; uint64_t attempted; uint64_t written; };
static_assert(sizeof(Record) == 24 && sizeof(Header) == 40);
static Record records[BN_TRACE_CAPACITY];
static std::atomic<uint64_t> epoch { 0 }, nextEpoch { 0 }, count { 0 }, writers { 0 };
static std::atomic_flag busy = ATOMIC_FLAG_INIT;
static char destination[4096];

static uint64_t begin()
{
    const char* directory = std::getenv("BN_COLLECTOR_TRACE_DIR");
    if (!directory || !*directory || std::strlen(directory) > 3500)
        return 0;
    // A concurrent VM is not attributable to a single collection. Fail closed.
    if (busy.test_and_set(std::memory_order_acquire))
        return 0;
    uint64_t next = nextEpoch.fetch_add(1, std::memory_order_relaxed) + 1;
    if (!next) {
        busy.clear(std::memory_order_release);
        return 0;
    }
#if defined(_WIN32)
    const auto pid = static_cast<unsigned long>(_getpid());
#else
    const auto pid = static_cast<unsigned long>(getpid());
#endif
    int n = std::snprintf(destination, sizeof(destination), "%s/bn-gc-%lu-%llu.bin", directory, pid, static_cast<unsigned long long>(next));
    if (n < 0 || static_cast<size_t>(n) >= sizeof(destination)) {
        busy.clear(std::memory_order_release);
        return 0;
    }
    count.store(0, std::memory_order_release);
    epoch.store(next, std::memory_order_release);
    return next;
}

static void record(uint32_t kind, const void* source, const void* target)
{
    uint64_t current = epoch.load(std::memory_order_acquire);
    if (!current)
        return;
    writers.fetch_add(1, std::memory_order_acq_rel);
    if (epoch.load(std::memory_order_acquire) == current) {
        uint64_t index = count.fetch_add(1, std::memory_order_relaxed);
        if (index < BN_TRACE_CAPACITY)
            records[index] = { reinterpret_cast<uintptr_t>(source), reinterpret_cast<uintptr_t>(target), kind, 0 };
    }
    writers.fetch_sub(1, std::memory_order_release);
}

static bool finish(uint64_t current)
{
    if (!current)
        return false;
    uint64_t expected = current;
    if (!epoch.compare_exchange_strong(expected, 0, std::memory_order_acq_rel))
        return false;
    while (writers.load(std::memory_order_acquire)) { }
    const uint64_t attempted = count.load(std::memory_order_acquire);
    const uint64_t written = attempted < BN_TRACE_CAPACITY ? attempted : BN_TRACE_CAPACITY;
    Header header { { 'B','N','G','C','T','R','C','1' }, 1, sizeof(Record), current, attempted, written };
    FILE* file = std::fopen(destination, "wb");
    if (!file) {
        std::fprintf(stderr, "BN collector trace: cannot open output\n");
        busy.clear(std::memory_order_release);
        return false;
    }
    bool ok = std::fwrite(&header, sizeof(header), 1, file) == 1;
    ok = (std::fwrite(records, sizeof(Record), static_cast<size_t>(written), file) == written) && ok;
    ok = (std::fclose(file) == 0) && ok;
    if (!ok)
        std::fprintf(stderr, "BN collector trace: incomplete output\n");
    busy.clear(std::memory_order_release);
    return ok;
}
}
