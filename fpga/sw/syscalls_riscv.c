#include <sys/types.h>
#include <sys/stat.h>
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

void* __dso_handle = 0;

static char* __empty_environ[1] = { 0 };
char** environ = __empty_environ;

char* getenv(const char* name) {
    return NULL;
}

extern char __heap_start;
extern char __heap_end;

static char* heap_ptr = 0;

void* _sbrk(ptrdiff_t incr) {
    if (heap_ptr == 0) {
        heap_ptr = &__heap_start;
    }
    char* prev = heap_ptr;
    if (heap_ptr + incr > &__heap_end) {
        return (void*)-1;
    }
    heap_ptr += incr;
    return (void*)prev;
}

int _write(int fd, const void* buf, size_t count) {
    return (int)count;
}

int _read(int fd, void* buf, size_t count) {
    return 0;
}

int _close(int fd) {
    return -1;
}

int _fstat(int fd, struct stat* st) {
    st->st_mode = S_IFCHR;
    return 0;
}

int _isatty(int fd) {
    return 1;
}

off_t _lseek(int fd, off_t offset, int whence) {
    return 0;
}

int _getentropy(void* buf, size_t buflen) {
    uint8_t* p = (uint8_t*)buf;
    for (size_t i = 0; i < buflen; ++i) {
        p[i] = (uint8_t)(i ^ 0x5A);
    }
    return 0;
}

void _exit(int status) {
    volatile uint32_t* mb = (volatile uint32_t*)0x1FF00000;
    mb[0] = 0xDEADBEEF;
    while (1) {
    }
}

// 64-bit atomic helpers for 32-bit RISC-V baremetal single core
uint64_t __atomic_load_8(const volatile void* ptr, int memorder) {
    return *(const volatile uint64_t*)ptr;
}

void __atomic_store_8(volatile void* ptr, uint64_t val, int memorder) {
    *(volatile uint64_t*)ptr = val;
}

uint64_t __atomic_exchange_8(volatile void* ptr, uint64_t val, int memorder) {
    uint64_t old = *(volatile uint64_t*)ptr;
    *(volatile uint64_t*)ptr = val;
    return old;
}

bool __atomic_compare_exchange_8(volatile void* ptr, void* expected, uint64_t desired, bool weak, int success_order, int failure_order) {
    uint64_t cur = *(volatile uint64_t*)ptr;
    uint64_t exp = *(uint64_t*)expected;
    if (cur == exp) {
        *(volatile uint64_t*)ptr = desired;
        return true;
    } else {
        *(uint64_t*)expected = cur;
        return false;
    }
}

uint64_t __atomic_fetch_add_8(volatile void* ptr, uint64_t val, int memorder) {
    uint64_t old = *(volatile uint64_t*)ptr;
    *(volatile uint64_t*)ptr = old + val;
    return old;
}

uint64_t __atomic_fetch_sub_8(volatile void* ptr, uint64_t val, int memorder) {
    uint64_t old = *(volatile uint64_t*)ptr;
    *(volatile uint64_t*)ptr = old - val;
    return old;
}
