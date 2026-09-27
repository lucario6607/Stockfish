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

#include <iostream>
#include <memory>
#include <sstream>
#include <utility>

#include "attacks.h"
#include "misc.h"
#include "position.h"
#include "tune.h"
#include "uci.h"

using namespace Stockfish;

#if defined(BAREMETAL_RISCV)
#define MAILBOX_ADDR 0x1FF00000u
#else
#define MAILBOX_ADDR 0x4FF00000u
#endif

int main(int argc, char* argv[]) {
    volatile unsigned int* mb = (volatile unsigned int*)MAILBOX_ADDR;
    mb[0] = 0x494E4954; // 'INIT'
    mb[1] = 1;
#if defined(BAREMETAL_RISCV)
    volatile uint32_t* accel = (volatile uint32_t*)0x40000000;
    mb[2] = accel[0]; // Probed HW accelerator ID (0x53460000)
#else
    mb[2] = 0;
#endif
    mb[3] = 0;
    mb[4] = 0;
    mb[5] = 0;
    mb[6] = 0;
    mb[7] = 0;

#if defined(BAREMETAL_SPARC)
    // Initialize GRLIB GPTIMER 0 (82.359 MHz / 82 = ~1 MHz, 1 tick = 1 us)
    volatile unsigned int* gpt = (volatile unsigned int*)0x80000300;
    gpt[1] = 82;         // scaler reload
    gpt[0] = 82;         // scaler value
    gpt[5] = 0xFFFFFFFF; // timer 0 reload value
    gpt[6] = 7;          // EN (1) | RS (2) | LD (4)
#elif defined(BAREMETAL_RISCV)
    // Hardware mcycle CSR is always active and enabled automatically
#endif

    Attacks::init();
    mb[1] = 2;

    Position::init();
    mb[1] = 3;

    static char app_name[] = "stockfish";
    static char* dummy_argv[] = {app_name, nullptr};
    auto cli = CommandLine(1, dummy_argv);
    auto uci = std::make_unique<UCIEngine>(std::move(cli));
    mb[1] = 4;

    Tune::init(uci->engine_options());
    mb[1] = 5;

    // Launch speedtest: 1 thread, 1 MB Hash, 150 seconds
    std::istringstream args("1 1 150");
    uci->benchmark(args);

    volatile unsigned int heartbeat = 0;
    while (1) {
        heartbeat++;
        mb[7] = heartbeat;
        for (volatile int d = 0; d < 100000; d++) {}
    }

    return 0;
}

#ifdef UNIVERSAL_BINARY
}  // namespace Stockfish

    #ifdef UNIVERSAL_NEEDS_MAIN_SHIM
int main(int argc, char* argv[]) { return Stockfish::main(argc, argv); }
    #endif
#endif
