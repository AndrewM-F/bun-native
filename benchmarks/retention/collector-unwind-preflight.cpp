// Compile and exercise the diagnostic header against the installed Windows SDK.
#include <cstdint>
#include <cstdio>
#define NEVER_INLINE __declspec(noinline)
static unsigned counts[14] {};
extern "C" void BNCollectorTraceRecord(uint32_t kind, const void* source, const void* target)
{
    if (kind < 14 && source && target)
        ++counts[kind];
}
#include "collector-unwind.h"
static NEVER_INLINE void exercise() { BNCollectorTraceFrames(); }
int main()
{
    exercise();
    std::printf("frame_ranges=%u pcs=%u image_bases=%u\n", counts[11], counts[12], counts[13]);
    return counts[11] && counts[12] && counts[13] ? 0 : 1;
}
