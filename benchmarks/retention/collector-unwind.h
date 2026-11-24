// Diagnostic-only Windows x64 unwind snapshot taken immediately before GC.
// Missing unwind entries stop the walk: do not guess a leaf frame or stack slot.
#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <cstdint>

extern "C" void BNCollectorTraceRecord(uint32_t, const void*, const void*);

static NEVER_INLINE void BNCollectorTraceFrames()
{
    ULONG_PTR low = 0, high = 0;
    GetCurrentThreadStackLimits(&low, &high);
    CONTEXT context {};
    RtlCaptureContext(&context);
    for (unsigned i = 0; i < 64; ++i) {
        const auto start = context.Rsp;
        const auto pc = context.Rip;
        if (!pc || start < low || start >= high)
            break;
        BNCollectorTraceRecord(12, reinterpret_cast<const void*>(start), reinterpret_cast<const void*>(pc));
        DWORD64 imageBase = 0;
        auto* entry = RtlLookupFunctionEntry(pc, &imageBase, nullptr);
        if (!entry || !imageBase)
            break;
        BNCollectorTraceRecord(13, reinterpret_cast<const void*>(start), reinterpret_cast<const void*>(imageBase));
        void* handler = nullptr;
        DWORD64 establisher = 0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER, imageBase, pc, entry, &context, &handler, &establisher, nullptr);
        if (context.Rsp <= start || context.Rsp > high)
            break;
        BNCollectorTraceRecord(11, reinterpret_cast<const void*>(start), reinterpret_cast<const void*>(context.Rsp));
    }
}
