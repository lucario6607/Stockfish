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

#include "thread.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "bitboard.h"
#include "history.h"
#include "memory.h"
#include "movegen.h"
#include "search.h"
#include "syzygy/tbprobe.h"
#include "timeman.h"
#include "types.h"
#include "uci.h"
#include "ucioption.h"

namespace Stockfish {

// Synchronous single-threaded implementation for bare-metal SPARC
Thread::Thread(Search::SharedState&                    sharedState,
               std::unique_ptr<Search::ISearchManager> sm,
               usize                                   n,
               usize                                   numaN,
               usize                                   totalNumaCount,
               OptionalThreadToNumaNodeBinder          binder) :
    idx(n),
    idxInNuma(numaN),
    totalNuma(totalNumaCount),
    nthreads(sharedState.options["Threads"]),
    exit(false),
    searching(false) {

    volatile uint32_t* mb = (volatile uint32_t*)MAILBOX_ADDR;
    mb[1] = 0x351;
    this->numaAccessToken = binder();
    mb[1] = 0x352;
    this->worker          = make_unique_large_page<Search::Worker>(
      sharedState, std::move(sm), n, idxInNuma, totalNuma, this->numaAccessToken);
    mb[1] = 0x353;
}

Thread::~Thread() {
    worker.reset();
}

extern "C" void hart1_search_trampoline(void* arg) {
    Search::Worker* w = (Search::Worker*)arg;
    if (w != nullptr) {
        w->start_searching();
    }
#if defined(BAREMETAL_RISCV)
    *HW_H1_DONE_REG = 1;
#endif
}

void Thread::start_searching() {
    if (worker == nullptr) return;

    if (idx == 0) {
        worker->start_searching();
    } else if (idx == 1) {
#if defined(BAREMETAL_RISCV)
        *HW_H1_STOP_REG = 0;
        *HW_H1_DONE_REG = 0;
#endif
        // Dispatch to Hart 1 via mailbox 0x1FF00020
        volatile uint32_t* h1_box = (volatile uint32_t*)0x1FF00020;
        h1_box[3] = 0; // Clear stop flag
        h1_box[2] = (uint32_t)(uintptr_t)worker.get(); // argument a0 = worker pointer
        h1_box[0] = (uint32_t)(uintptr_t)hart1_search_trampoline; // entry point triggers Hart 1
        asm volatile(
            "cbo.flush (%0)\n"
            "fence rw, rw\n"
            : : "r"(h1_box) : "memory"
        );
    }
}

void Thread::clear_worker() {
    if (worker != nullptr)
        worker->clear();
}

void Thread::wait_for_search_finished() {
    if (idx == 1) {
#if defined(BAREMETAL_RISCV)
        *HW_H1_STOP_REG = 1;
        // Wait until Hart 1 finishes
        while (*HW_H1_DONE_REG == 0) {
            for (volatile int d = 0; d < 100; ++d) {}
        }
#endif
    }
}

void Thread::run_custom_job(std::function<void()> f) {
    if (f)
        f();
}

void Thread::ensure_network_replicated() {
    if (worker != nullptr)
        worker->ensure_network_replicated();
}

void Thread::idle_loop() {
}

Search::SearchManager* ThreadPool::main_manager() { return main_thread()->worker->main_manager(); }

u64 ThreadPool::nodes_searched() const { return accumulate(&Search::Worker::nodes); }
u64 ThreadPool::tb_hits() const { return accumulate(&Search::Worker::tbHits); }

static usize next_power_of_two(u64 count) { return count > 1 ? (2ULL << msb(count - 1)) : 1; }

// Creates/destroys threads to match the requested number.
void ThreadPool::set(const NumaConfig&                           numaConfig,
                     Search::SharedState                         sharedState,
                     const Search::SearchManager::UpdateContext& updateContext) {

    volatile uint32_t* mb = (volatile uint32_t*)MAILBOX_ADDR;
    const usize requested = sharedState.options["Threads"];
    if (threads.size() == requested && requested > 0) {
        mb[1] = 0x3506;
        clear();
        return;
    }

    threads.clear();
    boundThreadToNumaNode.clear();

    if (requested > 0)
    {
        mb[1] = 0x3502;
        sharedState.sharedHistories.clear();
        sharedState.sharedHistories.try_emplace(0, next_power_of_two(requested));

        mb[1] = 0x3503;
        auto binder = OptionalThreadToNumaNodeBinder(0);

        for (usize i = 0; i < requested && i < 2; ++i) {
            auto manager = std::make_unique<Search::SearchManager>(updateContext);
            threads.emplace_back(std::make_unique<Thread>(
                sharedState, std::move(manager), i, i, requested, binder));
        }

        mb[1] = 0x3505;
        clear();
        mb[1] = 0x3506;
    }
}



// Sets threadPool data to initial values
void ThreadPool::clear() {
    if (threads.size() == 0)
        return;

    for (auto&& th : threads)
        th->clear_worker();

    for (auto&& th : threads)
        th->wait_for_search_finished();

    // These two affect the time taken on the first move of a game:
    main_manager()->bestPreviousAverageScore = VALUE_INFINITE;
    main_manager()->previousTimeReduction    = 0.85;

    main_manager()->callsCnt           = 0;
    main_manager()->bestPreviousScore  = VALUE_INFINITE;
    main_manager()->originalTimeAdjust = -1;
    main_manager()->tm.clear();
}

void ThreadPool::run_on_thread(usize threadId, std::function<void()> f) {
    assert(threads.size() > threadId);
    threads[threadId]->run_custom_job(std::move(f));
}

void ThreadPool::wait_on_thread(usize threadId) {
    assert(threads.size() > threadId);
    threads[threadId]->wait_for_search_finished();
}

usize ThreadPool::num_threads() const { return threads.size(); }


// Wakes up main thread waiting in idle_loop() and returns immediately.
// Main thread will wake up other threads and start the search.
void ThreadPool::start_thinking(const OptionsMap&  options,
                                Position&          pos,
                                StateListPtr&      states,
                                Search::LimitsType limits) {

    main_thread()->wait_for_search_finished();

    main_manager()->stopOnPonderhit = stop = false;
#if defined(BAREMETAL_RISCV)
    asm volatile("cbo.flush (%0)\nfence rw, rw" : : "r"(&stop) : "memory");
#endif
    main_manager()->ponder                 = limits.ponderMode;

    increaseDepth = true;

    Search::RootMoves rootMoves;

    for (const auto& uciMove : limits.searchmoves)
    {
        auto move = UCIEngine::to_move(pos, uciMove);

        if (move != Move::none())
            rootMoves.emplace_back(move);
    }

    if (rootMoves.empty())
        for (const auto& m : MoveList<LEGAL>(pos))
            rootMoves.emplace_back(m);

    Tablebases::Config tbConfig = Tablebases::rank_root_moves(options, pos, rootMoves);

    // After ownership transfer 'states' becomes empty, so if we stop the search
    // and call 'go' again without setting a new position states.get() == nullptr.
    assert(states.get() || setupStates.get());

    if (states.get())
        setupStates = std::move(states);  // Ownership transfer, states is now empty

    // We use Position::set() to set root position across threads. But there are
    // some StateInfo fields (previous, pliesFromNull, capturedPiece) that cannot
    // be deduced from a fen string, so set() clears them and they are set from
    // setupStates->back() later. The rootState is per thread, earlier states are
    // shared since they are read-only.
    for (auto&& th : threads)
    {
        th->run_custom_job([&]() {
            th->worker->limits = limits;
            th->worker->nodes = th->worker->tbHits = th->worker->bestMoveChanges = 0;
            th->worker->nmpMinPly                                                = 0;
            th->worker->rootDepth                                                = 0;
            th->worker->rootMoves                                                = rootMoves;
            th->worker->rootPos.set(pos.fen(), pos.is_chess960(), &th->worker->rootState);
            th->worker->rootState = setupStates->back();
            th->worker->tbConfig  = tbConfig;
        });
    }

    for (auto&& th : threads)
        th->wait_for_search_finished();

    main_thread()->start_searching();
}

Thread* ThreadPool::get_best_thread() const {

    Thread* bestThread = threads.front().get();
    Value   minScore   = VALUE_INFINITE;

    std::unordered_map<Move, i64, Move::MoveHash> votes(
      2 * std::min(size(), bestThread->worker->rootMoves.size()));

    for (auto&& th : threads)
        minScore = std::min(minScore, th->worker->rootMoves[0].score);

    // Vote according to score, and select the best thread
    for (auto&& th : threads)
        votes[th->worker->rootMoves[0].pv[0]] += th->worker->rootMoves[0].score - minScore + 14;

    for (auto&& th : threads)
    {
        const auto& bestThreadMove = bestThread->worker->rootMoves[0];
        const auto& newThreadMove  = th->worker->rootMoves[0];

        const auto bestThreadMoveVote = votes[bestThreadMove.pv[0]];
        const auto newThreadMoveVote  = votes[newThreadMove.pv[0]];

        // Aborted (d1) searches may lead to inexact win (or loss) scores.
        const bool bestThreadDecisive = bestThreadMove.score != -VALUE_INFINITE
                                     && is_decisive(bestThreadMove.score)
                                     && !bestThreadMove.score_is_bound();
        const bool newThreadDecisive = newThreadMove.score != -VALUE_INFINITE
                                    && is_decisive(newThreadMove.score)
                                    && !newThreadMove.score_is_bound();

        if (bestThreadDecisive)
        {
            // Make sure we pick the shortest mate / TB conversion.
            if (newThreadDecisive && std::abs(newThreadMove.score) > std::abs(bestThreadMove.score))
            {
                assert((is_win(bestThreadMove.score) && is_win(newThreadMove.score))
                       || (is_loss(bestThreadMove.score) && is_loss(newThreadMove.score)));

                bestThread = th.get();
            }
        }
        else if (newThreadDecisive
                 || (!is_loss(newThreadMove.score)
                     && (newThreadMoveVote > bestThreadMoveVote
                         || (newThreadMoveVote == bestThreadMoveVote
                             && newThreadMove.pv.size() > bestThreadMove.pv.size()))))
            bestThread = th.get();
    }

    return bestThread;
}


// Start non-main threads.
// Will be invoked by main thread after it has started searching.
void ThreadPool::start_searching() {

    for (auto&& th : threads)
        if (th != threads.front())
            th->start_searching();
}


// Wait for non-main threads
void ThreadPool::wait_for_search_finished() const {

    for (auto&& th : threads)
        if (th != threads.front())
            th->wait_for_search_finished();
}

std::vector<usize> ThreadPool::get_bound_thread_to_numa_node() const {
    return boundThreadToNumaNode;
}

std::vector<usize> ThreadPool::get_bound_thread_count_by_numa_node() const {
    std::vector<usize> counts;

    if (!boundThreadToNumaNode.empty())
    {
        NumaIndex highestNumaNode = 0;
        for (NumaIndex n : boundThreadToNumaNode)
            if (n > highestNumaNode)
                highestNumaNode = n;

        counts.resize(highestNumaNode + 1, 0);

        for (NumaIndex n : boundThreadToNumaNode)
            counts[n] += 1;
    }

    return counts;
}

usize ThreadPool::numa_nodes() const {
    std::unordered_set<usize> seen;
    for (NumaIndex n : boundThreadToNumaNode)
        seen.insert(n);
    return std::max(seen.size(), usize(1));
}

void ThreadPool::ensure_network_replicated() {
    for (auto&& th : threads)
        th->ensure_network_replicated();
}

}  // namespace Stockfish
