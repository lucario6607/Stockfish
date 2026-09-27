#include "tbprobe.h"

namespace Stockfish::Tablebases {

int MaxCardinality = 0;

void init(const std::string&) {}

WDLScore probe_wdl(Position&, ProbeState* result) {
    if (result) *result = FAIL;
    return WDLDraw;
}

int probe_dtz(Position&, ProbeState* result) {
    if (result) *result = FAIL;
    return 0;
}

bool root_probe(Position&,
                Search::RootMoves&,
                bool,
                bool,
                const std::function<bool()>&) {
    return false;
}

bool root_probe_wdl(Position&, Search::RootMoves&, bool) {
    return false;
}

Config rank_root_moves(
    const OptionsMap&,
    Position&,
    Search::RootMoves&,
    bool,
    const std::function<bool()>&) {
    return Config{};
}

} // namespace Stockfish::Tablebases
