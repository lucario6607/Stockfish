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

#include "mat_config.h"

#include <algorithm>

#include "../../bitboard.h"
#include "../../position.h"
#include "../../types.h"
#include "../nnue_common.h"

namespace Stockfish::Eval::NNUE::Features {

namespace {

constexpr Bitboard DarkSquares = 0xAA55AA55AA55AA55ULL;

enum Slot {
    QueenSlot,
    RookSlot,
    KnightSlot,
    LightBishopSlot,
    DarkBishopSlot,
    SlotNb
};

constexpr int shift(Color c, int slot) { return (int(c) * SlotNb + slot) * 4; }

constexpr int count(MatConfig::Signature signature, Color c, int slot) {
    return int(signature >> shift(c, slot)) & 0xF;
}

MatConfig::Signature unit(Piece pc, Square sq) {
    const Color c = color_of(pc);

    switch (type_of(pc))
    {
    case QUEEN :
        return MatConfig::Signature(1) << shift(c, QueenSlot);
    case ROOK :
        return MatConfig::Signature(1) << shift(c, RookSlot);
    case KNIGHT :
        return MatConfig::Signature(1) << shift(c, KnightSlot);
    case BISHOP :
        return MatConfig::Signature(1)
            << shift(c, (DarkSquares & square_bb(sq)) ? DarkBishopSlot : LightBishopSlot);
    default :
        return 0;
    }
}

}

MatConfig::Signature MatConfig::signature(const Position& pos) {
    Signature signature = 0;

    for (Color c : {WHITE, BLACK})
    {
        const int darkBishops = popcount(pos.pieces(c, BISHOP) & DarkSquares);

        signature |= Signature(pos.count<QUEEN>(c)) << shift(c, QueenSlot);
        signature |= Signature(pos.count<ROOK>(c)) << shift(c, RookSlot);
        signature |= Signature(pos.count<KNIGHT>(c)) << shift(c, KnightSlot);
        signature |= Signature(pos.count<BISHOP>(c) - darkBishops) << shift(c, LightBishopSlot);
        signature |= Signature(darkBishops) << shift(c, DarkBishopSlot);
    }

    return signature;
}

MatConfig::Signature MatConfig::update(Signature signature, const DirtyPiece& diff, bool forward) {
    const Signature removed = diff.remove_sq != SQ_NONE ? unit(diff.remove_pc, diff.remove_sq) : 0;
    const Signature added   = diff.add_sq != SQ_NONE ? unit(diff.add_pc, diff.add_sq) : 0;

    return forward ? signature - removed + added : signature + removed - added;
}

void MatConfig::append_active_indices(Color perspective, Signature signature, IndexList& active) {
    const Color us   = perspective;
    const Color them = ~perspective;

    auto bishops = [&](Color c) {
        return count(signature, c, LightBishopSlot) + count(signature, c, DarkBishopSlot);
    };
    auto queens = [&](Color c) { return IndexType(std::min(count(signature, c, QueenSlot), 2)); };
    auto rooks  = [&](Color c) { return IndexType(std::min(count(signature, c, RookSlot), 2)); };
    auto minors = [&](Color c) {
        return IndexType(std::min(count(signature, c, KnightSlot) + bishops(c), 4));
    };

    active.push_back(
      ((((queens(us) * 3 + queens(them)) * 3 + rooks(us)) * 3 + rooks(them)) * 5 + minors(us)) * 5
      + minors(them));

    if (bishops(us) >= 2)
        active.push_back(OwnBishopPair);
    if (bishops(them) >= 2)
        active.push_back(TheirBishopPair);
    if (bishops(us) == 1 && bishops(them) == 1
        && count(signature, us, LightBishopSlot) != count(signature, them, LightBishopSlot))
        active.push_back(OppositeBishops);
}

void MatConfig::append_changed_indices(
  Color perspective, Signature from, Signature to, IndexList& removed, IndexList& added) {
    if (from == to)
        return;

    IndexList before, after;
    append_active_indices(perspective, from, before);
    append_active_indices(perspective, to, after);

    for (IndexType index : before)
        if (std::find(after.begin(), after.end(), index) == after.end())
            removed.push_back(index);

    for (IndexType index : after)
        if (std::find(before.begin(), before.end(), index) == before.end())
            added.push_back(index);
}

}  // namespace Stockfish::Eval::NNUE::Features
