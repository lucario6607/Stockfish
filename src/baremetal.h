#ifndef BAREMETAL_H_INCLUDED
#define BAREMETAL_H_INCLUDED

#include <mutex>
#include <condition_variable>
#include <cstdint>

#define HW_H1_STOP_REG ((volatile uint32_t*)0x41C00010)
#define HW_H1_DONE_REG ((volatile uint32_t*)0x41C00014)

namespace std {
    class mutex {
    public:
        void lock() {}
        void unlock() {}
        bool try_lock() { return true; }
    };

    class condition_variable {
    public:
        void notify_one() {}
        void notify_all() {}
        template<typename Lock, typename Pred>
        void wait(Lock&, Pred) {}
    };
}

#endif

