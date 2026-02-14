/******************************************************************************
 * Copyright 2014-2017 cisco Systems, Inc.                                    *
 *                                                                            *
 * Licensed under the Apache License, Version 2.0 (the "License");            *
 * you may not use this file except in compliance with the License.           *
 * You may obtain a copy of the License at                                    *
 *                                                                            *
 *     http://www.apache.org/licenses/LICENSE-2.0                             *
 *                                                                            *
 * Unless required by applicable law or agreed to in writing, software        *
 * distributed under the License is distributed on an "AS IS" BASIS,          *
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.   *
 * See the License for the specific language governing permissions and        *
 * limitations under the License.                                             *
 ******************************************************************************/

/**
 * @file
 * Syncodecs implementation file.
 *
 * @version 0.1.0
 * @author Sergio Mena
 * @author Stefano D'Aronco
 * @author Xiaoqing Zhu
 */

#include "syncodecs.h"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <sys/stat.h>
#include <thread>
#include "api/video/i420_buffer.h"

#define INITIAL_RATE 100. // Initial (very low) target rate set by default in codecs, in bps
#define EPSILON 1e-10 // Used to check floats/doubles for zero
#define SCALE_T .15 // Reference scaling for frame interval noise (zero-mean laplacian distribution)
#define SCALE_B .15 // Reference scaling for frame size (zero-mean laplacian distribution)

/**
 * Portable implementation of rand taken from the C standard, section 7.20.2
 * See [http://www.open-std.org/jtc1/sc22/wg14/www/docs/n1256.pdf]
 *
 * The reason for introducing is for #SimpleContentSharingCodec to produce the same "peaks"
 * independently of the platform/compiler used
 *
 */
#define P_RAND_MAX 32767
static unsigned long int next = 1; /* Seed */
static int PortableRand(void) {
    next = next * 1103515245 + 12345;
    return (unsigned int) (next / 65536) % 32768;
}

namespace syncodecs {

    Codec::Codec() : m_targetRate(INITIAL_RATE), m_currentPacketOrFrame(std::vector<uint8_t>(0, 0), 0.) {}

    Codec::~Codec() {}

    const Codec::value_type Codec::operator*() const {
        assert(isValid());
        return m_currentPacketOrFrame;
    }

    const Codec::value_type *Codec::operator->() const {
        assert(isValid());
        return &m_currentPacketOrFrame;
    }

    Codec &Codec::operator++() {
        assert(isValid());
        nextPacketOrFrame(); // Update current packet/frame
        return *this;
    }

    Codec::operator bool() const { return isValid(); }

    float Codec::getTargetRate() const { return m_targetRate; }

    float Codec::setTargetRate(float newRateBps) {
        if (newRateBps > EPSILON) {
            m_targetRate = newRateBps;
        }
        return m_targetRate;
    }

    bool Codec::isValid() const { return m_currentPacketOrFrame.first.size() > 0; }


    CodecWithFps::CodecWithFps(double fps, AddNoiseFunc addFrSizeNoise, AddNoiseFunc addFrInterNoise) :
        Codec(), m_fps(static_cast<float>(fps)), m_addFrSizeNoise(addFrSizeNoise), m_addFrInterNoise(addFrInterNoise) {
        assert(fps > 0);
    }

    CodecWithFps::~CodecWithFps() {}

    double CodecWithFps::addLaplaceNoise(double value, double mu, double b) {
        value += value * laplace(mu, b);
        return value;
    }

    double CodecWithFps::addLaplaceSize(double size) {
        return std::max(1., addLaplaceNoise(size, 0, SCALE_B)); // At least 1 byte to send
    }

    double CodecWithFps::addLaplaceInter(double seconds) {
        return std::max(0., addLaplaceNoise(seconds, 0, SCALE_T)); // Non-negative time
    }

    double CodecWithFps::uniform(double min, double max) {
        return double(PortableRand()) / double(P_RAND_MAX) * (max - min) + min;
    }

    double CodecWithFps::laplace(double mu, double b) {
        assert(b > 0.);
        const double u = uniform(-.5 + EPSILON, .5 - EPSILON);
        const int sign = int(0 < u) - int(u < 0);
        return mu - b * double(sign) * log(1 - 2 * fabs(u));
    }


    Packetizer::Packetizer(unsigned long payloadSize) : Codec(), m_payloadSize(payloadSize) { assert(payloadSize > 0); }

    Packetizer::~Packetizer() {}


    PerfectCodec::PerfectCodec(unsigned long payloadSize) : Packetizer(payloadSize) {
        nextPacketOrFrame(); // Read first frame
        assert(isValid());
    }

    PerfectCodec::~PerfectCodec() {}

    void PerfectCodec::nextPacketOrFrame() {
        const double secsToNextFrame = double(m_payloadSize) * 8. / m_targetRate;

        m_currentPacketOrFrame.first.resize(m_payloadSize, 0);
        m_currentPacketOrFrame.second = secsToNextFrame;
    }


    SimpleFpsBasedCodec::SimpleFpsBasedCodec(double fps, AddNoiseFunc addFrSizeNoise, AddNoiseFunc addFrInterNoise) :
        CodecWithFps(fps, addFrSizeNoise, addFrInterNoise) {
        nextPacketOrFrame(); // Read first frame
        assert(isValid());
    }

    SimpleFpsBasedCodec::~SimpleFpsBasedCodec() {}

    void SimpleFpsBasedCodec::nextPacketOrFrame() {
        double frameBytes = std::ceil(m_targetRate / (m_fps * 8.));
        // Apply the configured noise function to frame size
        if (m_addFrSizeNoise != NULL) {
            frameBytes = m_addFrSizeNoise(frameBytes);
        }
        assert(frameBytes > 0);

        double secsToNextFrame = 1. / m_fps;
        // Apply the configured noise function to frame interval
        if (m_addFrInterNoise != NULL) {
            secsToNextFrame = m_addFrInterNoise(secsToNextFrame);
        }
        assert(secsToNextFrame >= 0.);

        m_currentPacketOrFrame.first.resize(static_cast<unsigned long>(frameBytes), 0);
        m_currentPacketOrFrame.second = secsToNextFrame;
    }


    ShapedPacketizer::ShapedPacketizer(Codec *innerCodec, unsigned long payloadSize, unsigned int perPacketOverhead) :
        Packetizer(payloadSize), m_innerCodec(innerCodec), m_overhead(perPacketOverhead), m_bytesToSend(0, 0),
        m_secsToNextFrame(0.), m_lastOverheadFactor(double(perPacketOverhead) / double(payloadSize)) {

        assert(innerCodec != NULL);
        nextPacketOrFrame(); // Read first frame
        assert(isValid());
    }

    ShapedPacketizer::~ShapedPacketizer() {}

    bool ShapedPacketizer::isValid() const { return Codec::isValid() && bool(m_innerCodec.get()); }

    void ShapedPacketizer::nextPacketOrFrame() {
        if (m_bytesToSend.size() == 0) {
            assert(std::abs(m_secsToNextFrame) < EPSILON);

            Codec &codec = *m_innerCodec;
            m_innerCodec->setTargetRate(static_cast<float>(m_targetRate / (1. + m_lastOverheadFactor)));
            ++codec; // Advance codec to next frame
            m_bytesToSend = codec->first;
            m_secsToNextFrame += codec->second;

            const double packetsToSend = std::ceil(double(m_bytesToSend.size()) / double(m_payloadSize));
            assert(m_bytesToSend.size() > 0);
            m_lastOverheadFactor = double(m_overhead) * packetsToSend / double(m_bytesToSend.size());
        }

        assert(m_bytesToSend.size() > 0);
        assert(m_secsToNextFrame >= 0);

        // m_payloadSize is interpreted here as "max payload size"
        const unsigned long payloadSize = std::min<unsigned long>(m_payloadSize, m_bytesToSend.size());
        const double packetsToSend = std::ceil(double(m_bytesToSend.size()) / double(m_payloadSize));
        assert(packetsToSend >= 1.);
        const double secsToNextPacket = m_secsToNextFrame / packetsToSend;

        // copy the first part of the vector
        m_currentPacketOrFrame.first =
                std::vector<uint8_t>(m_bytesToSend.begin(), m_bytesToSend.begin() + static_cast<long>(payloadSize));
        m_currentPacketOrFrame.second = secsToNextPacket;

        // remove the first part of the vector
        m_bytesToSend =
                std::vector<uint8_t>(m_bytesToSend.begin() + static_cast<long>(payloadSize), m_bytesToSend.end());
        m_secsToNextFrame -= secsToNextPacket;
    }


    StatisticsCodec::StatisticsCodec(double fps, float maxUpdateRatio, double updateInterval, float bigChangeRatio,
                                     unsigned int transientLength, unsigned long iFrameSize,
                                     AddNoiseFunc addFrSizeNoise, AddNoiseFunc addFrInterNoise) :
        CodecWithFps(fps, addFrSizeNoise, addFrInterNoise), m_maxUpdateRatio(maxUpdateRatio),
        m_updateInterval(updateInterval), m_bigChangeRatio(bigChangeRatio), m_transientLength(transientLength),
        m_iFrameSize(iFrameSize), m_timeToUpdate(0.), m_remainingBurstFrames(transientLength) { // Start with a burst
        assert(m_maxUpdateRatio > -EPSILON); // >= 0
        assert(m_updateInterval > -EPSILON); // >= 0
        assert(m_bigChangeRatio > EPSILON); // > 0
        assert(m_transientLength > 1);
        assert(m_iFrameSize > 0);
        nextPacketOrFrame(); // Read first frame
        assert(isValid());
    }

    StatisticsCodec::~StatisticsCodec() {}

    float StatisticsCodec::setTargetRate(float newRateBps) {
        if (newRateBps < EPSILON || m_timeToUpdate > EPSILON) {
            return m_targetRate;
        }

        // Will have to wait the update interval before accepting a new update
        m_timeToUpdate = m_updateInterval;

        // Big change, initiate burst
        const float changeFact = (newRateBps - m_targetRate) / m_targetRate;
        if (std::abs(changeFact) > m_bigChangeRatio) {
            m_remainingBurstFrames = m_transientLength;
            m_targetRate = newRateBps;
            return m_targetRate;
        }

        // Not big change, so clip to +/- m_maxUpdateRatio
        if (m_maxUpdateRatio > EPSILON) {
            const double upperBound = m_targetRate * (1 + m_maxUpdateRatio);
            const double lowerBound = m_targetRate * (1 - m_maxUpdateRatio);
            if (newRateBps > upperBound) {
                newRateBps = static_cast<float>(upperBound);
            } else if (newRateBps < lowerBound) {
                newRateBps = static_cast<float>(std::max(INITIAL_RATE, lowerBound));
            }
        }
        m_targetRate = newRateBps;

        return m_targetRate;
    }

    void StatisticsCodec::nextPacketOrFrame() {
        auto frameBytes = static_cast<float>(m_targetRate / (m_fps * 8.));
        if (m_remainingBurstFrames > 0) {
            assert(m_transientLength > 0);
            if (m_remainingBurstFrames == m_transientLength) { // I frame
                frameBytes = static_cast<float>(m_iFrameSize);
            } else {
                const float iFrameRatio = float(m_iFrameSize) / float(frameBytes);
                float newRatio = float(m_transientLength) - iFrameRatio;
                newRatio /= float(m_transientLength - 1);
                newRatio = std::max(.2f, newRatio);
                frameBytes *= newRatio;
            }
            --m_remainingBurstFrames;
        }

        // Apply the configured noise function to frame size
        if (m_addFrSizeNoise != NULL) {
            frameBytes = static_cast<float>(m_addFrSizeNoise(frameBytes));
        }
        assert(frameBytes > 0);

        double secsToNextFrame = 1. / m_fps;
        // Apply the configured noise function to frame interval
        if (m_addFrInterNoise != NULL) {
            secsToNextFrame = m_addFrInterNoise(secsToNextFrame);
        }
        assert(secsToNextFrame >= 0.);

        m_currentPacketOrFrame.first.resize((size_t) frameBytes, 0);
        m_currentPacketOrFrame.second = secsToNextFrame;

        m_timeToUpdate = std::max(0., m_timeToUpdate - secsToNextFrame);
    }


    SimpleContentSharingCodec::SimpleContentSharingCodec(double fps, unsigned long noChangeMaxSize, float bigFrameProb,
                                                         float bigFrameRatioMin, float bigFrameRatioMax) :
        CodecWithFps(fps, NULL, NULL), m_noChangeMaxSize(noChangeMaxSize), m_bigFrameProb(bigFrameProb),
        m_bigFrameRatioMin(bigFrameRatioMin), m_bigFrameRatioMax(bigFrameRatioMax), m_first(true) {
        assert(m_noChangeMaxSize > 0);
        assert(m_bigFrameProb > -EPSILON); // >= 0%
        assert(m_bigFrameProb <= 1.); // <= 100%
        assert(m_bigFrameRatioMin > -EPSILON); // >= 0
        assert(m_bigFrameRatioMax > -EPSILON); // >= 0
        nextPacketOrFrame(); // Read first frame
        assert(isValid());
    }

    SimpleContentSharingCodec::~SimpleContentSharingCodec() {}

    void SimpleContentSharingCodec::nextPacketOrFrame() {
        float frameBytes = m_targetRate / (m_fps * 8.f);

        // Cap bytes to maximum small packet size
        frameBytes = std::min<float>(frameBytes, static_cast<float>(m_noChangeMaxSize));

        // Time for a big frame?
        if (m_first != 0 || uniform(0., 1.) < m_bigFrameProb) {
            m_first = false;
            frameBytes *= static_cast<float>(uniform(m_bigFrameRatioMin, m_bigFrameRatioMax));
        }

        // Should have at least 1 byte to send
        frameBytes = std::max(1.f, frameBytes);

        const double secsToNextFrame = 1. / m_fps;

        m_currentPacketOrFrame.first.resize((size_t) frameBytes, 0);
        m_currentPacketOrFrame.second = secsToNextFrame;
    }

    SyntheticVideoEncoder::SyntheticVideoEncoder(int target_fps) {
        if (target_fps <= 0) {
            target_fps = 60;
        }
        m_codec = new StatisticsCodec(target_fps);
    };
    SyntheticVideoEncoder::~SyntheticVideoEncoder() = default;

    int SyntheticVideoEncoder::InitEncode(const webrtc::VideoCodec* codec_settings, const VideoEncoder::Settings&) {
        std::cout << "Initializing synthetic encoder" << std::endl;
        m_timestamp = 0;
        m_min_bitrate_bps = codec_settings->minBitrate * 1000;
        m_max_bitrate_bps = codec_settings->maxBitrate * 1000;
        m_codec->setTargetRate(static_cast<float>(codec_settings->startBitrate * 1000));
        std::cout << "Encoder configured" << std::endl;
        return 0;
    }

    int32_t SyntheticVideoEncoder::RegisterEncodeCompleteCallback(webrtc::EncodedImageCallback* callback) {
        std::cout << "Updated encoder callback" << std::endl;
        m_callback = callback;
        return 0;
    }

    int32_t SyntheticVideoEncoder::Release() {
        m_callback = nullptr;
        return 0;
    }

    int32_t SyntheticVideoEncoder::Encode(const webrtc::VideoFrame& input_image,
                                      const std::vector<webrtc::VideoFrameType>*) {
        ++*m_codec;
        const auto &[enc_data, time_until_next_frame] = **m_codec;

        webrtc::EncodedImage encoded_image;
        encoded_image.timing_.encode_start_ms = input_image.render_time_ms();
        encoded_image.timing_.encode_start_ms = input_image.render_time_ms() + 1;
        encoded_image.SetRtpTimestamp(input_image.rtp_timestamp());
        encoded_image.SetPresentationTimestamp(input_image.presentation_timestamp());
        encoded_image.capture_time_ms_ = input_image.render_time_ms();
        encoded_image.SetEncodedData(webrtc::EncodedImageBuffer::Create(enc_data.data(), enc_data.size()));
        encoded_image._encodedWidth = 1920;
        encoded_image._encodedHeight = 1080;
        encoded_image._frameType = webrtc::VideoFrameType::kVideoFrameDelta;
        if (static_cast<double>(enc_data.size()) > 4.1 * 1024 || first_frame_) {
            encoded_image._frameType = webrtc::VideoFrameType::kVideoFrameKey;
            first_frame_ = false;
        }
        encoded_image.qp_ = 2;
        encoded_image.rotation_ = input_image.rotation();
        encoded_image.content_type_ = webrtc::VideoContentType::UNSPECIFIED;
        encoded_image.timing_.flags = webrtc::VideoSendTiming::kInvalid;
        encoded_image.SetSpatialIndex(0);
        encoded_image.SetTemporalIndex(0);

        if (m_callback) {
            webrtc::EncodedImageCallback::Result res = m_callback->OnEncodedImage(encoded_image, nullptr);
            if (res.error != webrtc::EncodedImageCallback::Result::OK) {
                return -1;
            }
        }
        return 0;
    }

    void SyntheticVideoEncoder::SetRates(const RateControlParameters& parameters) {
        if (m_codec) {
            auto target_bitrate = parameters.target_bitrate.get_sum_bps();
            if (target_bitrate > m_max_bitrate_bps) {
                target_bitrate = m_max_bitrate_bps;
            } else if (target_bitrate < m_min_bitrate_bps) {
                target_bitrate = m_min_bitrate_bps;
            }
            m_codec->setTargetRate(static_cast<float>(target_bitrate));
        }
    }

    webrtc::VideoEncoder::EncoderInfo SyntheticVideoEncoder::GetEncoderInfo() const {
        EncoderInfo info;
        info.supports_native_handle = false;
        info.implementation_name = "SyntheticVideoEncoder";
        info.has_trusted_rate_controller = true;
        return info;
    }


} // namespace syncodecs
