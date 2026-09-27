/*
  Stockfish, a UCI chess playing engine derived from Glaurung 2.1
  Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)

  Stockfish is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  Stockfish is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "memory.h"

#include <cstdlib>
#include <iostream>  // std::cerr

#if __has_include("features.h")
    #include <features.h>
#endif

#if defined(__linux__) && !defined(__ANDROID__)
    #include <errno.h>
    #include <sys/mman.h>
    // IWYU pragma: no_include <bits/mman-map-flags-generic.h>
    #include <cstring>
    #include <mutex>
    #include <map>
#endif

#if defined(__APPLE__) || defined(__ANDROID__) || defined(__OpenBSD__) \
  || (defined(__GLIBCXX__) && !defined(_GLIBCXX_HAVE_ALIGNED_ALLOC) && !defined(_WIN32)) \
  || defined(__e2k__)
    #define POSIXALIGNEDALLOC
    #include <stdlib.h>
#endif

#ifdef _WIN32
    #if _WIN32_WINNT < 0x0601
        #undef _WIN32_WINNT
        #define _WIN32_WINNT 0x0601  // Force to include needed API prototypes
    #endif

    #ifndef NOMINMAX
        #define NOMINMAX
    #endif

    #include <ios>  // std::hex, std::dec
    #include <windows.h>

// The needed Windows API for processor groups could be missed from old Windows
// versions, so instead of calling them directly (forcing the linker to resolve
// the calls at compile time), try to load them at runtime. To do this we need
// first to define the corresponding function pointers.

#endif


namespace Stockfish {

// Wrappers for systems where the c++17 implementation does not guarantee the
// availability of aligned_alloc(). Memory allocated with std_aligned_alloc()
// must be freed with std_aligned_free().

void* std_aligned_alloc(usize alignment, usize size) {
    if (alignment < sizeof(void*)) alignment = sizeof(void*);
    usize total = size + alignment + sizeof(void*);
    void* raw = std::malloc(total);
    if (!raw) return nullptr;
    uintptr_t addr = (uintptr_t)raw + sizeof(void*);
    void* aligned = (void*)((addr + alignment - 1) & ~(alignment - 1));
    ((void**)aligned)[-1] = raw;
    return aligned;
}

void std_aligned_free(void* ptr) {
    if (ptr) {
        std::free(((void**)ptr)[-1]);
    }
}

// aligned_large_pages_alloc() will return suitably aligned memory,
// if possible using large pages.

#if defined(_WIN32)

static void* aligned_large_pages_alloc_windows([[maybe_unused]] usize allocSize) {

    return windows_try_with_large_page_priviliges(
      [&](usize largePageSize) {
          // Round up size to full pages and allocate
          allocSize = (allocSize + largePageSize - 1) & ~usize(largePageSize - 1);
          return VirtualAlloc(nullptr, allocSize, MEM_RESERVE | MEM_COMMIT | MEM_LARGE_PAGES,
                              PAGE_READWRITE);
      },
      []() { return (void*) nullptr; });
}

void* aligned_large_pages_alloc_with_hint(usize allocSize, bool) {

    // Try to allocate large pages
    void* mem = aligned_large_pages_alloc_windows(allocSize);

    // Fall back to regular, page-aligned, allocation if necessary
    if (!mem)
        mem = VirtualAlloc(nullptr, allocSize, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);

    return mem;
}

#else

    #if defined(__linux__) && defined(MAP_HUGE_SHIFT) && defined(__x86_64__)
        #define HAS_HUGE_PAGES

static std::map<void*, usize> huge_pages;
static std::mutex             huge_pages_mtx;

static void* try_huge_pages_alloc(usize allocSize) {
    usize size = ((allocSize + HugePageSize - 1) / HugePageSize) * HugePageSize;
    void* mem  = mmap(NULL, size, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB | (30 << MAP_HUGE_SHIFT), -1, 0);

    if (mem == MAP_FAILED)
        return nullptr;

    std::lock_guard lg(huge_pages_mtx);
    huge_pages[mem] = size;
    return mem;
}
    #endif  // defined(__linux__) && defined(MAP_HUGE_SHIFT) && defined(__x86_64__)

extern "C" void* _sbrk(intptr_t);
extern "C" char __heap_end;

void* aligned_large_pages_alloc_with_hint(usize allocSize, [[maybe_unused]] bool hugePageHint) {
    volatile uint32_t* mb = (volatile uint32_t*)MAILBOX_ADDR;
    mb[2] = allocSize;
    mb[4] = (uint32_t)_sbrk(0);
    mb[5] = (uint32_t)&__heap_end;

    constexpr usize alignment = 4096;
    usize size = ((allocSize + alignment - 1) / alignment) * alignment;
    void* mem  = std_aligned_alloc(alignment, size);
    if (!mem) {
        mb[3] = 0xDEAD0001; // allocation failed!
    } else {
        mb[3] = (uint32_t)mem; // success pointer
    }
    return mem;
}


#endif

void* aligned_large_pages_alloc(usize size) {
    return aligned_large_pages_alloc_with_hint(size, false);
}

bool has_large_pages() {

#if defined(_WIN32)

    constexpr usize page_size = 2 * 1024 * 1024;  // 2MB page size assumed
    void*           mem       = aligned_large_pages_alloc_windows(page_size);
    if (mem == nullptr)
    {
        return false;
    }
    else
    {
        aligned_large_pages_free(mem);
        return true;
    }

#elif defined(__linux__)

    #if defined(MADV_HUGEPAGE)
    return true;
    #else
    return false;
    #endif

#else

    return false;

#endif
}


// aligned_large_pages_free() will free the previously memory allocated
// by aligned_large_pages_alloc(). The effect is a nop if mem == nullptr.

#if defined(_WIN32)

void aligned_large_pages_free(void* mem) {

    if (mem && !VirtualFree(mem, 0, MEM_RELEASE))
    {
        DWORD err = GetLastError();
        std::cerr << "Failed to free large page memory. Error code: 0x" << std::hex << err
                  << std::dec << std::endl;
        exit(EXIT_FAILURE);
    }
}

#else

void aligned_large_pages_free(void* mem) {
    if (!mem)
        return;

    #ifdef HAS_HUGE_PAGES
    std::lock_guard lg(huge_pages_mtx);
    if (auto it = huge_pages.find(mem); it != huge_pages.end())
    {
        if (munmap(mem, it->second) != 0)
        {
            std::cerr << "munmap failed: " << strerror(errno) << std::endl;
            exit(EXIT_FAILURE);
        }
        huge_pages.erase(it);
        return;
    #endif
#if defined(BAREMETAL_RISCV)
    if (reinterpret_cast<uintptr_t>(mem) == 0x1FF10000u) {
        return;
    }
#endif

    std_aligned_free(mem);
}

#endif
}  // namespace Stockfish
