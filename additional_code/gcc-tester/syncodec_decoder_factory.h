//
// Created by yannis on 6/21/25.
//

#ifndef SYNCODEC_DECODER_FACTORY_H
#define SYNCODEC_DECODER_FACTORY_H
#include <api/video/i420_buffer.h>

namespace syncodecs {

    class SynCodecsVideoDecoder : public webrtc::VideoDecoder {
    public:
        struct DecoderInfo {
            std::string implementation_name = "fake_decoder";
        };
        bool Configure(const Settings&) override { return true; }
        int32_t RegisterDecodeCompleteCallback(webrtc::DecodedImageCallback * callback) override {
            callback_ = callback;
            return 0;
        }
        int32_t Release() override {
            return 0;
        }
        int32_t Decode(const webrtc::EncodedImage & enc_img, int64_t) override {
            if (!callback_) {
                return -1;
            }

            auto buffer = webrtc::I420Buffer::Create(1920, 1080);
            buffer->InitializeData();

            webrtc::VideoFrame decoded_image = webrtc::VideoFrame::Builder()
                .set_video_frame_buffer(buffer)
                .set_rtp_timestamp(enc_img.RtpTimestamp())
                .set_ntp_time_ms(enc_img.ntp_time_ms_)
                .set_color_space(enc_img.ColorSpace())
                .build();

            callback_->Decoded(decoded_image);
            return 0;
        }
        int32_t Decode(const webrtc::EncodedImage& ei, bool, int64_t ts) override {
            return Decode(ei, ts);
        }
    private:
        webrtc::DecodedImageCallback* callback_ = nullptr;
    };

    class SynCodecsVideoDecoderFactory final : public webrtc::VideoDecoderFactory {
    public:
        SynCodecsVideoDecoderFactory() = default;

        [[nodiscard]] std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
            return {
                webrtc::SdpVideoFormat("syncodec", {})
            };
        }

        std::unique_ptr<webrtc::VideoDecoder> Create(const webrtc::Environment&, const webrtc::SdpVideoFormat&) override {
            new SynCodecsVideoDecoder();
            return std::make_unique<SynCodecsVideoDecoder>();
        }

        [[nodiscard]] CodecSupport QueryCodecSupport(const webrtc::SdpVideoFormat & format, bool) const override {
            CodecSupport support = {
                format.name == "syncodec",
                true
            };
            return support;
        }
    };
}

#endif //SYNCODEC_DECODER_FACTORY_H
