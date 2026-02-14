#ifndef FAKE_TRACK_SOURCE_H
#define FAKE_TRACK_SOURCE_H
#include <media/base/adapted_video_track_source.h>
#include <utility>

enum FakeVideoSourceType {
    BLACK,
    RANDOM_NOISE,
    FFMPEG
};


class FakeVideoSource : public webrtc::AdaptedVideoTrackSource{
public:
    explicit FakeVideoSource(FakeVideoSourceType source_type, std::string ffmpeg_source_file) : source_type_(source_type), ffmpeg_source_file_(std::move(ffmpeg_source_file)) {}
    void StartSource(int output_fps);
    void StopSource();

    void OnFrameCaptured(const webrtc::VideoFrame& frame) {
        OnFrame(frame);
    }

    SourceState state() const override {
        return kLive;
    }
    bool remote() const override {
        return false;
    }
    bool is_screencast() const override {
        return false;
    }
    std::optional<bool> needs_denoising() const override {
        return false;
    }
private:
    FakeVideoSourceType source_type_ = BLACK;
    std::string ffmpeg_source_file_;
    bool is_stopping_ = false;
};

#endif //FAKE_TRACK_SOURCE_H
