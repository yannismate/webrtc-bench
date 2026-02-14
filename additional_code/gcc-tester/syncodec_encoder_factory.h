//
// Created by yannis on 6/21/25.
//

#ifndef SYNCODEC_ENCODER_FACTORY_H
#define SYNCODEC_ENCODER_FACTORY_H

#include "syncodecs.h"

namespace syncodecs {

    class SynCodecsVideoEncoderFactory final : public webrtc::VideoEncoderFactory {
    public:
        explicit SynCodecsVideoEncoderFactory(int target_fps) : target_fps_(target_fps) {}

        [[nodiscard]] std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
            return {
                webrtc::SdpVideoFormat("syncodec", {})
            };
        }

        std::unique_ptr<webrtc::VideoEncoder> Create(const webrtc::Environment&,
                                             const webrtc::SdpVideoFormat&) override {
            return std::make_unique<SyntheticVideoEncoder>(target_fps_);
        }
    private:
        int target_fps_ = 60;
    };
}

#endif //SYNCODEC_ENCODER_FACTORY_H
