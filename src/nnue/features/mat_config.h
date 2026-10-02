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

#ifndef NNUE_FEATURES_MAT_CONFIG_INCLUDED
#define NNUE_FEATURES_MAT_CONFIG_INCLUDED

#include "../../misc.h"
#include "../../types.h"
#include "../nnue_common.h"

namespace Stockfish {
class Position;
}

namespace Stockfish::Eval::NNUE::Features {

class MatConfig {
   public:
    static constexpr u32 HashValue = 0x3a5c91e7u;

    static constexpr IndexType Configurations  = 3 * 3 * 3 * 3 * 5 * 5;
    static constexpr IndexType OwnBishopPair   = Configurations;
    static constexpr IndexType TheirBishopPair = Configurations + 1;
    static constexpr IndexType OppositeBishops = Configurations + 2;
    static constexpr IndexType Dimensions      = Configurations + 3;

    static constexpr IndexType MaxActiveDimensions = 4;
    using IndexList                                = ValueList<IndexType, MaxActiveDimensions>;

    using Signature = u64;

    static Signature signature(const Position& pos);
    static Signature update(Signature signature, const DirtyPiece& diff, bool forward);

    static void append_active_indices(Color perspective, Signature signature, IndexList& active);
    static void append_changed_indices(
      Color perspective, Signature from, Signature to, IndexList& removed, IndexList& added);
};

}  // namespace Stockfish::Eval::NNUE::Features

#endif  // #ifndef NNUE_FEATURES_MAT_CONFIG_INCLUDED
