#ifndef H264_ONLY_FACTORY_H
#define H264_ONLY_FACTORY_H

#include "api/video_codecs/video_encoder_factory.h"
#include "api/video_codecs/video_decoder_factory.h"
#include "modules/video_coding/codecs/h264/include/h264.h"

class H264OnlyVideoEncoderFactory : public webrtc::VideoEncoderFactory {
public:
    H264OnlyVideoEncoderFactory() = default;

    std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
        // Only return H.264 codecs
        return webrtc::SupportedH264Codecs(true);
    }

    std::unique_ptr<webrtc::VideoEncoder> Create(
        const webrtc::Environment& env,
        const webrtc::SdpVideoFormat& format) override {
        // Only create encoders for H.264 formats
        if (format.name == "H264") {
            auto settings = webrtc::H264EncoderSettings::Parse(format);
            return webrtc::CreateH264Encoder(env, settings);
        }
        return nullptr;
    }
};

class H264OnlyVideoDecoderFactory : public webrtc::VideoDecoderFactory {
public:
    H264OnlyVideoDecoderFactory() = default;

    std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
        // Only return H.264 codecs
        return webrtc::SupportedH264Codecs(true);
    }

    std::unique_ptr<webrtc::VideoDecoder> Create(
        const webrtc::Environment& /* env */,
        const webrtc::SdpVideoFormat& format) override {
        // Only create decoders for H.264 formats
        if (format.name == "H264") {
            return webrtc::H264Decoder::Create();
        }
        return nullptr;
    }

    CodecSupport QueryCodecSupport(
        const webrtc::SdpVideoFormat& format,
        bool /* reference_scaling */) const override {
        if (format.name == "H264") {
            return {true, true};
        }
        return {false, false};
    }
};

#endif // H264_ONLY_FACTORY_H
