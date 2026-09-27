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

#include "network.h"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <optional>
#include <type_traits>
#include <vector>
#include <filesystem>

#define INCBIN_SILENCE_BITCODE_WARNING
#include "../incbin/incbin.h"

#include "../evaluate.h"
#include "../misc.h"
#include "../position.h"
#include "../types.h"
#include "nnue_architecture.h"
#include "nnue_common.h"
#include "nnue_misc.h"
#include "nnz_helper.h"

// Macro to embed the default efficiently updatable neural network (NNUE) file
// data in the engine binary (using incbin.h, by Dale Weiler).
// This macro invocation will declare the following three variables
//     const unsigned char        gEmbeddedNNUEData[];  // a pointer to the embedded data
//     const unsigned char *const gEmbeddedNNUEEnd;     // a marker to the end
//     const unsigned int         gEmbeddedNNUESize;    // the size of the embedded file
// Note that this does not work in Microsoft Visual Studio.
#if !defined(UNIVERSAL_BINARY) && !defined(_MSC_VER) && !defined(NNUE_EMBEDDING_OFF)
INCBIN(EmbeddedNNUE, EvalFileDefaultName);
#elif defined(UNIVERSAL_BINARY_MACOS_X86_SLICE)
// Determined at runtime, see universal/nnue_embed.cpp
extern const unsigned char* const gEmbeddedNNUEData;
extern const unsigned int         gEmbeddedNNUESize;
#elif defined(UNIVERSAL_BINARY)
extern const unsigned char gEmbeddedNNUEData[];
extern const unsigned int  gEmbeddedNNUESize;
#else
const unsigned char gEmbeddedNNUEData[1] = {0x0};
const unsigned int  gEmbeddedNNUESize    = 1;
#endif


namespace Stockfish::Eval::NNUE {

namespace fs = std::filesystem;

namespace Detail {

// Read evaluation function parameters
template<typename T>
bool read_parameters(std::istream& stream, T& reference) {

    u32 header;
    header = read_little_endian<u32>(stream);
    if (!stream || header != T::get_hash_value())
        return false;
    return reference.read_parameters(stream);
}

// Write evaluation function parameters
template<typename T>
bool write_parameters(std::ostream& stream, const T& reference) {

    write_little_endian<u32>(stream, T::get_hash_value());
    return reference.write_parameters(stream);
}

}  // namespace Detail

void Network::load(const fs::path& rootDirectory, fs::path evalfilePath, EvalFile& evalFile) {
#if defined(DEFAULT_NNUE_DIRECTORY)
    std::vector<fs::path> dirs = {fs::path{}, rootDirectory,
                                  fs::path(stringify(DEFAULT_NNUE_DIRECTORY))};
#else
    std::vector<fs::path> dirs = {fs::path{}, rootDirectory};
#endif

    if (evalfilePath.empty())
        evalfilePath = evalFile.defaultName;

    if (evalFile.current != evalfilePath && evalfilePath == evalFile.defaultName)
        load_internal(evalFile);

    for (const auto& directory : dirs)
    {
        if (evalFile.current != evalfilePath)
            load_external(directory, evalfilePath, evalFile);
    }
}

bool Network::save(const EvalFile& evalFile, const std::optional<fs::path>& filename) const {
    if (!evalFile.current.has_value())
    {
        sync_cout << "Failed to export a net. No network file is currently loaded. "
                     "Please load a network file first."
                  << sync_endl;
        return false;
    }

    if (!filename.has_value() && evalFile.current != evalFile.defaultName)
    {
        sync_cout << "Failed to export a net. A non-embedded net can only be "
                     "saved if the filename is specified"
                  << sync_endl;
        return false;
    }

    fs::path      actualFilename = filename.value_or(evalFile.defaultName);
    std::ofstream stream(actualFilename, std::ios_base::binary);

    bool saved = save(stream, evalFile.netDescription);

    sync_cout << (saved ? "Network saved successfully to " + actualFilename.string()
                        : "Failed to export a net")
              << sync_endl;

    return saved;
}

#if defined(BAREMETAL_RISCV)
#define NNUE_ACCEL_BASE        0x40000000u
#else
#define NNUE_ACCEL_BASE        0x80010000u
#endif
#define NNUE_ACCEL_REG_CTRL    ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x0000u))
#define NNUE_ACCEL_REG_EVAL    ((volatile int32_t* )(NNUE_ACCEL_BASE + 0x0004u))
#define NNUE_ACCEL_REG_CYCLES  ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x0008u))
#define NNUE_ACCEL_REG_BUCKET  ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x000Cu))
#define NNUE_ACCEL_REG_LOCK    ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x0010u))
#define NNUE_ACCEL_INBUF       ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x0400u))
#define NNUE_ACCEL_BIAS_FC0    ((volatile int32_t* )(NNUE_ACCEL_BASE + 0x1000u))
#define NNUE_ACCEL_BIAS_FC1    ((volatile int32_t* )(NNUE_ACCEL_BASE + 0x1080u))
#define NNUE_ACCEL_BIAS_FC2    ((volatile int32_t* )(NNUE_ACCEL_BASE + 0x1100u))
#define NNUE_ACCEL_WEIGHT_FC2  ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x1200u))
#define NNUE_ACCEL_WEIGHT_FC1  ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x1400u))
#define NNUE_ACCEL_WEIGHT_FC0  ((volatile uint32_t*)(NNUE_ACCEL_BASE + 0x8000u))

static int g_accel_present = -1;
static volatile int g_accel_active_bucket = -1;

static inline void hw_accel_lock() {
    // Hardware atomic test-and-set at 0x0010: read returns 1 if acquired, 0 if busy
    while (*NNUE_ACCEL_REG_LOCK == 0) {
        for (volatile int d = 0; d < 8; ++d) {}
    }
}

static inline void hw_accel_unlock() {
    *NNUE_ACCEL_REG_LOCK = 0;
}

static inline bool hw_accel_is_present() {
    if (g_accel_present < 0) {
        uint32_t ctrl = *NNUE_ACCEL_REG_CTRL;
        if ((ctrl >> 16) == 0x5346u) {
            g_accel_present = 1;
        } else {
            g_accel_present = 0;
        }
    }
    return g_accel_present == 1;
}

uint32_t get_accel_status() {
    hw_accel_is_present();
    uint32_t magic = (g_accel_present == 1) ? 0xACC10000u : 0x50F70000u;
    return magic | (uint32_t)(g_accel_active_bucket & 0xFF);
}

static void hw_accel_load_bucket(const NetworkArchitecture& arch, int bucket) {
    const int32_t* fc0_b = arch.fc_0.get_biases();
    for (int i = 0; i < 32; ++i) {
        NNUE_ACCEL_BIAS_FC0[i] = fc0_b[i];
    }

    const int32_t* fc1_b = arch.fc_1.get_biases();
    for (int i = 0; i < 32; ++i) {
        NNUE_ACCEL_BIAS_FC1[i] = fc1_b[i];
    }

    const int32_t* fc2_b = arch.fc_2.get_biases();
    *NNUE_ACCEL_BIAS_FC2 = fc2_b[0];

    const uint32_t* fc2_w = (const uint32_t*)arch.fc_2.get_weights();
    for (int i = 0; i < 32; ++i) {
        NNUE_ACCEL_WEIGHT_FC2[i] = fc2_w[i];
    }

    const int8_t* fc1_w = arch.fc_1.get_weights();
    for (int m = 0; m < 64; ++m) {
        for (int g = 0; g < 8; ++g) {
            uint8_t b0 = (uint8_t)fc1_w[(g * 4 + 0) * 64 + m];
            uint8_t b1 = (uint8_t)fc1_w[(g * 4 + 1) * 64 + m];
            uint8_t b2 = (uint8_t)fc1_w[(g * 4 + 2) * 64 + m];
            uint8_t b3 = (uint8_t)fc1_w[(g * 4 + 3) * 64 + m];
            uint32_t w_word = (uint32_t)b0 | ((uint32_t)b1 << 8) | ((uint32_t)b2 << 16) | ((uint32_t)b3 << 24);
            NNUE_ACCEL_WEIGHT_FC1[m * 8 + g] = w_word;
        }
    }

    const int8_t* fc0_w = arch.fc_0.get_weights();
    for (int b = 0; b < 8; ++b) {
        volatile uint32_t* bank_ptr = NNUE_ACCEL_WEIGHT_FC0 + (b * 1024);
        for (int k = 0; k < 1024; ++k) {
            uint8_t b0 = (uint8_t)fc0_w[(b * 4 + 0) * 1024 + k];
            uint8_t b1 = (uint8_t)fc0_w[(b * 4 + 1) * 1024 + k];
            uint8_t b2 = (uint8_t)fc0_w[(b * 4 + 2) * 1024 + k];
            uint8_t b3 = (uint8_t)fc0_w[(b * 4 + 3) * 1024 + k];
            uint32_t w_word = (uint32_t)b0 | ((uint32_t)b1 << 8) | ((uint32_t)b2 << 16) | ((uint32_t)b3 << 24);
            bank_ptr[k] = w_word;
        }
    }

    *NNUE_ACCEL_REG_BUCKET = bucket;
    g_accel_active_bucket = bucket;
}

static inline i32 hw_accel_propagate(const NetworkArchitecture& arch, int bucket, const TransformedFeatureType* transformedFeatures) {
    if (g_accel_active_bucket != bucket) {
        hw_accel_load_bucket(arch, bucket);
    }

    const uint32_t* src = (const uint32_t*)transformedFeatures;
    for (int i = 0; i < 256; ++i) {
        NNUE_ACCEL_INBUF[i] = src[i];
    }

    *NNUE_ACCEL_REG_CTRL = 1;

    while (!(*NNUE_ACCEL_REG_CTRL & 4)) {
    }

    return *NNUE_ACCEL_REG_EVAL;
}

static inline bool is_hart0() {
#if defined(BAREMETAL_RISCV)
    uint32_t hid;
    asm volatile("csrr %0, mhartid" : "=r"(hid));
    return hid == 0;
#else
    return true;
#endif
}

std::pair<Value, bool> Network::evaluate_start(const Position&    pos,
                                              AccumulatorStack&  accumulatorStack,
                                              AccumulatorCaches& cache) const {
    const int bucket = (pos.count<ALL_PIECES>() - 1) / 4;

    if (hw_accel_is_present() && is_hart0()) {
        if (*NNUE_ACCEL_REG_BUCKET != (uint32_t)bucket) {
            hw_accel_load_bucket(network[bucket], bucket);
        }

        NNZInfo<L1> nnzInfo;
        constexpr u64 alignment = CacheLineSize;
        alignas(alignment) TransformedFeatureType transformedFeatures[FeatureTransformer::BufferSize];
        ASSERT_ALIGNED(transformedFeatures, alignment);

        const auto psqt = featureTransformer.transform(
            pos, accumulatorStack, cache,
            transformedFeatures,
            bucket, nnzInfo);

        const uint32_t* __restrict__ src = reinterpret_cast<const uint32_t*>(transformedFeatures);
        volatile uint32_t* __restrict__ dst = NNUE_ACCEL_INBUF;
        for (int i = 0; i < 256; i += 16) {
            dst[i +  0] = src[i +  0];
            dst[i +  1] = src[i +  1];
            dst[i +  2] = src[i +  2];
            dst[i +  3] = src[i +  3];
            dst[i +  4] = src[i +  4];
            dst[i +  5] = src[i +  5];
            dst[i +  6] = src[i +  6];
            dst[i +  7] = src[i +  7];
            dst[i +  8] = src[i +  8];
            dst[i +  9] = src[i +  9];
            dst[i + 10] = src[i + 10];
            dst[i + 11] = src[i + 11];
            dst[i + 12] = src[i + 12];
            dst[i + 13] = src[i + 13];
            dst[i + 14] = src[i + 14];
            dst[i + 15] = src[i + 15];
        }

        *NNUE_ACCEL_REG_CTRL = 5;
        return {static_cast<Value>(psqt / OutputScale), true};
    }
    return {VALUE_ZERO, false};
}

Value Network::evaluate_finish() const {
    while (!(*NNUE_ACCEL_REG_CTRL & 4)) {
    }
    i32 positional = *NNUE_ACCEL_REG_EVAL;
    return static_cast<Value>(positional / OutputScale);
}

NetworkOutput Network::evaluate(const Position&    pos,
                                AccumulatorStack&  accumulatorStack,
                                AccumulatorCaches& cache) const {

    auto [psqt, hw] = evaluate_start(pos, accumulatorStack, cache);

    if (hw) {
        Value positional = evaluate_finish();
        return {psqt, positional};
    } else {
        const int bucket = (pos.count<ALL_PIECES>() - 1) / 4;
        NNZInfo<L1> nnzInfo;
        constexpr u64 alignment = CacheLineSize;
        alignas(alignment) TransformedFeatureType transformedFeatures[FeatureTransformer::BufferSize];
        ASSERT_ALIGNED(transformedFeatures, alignment);

        const auto psqt_raw = featureTransformer.transform(pos, accumulatorStack, cache,
                                                           transformedFeatures, bucket, nnzInfo);
        i32 positional = network[bucket].propagate(transformedFeatures, nnzInfo);
        return {static_cast<Value>(psqt_raw / OutputScale), static_cast<Value>(positional / OutputScale)};
    }
}


void Network::verify(const std::function<void(std::string_view)>& f,
                     const EvalFile&                              evalFile,
                     fs::path                                     evalfilePath) const {
    if (evalfilePath.empty())
        evalfilePath = evalFile.defaultName;

    if (evalFile.current != evalfilePath)
    {
        if (f)
        {
            std::string msg1 =
              "Network evaluation parameters compatible with the engine must be available.";
            std::string msg2 =
              "The network file " + evalfilePath.string() + " was not loaded successfully.";
            std::string msg3 = "The UCI option EvalFile might need to specify the full path, "
                               "including the directory name, to the network file.";
            std::string msg4 = "The default net can be downloaded from: "
                               "https://tests.stockfishchess.org/api/nn/"
                             + std::string(evalFile.defaultName);
            std::string msg5 = "The engine will be terminated now.";

            std::string msg = "ERROR: " + msg1 + '\n' + "ERROR: " + msg2 + '\n' + "ERROR: " + msg3
                            + '\n' + "ERROR: " + msg4 + '\n' + "ERROR: " + msg5 + '\n';

            f(msg);
        }

        exit(EXIT_FAILURE);
    }

    if (f)
    {
        usize size = sizeof(featureTransformer) + sizeof(NetworkArchitecture) * LayerStacks;
        f("NNUE evaluation using " + evalfilePath.string() + " ("
          + std::to_string(size / (1024 * 1024)) + "MiB, ("
          + std::to_string(featureTransformer.InputDimensions) + ", "
          + std::to_string(network[0].TransformedFeatureDimensions) + ", "
          + std::to_string(network[0].FC_0_OUTPUTS) + ", " + std::to_string(network[0].FC_1_OUTPUTS)
          + ", 1))");
    }
}


NnueEvalTrace Network::trace_evaluate(const Position&    pos,
                                      AccumulatorStack&  accumulatorStack,
                                      AccumulatorCaches& cache) const {

    constexpr u64 alignment = CacheLineSize;

    alignas(alignment) TransformedFeatureType transformedFeatures[FeatureTransformer::BufferSize];

    ASSERT_ALIGNED(transformedFeatures, alignment);

    NnueEvalTrace t{};
    t.correctBucket = (pos.count<ALL_PIECES>() - 1) / 4;
    for (IndexType bucket = 0; bucket < LayerStacks; ++bucket)
    {
        NNZInfo<L1> nnzInfo;
        const auto  materialist = featureTransformer.transform(pos, accumulatorStack, cache,
                                                               transformedFeatures, bucket, nnzInfo);
        const auto  positional  = network[bucket].propagate(transformedFeatures, nnzInfo);

        t.psqt[bucket]       = static_cast<Value>(materialist / OutputScale);
        t.positional[bucket] = static_cast<Value>(positional / OutputScale);
    }

    return t;
}


void Network::load_external(const fs::path& dir, const fs::path& evalfilePath, EvalFile& evalFile) {
    std::ifstream stream(dir / evalfilePath, std::ios::binary);
    auto          description = load(stream);

    if (description.has_value())
    {
        evalFile.current        = evalfilePath;
        evalFile.netDescription = description.value();
    }
}


void Network::load_internal(EvalFile& evalFile) {
    // C++ way to prepare a buffer for a memory stream
    class MemoryBuffer: public std::basic_streambuf<char> {
       public:
        MemoryBuffer(char* p, usize n) {
            setg(p, p, p + n);
            setp(p, p + n);
        }
    };

#ifdef UNIVERSAL_BINARY_MACOS_X86_SLICE
    if (gEmbeddedNNUEData == nullptr)  // failed embedded load
        return;
#endif

    MemoryBuffer buffer(const_cast<char*>(reinterpret_cast<const char*>(gEmbeddedNNUEData)),
                        usize(gEmbeddedNNUESize));

    std::istream stream(&buffer);
    auto         description = load(stream);

    if (description.has_value())
    {
        evalFile.current        = evalFile.defaultName;
        evalFile.netDescription = description.value();
    }
}


void Network::initialize() { initialized = true; }


bool Network::save(std::ostream& stream, const std::string& netDescription) const {
    return write_parameters(stream, netDescription);
}


std::optional<std::string> Network::load(std::istream& stream) {
    initialize();
    std::string description;

    return read_parameters(stream, description) ? std::make_optional(description) : std::nullopt;
}


usize Network::get_content_hash() const {
    if (!initialized)
        return 0;

    usize h = 0;
    hash_combine(h, featureTransformer);
    for (auto&& layerstack : network)
        hash_combine(h, layerstack);
    return h;
}

// Read network header
bool Network::read_header(std::istream& stream, u32* hashValue, std::string* desc) const {
    u32 version, size;

    version    = read_little_endian<u32>(stream);
    *hashValue = read_little_endian<u32>(stream);
    size       = read_little_endian<u32>(stream);
    if (!stream || version != Version)
        return false;
    desc->resize(size);
    stream.read(&(*desc)[0], size);
    return !stream.fail();
}


// Write network header
bool Network::write_header(std::ostream& stream, u32 hashValue, const std::string& desc) const {
    write_little_endian<u32>(stream, Version);
    write_little_endian<u32>(stream, hashValue);
    write_little_endian<u32>(stream, u32(desc.size()));
    stream.write(&desc[0], desc.size());
    return !stream.fail();
}


bool Network::read_parameters(std::istream& stream, std::string& netDescription) {
    u32 hashValue;
    if (!read_header(stream, &hashValue, &netDescription))
        return false;
    if (hashValue != Network::hash)
        return false;
    if (!Detail::read_parameters(stream, featureTransformer))
        return false;
    for (usize i = 0; i < LayerStacks; ++i)
    {
        if (!Detail::read_parameters(stream, network[i]))
            return false;
    }
    return stream && stream.peek() == std::ios::traits_type::eof();
}


bool Network::write_parameters(std::ostream& stream, const std::string& netDescription) const {
    if (!write_header(stream, Network::hash, netDescription))
        return false;
    if (!Detail::write_parameters(stream, featureTransformer))
        return false;
    for (usize i = 0; i < LayerStacks; ++i)
    {
        if (!Detail::write_parameters(stream, network[i]))
            return false;
    }
    return bool(stream);
}

}  // namespace Stockfish::Eval::NNUE
